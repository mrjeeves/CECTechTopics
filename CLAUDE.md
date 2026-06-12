# CEC Tech Topics

Topic radar for the CEC live stream daily show. A local Claude Code session
(you) researches current tech news and feeds candidate topics into a SQLite
database; the hosts review them in a localhost web UI and mark each one
**highlighted** (want to cover) or **declined** (not interested). Those
decisions are your feedback signal for the next batch.

Everything is Python stdlib — no installs, no build step.

- `server.py` — localhost web UI (`python3 server.py`, http://127.0.0.1:8765)
- `topics.py` — CLI you use to read feedback and add topics
- `db.py` — shared SQLite helpers (DB at `data/topics.db`, gitignored)
- `static/` — frontend for the review UI

## Workflow: "find new topics" / "new batch"

When asked to find topics, do this:

1. **Read the feedback window** — what the hosts liked and rejected recently:
   ```
   python3 topics.py feedback --window 50
   ```
2. **Check what's already in the DB** so you don't research duplicates
   (`add-batch` also hard-dedupes by URL and title as a backstop):
   ```
   python3 topics.py recent --days 14
   ```
3. **Web search for current news** — strongly prefer stories from the last
   ~72 hours. Core beats:
   - PC hardware: CPUs, GPUs, motherboards, RAM, storage, PSUs, cases, cooling
   - Builds & DIY: notable builds, mods, SFF, watercooling, price/perf trends
   - Gaming hardware: monitors, peripherals, handhelds, VR, controllers
   - Gaming/industry news that matters to PC builders and PC gamers
     (big releases and performance/ports, drivers, Windows/DirectX, deals,
     supply/pricing, benchmarks, recalls/failures)
4. **Curate 12–18 candidates.** Steer toward the patterns in `highlighted`
   and away from the patterns in `declined` (categories, sources, story
   types). Mix categories — don't make the whole batch one beat. Prefer
   reputable outlets and primary sources; link the article, not an aggregator.
5. **Insert the batch** as a JSON array via stdin or a temp file:
   ```
   python3 topics.py add-batch /tmp/batch.json     # or: ... add-batch -
   ```
6. **Confirm and report**: run `python3 topics.py stats`, then give the hosts
   a one-line-per-topic rundown of what you added. The UI picks new rows up
   automatically within a few seconds.

### add-batch JSON shape

```json
[
  {
    "title": "RTX 5080 Super rumored for Q3 with 24GB",
    "summary": "1-3 sentences: what happened and why it matters to PC builders or gamers.",
    "url": "https://www.tomshardware.com/...",
    "source": "Tom's Hardware",
    "category": "GPUs"
  }
]
```

- `title` is required; everything else is optional but fill it in when you can.
- `category`: pick one of CPUs, GPUs, Motherboards, Memory, Storage, Cooling,
  Cases, PSUs, Peripherals, Displays, Gaming, Industry, Deals, Software —
  consistent categories make the feedback breakdown useful.
- Summaries are read aloud on stream: neutral, concrete, no hype.

## Rules

- Never re-add a topic that was declined, and don't add near-duplicates of
  anything in `recent` — a story counts as a duplicate if it's the same
  underlying news, even from a different outlet.
- Write to the DB only through `topics.py` (it normalizes, dedupes, and
  stamps batches) — don't hand-craft SQL against `data/topics.db`.
- Statuses are exactly: `pending`, `highlighted`, `declined`. Decisions are
  made by the hosts in the UI, not by you.
