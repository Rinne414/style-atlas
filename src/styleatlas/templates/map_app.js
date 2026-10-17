// Web-app features (search, editing, votes, export) and start-up. Joined after map.js into
// one module script by report.render_html, so it shares map.js's scope; the start-up lines
// run last, once every declaration in both files exists.

const STATUS_FADE_MS = 8000;  // over the group view a message clears itself (it covers pictures)
let statusTimer = null, statusCount = 0;
function setStatus(msg) {
  $("status").textContent = msg || "";
  clearTimeout(statusTimer);
  const mine = ++statusCount;  // a later message (or an "open folder" button added to this one) keeps its own
  if (msg && document.body.classList.contains("gv-open")) {
    statusTimer = setTimeout(() => { if (statusCount === mine) $("status").replaceChildren(); }, STATUS_FADE_MS);
  }
  if (!DATA.live) toast(msg);  // a shared map has no bottom bar: show the message for a moment
}

const TOAST_MS = 6000;
let toastTimer = null;
function toast(msg) {
  let el = document.getElementById("toast");
  if (!el) {
    el = document.createElement("div"); el.id = "toast"; el.setAttribute("role", "status");
    document.querySelector("main").append(el);
  }
  el.textContent = msg || ""; el.hidden = !msg;
  clearTimeout(toastTimer);
  if (msg) toastTimer = setTimeout(() => { el.hidden = true; }, TOAST_MS);
}

// A button after a status message that names a file or folder in the output folder.
function fileName(path) { return String(path).split(/[\\/]/).pop(); }  // the folder: "open folder"

function addOpenFolder() {
  const b = document.createElement("button");
  b.textContent = t("openFolder"); b.style.marginLeft = "8px";
  b.addEventListener("click", () => post("api/open_output", "{}", "application/json").catch((e) => setStatus(String(e.message || e))));
  $("status").append(b);
}

async function post(url, body, type) {
  const r = await fetch(url, { method: "POST", body,
    headers: { "X-Style-Atlas": "1", "Content-Type": type } });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
  return j;
}

const MAX_QUERY_IMAGES = 32;

function toBase64(file) {
  return new Promise((ok, fail) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result).split(",")[1]);
    r.onerror = () => fail(r.error);
    r.readAsDataURL(file);
  });
}

// One image: nearest styles. Several: searched as one style (a model learned from 3 up).
async function searchFiles(fileList) {
  const files = [...(fileList || [])].filter((f) => f.type.startsWith("image/")).slice(0, MAX_QUERY_IMAGES);
  if (!files.length) return;
  setStatus(t("searching"));
  try {
    const within = tagOnly && tagOnly.hits.length ? tagOnly : null;  // a #tag filter is on
    const r = files.length === 1 && !within
      ? await post("api/search", files[0], files[0].type)  // {hits}: one image is no batch
      : await post("api/search_set", JSON.stringify({ images: await Promise.all(files.map(toBase64)),
        ...(within ? { only: within.hits } : {}) }), "application/json");
    setStatus(within ? t("withinTag").replace("{t}", within.tag).replace("{n}", within.hits.length) : "");
    showSearch(files, r.hits, r.fit, r.folders, r.copies, r.folded);
  } catch (e) { setStatus(String(e.message || e)); }
}

const FIT_BATCH = 8;

function fitSummary(fit) {  // a batch's verdict: the share that falls inside a group's range
  const box = document.createElement("div"); box.className = "kv";
  const fits = fit.filter((f) => f.fits);
  const counts = {};
  fits.forEach((f) => { counts[f.group] = (counts[f.group] || 0) + 1; });
  const where = Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([g, n]) => `${clusterName(Number(g))} ${n}`).join(" · ");
  const share = fits.length / fit.length;
  // as `sort`: under FIT_BATCH images the share says little (docs/BENCHMARKS.md)
  const verdict = fit.length < FIT_BATCH ? "fitFew" : share > 0.5 ? "fitYes" : share <= 0.25 ? "fitNo" : "fitSome";
  box.textContent = t("fitLine").replace("{k}", fits.length).replace("{n}", fit.length) + (where ? ` (${where})` : "") + " — " + t(verdict);
  const note = document.createElement("div"); note.className = "meta"; note.textContent = t("fitNote");
  return [box, note];
}

function folderList(folders) {  // which sub-folder (an artist, a style) the query looks like
  const h = document.createElement("h3"); h.textContent = t("closestFolders");
  const box = document.createElement("div"); box.className = "meta near";
  folders.forEach((f, k) => {
    const a = document.createElement("a"); a.href = "#";
    a.textContent = `${f.folder} ${f.score.toFixed(2)} (${f.size})`;
    a.title = t("folderTip");
    a.addEventListener("click", (e) => {
      e.preventDefault();
      filter = ""; searchHits = null; tagOnly = null; folderFilter = f.folder; $("find").value = f.folder + "/";
      recolor(); focusOn([f.best]);
    });
    box.append(...(k ? [" · "] : []), a);
  });
  const legend = document.createElement("div"); legend.className = "kv"; legend.textContent = t("folderLegend");
  const first = folders[0];
  if (!first || !first.verdict) return [h, box, legend];
  const sure = document.createElement("div"); sure.className = "kv";  // how far to trust the first (measured)
  sure.textContent = t("folderVerdict_" + first.verdict).replace("{f}", first.folder)
    .replace("{m}", first.lead.toFixed(2)).replace("{r}", first.right) + " " + t("folderDrift");
  return [h, box, sure, legend];
}

function copyList(files, copies) {  // dropped images that the folder already holds (or a LoRA repeated)
  const box = document.createElement("div"); box.className = "kv warn";
  box.textContent = t("copiesLine").replace("{k}", copies.length).replace("{n}", files.length);
  box.title = t("copiesTip");
  const g = document.createElement("div"); g.className = "grid";
  copies.forEach((c) => { const im = thumb(c.i); im.title = `${files[c.q].name} ≈ ${PTS[c.i].n} (${c.score.toFixed(3)})`; g.append(im); });
  return [box, g];
}

function showSearch(files, hits, fit, folders, copies, folded) {
  $("tip").style.display = "none";  // the hover card of the last picture under the cursor
  selected = null; focusCluster = null; searchHits = new Set(hits.map((h) => h.i)); recolor();
  if (hits.length) focusOn(hits.slice(0, 8).map((h) => h.i));
  const pane = $("pane-selected"); pane.replaceChildren();
  const h = document.createElement("h3");
  h.textContent = files.length > 1 ? t("queries").replace("{n}", files.length) : t("query");
  const qs = document.createElement("div"); if (files.length > 1) qs.className = "grid";
  files.forEach((f, k) => {
    const q = document.createElement("img"); q.alt = f.name; q.src = URL.createObjectURL(f);
    if (files.length === 1) q.className = "query";
    if (fit && fit[k]) q.title = `${f.name} · ${clusterName(fit[k].group)} · ${t(fit[k].fits ? "fitOne" : "fitNotOne")}`;
    qs.append(q);
  });
  const h2 = document.createElement("h3");
  h2.textContent = t("nearest") + (folded ? " · " + t("foldedNote").replace("{n}", folded) : "");
  const legend = document.createElement("div"); legend.className = "kv";
  legend.textContent = t(files.length > 1 ? "cosLegendSet" : "cosLegend");
  const results = document.createElement("div");  // the copy button and the grid of the shown hits
  const show = (list) => {
    searchHits = new Set(list.map((x) => x.i)); recolor();
    const g = document.createElement("div"); g.className = "grid"; g.append(...list.map(scored));
    results.replaceChildren(...(list.length ? [copyButton(list)] : []), g);
  };
  const close = hits.filter((x) => x.cos >= CLOSE_COS);  // the scale holds for one query image only
  const closeOnly = files.length === 1 && close.length && close.length < hits.length ? [closeToggle(close, hits, show)] : [];
  show(hits);
  pane.append(h, qs, ...(copies && copies.length ? copyList(files, copies) : []),
    ...(fit && fit.length ? fitSummary(fit) : []),
    ...(folders && folders.length ? folderList(folders) : []), h2,
    ...(hits.length ? [legend, ...closeOnly] : []), results);
  showPane("selected");
}

function closeToggle(close, all, show) {  // only the results at CLOSE_COS or more
  const wrap = document.createElement("label"); wrap.className = "chip";
  const box = document.createElement("input"); box.type = "checkbox";
  box.addEventListener("change", () => show(box.checked ? close : all));
  wrap.append(box, " " + t("onlyClose").replace("{n}", close.length));
  return wrap;
}

const CLOSE_COS = 0.85;  // 9 in 10 pairs this close were by one artist (306 Danbooru artists)
const FAR_COS = 0.43;  // the median of pairs by different artists there: shown faded
const LIKE_COS = 0.59;  // the median of two works by one artist there: "close"

function scored(x) {  // a search result with its style similarity in the corner
  const cell = document.createElement("figure"); cell.className = "hit";
  const im = thumb(x.i); im.title = `${PTS[x.i].n} · cos ${x.cos.toFixed(3)}`;
  cell.append(im);
  if (x.cos >= LIKE_COS) {  // a word, not a number: the order is the search's, not the cosine's
    const cap = document.createElement("figcaption");
    cap.textContent = t(x.cos >= CLOSE_COS ? "simVery" : "simLike");
    if (x.cos >= CLOSE_COS) cap.className = "close";
    cell.append(cap);
  }
  if (x.cos < FAR_COS) cell.classList.add("far");
  if (SEVERAL_FOLDERS) {  // a library: whose picture it is, without hovering
    const who = document.createElement("div"); who.className = "who"; who.textContent = folderOf(x.i); cell.append(who);
  }
  return cell;
}

// gather the results into a folder, e.g. to grow a training set; name: a group's, for its folder
function copyButton(hits, name = null) {
  const copy = document.createElement("button"); copy.textContent = t("copyHits").replace("{n}", hits.length);
  copy.title = t(name ? "tipCopyGroup" : "tipCopyHits"); copy.style.margin = "2px 0 6px";
  copy.addEventListener("click", async () => {
    copy.disabled = true;
    try {
      const body = { items: hits.map((x) => x.i), ...(name ? { name } : {}) };
      const r = await post("api/copy_hits", JSON.stringify(body), "application/json");
      setStatus(t("copiedHits").replace("{n}", r.placed).replace("{f}", r.folder)); addOpenFolder();
    } catch (e) { setStatus(String(e.message || e)); }
    copy.disabled = false;
  });
  return copy;
}

// a group id, "excluded" (the images excluded by hand) or {items: [...]} (pictures as examples)
async function showSimilar(group) {
  setStatus(t("searching"));
  const body = group === "excluded" ? { excluded: true } : group.items ? group : { group };
  try {
    const { hits } = await post("api/similar", JSON.stringify(body), "application/json");
    setStatus(""); $("tip").style.display = "none";
    selected = null; searchHits = new Set(hits.map((h) => h.i)); recolor();
    if (hits.length) focusOn(hits.slice(0, 8).map((h) => h.i));
    const pane = $("pane-selected"); pane.replaceChildren();
    const h = document.createElement("h3");
    h.textContent = group === "excluded" ? t("moreLikeExcluded")
      : group.items ? t("similarTitle") : t("moreLikeTitle").replace("{g}", clusterName(group));
    const g = document.createElement("div"); g.className = "grid";
    hits.forEach((x) => { const cell = scored(x); cell.querySelector("img").title += ` · ${clusterName(x.group)}`; g.append(cell); });
    const legend = document.createElement("div"); legend.className = "kv"; legend.textContent = t("cosLegend");
    if (group.items) pane.append(...group.items.map((i) => { const q = tile(i); q.className = "query"; return q; }));  // map_group.js: sharp
    pane.append(h, copyButton(hits), g, legend);
    showPane("selected");
  } catch (e) { setStatus(String(e.message || e)); }
}

const VERDICT_KEYS = { "same style": "v_same", related: "v_related", "clearly different": "v_different" };
const POSITION_KEYS = { below_p5: "r_below", p5_to_median: "r_mid", above_median: "r_above" };  // among pairs of artists
const SEPARABLE_P = 0.05;  // metrics.SEPARABLE_P

const COMPARE_THUMBS = 6;  // a sample of each side under a comparison

// picked images in place of group a / group b; names: what to call the two sides (two artists)
async function showCompare(a, b, items, itemsB, names = null) {
  setStatus(t("searching"));
  try {
    const body = itemsB ? { items, items_b: itemsB } : items ? { items, b } : { a, b };
    const r = await post("api/compare", JSON.stringify(body), "application/json");
    setStatus("");
    const pane = $("pane-selected"); pane.replaceChildren();
    // as the server compares them: side b without the images side a already holds
    const membersOf = (g) => [...PTS.keys()].filter((i) => PTS[i].c === g);
    const sideA0 = items || membersOf(a);
    const inA = new Set(sideA0);
    const sideB0 = (itemsB || membersOf(b)).filter((i) => !inA.has(i));
    // the images that best show the difference first (the server's order), else as they come
    const sideA = r.order_a && r.order_a.length === sideA0.length ? r.order_a : sideA0;
    const sideB = r.order_b && r.order_b.length === sideB0.length ? r.order_b : sideB0;
    const nameA = names ? names[0] : items ? t("marked").replace("{n}", items.length) : clusterName(a);
    const nameB = names ? names[1] : itemsB ? t("markedA").replace("{n}", sideB.length) : clusterName(b);
    const h = document.createElement("h3");
    h.textContent = t("compareTitle").replace("{a}", nameA).replace("{b}", nameB);
    const kv = document.createElement("div"); kv.className = "kv";
    const zh = lang === "zh";
    const line = (k, v) => { const d = document.createElement("div"); d.textContent = `${k}${zh ? "：" : ": "}${v}`; kv.append(d); };
    const real = r.reading;  // 5 or more images a side: read next to real artists, not the z scale
    // sides mixing artists: their means drift together, so only "can the two be told apart" holds
    const verdict = r.mixed ? t(r.p < SEPARABLE_P ? "cmpMixedDiffer" : "cmpMixedSame")
      : real ? t(POSITION_KEYS[real.position]) : t(VERDICT_KEYS[r.verdict] || "v_related");
    const head = document.createElement("div"); head.className = "verdict";
    const strong = document.createElement("b"); strong.textContent = verdict; head.append(strong);
    kv.append(head);  // the answer first, the numbers below it
    if (r.mixed) {
      line(t("cmpDistance"), r.distance.toFixed(3));
      const why = document.createElement("div"); why.textContent = t("cmpMixedNote"); kv.append(why);
    } else if (real) {
      line(t("cmpDistance"), r.distance.toFixed(3));
      const ref = document.createElement("div");
      ref.textContent = t("cmpReading").replace("{n}", Math.round(real.n)).replace("{p5}", real.p5.toFixed(3))
        .replace("{m}", real.median.toFixed(3)).replace("{c}", real.change.toFixed(3));
      kv.append(ref);
    } else {
      line(t("cmpDistance"), `${r.distance.toFixed(3)}${zh ? `（z ${r.z}，${verdict}）` : ` (z ${r.z}, ${verdict})`}`);
    }
    line(t("cmpP"), r.p < 0.01 ? "< 0.01" : r.p.toFixed(2));
    if (r.look) {
      const z = LOOKS.map((k) => r.look[k] || 0);
      line(t("cmpLook").replace("{a}", nameA).replace("{b}", nameB), wordsFor(z) || t("cmpLookSame"));
    }
    const note = document.createElement("div"); note.className = "meta";
    note.textContent = t("cmpOrder") + " " + t(real ? "cmpNoteReal" : "cmpNote");
    const strips = [sideA, sideB].map((members, side) => {
      const grid = document.createElement("div"); grid.className = "grid";
      members.slice(0, COMPARE_THUMBS).forEach((i) => grid.append(thumb(i)));
      const cap = document.createElement("div"); cap.className = "meta";
      const shown = t("showingOf").replace("{k}", Math.min(COMPARE_THUMBS, members.length)).replace("{n}", members.length);
      cap.textContent = `${side === 0 ? nameA : nameB} · ${shown}`;
      return [cap, grid];
    }).flat();
    pane.append(h, kv, ...strips, note);
    showPane("selected");
  } catch (e) { setStatus(String(e.message || e)); }
}

/* ---------- several images at once: Shift+click, Shift+drag a box ---------- */
let MARKED = new Set();
let MARKED_A = null;  // an earlier selection kept to compare the next one with

function toggleMark(i) {
  if (MARKED.has(i)) MARKED.delete(i); else MARKED.add(i);
  showMarks();
}

function showMarks() {
  recolor(); markTiles();
  let bar = $("markBar");
  if (!MARKED.size) { if (bar) bar.remove(); return; }
  if (!bar) { bar = document.createElement("div"); bar.id = "markBar"; $("stage").append(bar); }
  const items = () => [...MARKED];
  const button = (key, fn) => { const b = document.createElement("button"); b.textContent = t(key); b.addEventListener("click", fn); return b; };
  const count = document.createElement("span"); count.textContent = t("marked").replace("{n}", MARKED.size);
  const ex = button("markExclude", () => batchExclude(items(), true));
  const inc = button("markInclude", () => batchExclude(items(), false));
  ex.textContent = t("markExclude").replace("{n}", MARKED.size);
  inc.textContent = t("markInclude").replace("{n}", MARKED.size);
  bar.replaceChildren(count, ex, inc,
    groupSelect(t("moveTo"), null, true, (to) => editPost("api/move", { items: items(), to })),
    ...(MARKED.size >= 2 ? [groupSelect(t("compareWith"), null, false, (b) => showCompare(null, b, items()))] : []),
    ...(MARKED.size >= 2 ? [button("rememberA", () => {
      MARKED_A = items(); MARKED = new Set(); showMarks();
      setStatus(t("rememberedA").replace("{n}", MARKED_A.length));
    })] : []),
    ...(MARKED.size >= 2 && MARKED_A ? [button("compareA", () => showCompare(null, null, items(), MARKED_A))] : []),
    button("markClear", () => { MARKED = new Set(); showMarks(); }));
}

async function batchExclude(items, excluded) {
  try {
    const r = await post("api/exclude", JSON.stringify({ items, excluded }), "application/json");
    EXCLUDED = new Set(r.excluded); buildOutliers();
    setStatus(t(excluded ? "markExcluded" : "markIncluded").replace("{n}", items.length));
    MARKED = new Set(); showMarks();
  } catch (e) { setStatus(String(e.message || e)); }
}

function setupMarking() {  // Shift+drag on the map draws a box; OrbitControls must not pan meanwhile
  const box = document.createElement("div"); box.id = "boxSel"; $("stage").append(box);
  let start = null;
  canvas.addEventListener("pointerdown", (e) => {
    if (!e.shiftKey || e.button !== 0) return;
    e.stopImmediatePropagation();
    downAt = [e.clientX, e.clientY];  // a Shift+click is still a click (map.js picks and marks)
    start = [e.clientX, e.clientY];
    try { canvas.setPointerCapture(e.pointerId); } catch (err) { /* no live pointer */ }
  }, { capture: true });
  canvas.addEventListener("pointermove", (e) => {
    if (!start) return;
    if (!e.buttons) { start = null; box.style.display = "none"; return; }  // the button was let go elsewhere
    const r = $("stage").getBoundingClientRect();
    Object.assign(box.style, { display: "block",
      left: `${Math.min(start[0], e.clientX) - r.left}px`, top: `${Math.min(start[1], e.clientY) - r.top}px`,
      width: `${Math.abs(e.clientX - start[0])}px`, height: `${Math.abs(e.clientY - start[1])}px` });
  });
  const reset = () => { start = null; box.style.display = "none"; };
  canvas.addEventListener("pointercancel", reset);
  canvas.addEventListener("lostpointercapture", (e) => { if (start && !e.buttons) reset(); });
  canvas.addEventListener("pointerup", (e) => {
    if (!start) return;
    const [sx, sy] = start; start = null; box.style.display = "none";
    if (Math.hypot(e.clientX - sx, e.clientY - sy) < 6) return;
    const r = canvas.getBoundingClientRect();
    const x0 = Math.min(sx, e.clientX) - r.left, x1 = Math.max(sx, e.clientX) - r.left;
    const y0 = Math.min(sy, e.clientY) - r.top, y1 = Math.max(sy, e.clientY) - r.top;
    for (let i = 0; i < N; i++) {
      if (alpha[i] < 0.5) continue;  // only what can be seen
      ray.set(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]).project(camera);
      if (ray.z > 1) continue;
      const px = (ray.x + 1) / 2 * r.width, py = (1 - ray.y) / 2 * r.height;
      if (px >= x0 && px <= x1 && py >= y0 && py <= y1) MARKED.add(i);
    }
    showMarks();
  });
}

let TASTE = null;

function voteOf(i) { return TASTE && TASTE.votes[String(i)]; }

let EXCLUDED = new Set();

async function toggleExclude(i) {
  try {
    const r = await post("api/exclude", JSON.stringify({ i, excluded: !EXCLUDED.has(i) }), "application/json");
    EXCLUDED = new Set(r.excluded);
    buildOutliers(); recolor(); applyText();
    if (RATING && EXCLUDED.has(i)) { rateNext(); return; }
    const old = $("pane-selected").querySelector(".votes");
    if (selected === i && old) old.replaceWith(voteButtons(i));
  } catch (e) { setStatus(String(e.message || e)); }
}

function groupSelect(title, current, withUnassigned, onPick) {
  const sel = document.createElement("select"); sel.name = "group"; sel.setAttribute("aria-label", title);
  sel.style.cssText = "background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:999px;padding:5px 8px;font:inherit;font-size:12px;max-width:170px";
  const head = document.createElement("option"); head.value = ""; head.textContent = title; sel.append(head);
  const ids = DATA.clusters.map((c) => c.id).concat(withUnassigned ? [-1] : []);
  ids.filter((id) => id !== current).forEach((id) => {
    const o = document.createElement("option"); o.value = String(id); o.textContent = clusterName(id); sel.append(o);
  });
  sel.addEventListener("click", (e) => e.stopPropagation());
  sel.addEventListener("change", () => { if (sel.value !== "") onPick(parseInt(sel.value, 10)); });
  return sel;
}

// What each undo step takes back, in words (this tab; the server keeps the steps themselves)
const LOG_KEY = "styleAtlasEdits";
const LOG_STEPS = 30;  // serve_edits.UNDO_STEPS
function editLog() { try { return JSON.parse(sessionStorage.getItem(LOG_KEY) || "[]"); } catch (e) { return []; } }
function setEditLog(log) { try { sessionStorage.setItem(LOG_KEY, JSON.stringify(log.slice(-LOG_STEPS))); } catch (e) { /* storage off */ } }
function logEdit(label) { const log = editLog(); log.push(label); setEditLog(log); }

function editLabel(url, body) {
  const g = (id) => clusterName(id);
  if (url === "api/merge") return t("logMerge").replace("{a}", g(body.from)).replace("{b}", g(body.into));
  if (url === "api/split") return t("logSplit").replace("{a}", g(body.group));
  if (url === "api/move") return t("logMove").replace("{n}", body.items ? body.items.length : 1).replace("{b}", g(body.to));
  if (url === "api/rename" && body.name.trim()) return t("logRename").replace("{a}", g(body.group)).replace("{b}", body.name.trim());
  if (url === "api/rename") return t("logUnname").replace("{a}", g(body.group));
  return t("logEdit");
}

// note: shown after the page reloads (else what was done); anchor: an image whose group the
// group view opens on then
async function editPost(url, body, note = "", anchor = null) {
  const undo = url === "api/undo";
  const log = editLog();
  const label = undo ? log.pop() : editLabel(url, body);
  try {
    await post(url, JSON.stringify({ ...body, rev: DATA.live.revision }), "application/json");
    if (!undo) { log.push(label); markStep("groups"); }  // map_browse.js
    setEditLog(log);
    const said = undo ? (label ? t("undoneWhat").replace("{what}", label) : t("undoneAny")) : `${label}${t("undoHint")}`;
    reloadKeepingView(note || said, anchor);
  }
  catch (e) { setStatus(String(e.message || e)); }
}

async function keepCopy(i) {  // keep this one of its near-duplicates at export
  try {
    const r = await post("api/keep_copy", JSON.stringify({ i }), "application/json");
    DATA.live.dup_keep = r.dup_keep; buildDups();
    setStatus(t("dupKeptNote").replace("{f}", PTS[i].n));
  } catch (e) { setStatus(String(e.message || e)); }
}

async function placeUnassigned() {  // fitting images move; a reload shows the new groups
  try {
    const r = await post("api/place_unassigned", JSON.stringify({ rev: DATA.live.revision }), "application/json");
    if (r.moved) { logEdit(t("logPlace").replace("{n}", r.moved)); reloadKeepingView(t("logPlace").replace("{n}", r.moved) + t("undoHint")); }
    else setStatus(t("placedNone").replace("{n}", r.left));
  } catch (e) { setStatus(String(e.message || e)); }
}

let PATH_FROM = null;

async function showPath(a, b) {
  try {
    const r = await post("api/path", JSON.stringify({ a, b, steps: 10 }), "application/json");
    searchHits = new Set(r.path); selected = null; recolor(); focusOn(r.path);
    const pane = $("pane-selected"); pane.replaceChildren();
    const h = document.createElement("h3"); h.textContent = t("pathTitle");
    const g = document.createElement("div"); g.className = "grid";
    r.path.forEach((i) => g.append(thumb(i)));
    pane.append(h, g); showPane("selected");
  } catch (e) { setStatus(String(e.message || e)); }
}

function pathButton(i) {
  const b = document.createElement("button");
  b.textContent = PATH_FROM === null || PATH_FROM === i ? t("pathFrom") : t("pathTo");
  b.addEventListener("click", () => {
    if (PATH_FROM === null || PATH_FROM === i) { PATH_FROM = i; b.textContent = t("pathTo"); setStatus(t("pathHint")); return; }
    const a = PATH_FROM; PATH_FROM = null; showPath(a, i);
  });
  return b;
}

function voteButtons(i) {
  const row = document.createElement("div"); row.className = "votes"; row.style.flexWrap = "wrap";
  const ex = document.createElement("button");
  ex.textContent = EXCLUDED.has(i) ? t("included") : t("exclude");
  if (EXCLUDED.has(i)) ex.classList.add("on");
  ex.addEventListener("click", () => toggleExclude(i));
  [["like", true], ["dislike", false], ["clearVote", null]].forEach(([k, v]) => {
    const b = document.createElement("button"); b.textContent = t(k);
    if (v !== null && voteOf(i) === v) b.classList.add("on");
    b.addEventListener("click", () => castVote(i, v));
    row.append(b);
  });
  row.append(ex, pathButton(i));
  row.append(groupSelect(t("moveTo"), PTS[i].c, true, (to) => editPost("api/move", { i, to })));
  return row;
}

let RATING = false;

async function rateNext() {
  try {
    const r = await post("api/next", "{}", "application/json");
    if (r.i === null) { RATING = false; setStatus(t("allRated")); return; }
    RATING = true;
    const counts = TASTE ? " · " + t("tasteCount").replace("{a}", TASTE.likes).replace("{b}", TASTE.dislikes) : "";
    setStatus(t("ratingHint") + counts);
    select(r.i);
    rateReadyAt = performance.now() + SEE_FIRST_MS;
  } catch (e) { setStatus(String(e.message || e)); }
}

let VOTING = false;  // one vote (and, when rating, the step to the next image) at a time
const SEE_FIRST_MS = 350;  // rating mode: a press this soon after the next image came is ignored
let rateReadyAt = 0;

async function castVote(i, like) {
  if (VOTING) return;  // a fast second L/D press would rate the same image again
  if (RATING && like !== null && performance.now() < rateReadyAt) return;  // not seen yet
  VOTING = true;
  try {
    TASTE = await post("api/taste", JSON.stringify({ i, like }), "application/json");
    const before = ["axX", "axY", "axZ"].map((id) => $(id).value).join();
    buildTaste(); setupAxes();
    const after = ["axX", "axY", "axZ"].map((id) => $(id).value).join();
    if (layoutMode === "measures" && (before !== after || after.includes("taste"))) applyLayout();
    const old = $("pane-selected").querySelector(".votes");
    if (selected === i && old) old.replaceWith(voteButtons(i));
    setStatus(t("tasteCount").replace("{a}", TASTE.likes).replace("{b}", TASTE.dislikes));
    if (RATING && like !== null) await rateNext();
  } catch (e) { setStatus(String(e.message || e)); }
  VOTING = false;
}

function tasteGrid(indices) {
  const g = document.createElement("div"); g.className = "grid";
  indices.forEach((i) => {
    const im = thumb(i);
    const v = voteOf(i); if (v === true) im.classList.add("liked"); if (v === false) im.classList.add("disliked");
    if (TASTE.scores) im.title = `${PTS[i].n} · p(like) ${TASTE.scores[i].toFixed(2)}`;
    g.append(im);
  });
  return g;
}

function buildTaste() {
  if (!DATA.live) return;
  const tab = document.querySelector('.tabs button[data-pane="taste"]');
  tab.hidden = false;
  tab.textContent = t("taste");
  const pane = $("pane-taste"); pane.replaceChildren();
  const add = (cls, text) => { const d = document.createElement("div"); d.className = cls; d.textContent = text; pane.append(d); };
  add("kv", t("tasteHelp").replace("{n}", TASTE.min));
  add("kv", t("tasteCount").replace("{a}", TASTE.likes).replace("{b}", TASTE.dislikes));
  const go = document.createElement("button"); go.textContent = t("rateNext");
  go.addEventListener("click", rateNext);
  pane.append(go);
  if (!TASTE.scores) return;
  add("kv", t("tasteAuc").replace("{x}", TASTE.auc.toFixed(2)).replace("{n}", TASTE.likes + TASTE.dislikes)
    + (TASTE.auc_groups != null ? " " + t("tasteAucGroups").replace("{g}", TASTE.auc_groups.toFixed(2)) : ""));
  const unrated = [...PTS.keys()].filter((i) => voteOf(i) === undefined)
    .sort((a, b) => TASTE.scores[b] - TASTE.scores[a]);
  const h1 = document.createElement("h3"); h1.textContent = t("tasteTop");
  const h2 = document.createElement("h3"); h2.textContent = t("tasteBottom");
  const nTop = Math.min(40, Math.ceil(unrated.length / 2));
  const nBottom = Math.min(20, unrated.length - nTop);  // the two lists never overlap
  add("kv", t("tasteLists").replace("{k}", nTop).replace("{m}", nBottom));
  pane.append(h1, tasteGrid(unrated.slice(0, nTop)));
  if (nBottom > 0) pane.append(h2, tasteGrid(unrated.slice(unrated.length - nBottom).reverse()));
}

function setupUndo() {
  $("undo").hidden = !DATA.live.can_undo;
  $("undo").addEventListener("click", () => editPost("api/undo", {}));
}

const LAYOUT_KEY = "style-atlas-layout";  // survives the reload after a reference is loaded

function setupReference() {
  $("refPath").title = t("tipRef"); $("refLoad").title = t("tipRef");
  $("refLoad").addEventListener("click", async () => {
    const folder = DATA.reference && !$("refPath").value.trim() ? "" : $("refPath").value;
    if (!folder && !DATA.reference) return;
    $("refLoad").disabled = true; setStatus(t("refBusy"));
    try {
      await post("api/reference", JSON.stringify({ folder }), "application/json");
      try { if (folder) sessionStorage.setItem(LAYOUT_KEY, "measures:ref"); } catch (e) { /* storage off */ }
      location.reload();
    } catch (err) { setStatus(String(err.message || err)); $("refLoad").disabled = false; }
  });
  $("refPath").addEventListener("input", () => {
    $("refLoad").textContent = DATA.reference && !$("refPath").value.trim() ? t("refClear") : t("refLoad");
  });
  let saved = null;
  try { saved = sessionStorage.getItem(LAYOUT_KEY); sessionStorage.removeItem(LAYOUT_KEY); } catch (e) { /* storage off */ }
  if (saved === "measures:ref" && DATA.reference) {
    setTimeout(() => {  // after applyText has filled the axis menus
      const sel = $("layoutSel"); sel.value = "measures"; sel.dispatchEvent(new Event("change"));
      $("axX").value = "ref"; $("axX").dispatchEvent(new Event("change"));
    }, 0);
  }
}

function setupPanels() {  // export options and the advanced switches open above the bar
  const pairs = [["exportOpen", "exportPanel"], ["moreOpen", "morePanel"]];
  pairs.forEach(([button, panel]) => {
    $(button).addEventListener("click", () => {
      const open = $(panel).hidden;
      pairs.forEach(([b, p]) => { $(p).hidden = true; $(b).classList.remove("on"); });
      $(panel).hidden = !open; $(button).classList.toggle("on", open);
    });
  });
  if ((DATA.live.space || "plain") !== "plain" || DATA.reference) {  // a switch is on: show it
    $("morePanel").hidden = false; $("moreOpen").classList.add("on");
  }
}

function setupSteps() {  // the LoRA workflow at a glance: check, sort the groups, export
  const box = $("steps"); box.hidden = false;
  const go = {
    check: () => {  // the check runs at once the first time (the side it measures can be changed after)
      showPane("outliers");
      if (!CHECK) runCheck(parseInt(document.querySelector('#pane-outliers select[name="minSide"]')?.value, 10) || 512);
    },
    groups: () => showPane("clusters"),
    export: () => { if ($("exportPanel").hidden) $("exportOpen").click(); $("expName").focus(); },
  };
  // the group view covers the map and its bottom bar: each step goes back to the map first
  box.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { closeGroup(false); go[b.dataset.step](); }));
}

function setupLive() {
  setupModes();  // map_browse.js
  setupUndo();
  setupPanels();
  setupSteps();
  setupMarking();
  setupReference();
  setupSpace();
  TASTE = DATA.live.taste;
  EXCLUDED = new Set(DATA.live.excluded || []);
  $("live").style.display = "flex";
  setupRegroup();
  setupExport();
  setupSaves();
  setupDrop();
}

function setupSpace() {  // the "ignore the character axis" switch
  $("neutral").checked = (DATA.live.space || "plain") !== "plain";
  $("neutral").addEventListener("change", async (e) => {
    setStatus(t("neutralBusy"));
    try {
      const space = e.target.checked ? "characters" : "plain";
      await post("api/space", JSON.stringify({ space }), "application/json");
      location.reload();
    } catch (err) { setStatus(String(err.message || err)); }
  });
}

function setupRegroup() {  // granularity, cut, periods, the regroup button and the file picker
  const s = DATA.live.settings;
  $("thr").value = (s.threshold ?? DATA.live.cut ?? DATA.live.granularity.medium).toFixed(2);
  $("pickBtn").addEventListener("click", () => $("pickFile").click());
  $("pickFile").addEventListener("change", (e) => searchFiles(e.target.files));
  $("periods").value = s.method === "kmeans" ? (s.k || DATA.live.periods) : DATA.live.periods;
  $("gran").addEventListener("change", (e) => {
    if (e.target.value in DATA.live.granularity) $("thr").value = DATA.live.granularity[e.target.value].toFixed(2);
    showPeriods(e.target.value === "period" || e.target.value === "timeline");
  });
  $("regroup").addEventListener("click", async () => {
    setStatus(t("regrouping"));
    try {
      const g = $("gran").value;
      const periods = parseInt($("periods").value, 10) || DATA.live.periods;
      const body = g === "period" ? { method: "kmeans", k: periods }
        : g === "timeline" ? { method: "timeline", k: periods }
        : g === "artists" ? { method: "artists" }
        : g === "folders" ? { method: "folders" }
        : g === "one" ? { method: "agglomerative", k: 1 }  // one LoRA: every image in one group
        : { threshold: g === "auto" ? null : parseFloat($("thr").value) };
      const r = await post("api/regroup", JSON.stringify(body), "application/json");
      const key = r.verdict === "turns" && r.edge ? "timelineTurnsEdge"  // one message, not two that disagree
        : { few: "timelineFew", none: "timelineNone", drift: "timelineDrift", turns: "timelineTurns" }[r.verdict];
      const verdict = key  // the timeline's tests (timeline.verdict), shown after the reload
        ? t(key).replace("{n}", r.distinct).replace("{p}", r.p_time).replace("{q}", r.p_turns)
          .replace("{sep}", (r.separation ?? 0).toFixed(3)) + (r.edge && r.verdict !== "turns" ? " " + t("edge_" + r.edge) : "")
          + " " + t("timelineSizes")
        : "";
      logEdit(t("logRegroup"));
      const advised = verdict && useMode === "lora";  // map_browse.js: the advice box reads the verdict
      reloadKeepingView(advised ? t("logRegroup") + t("seeAdvice") : verdict || t("logRegroup") + t("undoHint"));
    } catch (e) { setStatus(String(e.message || e)); }
  });
}

const EXPORT_KEY = "styleAtlasExport";  // the export options, kept while the tab is open
const EXPORT_FIELDS = ["expLayout", "expName", "expMax", "expRep", "expStrip"];

function saveExportOptions() {
  const options = Object.fromEntries(EXPORT_FIELDS.map((id) => [id, $(id).value]));
  options.expTrig = $("expTrig").checked; options.expSpell = $("expSpell").checked;
  try { sessionStorage.setItem(EXPORT_KEY, JSON.stringify(options)); } catch (e) { /* storage off */ }
}

function restoreExportOptions() {  // an edit reloads the page: the bar comes back as it was
  let options = null;
  try { options = JSON.parse(sessionStorage.getItem(EXPORT_KEY) || "null"); } catch (e) { return; }
  if (!options) return;
  EXPORT_FIELDS.forEach((id) => { if (typeof options[id] === "string") $(id).value = options[id]; });
  $("expTrig").checked = Boolean(options.expTrig); $("expSpell").checked = Boolean(options.expSpell);
}

function closeExport() { $("exportPanel").hidden = true; $("exportOpen").classList.remove("on"); }

function exportBody() {  // the export bar's options, as the server reads them
  const cap = parseInt($("expMax").value, 10);
  const rep = parseInt($("expRep").value, 10);
  const kohya = $("expLayout").value === "kohya";
  return { mode: "copy", layout: $("expLayout").value, name: $("expName").value.trim(),
    trigger: $("expTrig").checked, fix_spelling: $("expSpell").checked, max_per_group: cap > 0 ? cap : null,
    repeats: kohya && rep > 0 ? rep : null, strip_tags: $("expStrip").value.trim() };
}

function syncRepeats() {  // repeats are a kohya folder's prefix: no field for plain folders
  const kohya = $("expLayout").value === "kohya";
  $("expRep").hidden = !kohya; $("expRepLbl").hidden = !kohya;
}

// what the export would write, before it writes anything; after an export (done: its answer),
// what it wrote, in the export dialog
async function showExportPlan(done = null) {
  try {
    const r = await post("api/export_plan", JSON.stringify(exportBody()), "application/json");
    const pane = $("expPlan"); pane.replaceChildren();
    if (done) pane.append(exportDone(done));
    const h = document.createElement("h3"); h.textContent = t(done ? "planWritten" : "planTitle");
    const table = document.createElement("table"); table.className = "plan";
    const head = document.createElement("tr");
    [t("planFolder"), t("planImages"), t("planRepeats")].forEach((x) => { const th = document.createElement("th"); th.textContent = x; head.append(th); });
    table.append(head);
    r.rows.forEach((row) => {
      const tr = document.createElement("tr"); if (!row.training) tr.className = "aside";
      [row.folder, row.images, row.repeats ?? ""].forEach((x) => { const td = document.createElement("td"); td.textContent = String(x); tr.append(td); });
      table.append(tr);
    });
    const kv = document.createElement("div"); kv.className = "kv";
    const lines = [t("planTraining").replace("{k}", r.training)];
    if (r.steps) lines.push(t("stepsNote").replace("{n}", r.steps) + (exportBody().repeats ? "" : " " + t("repeatsNote")));
    if (r.small_groups) {
      const groups = r.small_ids.map(clusterName).join(lang === "zh" ? "、" : ", ");
      lines.push(t("smallGroups").replace("{n}", r.small_groups).replace("{g}", groups));
    }
    if (r.triggers.length) lines.push(t("triggersNote").replace("{w}", r.triggers.join(", ")));
    kv.textContent = lines.join(" ");
    pane.append(h, ...(done ? [] : [kv]), table);  // after an export its notes are above already
  } catch (e) { setStatus(String(e.message || e)); }
}

function exportDone(r) {  // the headline of a finished export, then its notes one per line
  const box = document.createElement("div"); box.className = "done";
  const head = document.createElement("b");
  const aside = r.placed - r.training;  // duplicates, exclusions, unassigned: in the _ folders
  head.textContent = t("exportedHead").replace("{k}", r.training) + (aside > 0 ? t("exportedAside").replace("{r}", aside) : "");
  const where = document.createElement("div"); where.className = "kv"; where.textContent = r.folder;
  const groups = (r.small_ids || []).map(clusterName).join(lang === "zh" ? "、" : ", ");
  const notes = [
    r.small_groups && t("smallGroups").replace("{n}", r.small_groups).replace("{g}", groups),
    r.trimmed && t("trimmedNote").replace("{n}", r.trimmed),
    r.steps && t("stepsNote").replace("{n}", r.steps) + (exportBody().repeats ? "" : " " + t("repeatsNote")),
    r.small_training && t("smallTraining").replace("{n}", r.small_training),
    r.upright && t("uprightNote").replace("{n}", r.upright),
    r.respelt && r.respelt.length && t("respeltNote").replace("{w}", r.respelt.join(", ")),
    r.triggers && r.triggers.length && t("triggersNote").replace("{w}", r.triggers.join(", ")),
    (r.triggers || []).some((w) => /[^\x00-\x7f]/.test(w)) && t("nonAsciiTrigger"),
    r.config && t("configWritten"),
  ].filter(Boolean);
  const list = document.createElement("ul"); list.className = "notes";
  notes.forEach((text) => { const li = document.createElement("li"); li.textContent = text; list.append(li); });
  box.append(head, where, list);
  return box;
}

function setupExport() {
  [...EXPORT_FIELDS, "expTrig", "expSpell"].forEach((id) => {
    $(id).addEventListener("change", saveExportOptions); $(id).addEventListener("input", saveExportOptions);
  });
  $("exportOpen").addEventListener("click", saveExportOptions);  // after setupPanels toggled it
  restoreExportOptions();
  syncRepeats(); $("expLayout").addEventListener("change", syncRepeats);
  $("exportPreview").addEventListener("click", () => showExportPlan());
  $("exportClose").addEventListener("click", closeExport);
  $("export").addEventListener("click", async () => {
    try {
      const r = await post("api/export", JSON.stringify(exportBody()), "application/json");
      setStatus(t("exportedHead").replace("{k}", r.training)); markStep("export");
      await showExportPlan(r);
      addOpenFolder();
    } catch (e) { setStatus(String(e.message || e)); }
  });
}

const LARGE_SHARE_MB = 10;  // Discord's upload limit without Nitro

function setupSaves() {  // the report and the shareable map
  $("saveReport").addEventListener("click", async () => {
    setStatus(t("savingMap"));
    try {
      const r = await post("api/save_report", JSON.stringify({ lang }), "application/json");
      setStatus(t("savedReport").replace("{f}", fileName(r.file)));
      addOpenFolder();
    } catch (e) { setStatus(String(e.message || e)); }
  });
  $("artistMap").hidden = folderCount() < 3;  // one point per sub-folder (artist)
  $("artistMap").addEventListener("click", async () => {
    const tab = window.open("", "_blank");  // opened now, while the click still counts
    setStatus(t("savingMap"));
    try {
      const r = await post("api/artist_map", "{}", "application/json");
      setStatus(t(r.families ? "artistMapDone" : "artistMapNone").replace("{n}", r.folders).replace("{k}", r.families).replace("{f}", r.file));
      if (tab) tab.location = r.url;
      else {  // the browser blocked the new tab: a link instead
        const a = document.createElement("a"); a.href = r.url; a.target = "_blank"; a.textContent = t("openArtistMap");
        a.style.marginLeft = "8px"; $("status").append(a);
      }
    } catch (e) { if (tab) tab.close(); setStatus(String(e.message || e)); }
  });
  $("saveMap").addEventListener("click", async () => {
    setStatus(t("savingMap"));
    try {
      const r = await post("api/save_map", "{}", "application/json");
      const big = r.mb > LARGE_SHARE_MB ? " " + t("bigMap").replace("{m}", LARGE_SHARE_MB) : "";
      setStatus(t("savedMap").replace("{f}", fileName(r.file)).replace("{mb}", r.mb) + big);
      addOpenFolder();
    } catch (e) { setStatus(String(e.message || e)); }
  });
}

function setupDrop() {  // images dropped anywhere on the page are searched
  let depth = 0;
  addEventListener("dragenter", (e) => { e.preventDefault(); depth++; document.body.classList.add("dragging"); });
  addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; document.body.classList.remove("dragging"); } });
  addEventListener("dragover", (e) => e.preventDefault());
  addEventListener("drop", (e) => {
    e.preventDefault(); depth = 0; document.body.classList.remove("dragging");
    searchFiles(e.dataTransfer.files);
  });
}

function liveText() {
  if (!DATA.live) return;
  modesText();  // map_browse.js
  $("expLayoutLbl").textContent = t("lblLayout"); $("expMoreLbl").textContent = t("moreOptions");
  $("exportWhere").textContent = t("exportWhere");
  $("pickBtn").textContent = t("searchImg"); $("regroup").textContent = t("regroup");
  $("export").textContent = t("exportGo"); $("exportPreview").textContent = t("exportPreview"); $("exportOpen").textContent = t("exportOpen");
  $("exportTitle").textContent = t("exportTitle"); $("moreOpen").textContent = t("moreOpen");
  $("drop").textContent = t("drop");
  stepsText();  // map_browse.js: with a tick on the steps done
  $("saveMap").textContent = t("saveMap"); $("saveReport").textContent = t("saveReport");
  $("artistMap").textContent = t("artistMap"); $("artistMap").title = t("tipArtistMap");
  $("undo").textContent = t("undo");
  $("expLayout").options[0].textContent = t("plainFolders");
  $("expName").placeholder = t("conceptName");
  $("expMax").placeholder = t("maxPerGroup");
  $("expStrip").placeholder = t("stripTags");
  $("expNameLbl").textContent = t("lblName"); $("expMaxLbl").textContent = t("lblMax");
  $("expRepLbl").textContent = t("lblRepeats"); $("expRep").placeholder = t("repeatsAuto"); $("expRep").title = t("repeatsTip");
  $("expStripLbl").textContent = t("lblStrip");
  $("expTrigWrap").querySelector("span").textContent = t("triggerCaptions");
  $("expSpellWrap").querySelector("span").textContent = t("fixSpelling");
  $("neutralWrap").querySelector("span").textContent = t("neutral");
  $("refPath").placeholder = DATA.reference ? DATA.reference : t("refPath");
  $("refLoad").textContent = DATA.reference && !$("refPath").value.trim() ? t("refClear") : t("refLoad");
  const cur = $("gran").value;
  const option = (k) => { const o = document.createElement("option"); o.value = k; o.textContent = t(k); return o; };
  const more = document.createElement("optgroup"); more.label = t("granMore");  // less common ways
  more.append(...["period", ...Object.keys(DATA.live.granularity), "custom"].map(option));
  const byFolder = folderNames().length >= 2 ? ["folders"] : [];  // map_browse.js
  $("gran").replaceChildren(...["auto", ...byFolder, ...(HAS_TIME ? ["timeline"] : []), "artists", "one"].map(option), more);
  const thr = parseFloat($("thr").value);
  const match = Object.entries(DATA.live.granularity).find(([, v]) => Math.abs(v - thr) < 1e-6);
  const s = DATA.live.settings;
  const auto = s.threshold == null && !s.k;
  const initial = s.method === "agglomerative" && s.k === 1 ? "one"
    : s.method === "kmeans" ? "period" : s.method === "timeline" ? "timeline" : s.method === "artists" ? "artists"
    : s.method === "folders" ? "folders"
    : (auto ? "auto" : (match ? match[0] : "custom"));
  $("gran").value = cur && cur !== "custom" ? cur : initial;
  $("periods").title = t("periods");
  showPeriods($("gran").value === "period" || $("gran").value === "timeline");
  const tips = { exportOpen: "tipExport", moreOpen: "tipMore", expMax: "tipMax", expStrip: "tipStrip", pickBtn: "tipSearch", gran: "tipGran", thr: "tipThr", regroup: "tipRegroup", undo: "tipUndo",
    expLayout: "tipLayout", expName: "tipName", expTrigWrap: "tipTrig", expSpellWrap: "tipSpell", exportPreview: "tipPreview", export: "tipExport",
    saveMap: "tipSaveMap", neutralWrap: "tipNeutral", saveReport: "tipSaveReport" };
  Object.entries(tips).forEach(([id, key]) => { $(id).title = t(key); });
}

// "period" asks for a number of periods instead of a distance cut.
function showPeriods(on) {  // the number field: periods, or the cut (only when set by hand)
  const cut = $("gran").value === "custom";
  $("thr").hidden = on || !cut; $("periods").hidden = !on;
  $("thrLbl").hidden = !on && !cut;
  $("thrLbl").textContent = t(on ? "lblPeriods" : "lblCut");
  $("thrLbl").htmlFor = on ? "periods" : "thr";
}

const VIEW_KEY = "styleAtlasView";  // the camera, carried over the reload after an edit
function reloadKeepingView(note = "", anchor = null) {
  const view = { cam: camera.position.toArray(), target: controls.target.toArray(), note,
    anchor: anchor ?? anchorForReload(), layout: layoutMode };
  try { sessionStorage.setItem(VIEW_KEY, JSON.stringify(view)); } catch (e) { /* storage off */ }
  location.reload();
}

function restoreView() {
  let view = null;
  try {
    view = JSON.parse(sessionStorage.getItem(VIEW_KEY) || "null");
    sessionStorage.removeItem(VIEW_KEY);
  } catch (e) { return false; }
  const point = (v) => Array.isArray(v) && v.length === 3 && v.every(Number.isFinite);
  if (!view || !point(view.cam) || !point(view.target)) return false;
  viewAnchor = Number.isInteger(view.anchor) ? view.anchor : null;  // the group view reopens on it
  if (typeof view.note === "string" && view.note) setTimeout(() => setStatus(view.note), 0);
  if (view.layout !== layoutMode) return false;  // the groups changed the layout: frame the new one
  camera.position.fromArray(view.cam); controls.target.fromArray(view.target); controls.update();
  return true;
}

// start-up
const restored = restoreView();
if (DATA.live) setupLive();
applyText();
buildPages();
resize();
if (!restored) camera.position.copy(homeView());  // every point in view, whatever the window
$("loading").classList.add("badge");  // thumbnails keep loading behind a small corner note
if (viewAnchor !== null) { const a = viewAnchor; viewAnchor = null; reopenGroup(a); }
animate();
fillPages();
