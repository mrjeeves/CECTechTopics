"use strict";

const TABS = ["pending", "highlighted", "declined", "all"];
const state = { tab: "pending", topics: [], counts: {} };

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
      "Ask the bot for a batch: ", el("code", {}, 'claude "find new topics"')));
    return;
  }
  list.replaceChildren(...state.topics.map(card));
}

// -- boot --------------------------------------------------------------------

refresh();
setInterval(() => { if (!document.hidden) refresh(); }, 5000);
