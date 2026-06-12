#!/usr/bin/env python3
"""Localhost web server for CEC Tech Topics. Stdlib only — no installs.

    python3 server.py                       # http://127.0.0.1:8765
    python3 server.py --host 0.0.0.0        # expose for tailscale access
    python3 server.py --port 9000

API:
    GET  /api/topics?status=pending|highlighted|declined|all
    POST /api/topics/<id>/status   body: {"status": "highlighted",
                                          "reason": "optional note for the bot"}
                                   reason omitted = unchanged; pending clears it
    GET  /api/fetch                status of the "find new topics" bot job
    POST /api/fetch                start a bot job (409 if one is running)
    POST /api/fetch/cancel         stop the running bot job
"""

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import db
import fetch

STATIC_DIR = Path(__file__).resolve().parent / "static"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}
STATUS_ROUTE = re.compile(r"^/api/topics/(\d+)/status$")


class Handler(BaseHTTPRequestHandler):
    server_version = "CECTopics/1.0"

    # -- helpers ----------------------------------------------------------

    def send_json(self, payload, code=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path):
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return None
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return None

    # -- routes -----------------------------------------------------------

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            return self.send_file(STATIC_DIR / "index.html")
        if parsed.path == "/api/topics":
            return self.get_topics(parsed)
        if parsed.path == "/api/fetch":
            return self.send_json(fetch.status())
        if parsed.path.startswith("/static/"):
            target = (STATIC_DIR / parsed.path[len("/static/"):]).resolve()
            if target.is_file() and STATIC_DIR in target.parents:
                return self.send_file(target)
        self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/fetch":
            started = fetch.start()
            return self.send_json(fetch.status(), 200 if started else 409)
        if path == "/api/fetch/cancel":
            fetch.cancel()
            return self.send_json(fetch.status())

        match = STATUS_ROUTE.match(path)
        if not match:
            return self.send_json({"error": "not found"}, 404)

        body = self.read_json_body() or {}
        status = body.get("status")
        if status not in db.STATUSES:
            return self.send_json(
                {"error": f"status must be one of {list(db.STATUSES)}"}, 400)

        topic_id = int(match.group(1))
        decided_at = None if status == "pending" else db.utcnow_iso()
        sets, params = ["status = ?", "decided_at = ?"], [status, decided_at]
        if status == "pending":
            sets.append("reason = ''")
        elif body.get("reason") is not None:
            sets.append("reason = ?")
            params.append(str(body["reason"]).strip()[:1000])
        conn = db.connect()
        try:
            with conn:
                cur = conn.execute(
                    f"UPDATE topics SET {', '.join(sets)} WHERE id = ?",
                    (*params, topic_id),
                )
                row = (conn.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
                       if cur.rowcount else None)
        finally:
            conn.close()
        if row is None:
            return self.send_json({"error": f"no topic with id {topic_id}"}, 404)
        self.send_json({"topic": db.topic_dict(row)})

    def get_topics(self, parsed):
        status = (parse_qs(parsed.query).get("status") or ["all"])[0]
        if status not in db.STATUSES + ("all",):
            return self.send_json({"error": "bad status filter"}, 400)

        order = ("decided_at DESC, id DESC" if status in ("highlighted", "declined")
                 else "created_at DESC, id DESC")
        where = "" if status == "all" else "WHERE status = ?"
        params = () if status == "all" else (status,)

        conn = db.connect()
        try:
            rows = conn.execute(
                f"SELECT * FROM topics {where} ORDER BY {order} LIMIT 500", params
            ).fetchall()
            counts = db.status_counts(conn)
        finally:
            conn.close()
        self.send_json({"topics": [db.topic_dict(r) for r in rows], "counts": counts})


def main():
    p = argparse.ArgumentParser(description="CEC Tech Topics web server")
    p.add_argument("--host", default="127.0.0.1",
                   help="bind address (use 0.0.0.0 to reach it over tailscale)")
    p.add_argument("--port", type=int, default=8765)
    args = p.parse_args()

    db.connect().close()  # create the database up front
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"CEC Tech Topics  →  http://{args.host}:{args.port}")
    print(f"database         →  {db.DB_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
