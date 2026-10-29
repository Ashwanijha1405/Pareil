// Pareil UI (dark): preloader -> landing -> running (live SSE trace) -> results.
// No framework, no build step. API data reaches the DOM only through textContent.
"use strict";

const $ = (id) => document.getElementById(id);
const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const state = { report: null, demo: null, filter: "all", query: "", heroIndex: 0, runs: 0, es: null };

function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) el.append(c.nodeType ? c : String(c));
  return el;
}
function icon(paths, cls = "") {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  if (cls) svg.setAttribute("class", cls);
  for (const d of [].concat(paths)) {
    const p = document.createElementNS(ns, "path");
    p.setAttribute("d", d);
    svg.append(p);
  }
  return svg;
}
const ICON = {
  check: "M20 6L9 17l-5-5",
  retry: ["M21 12a9 9 0 1 1-3-6.7", "M21 4v5h-5"],
  warn: ["M12 8v5", "M12 16.5v.5", "M10.3 3.9L2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"],
  arrow: "M5 12h14M13 6l6 6-6 6",
  down: "M12 5v14M6 13l6 6 6-6",
  x: "M18 6L6 18M6 6l12 12",
};

// ---- formatting ---------------------------------------------------------------------------
const symOf = (r) => r.symbol;
const tiers = (r, n) => (n ? symOf(r).repeat(n) : "?");
function money(r, v, digits = 0) {
  const locale = r.currency === "INR" ? "en-IN" : "en-US";
  return symOf(r) + Number(v).toLocaleString(locale, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
const hhmm = (iso) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const shortName = (name) => name.split(/ [-|·] | \| /)[0];
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

// ---- cafe & restaurant images -------------------------------------------------------------
const PLACE_IMAGES = {
  "carbone": "/images/carbone.jpg",
  "via carota": "/images/via-carota.jpg",
  "ci siamo": "/images/ci-siamo.jpg",
  "raoul's": "/images/raouls.jpg",
  "raouls": "/images/raouls.jpg",
  "le gigot": "/images/le-gigot.jpg",
  "joseph leonard": "/images/joseph-leonard.jpg",
  "katz's": "/images/katzs.jpg",
  "katzs": "/images/katzs.jpg",
  "katz's delicatessen": "/images/katzs.jpg",
  "russ & daughters": "/images/russ-and-daughters.jpg",
  "joe's pizza": "/images/joes-pizza.jpg",
  "levain bakery": "/images/levain-bakery.jpg",
  "au cheval": "/images/au-cheval.jpg",
  "misi": "/images/misi.jpg",
  "malaparte": "/images/malaparte.jpg",
  "los tacos": "/images/los-tacos.jpg",
  "the fatty bao": "/images/fatty-bao.jpg",
  "fatty bao": "/images/fatty-bao.jpg",
  "araku": "/images/araku-coffee.jpg",
  "araku coffee": "/images/araku-coffee.jpg",
  "hole in the wall": "/images/hole-in-the-wall.jpg",
  "matteo coffea": "/images/matteo-coffea.jpg",
  "sharief bhai": "/images/sharief-bhai.jpg",
  "toit": "/images/toit.jpg",
  "smoke house deli": "/images/smoke-house-deli.jpg",
  "leon's burgers": "/images/leons-burgers.jpg",
  "thai basil": "/images/thai-basil.jpg",
  "daily sushi": "/images/daily-sushi.jpg",
};

function getPlaceImage(name = "", concepts = [], kind = "") {
  const low = String(name).toLowerCase().replace(/['’]/g, "");
  for (const [k, src] of Object.entries(PLACE_IMAGES)) {
    const kLow = k.replace(/['’]/g, "");
    if (low.includes(kLow) || kLow.includes(low)) return src;
  }
  const allTags = [low, ...(concepts || []), kind].join(" ").toLowerCase();
  if (/coffee|cafe|espresso|roast|bakery|croissant/i.test(allTags)) return "/images/sample-coffee.jpg";
  if (/pizza|italian|pasta|trattoria|risotto/i.test(allTags)) return "/images/via-carota.jpg";
  if (/beer|brew|pub|bar|cocktail|ale/i.test(allTags)) return "/images/sample-beer.jpg";
  if (/brunch|breakfast|waffle|pancake|egg/i.test(allTags)) return "/images/hole-in-the-wall.jpg";
  if (/burger|sandwich|wing|fry/i.test(allTags)) return "/images/leons-burgers.jpg";
  if (/deli|pastrami|bagel|smoke/i.test(allTags)) return "/images/katzs.jpg";
  if (/asian|sushi|thai|bao|noodle|ramen|dim sum/i.test(allTags)) return "/images/fatty-bao.jpg";
  if (/indian|biryani|curry|mughlai/i.test(allTags)) return "/images/sharief-bhai.jpg";
  if (/french|bistro/i.test(allTags)) return "/images/le-gigot.jpg";
  return "/images/cafe-default.jpg";
}

// ---- preloader ----------------------------------------------------------------------------
// Initial load only: 5.5s intro with skip button and cycling messages.
// Navigating between pages/views NEVER shows the preloader again.
const preloader = {
  shownAt: performance.now(),
  visible: true,
  timer: null,
  msgTimer: null,
  startIntro() {
    if (sessionStorage.getItem("pareil_preloaded")) {
      this.hide(0);
      return;
    }
    const msgs = [
      "reading the taste graph",
      "indexing culinary fingerprints",
      "matching price tier differentials",
      "curating your taste twins",
    ];
    let idx = 0;
    this.msgTimer = setInterval(() => {
      idx = (idx + 1) % msgs.length;
      const statusEl = $("pl-status");
      if (statusEl) {
        statusEl.style.opacity = "0";
        setTimeout(() => {
          statusEl.textContent = msgs[idx];
          statusEl.style.opacity = "1";
        }, 200);
      }
    }, 1400);

    // 5.5s intro duration
    this.timer = setTimeout(() => {
      this.hide(0);
    }, 5500);
  },
  show(text) {
    if (sessionStorage.getItem("pareil_preloaded")) return;
    clearTimeout(this.timer);
    clearInterval(this.msgTimer);
    const el = $("preloader");
    if (!el) return;
    $("pl-status").textContent = text || "reading the taste graph";
    el.classList.remove("play");
    void el.offsetWidth;
    el.classList.add("play");
    el.classList.remove("hide");
    document.body.classList.add("loading");
    this.visible = true;
    this.shownAt = performance.now();
  },
  hide(minMs = 0) {
    clearTimeout(this.timer);
    clearInterval(this.msgTimer);
    sessionStorage.setItem("pareil_preloaded", "1");
    const wait = Math.max(0, minMs - (performance.now() - this.shownAt));
    this.timer = setTimeout(() => {
      const el = $("preloader");
      if (el) {
        el.classList.add("hide");
        setTimeout(() => { el.style.display = "none"; }, 450);
      }
      document.body.classList.remove("loading");
      this.visible = false;
      show("landing");
    }, wait);
  },
};

// ---- views --------------------------------------------------------------------------------
function show(view) {
  for (const v of ["landing", "running", "results"]) $(v).hidden = v !== view;
  document.querySelectorAll(".nav-pills a").forEach((a) => a.toggleAttribute("aria-current", false));
  if (view === "landing") document.querySelector('.nav-pills a[href="#top"]').setAttribute("aria-current", "true");
  window.scrollTo({ top: 0, behavior: "instant" });
}

function showError(message) {
  show("landing");
  const visible = [...document.querySelectorAll("[data-error]")];
  visible.forEach((el) => { el.textContent = message; el.hidden = false; });
  document.getElementById("demo").scrollIntoView({ block: "center" });
  setButtons(false);
}
function clearErrors() {
  document.querySelectorAll("[data-error]").forEach((el) => (el.hidden = true));
}
function setButtons(busy) {
  document.querySelectorAll("[data-demo]").forEach((b) => (b.disabled = busy));
}

// ---- landing: demo status + live sample card ---------------------------------------------
async function loadDemos() {
  try {
    const demos = await (await fetch("/api/demos")).json();
    const ready = demos.filter((d) => d.ready);
    $("demo-status").textContent = ready.length
      ? `Demos open instantly as a replay of the run at ${hhmm(ready[0].ran_at)}; “Run live” calls Qloo again.`
      : "Demos run live right now (about a minute) while the instant replays warm up.";
    const nyc = demos.find((d) => d.id === "nyc");
    if (nyc && nyc.ready) fillSampleCard();
    else setTimeout(loadDemos, 15000);
  } catch {
    $("demo-status").textContent = "";
  }
}

async function fetchReplay(demo) {
  const res = await fetch("/api/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ demo }) });
  const data = await res.json();
  if (!res.ok || !data.replay) return null; // never start a live run just to decorate the page
  await new Promise((ok) => {
    const es = new EventSource(`/api/runs/${data.run_id}/events`);
    const end = () => { es.close(); ok(); };
    es.addEventListener("done", end);
    es.addEventListener("error", end);
  });
  const r = await fetch(`/api/runs/${data.run_id}/report`);
  return r.status === 200 ? r.json() : null;
}

async function fillSampleCard() {
  let report;
  try { report = await fetchReplay("nyc"); } catch { return; }
  const s = report && topSwaps(report)[0];
  if (!s) return;
  const p = s.picks[0];
  const card = $("sample-card");
  card.classList.add("updating");
  setTimeout(() => {
    card.querySelector(".label").textContent = "Real swap · NYC demo";
    $("sc-city").textContent = "New York";
    $("sc-from").textContent = shortName(s.qloo_name);
    $("sc-from-tier").textContent = tiers(report, s.tier);
    $("sc-from-meta").textContent = `${plural(s.visits, "visit")} this month · avg ${money(report, s.avg_bill)} a visit · rated ${s.rating.toFixed(1)}`;
    const fromImg = $("sc-from-img");
    if (fromImg) { fromImg.src = getPlaceImage(s.qloo_name); fromImg.alt = shortName(s.qloo_name); }
    $("sc-down").textContent = p.tiers_down >= 2 ? "two tiers down" : "one tier down";
    $("sc-to").textContent = p.name;
    $("sc-to-tier").textContent = tiers(report, p.price_level);
    $("sc-to-meta").textContent = [`Rated ${p.rating}`, ...p.shared.slice(0, 2)].join(" · ");
    const toImg = $("sc-to-img");
    if (toImg) { toImg.src = getPlaceImage(p.name, p.shared, s.kind); toImg.alt = p.name; }
    $("sc-why").replaceChildren(...driverSentence(p));
    $("sc-save").textContent = `≈ ${money(report, s.saving.monthly_half)}`;
    $("sc-note").textContent = `From the NYC demo run at ${hhmm(report.ran_at)} · if you swap 1 in 2 visits${s.saving.estimate ? " · estimate" : ""}`;
    card.classList.remove("updating");
  }, REDUCED ? 0 : 400);
}

function driverSentence(p) {
  const d = (p.drivers || []).slice(0, 2);
  if (!d.length) return ["A Qloo taste match for your places."];
  const parts = ["Matched on your taste for "];
  d.forEach((x, i) => {
    if (i) parts.push(" and ");
    parts.push(h("strong", {}, shortName(x.place)), ` (${x.percent}%)`);
  });
  parts.push(".");
  return parts;
}

// ---- starting runs ------------------------------------------------------------------------
async function startRun(body, headers, label) {
  clearErrors();
  setButtons(true);
  let res, data;
  try {
    res = await fetch("/api/runs", { method: "POST", headers, body });
    data = await res.json();
  } catch {
    return showError("Couldn't reach Pareil. Check your connection and try again.");
  }
  if (!res.ok) return showError(data.error || `Request failed (${res.status}).`);
  follow(data.run_id, label);
}

function runDemo(demo, live = false) {
  state.demo = demo;
  const label = demo === "nyc" ? "NYC demo" : "Bengaluru demo";
  startRun(JSON.stringify({ demo, live }), { "Content-Type": "application/json" }, label);
}

function uploadFile(file) {
  state.demo = null;
  if (!/\.csv$/i.test(file.name) && file.type && !/csv|text|excel/i.test(file.type)) {
    return showError("That doesn't look like a CSV. Export your statement as .csv and try again.");
  }
  if (file.size > 200_000) return showError("File too large: the limit is 200 KB (about 300 rows).");
  startRun(file, { "Content-Type": "text/csv" }, file.name);
}

// ---- running: live trace ------------------------------------------------------------------
function follow(runId, label) {
  state.runs += 1;
  if (state.es) state.es.close();

  show("running");
  $("timeline").replaceChildren();
  $("run-error").hidden = true;
  $("run-title").textContent = "Agent trace";
  $("run-sub").textContent = label;

  const es = new EventSource(`/api/runs/${runId}/events`);
  state.es = es;
  es.addEventListener("start", (e) => {
    const meta = JSON.parse(e.data);
    $("run-sub").textContent = meta.replayed_at ? `replay of ${hhmm(meta.replayed_at)} run` : "live · calling Qloo";
  });
  es.addEventListener("step", (e) => {
    const li = stepItem(JSON.parse(e.data));
    $("timeline").append(li);
    li.scrollIntoView({ block: "nearest" });
  });
  es.addEventListener("done", async () => {
    es.close();
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
    let message = "The connection to the run was lost. Go back and try again.";
    try { if (e.data) message = JSON.parse(e.data).error; } catch {}
    runError(message);
  });
}
function runError(message) {
  setButtons(false);
  $("run-title").textContent = "Run stopped";
  $("run-error").textContent = message;
  $("run-error").hidden = false;
}

const STEP_TEXT = {
  clean: "Cleaned merchant names", resolve: "Matched on Qloo", tier: "Price tier",
  twins: "Found taste twins", rank: "Ranked · rating floor applied", recover: "Recovery",
  dedupe: "One twin per merchant", explain: "Explanations · names verified",
};
function stepItem(ev) {
  const warn = ["error", "needs_review", "rejected", "budget_exhausted", "iteration_cap"].includes(ev.status);
  const recover = ev.step === "recover";
  const hard = recover && ev.status === "give_up" && /rated below/.test(ev.detail);
  const retry = recover || ["partial", "fallback"].includes(ev.status) || /fallback rule/.test(ev.detail);

  let title = [STEP_TEXT[ev.step] || ev.step];
  if (hard) title = ["Hard to beat: gave up on rating"];
  else if (recover && ev.tool === "code") title = ["Recovery → agent chose ", h("span", { class: "brass" }, ev.status)];
  else if (recover) title = ["Recovery · model choosing an action"];
  const main = h("span", { class: "t-text" }, ...title, ev.target ? ` · ${ev.target}` : "",
    h("span", { class: "t-sub" }, ev.status === "cached" ? `${ev.detail} (cached)` : ev.detail));

  const kind = warn ? "warn" : retry ? "retry" : "check";
  return h("li", { class: `t-new${retry && !warn ? " t-retry" : ""}${hard ? " t-hard" : ""}` },
    icon(ICON[kind], `ic-${kind}`), main,
    h("span", { class: "t-ms" }, ev.ms ? `${(ev.ms / 1000).toFixed(1)}s` : ""));
}

// ---- results ------------------------------------------------------------------------------
function topSwaps(r) {
  return r.swaps.filter((s) => s.picks.length).sort((a, b) => b.saving.monthly_half - a.saving.monthly_half);
}

function renderResults(report) {
  setButtons(false);
  state.report = report;
  state.heroIndex = 0;
  state.filter = "all";
  state.query = "";
  $("q").value = "";
  document.querySelectorAll("[data-filter]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.filter === "all")));

  $("data-chip").textContent = report.source;
  $("month-chip").textContent = new Date(report.period.first + "T00:00:00").toLocaleDateString("en-US", { month: "long", year: "numeric" });
  $("replay").hidden = !report.replayed_at;
  if (report.replayed_at) {
    $("replay-text").textContent = `Replayed from a run at ${hhmm(report.replayed_at)}`;
    $("run-live").hidden = !state.demo;
  }

  const sm = report.summary;
  $("headline-num").replaceChildren(`~${money(report, sm.monthly_saving_half)}`, h("small", {}, " / month"));
  $("headline-note").textContent = (sm.saving_is_estimate ? "Estimate · some tiers use a fallback average. " : "Estimate from your own bills. ")
    + `${plural(topSwaps(report).reduce((t, s) => t + s.picks.length, 0), "swap")} for ${plural(topSwaps(report).length, "place")} · rating floor: never lower.`;
  $("res-foot").textContent = `${report.source} · ${sm.qloo_calls} Qloo calls · places and ratings from Qloo · savings are estimates from your own spending`;

  renderHero();
  renderGrid();
  renderLists();
  renderHow();
  show("results");
}

function renderHero() {
  const r = state.report;
  const s = topSwaps(r)[0];
  const box = $("res-hero");
  if (!s) {
    box.replaceChildren(h("p", { class: "empty-hero" },
      r.already_budget.length ? "You're already eating on a budget. Nothing cheaper beat your places." : "No swap passed the quality filters for this month."));
    return;
  }
  const pool = [...s.picks, ...s.alternates];
  const p = pool[state.heroIndex];
  const last = state.heroIndex >= pool.length - 1;
  const origin = shortName(s.qloo_name);
  const originImg = getPlaceImage(origin);
  const twinImg = getPlaceImage(p.name, p.shared, s.kind);

  const copy = h("div", { class: "res-hero-copy" },
    h("p", { class: "eyebrow" }, `Biggest saving · ${state.heroIndex + 1} of ${pool.length}`),
    h("h2", { class: "h2" }, `Instead of ${origin}, `, h("span", { class: "em-brass" }, p.name), "."),
    h("div", { class: "chip-row" }, [...p.shared.slice(0, 3), p.label].filter(Boolean).map((c) => h("span", { class: "chip" }, c))),
    h("p", { class: "body" }, p.why),
    h("div", { class: "cta-row" },
      h("a", { class: "btn-brass", href: mapsUrl(p), target: "_blank", rel: "noopener" }, "See the swap", icon(ICON.arrow)),
      h("button", {
        type: "button", class: "btn-line", disabled: last, id: "not-my-vibe",
        "aria-label": last ? `No other twins for ${origin}` : `Not my vibe: show another twin for ${origin}`,
        onclick: () => { state.heroIndex += 1; renderHero(); renderGrid(); $("not-my-vibe").focus(); },
      }, icon(ICON.x), last ? "No more twins" : "Not my vibe")));

  const card = h("div", { class: "swapcard" },
    h("div", { class: "swapcard-head" }, h("span", { class: "label" }, "Your swap"), h("span", { class: "pill-line" }, r.currency === "INR" ? "Bengaluru" : "New York")),
    h("div", { class: "place place-with-img" },
      h("div", { class: "place-thumb-wrap" }, h("img", { class: "place-thumb", src: originImg, alt: origin, loading: "lazy" })),
      h("div", { class: "place-info" },
        h("div", { class: "place-row" }, h("span", { class: "place-name" }, origin), h("span", { class: "tiers muted-tiers" }, tiers(r, s.tier))),
        h("p", { class: "place-meta" }, `${plural(s.visits, "visit")} · avg ${money(r, s.avg_bill)} a visit · rated ${s.rating.toFixed(1)}`))),
    h("div", { class: "tier-divider" }, h("span"), icon(ICON.down), h("b", {}, p.tiers_down >= 2 ? "two tiers down" : "one tier down"), h("span")),
    h("div", { class: "place place-twin place-with-img" },
      h("div", { class: "place-thumb-wrap" }, h("img", { class: "place-thumb", src: twinImg, alt: p.name, loading: "lazy" })),
      h("div", { class: "place-info" },
        h("div", { class: "place-row" }, h("span", { class: "place-name" }, p.name), h("span", { class: "tiers brass" }, tiers(r, p.price_level))),
        h("p", { class: "place-meta" }, `Rated ${p.rating} vs ${s.rating.toFixed(1)}`),
        h("p", { class: "place-why" }, ...driverSentence(p)))),
    h("div", { class: "swapcard-foot" },
      h("div", {}, h("div", { class: "label-plain" }, "Estimated saving"),
        h("div", { class: "saving" }, `≈ ${money(r, s.saving.monthly_half)}`, h("small", {}, " / month"))),
      h("span", { class: "fine-note" }, `if you swap 1 in 2 visits${s.saving.estimate ? " · estimate" : ""}`)));

  box.replaceChildren(copy, card);
}

function mapsUrl(p) {
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${p.name} ${p.address}`)}`;
}
function matches(...texts) {
  const q = state.query.trim().toLowerCase();
  return !q || texts.some((t) => t && t.toLowerCase().includes(q));
}

function renderGrid() {
  const r = state.report;
  const hero = topSwaps(r)[0];
  const heroPick = hero ? [...hero.picks, ...hero.alternates][state.heroIndex] : null;
  const tiles = [];

  if (state.filter === "budget") {
    for (const a of r.already_budget) {
      if (!matches(a.qloo_name, a.merchant)) continue;
      const img = getPlaceImage(a.qloo_name, [], "budget");
      tiles.push(h("div", { class: "swap-tile tile-has-img" },
        h("div", { class: "tile-img-container" },
          h("img", { class: "tile-img", src: img, alt: a.qloo_name, loading: "lazy" }),
          h("span", { class: "chip chip-overlay" }, "Already budget-friendly")),
        h("div", { class: "tile-body" },
          h("p", { class: "tile-name" }, shortName(a.qloo_name)),
          h("div", { class: "tier-change" }, h("span", { class: "brass" }, tiers(r, a.tier))),
          h("p", { class: "tile-text" }, `${plural(a.visits, "visit")} · avg ${money(r, a.avg_bill)}`))));
    }
  } else {
    for (const s of topSwaps(r)) {
      if (state.filter !== "all" && s.kind !== state.filter) continue;
      for (const p of s.picks) {
        if (p === heroPick || !matches(p.name, s.qloo_name, s.merchant, ...p.shared)) continue;
        const img = getPlaceImage(p.name, p.shared, s.kind);
        const chipText = p.shared.slice(0, 2).join(" · ") || "Taste match";
        tiles.push(h("a", { class: "swap-tile tile-has-img", href: mapsUrl(p), target: "_blank", rel: "noopener",
          "aria-label": `${p.name}, instead of ${shortName(s.qloo_name)}. Opens a map.` },
          h("div", { class: "tile-img-container" },
            h("img", { class: "tile-img", src: img, alt: p.name, loading: "lazy" }),
            h("span", { class: "chip chip-overlay" }, chipText)),
          h("div", { class: "tile-body" },
            h("p", { class: "tile-name" }, p.name),
            h("p", { class: "tile-meta" }, `for ${shortName(s.qloo_name)}`, p.label ? h("span", { class: "tag-two" }, ` · ${p.label}`) : ""),
            h("div", { class: "tier-change" }, h("s", {}, tiers(r, s.tier)), icon(ICON.arrow), h("span", { class: "brass" }, tiers(r, p.price_level))),
            h("p", { class: "tile-text" }, `Rating ${s.rating.toFixed(1)} → ${p.rating}`),
            h("div", { class: "tile-save" }, `≈ ${money(r, s.saving.monthly_half)}`,
              h("small", {}, ` / month at ${shortName(s.qloo_name)}`)))));
      }
    }
  }
  $("swap-grid").replaceChildren(...tiles);
  $("swap-empty").hidden = tiles.length > 0;
}

function renderLists() {
  const rows = state.report.where_you_spent;
  const fill = (id, statuses, sub) => {
    const items = rows.filter((w) => statuses.includes(w.status));
    $(id).replaceChildren(...(items.length
      ? items.map((w) => h("li", { title: w.reason || null }, shortName(w.name), h("span", {}, sub(w))))
      : [h("li", { class: "none" }, "None")]));
  };
  const r = state.report;
  fill("list-hard", ["hard_to_beat", "no_match"], (w) => w.note);
  fill("list-budget", ["budget"], (w) => `${plural(w.visits, "visit")} · avg ${money(r, w.avg_bill)}`);
  fill("list-review", ["review"], (w) => w.note);
  fill("list-skipped", ["skipped"], (w) => `${plural(w.visits, "visit")} · ${money(r, w.avg_bill * w.visits)} total`);
}

function renderHow() {
  const calls = state.report.trace.filter((t) => t.meta && t.meta.endpoint);
  $("how-count").textContent = `${calls.length} Qloo calls`;
  $("how-list").replaceChildren(...calls.map((t) => {
    const m = t.meta;
    const params = [];
    if (m.query) params.push(`query="${m.query}"`);
    if (m["filter.location"]) params.push(`filter.location=${m["filter.location"]}`);
    if (m["filter.location.query"]) params.push(`filter.location.query="${m["filter.location.query"]}"`);
    if (m["filter.price_level.max"] !== undefined) params.push(`price_level.min=max=${m["filter.price_level.max"]}`);
    if (m["filter.tags"]) params.push(`filter.tags=${m["filter.tags"].map((x) => x.split(":").pop()).join(",")}`);
    if (m.signals) params.push(`signals=[${m.signals.map((s) => `${s.name}×${s.weight}`).join(", ")}]`);
    if (m["feature.explainability"]) params.push("explainability=true");
    return h("li", {},
      h("div", { class: "how-top" }, h("b", {}, `${m.endpoint}  ${t.target}`), h("span", {}, `${t.status} · ${t.ms}ms`)),
      h("p", { class: "how-params" }, params.join("  ")));
  }));
}

function initHeroJewelry() {
  const stage = $("hero-word-stage");
  const emblem = $("hero-jewelry-emblem");
  if (!stage || !emblem) return;

  emblem.classList.add("ambient-float");

  let rect = null;
  const updateRect = () => { rect = stage.getBoundingClientRect(); };
  window.addEventListener("resize", updateRect);
  window.addEventListener("scroll", updateRect, { passive: true });

  let targetX = 0;
  let targetY = 0;
  let currentX = 0;
  let currentY = 0;
  let isHovered = false;
  let rafId = null;

  function renderTilt() {
    if (isHovered) {
      currentX += (targetX - currentX) * 0.12;
      currentY += (targetY - currentY) * 0.12;
      emblem.style.transform = `perspective(1200px) rotateX(${currentX.toFixed(2)}deg) rotateY(${currentY.toFixed(2)}deg) scale3d(1.02, 1.02, 1.02)`;
    }
    rafId = requestAnimationFrame(renderTilt);
  }
  rafId = requestAnimationFrame(renderTilt);

  stage.addEventListener("mouseenter", () => {
    isHovered = true;
    emblem.classList.remove("ambient-float");
    updateRect();
  });

  stage.addEventListener("mousemove", (e) => {
    if (!rect) updateRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    const nx = (e.clientX - cx) / (rect.width / 2 || 1);
    const ny = (e.clientY - cy) / (rect.height / 2 || 1);
    targetX = Math.max(-10, Math.min(10, -ny * 9));
    targetY = Math.max(-14, Math.min(14, nx * 12));
  });

  stage.addEventListener("mouseleave", () => {
    isHovered = false;
    targetX = 0;
    targetY = 0;
    emblem.style.transform = "";
    emblem.classList.add("ambient-float");
  });
}

// ---- wiring -------------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  const linked = location.hash.slice(1); // /#nyc or /#blr opens a demo directly
  const deepLink = linked === "nyc" || linked === "blr";

  loadDemos();
  initHeroJewelry();

  const skipBtn = $("pl-skip");
  if (skipBtn) skipBtn.addEventListener("click", () => preloader.hide(0));

  if (deepLink) {
    preloader.hide(0);
    runDemo(linked);
  } else {
    preloader.startIntro();
  }

  document.querySelectorAll("[data-demo]").forEach((b) => b.addEventListener("click", () => runDemo(b.dataset.demo)));
  $("file").addEventListener("change", (e) => { const f = e.target.files[0]; e.target.value = ""; if (f) uploadFile(f); });
  document.querySelectorAll("[data-back]").forEach((b) => b.addEventListener("click", () => {
    if (state.es) state.es.close();
    setButtons(false);
    show("landing");
  }));
  $("new-analysis").addEventListener("click", () => { show("landing"); document.getElementById("demo").scrollIntoView(); });
  $("run-live").addEventListener("click", () => state.demo && runDemo(state.demo, true));
  $("q").addEventListener("input", (e) => { state.query = e.target.value; renderGrid(); });
  document.querySelectorAll("[data-filter]").forEach((b) => b.addEventListener("click", () => {
    state.filter = b.dataset.filter;
    document.querySelectorAll("[data-filter]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    renderGrid();
  }));
  // Nav links point at landing sections; from another view, switch back to the landing first.
  document.querySelectorAll("a[data-landing]").forEach((a) => a.addEventListener("click", (e) => {
    if (!$("landing").hidden) return;
    e.preventDefault();
    if (state.es) state.es.close();
    show("landing");
    document.querySelector(a.getAttribute("href")).scrollIntoView();
  }));
});
