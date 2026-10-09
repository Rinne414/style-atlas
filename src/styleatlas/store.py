"""Content-addressed vector cache (SQLite).

Vectors are keyed by the SHA-1 of the file bytes plus the encoder signature, so renaming or moving
images never triggers re-embedding, and the cache is shared by every folder you analyse. A second
table remembers (path, size, mtime) -> hash so unchanged files are not re-hashed.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterable
from pathlib import Path

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS vectors (
  hash TEXT NOT NULL, signature TEXT NOT NULL, style BLOB NOT NULL, content BLOB NOT NULL,
  PRIMARY KEY (hash, signature));
CREATE TABLE IF NOT EXISTS files (
  path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, hash TEXT NOT NULL);
"""
HASH_CHUNK = 1 << 20


def file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while chunk := f.read(HASH_CHUNK):
            h.update(chunk)
    return h.hexdigest()


class VectorStore:
    def __init__(self, db_path: Path):
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path), timeout=60)
        self.conn.execute("PRAGMA journal_mode=WAL")  # several runs may share one cache
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> VectorStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def key(self, path: Path) -> str:
        """Content hash of `path`, re-hashing only when size or mtime changed."""
        path = Path(path).resolve()
        st = path.stat()
        row = self.conn.execute(
            "SELECT size, mtime_ns, hash FROM files WHERE path = ?", (str(path),)
        ).fetchone()
        if row and row[0] == st.st_size and row[1] == st.st_mtime_ns:
            return row[2]
        digest = file_sha1(path)
        self.conn.execute(
            "INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?)",
            (str(path), st.st_size, st.st_mtime_ns, digest),
        )
        return digest

    def get(self, keys: Iterable[str], signature: str) -> dict[str, tuple[np.ndarray, np.ndarray]]:
        out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        keys = list(dict.fromkeys(keys))
        for i in range(0, len(keys), 500):
            chunk = keys[i : i + 500]
            marks = ",".join("?" * len(chunk))
            rows = self.conn.execute(
                "SELECT hash, style, content FROM vectors "
                f"WHERE signature = ? AND hash IN ({marks})",
                (signature, *chunk),
            )
            for h, s, c in rows:
                out[h] = (np.frombuffer(s, np.float32), np.frombuffer(c, np.float32))
        return out

    def put(self, items: dict[str, tuple[np.ndarray, np.ndarray]], signature: str) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO vectors VALUES (?, ?, ?, ?)",
            [
                (
                    h,
                    signature,
                    np.asarray(s, np.float32).tobytes(),
                    np.asarray(c, np.float32).tobytes(),
                )
                for h, (s, c) in items.items()
            ],
        )
        self.conn.commit()

    def commit(self) -> None:
        self.conn.commit()
