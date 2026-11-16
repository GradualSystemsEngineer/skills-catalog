"""SQLite storage: the publish transaction, lookups and search. Insert-only for versions and files."""

import base64
import re
import sqlite3
from datetime import datetime, timezone

from skills_catalog.domain import diff_files, version_digest

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS versions (
  name         TEXT NOT NULL,
  version      INTEGER NOT NULL,
  digest       TEXT NOT NULL,
  description  TEXT NOT NULL,
  author       TEXT,
  published_at TEXT NOT NULL,
  PRIMARY KEY (name, version)
)""",
    """CREATE TABLE IF NOT EXISTS files (
  name TEXT, version INTEGER, path TEXT,
  sha256 TEXT NOT NULL, size INTEGER NOT NULL, executable INTEGER NOT NULL,
  bytes BLOB NOT NULL,
  PRIMARY KEY (name, version, path)
)""",
    "CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts USING fts5(name, description, body, tokenize = 'porter unicode61')",
]

STOP_WORDS = {
    "a", "an", "the", "for", "to", "of", "in", "on", "and", "or", "is", "my", "me", "i", "with",
    "that", "this", "do", "we", "have", "any", "there", "skill", "skills",
}

LATEST = "(SELECT MAX(version) FROM versions WHERE name = v.name)"
SUMMARY = "v.name, v.description, v.version, v.author, v.published_at"


def connect(path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    init(conn)
    return conn


def init(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA:
        conn.execute(statement)


def publish(conn, name, description, body, author, files) -> tuple[int, str, str]:
    """Store a new version in one transaction. files: dicts with path, sha256, size, executable, data."""
    digest = version_digest([[f["path"], f["sha256"], f["executable"]] for f in files])
    published_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute("BEGIN IMMEDIATE")
    try:
        version = conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM versions WHERE name = ?", (name,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO versions VALUES (?, ?, ?, ?, ?, ?)",
            (name, version, digest, description, author, published_at),
        )
        conn.executemany(
            "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(name, version, f["path"], f["sha256"], f["size"], int(f["executable"]), f["data"]) for f in files],
        )
        conn.execute("DELETE FROM skills_fts WHERE name = ?", (name,))
        conn.execute("INSERT INTO skills_fts VALUES (?, ?, ?)", (name, description, body))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return version, digest, published_at


def search(conn, query: str) -> list[dict]:
    tokens = re.findall(r"\w+", query.lower())
    if not tokens:
        return []
    kept = [t for t in tokens if t not in STOP_WORDS] or tokens
    expression = " OR ".join(f'"{t}"' for t in kept)
    rows = conn.execute(
        f"SELECT {SUMMARY} FROM skills_fts f JOIN versions v ON v.name = f.name AND v.version = {LATEST} "
        "WHERE skills_fts MATCH ? ORDER BY bm25(skills_fts, 10.0, 5.0, 1.0) LIMIT 10",
        (expression,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_all(conn) -> list[dict]:
    rows = conn.execute(f"SELECT {SUMMARY} FROM versions v WHERE v.version = {LATEST} ORDER BY v.name").fetchall()
    return [dict(r) for r in rows]


def count_skills(conn) -> int:
    return conn.execute("SELECT COUNT(DISTINCT name) FROM versions").fetchone()[0]


def latest_version(conn, name) -> int | None:
    return conn.execute("SELECT MAX(version) FROM versions WHERE name = ?", (name,)).fetchone()[0]


def get_version(conn, name, version=None) -> dict | None:
    """One complete package, files included. Latest when version is None."""
    if version is None:
        version = latest_version(conn, name)
    row = conn.execute(
        "SELECT name, version, digest, author, published_at FROM versions WHERE name = ? AND version = ?",
        (name, version),
    ).fetchone()
    if row is None:
        return None
    files = conn.execute(
        "SELECT path, sha256, size, executable, bytes FROM files WHERE name = ? AND version = ? ORDER BY path",
        (name, version),
    ).fetchall()
    package = dict(row)
    package["files"] = [
        {
            "path": f["path"],
            "sha256": f["sha256"],
            "size": f["size"],
            "executable": bool(f["executable"]),
            "content_b64": base64.b64encode(f["bytes"]).decode("ascii"),
        }
        for f in files
    ]
    return package


def history(conn, name) -> list[dict]:
    """Every version, newest first, with the files changed since the previous one. No file bytes."""
    versions = conn.execute(
        "SELECT version, digest, author, published_at FROM versions WHERE name = ? ORDER BY version",
        (name,),
    ).fetchall()
    entries = {}
    for f in conn.execute("SELECT version, path, sha256, executable FROM files WHERE name = ?", (name,)):
        entries.setdefault(f["version"], []).append([f["path"], f["sha256"], bool(f["executable"])])
    result, prev = [], []
    for v in versions:
        curr = entries.get(v["version"], [])
        result.append({**dict(v), "changes": diff_files(prev, curr)})
        prev = curr
    return result[::-1]
