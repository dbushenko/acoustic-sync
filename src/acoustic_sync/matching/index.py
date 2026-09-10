"""Disposable, disk-backed inverted index owned exclusively by Module B."""
from pathlib import Path
import sqlite3


class FingerprintIndex:
    def __init__(self, path: Path):
        self.connection = sqlite3.connect(path)
        self.connection.executescript("""
            PRAGMA journal_mode=OFF;
            PRAGMA synchronous=OFF;
            PRAGMA temp_store=FILE;
            PRAGMA cache_size=-32768;
            CREATE TABLE postings (hash INTEGER NOT NULL, stream INTEGER NOT NULL, t INTEGER NOT NULL);
            CREATE TABLE streams (id INTEGER PRIMARY KEY, media_id TEXT NOT NULL);
        """)

    def add_stream(self, stream: int, media_id: str):
        self.connection.execute("INSERT INTO streams VALUES (?, ?)", (stream, media_id))

    def add(self, stream: int, rows: list[tuple[int, int]], origin: int):
        self.connection.executemany("INSERT INTO postings VALUES (?, ?, ?)", ((h, stream, t+origin) for h, t in rows))
        self.connection.commit()

    def finalize(self):
        self.connection.executescript("""
            CREATE INDEX by_hash ON postings(hash);
            CREATE INDEX by_stream ON postings(stream);
            CREATE TABLE stats AS SELECT hash, COUNT(*) AS n FROM postings GROUP BY hash;
            CREATE UNIQUE INDEX stats_hash ON stats(hash);
            ANALYZE;
        """)

    def close(self):
        self.connection.close()
