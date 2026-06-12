#!/usr/bin/env python3
"""CLI for the CEC Tech Topics database.

This is the interface the local Claude Code session uses to feed the site
and to learn from past decisions:

    python3 topics.py feedback              # recent highlight/decline window (JSON)
    python3 topics.py recent --days 14      # what's already in the DB (JSON, for dedupe)
    python3 topics.py add-batch FILE|-      # insert a JSON array of new topics
    python3 topics.py add --title "..."     # insert a single topic
    python3 topics.py list --status pending # human-readable listing
    python3 topics.py stats                 # counts by status
"""

import argparse
import json
import sys
from datetime import datetime, timezone

import db

CATEGORY_HINT = (
    "CPUs, GPUs, Motherboards, Memory, Storage, Cooling, Cases, PSUs, "
    "Peripherals, Displays, Gaming, Industry, Deals, Software"
)


def insert_topic(conn, item, batch_id):
    """Insert one topic unless it duplicates an existing URL or title.

    Returns (inserted: bool, reason: str).
    """
    title = (item.get("title") or "").strip()
    if not title:
        return False, "missing title"

    url = (item.get("url") or "").strip()
    key = db.title_key(title)

    if url:
        row = conn.execute("SELECT id FROM topics WHERE url = ?", (url,)).fetchone()
        if row:
            return False, f"duplicate url (id {row['id']})"
    row = conn.execute("SELECT id FROM topics WHERE title_key = ?", (key,)).fetchone()
    if row:
        return False, f"duplicate title (id {row['id']})"

    conn.execute(
        """INSERT INTO topics (title, title_key, summary, url, source, category,
                               status, batch_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
        (
            title,
            key,
            (item.get("summary") or "").strip(),
            url,
            (item.get("source") or "").strip(),
            (item.get("category") or "").strip(),
            batch_id,
            db.utcnow_iso(),
        ),
    )
    return True, "added"


def new_batch_id():
    return "batch-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def cmd_add(args):
    item = {
        "title": args.title,
        "summary": args.summary,
        "url": args.url,
        "source": args.source,
        "category": args.category,
    }
    with db.connect() as conn:
        ok, reason = insert_topic(conn, item, new_batch_id())
    print(("added: " if ok else "skipped: ") + args.title + ("" if ok else f" ({reason})"))
    return 0 if ok else 1


def cmd_add_batch(args):
    raw = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"error: invalid JSON: {e}", file=sys.stderr)
        return 2
    if not isinstance(items, list):
        print("error: expected a JSON array of topic objects", file=sys.stderr)
        return 2

    batch_id = new_batch_id()
    added = skipped = 0
    with db.connect() as conn:
        for item in items:
            if not isinstance(item, dict):
                skipped += 1
                print("skipped: (not an object)")
                continue
            ok, reason = insert_topic(conn, item, batch_id)
            if ok:
                added += 1
                print(f"added:   {item['title'].strip()}")
            else:
                skipped += 1
                print(f"skipped: {(item.get('title') or '(untitled)').strip()} ({reason})")
    print(f"\n{batch_id}: {added} added, {skipped} skipped")
    return 0


def cmd_feedback(args):
    """Emit the recent-decision window the bot uses to steer its next batch."""
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT title, summary, url, source, category, status, reason, decided_at
               FROM topics WHERE status IN ('highlighted', 'declined')
               ORDER BY decided_at DESC LIMIT ?""",
            (args.window,),
        ).fetchall()

    highlighted, declined = [], []
    breakdown = {}
    for row in rows:
        entry = {
            "title": row["title"],
            "category": row["category"],
            "source": row["source"],
            "summary": row["summary"][:240],
            "reason": row["reason"][:300],
            "decided_at": row["decided_at"],
        }
        (highlighted if row["status"] == "highlighted" else declined).append(entry)
        cat = row["category"] or "(none)"
        breakdown.setdefault(cat, {"highlighted": 0, "declined": 0})
        breakdown[cat][row["status"]] += 1

    print(json.dumps({
        "generated_at": db.utcnow_iso(),
        "window": args.window,
        "decisions_in_window": len(rows),
        "highlighted": highlighted,
        "declined": declined,
        "category_breakdown": breakdown,
    }, indent=2))
    return 0


def cmd_recent(args):
    """Everything added recently, regardless of status — for dedupe awareness."""
    cutoff = f"-{args.days} days"
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT title, url, category, status, created_at FROM topics
               WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?)
               ORDER BY created_at DESC""",
            (cutoff,),
        ).fetchall()
    print(json.dumps({
        "days": args.days,
        "count": len(rows),
        "topics": [dict(r) for r in rows],
    }, indent=2))
    return 0


def cmd_list(args):
    with db.connect() as conn:
        if args.status == "all":
            rows = conn.execute(
                "SELECT * FROM topics ORDER BY created_at DESC, id DESC LIMIT ?",
                (args.limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM topics WHERE status = ? ORDER BY created_at DESC, id DESC LIMIT ?",
                (args.status, args.limit),
            ).fetchall()
    if not rows:
        print(f"no topics ({args.status})")
        return 0
    for r in rows:
        cat = f" [{r['category']}]" if r["category"] else ""
        note = f"  — {r['reason']}" if r["reason"] else ""
        print(f"#{r['id']:<4} {r['status']:<11} {r['title']}{cat}{note}")
    return 0


def cmd_stats(args):
    with db.connect() as conn:
        counts = db.status_counts(conn)
        last = conn.execute("SELECT MAX(created_at) AS t FROM topics").fetchone()["t"]
    for s in ("pending", "highlighted", "declined", "all"):
        print(f"{s:<12} {counts[s]}")
    print(f"last added   {last or '-'}")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("add", help="add a single topic")
    sp.add_argument("--title", required=True)
    sp.add_argument("--summary", default="")
    sp.add_argument("--url", default="")
    sp.add_argument("--source", default="", help="publication name, e.g. Tom's Hardware")
    sp.add_argument("--category", default="", help=f"one of: {CATEGORY_HINT}")
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("add-batch", help="add a JSON array of topics from a file or stdin (-)")
    sp.add_argument("file", help="path to JSON file, or - for stdin")
    sp.set_defaults(func=cmd_add_batch)

    sp = sub.add_parser("feedback", help="JSON window of recent highlight/decline decisions")
    sp.add_argument("--window", type=int, default=50, help="max decisions to include (default 50)")
    sp.set_defaults(func=cmd_feedback)

    sp = sub.add_parser("recent", help="JSON of topics added in the last N days (dedupe helper)")
    sp.add_argument("--days", type=int, default=14)
    sp.set_defaults(func=cmd_recent)

    sp = sub.add_parser("list", help="print topics")
    sp.add_argument("--status", default="all", choices=("all",) + db.STATUSES)
    sp.add_argument("--limit", type=int, default=200)
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("stats", help="counts by status")
    sp.set_defaults(func=cmd_stats)

    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
