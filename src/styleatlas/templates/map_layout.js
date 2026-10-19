// Layouts on top of the map (measure axes and their morph), group names floating in the
// scene, and recording a turn of the map. Joined after map.js by report.page_script.

/* ---------- layouts ---------- */
// Groups apart: a wall of pictures. Each group is a block of its own under its name, its pictures
// side by side in rows (those close on the map next to each other), and the blocks are packed close,
// largest first (packBlocks). Nothing overlaps, so every picture is seen whole at every zoom; the wall
// faces the camera and does not turn. The default for 2 to GROUPS_APART_MAX groups; a gallery of
// hundreds keeps the similarity layout.
const GROUPS_APART_MAX = 60;
const MOSAIC_POINT = pointSize;  // the picture size the wall is laid out for (+ and - only resize)
const MOSAIC_GAP = 0.06;  // between two neighbouring pictures, a share of one
const BLOCK_GAP = 1.4;  // between two groups' blocks, in pictures
const LABEL_ROOM = 2;  // above a block for its name, in pictures
const NAME_FILL = 0.8;  // the name's height in that room
const BLOCK_ASPECT = 1.3;  // a block is this much wider than tall
const PACK_WIDTHS = [0.7, 0.8, 0.9, 1, 1.1, 1.25, 1.4, 1.6];  // wall widths tried, times the width of a square-ish fill
const WALL_CLOSEST = 0.7;  // the camera comes no closer than this many pictures (one fills the view)
const NAME_CHARS = 28;  // longer names are cut, or one label would cover the map
const NAME_FONT = "600 30px system-ui, sans-serif", NAME_PAD = 24, NAME_BOX = 46;  // a name's canvas
const LAYOUT_PICK_KEY = "styleAtlasLayout";  // the layout picked last (not the measures)
let layoutMode = ["style", "groups"].includes(stored(LAYOUT_PICK_KEY)) ? stored(LAYOUT_PICK_KEY)
  : DATA.clusters.length >= 2 && DATA.clusters.length <= GROUPS_APART_MAX ? "groups" : "style";
let axisLines = null;
let MOSAIC = null;  // the wall's picture pitch and where each group's name goes (mosaicPositions)
if (layoutMode === "groups") pos.set(mosaicPositions());  // drawn that way from the first frame
layoutControls();

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

function nameText(full) { return full.length > NAME_CHARS ? full.slice(0, NAME_CHARS - 1) + "…" : full; }

function nameAspect(full) {  // a name label's width over its height, as nameSprite draws it
  const g = document.createElement("canvas").getContext("2d");  // called before the page is up: no shared one
  g.font = NAME_FONT;
  return (Math.ceil(g.measureText(nameText(full)).width) + NAME_PAD) / NAME_BOX;
}

function mosaicPitch() {  // the distance between two neighbouring pictures on the wall
  return MOSAIC_POINT * POINT_SCALE * 2 * Math.tan((camera.fov * Math.PI) / 360) * (1 + MOSAIC_GAP);
}

function viewAspect() {  // the map area's shape (the camera's aspect is set only once the page is up)
  const r = canvas.parentElement.getBoundingClientRect();
  return r.width > 0 && r.height > 0 ? r.width / r.height : 16 / 9;
}

function blockRows(members, cols) {  // top to bottom, then left to right, as the pictures lie on the map
  const top = [...members].sort((a, b) => basePos[b * 3 + 1] - basePos[a * 3 + 1]);
  const rows = [];
  for (let r = 0; r * cols < top.length; r++) {
    rows.push(top.slice(r * cols, (r + 1) * cols).sort((a, b) => basePos[a * 3] - basePos[b * 3]));
  }
  return rows;
}

function mosaicPositions() {
  const pitch = mosaicPitch(), room = LABEL_ROOM * pitch, nameH = room * NAME_FILL;
  const members = new Map();
  PTS.forEach((p, i) => (members.get(p.c) || members.set(p.c, []).get(p.c)).push(i));
  const blocks = [...members.entries()].map(([c, m]) => {
    const cols = Math.ceil(Math.sqrt(m.length * BLOCK_ASPECT));
    const rows = Math.ceil(m.length / cols);
    // the name always fits above its block: a small group's block is as wide as its name
    const w = Math.max(cols * pitch, nameH * nameAspect(clusterName(c)));
    return { c, m, cols, x: 0, y: 0, w, h: rows * pitch + room };
  });
  packBlocks(blocks, BLOCK_GAP * pitch);
  const target = new Float32Array(N * 3);  // z stays 0: the wall is flat
  const labels = new Map(), rowsOf = new Map();
  blocks.forEach((b) => {
    const left = b.x - b.w / 2, top = b.y + b.h / 2;
    const rows = blockRows(b.m, b.cols);
    rowsOf.set(b.c, rows);  // map_walk.js walks them in this order
    rows.forEach((row, r) => row.forEach((i, k) => {
      target[i * 3] = left + (k + 0.5) * pitch;
      target[i * 3 + 1] = top - room - (r + 0.5) * pitch;
    }));
    labels.set(b.c, { x: left, y: top - room + (room - nameH) / 3, h: nameH });
  });
  MOSAIC = { pitch, labels, rows: rowsOf };
  return target;
}

// The blocks packed into rows of a set width, largest first (the order of the side list): each one
// goes where it ends highest, so small blocks fill the room beside large ones (a skyline packing).
// Several widths are tried and the one whose wall fills the view best is kept: the larger the wall
// shows at the home view, the larger every picture is.

function packBlocks(blocks, gap) {
  const order = [...blocks].sort((a, b) => b.h - a.h || b.m.length - a.m.length);
  const area = blocks.reduce((sum, b) => sum + (b.w + gap) * (b.h + gap), 0);
  const aspect = viewAspect(), widest = Math.max(...blocks.map((b) => b.w + gap));
  let best = null;
  PACK_WIDTHS.forEach((k) => {
    const width = Math.max(widest, Math.sqrt(area * aspect) * k);
    const placed = skyline(order, width, gap);
    const fill = Math.max(placed.width / aspect, placed.height);  // what the view must take in
    if (!best || fill < best.fill) best = { ...placed, fill };
  });
  order.forEach((b, j) => {  // centres, the wall's middle at the origin
    b.x = best.at[j][0] + b.w / 2 - best.width / 2;
    b.y = best.height / 2 - (best.at[j][1] + b.h / 2);
  });
}

function skyline(order, width, gap) {  // top-left corners going down from 0; the size taken
  let line = [{ x: 0, w: width, y: 0 }];  // the filled depth across the width
  const at = [];
  order.forEach((b) => {
    const bw = b.w + gap, bh = b.h + gap;
    let pick = null;
    line.forEach((seg) => {
      if (seg.x + bw > width + 1e-9) return;
      const y = Math.max(...line.filter((o) => o.x < seg.x + bw - 1e-9 && o.x + o.w > seg.x + 1e-9).map((o) => o.y));
      if (!pick || y + bh < pick.y + bh - 1e-9 || (Math.abs(y - pick.y) < 1e-9 && seg.x < pick.x)) pick = { x: seg.x, y };
    });
    at.push([pick.x, pick.y]);
    const right = pick.x + bw;  // the line under the block rises to its bottom
    const cut = [];
    line.forEach((o) => {
      if (o.x + o.w <= pick.x + 1e-9 || o.x >= right - 1e-9) { cut.push(o); return; }
      if (o.x < pick.x) cut.push({ x: o.x, w: pick.x - o.x, y: o.y });
      if (o.x + o.w > right) cut.push({ x: right, w: o.x + o.w - right, y: o.y });
    });
    cut.push({ x: pick.x, w: bw, y: pick.y + bh });
    line = cut.sort((a, c) => a.x - c.x);
  });
  const used = Math.max(...order.map((b, j) => at[j][0] + b.w));
  const height = Math.max(...order.map((b, j) => at[j][1] + b.h));
  return { at, width: used, height };
}

// the wall faces the camera: either button drags it, nothing turns it, and its pictures grow with
// the zoom like the gaps between them; the 3D layouts turn with the right button
function layoutControls() {
  const wall = layoutMode === "groups";
  controls.enableRotate = !wall;
  controls.mouseButtons.RIGHT = wall ? THREE.MOUSE.PAN : THREE.MOUSE.ROTATE;
  controls.touches.TWO = wall ? THREE.TOUCH.DOLLY_PAN : THREE.TOUCH.DOLLY_ROTATE;
  controls.minDistance = wall && MOSAIC ? MOSAIC.pitch * WALL_CLOSEST : 0.15;
  SIZE_GROW.value = wall ? 1 : SIZE_GROW_3D;
  if (wall) setSpin(false);  // map.js
  $("spin").disabled = wall; $("rec").disabled = wall || !recorderType();
}

function targetPositions() {
  if (layoutMode === "groups") return mosaicPositions();
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
const MAX_NOTES = 40;  // notes drawn on the map (the details show every note)
const NOTE_COLOR = "#f5f5f5";
const NOTE_HEIGHT = 0.03;  // of the view's height
let nameSprites = null;
let showNames = true;

// In the 3D layouts group names keep one size on screen (a share of the view's height, as notes
// do): grown with the zoom they covered the very pictures one came closer to see. On the wall each
// name has its own room above its block, so it is part of the wall and grows with it.
const NAME_HEIGHT = 0.03;

function nameSprite(full, color, wallHeight = 0) {
  const text = nameText(full);
  const cv = document.createElement("canvas"); const g = cv.getContext("2d");
  g.font = NAME_FONT;
  cv.width = Math.ceil(g.measureText(text).width) + NAME_PAD; cv.height = NAME_BOX;
  g.font = NAME_FONT; g.fillStyle = "rgba(12,14,18,0.86)"; g.fillRect(0, 0, cv.width, cv.height);
  g.fillStyle = color; g.fillText(text, NAME_PAD / 2, 33);
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: srgbTexture(cv), depthTest: false, transparent: true,
    sizeAttenuation: wallHeight > 0 }));
  const h = wallHeight || NAME_HEIGHT;
  sp.scale.set(h * cv.width / cv.height, h, 1); sp.renderOrder = 10;
  return sp;
}

function wallNames() {  // every group's name in the room above its block, from its left edge
  MOSAIC.labels.forEach((at, c) => {
    const sp = nameSprite(clusterName(c), colorOf(c), at.h);
    sp.center.set(0, 0); sp.position.set(at.x, at.y, 0); sp.userData.c = c;
    nameSprites.add(sp);
  });
}

function drawNames() {
  if (nameSprites) { scene.remove(nameSprites); disposeTree(nameSprites); nameSprites = null; }
  if (!showNames) return;
  nameSprites = new THREE.Group();
  if (layoutMode === "groups" && MOSAIC) wallNames(); else floatingNames();
  drawNotes();
  scene.add(nameSprites);
  fadeNames();
}

function floatingNames() {  // the largest groups' names over their centres
  const sums = new Map();
  PTS.forEach((p, i) => {
    if (p.c < 0) return;
    const s = sums.get(p.c) || [0, 0, 0, 0];
    s[0] += pos[i * 3]; s[1] += pos[i * 3 + 1]; s[2] += pos[i * 3 + 2]; s[3] += 1; sums.set(p.c, s);
  });
  [...sums.entries()].sort((a, b) => b[1][3] - a[1][3]).slice(0, MAX_NAMES).forEach(([c, s]) => {
    const sp = nameSprite(clusterName(c), colorOf(c));
    sp.position.set(s[0] / s[3], s[1] / s[3] + 0.12, s[2] / s[3]); sp.userData.c = c;
    nameSprites.add(sp);
  });
}

function drawNotes() {
  Object.entries(NOTES).slice(0, MAX_NOTES).forEach(([k, text]) => {  // notes at their images
    const i = Number(k);
    if (!(i >= 0 && i < N) || !text) return;
    const sp = nameSprite(text, NOTE_COLOR);
    sp.scale.set(NOTE_HEIGHT * sp.scale.x / sp.scale.y, NOTE_HEIGHT, 1);
    sp.center.set(0, 0);  // starts at the image and reaches up and right, off its group's name
    sp.position.set(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]); sp.userData.note = i;
    nameSprites.add(sp);
  });
}

const DECLUTTER_MS = 250;  // how often overlapping group names are sorted out
let lastDeclutter = 0;
function declutterNames(now) {  // where group names overlap on screen, the larger (or focused) group's wins
  if (!nameSprites || now - lastDeclutter < DECLUTTER_MS) return;
  lastDeclutter = now;
  if (layoutMode === "groups" && MOSAIC) {  // the wall's names have rooms of their own: none overlap
    nameSprites.children.forEach((sp) => { if (sp.userData.note === undefined) sp.material.opacity = (sp.userData.base ?? 1) * nameZoomFade(); });
    return;
  }
  const w = canvas.clientWidth, h = canvas.clientHeight;
  const px = h / (4 * Math.tan((camera.fov * Math.PI) / 360));  // a fixed-size sprite's half size in pixels, per unit
  const toPx = (v) => { const p = v.clone().project(camera); return [(p.x + 1) / 2 * w, (1 - p.y) / 2 * h, p.z]; };
  const names = nameSprites.children.filter((sp) => sp.userData.note === undefined);  // notes always stay
  names.sort((a, b) => (b.userData.c === focusCluster) - (a.userData.c === focusCluster));  // stable: larger first
  const kept = [];
  names.forEach((sp) => {
    const [x, y, z] = toPx(sp.position);
    const hw = sp.scale.x * px, hh = sp.scale.y * px;
    const box = [x - hw, y - hh, x + hw, y + hh];
    const clash = z > 1 || kept.some((b) => box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1]);
    sp.visible = !clash;
    if (!clash) kept.push(box);
    sp.material.opacity = (sp.userData.base ?? 1) * nameZoomFade();
  });
}

// close in, the pictures matter more than their group's name: names step back (not notes)
const NAME_FADE_FROM = 0.6, NAME_FADE_TO = 0.3, NAME_FADE_MIN = 0.25;  // shares of the home distance
function nameZoomFade() {
  const k = camera.position.distanceTo(controls.target) / SIZE_REF.value;
  const t = Math.min(1, Math.max(0, (k - NAME_FADE_TO) / (NAME_FADE_FROM - NAME_FADE_TO)));
  return NAME_FADE_MIN + (1 - NAME_FADE_MIN) * t;
}

function fadeNames() {  // names step back with the points: a focused group keeps its own
  if (!nameSprites) return;
  const dimmed = selected !== null || searchHits !== null || filter !== "" || folderFilter !== null;
  nameSprites.children.forEach((sp) => {
    const own = sp.userData.note !== undefined ? PTS[sp.userData.note].c : sp.userData.c;
    const on = focusCluster !== null ? own === focusCluster : !dimmed;
    sp.userData.base = on ? 1 : 0.15;
    sp.material.opacity = sp.userData.base * (sp.userData.note === undefined ? nameZoomFade() : 1);
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
    if (hidden || !chunks.length) { $("rec").title = t("recHidden"); setStatus(t("recHidden")); return; }  // no broken file
    const blob = new Blob(chunks, { type: type.split(";")[0] });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${DATA.title || "style_atlas"}.${type.includes("mp4") ? "mp4" : "webm"}`;
    a.click();
    setStatus(t("downloaded").replace("{f}", a.download));
    setTimeout(() => URL.revokeObjectURL(a.href), 60000);
  } finally {
    document.removeEventListener("visibilitychange", onHide);
    if (rec) rec.stream.getTracks().forEach((tr) => tr.stop());
    controls.autoRotate = was.auto; controls.autoRotateSpeed = was.speed;
    recordingNow = false; $("rec").disabled = false; $("spin").disabled = false;
    $("rec").textContent = t("rec");
    layoutControls();  // switched to the wall meanwhile: it stays still
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
    axisLines.add(label(`${"XYZ"[d]}: ${t("m_" + key)} ${t("axisLowHigh")}`, ends[d]));
  });
  scene.add(axisLines);
}

// the true layout frames 95% of the points with room to spare; farther strays may lie outside
const FRAME_SHARE = 0.95, FRAME_ROOM = 1.35, FRAME_MIN_N = 50;
const WALL_HOME = new THREE.Vector3(0, 0, 1);  // the wall is looked at straight on
const WALL_MARGIN = 1.04;  // a little room around the wall, inside the band the bars leave free
const BAND_GAP = 10;  // px between the bars and the wall
const HOME_TARGET = new THREE.Vector3();  // where the home view looks (set by homeView)

// the map's height the title and tools above and the bottom bar leave free (they float over it)
function freeBand() {
  const r = canvas.getBoundingClientRect();
  const shown = (el) => el && el.offsetParent !== null && el.getBoundingClientRect().height > 0;
  const top = ["title", "hud"].map((id) => $(id)).filter(shown)
    .reduce((m, el) => Math.max(m, el.getBoundingClientRect().bottom - r.top), 0);
  const bar = $("live"), bottom = shown(bar) ? Math.max(0, r.bottom - bar.getBoundingClientRect().top) : 0;
  const free = Math.max(r.height * 0.5, r.height - top - bottom - 2 * BAND_GAP);  // a tiny window: overlap rather than vanish
  return { height: r.height, free, shift: (top - bottom) / 2 };  // shift: px the band's middle lies below the map's
}

function flyHome() {  // back to the home view, smoothly
  const cam = homeView();
  flyTo = { target: HOME_TARGET.clone(), cam, k: 0 };
  markHome(false);  // map.js: nothing to go back from
}

function homeView() {  // looking at the centre from HOME's direction, every point in view
  if (layoutMode === "measures") { SIZE_REF.value = HOME_MEASURES.length(); return HOME_MEASURES.clone(); }
  const wall = layoutMode === "groups" && MOSAIC;
  const back = (wall ? WALL_HOME : HOME).clone().normalize();  // from the centre towards the camera
  const right = new THREE.Vector3(0, 1, 0).cross(back).normalize();
  const up = back.clone().cross(right);
  const tanV = Math.tan((camera.fov * Math.PI) / 360);
  const tanH = tanV * camera.aspect;
  const band = wall ? freeBand() : null;
  const tanY = wall ? tanV * (band.free / Math.max(1, band.height)) : tanV;  // the wall fits the free band
  const at = morph ? morph.to : pos;  // a layout being switched to: where its points are going
  const q = new THREE.Vector3();
  const need = (x, y, z, room) => {  // the distance at which a point still fits, with room around it
    q.set(x, y, z);
    return Math.max(q.dot(back) + (Math.abs(q.dot(right)) + room) / tanH, q.dot(back) + (Math.abs(q.dot(up)) + room) / tanY);
  };
  const needs = Array.from({ length: N }, (_, i) => need(at[i * 3], at[i * 3 + 1], at[i * 3 + 2], pointSize / 2));
  if (wall) MOSAIC.labels.forEach((l) => needs.push(need(l.x, l.y + l.h, 0, 0)));  // the names above the top row
  needs.sort((a, b) => a - b);
  // the wall: all of it in view. The true layout: the bulk fills the view, one far stray (zoom out
  // to see it) no longer shrinks the rest to a ball in the middle
  const all = needs.length ? needs[needs.length - 1] : 0;
  const bulk = needs[Math.floor(FRAME_SHARE * (N - 1))] * FRAME_ROOM;
  const fit = layoutMode === "style" && N >= FRAME_MIN_N ? Math.min(all, bulk) : all;
  const far = wall ? Infinity : HOME_MAX;  // the wall is all of it in view, however large
  const distance = Number.isFinite(fit) ? Math.min(far, Math.max(1, fit * (wall ? WALL_MARGIN : HOME_MARGIN))) : HOME.length();  // a 0x0 canvas
  controls.maxDistance = Math.max(HOME_MAX, distance) * 2;
  // the wall's middle at the free band's middle: the camera looks a little above it
  HOME_TARGET.set(0, wall ? (band.shift * 2 * distance * tanV) / Math.max(1, band.height) : 0, 0);
  SIZE_REF.value = distance;  // map.js: pictures drawn at plain perspective size from here
  return back.multiplyScalar(distance).add(HOME_TARGET);
}

function setupAxes() {
  const opts = ["map", ...availableMeasures()];
  // a library of many artists: time across them says little, so it is not a default axis
  const defaults = availableMeasures().filter((k) => k !== "time" || folderNames().length < 2);
  ["axX", "axY", "axZ"].forEach((id, d) => {
    const sel = $(id); const cur = sel.value;
    sel.replaceChildren(...opts.map((k) => { const o = document.createElement("option"); o.value = k; o.textContent = t("m_" + k); return o; }));
    sel.value = cur && opts.includes(cur) ? cur : (defaults[d] || "map");
  });
  layoutShown();
}

// groups apart / true layout: the switch at the top; the measure axes from the View menu
function setLayout(next) {
  if (!["groups", "style", "measures"].includes(next) || next === layoutMode) return;
  layoutMode = next; applyLayout(); layoutControls(); walkLayoutChanged();  // map_walk.js
  if (layoutMode !== "measures") store(LAYOUT_PICK_KEY, layoutMode);
  flyHome();
  layoutShown();
}

function layoutShown() {  // the switch, the axis menus and the line under the title follow the layout
  document.querySelectorAll("#layoutSeg button").forEach((b) => b.classList.toggle("on", b.dataset.layout === layoutMode));
  $("layoutMeasures").classList.toggle("on", layoutMode === "measures");
  $("axes").hidden = layoutMode !== "measures";
  const note = document.querySelector("#title .layout-note");
  note.hidden = layoutMode === "measures";
  note.textContent = t(layoutMode === "groups" ? "layoutNoteGroups" : "layoutNoteStyle");
}

document.querySelectorAll("#layoutSeg button").forEach((b) => b.addEventListener("click", () => setLayout(b.dataset.layout)));
$("layoutMeasures").addEventListener("click", () => { closeViewMenu(); setLayout(layoutMode === "measures" ? "groups" : "measures"); });
["axX", "axY", "axZ"].forEach((id) => $(id).addEventListener("change", applyLayout));
