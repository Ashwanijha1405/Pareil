// Pareil UI: start -> running (live SSE trace) -> results. No framework, no build step.
// All data from the API goes into the DOM through textContent, never innerHTML.
"use strict";

const TILE_COLORS = [
  ["#26302A", "#C9D3C6"], ["#2B2723", "#D9D2C4"], ["#23302A", "#C9D3C6"],
  ["#2E2A30", "#D6D0DA"], ["#34312B", "#D9D2C4"],
];
const STEP_TITLES = {
  clean: "Cleaning merchant names", resolve: "Finding the place in Qloo", tier: "Price tier",
  twins: "Asking Qloo for taste twins", rank: "Quality filters", recover: "Recovery",
  dedupe: "One twin per merchant", explain: "Writing the why",
};
const ICONS = {
  check: "M20 6L9 17l-5-5",
  retry: "M3 12a9 9 0 0 1 15.5-6.3L21 8M21 3v5h-5M21 12a9 9 0 0 1-15.5 6.3L3 16M3 21v-5h5",
  warn: "M12 8v5M12 16.5v.5M10.3 3.9L2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
};

const $ = (id) => document.getElementById(id);
const state = { report: null, demo: null, filter: "all", query: "", heroIndex: 0, source: null };

function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style") for (const [p, val] of Object.entries(v)) el.style.setProperty(p, val);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) el.append(c.nodeType ? c : String(c));
  return el;
}
function icon(path, cls = "") {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  if (cls) svg.setAttribute("class", cls);
  const p = document.createElementNS(ns, "path");
  p.setAttribute("d", path);
  svg.append(p);
  return svg;
}

// ---- formatting --------------------------------------------------------------------------
const sym = () => state.report.symbol;
const tiers = (n) => (n ? sym().repeat(n) : "?");
function money(v, digits = 0) {
  const locale = state.report.currency === "INR" ? "en-IN" : "en-US";
  return sym() + Number(v).toLocaleString(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
function hhmm(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
const shortName = (name) => name.split(/ [-|·] | \| /)[0];

// ---- states ------------------------------------------------------------------------------
function show(id) {
  for (const s of ["start", "running", "results"]) $(s).hidden = s !== id;
  window.scrollTo({ top: 0 });
}

async function loadDemos() {
  try {
    const demos = await (await fetch("/api/demos")).json();
    for (const d of demos) {
      const el = document.querySelector(`[data-status="${d.id}"]`);
      if (el) el.textContent = d.ready ? `Instant replay · ran at ${hhmm(d.ran_at)}` : "Runs live (about a minute)";
    }
  } catch {
    document.querySelectorAll("[data-status]").forEach((el) => (el.textContent = "Start"));
  }
}

async function startRun(body, headers, label) {
  $("start-error").hidden = true;
  let res, data;
  try {
    res = await fetch("/api/runs", { method: "POST", headers, body });
    data = await res.json();
  } catch {
    return startError("Couldn't reach Pareil. Check your connection and try again.");
  }
  if (!res.ok) return startError(data.error || `Request failed (${res.status}).`);
  follow(data.run_id, label);
}
function startError(message) {
  show("start");
  $("start-error").textContent = message;
  $("start-error").hidden = false;
}

function runDemo(demo, live = false) {
  state.demo = demo;
  const label = demo === "nyc" ? "NYC demo" : "Bengaluru demo";
  startRun(JSON.stringify({ demo, live }), { "Content-Type": "application/json" }, label);
}

function uploadFile(file) {
  state.demo = null;
  if (file.size > 200_000) return startError("File too large: the limit is 200 KB.");
  startRun(file, { "Content-Type": "text/csv" }, file.name);
}

// ---- running: live trace -----------------------------------------------------------------
function follow(runId, label) {
  show("running");
  $("timeline").replaceChildren();
  $("run-error").hidden = true;
  $("run-back").hidden = true;
  $("run-title").textContent = "Working on it";
  $("run-sub").textContent = label;
  let count = 0;

  const es = new EventSource(`/api/runs/${runId}/events`);
  es.addEventListener("start", (e) => {
    const meta = JSON.parse(e.data);
    $("run-sub").textContent = meta.replayed_at
      ? `${meta.source} · replaying the run from ${hhmm(meta.replayed_at)}`
      : `${meta.source} · live: calling Qloo now`;
  });
  es.addEventListener("step", (e) => {
    count += 1;
    $("run-count").textContent = `${count} step${count === 1 ? "" : "s"}`;
    const li = stepItem(JSON.parse(e.data));
    $("timeline").append(li);
    li.scrollIntoView({ block: "nearest" });
  });
  es.addEventListener("done", async () => {
    es.close();
    $("run-title").textContent = "Done";
    try {
      const res = await fetch(`/api/runs/${runId}/report`);
      if (!res.ok) throw new Error((await res.json()).error || `HTTP ${res.status}`);
      renderResults(await res.json());
    } catch (err) {
      runError(`Couldn't load the report: ${err.message}`);
    }
  });
  es.addEventListener("error", (e) => {
    es.close();
    let message = "The connection to the run was lost.";
    try { if (e.data) message = JSON.parse(e.data).error; } catch {}
    runError(message);
  });
}
function runError(message) {
  $("run-title").textContent = "Something went wrong";
  $("run-error").textContent = message;
  $("run-error").hidden = false;
  $("run-back").hidden = false;
}

function stepItem(ev) {
  const bad = ["error", "needs_review", "rejected", "budget_exhausted", "iteration_cap"].includes(ev.status);
  const retry = ["partial", "fallback"].includes(ev.status) || ev.detail.includes("decided by fallback rule");
  const recover = ev.step === "recover";
  let title = STEP_TITLES[ev.step] || ev.step;
  let detail = ev.detail;
  if (recover && ev.tool === "code") {
    title = ev.status === "give_up" && /rated below/.test(ev.detail)
      ? "Hard to beat: gave up on rating"
      : `Recovery: ${ev.status.replaceAll("_", " ")}`;
  } else if (ev.status === "cached") {
    detail += " (cached)";
  }
  const kind = bad ? "warn" : retry ? "retry" : "check";
  return h("li", { class: `step ${kind}${recover ? " recover" : ""}` },
    h("span", { class: "step-icon" }, icon(ICONS[kind])),
    h("div", {},
      h("div", { class: "step-title" }, title, ev.target ? ` · ${ev.target}` : ""),
      h("div", { class: "step-detail" }, detail)),
    h("span", { class: "step-ms" }, ev.ms ? `${(ev.ms / 1000).toFixed(1)} s` : ""));
}

// ---- results -----------------------------------------------------------------------------
function swapsWithPicks() {
  return state.report.swaps.filter((s) => s.picks.length);
}
function heroSwap() {
  return [...swapsWithPicks()].sort((a, b) => b.saving.monthly_half - a.saving.monthly_half)[0] || null;
}

function renderResults(report) {
  state.report = report;
  state.heroIndex = 0;
  state.filter = "all";
  state.query = "";
  $("q").value = "";
  document.querySelectorAll("[data-filter]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.filter === "all")));

  const first = new Date(report.period.first + "T00:00:00");
  $("month-chip").textContent = first.toLocaleDateString("en-US", { month: "long", year: "numeric" });
  const [title, sub] = report.source.split(" · ");
  $("data-title").textContent = title;
  $("data-sub").textContent = sub || "";
  $("data-badge").textContent = report.currency === "INR" ? "BL" : title.startsWith("NYC") ? "NY" : "You";
  $("foot-source").textContent = report.source;

  $("replay-bar").hidden = !report.replayed_at;
  if (report.replayed_at) {
    $("replay-text").textContent = `Replayed from a run at ${hhmm(report.replayed_at)}. Nothing was called just now.`;
    $("run-live").hidden = !state.demo;
  }

  renderTop();
  renderWhere();
  renderHero();
  renderSummary();
  renderMore();
  renderHow();
  show("results");
}

function tileColor(i) {
  const [bg, soft] = TILE_COLORS[i % TILE_COLORS.length];
  return { background: bg, "--tile-soft": soft };
}
function mapsUrl(p) {
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${p.name} ${p.address}`)}`;
}

function renderTop() {
  const top = [...swapsWithPicks()].sort((a, b) => b.saving.monthly_half - a.saving.monthly_half).slice(0, 2);
  $("top-swaps").replaceChildren(...top.map((s, i) => {
    const p = s.picks[0];
    return h("a", { class: "dark top-tile", href: mapsUrl(p), target: "_blank", rel: "noopener", style: tileColor(i) },
      h("div", { class: "tile-kicker" }, `For ${shortName(s.qloo_name)}`),
      h("div", { class: "tile-row" },
        h("span", { class: "tile-name" }, p.name),
        h("span", { class: "tile-meta" }, `${tiers(s.tier)} → ${tiers(p.price_level)}`)),
      h("div", { class: "tile-foot" }, `≈ ${money(s.saving.monthly_half, 2)} / mo · rated ${p.rating}`));
  }));
  if (!top.length) $("top-swaps").append(h("p", { class: "muted small" }, "No swaps passed the quality filters."));
}

const STATUS_LABEL = { swap: "Swap", hard_to_beat: "Hard to beat", no_match: "No match", budget: "", review: "Needs review", skipped: "Skipped" };
const WHERE_LIMIT = 8;
function renderWhere(all = false) {
  const rows = state.report.where_you_spent;
  const shown = all ? rows : rows.slice(0, WHERE_LIMIT);
  $("where").replaceChildren(...shown.map((w) => {
    const sub = w.status === "swap" ? `${w.visits} visit${w.visits === 1 ? "" : "s"} · avg ${money(w.avg_bill)}` : w.note;
    const status = w.status === "budget"
      ? h("span", { class: "status", role: "img", "aria-label": "Budget-friendly" }, icon("M20 6L9 17l-5-5"))
      : h("span", { class: `status ${w.status}` }, STATUS_LABEL[w.status]);
    return h("li", { title: w.reason || null },
      h("span", { class: "initial", "aria-hidden": "true" }, shortName(w.name).replace(/^the /i, "").charAt(0).toUpperCase()),
      h("span", { class: "where-text" }, h("span", { class: "where-name" }, shortName(w.name)), h("span", { class: "where-sub" }, sub)),
      status);
  }));
  const more = rows.length - shown.length;
  if (more > 0) {
    $("where").append(h("li", { class: "where-more" },
      h("button", { type: "button", class: "btn-small", onclick: () => renderWhere(true) }, `Show all ${rows.length}`)));
  }
}

function renderHero() {
  const s = heroSwap();
  const hero = $("hero");
  if (!s) {
    const budget = state.report.already_budget.length;
    hero.replaceChildren(h("p", { class: "hero-empty" },
      budget ? "You're already eating on a budget. Nothing cheaper beat your places." : "No swaps passed the quality filters."));
    return;
  }
  const pool = [...s.picks, ...s.alternates];
  const p = pool[state.heroIndex];
  const last = state.heroIndex >= pool.length - 1;
  const chips = ["Biggest saving", ...p.shared.slice(0, 2), `${tiers(s.tier)} → ${tiers(p.price_level)}`];
  if (p.label) chips.push(p.label);

  hero.replaceChildren(
    h("div", { class: "hero-ghost", "aria-hidden": "true" }, p.name),
    h("div", { class: "hero-chips" }, chips.map((c) => h("span", { class: "hero-chip" }, c))),
    h("div", { class: "hero-body" },
      h("div", { class: "hero-main" },
        h("p", { class: "hero-instead" }, `Instead of ${shortName(s.qloo_name)}`),
        h("h1", { class: "hero-name" }, p.name),
        h("p", { class: "hero-why" }, p.why),
        h("p", { class: "hero-rating" }, `Rated ${p.rating} vs ${shortName(s.qloo_name)}'s ${s.rating.toFixed(1)}`),
        h("div", { class: "hero-actions" },
          h("a", { class: "btn-light", href: mapsUrl(p), target: "_blank", rel: "noopener" },
            icon("M5 12h14M13 6l6 6-6 6"), "See the swap"),
          h("button", {
            type: "button", class: "btn-outline", disabled: last,
            "aria-label": last ? "No other twins for this place" : `Not my vibe: show another twin for ${shortName(s.qloo_name)}`,
            onclick: () => { state.heroIndex += 1; renderHero(); renderMore(); $("hero").querySelector(".btn-outline")?.focus(); },
          }, icon("M18 6L6 18M6 6l12 12"), last ? "No more twins" : "Not my vibe"))),
      h("div", { class: "hero-save" },
        h("div", { class: "hero-amount" }, `≈ ${money(s.saving.monthly_half)}`),
        h("div", { class: "hero-save-sub" }, `a month, if you swap 1 in 2 visits${s.saving.estimate ? " (estimate)" : ""}`),
        h("div", { class: "dots", "aria-hidden": "true" }, pool.map((_, i) => h("span", { class: i === state.heroIndex ? "on" : "" }))))));
}

function renderSummary() {
  const sm = state.report.summary;
  const withPicks = swapsWithPicks();
  const n = withPicks.reduce((t, s) => t + s.picks.length, 0);
  $("sum-save").textContent = `≈ ${money(sm.monthly_saving_half)} / mo`;
  $("sum-est").textContent = sm.saving_is_estimate ? "estimate · some tiers use a fallback average" : "from your own bills";
  $("sum-swaps").textContent = `${n} for ${withPicks.length} place${withPicks.length === 1 ? "" : "s"}`;
}

function matchesQuery(...texts) {
  const q = state.query.trim().toLowerCase();
  return !q || texts.some((t) => t && t.toLowerCase().includes(q));
}

function renderMore() {
  const hero = heroSwap();
  const heroPick = hero ? [...hero.picks, ...hero.alternates][state.heroIndex] : null;
  let tiles = [];
  if (state.filter === "budget") {
    tiles = state.report.already_budget
      .filter((a) => matchesQuery(a.qloo_name, a.merchant))
      .map((a, i) => h("div", { class: "dark more-tile", style: tileColor(i) },
        h("span", { class: "more-chip" }, "Already budget-friendly"),
        h("span", {}, h("span", { class: "tile-name" }, shortName(a.qloo_name)),
          h("span", { class: "more-sub" }, `${a.visits} visits · avg ${money(a.avg_bill)} · ${tiers(a.tier)}`))));
  } else {
    let i = 0;
    for (const s of swapsWithPicks()) {
      if (state.filter !== "all" && s.kind !== state.filter) continue;
      for (const p of s.picks) {
        if (p === heroPick || !matchesQuery(p.name, s.qloo_name, s.merchant, ...p.shared)) continue;
        tiles.push(h("a", { class: "dark more-tile", href: mapsUrl(p), target: "_blank", rel: "noopener", style: tileColor(i++) },
          h("span", { class: "more-chip" }, p.shared.slice(0, 2).join(" · ") || "Taste match"),
          h("span", {}, h("span", { class: "tile-name" }, p.name),
            h("span", { class: "more-sub" }, `for ${shortName(s.qloo_name)} · ${tiers(s.tier)} → ${tiers(p.price_level)} · ${p.rating}`))));
      }
    }
  }
  $("more-grid").replaceChildren(...tiles);
  $("more-empty").hidden = tiles.length > 0;
}

function renderHow() {
  const calls = state.report.trace.filter((t) => t.meta && t.meta.endpoint);
  $("how-count").textContent = `· ${calls.length} Qloo calls`;
  $("how-list").replaceChildren(...calls.map((t) => {
    const m = t.meta;
    const params = [];
    if (m.query) params.push(`query=${m.query}`);
    if (m["filter.location"]) params.push(`filter.location=${m["filter.location"]}`);
    if (m["filter.location.query"]) params.push(`filter.location.query=${m["filter.location.query"]}`);
    if (m["filter.price_level.min"] !== undefined) params.push(`price_level min=max=${m["filter.price_level.max"]}`);
    if (m["filter.tags"]) params.push(`filter.tags=${m["filter.tags"].map((x) => x.split(":").pop()).join(",")}`);
    if (m.signals) params.push(`signals=${m.signals.map((s) => `${s.name} ×${s.weight}`).join(", ")}`);
    if (m["feature.explainability"]) params.push("explainability=on");
    return h("li", { class: "how-item" },
      h("div", { class: "how-top" },
        h("span", { class: "how-endpoint" }, `${m.endpoint} · ${t.target}`),
        h("span", { class: "muted" }, `${t.status} · ${t.ms} ms`)),
      h("p", { class: "how-params" }, params.join(" · ")));
  }));
}

// ---- wiring ------------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  loadDemos();
  const linked = location.hash.slice(1);  // pareil.app/#nyc opens the NYC demo directly
  if (linked === "nyc" || linked === "blr") runDemo(linked);
  document.querySelectorAll("[data-demo]").forEach((b) => b.addEventListener("click", () => runDemo(b.dataset.demo)));
  $("file").addEventListener("change", (e) => { const f = e.target.files[0]; e.target.value = ""; if (f) uploadFile(f); });
  $("run-back").addEventListener("click", () => show("start"));
  $("new-run").addEventListener("click", () => { show("start"); loadDemos(); });
  $("run-live").addEventListener("click", () => state.demo && runDemo(state.demo, true));
  $("q").addEventListener("input", (e) => { state.query = e.target.value; renderMore(); });
  document.querySelectorAll("[data-filter]").forEach((b) => b.addEventListener("click", () => {
    state.filter = b.dataset.filter;
    document.querySelectorAll("[data-filter]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    renderMore();
  }));
  document.querySelectorAll("[data-nav]").forEach((a) => a.addEventListener("click", (e) => {
    const nav = a.dataset.nav;
    document.querySelectorAll(".rail-btn").forEach((x) => x.removeAttribute("aria-current"));
    if (a.classList.contains("rail-btn")) a.setAttribute("aria-current", "page");
    if (nav === "home" || nav === "upload" || !state.report) {
      e.preventDefault();
      show("start");
      if (nav === "upload") $("file").click();
    } else if (nav === "how") {
      $("how").open = true;
    }
  }));
});
