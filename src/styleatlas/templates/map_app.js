// Web-app features (search, editing, votes, export) and start-up. Joined after map.js into
// one module script by report.render_html, so it shares map.js's scope; the start-up lines
// run last, once every declaration in both files exists.

function setStatus(msg) { $("status").textContent = msg || ""; }

// A button after a status message that names a file or folder in the output folder.
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
  return [h, box];
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
  const g = document.createElement("div"); g.className = "grid";
  hits.forEach((x) => { const im = thumb(x.i); im.title = `${PTS[x.i].n} · cos ${x.cos.toFixed(3)}`; g.append(im); });
  pane.append(h, qs, ...(copies && copies.length ? copyList(files, copies) : []),
    ...(fit && fit.length ? fitSummary(fit) : []),
    ...(folders && folders.length ? folderList(folders) : []), h2, ...(hits.length ? [copyButton(hits)] : []), g);
  showPane("selected");
}

function copyButton(hits) {  // gather the results into a folder, e.g. to grow a training set
  const copy = document.createElement("button"); copy.textContent = t("copyHits").replace("{n}", hits.length);
  copy.title = t("tipCopyHits"); copy.style.margin = "2px 0 6px";
  copy.addEventListener("click", async () => {
    copy.disabled = true;
    try {
      const r = await post("api/copy_hits", JSON.stringify({ items: hits.map((x) => x.i) }), "application/json");
      setStatus(t("copiedHits").replace("{n}", r.placed).replace("{f}", r.folder)); addOpenFolder();
    } catch (e) { setStatus(String(e.message || e)); }
    copy.disabled = false;
  });
  return copy;
}

async function showSimilar(group) {  // a group id, or "excluded": the images excluded by hand
  setStatus(t("searching"));
  const body = group === "excluded" ? { excluded: true } : { group };
  try {
    const { hits } = await post("api/similar", JSON.stringify(body), "application/json");
    setStatus("");
    selected = null; searchHits = new Set(hits.map((h) => h.i)); recolor();
    if (hits.length) focusOn(hits.slice(0, 8).map((h) => h.i));
    const pane = $("pane-selected"); pane.replaceChildren();
    const h = document.createElement("h3");
    h.textContent = group === "excluded" ? t("moreLikeExcluded") : t("moreLikeTitle").replace("{g}", clusterName(group));
    const g = document.createElement("div"); g.className = "grid";
    hits.forEach((x) => { const im = thumb(x.i); im.title = `${PTS[x.i].n} · ${clusterName(x.group)}`; g.append(im); });
    pane.append(h, g);
    showPane("selected");
  } catch (e) { setStatus(String(e.message || e)); }
}

const VERDICT_KEYS = { "same style": "v_same", related: "v_related", "clearly different": "v_different" };

const COMPARE_THUMBS = 6;  // a sample of each side under a comparison

async function showCompare(a, b, items, itemsB) {  // picked images in place of group a / group b
  setStatus(t("searching"));
  try {
    const body = itemsB ? { items, items_b: itemsB } : items ? { items, b } : { a, b };
    const r = await post("api/compare", JSON.stringify(body), "application/json");
    setStatus("");
    const pane = $("pane-selected"); pane.replaceChildren();
    // as the server compares them: side b without the images side a already holds
    const membersOf = (g) => [...PTS.keys()].filter((i) => PTS[i].c === g);
    const sideA = items || membersOf(a);
    const inA = new Set(sideA);
    const sideB = (itemsB || membersOf(b)).filter((i) => !inA.has(i));
    const nameA = items ? t("marked").replace("{n}", items.length) : clusterName(a);
    const nameB = itemsB ? t("markedA").replace("{n}", sideB.length) : clusterName(b);
    const h = document.createElement("h3");
    h.textContent = t("compareTitle").replace("{a}", nameA).replace("{b}", nameB);
    const kv = document.createElement("div"); kv.className = "kv";
    const zh = lang === "zh";
    const line = (k, v) => { const d = document.createElement("div"); d.textContent = `${k}${zh ? "：" : ": "}${v}`; kv.append(d); };
    const verdict = t(VERDICT_KEYS[r.verdict] || "v_related");
    const head = document.createElement("div"); head.className = "verdict";
    const strong = document.createElement("b"); strong.textContent = verdict; head.append(strong);
    kv.append(head);  // the answer first, the numbers below it
    line(t("cmpDistance"), `${r.distance.toFixed(3)}${zh ? `（z ${r.z}，${verdict}）` : ` (z ${r.z}, ${verdict})`}`);
    line(t("cmpP"), r.p < 0.01 ? "< 0.01" : r.p.toFixed(2));
    if (r.look) {
      const z = LOOKS.map((k) => r.look[k] || 0);
      line(t("cmpLook").replace("{a}", nameA).replace("{b}", nameB), wordsFor(z) || t("cmpLookSame"));
    }
    const note = document.createElement("div"); note.className = "meta"; note.textContent = t("cmpNote");
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
  recolor();
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

async function editPost(url, body, note = "") {  // note: shown after the page reloads
  try {
    await post(url, JSON.stringify({ ...body, rev: DATA.live.revision }), "application/json");
    reloadKeepingView(note);
  }
  catch (e) { setStatus(String(e.message || e)); }
}

async function placeUnassigned() {  // fitting images move; a reload shows the new groups
  try {
    const r = await post("api/place_unassigned", JSON.stringify({ rev: DATA.live.revision }), "application/json");
    if (r.moved) reloadKeepingView();
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
    if (PATH_FROM === null || PATH_FROM === i) { PATH_FROM = i; b.textContent = t("pathTo"); return; }
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
    RATING = true; setStatus(t("ratingHint"));
    select(r.i);
  } catch (e) { setStatus(String(e.message || e)); }
}

async function castVote(i, like) {
  try {
    TASTE = await post("api/taste", JSON.stringify({ i, like }), "application/json");
    const before = ["axX", "axY", "axZ"].map((id) => $(id).value).join();
    buildTaste(); setupAxes();
    const after = ["axX", "axY", "axZ"].map((id) => $(id).value).join();
    if (layoutMode === "measures" && (before !== after || after.includes("taste"))) applyLayout();
    const old = $("pane-selected").querySelector(".votes");
    if (selected === i && old) old.replaceWith(voteButtons(i));
    if (RATING && like !== null) rateNext();
  } catch (e) { setStatus(String(e.message || e)); }
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
  add("kv", t("tasteAuc").replace("{x}", TASTE.auc.toFixed(2)));
  const unrated = [...PTS.keys()].filter((i) => voteOf(i) === undefined)
    .sort((a, b) => TASTE.scores[b] - TASTE.scores[a]);
  const h1 = document.createElement("h3"); h1.textContent = t("tasteTop");
  const h2 = document.createElement("h3"); h2.textContent = t("tasteBottom");
  const nTop = Math.min(40, Math.ceil(unrated.length / 2));
  const nBottom = Math.min(20, unrated.length - nTop);  // the two lists never overlap
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
    check: () => showPane("outliers"),
    groups: () => showPane("clusters"),
    export: () => { if ($("exportPanel").hidden) $("exportOpen").click(); $("expName").focus(); },
  };
  box.querySelectorAll("button").forEach((b) => b.addEventListener("click", go[b.dataset.step]));
}

function setupLive() {
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
    showPeriods(e.target.value === "period");
  });
  $("thr").addEventListener("input", () => { $("gran").value = "custom"; });
  $("regroup").addEventListener("click", async () => {
    setStatus(t("regrouping"));
    try {
      const g = $("gran").value;
      const body = g === "period"
        ? { method: "kmeans", k: parseInt($("periods").value, 10) || DATA.live.periods }
        : g === "artists" ? { method: "artists" }
        : { threshold: g === "auto" ? null : parseFloat($("thr").value) };
      await post("api/regroup", JSON.stringify(body), "application/json");
      reloadKeepingView();
    } catch (e) { setStatus(String(e.message || e)); }
  });
}

const EXPORT_KEY = "styleAtlasExport";  // the export options, kept while the tab is open
const EXPORT_FIELDS = ["expLayout", "expName", "expMax", "expStrip"];

function saveExportOptions() {
  const options = Object.fromEntries(EXPORT_FIELDS.map((id) => [id, $(id).value]));
  options.expTrig = $("expTrig").checked; options.open = !$("exportPanel").hidden;
  try { sessionStorage.setItem(EXPORT_KEY, JSON.stringify(options)); } catch (e) { /* storage off */ }
}

function restoreExportOptions() {  // an edit reloads the page: the bar comes back as it was
  let options = null;
  try { options = JSON.parse(sessionStorage.getItem(EXPORT_KEY) || "null"); } catch (e) { return; }
  if (!options) return;
  EXPORT_FIELDS.forEach((id) => { if (typeof options[id] === "string") $(id).value = options[id]; });
  $("expTrig").checked = Boolean(options.expTrig);
  if (options.open && $("exportPanel").hidden) $("exportOpen").click();
}

function setupExport() {
  [...EXPORT_FIELDS, "expTrig"].forEach((id) => {
    $(id).addEventListener("change", saveExportOptions); $(id).addEventListener("input", saveExportOptions);
  });
  $("exportOpen").addEventListener("click", saveExportOptions);  // after setupPanels toggled it
  restoreExportOptions();
  $("export").addEventListener("click", async () => {
    try {
      const cap = parseInt($("expMax").value, 10);
      const body = { mode: "copy", layout: $("expLayout").value, name: $("expName").value.trim(),
        trigger: $("expTrig").checked, max_per_group: cap > 0 ? cap : null,
        strip_tags: $("expStrip").value.trim() };
      const r = await post("api/export", JSON.stringify(body), "application/json");
      const groups = (r.small_ids || []).map(clusterName).join(lang === "zh" ? "、" : ", ");
      const small = r.small_groups ? " " + t("smallGroups").replace("{n}", r.small_groups).replace("{g}", groups) : "";
      const config = r.config ? " " + t("configWritten") : "";
      const trimmed = r.trimmed ? " " + t("trimmedNote").replace("{n}", r.trimmed) : "";
      const steps = r.steps ? " " + t("stepsNote").replace("{n}", r.steps) + " " + t("repeatsNote") : "";
      const tiny = r.small_training ? " " + t("smallTraining").replace("{n}", r.small_training) : "";
      const done = t("exported").replace("{n}", r.placed).replace("{f}", r.folder).replace("{k}", r.training);
      const upright = r.upright ? " " + t("uprightNote").replace("{n}", r.upright) : "";
      const words = r.triggers && r.triggers.length ? " " + t("triggersNote").replace("{w}", r.triggers.join(", ")) : "";
      const ascii = (r.triggers || []).some((w) => /[^\x00-\x7f]/.test(w)) ? " " + t("nonAsciiTrigger") : "";
      setStatus(done + small + trimmed + steps + tiny + upright + words + ascii + config);
      addOpenFolder();
    } catch (e) { setStatus(String(e.message || e)); }
  });
}

function setupSaves() {  // PNG, report and shareable map under "More..."
  $("savePng").addEventListener("click", () => { snapPending = true; });
  $("saveReport").addEventListener("click", async () => {
    setStatus(t("savingMap"));
    try {
      const r = await post("api/save_report", JSON.stringify({ lang }), "application/json");
      setStatus(t("savedReport").replace("{f}", r.file));
      addOpenFolder();
    } catch (e) { setStatus(String(e.message || e)); }
  });
  $("saveMap").addEventListener("click", async () => {
    setStatus(t("savingMap"));
    try {
      const r = await post("api/save_map", "{}", "application/json");
      setStatus(t("savedMap").replace("{f}", r.file));
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
  $("pickBtn").textContent = t("searchImg"); $("regroup").textContent = t("regroup");
  $("export").textContent = t("exportGo"); $("exportOpen").textContent = t("exportOpen");
  $("exportTitle").textContent = t("exportTitle"); $("moreOpen").textContent = t("moreOpen");
  $("drop").textContent = t("drop");
  document.querySelectorAll("#steps button").forEach((b) => { b.textContent = t("step_" + b.dataset.step); });
  $("saveMap").textContent = t("saveMap"); $("saveReport").textContent = t("saveReport");
  $("savePng").textContent = t("savePng");
  $("undo").textContent = t("undo");
  $("expLayout").options[0].textContent = t("plainFolders");
  $("expName").placeholder = t("conceptName");
  $("expMax").placeholder = t("maxPerGroup");
  $("expStrip").placeholder = t("stripTags");
  $("expNameLbl").textContent = t("lblName"); $("expMaxLbl").textContent = t("lblMax");
  $("expStripLbl").textContent = t("lblStrip");
  $("expTrigWrap").querySelector("span").textContent = t("triggerCaptions");
  $("neutralWrap").querySelector("span").textContent = t("neutral");
  $("refPath").placeholder = DATA.reference ? DATA.reference : t("refPath");
  $("refLoad").textContent = DATA.reference && !$("refPath").value.trim() ? t("refClear") : t("refLoad");
  const cur = $("gran").value;
  $("gran").replaceChildren(...["auto", "period", "artists", ...Object.keys(DATA.live.granularity), "custom"].map((k) => {
    const o = document.createElement("option"); o.value = k; o.textContent = t(k); return o;
  }));
  const thr = parseFloat($("thr").value);
  const match = Object.entries(DATA.live.granularity).find(([, v]) => Math.abs(v - thr) < 1e-6);
  const s = DATA.live.settings;
  const auto = s.threshold == null && !s.k;
  const initial = s.method === "kmeans" ? "period" : s.method === "artists" ? "artists"
    : (auto ? "auto" : (match ? match[0] : "custom"));
  $("gran").value = cur && cur !== "custom" ? cur : initial;
  $("periods").title = t("periods");
  showPeriods($("gran").value === "period");
  const tips = { exportOpen: "tipExport", moreOpen: "tipMore", expMax: "tipMax", expStrip: "tipStrip", pickBtn: "tipSearch", gran: "tipGran", thr: "tipThr", regroup: "tipRegroup", undo: "tipUndo",
    expLayout: "tipLayout", expName: "tipName", expTrigWrap: "tipTrig", export: "tipExport",
    saveMap: "tipSaveMap", neutralWrap: "tipNeutral", saveReport: "tipSaveReport" };
  Object.entries(tips).forEach(([id, key]) => { $(id).title = t(key); });
}

// "period" asks for a number of periods instead of a distance cut.
function showPeriods(on) {
  $("thr").hidden = on; $("periods").hidden = !on;
  $("thrLbl").textContent = t(on ? "lblPeriods" : "lblCut");
  $("thrLbl").htmlFor = on ? "periods" : "thr";
}

const VIEW_KEY = "styleAtlasView";  // the camera, carried over the reload after an edit
function reloadKeepingView(note = "") {
  const view = { cam: camera.position.toArray(), target: controls.target.toArray(), note };
  try { sessionStorage.setItem(VIEW_KEY, JSON.stringify(view)); } catch (e) { /* storage off */ }
  location.reload();
}

function restoreView() {
  let view = null;
  try {
    view = JSON.parse(sessionStorage.getItem(VIEW_KEY) || "null");
    sessionStorage.removeItem(VIEW_KEY);
  } catch (e) { return; }
  const point = (v) => Array.isArray(v) && v.length === 3 && v.every(Number.isFinite);
  if (!view || !point(view.cam) || !point(view.target)) return;
  camera.position.fromArray(view.cam); controls.target.fromArray(view.target); controls.update();
  if (typeof view.note === "string" && view.note) setTimeout(() => setStatus(view.note), 0);
}

// start-up
restoreView();
if (DATA.live) setupLive();
applyText();
buildPages();
resize();
$("loading").classList.add("badge");  // thumbnails keep loading behind a small corner note
animate();
fillPages();
