// Two ways to use the live app: browsing styles (groups, pictures alike, artists) or preparing a
// LoRA dataset (check, sort, export); each hides the other's tools. Also "find similar" on one
// picture and the artists tab (a library's sub-folders, each with the closest ones). Joined after
// map_group.js, before map_app.js.

const MODE_KEY = "styleAtlasMode";
const MODES = ["browse", "lora"];
let useMode = "browse";  // a shared map file always browses
const MIN_ARTISTS = 3;  // sub-folders before the artists tab shows (atlas.MIN_FOLDERS)

function setMode(next) {
  useMode = next; document.body.dataset.mode = next;
  store(MODE_KEY, next);
  document.querySelectorAll("#modes button").forEach((b) => b.classList.toggle("on", b.dataset.mode === next));
  $("welcome").hidden = true;
  const open = document.querySelector(".tabs button.on");
  if (open && getComputedStyle(open).display === "none") showPane("clusters");  // a tab this mode hides
  if (shownHint && $("status").textContent === shownHint) { shownHint = t(firstHintKey()); setStatus(shownHint); }
  if (GROUPS.length) buildClusters();  // cards and the LoRA advice differ by mode
}

/* ---------- the LoRA steps: a tick on each one done (this tab) ---------- */
const STEPS_KEY = "styleAtlasSteps";
function stepsDone() { try { return JSON.parse(sessionStorage.getItem(STEPS_KEY) || "{}"); } catch (e) { return {}; } }
function markStep(step) {
  const done = stepsDone();
  if (done[step]) return;
  done[step] = true;
  try { sessionStorage.setItem(STEPS_KEY, JSON.stringify(done)); } catch (e) { /* storage off */ }
  stepsText();
}
function stepsText() {
  const done = stepsDone();
  document.querySelectorAll("#steps button").forEach((b) => {
    const label = t("step_" + b.dataset.step);  // done: the tick takes the number's place (same width)
    b.textContent = done[b.dataset.step] ? label.replace(/^[①②③]\s*/, "✓ ") : label;
    b.title = label;  // in full, where a narrow panel cuts it
    b.classList.toggle("done", Boolean(done[b.dataset.step]));
  });
}

/* ---------- the LoRA advice: one or several, in words, with the step that settles it ---------- */
const ADVICE_KEY = "styleAtlasAdviceHidden";  // the advice put away (this tab), until it changes
function loraAdvice() {
  const box = document.createElement("div"); box.className = "advice";
  const close = document.createElement("button"); close.className = "close"; close.textContent = "✕";
  close.title = t("close"); close.setAttribute("aria-label", t("close"));
  box.append(close);
  const say = (key, extra = "") => { const p = document.createElement("p"); p.textContent = t(key) + extra; box.append(p); };
  const act = (key, fn) => { const b = document.createElement("button"); b.className = "primary"; b.textContent = t(key); b.addEventListener("click", fn); box.append(b); };
  const regroupTo = (g) => { $("gran").value = g; showPeriods(g === "timeline"); $("regroup").click(); };  // map_app.js
  const reading = DATA.live.timeline;
  const folders = folderNames().length;
  if (reading) {  // periods along the timeline: their tests have spoken
    const edge = reading.edge ? t("adviceEdge") : "";
    if (reading.verdict === "turns") { say("adviceTurns", edge); act("adviceExport", () => $("exportOpen").click()); }
    else { say(reading.verdict === "few" ? "adviceFew" : reading.verdict === "drift" ? "adviceDrift" : "adviceNone", edge); act("one", () => regroupTo("one")); }
  } else if (DATA.clusters.length <= 1) {
    say("adviceOneGroup"); act("adviceExport", () => $("exportOpen").click());
  } else if (folders >= 2 && DATA.method !== "folders") {
    say("adviceFolders", ""); box.lastChild.textContent = t("adviceFolders").replace("{n}", folders);
    act("folders", () => regroupTo("folders"));
  } else if (HAS_TIME) {
    say("adviceAskTime"); act("adviceTime", () => regroupTo("timeline"));
  } else {
    say("adviceAskCheck"); act("adviceCheck", () => document.querySelector('#steps button[data-step="check"]').click());
  }
  const said = box.querySelector("p").textContent;
  let hidden = null;
  try { hidden = sessionStorage.getItem(ADVICE_KEY); } catch (e) { /* storage off */ }
  if (hidden === said) return document.createComment("advice put away");
  close.addEventListener("click", () => {
    try { sessionStorage.setItem(ADVICE_KEY, said); } catch (e) { /* storage off */ }
    box.remove();
  });
  return box;
}

function firstHintKey() { return useMode === "lora" ? "firstHint" : "firstHintBrowse"; }

function setupModes() {  // live app only
  document.querySelectorAll("#modes button, #welcome button[data-mode]").forEach((b) =>
    b.addEventListener("click", () => setMode(b.dataset.mode)));
  const saved = stored(MODE_KEY);
  if (MODES.includes(saved)) setMode(saved);
  else { document.body.dataset.mode = "browse"; $("welcome").hidden = false; }  // first visit: ask
  $("modes").hidden = false;
  if (folderNames().length >= MIN_ARTISTS) {
    const tab = document.querySelector('.tabs button[data-pane="artists"]');
    tab.hidden = false; tab.addEventListener("click", buildArtists);
  }
}

function modesText() {
  document.querySelectorAll("#modes button").forEach((b) => { b.textContent = t("mode_" + b.dataset.mode); });
  $("welcome").querySelector("h2").textContent = t("welcomeTitle");
  $("welcome").querySelectorAll("button[data-mode]").forEach((b) => {
    b.querySelector("b").textContent = t("mode_" + b.dataset.mode);
    b.querySelector("span").textContent = t("modeWhat_" + b.dataset.mode);
  });
  $("welcome").querySelector("p").textContent = t("welcomeLater");
  const tab = document.querySelector('.tabs button[data-pane="artists"]');
  if (tab) tab.textContent = t("artistsTab");
  if (ARTISTS && document.querySelector('.tabs button[data-pane="artists"].on')) showArtistList();
}

function folderNames() {
  return [...new Set(PTS.map((p) => (p.n.includes("/") ? p.n.split("/")[0] : "")).filter(Boolean))];
}

function membersOfFolder(name) { return [...PTS.keys()].filter((i) => PTS[i].n.startsWith(name + "/")); }

/* ---------- find similar: one picture as the example ---------- */
function findSimilarButton(i) {
  const b = document.createElement("button"); b.className = "primary wide";
  b.textContent = t("findSimilar"); b.title = t("findSimilarTip");
  b.addEventListener("click", () => showSimilar({ items: [i] }));  // map_app.js
  return b;
}

/* ---------- the artists tab ---------- */
let ARTISTS = null;  // from api/artists: name, size, rep (an image), near: [[artist, similarity]]
let artistQuery = "";

async function buildArtists() {
  if (ARTISTS) { showArtistList(); return; }
  const pane = $("pane-artists");
  pane.textContent = t("artistsLoading");
  try { ARTISTS = (await post("api/artists", "{}", "application/json")).artists; }
  catch (e) { pane.textContent = String(e.message || e); return; }
  showArtistList();
}

function artistRow(k, note, onClick) {
  const a = ARTISTS[k];
  const row = document.createElement("div"); row.className = "cl artist"; row.tabIndex = 0;
  const img = document.createElement("img"); img.src = PTS[a.rep].t; img.alt = "";
  const txt = document.createElement("div");
  const nm = document.createElement("div"); nm.className = "name"; nm.textContent = a.name;
  const mt = document.createElement("div"); mt.className = "meta"; mt.textContent = `${a.size} ${t("size")}${note ? " · " + note : ""}`;
  txt.append(nm, mt);
  row.append(img, txt);
  row.addEventListener("click", onClick || (() => showArtist(k)));
  row.addEventListener("keydown", (e) => { if (e.key === "Enter") row.click(); });
  return row;
}

function showArtistList() {
  const pane = $("pane-artists"); pane.replaceChildren();
  const help = document.createElement("div"); help.className = "kv"; help.textContent = t("artistsHelp").replace("{n}", ARTISTS.length);
  const find = document.createElement("input"); find.type = "search"; find.className = "artist-find";
  find.placeholder = t("artistFind"); find.setAttribute("aria-label", t("artistFind")); find.value = artistQuery;
  const list = document.createElement("div");
  const fill = () => {
    artistQuery = find.value.trim().toLowerCase();
    list.replaceChildren(...ARTISTS.map((a, k) => [a, k]).filter(([a]) => a.name.toLowerCase().includes(artistQuery))
      .map(([, k]) => artistRow(k)));
  };
  find.addEventListener("input", fill);
  pane.append(help, find, list);
  fill();
}

function showArtist(k) {
  const a = ARTISTS[k];
  const pane = $("pane-artists"); pane.replaceChildren();
  const back = document.createElement("a"); back.href = "#"; back.className = "back"; back.textContent = t("artistsBack");
  back.addEventListener("click", (e) => { e.preventDefault(); showArtistList(); });
  const h = document.createElement("h2"); h.className = "artist-name"; h.textContent = a.name;
  const members = membersOfFolder(a.name);
  const bar = document.createElement("div"); bar.className = "gv-bar";
  const onMap = document.createElement("button"); onMap.textContent = t("artistOnMap");
  onMap.addEventListener("click", () => {
    closeGroup(false);
    filter = ""; searchHits = null; tagOnly = null; selected = null; focusCluster = null;
    folderFilter = a.name; $("find").value = a.name + "/";
    recolor(); focusOn(members);
  });
  const compare = document.createElement("select"); compare.setAttribute("aria-label", t("artistCompare"));
  const head = document.createElement("option"); head.value = ""; head.textContent = t("artistCompare"); compare.append(head);
  a.near.forEach(([j]) => { const o = document.createElement("option"); o.value = String(j); o.textContent = ARTISTS[j].name; compare.append(o); });
  compare.addEventListener("change", () => {
    if (compare.value === "") return;
    const other = ARTISTS[parseInt(compare.value, 10)];
    showCompare(null, null, members, membersOfFolder(other.name), [a.name, other.name]);  // map_app.js
  });
  bar.append(onMap, compare);
  const nh = document.createElement("h3"); nh.textContent = t("artistNear");
  const legend = document.createElement("div"); legend.className = "kv"; legend.textContent = t("artistNearLegend");
  const near = document.createElement("div");
  a.near.forEach(([j, s]) => near.append(artistRow(j, `${t("similarity")} ${s.toFixed(2)}`)));
  pane.append(back, h, artistRow(k, "", () => {}), bar, nh, legend, near);
  pane.scrollTop = 0;
}
