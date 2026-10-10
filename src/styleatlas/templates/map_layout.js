// Layouts on top of the map (measure axes and their morph), group names floating in the
// scene, and recording a turn of the map. Joined after map.js by report.page_script.

/* ---------- measure axes ---------- */
let layoutMode = "style";
let axisLines = null;

const LOOKS = DATA.look_names || [];
const LOOK_NOTABLE = 0.5;  // as look.NOTABLE: |z| from which a difference is put into words

let LOOK_STATS = null;
function lookStats() {  // the folder's mean and spread of each measure (they never change)
  if (LOOK_STATS) return LOOK_STATS;
  const mean = LOOKS.map((_, j) => PTS.reduce((s, p) => s + p.lk[j], 0) / N);
  const sd = LOOKS.map((_, j) => Math.sqrt(PTS.reduce((s, p) => s + (p.lk[j] - mean[j]) ** 2, 0) / N));
  LOOK_STATS = { mean, sd };
  return LOOK_STATS;
}

function lookWords(members) {
  if (!LOOKS.length || !members.length) return "";
  const st = lookStats();
  const z = LOOKS.map((_, j) => {
    const m = members.reduce((s, i) => s + PTS[i].lk[j], 0) / members.length;
    return st.sd[j] > 1e-9 ? (m - st.mean[j]) / st.sd[j] : 0;
  });
  return wordsFor(z) || t("lookAverage");
}

function wordsFor(z) {  // z in LOOKS order -> "cooler, more line work" (strongest first; "" if none)
  const order = [...z.keys()].sort((a, b) => Math.abs(z[b]) - Math.abs(z[a]));
  const words = order.filter((j) => Math.abs(z[j]) >= LOOK_NOTABLE).map((j) => t("w_" + LOOKS[j])[z[j] > 0 ? 0 : 1]);
  return words.join(lang === "zh" ? "、" : ", ");
}

function measure(key) {
  const j = LOOKS.indexOf(key);
  if (j >= 0) return PTS.map((p) => p.lk[j]);
  if (key === "outlier") return PTS.map((p) => p.o);
  if (key === "time") return HAS_TIME ? PTS.map((p) => p.ts) : null;
  if (key === "ref") return DATA.reference ? PTS.map((p) => p.r) : null;
  if (key === "taste") return (typeof TASTE !== "undefined" && TASTE && TASTE.scores) ? TASTE.scores : null;
  return null;
}

function availableMeasures() {
  return ["taste", "ref", "time", "outlier", ...LOOKS].filter((k) => measure(k));
}

function rankNorm(vals) {
  const idx = [...vals.keys()].filter((i) => vals[i] !== null && vals[i] !== undefined);
  idx.sort((a, b) => vals[a] - vals[b]);
  const out = new Float32Array(vals.length).fill(-1.15);  // no value: parked before the axis start
  const span = Math.max(1, idx.length - 1);
  for (let s = 0; s < idx.length; ) {
    let e = s;
    while (e + 1 < idx.length && vals[idx[e + 1]] === vals[idx[s]]) e++;
    const r = (s + e) / 2;  // ties share their average rank
    for (let j = s; j <= e; j++) out[idx[j]] = idx.length > 1 ? (r / span) * 2 - 1 : 0;
    s = e + 1;
  }
  return out;
}

function targetPositions() {
  const target = basePos.slice();
  if (layoutMode !== "measures") return target;
  ["axX", "axY", "axZ"].forEach((id, d) => {
    const key = $(id).value;
    const vals = key === "map" ? null : measure(key);
    if (!vals) return;
    const r = rankNorm(vals);
    for (let i = 0; i < N; i++) target[i * 3 + d] = r[i] * SPREAD;
  });
  return target;
}

function applyLayout() {
  if (nameSprites) nameSprites.visible = false;  // redrawn where the groups land
  morph = { from: pos.slice(), to: targetPositions(), k: 0 };
  drawAxes();
}

function stepMorph() {
  if (!morph) return;
  morph.k = Math.min(1, morph.k + 0.04);
  const e = morph.k < 0.5 ? 2 * morph.k * morph.k : 1 - Math.pow(-2 * morph.k + 2, 2) / 2;
  for (let j = 0; j < pos.length; j++) pos[j] = morph.from[j] + (morph.to[j] - morph.from[j]) * e;
  for (const pg of pages) {
    const a = pg.geo.getAttribute("position");
    a.array.set(pos.subarray(pg.start * 3, (pg.start + pg.count) * 3));
    a.needsUpdate = true;
    pg.geo.computeBoundingSphere();
  }
  if (morph.k >= 1) { morph = null; drawNames(); }
}

function srgbTexture(cv) {  // canvas pixels are sRGB; unmarked, the sprite shader would brighten them
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

/* ---------- group names floating at each group's centre ---------- */
const MAX_NAMES = 16;  // the largest groups only: more labels cover the map
let nameSprites = null;
let showNames = true;

const NAME_CHARS = 28;  // longer names are cut, or one label would cover the map

function nameSprite(full, color) {
  const text = full.length > NAME_CHARS ? full.slice(0, NAME_CHARS - 1) + "…" : full;
  const cv = document.createElement("canvas"); const g = cv.getContext("2d");
  const font = "600 30px system-ui, sans-serif"; g.font = font;
  cv.width = Math.ceil(g.measureText(text).width) + 24; cv.height = 46;
  g.font = font; g.fillStyle = "rgba(12,14,18,0.86)"; g.fillRect(0, 0, cv.width, cv.height);
  g.fillStyle = color; g.fillText(text, 12, 33);
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: srgbTexture(cv), depthTest: false, transparent: true }));
  const h = 0.11; sp.scale.set(h * cv.width / cv.height, h, 1); sp.renderOrder = 10;
  return sp;
}

function drawNames() {
  if (nameSprites) { scene.remove(nameSprites); disposeTree(nameSprites); nameSprites = null; }
  if (!showNames) return;
  const sums = new Map();
  PTS.forEach((p, i) => {
    if (p.c < 0) return;
    const s = sums.get(p.c) || [0, 0, 0, 0];
    s[0] += pos[i * 3]; s[1] += pos[i * 3 + 1]; s[2] += pos[i * 3 + 2]; s[3] += 1; sums.set(p.c, s);
  });
  nameSprites = new THREE.Group();
  [...sums.entries()].sort((a, b) => b[1][3] - a[1][3]).slice(0, MAX_NAMES).forEach(([c, s]) => {
    const sp = nameSprite(clusterName(c), colorOf(c));
    sp.position.set(s[0] / s[3], s[1] / s[3] + 0.12, s[2] / s[3]); sp.userData.c = c;
    nameSprites.add(sp);
  });
  scene.add(nameSprites);
  fadeNames();
}

function fadeNames() {  // names step back with the points: a focused group keeps its own
  if (!nameSprites) return;
  const dimmed = selected !== null || searchHits !== null || filter !== "" || folderFilter !== null;
  nameSprites.children.forEach((sp) => {
    const on = focusCluster !== null ? sp.userData.c === focusCluster : !dimmed;
    sp.material.opacity = on ? 1 : 0.15;
  });
}

/* ---------- one turn of the map as a video, to share ---------- */
const RECORD_SECONDS = 8;
let recordingNow = false;

function recorderType() {
  if (!canvas.captureStream || typeof MediaRecorder === "undefined") return null;
  // MP4 first: social apps take it more readily than WebM (Firefox only records WebM)
  const types = ["video/mp4;codecs=avc1", "video/mp4", "video/webm;codecs=vp9", "video/webm"];
  return types.find((m) => MediaRecorder.isTypeSupported(m)) || null;
}

async function recordTurn() {
  const type = recorderType();
  if (!type || recordingNow) return;
  if (document.hidden) return;  // a hidden tab draws no frames
  recordingNow = true;
  const was = { auto: controls.autoRotate, speed: controls.autoRotateSpeed };
  $("rec").disabled = true; $("spin").disabled = true;
  let rec = null;
  let hidden = false;
  const onHide = () => { if (document.hidden) hidden = true; };
  document.addEventListener("visibilitychange", onHide);
  try {
    const chunks = [];
    rec = new MediaRecorder(canvas.captureStream(30), { mimeType: type, videoBitsPerSecond: 8e6 });
    rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    const stopped = new Promise((r) => { rec.onstop = r; });
    controls.autoRotate = true;
    controls.autoRotateSpeed = 60 / RECORD_SECONDS;  // OrbitControls: speed 2 = one turn in 30 s
    rec.start();
    for (let s = RECORD_SECONDS; s > 0 && !hidden; s--) {
      $("rec").textContent = t("recording").replace("{s}", s);
      await new Promise((r) => setTimeout(r, 1000));
    }
    rec.stop(); await stopped;
    if (hidden || !chunks.length) { $("rec").title = t("recHidden"); return; }  // no broken file
    const blob = new Blob(chunks, { type: type.split(";")[0] });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${DATA.title || "style_atlas"}.${type.includes("mp4") ? "mp4" : "webm"}`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 60000);
  } finally {
    document.removeEventListener("visibilitychange", onHide);
    if (rec) rec.stream.getTracks().forEach((tr) => tr.stop());
    controls.autoRotate = was.auto; controls.autoRotateSpeed = was.speed;
    recordingNow = false; $("rec").disabled = false; $("spin").disabled = false;
    $("rec").textContent = t("rec");
  }
}
if (!recorderType()) { $("rec").disabled = true; }
$("rec").addEventListener("click", () => { recordTurn().catch((e) => { $("rec").title = String(e.message || e); }); });

$("names").addEventListener("click", () => {
  showNames = !showNames; $("names").classList.toggle("on", showNames); drawNames();
});

function label(text, at) {
  const cv = document.createElement("canvas"); cv.width = 1024; cv.height = 64;
  const g = cv.getContext("2d"); g.font = "34px system-ui, sans-serif";
  g.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--accent");
  g.fillText(text, 8, 42);
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: srgbTexture(cv), depthTest: false }));
  sp.position.copy(at); sp.scale.set(4.4, 0.275, 1);  // read from HOME_MEASURES
  sp.center.set(0, 0.5);  // the text starts at the axis end instead of covering it
  return sp;
}

function disposeTree(obj) {
  obj.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    if (o.material) { if (o.material.map) o.material.map.dispose(); o.material.dispose(); }
  });
}

function drawAxes() {
  if (axisLines) { scene.remove(axisLines); disposeTree(axisLines); axisLines = null; }
  if (layoutMode !== "measures") return;
  axisLines = new THREE.Group();
  const L = SPREAD * 1.05;
  const pts = [-L, -L, -L, L, -L, -L, -L, -L, -L, -L, L, -L, -L, -L, -L, -L, -L, L];
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
  axisLines.add(new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color: 0x8f949c })));
  const ends = [new THREE.Vector3(L, -L, -L), new THREE.Vector3(-L, L, -L), new THREE.Vector3(-L, -L, L)];
  ["axX", "axY", "axZ"].forEach((id, d) => {
    const key = $(id).value;
    axisLines.add(label(`${"XYZ"[d]}: ${t("m_" + key)} →`, ends[d]));
  });
  scene.add(axisLines);
}

function homeView() {
  return (layoutMode === "measures" ? HOME_MEASURES : HOME).clone();
}

function setupAxes() {
  const opts = ["map", ...availableMeasures()];
  const defaults = availableMeasures();
  ["axX", "axY", "axZ"].forEach((id, d) => {
    const sel = $(id); const cur = sel.value;
    sel.replaceChildren(...opts.map((k) => { const o = document.createElement("option"); o.value = k; o.textContent = t("m_" + k); return o; }));
    sel.value = cur && opts.includes(cur) ? cur : (defaults[d] || "map");
  });
  const ls = $("layoutSel");
  ls.replaceChildren(...["style", "measures"].map((k) => {
    const o = document.createElement("option"); o.value = k;
    o.textContent = t(k === "style" ? "layoutStyle" : "layoutMeasures"); return o;
  }));
  ls.value = layoutMode;
}

$("layoutSel").addEventListener("change", (e) => {
  layoutMode = e.target.value; $("axes").hidden = layoutMode !== "measures"; applyLayout();
  flyTo = { target: new THREE.Vector3(), cam: homeView(), k: 0 };
});
["axX", "axY", "axZ"].forEach((id) => $(id).addEventListener("change", applyLayout));
