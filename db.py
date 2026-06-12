"""Shared SQLite helpers for CEC Tech Topics.

The database lives at data/topics.db (gitignored). Both the web server and
the topics.py CLI open short-lived connections; WAL mode keeps concurrent
reads/writes from the server and a Claude Code session safe.
"""

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "data" / "topics.db"

STATUSES = ("pending", "highlighted", "declined")

SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    title_key   TEXT NOT NULL,
    summary     TEXT NOT NULL DEFAULT '',
    url         TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT '',
    category    TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'highlighted', 'declined')),
    reason      TEXT NOT NULL DEFAULT '',
    batch_id    TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    decided_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_topics_status ON topics(status);
CREATE INDEX IF NOT EXISTS idx_topics_title_key ON topics(title_key);
CREATE INDEX IF NOT EXISTS idx_topics_url ON topics(url);
"""


def utcnow_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def title_key(title):
    """Normalized form of a title used for duplicate detection.

    Tokens are joined without separators so spacing/punctuation variants
    ("24GB" vs "24 GB", trailing "!") collapse to the same key.
    """
    return "".join(re.findall(r"[a-z0-9]+", title.lower()))


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn):
    """Bring databases created by older versions up to the current schema."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(topics)")}
    if "reason" not in cols:
        conn.execute("ALTER TABLE topics ADD COLUMN reason TEXT NOT NULL DEFAULT ''")
        conn.commit()


def topic_dict(row):
    d = dict(row)
    d.pop("title_key", None)
    return d


def status_counts(conn):
    counts = {s: 0 for s in STATUSES}
    for row in conn.execute("SELECT status, COUNT(*) AS n FROM topics GROUP BY status"):
        counts[row["status"]] = row["n"]
    counts["all"] = sum(counts[s] for s in STATUSES)
    return counts
