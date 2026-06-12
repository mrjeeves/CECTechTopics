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

async function setStatus(id, status) {
  await fetch(`/api/topics/${id}/status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  }).catch(() => {});
  refresh();
}

async function refreshFetch() {
  try {
    const res = await fetch("/api/fetch");
    if (!res.ok) throw new Error(res.status);
    state.fetch = await res.json();
  } catch {
    return;
  }
  renderFetch();
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

function actionButtons(topic) {
  const highlight = el("button",
    { class: "btn highlight", onclick: () => setStatus(topic.id, "highlighted") },
    "★ Highlight");
  const decline = el("button",
    { class: "btn decline", onclick: () => setStatus(topic.id, "declined") },
    "✕ Decline");
  const reset = el("button",
    { class: "btn reset", onclick: () => setStatus(topic.id, "pending") },
    "↺ Reset");

  if (topic.status === "pending") return [highlight, decline];
  const badge = el("span", { class: `badge ${topic.status}` },
    topic.status === "highlighted" ? "★ Highlighted" : "✕ Declined");
  return [badge, topic.status === "highlighted" ? decline : highlight, reset];
}

function card(topic) {
  const title = topic.url
    ? el("a", { href: topic.url, target: "_blank", rel: "noopener" }, topic.title)
    : topic.title;

  const metaParts = [topic.source || hostOf(topic.url), timeAgo(topic.created_at)]
    .filter(Boolean);

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
    el("div", { class: "actions" }, actionButtons(topic)));
}

function renderList() {
  const list = document.getElementById("list");
  if (state.topics.length === 0) {
    list.replaceChildren(el("div", { class: "empty" },
      `No ${state.tab === "all" ? "" : state.tab + " "}topics. `,
      "Hit ", el("strong", {}, "⟳ Fetch new topics"), " to send the bot researching."));
    return;
  }
  list.replaceChildren(...state.topics.map(card));
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
    pieces.push(`Last fetch added ${job.added} topic${job.added === 1 ? "" : "s"} · ${timeAgo(job.finished_at)}`);
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

// -- boot --------------------------------------------------------------------

document.getElementById("fetch-btn").addEventListener("click", startFetch);
refresh();
refreshFetch();
setInterval(() => { if (!document.hidden) refresh(); }, 5000);
setInterval(() => { if (!document.hidden) refreshFetch(); }, 2000);
