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
    const { hits } = files.length === 1
      ? await post("api/search", files[0], files[0].type)
      : await post("api/search_set", JSON.stringify({ images: await Promise.all(files.map(toBase64)) }), "application/json");
    setStatus("");
    showSearch(files, hits);
  } catch (e) { setStatus(String(e.message || e)); }
}

function showSearch(files, hits) {
  selected = null; focusCluster = null; searchHits = new Set(hits.map((h) => h.i)); recolor();
  if (hits.length) focusOn(hits.slice(0, 8).map((h) => h.i));
  const pane = $("pane-selected"); pane.replaceChildren();
  const h = document.createElement("h3");
  h.textContent = files.length > 1 ? t("queries").replace("{n}", files.length) : t("query");
  const qs = document.createElement("div"); if (files.length > 1) qs.className = "grid";
  files.forEach((f) => {
    const q = document.createElement("img"); q.alt = f.name; q.src = URL.createObjectURL(f);
    if (files.length === 1) q.className = "query";
    qs.append(q);
  });
  const h2 = document.createElement("h3"); h2.textContent = t("nearest");
  const g = document.createElement("div"); g.className = "grid";
  hits.forEach((x) => { const im = thumb(x.i); im.title = `${PTS[x.i].n} · cos ${x.cos.toFixed(3)}`; g.append(im); });
  pane.append(h, qs, h2, g);
  showPane("selected");
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

async function showCompare(a, b) {
  setStatus(t("searching"));
  try {
    const r = await post("api/compare", JSON.stringify({ a, b }), "application/json");
    setStatus("");
    const pane = $("pane-selected"); pane.replaceChildren();
    const h = document.createElement("h3");
    h.textContent = t("compareTitle").replace("{a}", clusterName(a)).replace("{b}", clusterName(b));
    const kv = document.createElement("div"); kv.className = "kv";
    const zh = lang === "zh";
    const line = (k, v) => { const d = document.createElement("div"); d.textContent = `${k}${zh ? "：" : ": "}${v}`; kv.append(d); };
    const verdict = t(VERDICT_KEYS[r.verdict] || "v_related");
    line(t("cmpDistance"), `${r.distance.toFixed(3)}${zh ? `（z ${r.z}，${verdict}）` : ` (z ${r.z}, ${verdict})`}`);
    line(t("cmpP"), r.p < 0.01 ? "< 0.01" : r.p.toFixed(2));
    if (r.look) {
      const z = LOOKS.map((k) => r.look[k] || 0);
      line(t("cmpLook").replace("{a}", clusterName(a)).replace("{b}", clusterName(b)), wordsFor(z) || t("cmpLookSame"));
    }
    const note = document.createElement("div"); note.className = "meta"; note.textContent = t("cmpNote");
    const strips = [a, b].map((g) => {
      const grid = document.createElement("div"); grid.className = "grid";
      PTS.forEach((p, i) => { if (p.c === g && grid.childElementCount < 6) grid.append(thumb(i)); });
      const cap = document.createElement("div"); cap.className = "meta"; cap.textContent = clusterName(g);
      return [cap, grid];
    }).flat();
    pane.append(h, kv, ...strips, note);
    showPane("selected");
  } catch (e) { setStatus(String(e.message || e)); }
}

let TASTE = null;

function voteOf(i) { return TASTE && TASTE.votes[String(i)]; }

let EXCLUDED = new Set();

async function toggleExclude(i) {
  try {
    const r = await post("api/exclude", JSON.stringify({ i, excluded: !EXCLUDED.has(i) }), "application/json");
    EXCLUDED = new Set(r.excluded);
    buildOutliers();
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

async function editPost(url, body) {
  try {
    await post(url, JSON.stringify({ ...body, rev: DATA.live.revision }), "application/json");
    location.reload();
  }
  catch (e) { setStatus(String(e.message || e)); }
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

function setupLive() {
  setupUndo();
  $("neutral").checked = (DATA.live.space || "plain") !== "plain";
  $("neutral").addEventListener("change", async (e) => {
    setStatus(t("neutralBusy"));
    try {
      const space = e.target.checked ? "characters" : "plain";
      await post("api/space", JSON.stringify({ space }), "application/json");
      location.reload();
    } catch (err) { setStatus(String(err.message || err)); }
  });
  TASTE = DATA.live.taste;
  EXCLUDED = new Set(DATA.live.excluded || []);
  $("live").style.display = "flex";
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
        : { threshold: g === "auto" ? null : parseFloat($("thr").value) };
      await post("api/regroup", JSON.stringify(body), "application/json");
      location.reload();
    } catch (e) { setStatus(String(e.message || e)); }
  });
  $("export").addEventListener("click", async () => {
    try {
      const body = { mode: "copy", layout: $("expLayout").value, name: $("expName").value.trim(),
        trigger: $("expTrig").checked };
      const r = await post("api/export", JSON.stringify(body), "application/json");
      const small = r.small_groups ? " " + t("smallGroups").replace("{n}", r.small_groups) : "";
      const config = r.config ? " " + t("configWritten") : "";
      setStatus(t("exported").replace("{n}", r.placed).replace("{f}", r.folder) + small + config);
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
  $("export").textContent = t("export"); $("drop").textContent = t("drop");
  $("saveMap").textContent = t("saveMap");
  $("undo").textContent = t("undo");
  $("expLayout").options[0].textContent = t("plainFolders");
  $("expName").placeholder = t("conceptName");
  $("expTrigWrap").querySelector("span").textContent = t("triggerCaptions");
  $("neutralWrap").querySelector("span").textContent = t("neutral");
  const cur = $("gran").value;
  $("gran").replaceChildren(...["auto", "period", ...Object.keys(DATA.live.granularity), "custom"].map((k) => {
    const o = document.createElement("option"); o.value = k; o.textContent = t(k); return o;
  }));
  const thr = parseFloat($("thr").value);
  const match = Object.entries(DATA.live.granularity).find(([, v]) => Math.abs(v - thr) < 1e-6);
  const s = DATA.live.settings;
  const auto = s.threshold == null && !s.k;
  const initial = s.method === "kmeans" ? "period" : (auto ? "auto" : (match ? match[0] : "custom"));
  $("gran").value = cur && cur !== "custom" ? cur : initial;
  $("periods").title = t("periods");
  showPeriods($("gran").value === "period");
  const tips = { pickBtn: "tipSearch", gran: "tipGran", thr: "tipThr", regroup: "tipRegroup", undo: "tipUndo",
    expLayout: "tipLayout", expName: "tipName", expTrigWrap: "tipTrig", export: "tipExport",
    saveMap: "tipSaveMap", neutralWrap: "tipNeutral" };
  Object.entries(tips).forEach(([id, key]) => { $(id).title = t(key); });
}

// "period" asks for a number of periods instead of a distance cut.
function showPeriods(on) {
  $("thr").hidden = on; $("periods").hidden = !on;
}

// start-up
if (DATA.live) setupLive();
applyText();
buildPages();
resize();
$("loading").classList.add("badge");  // thumbnails keep loading behind a small corner note
animate();
fillPages();
