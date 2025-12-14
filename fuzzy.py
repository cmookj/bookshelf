import sqlite3

def setup_fts(db_path: str, table_name: str):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Enable foreign keys (good practice)
    cur.execute("PRAGMA foreign_keys = ON;")

    # Create FTS5 virtual table
    cur.execute(f"""
    CREATE VIRTUAL TABLE IF NOT EXISTS bookshelf_fts
    USING fts5(
        id,
        title,
        authors,
        keywords,
        description,
        content='{table_name}',
        content_rowid='rowid'
    );
    """)

    # Populate FTS table from the content table
    cur.execute(f"""
    INSERT INTO bookshelf_fts(rowid, id, title, authors, keywords, description)
    SELECT rowid, id, title, authors, keywords, description
    FROM {table_name};
    """)

    conn.commit()
    conn.close()

def setup_fts_triggers(db_path: str, table_name: str):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Insert trigger
    cur.execute(f"""
    CREATE TRIGGER IF NOT EXISTS bookshelf_ai
    AFTER INSERT ON {table_name}
    BEGIN
        INSERT INTO bookshelf_fts(rowid, id, title, authors, keywords, description)
        VALUES (
            new.rowid,
            new.id,
            new.title,
            new.authors,
            new.keywords,
            new.description
        );
    END;
    """)

    # Delete trigger
    cur.execute(f"""
    CREATE TRIGGER IF NOT EXISTS bookshelf_ad
    AFTER DELETE ON {table_name}
    BEGIN
        INSERT INTO bookshelf_fts(bookshelf_fts, rowid, id, title, authors, keywords, description)
        VALUES('delete', old.rowid, old.id, old.title, old.authors, old.keywords, old.description);
    END;
    """)

    # Update trigger
    cur.execute(f"""
    CREATE TRIGGER IF NOT EXISTS bookshelf_au
    AFTER UPDATE ON {table_name}
    BEGIN
        INSERT INTO bookshelf_fts(bookshelf_fts, rowid, id, title, authors, keywords, description)
        VALUES('delete', old.rowid, old.id, old.title, old.authors, old.keywords, old.description);

        INSERT INTO bookshelf_fts(rowid, id, title, authors, keywords, description)
        VALUES (
            new.rowid,
            new.id,
            new.title,
            new.authors,
            new.keywords,
            new.description
        );
    END;
    """)

    conn.commit()
    conn.close()

def test_fts(db_path: str, query: str):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
    SELECT id, title
    FROM bookshelf_fts
    WHERE bookshelf_fts MATCH ?
    """, (query,))

    for row in cur.fetchall():
        print(row)

    conn.close()

def fuzzy_search_fts(db_path, table_name, query):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    sql = f"""
    SELECT b.id, b.filename, b.title, rank
    FROM bookshelf_fts f
    JOIN {table_name} b ON b.rowid = f.rowid
    WHERE bookshelf_fts MATCH ?
    ORDER BY rank
    """

    cur.execute(sql, (query,))
    results = cur.fetchall()

    print(results)

    conn.close()
    return results

