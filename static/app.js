"use strict";

const TABS = ["pending", "highlighted", "declined", "all"];
const state = { tab: "pending", topics: [], counts: {}, fetch: null };

// -- tiny DOM helper ---------------------------------------------------------

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) node.setAttribute(k, v);
  }
  for (const child of children.flat()) {
    if (child !== null && child !== undefined) node.append(child);
  }
  return node;
}

// -- formatting --------------------------------------------------------------

function timeAgo(iso) {
  if (!iso) return "";
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso)) / 60000));
  if (mins < 60) return `${mins}m ago`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)}h ago`;
  return `${Math.round(mins / (60 * 24))}d ago`;
}

function elapsed(iso) {
  const secs = Math.max(0, Math.round((Date.now() - new Date(iso)) / 1000));
  return secs < 60 ? `${secs}s` : `${Math.floor(secs / 60)}m ${secs % 60}s`;
}

function hueFor(text) {
  let hash = 0;
  for (const ch of text) hash = (hash * 31 + ch.codePointAt(0)) % 360;
  return hash;
}

function hostOf(url) {
  try { return new URL(url).hostname.replace(/^www\./, ""); }
  catch { return ""; }
}

// -- api ---------------------------------------------------------------------

async function refresh() {
  try {
    const res = await fetch(`/api/topics?status=${state.tab}`);
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();
    state.topics = data.topics;
    state.counts = data.counts;
    document.getElementById("conn").classList.remove("down");
  } catch {
    document.getElementById("conn").classList.add("down");
    return;
  }
  render();
}

async function setStatus(id, status, reason) {
  const body = { status };
  if (reason !== undefined) body.reason = reason;
  await fetch(`/api/topics/${id}/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).catch(() => {});
  refresh();
}

// While a fetch job is running we watch its status every few seconds so the
// bar updates and the batch appears when it lands. The watch stops as soon
// as the job ends — at rest the page makes no requests until you click.
let watchTimer = null;
let wasBusy = false;

function scheduleWatch() {
  const s = state.fetch ? state.fetch.state : null;
  const busy = s === "running" || s === "cancelling";
  clearTimeout(watchTimer);
  watchTimer = busy ? setTimeout(refreshFetch, 2500) : null;
  if (wasBusy && !busy) { refresh(); loadJokes(); } // job done — pull in new topics & jokes
  wasBusy = busy;
}

async function refreshFetch() {
  try {
    const res = await fetch("/api/fetch");
    if (!res.ok) throw new Error(res.status);
    state.fetch = await res.json();
  } catch {
    if (wasBusy) { // server hiccup mid-run: keep watching so we recover
      clearTimeout(watchTimer);
      watchTimer = setTimeout(refreshFetch, 2500);
    }
    return;
  }
  renderFetch();
  scheduleWatch();
}

async function startFetch() {
  await fetch("/api/fetch", { method: "POST" }).catch(() => {});
  refreshFetch();
}

async function cancelFetch() {
  await fetch("/api/fetch/cancel", { method: "POST" }).catch(() => {});
  refreshFetch();
}

// -- rendering ---------------------------------------------------------------

function render() {
  renderTabs();
  renderList();
}

function renderTabs() {
  const nav = document.getElementById("tabs");
  nav.replaceChildren(...TABS.map((tab) =>
    el("button",
      { class: `tab${tab === state.tab ? " active" : ""}`,
        onclick: () => { state.tab = tab; refresh(); } },
      tab[0].toUpperCase() + tab.slice(1),
      el("span", { class: "count" }, String(state.counts[tab] ?? 0)))
  ));
}

function actionButtons(topic, reasonInput) {
  const note = () => reasonInput.value.trim();
  const highlight = el("button",
    { class: "btn highlight", onclick: () => setStatus(topic.id, "highlighted", note()) },
    "★ Highlight");
  const decline = el("button",
    { class: "btn decline", onclick: () => setStatus(topic.id, "declined", note()) },
    "✕ Decline");
  const reset = el("button",
    { class: "btn reset", onclick: () => setStatus(topic.id, "pending", "") },
    "↺ Reset");

  if (topic.status === "pending") return [highlight, decline];
  const badge = el("span", { class: `badge ${topic.status}` },
    topic.status === "highlighted" ? "★ Highlighted" : "✕ Declined");
  const save = el("button",
    { class: "btn small", onclick: () => setStatus(topic.id, topic.status, note()) },
    "Save note");
  return [badge, topic.status === "highlighted" ? decline : highlight, reset, save];
}

function card(topic, drafts) {
  const title = topic.url
    ? el("a", { href: topic.url, target: "_blank", rel: "noopener" }, topic.title)
    : topic.title;

  const metaParts = [topic.source || hostOf(topic.url), timeAgo(topic.created_at)]
    .filter(Boolean);

  const reasonInput = el("input", {
    class: "reason",
    type: "text",
    maxlength: "500",
    placeholder: topic.status === "pending"
      ? "why? (optional — the bot reads this next fetch)"
      : "note for the bot — why this call?",
  });
  reasonInput.dataset.id = String(topic.id);
  reasonInput.dataset.saved = topic.reason || "";
  reasonInput.value = topic.id in drafts ? drafts[topic.id] : (topic.reason || "");
  if (topic.status !== "pending") {
    reasonInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") setStatus(topic.id, topic.status, reasonInput.value.trim());
    });
  }

  return el("article", { class: `card ${topic.status}` },
    el("div", { class: "card-top" },
      topic.category
        ? el("span", { class: "chip",
            style: `background: hsl(${hueFor(topic.category)} 45% 38%)` },
            topic.category)
        : null,
      el("span", { class: "meta" }, metaParts.join(" · "))),
    el("h2", {}, title),
    topic.summary ? el("p", { class: "summary" }, topic.summary) : null,
    el("div", { class: "actions" }, actionButtons(topic, reasonInput), reasonInput));
}

function renderList() {
  const list = document.getElementById("list");
  // keep half-typed notes alive across re-renders (saved values defer to server)
  const drafts = {};
  for (const inp of list.querySelectorAll("input.reason")) {
    if (inp.value !== inp.dataset.saved) drafts[inp.dataset.id] = inp.value;
  }
  if (state.topics.length === 0) {
    list.replaceChildren(el("div", { class: "empty" },
      `No ${state.tab === "all" ? "" : state.tab + " "}topics. `,
      "Hit ", el("strong", {}, "⟳ Fetch new topics"), " to send the bot researching."));
    return;
  }
  list.replaceChildren(...state.topics.map((t) => card(t, drafts)));
}

function renderFetch() {
  const job = state.fetch;
  if (!job) return;
  const busy = job.state === "running" || job.state === "cancelling";

  const btn = document.getElementById("fetch-btn");
  btn.disabled = busy;
  btn.replaceChildren(
    el("span", { class: busy ? "glyph spin" : "glyph" }, "⟳"),
    busy ? " Fetching…" : " Fetch new topics");

  const bar = document.getElementById("fetchbar");
  if (job.state === "idle") {
    bar.className = "fetchbar hidden";
    return;
  }
  bar.className = `fetchbar ${job.state}`;

  const pieces = [];
  if (job.state === "running") {
    pieces.push(`Bot is researching new topics… ${elapsed(job.started_at)}`,
      el("button", { class: "btn small", onclick: cancelFetch }, "Cancel"));
  } else if (job.state === "cancelling") {
    pieces.push("Stopping…");
  } else if (job.state === "done") {
    const jk = job.jokes_added ? `, ${job.jokes_added} joke${job.jokes_added === 1 ? "" : "s"}` : "";
    pieces.push(`Last fetch added ${job.added} topic${job.added === 1 ? "" : "s"}${jk} · ${timeAgo(job.finished_at)}`);
  } else if (job.state === "cancelled") {
    pieces.push(`Fetch cancelled (${job.added ?? 0} added) · ${timeAgo(job.finished_at)}`);
  } else if (job.state === "error") {
    pieces.push(`Fetch failed${job.returncode != null ? ` (exit ${job.returncode})` : ""} · ${timeAgo(job.finished_at)}`);
  }
  if (job.log_tail && job.state !== "running" && job.state !== "cancelling") {
    pieces.push(el("details", { class: "fetchlog" },
      el("summary", {}, "bot output"),
      el("pre", {}, job.log_tail)));
  }
  bar.replaceChildren(...pieces);
}

// -- jokes carousel ----------------------------------------------------------
// Shows 3 jokes at a time, rotating every few minutes (client-side, no polling).
// Laugh keeps a joke (it may resurface on a later day); Pass bins it for good.

const JOKE_SLOTS = 3;
const JOKE_ROTATE_MS = 3 * 60 * 1000; // a few minutes per set of three
const jokesState = { pool: [], slots: [], cursor: 0 };

async function loadJokes() {
  try {
    const res = await fetch("/api/jokes");
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();
    jokesState.pool = data.jokes || [];
    jokesState.cursor = 0;
    fillJokeSlots();
  } catch {
    return; // leave whatever's on screen
  }
  renderJokes();
}

// Pull the next unused joke from the pool, cycling round; null if the pool is
// smaller than the slots it needs to fill.
function takeNextJoke(used) {
  const pool = jokesState.pool;
  if (pool.length === 0) return null;
  for (let tries = 0; tries < pool.length; tries++) {
    const joke = pool[jokesState.cursor % pool.length];
    jokesState.cursor++;
    if (!used.has(joke.id)) return joke;
  }
  return null;
}

function fillJokeSlots() {
  const used = new Set();
  jokesState.slots = [];
  for (let i = 0; i < JOKE_SLOTS; i++) {
    const joke = takeNextJoke(used);
    jokesState.slots.push(joke);
    if (joke) used.add(joke.id);
  }
}

function rotateJokes() {
  if (document.hidden || jokesState.pool.length <= JOKE_SLOTS) return;
  fillJokeSlots();
  renderJokes();
}

async function reactJoke(id, reaction) {
  fetch(`/api/jokes/${id}/react`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reaction }),
  }).catch(() => {});
  // resolve locally: drop it from the pool and refill just its slot
  jokesState.pool = jokesState.pool.filter((j) => j.id !== id);
  const used = new Set(jokesState.slots.filter(Boolean).map((j) => j.id));
  used.delete(id);
  jokesState.slots = jokesState.slots.map((j) => {
    if (j && j.id === id) {
      const next = takeNextJoke(used);
      if (next) used.add(next.id);
      return next;
    }
    return j;
  });
  renderJokes();
  if (jokesState.pool.length === 0) loadJokes();
}

function jokeCard(joke) {
  if (!joke) return null;
  return el("div", { class: "joke" },
    el("p", { class: "joke-text" }, joke.text),
    el("div", { class: "joke-actions" },
      el("button", { class: "btn laugh", onclick: () => reactJoke(joke.id, "laugh") }, "😂 Laugh"),
      el("button", { class: "btn pass", onclick: () => reactJoke(joke.id, "pass") }, "✕ Pass")));
}

function renderJokes() {
  const body = document.getElementById("jokes-body");
  const count = document.getElementById("jokes-count");
  count.textContent = jokesState.pool.length ? `(${jokesState.pool.length})` : "";
  const cards = jokesState.slots.map(jokeCard).filter(Boolean);
  if (cards.length === 0) {
    body.replaceChildren(el("div", { class: "jokes-empty" },
      "No jokes yet — they arrive with the next fetch."));
    return;
  }
  body.replaceChildren(...cards);
}

function toggleJokes(force) {
  const collapsed = force !== undefined ? force : !document.body.classList.contains("jokes-collapsed");
  document.body.classList.toggle("jokes-collapsed", collapsed);
  const btn = document.getElementById("jokes-toggle");
  btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
  btn.title = collapsed ? "show jokes" : "hide jokes";
  try { localStorage.setItem("jokesCollapsed", collapsed ? "1" : "0"); } catch {}
}

// -- autoscroll --------------------------------------------------------------
// Ping-pongs the whole page (the topic feed) down then back up at one constant,
// host-set speed. Toggle and speed both persist in localStorage. The sticky
// header — including these controls — stays put while the feed scrolls.

let autoOn = false;
// The slider is an abstract position (0..1000) mapped to speed on an
// exponential curve, so the lower half of the travel covers slow speeds with
// fine, granular control — handy for a gentle reading crawl on stream.
const SCROLL_MIN = 10;      // px/sec at the slow end of the slider
const SCROLL_MAX = 150;     // px/sec at the fast end
const SCROLL_STEPS = 1000;  // slider resolution
const SCROLL_DEFAULT = 20;  // px/sec, a calm default

let autoSpeed = SCROLL_DEFAULT; // pixels per second, same magnitude up and down
let autoDir = 1;                // 1 = down, -1 = up
let autoRAF = null;
let autoLastT = null;
let autoPos = 0;                // our own fractional scroll position, in px

function speedFromPos(pos) {
  return SCROLL_MIN * Math.pow(SCROLL_MAX / SCROLL_MIN, pos / SCROLL_STEPS);
}

function posFromSpeed(px) {
  const clamped = Math.min(SCROLL_MAX, Math.max(SCROLL_MIN, px));
  return Math.round(SCROLL_STEPS * Math.log(clamped / SCROLL_MIN) / Math.log(SCROLL_MAX / SCROLL_MIN));
}

function fmtSpeed(px) {
  return (px < 10 ? px.toFixed(1) : String(Math.round(px))) + " px/s";
}

// Pure step: where to scroll next, and which way to head, given the clamp.
// Reversing only flips direction, so the up and down passes share one speed.
function nextScroll(y, dir, speed, dt, max) {
  let ny = y + dir * speed * dt;
  if (ny >= max) return { y: max, dir: -1 };
  if (ny <= 0) return { y: 0, dir: 1 };
  return { y: ny, dir };
}

function autoMaxScroll() {
  return Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
}

function autoTick(t) {
  if (!autoOn) { autoRAF = null; return; }
  if (autoLastT === null) { autoLastT = t; autoPos = window.scrollY; } // sync on (re)start
  const dt = Math.min(0.1, (t - autoLastT) / 1000); // clamp gaps (e.g. tab was hidden)
  autoLastT = t;
  const max = autoMaxScroll();
  if (max > 0) {
    // Integrate our own fractional position rather than reading window.scrollY
    // back each frame: browsers (notably on Windows / HiDPI) quantize scrollY
    // to whole pixels, which would swallow the sub-pixel-per-frame motion at
    // slow speeds and make the real rate fall short of the advertised one.
    const step = nextScroll(autoPos, autoDir, autoSpeed, dt, max);
    autoDir = step.dir;
    autoPos = step.y;
    window.scrollTo(0, autoPos);
  }
  autoRAF = requestAnimationFrame(autoTick);
}

function applyAutoUI() {
  const btn = document.getElementById("autoscroll-toggle");
  btn.classList.toggle("active", autoOn);
  btn.setAttribute("aria-checked", autoOn ? "true" : "false");
}

function setAutoOn(on) {
  autoOn = on;
  applyAutoUI();
  try { localStorage.setItem("autoscrollOn", on ? "1" : "0"); } catch {}
  if (on && autoRAF === null) { autoLastT = null; autoRAF = requestAnimationFrame(autoTick); }
  if (!on && autoRAF !== null) { cancelAnimationFrame(autoRAF); autoRAF = null; }
}

function setAutoSpeed(px) {
  autoSpeed = px;
  const readout = document.getElementById("autoscroll-readout");
  if (readout) readout.textContent = fmtSpeed(px);
  try { localStorage.setItem("autoscrollSpeed", String(Math.round(px * 100) / 100)); } catch {}
}

// -- boot --------------------------------------------------------------------

function syncAll() {
  refresh();
  refreshFetch();
  loadJokes();
}

document.getElementById("fetch-btn").addEventListener("click", startFetch);
document.getElementById("refresh-btn").addEventListener("click", syncAll);
document.getElementById("jokes-toggle").addEventListener("click", () => toggleJokes());
try { if (localStorage.getItem("jokesCollapsed") === "1") toggleJokes(true); } catch {}
setInterval(rotateJokes, JOKE_ROTATE_MS);

const autoRange = document.getElementById("autoscroll-speed");
let bootSpeed = SCROLL_DEFAULT;
try {
  const saved = parseFloat(localStorage.getItem("autoscrollSpeed"));
  if (!Number.isNaN(saved)) bootSpeed = saved;
} catch {}
autoRange.value = String(posFromSpeed(bootSpeed));               // place the notch
setAutoSpeed(speedFromPos(parseInt(autoRange.value, 10)));       // sync speed + readout to it
document.getElementById("autoscroll-toggle").addEventListener("click", () => setAutoOn(!autoOn));
autoRange.addEventListener("input", () => setAutoSpeed(speedFromPos(parseInt(autoRange.value, 10))));
try { setAutoOn(localStorage.getItem("autoscrollOn") === "1"); } catch { applyAutoUI(); }

// one re-sync when you come back to the tab — not a poll
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) syncAll();
});
syncAll();
