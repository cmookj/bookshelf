"""
bookshelf/merge.py

Merge a secondary Bookshelf database + file store into the primary one.

Duplicate-detection strategy (in priority order):
  1. File hash (SHA-256)     – exact content match → definitive duplicate
  2. Weighted fuzzy score    – title (50%), authors (25%), description (25%)
     using difflib.SequenceMatcher (no extra dependencies)

Behaviour by score:
  score >= high_threshold  → auto-skip, write to report
  score >= low_threshold   → ask user interactively
  score <  low_threshold   → treat as new, migrate automatically

FTS index:
  The primary DB's FTS5 table (bookshelf_fts) is kept in sync automatically
  via the INSERT / UPDATE triggers set up by bookshelf.fuzzy.setup_fts_triggers.
  No manual FTS work is needed here.

Usage (standalone):
    python -m bookshelf.merge \\
        --primary-db    ~/bookshelf/_database.db \\
        --primary-files ~/bookshelf/files \\
        --secondary-db  ~/other/_database.db \\
        --secondary-files ~/other/files \\
        [--high-threshold 0.85] \\
        [--low-threshold  0.50] \\
        [--report merge_report.txt] \\
        [--dry-run]

Wiring into existing CLI (bookshelf/__main__.py or wherever main() lives):
    elif sys.argv[1] == "merge":
        from bookshelf.merge import run_merge_cli
        run_merge_cli(sys.argv[2:])
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from enum import Enum, auto
from typing import List, Optional

import bookshelf.util as util

# pypdf is optional.  When present, PDF text extraction is used to detect
# annotated copies of the same document (whose binary hashes differ).
try:
    import pypdf as _pypdf
    _PYPDF_AVAILABLE = True
except ImportError:
    _pypdf = None           # type: ignore[assignment]
    _PYPDF_AVAILABLE = False


# ---------------------------------------------------------------------------
# Constants & tuneable defaults
# ---------------------------------------------------------------------------

HIGH_THRESHOLD_DEFAULT = 0.85   # auto-skip (confident duplicate)
LOW_THRESHOLD_DEFAULT  = 0.50   # ask user  (uncertain)

# Minimum SequenceMatcher ratio between two PDFs' extracted text to consider
# them the "same document" even when their binary hashes differ (annotations).
PDF_TEXT_THRESHOLD = 0.95

# Field weights for fuzzy score – must sum to 1.0
W_TITLE       = 0.50
W_AUTHORS     = 0.25
W_DESCRIPTION = 0.25

# Icons (matches the Nerd-Font glyphs used throughout the main app)
ICON_INFO = "\uf02d"
ICON_WARN = "\uea6c"
ICON_ERR  = "\uea87"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class MergeAction(Enum):
    MIGRATED  = auto()   # new to primary – copied from secondary
    SKIPPED   = auto()   # duplicate – not copied
    REPLACED  = auto()   # primary record metadata overwritten with secondary's
    KEPT_BOTH = auto()   # both records retained (secondary migrated as-is)


@dataclass
class Record:
    id:          str
    filename:    str
    title:       str
    authors:     str
    category:    str
    keywords:    str
    description: str


@dataclass
class ReportEntry:
    action:       MergeAction
    secondary_id: str
    primary_id:   Optional[str]
    title:        str
    score:        float
    reason:       str


@dataclass
class MergeReport:
    started_at: str = field(
        default_factory=lambda: datetime.now().isoformat(sep=" ", timespec="seconds")
    )
    entries:  List[ReportEntry] = field(default_factory=list)
    dry_run:  bool = False

    def add(self, entry: ReportEntry):
        self.entries.append(entry)

    def summary(self) -> str:
        counts = {a: 0 for a in MergeAction}
        for e in self.entries:
            counts[e.action] += 1
        lines = [
            "",
            "=" * 72,
            f"  Bookshelf Merge Report  -  {self.started_at}",
            f"  Dry-run: {self.dry_run}",
            "=" * 72,
            f"  Migrated  (new to primary)       : {counts[MergeAction.MIGRATED]}",
            f"  Skipped   (confident duplicate)  : {counts[MergeAction.SKIPPED]}",
            f"  Replaced  (primary overwritten)  : {counts[MergeAction.REPLACED]}",
            f"  Kept both (both records retained): {counts[MergeAction.KEPT_BOTH]}",
            f"  Total processed                  : {len(self.entries)}",
            "=" * 72,
        ]
        return "\n".join(lines)

    def detail_lines(self) -> List[str]:
        lines = []
        for e in self.entries:
            pri = e.primary_id[:8] if e.primary_id else "N/A     "
            lines.append(
                f"[{e.action.name:<10}]  score={e.score:.2f}"
                f"  sec={e.secondary_id[:8]}  pri={pri}"
                f"  title={e.title[:48]!r}"
                f"  reason={e.reason}"
            )
        return lines

    def write(self, path: str):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.summary())
            fh.write("\n\nDetailed log:\n")
            fh.write("\n".join(self.detail_lines()))
            fh.write("\n")


# ---------------------------------------------------------------------------
# Similarity helpers
# ---------------------------------------------------------------------------

def _sha256(path: str) -> Optional[str]:
    """Return hex SHA-256 of *path*, or None if the file does not exist."""
    if not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65_536), b""):
            h.update(chunk)
    return h.hexdigest()


def _fuzzy(a: str, b: str) -> float:
    """0.0-1.0 similarity between two strings (case-insensitive)."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


# ---------------------------------------------------------------------------
# Name normalisation
# ---------------------------------------------------------------------------
# Supported name formats (comma = author separator in bookshelf, NOT Last/First):
#   "Donald Knuth"       – first last
#   "Donald E. Knuth"    – first middle-initial last
#   "D. Knuth"           – initial last
#   "D.E. Knuth"         – two initials last
#
# Note: "Knuth, Donald E." (Last, First) is handled by _split_authors before
# any individual name reaches _parse_name.  _parse_name itself does NOT split
# on commas to avoid confusing the author-separator comma with a name comma.
# ---------------------------------------------------------------------------

import re as _re
import string as _string


@dataclass(frozen=True)
class _ParsedName:
    last:       str        # lower-cased, punctuation stripped
    initials:   frozenset  # single-character lower-cased initials (from ANY given token)
    full_given: frozenset  # lower-cased full given-name tokens (multi-char, not just initial)


def _parse_name(raw: str) -> _ParsedName:
    """
    Parse one person's name string (in "First [Middle] Last" format) into
    a _ParsedName.  The last whitespace-separated token is the surname; all
    preceding tokens are given-name / initial tokens.

    A token is classified as an "initial" if, after stripping punctuation,
    it reduces to a single letter.  A token like "D.E." (two letters separated
    by dots) contributes both letters as initials.  A multi-letter token with
    no dots (e.g. "Donald") is a full given name.

    Examples:
      "Donald Knuth"    → last="knuth", initials={"d"},      full_given={"donald"}
      "Donald E. Knuth" → last="knuth", initials={"d","e"},  full_given={"donald"}
      "D. Knuth"        → last="knuth", initials={"d"},      full_given={}
      "D.E. Knuth"      → last="knuth", initials={"d","e"},  full_given={}
    """
    raw = raw.strip()
    if not raw:
        return _ParsedName(last="", initials=frozenset(), full_given=frozenset())

    tokens = raw.split()
    last_clean = tokens[-1].lower().translate(
        str.maketrans("", "", _string.punctuation)
    ).strip()

    initials:   set[str] = set()
    full_given: set[str] = set()

    for token in tokens[:-1]:
        stripped = token.strip(_string.punctuation)
        if not stripped:
            continue
        if len(stripped) == 1:
            # Single letter: plain initial — e.g. "E" from "E."
            initials.add(stripped.lower())
        elif "." in token:
            # Token contains dots: treat every letter as a separate initial
            # Covers "D.E.", "J.R.R.", etc.
            for ch in _re.findall(r"[A-Za-z]", token):
                initials.add(ch.lower())
        else:
            # Multi-letter token with no dots: full given name
            full_given.add(stripped.lower())
            initials.add(stripped[0].lower())  # contribute first letter as initial too

    return _ParsedName(last=last_clean,
                       initials=frozenset(initials),
                       full_given=frozenset(full_given))


def _names_match(a: str, b: str) -> bool:
    """
    Return True if two name strings plausibly refer to the same person.

    Rules applied in order:
      1. Last names must match exactly (case-insensitive, punctuation stripped).
      2. When BOTH sides carry at least one full given-name token, they must
         share at least one in common.
         • "Donald Knuth" vs "David Knuth" → {"donald"} ∩ {"david"} = ∅ → False
         • "Donald Knuth" vs "Donald E. Knuth" → {"donald"} ∩ {"donald"} ≠ ∅ → ok
      3. Initial sets must not contradict each other: the smaller set must be
         a subset of the larger.  A side with no initials at all (bare last
         name) matches anything with the same last name.
    """
    pa, pb = _parse_name(a), _parse_name(b)
    if not pa.last or not pb.last:
        return False
    if pa.last != pb.last:
        return False
    # Rule 2: full given-name conflict
    if pa.full_given and pb.full_given:
        if not (pa.full_given & pb.full_given):
            return False
    # Rule 3: initial consistency (bare last name has no initials → always ok)
    if not pa.initials or not pb.initials:
        return True
    return pa.initials <= pb.initials or pb.initials <= pa.initials


def _split_authors(s: str) -> list[str]:
    """
    Split a comma-separated author string into individual name strings.

    Commas serve double duty in this system: they separate multiple authors
    AND they appear within a single name in "Last, First [M.]" format.
    The heuristic below re-joins such pairs before returning.

    A pair (cur, nxt) is treated as one "Last, First" name when:
      • cur is a single word with no dots or spaces  (likely bare last name)
      • nxt contains a dot, a space, or is a single letter (likely given part)

    After joining, the result is converted to "First Last" order so that
    _parse_name (which assumes "First Last" layout) works correctly.

    Examples:
      "Donald Knuth, Alan Turing"      → ["Donald Knuth", "Alan Turing"]
      "Knuth, Donald E., Turing, Alan" → ["Donald E. Knuth", "Alan Turing"]
      "LeCun, Bengio"                  → ["LeCun", "Bengio"]  (ambiguous → two authors)
    """
    if not s.strip():
        return []
    parts = [p.strip() for p in s.split(",") if p.strip()]
    if len(parts) == 1:
        return parts

    def _is_given(seg: str) -> bool:
        """True when seg looks like a given-name fragment, not a bare last name."""
        return "." in seg or " " in seg or (len(seg) == 1 and seg.isalpha())

    result: list[str] = []
    i = 0
    while i < len(parts):
        cur = parts[i]
        nxt = parts[i + 1] if i + 1 < len(parts) else None
        if nxt is not None and "." not in cur and " " not in cur and _is_given(nxt):
            # Detected "Last, Given" pair → convert to "Given Last" for _parse_name
            result.append(nxt.strip() + " " + cur.strip())
            i += 2
        else:
            result.append(cur)
            i += 1
    return result


def _author_similarity(a: str, b: str) -> float:
    """
    Similarity score (0.0–1.0) for two comma-separated author strings.

    Algorithm: treat each side as a set of parsed names and compute the
    Jaccard-style overlap — matched_pairs / max(count_a, count_b).
    Two names are "matched" if _names_match() returns True.

    Falls back to plain character-level fuzzy ratio when either side is
    unparseable (e.g. an organisation name).
    """
    authors_a = _split_authors(a)
    authors_b = _split_authors(b)

    if not authors_a and not authors_b:
        return 1.0
    if not authors_a or not authors_b:
        return 0.0

    # Greedy matching: for each name in A find the first unmatched name in B
    used = [False] * len(authors_b)
    matched = 0
    for na in authors_a:
        for j, nb in enumerate(authors_b):
            if not used[j] and _names_match(na, nb):
                matched += 1
                used[j] = True
                break

    score = matched / max(len(authors_a), len(authors_b))

    # If no name-level match at all, fall back to string similarity so that
    # organisation names and unusual formats still get a reasonable score.
    if score == 0.0:
        score = _fuzzy(a, b)

    return score


def weighted_similarity(sec: Record, pri: Record) -> float:
    """Weighted metadata similarity, ignoring file content."""
    return (
        W_TITLE       * _fuzzy(sec.title,              pri.title)
        + W_AUTHORS     * _author_similarity(sec.authors, pri.authors)
        + W_DESCRIPTION * _fuzzy(sec.description,        pri.description)
    )


def _metadata_identical(a: Record, b: Record) -> bool:
    """True when every user-visible metadata field is exactly equal."""
    return (
        a.title       == b.title
        and a.authors     == b.authors
        and a.category    == b.category
        and a.keywords    == b.keywords
        and a.description == b.description
    )


# ---------------------------------------------------------------------------
# PDF content similarity  (requires pypdf; graceful fallback otherwise)
# ---------------------------------------------------------------------------

def _pdf_text(path: str) -> Optional[str]:
    """
    Extract all text from a PDF and return it as a single normalised string.
    Returns None if pypdf is not installed, the file is not a PDF, or
    extraction fails for any reason.
    """
    if not _PYPDF_AVAILABLE:
        return None
    if not path.lower().endswith(".pdf"):
        return None
    try:
        reader = _pypdf.PdfReader(path)
        pages  = (page.extract_text() or "" for page in reader.pages)
        text   = " ".join(pages)
        return " ".join(text.split())   # collapse all whitespace
    except Exception:
        return None


def _same_pdf_content(path_a: str, path_b: str) -> bool:
    """
    Return True when two PDF files contain the same text content at or above
    PDF_TEXT_THRESHOLD similarity, even if their binary representations differ
    (e.g. one has annotations, highlights, or a re-saved cross-reference table).

    Returns False whenever pypdf is unavailable or either file cannot be read.
    """
    text_a = _pdf_text(path_a)
    text_b = _pdf_text(path_b)
    if text_a is None or text_b is None:
        return False
    # Both empty (e.g. scanned image PDFs with no text layer)
    if not text_a and not text_b:
        return False   # can't confirm — don't assume they are the same
    if not text_a or not text_b:
        return False
    ratio = SequenceMatcher(None, text_a, text_b).ratio()
    return ratio >= PDF_TEXT_THRESHOLD


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _load_records(db_path: str, table: str) -> List[Record]:
    conn = sqlite3.connect(db_path)
    cur  = conn.cursor()
    cur.execute(
        f"SELECT id, filename, title, authors, category, keywords, description"
        f" FROM {table}"
    )
    rows = cur.fetchall()
    conn.close()
    return [Record(*row) for row in rows]


def _insert(conn: sqlite3.Connection, table: str, rec: Record):
    """
    Insert *rec* into *table*.
    The bookshelf_ai trigger (set up by bookshelf.fuzzy.setup_fts_triggers)
    will automatically keep the FTS index in sync.
    """
    conn.execute(
        f"INSERT INTO {table}"
        f" (id, filename, title, authors, category, keywords, description)"
        f" VALUES (?, ?, ?, ?, ?, ?, ?)",
        (rec.id, rec.filename, rec.title, rec.authors,
         rec.category, rec.keywords, rec.description),
    )
    conn.commit()


def _update(conn: sqlite3.Connection, table: str, rec: Record):
    """
    Overwrite metadata for an existing record (identified by rec.id).
    The bookshelf_au trigger keeps the FTS index in sync automatically.
    """
    conn.execute(
        f"UPDATE {table}"
        f" SET filename=?, title=?, authors=?, category=?, keywords=?, description=?"
        f" WHERE id=?",
        (rec.filename, rec.title, rec.authors,
         rec.category, rec.keywords, rec.description, rec.id),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# File-path helpers  (mirrors Bookshelf's UUID-based layout)
# ---------------------------------------------------------------------------

def _file_path(files_dir: str, filename: str) -> str:
    """<files_dir>/<first-2-chars-of-filename>/<filename>"""
    return os.path.join(files_dir, filename[:2], filename)


def _ensure_subdir(files_dir: str, filename: str):
    os.makedirs(os.path.join(files_dir, filename[:2]), exist_ok=True)


# ---------------------------------------------------------------------------
# Interactive duplicate-resolution prompt
# ---------------------------------------------------------------------------

def _ask_user(sec: Record, pri: Record, score: float) -> str:
    """
    Present a side-by-side comparison and ask the user what to do.

    Returns one of:
      's'  skip  - do NOT migrate; leave primary unchanged
      'b'  both  - migrate secondary as a new independent entry
      'm'  merge - choose the value to keep for each field individually
    """
    sep = "-" * 68
    print(f"\n{util.make_bold_red(sep)}")
    print(util.make_bold_red(
        f"  {ICON_WARN}  Potential duplicate  (similarity: {score:.0%})"
    ))
    print(util.make_bold_red(sep))

    # ── Field-by-field comparison table ───────────────────────────────
    fields = [
        ("Title",    sec.title,       pri.title),
        ("Authors",  sec.authors,     pri.authors),
        ("Category", sec.category,    pri.category),
        ("Keywords", sec.keywords,    pri.keywords),
    ]
    col_w = 30   # truncate each value to this width for the summary table

    print(f"\n  {'Field':<10}  {'SECONDARY':<{col_w}}  {'PRIMARY':<{col_w}}")
    print(f"  {'-'*10}  {'-'*col_w}  {'-'*col_w}")
    for name, sv, pv in fields:
        sv_short = (sv[:col_w - 1] + "…") if len(sv) > col_w else sv
        pv_short = (pv[:col_w - 1] + "…") if len(pv) > col_w else pv
        marker = "  " if sv.strip() == pv.strip() else "* "
        print(f"  {marker}{name:<8}  {sv_short:<{col_w}}  {pv_short:<{col_w}}")

    # Description shown in full on separate lines because it can be long
    print(f"\n  Description")
    print(f"  {'SECONDARY':─<{col_w*2+4}}")
    print(f"  {sec.description or '(empty)'}")
    print(f"  {'PRIMARY':─<{col_w*2+4}}")
    print(f"  {pri.description or '(empty)'}")

    print(f"\n{sep}")
    print("  (s) Skip   - keep primary as-is, discard secondary")
    print("  (b) Both   - migrate secondary as a separate entry")
    print("  (m) Merge  - choose which value to keep for each field")
    print(sep)

    return util.closed_ended_question(
        msg=f"  {ICON_INFO}  Your choice",
        options=["s", "b", "m"],
    )


def _csv_merge(pri_val: str, sec_val: str, is_authors: bool = False) -> str:
    """
    Union of two comma-separated value strings, preserving the order of the
    primary items first, then appending any items from secondary that are not
    already present.

    Parameters
    ----------
    is_authors
        When True, uses _split_authors() + _names_match() for splitting and
        deduplication so that "Donald Knuth" and "D. Knuth" are treated as
        the same person.  When False (default), uses plain comma-split and
        case-insensitive string comparison (suitable for keywords).
    """
    if is_authors:
        pri_items = _split_authors(pri_val)
        sec_items = _split_authors(sec_val)
    else:
        pri_items = [t.strip() for t in pri_val.split(",") if t.strip()]
        sec_items = [t.strip() for t in sec_val.split(",") if t.strip()]

    merged = list(pri_items)
    for sec_item in sec_items:
        already_present = any(
            (_names_match(sec_item, p) if is_authors else sec_item.lower() == p.lower())
            for p in merged
        )
        if not already_present:
            merged.append(sec_item)

    return ", ".join(merged)


def _pick(field_name: str, sec_val: str, pri_val: str,
          allow_csv_merge: bool = False,
          is_authors:      bool = False,
          allow_write_new: bool = False) -> str:
    """
    Show both values for a single field and return the one the user picks.

    Parameters
    ----------
    allow_csv_merge
        When True (Authors and Keywords), offer '(m) merge' which unions both
        comma-separated lists via _csv_merge().
    is_authors
        Passed through to _csv_merge() so that the author merge preview and
        the actual merge use name-aware deduplication.
    allow_write_new
        When True (Description), offer '(w) write new' so the user can type
        a replacement from scratch using util.string_input().

    If both values are already identical the prompt is skipped entirely.
    """
    if sec_val.strip() == pri_val.strip():
        return pri_val   # identical – nothing to decide

    sep = "  " + "·" * 64
    print(f"\n  ┌─ {field_name}")
    print(f"  │  (p) PRIMARY   : {pri_val}")
    print(f"  │  (s) SECONDARY : {sec_val}")

    options = ["p", "s"]
    hints   = ["(p)rimary", "(s)econdary"]

    if allow_csv_merge:
        preview = _csv_merge(pri_val, sec_val, is_authors=is_authors)
        print(f"  │  (m) MERGED    : {preview}")
        options.append("m")
        hints.append("(m)erge")

    if allow_write_new:
        print(f"  │  (w) WRITE NEW")
        options.append("w")
        hints.append("(w)rite new")

    print(sep)
    choice = util.closed_ended_question(
        msg=f"  └─ {' / '.join(hints)} for {field_name}?",
        options=options,
    )

    if choice == "p":
        return pri_val
    if choice == "s":
        return sec_val
    if choice == "m":
        return _csv_merge(pri_val, sec_val, is_authors=is_authors)
    # choice == "w"
    return util.string_input(f"New {field_name}", pri_val)


def _merge_fields(sec: Record, pri: Record) -> Record:
    """
    Walk through every metadata field and let the user pick the value to
    keep in the primary record.  Returns a new Record with the chosen values
    (primary's id and filename are always preserved).

    For Authors and Keywords the user is additionally offered '(m) merge',
    which unions both comma-separated lists without duplicates.
    """
    sep = "=" * 68
    print(f"\n{sep}")
    print(f"  {ICON_INFO}  Field-by-field merge  –  choose value to keep for each differing field")
    print(f"  Identical fields are kept automatically.")
    print(sep)

    title       = _pick("Title",       sec.title,       pri.title)
    authors     = _pick("Authors",     sec.authors,     pri.authors,    allow_csv_merge=True, is_authors=True)
    category    = _pick("Category",    sec.category,    pri.category)
    keywords    = _pick("Keywords",    sec.keywords,    pri.keywords,   allow_csv_merge=True)
    description = _pick("Description", sec.description, pri.description, allow_write_new=True)

    print(f"\n  {ICON_INFO}  Merged result:")
    print(f"    Title   : {title}")
    print(f"    Authors : {authors}")
    print(f"    Category: {category}")
    print(f"    Keywords: {keywords}")
    print(f"    Desc    : {description[:120]}")

    return Record(
        id=pri.id,
        filename=pri.filename,   # always keep the primary's physical file
        title=title,
        authors=authors,
        category=category,
        keywords=keywords,
        description=description,
    )


# ---------------------------------------------------------------------------
# Core merge logic
# ---------------------------------------------------------------------------

def merge(
    primary_db:       str,
    primary_files:    str,
    secondary_db:     str,
    secondary_files:  str,
    table:            str   = "docs",
    high_threshold:   float = HIGH_THRESHOLD_DEFAULT,
    low_threshold:    float = LOW_THRESHOLD_DEFAULT,
    report_path:      str   = "merge_report.txt",
    dry_run:          bool  = False,
) -> MergeReport:
    """
    Merge secondary into primary.

    Parameters
    ----------
    primary_db / secondary_db
        Full paths to the respective SQLite files.
    primary_files / secondary_files
        Full paths to the respective 'files' directories.
    high_threshold
        Fuzzy score at-or-above which a match is treated as a confident
        duplicate -> auto-skipped and logged.
    low_threshold
        Fuzzy score at-or-above which the user is prompted interactively.
    report_path
        Where to write the merge report.
    dry_run
        When True, nothing is written to disk or to either database.
    """

    report = MergeReport(dry_run=dry_run)

    # ------------------------------------------------------------------
    # 1. Load records from both sides
    # ------------------------------------------------------------------
    sec_records = _load_records(secondary_db, table)
    pri_records = _load_records(primary_db,   table)

    print(f"\n  {ICON_INFO}  Secondary records : {len(sec_records)}")
    print(f"  {ICON_INFO}  Primary records   : {len(pri_records)}")

    if not sec_records:
        print(f"\n  {ICON_INFO}  Nothing to merge.")
        report.write(report_path)
        return report

    # ------------------------------------------------------------------
    # 2. Build a hash -> Record map for every primary file
    # ------------------------------------------------------------------
    print(f"\n  {ICON_INFO}  Hashing primary files ...")
    pri_hash_map: dict[str, Record] = {}
    for rec in pri_records:
        h = _sha256(_file_path(primary_files, rec.filename))
        if h:
            pri_hash_map[h] = rec

    # ------------------------------------------------------------------
    # 3. Open the primary DB for writing
    #    Triggers (bookshelf_ai / bookshelf_au) were already created by
    #    bookshelf.fuzzy.setup_fts_triggers and will keep the FTS index
    #    up to date automatically on every INSERT or UPDATE below.
    # ------------------------------------------------------------------
    pri_conn: Optional[sqlite3.Connection] = None
    if not dry_run:
        pri_conn = sqlite3.connect(primary_db)
        pri_conn.execute("PRAGMA foreign_keys = ON;")

    # ------------------------------------------------------------------
    # 4. Process each secondary record
    # ------------------------------------------------------------------
    total = len(sec_records)
    for idx, sec in enumerate(sec_records, 1):
        label = sec.title[:60] or sec.filename
        print(f"\n  [{idx}/{total}]  {label}")

        sec_fp   = _file_path(secondary_files, sec.filename)
        sec_hash = _sha256(sec_fp)

        # ── 4a. Exact file-content match ──────────────────────────────
        # The physical file is identical, so we never need to copy it.
        # • If metadata also match  → plain duplicate, skip entirely.
        # • If metadata differ      → same file, two sets of metadata;
        #   let the user reconcile the fields in the primary record.
        if sec_hash and sec_hash in pri_hash_map:
            matched = pri_hash_map[sec_hash]
            if _metadata_identical(sec, matched):
                print(
                    f"         {ICON_INFO}  Exact file + metadata match"
                    f" -> [{matched.id[:8]}...]. Auto-skipping."
                )
                report.add(ReportEntry(
                    action=MergeAction.SKIPPED,
                    secondary_id=sec.id,
                    primary_id=matched.id,
                    title=sec.title,
                    score=1.0,
                    reason="exact SHA-256 file match and identical metadata",
                ))
            else:
                print(
                    f"         {ICON_INFO}  Exact file match but metadata differ"
                    f" -> [{matched.id[:8]}...]. Prompting for metadata merge."
                )
                merged = _merge_fields(sec, matched)
                if not dry_run and pri_conn:
                    _update(pri_conn, table, merged)
                report.add(ReportEntry(
                    action=MergeAction.REPLACED,
                    secondary_id=sec.id,
                    primary_id=matched.id,
                    title=merged.title,
                    score=1.0,
                    reason="same file, metadata merged by user",
                ))
            continue

        # ── 4b. Best fuzzy metadata match across all primary records ──
        best_score  = 0.0
        best_match: Optional[Record] = None
        for pri in pri_records:
            s = weighted_similarity(sec, pri)
            if s > best_score:
                best_score, best_match = s, pri

        # ── 4b'. Same PDF content despite different hash? ─────────────
        # Happens when one copy has annotations, highlights, or was
        # re-saved (binary differs but text is identical).
        # We only run the expensive text extraction when:
        #   • pypdf is installed
        #   • a metadata best_match was found (so we have a candidate)
        #   • both files are PDFs
        # If text matches, treat exactly like Case 2 (same file, possibly
        # different metadata) and jump straight to metadata reconciliation.
        if (
            best_match is not None
            and _PYPDF_AVAILABLE
            and sec_fp.lower().endswith(".pdf")
        ):
            pri_fp = _file_path(primary_files, best_match.filename)
            if _same_pdf_content(sec_fp, pri_fp):
                print(
                    f"         {ICON_INFO}  Same PDF text content (annotated copy?)"
                    f" -> [{best_match.id[:8]}...]. Checking metadata."
                )
                if _metadata_identical(sec, best_match):
                    print(
                        f"         {ICON_INFO}  Metadata also identical. Auto-skipping."
                    )
                    report.add(ReportEntry(
                        action=MergeAction.SKIPPED,
                        secondary_id=sec.id,
                        primary_id=best_match.id,
                        title=sec.title,
                        score=1.0,
                        reason="same PDF text content and identical metadata",
                    ))
                else:
                    print(
                        f"         {ICON_INFO}  Metadata differ. Prompting for merge."
                    )
                    merged = _merge_fields(sec, best_match)
                    if not dry_run and pri_conn:
                        _update(pri_conn, table, merged)
                    report.add(ReportEntry(
                        action=MergeAction.REPLACED,
                        secondary_id=sec.id,
                        primary_id=best_match.id,
                        title=merged.title,
                        score=1.0,
                        reason="same PDF text content, metadata merged by user",
                    ))
                continue

        # ── 4c. Very high metadata similarity but files differ ────────
        # The two records look like the same document but the physical files
        # are not identical (different versions, formats, or editions).
        # Keep both so neither copy is lost; log the decision.
        migrate_directly = False   # set True to bypass the interactive prompt
        if best_score >= high_threshold and best_match:
            print(
                f"         {ICON_INFO}  High metadata similarity ({best_score:.0%})"
                f" but different files -> keeping both."
            )
            migrate_directly = True

        # ── 4d. Ambiguous -> ask the user ─────────────────────────────
        if not migrate_directly and best_score >= low_threshold and best_match:
            choice = _ask_user(sec, best_match, best_score)

            if choice == "s":
                report.add(ReportEntry(
                    action=MergeAction.SKIPPED,
                    secondary_id=sec.id,
                    primary_id=best_match.id,
                    title=sec.title,
                    score=best_score,
                    reason="user chose skip",
                ))
                continue

            if choice == "m":
                # Field-by-field: user picks which value to keep per field.
                merged = _merge_fields(sec, best_match)
                if not dry_run and pri_conn:
                    _update(pri_conn, table, merged)
                print(
                    f"         {ICON_INFO}  Primary [{best_match.id[:8]}...]"
                    " metadata updated with merged values."
                )
                report.add(ReportEntry(
                    action=MergeAction.REPLACED,
                    secondary_id=sec.id,
                    primary_id=best_match.id,
                    title=merged.title,
                    score=best_score,
                    reason="user merged field-by-field",
                ))
                continue

            # choice == "b": fall through to migrate below

        # ── 4e. Migrate: copy file + insert DB record ─────────────────
        # Reached when:
        #   - fuzzy score is below low_threshold  (clearly a new record), OR
        #   - high metadata similarity but different files (auto keep both), OR
        #   - user chose "keep both" (b) in the interactive prompt
        #   (choices 's' and 'm' both continue'd above, so they never reach here)
        if migrate_directly:
            # high similarity, different files: auto keep both
            action = MergeAction.KEPT_BOTH
            reason = (
                f"auto keep both: high metadata similarity ({best_score:.0%})"
                " but different files"
            )
        elif best_score >= low_threshold:
            # user explicitly chose "b"
            action = MergeAction.KEPT_BOTH
            reason = "user chose keep both"
        else:
            action = MergeAction.MIGRATED
            reason = f"fuzzy score {best_score:.2f} < low threshold {low_threshold}"

        file_note = ""
        if not os.path.isfile(sec_fp):
            file_note = " (source file missing - DB record only)"
        elif not dry_run and pri_conn:
            dst_fp = _file_path(primary_files, sec.filename)

            # UUID collision: astronomically rare, but handle it cleanly
            if os.path.exists(dst_fp):
                _, ext    = os.path.splitext(sec.filename)
                new_fname = f"{uuid.uuid4()}{ext}"
                new_id    = new_fname[: -len(ext)]  # strip extension to get bare UUID
                sec = Record(
                    id=new_id,
                    filename=new_fname,
                    title=sec.title,
                    authors=sec.authors,
                    category=sec.category,
                    keywords=sec.keywords,
                    description=sec.description,
                )
                dst_fp = _file_path(primary_files, sec.filename)

            _ensure_subdir(primary_files, sec.filename)
            shutil.copy2(sec_fp, dst_fp)

        if not dry_run and pri_conn:
            _insert(pri_conn, table, sec)

        print(f"         {ICON_INFO}  Migrated -> [{sec.id[:8]}...].{file_note}")
        report.add(ReportEntry(
            action=action,
            secondary_id=sec.id,
            primary_id=None,
            title=sec.title,
            score=best_score,
            reason=reason + file_note,
        ))

    # ------------------------------------------------------------------
    # 5. Wrap up
    # ------------------------------------------------------------------
    if pri_conn:
        pri_conn.close()

    print(report.summary())
    report.write(report_path)
    print(f"\n  {ICON_INFO}  Report written -> {report_path}\n")
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bookshelf merge",
        description="Merge a secondary Bookshelf database into the primary one.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--primary-db",       required=True,
                   help="Full path to the primary SQLite DB file")
    p.add_argument("--primary-files",    required=True,
                   help="Full path to the primary 'files' directory")
    p.add_argument("--secondary-db",     required=True,
                   help="Full path to the secondary SQLite DB file")
    p.add_argument("--secondary-files",  required=True,
                   help="Full path to the secondary 'files' directory")
    p.add_argument("--table",            default="docs",
                   help="Table name used in both databases")
    p.add_argument("--high-threshold",   type=float,
                   default=HIGH_THRESHOLD_DEFAULT,
                   help="Score >= this -> auto-skip (confident duplicate)")
    p.add_argument("--low-threshold",    type=float,
                   default=LOW_THRESHOLD_DEFAULT,
                   help="Score >= this -> ask the user interactively")
    p.add_argument("--report",           default="merge_report.txt",
                   help="Path for the written merge report")
    p.add_argument("--dry-run",          action="store_true",
                   help="Simulate without writing any changes")
    return p


def run_merge_cli(argv: list[str] | None = None):
    """
    Entry-point called from the main bookshelf CLI:

        elif sys.argv[1] == "merge":
            from bookshelf.merge import run_merge_cli
            run_merge_cli(sys.argv[2:])
    """
    args = _build_parser().parse_args(argv)

    if args.dry_run:
        print(f"\n  {ICON_WARN}  *** DRY RUN - no changes will be written ***")

    merge(
        primary_db=os.path.expanduser(args.primary_db),
        primary_files=os.path.expanduser(args.primary_files),
        secondary_db=os.path.expanduser(args.secondary_db),
        secondary_files=os.path.expanduser(args.secondary_files),
        table=args.table,
        high_threshold=args.high_threshold,
        low_threshold=args.low_threshold,
        report_path=args.report,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    run_merge_cli()
