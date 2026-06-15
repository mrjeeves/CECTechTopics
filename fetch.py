"""Server-side runners for the headless bot jobs.

Two jobs the web UI can start, each spawning the local `claude` CLI in print
mode (claude -p) against this repo and following CLAUDE.md:

  - topics (POST /api/fetch): research current news, add a batch of topics,
    and top up the jokes carousel.
  - jokes  (POST /api/jokes/fetch): add jokes only — the carousel's own
    "fetch" so hosts can refill jokes without touching the topic feed.

Each job runs one at a time and only ever ADDS rows; the hosts clear topics
(Decline) and jokes (Pass) in the UI. stdout/stderr go to a per-job log so the
UI can show progress and the bot's summary.

Override a job's command with its env var (TOPICS_FETCH_CMD / JOKES_FETCH_CMD,
parsed with shlex) for different flags, a model, or a stub in tests.
"""

import os
import shlex
import signal
import subprocess
import threading
from pathlib import Path

import db

REPO_DIR = Path(__file__).resolve().parent
ALLOWED_TOOLS = "WebSearch,WebFetch,Write,Bash(python3:*)"

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

JOKES_PROMPT = (
    "Add fresh jokes for the show's side carousel. Follow CLAUDE.md: check "
    "`python3 jokes.py recent` to avoid repeats and `python3 jokes.py feedback` "
    "to match the humor that's landed, then add 8-12 short, clean, read-aloud "
    "jokes (PC building, GPUs, gaming, tech) with `python3 jokes.py add-batch`. "
    "Only add jokes — never delete or re-status existing rows. Finish with a "
    "one-line summary of what you added."
)


def _count(table):
    conn = db.connect()
    try:
        return conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
    finally:
        conn.close()


class Job:
    """One headless bot run at a time, with status the UI can poll."""

    def __init__(self, prompt, log_name, env_var):
        self.prompt = prompt
        self.log_path = db.DB_PATH.parent / log_name
        self.env_var = env_var
        self._lock = threading.Lock()
        self._proc = None
        self._job = {
            "state": "idle",  # idle | running | cancelling | done | cancelled | error
            "started_at": None,
            "finished_at": None,
            "returncode": None,
            "added": None,        # topics added this run
            "jokes_added": None,  # jokes added this run
            "topics_before": None,
            "jokes_before": None,
        }

    def command(self):
        custom = os.environ.get(self.env_var)
        if custom:
            return shlex.split(custom)
        return ["claude", "-p", self.prompt, "--allowedTools", ALLOWED_TOOLS]

    def _log_tail(self, max_bytes=4000):
        try:
            with open(self.log_path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - max_bytes))
                return f.read().decode("utf-8", "replace")
        except OSError:
            return ""

    def status(self):
        with self._lock:
            snap = dict(self._job)
        snap.pop("topics_before", None)  # internal baselines, not for the UI
        snap.pop("jokes_before", None)
        snap["log_tail"] = self._log_tail()
        return snap

    def start(self):
        """Kick off the job. Returns False if one is already running."""
        with self._lock:
            if self._job["state"] in ("running", "cancelling"):
                return False

            cmd = self.command()
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            log = open(self.log_path, "w", encoding="utf-8")
            log.write("$ " + shlex.join(cmd) + "\n\n")
            log.flush()

            self._job.update(started_at=db.utcnow_iso(), finished_at=None, returncode=None,
                             added=None, jokes_added=None,
                             topics_before=_count("topics"), jokes_before=_count("jokes"))
            try:
                self._proc = subprocess.Popen(
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
                self._job.update(state="error", finished_at=db.utcnow_iso(), added=0, jokes_added=0)
                return True

            self._job["state"] = "running"
            threading.Thread(target=self._reap, args=(self._proc, log), daemon=True).start()
            return True

    def _reap(self, proc, log):
        rc = proc.wait()
        log.close()
        topics_now = _count("topics")
        jokes_now = _count("jokes")
        with self._lock:
            self._job.update(
                finished_at=db.utcnow_iso(),
                returncode=rc,
                added=topics_now - (self._job["topics_before"] or 0),
                jokes_added=jokes_now - (self._job["jokes_before"] or 0),
            )
            if self._job["state"] == "cancelling":
                self._job["state"] = "cancelled"
            else:
                self._job["state"] = "done" if rc == 0 else "error"

    def cancel(self):
        """Stop the running job (and its child processes where possible)."""
        with self._lock:
            if self._job["state"] != "running" or self._proc is None:
                return False
            self._job["state"] = "cancelling"
            try:
                if os.name == "posix":
                    os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
                else:
                    self._proc.terminate()
            except (ProcessLookupError, PermissionError, OSError):
                pass
        return True


topics_job = Job(FETCH_PROMPT, "fetch.log", "TOPICS_FETCH_CMD")
jokes_job = Job(JOKES_PROMPT, "jokes_fetch.log", "JOKES_FETCH_CMD")


# Module-level API used by server.py. Topics keeps its original names.
def status():
    return topics_job.status()


def start():
    return topics_job.start()


def cancel():
    return topics_job.cancel()


def jokes_status():
    return jokes_job.status()


def jokes_start():
    return jokes_job.start()


def jokes_cancel():
    return jokes_job.cancel()
