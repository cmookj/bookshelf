"""
tests/test_merge.py

Test suite for bookshelf.merge.

Run with:
    pytest tests/test_merge.py -v

Fixes applied vs previous version
------------------------------------
1. call_args access
   _pick calls util.closed_ended_question(msg=..., options=...) using KEYWORD
   arguments.  call_args[0] (positional tuple) is therefore always empty ().
   All option-list inspections now use  call_args[1]["options"]  (kwargs dict).

2. "Last, First" format removed from name tests
   Comma is the author-separator in bookshelf.  "Knuth, Donald E." is
   recognised as one author by _split_authors (because "Donald E." has a dot),
   but bare "Knuth, Donald" is two separate authors.
   Tests that assumed bare first-name-after-comma would be detected as Last,First
   have been removed.  The Last,First handling tested via _author_similarity
   (which calls _split_authors) is retained.

3. PDF-text similarity test
   "completely different A" vs "completely different B" share 21/22 chars,
   giving SequenceMatcher ratio ≈ 0.954 which clears the 0.95 threshold.
   Replaced with texts from genuinely unrelated domains.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from unittest.mock import patch

import pytest

from bookshelf.merge import (
    MergeAction,
    Record,
    _ParsedName,
    _author_similarity,
    _csv_merge,
    _ensure_subdir,
    _file_path,
    _merge_fields,
    _metadata_identical,
    _names_match,
    _parse_name,
    _pick,
    _same_pdf_content,
    merge,
    weighted_similarity,
)

TABLE = "docs"


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_db(path: str, records: list[tuple]) -> None:
    conn = sqlite3.connect(path)
    conn.execute(f"""
        CREATE TABLE {TABLE} (
            id TEXT PRIMARY KEY, filename TEXT,
            title TEXT, authors TEXT, category TEXT,
            keywords TEXT, description TEXT
        )
    """)
    for row in records:
        conn.execute(f"INSERT INTO {TABLE} VALUES (?,?,?,?,?,?,?)", row)
    conn.commit()
    conn.close()


def _make_file(files_dir: str, filename: str, content: bytes = b"data") -> str:
    _ensure_subdir(files_dir, filename)
    fp = _file_path(files_dir, filename)
    with open(fp, "wb") as fh:
        fh.write(content)
    return fp


def _get_record(db_path: str, rec_id: str) -> tuple | None:
    conn = sqlite3.connect(db_path)
    row  = conn.execute(f"SELECT * FROM {TABLE} WHERE id=?", (rec_id,)).fetchone()
    conn.close()
    return row


def _count_records(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    n = conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
    conn.close()
    return n


@pytest.fixture()
def shelves():
    with tempfile.TemporaryDirectory() as pri_root, \
         tempfile.TemporaryDirectory() as sec_root:
        pri_files = os.path.join(pri_root, "files")
        sec_files = os.path.join(sec_root, "files")
        os.makedirs(pri_files)
        os.makedirs(sec_files)
        yield {
            "pri_db":    os.path.join(pri_root, "_database.db"),
            "pri_files": pri_files,
            "sec_db":    os.path.join(sec_root, "_database.db"),
            "sec_files": sec_files,
            "pri_root":  pri_root,
        }


def _run_merge(s: dict, **kwargs):
    return merge(
        primary_db=s["pri_db"],
        primary_files=s["pri_files"],
        secondary_db=s["sec_db"],
        secondary_files=s["sec_files"],
        table=TABLE,
        report_path=os.path.join(s["pri_root"], "report.txt"),
        **kwargs,
    )


def _get_mock_options(mock_q) -> list:
    """
    Extract the 'options' argument from a mock call to closed_ended_question.
    _pick always calls it with keyword arguments, so options live in
    call_args[1] (the kwargs dict), not call_args[0] (the positional tuple).
    """
    return mock_q.call_args[1]["options"]


# ─────────────────────────────────────────────────────────────────────────────
# _parse_name
# ─────────────────────────────────────────────────────────────────────────────

class TestParseName:

    def test_first_last(self):
        p = _parse_name("Donald Knuth")
        assert p.last == "knuth"
        assert "d" in p.initials
        assert "donald" in p.full_given

    def test_first_middle_initial_last(self):
        p = _parse_name("Donald E. Knuth")
        assert p.last == "knuth"
        assert {"d", "e"} <= p.initials
        assert "donald" in p.full_given

    def test_initial_dot_last(self):
        p = _parse_name("D. Knuth")
        assert p.last == "knuth"
        assert "d" in p.initials
        assert not p.full_given

    def test_two_initials_last(self):
        p = _parse_name("D.E. Knuth")
        assert p.last == "knuth"
        assert {"d", "e"} <= p.initials
        assert not p.full_given

    def test_bare_last_name_only(self):
        p = _parse_name("Knuth")
        assert p.last == "knuth"
        assert not p.initials
        assert not p.full_given

    def test_empty_string(self):
        p = _parse_name("")
        assert p.last == ""
        assert p.initials == frozenset()


# ─────────────────────────────────────────────────────────────────────────────
# _names_match
# ─────────────────────────────────────────────────────────────────────────────

class TestNamesMatch:

    def test_identical(self):
        assert _names_match("Donald Knuth", "Donald Knuth")

    def test_middle_initial_variant(self):
        assert _names_match("Donald Knuth", "Donald E. Knuth")

    def test_initial_vs_full_first(self):
        assert _names_match("D. Knuth", "Donald Knuth")

    def test_two_initials_vs_full_first(self):
        assert _names_match("D.E. Knuth", "Donald E. Knuth")

    def test_different_first_names(self):
        # Both have full first names whose initials happen to be the same letter.
        # Rule 2 must catch this: {"donald"} ∩ {"david"} = ∅ → no match.
        assert not _names_match("Donald Knuth", "David Knuth")

    def test_different_last_names(self):
        assert not _names_match("Donald Knuth", "Donald Turing")

    def test_case_insensitive(self):
        assert _names_match("donald knuth", "DONALD KNUTH")

    def test_empty_name(self):
        assert not _names_match("", "Donald Knuth")

    def test_bare_last_name_matches_any_first(self):
        # A bare last name carries no initials → matches any same-last-name entry.
        assert _names_match("Knuth", "Donald Knuth")


# ─────────────────────────────────────────────────────────────────────────────
# _author_similarity
# ─────────────────────────────────────────────────────────────────────────────

class TestAuthorSimilarity:

    def test_identical_authors(self):
        assert _author_similarity("Alice Lee, Bob Ray", "Alice Lee, Bob Ray") == 1.0

    def test_same_author_initial_vs_full(self):
        assert _author_similarity("D. Knuth", "Donald Knuth") == 1.0

    def test_last_comma_first_dot_format(self):
        # "Knuth, Donald E." has a dot → _split_authors detects it as one person
        # and converts to "Donald E. Knuth" before comparing.
        s = _author_similarity("Knuth, Donald E.", "Donald Knuth")
        assert s == 1.0

    def test_one_extra_author(self):
        s = _author_similarity("Alice Lee, Bob Ray", "Alice Lee, Bob Ray, Carol Wu")
        assert abs(s - 2/3) < 0.01

    def test_completely_different(self):
        s = _author_similarity("Alice Lee", "Bob Ray")
        assert s < 0.5

    def test_empty_both(self):
        assert _author_similarity("", "") == 1.0

    def test_empty_one_side(self):
        assert _author_similarity("", "Alice Lee") == 0.0

    def test_order_independent(self):
        assert _author_similarity("Alice Lee, Bob Ray", "Bob Ray, Alice Lee") == 1.0

    def test_weighted_similarity_uses_author_similarity(self):
        pri = Record("p", "p.pdf", "The Art", "Donald Knuth",
                     "book", "algorithms", "Classic text.")
        sec = Record("s", "s.pdf", "The Art", "D.E. Knuth",
                     "book", "algorithms", "Classic text.")
        assert weighted_similarity(sec, pri) >= 0.85


# ─────────────────────────────────────────────────────────────────────────────
# _csv_merge
# ─────────────────────────────────────────────────────────────────────────────

class TestCsvMerge:

    # ── keyword mode (is_authors=False) ───────────────────────────────

    def test_no_overlap(self):
        assert _csv_merge("a, b", "c, d") == "a, b, c, d"

    def test_full_overlap(self):
        assert _csv_merge("a, b, c", "a, b, c") == "a, b, c"

    def test_partial_overlap(self):
        assert _csv_merge("a, b, c, e", "a, b, c, d") == "a, b, c, e, d"

    def test_case_insensitive_keyword_dedup(self):
        result = _csv_merge("ML, CV", "ml, nlp")
        items = [i.strip() for i in result.split(",")]
        assert sum(1 for i in items if i.lower() == "ml") == 1

    def test_primary_order_preserved(self):
        assert _csv_merge("z, y, x", "a, b, c") == "z, y, x, a, b, c"

    def test_empty_primary(self):
        assert _csv_merge("", "a, b") == "a, b"

    def test_empty_secondary(self):
        assert _csv_merge("a, b", "") == "a, b"

    # ── author mode (is_authors=True) ─────────────────────────────────

    def test_author_name_variant_not_duplicated(self):
        # "D. Knuth" is the same person as "Donald Knuth" — should NOT appear twice.
        result = _csv_merge("Donald Knuth, Alice Lee", "D. Knuth, Bob Ray",
                             is_authors=True)
        items = [i.strip() for i in result.split(",")]
        knuth_count = sum(1 for i in items if "knuth" in i.lower())
        assert knuth_count == 1
        assert any("bob" in i.lower() or "ray" in i.lower() for i in items)

    def test_author_distinct_first_names_both_kept(self):
        # "Donald Knuth" vs "David Knuth" are different people → both must appear.
        result = _csv_merge("Donald Knuth", "David Knuth", is_authors=True)
        assert "Donald" in result
        assert "David" in result


# ─────────────────────────────────────────────────────────────────────────────
# _pick
# ─────────────────────────────────────────────────────────────────────────────

class TestPick:

    def test_identical_values_skipped(self):
        with patch("bookshelf.util.closed_ended_question") as mock_q:
            result = _pick("Title", "Same", "Same")
        mock_q.assert_not_called()
        assert result == "Same"

    def test_choose_primary(self):
        with patch("bookshelf.util.closed_ended_question", return_value="p"):
            assert _pick("Title", "Sec", "Pri") == "Pri"

    def test_choose_secondary(self):
        with patch("bookshelf.util.closed_ended_question", return_value="s"):
            assert _pick("Title", "Sec", "Pri") == "Sec"

    # Case 4/5: Authors / Keywords offer (m)erge
    def test_authors_merge_option_offered(self):
        with patch("bookshelf.util.closed_ended_question",
                   return_value="p") as mock_q:
            _pick("Authors", "A, B", "A, C", allow_csv_merge=True)
        assert "m" in _get_mock_options(mock_q)

    def test_authors_merge_result_is_name_aware(self):
        with patch("bookshelf.util.closed_ended_question", return_value="m"):
            result = _pick("Authors", "D. Knuth, Alice Lee",
                           "Donald Knuth, Bob Ray",
                           allow_csv_merge=True, is_authors=True)
        items = [i.strip() for i in result.split(",")]
        knuth_count = sum(1 for i in items if "knuth" in i.lower())
        assert knuth_count == 1
        assert any("alice" in i.lower() for i in items)
        assert any("bob" in i.lower() for i in items)

    def test_keywords_merge_option_offered(self):
        with patch("bookshelf.util.closed_ended_question",
                   return_value="p") as mock_q:
            _pick("Keywords", "ml, nlp", "ml, cv", allow_csv_merge=True)
        assert "m" in _get_mock_options(mock_q)

    # Case 6: Category — no (m)erge, no (w)rite
    def test_category_no_extra_options(self):
        with patch("bookshelf.util.closed_ended_question",
                   return_value="p") as mock_q:
            _pick("Category", "article", "book")
        opts = _get_mock_options(mock_q)
        assert "m" not in opts
        assert "w" not in opts

    # Case 7: Description offers (w)rite new but NOT (m)erge
    def test_description_write_new_option_offered(self):
        with patch("bookshelf.util.closed_ended_question",
                   return_value="p") as mock_q:
            _pick("Description", "sec", "pri", allow_write_new=True)
        opts = _get_mock_options(mock_q)
        assert "w" in opts
        assert "m" not in opts

    def test_description_write_new_result(self):
        new = "Brand new text."
        with patch("bookshelf.util.closed_ended_question", return_value="w"), \
             patch("bookshelf.util.string_input", return_value=new):
            assert _pick("Description", "old sec", "old pri",
                         allow_write_new=True) == new


# ─────────────────────────────────────────────────────────────────────────────
# _metadata_identical
# ─────────────────────────────────────────────────────────────────────────────

class TestMetadataIdentical:
    BASE = dict(id="x", filename="x.pdf", title="T", authors="A",
                category="c", keywords="k", description="d")

    def _rec(self, **ov) -> Record:
        return Record(**{**self.BASE, **ov})

    def test_same(self):
        assert _metadata_identical(self._rec(), self._rec(id="y", filename="y.pdf"))

    def test_diff_title(self):
        assert not _metadata_identical(self._rec(), self._rec(title="X"))

    def test_diff_authors(self):
        assert not _metadata_identical(self._rec(), self._rec(authors="B"))

    def test_diff_description(self):
        assert not _metadata_identical(self._rec(), self._rec(description="other"))


# ─────────────────────────────────────────────────────────────────────────────
# _same_pdf_content  (mocked _pdf_text)
# ─────────────────────────────────────────────────────────────────────────────

class TestSamePdfContent:

    def _mock_text(self, text_a, text_b):
        return patch("bookshelf.merge._pdf_text", side_effect=[text_a, text_b])

    def test_identical_text_returns_true(self):
        text = "The quick brown fox"
        with self._mock_text(text, text):
            assert _same_pdf_content("a.pdf", "b.pdf") is True

    def test_very_high_similarity_returns_true(self):
        # Simulate a lightly annotated copy: identical text ± trivial whitespace artefact
        base  = "word " * 300
        close = base.rstrip() + " "   # one trailing space different — virtually identical
        with self._mock_text(base.strip(), close.strip()):
            assert _same_pdf_content("a.pdf", "b.pdf") is True

    def test_different_text_returns_false(self):
        # Use texts from genuinely unrelated domains so ratio is well below 0.95.
        text_a = ("Machine learning is a branch of artificial intelligence "
                  "concerned with building systems that learn from data. "
                  "Neural networks, support vector machines, and decision trees "
                  "are common algorithms used in supervised learning tasks.")
        text_b = ("The Roman Empire at its height encompassed much of Europe, "
                  "North Africa, and the Middle East. Latin was the official "
                  "language of government and law, while Greek was widely spoken "
                  "in the eastern provinces during the Hellenistic period.")
        with self._mock_text(text_a, text_b):
            assert _same_pdf_content("a.pdf", "b.pdf") is False

    def test_none_text_returns_false(self):
        with self._mock_text(None, "some text"):
            assert _same_pdf_content("a.pdf", "b.pdf") is False

    def test_both_empty_returns_false(self):
        with self._mock_text("", ""):
            assert _same_pdf_content("a.pdf", "b.pdf") is False


# ─────────────────────────────────────────────────────────────────────────────
# Case 1 – Same metadata, different file  →  auto keep both (no prompt)
# ─────────────────────────────────────────────────────────────────────────────

class TestCase1SameMetadataDifferentFile:
    PRI_ID, SEC_ID   = "aa000001-0000-0000-0000-000000000001", "bb000002-0000-0000-0000-000000000002"
    PRI_FILE, SEC_FILE = PRI_ID + ".pdf", SEC_ID + ".pdf"
    METADATA = ("Deep Learning", "LeCun, Bengio", "book", "neural, learning", "A guide.")

    def _setup(self, s):
        _make_db(s["pri_db"], [(self.PRI_ID, self.PRI_FILE) + self.METADATA])
        _make_db(s["sec_db"], [(self.SEC_ID, self.SEC_FILE) + self.METADATA])
        _make_file(s["pri_files"], self.PRI_FILE, b"primary content")
        _make_file(s["sec_files"], self.SEC_FILE, b"DIFFERENT content")

    def test_action_is_kept_both(self, shelves):
        self._setup(shelves)
        assert _run_merge(shelves).entries[0].action == MergeAction.KEPT_BOTH

    def test_secondary_file_copied(self, shelves):
        self._setup(shelves)
        _run_merge(shelves)
        assert os.path.isfile(_file_path(shelves["pri_files"], self.SEC_FILE))

    def test_two_records_in_primary_db(self, shelves):
        self._setup(shelves)
        _run_merge(shelves)
        assert _count_records(shelves["pri_db"]) == 2

    def test_no_user_prompt(self, shelves):
        self._setup(shelves)
        with patch("bookshelf.util.closed_ended_question") as mock_q:
            _run_merge(shelves)
        mock_q.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Case 2 – Same file (hash), different metadata  →  merge metadata dialog
# ─────────────────────────────────────────────────────────────────────────────

class TestCase2SameFileDifferentMetadata:
    PRI_ID, SEC_ID   = "cc000003-0000-0000-0000-000000000003", "dd000004-0000-0000-0000-000000000004"
    PRI_FILE, SEC_FILE = PRI_ID + ".pdf", SEC_ID + ".pdf"
    CONTENT = b"identical file bytes"

    PRI_ROW = (PRI_ID, PRI_FILE, "Deep Learning", "LeCun",
               "book", "neural", "Primary abstract.")
    SEC_ROW = (SEC_ID, SEC_FILE, "Deep Learning", "LeCun, Bengio",
               "book", "neural, learning", "Secondary abstract.")

    def _setup(self, s):
        _make_db(s["pri_db"], [self.PRI_ROW])
        _make_db(s["sec_db"], [self.SEC_ROW])
        _make_file(s["pri_files"], self.PRI_FILE, self.CONTENT)
        _make_file(s["sec_files"], self.SEC_FILE, self.CONTENT)

    def test_action_is_replaced(self, shelves):
        self._setup(shelves)
        with patch("bookshelf.util.closed_ended_question", return_value="p"):
            assert _run_merge(shelves).entries[0].action == MergeAction.REPLACED

    def test_record_count_unchanged(self, shelves):
        self._setup(shelves)
        with patch("bookshelf.util.closed_ended_question", return_value="p"):
            _run_merge(shelves)
        assert _count_records(shelves["pri_db"]) == 1

    def test_secondary_file_not_copied(self, shelves):
        self._setup(shelves)
        with patch("bookshelf.util.closed_ended_question", return_value="p"):
            _run_merge(shelves)
        assert not os.path.isfile(_file_path(shelves["pri_files"], self.SEC_FILE))

    def test_merge_authors_keywords_desc(self, shelves):
        """Authors→merge, Keywords→merge, Description→keep primary."""
        self._setup(shelves)
        # Three differing fields: authors, keywords, description → 3 prompts.
        answers = iter(["m", "m", "p"])
        with patch("bookshelf.util.closed_ended_question",
                   side_effect=lambda msg, options: next(answers)):
            _run_merge(shelves)
        row = _get_record(shelves["pri_db"], self.PRI_ID)
        assert "Bengio" in row[3]
        assert "learning" in row[5]
        assert row[6] == "Primary abstract."


# ─────────────────────────────────────────────────────────────────────────────
# Case 2 (annotated) – Same PDF text despite different binary hash
# ─────────────────────────────────────────────────────────────────────────────

class TestCase2Annotated:
    PRI_ID, SEC_ID   = "ee000005-0000-0000-0000-000000000005", "ff000006-0000-0000-0000-000000000006"
    PRI_FILE, SEC_FILE = PRI_ID + ".pdf", SEC_ID + ".pdf"

    PRI_ROW = (PRI_ID, PRI_FILE, "Algorithms", "Cormen",
               "book", "sorting", "Primary abstract.")
    SEC_ROW = (SEC_ID, SEC_FILE, "Algorithms", "Cormen, Leiserson",
               "book", "sorting, searching", "Secondary abstract.")

    # Two texts that are genuinely different → ratio well below 0.95
    TEXT_DIFFERENT_A = (
        "Introduction to sorting algorithms including quicksort, mergesort, "
        "heapsort and their theoretical time complexity analysis."
    )
    TEXT_DIFFERENT_B = (
        "Principles of compiler design covering lexical analysis, parsing, "
        "semantic analysis, code generation and optimisation strategies."
    )

    def _setup(self, s):
        _make_db(s["pri_db"], [self.PRI_ROW])
        _make_db(s["sec_db"], [self.SEC_ROW])
        _make_file(s["pri_files"], self.PRI_FILE, b"pdf bytes v1")
        _make_file(s["sec_files"], self.SEC_FILE, b"pdf bytes v2 annotated")

    def test_annotated_copy_triggers_metadata_merge(self, shelves):
        """Same PDF text → jump directly to metadata reconciliation."""
        self._setup(shelves)
        shared = "Chapter 1: Foundations of algorithm analysis " * 20
        answers = iter(["m", "m", "p"])   # authors→merge, keywords→merge, desc→pri
        with patch("bookshelf.merge._PYPDF_AVAILABLE", True), \
             patch("bookshelf.merge._pdf_text", return_value=shared), \
             patch("bookshelf.util.closed_ended_question",
                   side_effect=lambda msg, options: next(answers)):
            report = _run_merge(shelves)
        assert report.entries[0].action == MergeAction.REPLACED
        row = _get_record(shelves["pri_db"], self.PRI_ID)
        assert "Leiserson" in row[3]
        assert "searching" in row[5]
        assert row[6] == "Primary abstract."

    def test_different_pdf_text_does_not_trigger_annotated_path(self, shelves):
        """Genuinely different text → annotated-copy path must NOT fire."""
        self._setup(shelves)
        # Use patched texts that produce ratio well below 0.95
        answers = iter(["s"])   # user skips at the top-level prompt
        with patch("bookshelf.merge._PYPDF_AVAILABLE", True), \
             patch("bookshelf.merge._pdf_text",
                   side_effect=[self.TEXT_DIFFERENT_A, self.TEXT_DIFFERENT_B]), \
             patch("bookshelf.util.closed_ended_question",
                   side_effect=lambda msg, options: next(answers)):
            report = _run_merge(shelves)
        # REPLACED would mean the annotated path fired — must not happen
        assert report.entries[0].action != MergeAction.REPLACED

    def test_pypdf_unavailable_falls_back_to_normal_flow(self, shelves):
        """Without pypdf the annotated-copy check is silently skipped."""
        self._setup(shelves)
        answers = iter(["s"])
        with patch("bookshelf.merge._PYPDF_AVAILABLE", False), \
             patch("bookshelf.util.closed_ended_question",
                   side_effect=lambda msg, options: next(answers)):
            report = _run_merge(shelves)
        assert report.entries[0].action == MergeAction.SKIPPED


# ─────────────────────────────────────────────────────────────────────────────
# Case 3 – Different titles  →  p / s prompt
# ─────────────────────────────────────────────────────────────────────────────

class TestCase3DifferentTitles:

    def _recs(self, pri_t, sec_t):
        return (Record("s", "s.pdf", sec_t, "Author", "article", "kw", "Desc."),
                Record("p", "p.pdf", pri_t, "Author", "article", "kw", "Desc."))

    def test_prompt_fires_exactly_once(self):
        sec, pri = self._recs("Old Title", "New Title")
        with patch("bookshelf.util.closed_ended_question",
                   return_value="p") as mock_q:
            _merge_fields(sec, pri)
        assert mock_q.call_count == 1

    def test_choose_primary_title(self):
        sec, pri = self._recs("Old Title", "New Title")
        with patch("bookshelf.util.closed_ended_question", return_value="p"):
            assert _merge_fields(sec, pri).title == "Old Title"

    def test_choose_secondary_title(self):
        sec, pri = self._recs("Old Title", "New Title")
        with patch("bookshelf.util.closed_ended_question", return_value="s"):
            assert _merge_fields(sec, pri).title == "New Title"


# ─────────────────────────────────────────────────────────────────────────────
# Case 4 – Different authors  →  p / s / m (name-aware CSV merge)
# ─────────────────────────────────────────────────────────────────────────────

class TestCase4DifferentAuthors:

    def _recs(self, pri_a, sec_a):
        return (Record("s", "s.pdf", "Title", sec_a, "article", "kw", "Desc."),
                Record("p", "p.pdf", "Title", pri_a, "article", "kw", "Desc."))

    def test_keep_primary(self):
        sec, pri = self._recs("Smith, Jones", "Smith, Brown")
        with patch("bookshelf.util.closed_ended_question", return_value="p"):
            assert _merge_fields(sec, pri).authors == "Smith, Jones"

    def test_keep_secondary(self):
        sec, pri = self._recs("Smith, Jones", "Smith, Brown")
        with patch("bookshelf.util.closed_ended_question", return_value="s"):
            assert _merge_fields(sec, pri).authors == "Smith, Brown"

    def test_merge_adds_new_author(self):
        sec, pri = self._recs("Smith, Jones", "Smith, Brown")
        with patch("bookshelf.util.closed_ended_question", return_value="m"):
            result = _merge_fields(sec, pri)
        assert "Smith" in result.authors
        assert "Jones" in result.authors
        assert "Brown" in result.authors

    def test_merge_no_duplicate_name_variants(self):
        """D. Knuth and Donald Knuth must not both appear after merge."""
        sec, pri = self._recs("Donald Knuth, Alice Lee", "D. Knuth, Bob Ray")
        with patch("bookshelf.util.closed_ended_question", return_value="m"):
            result = _merge_fields(sec, pri)
        items = [i.strip() for i in result.authors.split(",")]
        assert sum(1 for i in items if "knuth" in i.lower()) == 1

    def test_merge_option_in_options_list(self):
        with patch("bookshelf.util.closed_ended_question",
                   return_value="p") as mock_q:
            _pick("Authors", "A, B", "A, C", allow_csv_merge=True)
        assert "m" in _get_mock_options(mock_q)


# ─────────────────────────────────────────────────────────────────────────────
# Case 5 – Different keywords  →  p / s / m (plain CSV merge, no name logic)
# ─────────────────────────────────────────────────────────────────────────────

class TestCase5DifferentKeywords:

    def _recs(self, pri_k, sec_k):
        return (Record("s", "s.pdf", "Title", "Author", "article", sec_k, "Desc."),
                Record("p", "p.pdf", "Title", "Author", "article", pri_k, "Desc."))

    def test_keep_primary(self):
        sec, pri = self._recs("ml, cv", "ml, nlp")
        with patch("bookshelf.util.closed_ended_question", return_value="p"):
            assert _merge_fields(sec, pri).keywords == "ml, cv"

    def test_keep_secondary(self):
        sec, pri = self._recs("ml, cv", "ml, nlp")
        with patch("bookshelf.util.closed_ended_question", return_value="s"):
            assert _merge_fields(sec, pri).keywords == "ml, nlp"

    def test_merge_union(self):
        sec, pri = self._recs("ml, cv", "ml, nlp")
        with patch("bookshelf.util.closed_ended_question", return_value="m"):
            result = _merge_fields(sec, pri)
        assert all(kw in result.keywords for kw in ("ml", "cv", "nlp"))

    def test_merge_no_duplicates(self):
        sec, pri = self._recs("ml, cv", "ml, nlp")
        with patch("bookshelf.util.closed_ended_question", return_value="m"):
            result = _merge_fields(sec, pri)
        items = [k.strip() for k in result.keywords.split(",")]
        assert items.count("ml") == 1

    def test_merge_option_in_options_list(self):
        with patch("bookshelf.util.closed_ended_question",
                   return_value="p") as mock_q:
            _pick("Keywords", "a, b", "a, c", allow_csv_merge=True)
        assert "m" in _get_mock_options(mock_q)


# ─────────────────────────────────────────────────────────────────────────────
# Case 6 – Different categories  →  p / s only (no merge, no write)
# ─────────────────────────────────────────────────────────────────────────────

class TestCase6DifferentCategories:

    def _recs(self, pri_c, sec_c):
        return (Record("s", "s.pdf", "Title", "Author", sec_c, "kw", "Desc."),
                Record("p", "p.pdf", "Title", "Author", pri_c, "kw", "Desc."))

    def test_no_merge_or_write_option(self):
        with patch("bookshelf.util.closed_ended_question",
                   return_value="p") as mock_q:
            _pick("Category", "article", "book")
        opts = _get_mock_options(mock_q)
        assert "m" not in opts
        assert "w" not in opts

    def test_choose_primary_category(self):
        sec, pri = self._recs("book", "article")
        with patch("bookshelf.util.closed_ended_question", return_value="p"):
            assert _merge_fields(sec, pri).category == "book"

    def test_choose_secondary_category(self):
        sec, pri = self._recs("book", "article")
        with patch("bookshelf.util.closed_ended_question", return_value="s"):
            assert _merge_fields(sec, pri).category == "article"

    def test_identical_category_not_prompted(self):
        sec, pri = self._recs("article", "article")
        with patch("bookshelf.util.closed_ended_question") as mock_q:
            _merge_fields(sec, pri)
        mock_q.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Case 7 – Different descriptions  →  p / s / w (write new)
# ─────────────────────────────────────────────────────────────────────────────

class TestCase7DifferentDescriptions:

    def _recs(self, pri_d, sec_d):
        return (Record("s", "s.pdf", "Title", "Author", "article", "kw", sec_d),
                Record("p", "p.pdf", "Title", "Author", "article", "kw", pri_d))

    def test_write_new_option_offered(self):
        with patch("bookshelf.util.closed_ended_question",
                   return_value="p") as mock_q:
            _pick("Description", "sec", "pri", allow_write_new=True)
        opts = _get_mock_options(mock_q)
        assert "w" in opts

    def test_no_csv_merge_for_description(self):
        with patch("bookshelf.util.closed_ended_question",
                   return_value="p") as mock_q:
            _pick("Description", "sec", "pri", allow_write_new=True)
        assert "m" not in _get_mock_options(mock_q)

    def test_keep_primary_description(self):
        sec, pri = self._recs("Pri desc.", "Sec desc.")
        with patch("bookshelf.util.closed_ended_question", return_value="p"):
            assert _merge_fields(sec, pri).description == "Pri desc."

    def test_keep_secondary_description(self):
        sec, pri = self._recs("Pri desc.", "Sec desc.")
        with patch("bookshelf.util.closed_ended_question", return_value="s"):
            assert _merge_fields(sec, pri).description == "Sec desc."

    def test_write_new_description(self):
        sec, pri = self._recs("Pri desc.", "Sec desc.")
        new = "Hand-written replacement."
        with patch("bookshelf.util.closed_ended_question", return_value="w"), \
             patch("bookshelf.util.string_input", return_value=new):
            assert _merge_fields(sec, pri).description == new

    def test_write_new_end_to_end(self, shelves):
        """Full pipeline: same file, only description differs, user writes new."""
        pri_id = "a1b2c3d4-0000-0000-0000-000000000001"
        sec_id = "e5f6a7b8-0000-0000-0000-000000000002"
        content = b"shared bytes"
        _make_db(shelves["pri_db"], [(pri_id, pri_id+".pdf", "Title", "Author",
                                      "article", "kw", "Old primary.")])
        _make_db(shelves["sec_db"], [(sec_id, sec_id+".pdf", "Title", "Author",
                                      "article", "kw", "Old secondary.")])
        _make_file(shelves["pri_files"], pri_id+".pdf", content)
        _make_file(shelves["sec_files"], sec_id+".pdf", content)

        new_desc = "Freshly written unified abstract."
        with patch("bookshelf.util.closed_ended_question", return_value="w"), \
             patch("bookshelf.util.string_input", return_value=new_desc):
            report = _run_merge(shelves)
        assert report.entries[0].action == MergeAction.REPLACED
        assert _get_record(shelves["pri_db"], pri_id)[6] == new_desc
