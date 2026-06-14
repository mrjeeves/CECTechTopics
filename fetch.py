"""Server-side runner for the headless "find new topics" job.

The web UI's Fetch button POSTs /api/fetch and the server spawns the local
`claude` CLI in print mode (claude -p) against this repo. That session
follows the CLAUDE.md workflow — read the feedback window, dedupe, web
search, insert one batch via topics.py, and add a few jokes via jokes.py —
and exits. One job runs at a time; its stdout/stderr go to data/fetch.log so
the UI can show progress and the bot's final rundown.

Fetching only ever adds pending topics (and fresh jokes). Existing rows are
never touched — clearing the queue is what Decline / Pass are for.

Override the spawned command with the TOPICS_FETCH_CMD environment variable
(parsed with shlex) if you want different flags, a different model, or a
stub for testing.
"""

import os
import shlex
import signal
import subprocess
import threading
from pathlib import Path

import db

REPO_DIR = Path(__file__).resolve().parent
LOG_PATH = db.DB_PATH.parent / "fetch.log"

FETCH_PROMPT = (
    "Find new topics for the show. Follow the workflow in CLAUDE.md: read the "
    "feedback window, check recent topics so you don't duplicate them, "
    "web-search current news, and insert one curated batch of 12-18 topics "
    "with `python3 topics.py add-batch`. Then add 6-8 short, clean, "
    "read-aloud jokes for the side carousel with `python3 jokes.py add-batch` "
    "(check `python3 jokes.py recent` first to avoid repeats, and "
    "`python3 jokes.py feedback` to match the humor that's landed). Only ever "
    "add rows: never delete, modify, or re-status existing topics or jokes — "
    "the hosts clear them in the UI. Finish with a one-line-per-topic rundown "
    "of what you added."
)

DEFAULT_CMD = [
    "claude",
    "-p",
    FETCH_PROMPT,
    "--allowedTools",
    "WebSearch,WebFetch,Write,Bash(python3:*)",
]


def fetch_command():
    custom = os.environ.get("TOPICS_FETCH_CMD")
    return shlex.split(custom) if custom else DEFAULT_CMD


_lock = threading.Lock()
_proc = None
_job = {
    "state": "idle",  # idle | running | cancelling | done | cancelled | error
    "started_at": None,
    "finished_at": None,
    "returncode": None,
    "added": None,        # topics added this run
    "jokes_added": None,  # jokes added this run
    "topics_before": None,
    "jokes_before": None,
}


def _count(table):
    conn = db.connect()
    try:
        return conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
    finally:
        conn.close()


def _log_tail(max_bytes=4000):
    try:
        with open(LOG_PATH, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def status():
    with _lock:
        snap = dict(_job)
    snap.pop("topics_before", None)  # internal baselines, not for the UI
    snap.pop("jokes_before", None)
    snap["log_tail"] = _log_tail()
    return snap


def start():
    """Kick off a fetch job. Returns False if one is already running."""
    global _proc
    with _lock:
        if _job["state"] in ("running", "cancelling"):
            return False

        cmd = fetch_command()
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        log = open(LOG_PATH, "w", encoding="utf-8")
        log.write("$ " + shlex.join(cmd) + "\n\n")
        log.flush()

        _job.update(started_at=db.utcnow_iso(), finished_at=None, returncode=None,
                    added=None, jokes_added=None,
                    topics_before=_count("topics"), jokes_before=_count("jokes"))
        try:
            _proc = subprocess.Popen(
                cmd,
                cwd=REPO_DIR,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=(os.name == "posix"),
            )
        except OSError as e:
            log.write(f"failed to start: {e}\n")
            log.close()
            _job.update(state="error", finished_at=db.utcnow_iso(), added=0, jokes_added=0)
            return True

        _job["state"] = "running"
        threading.Thread(target=_reap, args=(_proc, log), daemon=True).start()
        return True


def _reap(proc, log):
    rc = proc.wait()
    log.close()
    topics_now = _count("topics")
    jokes_now = _count("jokes")
    with _lock:
        _job.update(
            finished_at=db.utcnow_iso(),
            returncode=rc,
            added=topics_now - (_job["topics_before"] or 0),
            jokes_added=jokes_now - (_job["jokes_before"] or 0),
        )
        if _job["state"] == "cancelling":
            _job["state"] = "cancelled"
        else:
            _job["state"] = "done" if rc == 0 else "error"


def cancel():
    """Stop the running job (and its child processes where possible)."""
    with _lock:
        if _job["state"] != "running" or _proc is None:
            return False
        _job["state"] = "cancelling"
        try:
            if os.name == "posix":
                os.killpg(os.getpgid(_proc.pid), signal.SIGTERM)
            else:
                _proc.terminate()
        except (ProcessLookupError, PermissionError, OSError):
            pass
    return True
