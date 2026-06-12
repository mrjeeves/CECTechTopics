# CECTechTopics

Tech topics curator/presenter/tracker for the CEC live stream daily show.

A local Claude Code session researches current PC-building and gaming news and
loads candidate topics into a local SQLite database. The hosts review them in
a simple localhost site and mark each topic **★ highlighted** (cover it on
stream) or **✕ declined** (skip it). The bot reads a window of those recent
decisions before building its next list, so it learns what the show does and
doesn't want.

No dependencies — Python 3.9+ stdlib only.

## Quick start

Needs [`just`](https://github.com/casey/just) (single binary) and Python 3.9+.

```bash
# 1. one-time, after cloning: checks python, creates the database
just setup

# 2. start the site (leave it running)
just dev                     # → http://127.0.0.1:8765

# 3. in the browser: hit "⟳ Fetch new topics", then highlight / decline
```

The **⟳ Fetch new topics** button runs your local `claude` CLI headless
(`claude -p`) with the workflow in [CLAUDE.md](CLAUDE.md) — so the machine
running the server needs Claude Code installed and signed in. The status bar
under the header shows progress, lets you cancel, and keeps the bot's rundown
under "bot output". Running `claude "find new topics"` in a terminal does the
exact same thing.

Fetching is additive: a new batch stacks on top of whatever is still pending.
Topics only leave the queue when you decline (or highlight) them.

The page is quiet by default — it talks to the server only when you click
something (**↻ Refresh** re-pulls the list) or when you return to the tab.
The exception: while a fetch job is running, it watches the job status every
few seconds so the bar updates and the batch appears when it lands, then goes
quiet again. The research itself runs entirely server-side, so you can kick
it off, close the browser, and find the results waiting later.

No `just`? It's all plain stdlib underneath: `python3 server.py`.

To customize how the bot is launched (flags, model, a test stub), set
`TOPICS_FETCH_CMD` to the full command before starting the server.

## Remote access (tailscale)

Bind to all interfaces, then open `http://<tailscale-ip>:8765` from the other
machine:

```bash
just dev 0.0.0.0             # or: python3 server.py --host 0.0.0.0
```

## CLI

The bot drives everything through `topics.py`, but it works by hand too:

```bash
python3 topics.py feedback --window 50   # recent highlight/decline decisions (JSON)
python3 topics.py recent --days 14       # recently added topics, for dedupe (JSON)
python3 topics.py add-batch batch.json   # insert a JSON array of topics (dedupes)
python3 topics.py add --title "..." --url "..." --category GPUs
python3 topics.py list --status pending
python3 topics.py stats
```

The bot's full workflow and the batch JSON shape live in [CLAUDE.md](CLAUDE.md).

## Layout

| Path | What it is |
| --- | --- |
| `justfile` | `just setup` / `just dev` |
| `server.py` | localhost web server + JSON API |
| `topics.py` | CLI used by the bot (and humans) |
| `fetch.py` | runs the bot headless for the UI's fetch button |
| `db.py` | SQLite schema/helpers |
| `static/` | the review UI |
| `data/topics.db` | the database (created on first run, gitignored) |
