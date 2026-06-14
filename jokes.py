#!/usr/bin/env python3
"""CLI for the jokes carousel.

The bot adds short jokes for the show's side carousel; the hosts react with
Laugh (keep — may resurface on a later day) or Pass (bin and forget). This is
the interface the local Claude Code session uses:

    python3 jokes.py feedback              # what landed / bombed recently (JSON)
    python3 jokes.py recent --days 30      # recent jokes, for dedupe (JSON)
    python3 jokes.py add-batch FILE|-      # insert a JSON array of jokes
    python3 jokes.py add --text "..."      # insert a single joke
    python3 jokes.py list --status fresh   # human-readable listing
    python3 jokes.py prune                 # drop jokes past the retention window
    python3 jokes.py stats                 # counts by status

Reactions are made by the hosts in the UI, never here.
"""

import argparse
import json
import sys
from datetime import datetime, timezone

import db

JOKE_CATEGORY_HINT = (
    "PC building, GPUs, gaming, tech support, dad jokes, puns — keep them short, "
    "clean, and read-aloud friendly"
)


def insert_joke(conn, item, batch_id):
    """Insert one joke unless its text duplicates an existing one.

    Returns (inserted: bool, reason: str).
    """
    text = (item.get("text") or "").strip()
    if not text:
        return False, "missing text"

    key = db.title_key(text)
    if not key:
        return False, "empty after normalizing"
    row = conn.execute("SELECT id FROM jokes WHERE text_key = ?", (key,)).fetchone()
    if row:
        return False, f"duplicate (id {row['id']})"

    conn.execute(
        """INSERT INTO jokes (text, text_key, category, status, batch_id, created_at)
           VALUES (?, ?, ?, 'fresh', ?, ?)""",
        (
            text,
            key,
            (item.get("category") or "").strip(),
            batch_id,
            db.utcnow_iso(),
        ),
    )
    return True, "added"


def new_batch_id():
    return "jokes-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def cmd_add(args):
    with db.connect() as conn:
        ok, reason = insert_joke(conn, {"text": args.text, "category": args.category},
                                 new_batch_id())
    print(("added: " if ok else "skipped: ") + args.text + ("" if ok else f" ({reason})"))
    return 0 if ok else 1


def cmd_add_batch(args):
    raw = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"error: invalid JSON: {e}", file=sys.stderr)
        return 2
    if not isinstance(items, list):
        print("error: expected a JSON array of joke objects", file=sys.stderr)
        return 2

    # Accept either {"text": "..."} objects or bare strings.
    batch_id = new_batch_id()
    added = skipped = 0
    with db.connect() as conn:
        for item in items:
            if isinstance(item, str):
                item = {"text": item}
            elif not isinstance(item, dict):
                skipped += 1
                print("skipped: (not an object)")
                continue
            ok, reason = insert_joke(conn, item, batch_id)
            if ok:
                added += 1
                print(f"added:   {item['text'].strip()}")
            else:
                skipped += 1
                print(f"skipped: {(item.get('text') or '(empty)').strip()} ({reason})")
    print(f"\n{batch_id}: {added} added, {skipped} skipped")
    return 0


def cmd_feedback(args):
    """What landed (laughed) and what bombed (passed) recently — humor steering."""
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT text, category, status, laughs, decided_at
               FROM jokes WHERE status IN ('laughed', 'passed')
               ORDER BY decided_at DESC LIMIT ?""",
            (args.window,),
        ).fetchall()

    laughed, passed = [], []
    for row in rows:
        entry = {"text": row["text"], "category": row["category"],
                 "laughs": row["laughs"], "decided_at": row["decided_at"]}
        (laughed if row["status"] == "laughed" else passed).append(entry)

    print(json.dumps({
        "generated_at": db.utcnow_iso(),
        "window": args.window,
        "laughed": laughed,   # emulate this style — these got a laugh
        "passed": passed,     # these bombed — avoid this style
    }, indent=2))
    return 0


def cmd_recent(args):
    """Recent joke texts regardless of status — for dedupe awareness."""
    cutoff = f"-{args.days} days"
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT text, category, status, created_at FROM jokes
               WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?)
               ORDER BY created_at DESC""",
            (cutoff,),
        ).fetchall()
    print(json.dumps({
        "days": args.days,
        "count": len(rows),
        "jokes": [dict(r) for r in rows],
    }, indent=2))
    return 0


def cmd_list(args):
    with db.connect() as conn:
        if args.status == "all":
            rows = conn.execute(
                "SELECT * FROM jokes ORDER BY created_at DESC, id DESC LIMIT ?",
                (args.limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jokes WHERE status = ? ORDER BY created_at DESC, id DESC LIMIT ?",
                (args.status, args.limit),
            ).fetchall()
    if not rows:
        print(f"no jokes ({args.status})")
        return 0
    for r in rows:
        cat = f" [{r['category']}]" if r["category"] else ""
        laughs = f" ♥{r['laughs']}" if r["laughs"] else ""
        print(f"#{r['id']:<4} {r['status']:<8}{laughs} {r['text']}{cat}")
    return 0


def cmd_prune(args):
    with db.connect() as conn:
        removed = db.prune_jokes(conn)
    print(f"pruned {removed} joke(s) older than {db.JOKE_RETENTION_DAYS} days")
    return 0


def cmd_stats(args):
    with db.connect() as conn:
        counts = db.joke_counts(conn)
        last = conn.execute("SELECT MAX(created_at) AS t FROM jokes").fetchone()["t"]
    for s in ("fresh", "laughed", "passed", "all"):
        print(f"{s:<10} {counts[s]}")
    print(f"last added {last or '-'}")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("add", help="add a single joke")
    sp.add_argument("--text", required=True)
    sp.add_argument("--category", default="", help=f"optional theme: {JOKE_CATEGORY_HINT}")
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("add-batch", help="add a JSON array of jokes from a file or stdin (-)")
    sp.add_argument("file", help="path to JSON file, or - for stdin")
    sp.set_defaults(func=cmd_add_batch)

    sp = sub.add_parser("feedback", help="JSON of recently laughed/passed jokes (humor steering)")
    sp.add_argument("--window", type=int, default=40)
    sp.set_defaults(func=cmd_feedback)

    sp = sub.add_parser("recent", help="JSON of jokes added in the last N days (dedupe helper)")
    sp.add_argument("--days", type=int, default=30)
    sp.set_defaults(func=cmd_recent)

    sp = sub.add_parser("list", help="print jokes")
    sp.add_argument("--status", default="all", choices=("all",) + db.JOKE_STATUSES)
    sp.add_argument("--limit", type=int, default=200)
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("prune", help="drop jokes past the retention window")
    sp.set_defaults(func=cmd_prune)

    sp = sub.add_parser("stats", help="counts by status")
    sp.set_defaults(func=cmd_stats)

    args = p.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
