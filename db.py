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

# Jokes: a side carousel the hosts react to. Laughed jokes can resurface on a
# later day; passed jokes are binned. We keep a rolling month and prune older.
JOKE_STATUSES = ("fresh", "laughed", "passed")
JOKE_RETENTION_DAYS = 30
# Once a joke has been shown on stream it sits out of rotation for a few days
# before it can resurface, so the carousel doesn't repeat itself.
JOKE_SHOWN_DECAY_DAYS = 3

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

CREATE TABLE IF NOT EXISTS jokes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT NOT NULL,
    text_key    TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'fresh'
                CHECK (status IN ('fresh', 'laughed', 'passed')),
    laughs      INTEGER NOT NULL DEFAULT 0,
    batch_id    TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    decided_at  TEXT,
    shown_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_jokes_status ON jokes(status);
CREATE INDEX IF NOT EXISTS idx_jokes_text_key ON jokes(text_key);
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
    jcols = {row["name"] for row in conn.execute("PRAGMA table_info(jokes)")}
    if "shown_at" not in jcols:
        conn.execute("ALTER TABLE jokes ADD COLUMN shown_at TEXT")
        # Carry each reacted joke's decision time forward as its last-shown time
        # so existing laughs serve out the new decay window instead of snapping
        # straight back into rotation.
        conn.execute("UPDATE jokes SET shown_at = decided_at WHERE decided_at IS NOT NULL")
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


# -- jokes -------------------------------------------------------------------

def joke_dict(row):
    d = dict(row)
    d.pop("text_key", None)
    return d


def prune_jokes(conn, days=JOKE_RETENTION_DAYS):
    """Delete jokes older than the retention window. Returns rows removed."""
    cur = conn.execute(
        "DELETE FROM jokes WHERE created_at < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?)",
        (f"-{days} days",),
    )
    return cur.rowcount


def eligible_jokes(conn, limit=60):
    """Jokes the carousel may show: not binned, and not shown in the last few
    days. A joke decays for JOKE_SHOWN_DECAY_DAYS once shown before it's eligible
    again, so it doesn't repeat. Fresh first, then crowd-pleasers."""
    return conn.execute(
        """SELECT * FROM jokes
           WHERE status != 'passed'
             AND (shown_at IS NULL
                  OR shown_at < strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?))
           ORDER BY (status = 'fresh') DESC, laughs DESC, created_at DESC
           LIMIT ?""",
        (f"-{JOKE_SHOWN_DECAY_DAYS} days", limit),
    ).fetchall()


def joke_counts(conn):
    counts = {s: 0 for s in JOKE_STATUSES}
    for row in conn.execute("SELECT status, COUNT(*) AS n FROM jokes GROUP BY status"):
        counts[row["status"]] = row["n"]
    counts["all"] = sum(counts[s] for s in JOKE_STATUSES)
    return counts
