import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const DATA = JSON.parse(document.getElementById("atlas-data").textContent);
const PTS = DATA.points;
const N = PTS.length;
let NOTES = DATA.notes || {};  // index -> a note on that image, drawn at its point
// per-viewer choices kept across the reload an edit makes (and the next visit)
const LANG_KEY = "styleAtlasLang", THEME_KEY = "styleAtlasTheme";
function stored(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
function store(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* storage off */ } }
let lang = ["zh", "en"].includes(stored(LANG_KEY)) ? stored(LANG_KEY)
  : (navigator.language || "en").toLowerCase().startsWith("zh") ? "zh" : "en";
if (["light", "dark"].includes(stored(THEME_KEY))) document.documentElement.dataset.theme = stored(THEME_KEY);
const t = (k) => T[lang][k];
const $ = (id) => document.getElementById(id);

const PALETTE = ["#f2994a","#56ccf2","#bb6bd9","#6fcf97","#eb5757","#f2c94c","#2d9cdb","#9b51e0",
  "#27ae60","#e0607e","#a0d468","#ff9f80","#4fc1e9","#ac92ec","#48cfad","#fc6e51","#ffce54",
  "#5d9cec","#ed5565","#8cc152"];
const colorOf = (c) => c < 0 ? "#6b7078" : PALETTE[c % PALETTE.length];

/* ---------- three.js scene ---------- */
const canvas = $("gl");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(50, 1, 0.01, 100);
const HOME = new THREE.Vector3(0, 0.6, 3.1);
const HOME_MEASURES = new THREE.Vector3(3.0, 2.2, 4.6);  // the whole axis cube, at an angle
const HOME_MARGIN = 1.12;  // room for the bars above and below the map
const HOME_MAX = 9;
camera.position.copy(HOME);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
// A long scroll used to carry the camera past the far plane (the whole map gone) or into the
// points; the widest home view is HOME_MAX away
controls.minDistance = 0.15;
controls.maxDistance = HOME_MAX * 2;
controls.autoRotate = false;
controls.autoRotateSpeed = 0.6;
// like a map or a picture viewer: the wheel zooms where the cursor points, the left button moves
// the map and the right one turns it (turning is seldom wanted while looking at pictures)
controls.zoomToCursor = true;
controls.zoomSpeed = 1.5;  // 7% a wheel step (1: 5%, which took eight steps to come 1.5x closer)
controls.mouseButtons = { LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.ROTATE };
controls.touches = { ONE: THREE.TOUCH.PAN, TWO: THREE.TOUCH.DOLLY_ROTATE };
const SPREAD = 1.6;
const pos = new Float32Array(N * 3);
PTS.forEach((p, i) => { pos[i*3] = p.p[0]*SPREAD; pos[i*3+1] = p.p[1]*SPREAD; pos[i*3+2] = p.p[2]*SPREAD; });
const basePos = pos.slice();
let morph = null;

function setBackground() {
  scene.background = new THREE.Color(getComputedStyle(document.documentElement).getPropertyValue("--bg").trim());
}
setBackground();

const CELL = N <= 4096 ? 128 : 64;   // atlas pages are 4096 px squares (up to 4 of them at 128 px)
const PER_ROW = 4096 / CELL;
const PER_PAGE = PER_ROW * PER_ROW;
const pages = [];
const alpha = new Float32Array(N).fill(1);
const ASPECT = new Float32Array(N);  // width / height of each picture, once its thumbnail is in (0 before)
let mode = N <= 6000 ? "thumbs" : "dots";
let pointSize = Math.min(0.4, Math.max(0.05, 1.6 / Math.cbrt(Math.max(N, 1))));
// In the 3D layouts pictures grow slower than the gaps between them as the camera comes closer, so
// zooming in pulls a crowded group apart (grown like the gaps, pictures that overlap overlap at
// every zoom). The wall of groups (map_layout.js) has no overlaps: its pictures grow like the gaps.
// At the home view's distance the size is as plain perspective would draw it.
const SIZE_GROW_3D = 0.5;  // 1 = plain perspective
const SIZE_GROW = { value: SIZE_GROW_3D };  // shared by every page's material; set by layoutControls()
const SIZE_REF = { value: HOME.length() };  // shared too; set by homeView()
const POINT_SCALE = 0.9;  // a picture's drawn size: its size (world units) x this x the view's height / distance
function depthScale(depth) { return 1 / (SIZE_REF.value * Math.pow(Math.max(depth, 1e-3) / SIZE_REF.value, SIZE_GROW.value)); }

const VERT = `
  attribute float aAlpha; attribute vec2 aCell; attribute vec3 aColor; attribute float aScale;
  uniform float uSize; uniform float uScale; uniform float uRef; uniform float uGrow;
  varying float vAlpha; varying vec2 vCell; varying vec3 vColor;
  void main() {
    vAlpha = aAlpha; vCell = aCell; vColor = aColor;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    float depth = max(-mv.z, 0.001);  // as depthScale() in the page script
    gl_PointSize = uSize * uScale * aScale / (uRef * pow(depth / uRef, uGrow)) * (0.55 + 0.45 * aAlpha);
    gl_Position = projectionMatrix * mv;
  }`;
const FRAG = `
  uniform sampler2D uAtlas; uniform float uCell; uniform int uMode;
  varying float vAlpha; varying vec2 vCell; varying vec3 vColor;
  void main() {
    vec2 pc = gl_PointCoord;  // canvas row 0 is the top and flipY is off, so no flip
    if (uMode == 1) {
      float d = length(gl_PointCoord - 0.5);
      if (d > 0.5) discard;
      float edge = smoothstep(0.5, 0.42, d);
      gl_FragColor = vec4(vColor, edge * (0.25 + 0.75 * vAlpha));
    } else {
      vec4 c = texture2D(uAtlas, (vCell + pc) * uCell);
      if (c.a < 0.08) discard;
      gl_FragColor = vec4(c.rgb * (0.35 + 0.65 * vAlpha), c.a * (0.2 + 0.8 * vAlpha));
    }
    // the texture is decoded from sRGB and THREE.Color works in linear: encode back for the screen,
    // or every thumbnail shows darker and more saturated than the file (yellow 255,183,3 as orange)
    #include <colorspace_fragment>
  }`;

async function loadImage(src, retries = 1) {
  const img = new Image();
  img.src = src;
  try { await img.decode(); return img; } catch {
    if (retries <= 0) return null;
    await new Promise((r) => setTimeout(r, 800));  // a busy server may have dropped it
    return loadImage(src, retries - 1);
  }
}

// The pages are made at once with a coloured dot in every cell, so the map shows straight away;
// fillPages() then draws the thumbnails in, page by page (a large gallery takes a while).
function buildPages() {
  for (let start = 0; start < N; start += PER_PAGE) {
    const count = Math.min(PER_PAGE, N - start);
    const cv = document.createElement("canvas");
    cv.width = PER_ROW * CELL; cv.height = PER_ROW * CELL;
    const g = cv.getContext("2d");
    for (let j = 0; j < count; j++) drawDot(g, j, colorOf(PTS[start + j].c));
    pages.push({ ...makePage(start, count, cv), cv });
  }
}

// thumbnails asked for together: all of a page at once (2,206) ran out of sockets
// (ERR_NO_BUFFER_SPACE) and left the retry to fill the gaps
const LOAD_AT_ONCE = 96;

async function fillPages() {
  let done = 0;
  for (const pg of pages) {
    const g = pg.cv.getContext("2d");
    for (let s = 0; s < pg.count; s += LOAD_AT_ONCE) {
      const part = PTS.slice(pg.start + s, pg.start + Math.min(pg.count, s + LOAD_AT_ONCE));
      const imgs = await Promise.all(part.map((p) => p.t ? loadImage(p.t) : null));
      imgs.forEach((img, k) => {
        if (!img) return;
        const j = s + k;
        ASPECT[pg.start + j] = img.width / Math.max(1, img.height);
        drawThumb(g, j, img, colorOf(PTS[pg.start + j].c));
      });
      done += part.length;
      $("loading").textContent = `${t("loading")} ${done} / ${N}`;
    }
    pg.mat.uniforms.uAtlas.value.needsUpdate = true;
  }
  $("loading").style.display = "none";
  aspectsKnown();  // map_layout.js: the wall can take each picture's shape now
}

function drawDot(g, j, col) {
  const x0 = (j % PER_ROW) * CELL, y0 = Math.floor(j / PER_ROW) * CELL;
  g.fillStyle = col; g.beginPath(); g.arc(x0 + CELL / 2, y0 + CELL / 2, CELL / 10, 0, 7); g.fill();
}

function drawThumb(g, j, img, col) {
  const x0 = (j % PER_ROW) * CELL, y0 = Math.floor(j / PER_ROW) * CELL;
  const s = (CELL - 8) / Math.max(img.width, img.height);
  const w = img.width * s, h = img.height * s;
  const x = x0 + (CELL - w) / 2, y = y0 + (CELL - h) / 2;
  g.clearRect(x0, y0, CELL, CELL);
  g.fillStyle = col; g.fillRect(x - 4, y - 4, w + 8, h + 8);
  g.drawImage(img, x, y, w, h);
}

function makePage(start, count, cv) {
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.flipY = false;
  tex.minFilter = THREE.LinearMipmapLinearFilter;
  tex.anisotropy = 4;
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos.slice(start * 3, (start + count) * 3), 3));
  const cell = new Float32Array(count * 2), color = new Float32Array(count * 3);
  const tmp = new THREE.Color();
  for (let j = 0; j < count; j++) {
    cell[j*2] = j % PER_ROW; cell[j*2+1] = Math.floor(j / PER_ROW);
    tmp.set(colorOf(PTS[start + j].c)); color.set([tmp.r, tmp.g, tmp.b], j * 3);
  }
  geo.setAttribute("aCell", new THREE.BufferAttribute(cell, 2));
  geo.setAttribute("aColor", new THREE.BufferAttribute(color, 3));
  geo.setAttribute("aAlpha", new THREE.BufferAttribute(alpha.slice(start, start + count), 1));
  geo.setAttribute("aScale", new THREE.BufferAttribute(SCALE.slice(start, start + count), 1));  // map_layout.js
  const mat = new THREE.ShaderMaterial({
    vertexShader: VERT, fragmentShader: FRAG, transparent: true, depthWrite: true,
    uniforms: { uAtlas: { value: tex }, uCell: { value: 1 / PER_ROW }, uSize: { value: pointSize },
      uScale: { value: 1 }, uRef: SIZE_REF, uGrow: SIZE_GROW, uMode: { value: mode === "dots" ? 1 : 0 } },
  });
  const obj = new THREE.Points(geo, mat);
  scene.add(obj);
  return { start, count, obj, mat, geo };
}

function pushScale() {  // map_layout.js: the wall's shaped cells
  for (const pg of pages) {
    const a = pg.geo.getAttribute("aScale");
    a.array.set(SCALE.subarray(pg.start, pg.start + pg.count));
    a.needsUpdate = true;
  }
}

function pushAlpha() {
  for (const pg of pages) {
    const a = pg.geo.getAttribute("aAlpha");
    a.array.set(alpha.subarray(pg.start, pg.start + pg.count));
    a.needsUpdate = true;
  }
}

function resize() {
  const r = canvas.parentElement.getBoundingClientRect();
  renderer.setSize(r.width, r.height, false);
  camera.aspect = r.width / r.height;
  camera.updateProjectionMatrix();
  const scale = r.height * renderer.getPixelRatio() * POINT_SCALE;
  for (const pg of pages) pg.mat.uniforms.uScale.value = scale;
}
addEventListener("resize", resize);

/* ---------- interaction ---------- */
let focusCluster = null, selected = null, filter = "", searchHits = null;
let folderFilter = null;  // a sub-folder picked from a search's closest folders
let tagOnly = null;  // {tag, hits}: the images a #tag filter found; searches stay inside them
let flyTo = null;

function filterOn() { return searchHits !== null || filter !== "" || folderFilter !== null; }
function shownByFilter(i) {  // in what a filter, a sub-folder or a search shows (not a picked picture's neighbours)
  const q = filter.toLowerCase();
  return (!q || PTS[i].n.toLowerCase().includes(q)) && (folderFilter === null || PTS[i].n.startsWith(folderFilter + "/"))
    && (!searchHits || searchHits.has(i));
}

function recolor() {  // returns how many images are lit
  const q = filter.toLowerCase();
  let lit = 0;
  for (let i = 0; i < N; i++) {
    let on = true;
    if (focusCluster !== null) on = PTS[i].c === focusCluster;
    if (q) on = on && PTS[i].n.toLowerCase().includes(q);
    if (folderFilter !== null) on = on && PTS[i].n.startsWith(folderFilter + "/");
    if (selected !== null) on = i === selected || PTS[selected].k.includes(i);
    else if (searchHits) on = searchHits.has(i);
    alpha[i] = on ? 1 : 0.12;
    lit += on ? 1 : 0;
    // marks sit on top of the view: marked bright, the rest visible but softer (still pickable)
    if (MARKED.size) alpha[i] = MARKED.has(i) ? 1 : on ? 0.6 : 0.12;
    if (EXCLUDED.has(i)) alpha[i] = Math.min(alpha[i], 0.25);  // excluded: still there, faded
  }
  pushAlpha();
  fadeNames();
  filterChip();
  homeShown();
  return lit;
}

function filterChip() {  // a filter in force, shown with a way out
  const chip = $("filterChip");
  const what = folderFilter !== null ? folderFilter + "/" : filter;
  chip.hidden = !what;
  if (what) chip.textContent = `${t("filterOn").replace("{f}", what)} ✕`;
}
$("filterChip").addEventListener("click", () => {
  filter = ""; folderFilter = null; tagOnly = null; $("find").value = ""; recolor();
});

function centerOf(indices) {
  const c = new THREE.Vector3();
  indices.forEach((i) => c.add(new THREE.Vector3(pos[i*3], pos[i*3+1], pos[i*3+2])));
  return c.multiplyScalar(1 / Math.max(1, indices.length));
}

function focusOn(indices) {
  const target = centerOf(indices);
  let radius = 0;
  indices.forEach((i) => { radius = Math.max(radius, target.distanceTo(new THREE.Vector3(pos[i*3], pos[i*3+1], pos[i*3+2]))); });
  const dir = camera.position.clone().sub(controls.target).normalize();
  const dist = Math.min(3.2, Math.max(0.9, radius * 2.4 + pointSize * 4));
  flyTo = { target, cam: target.clone().add(dir.multiplyScalar(dist)), k: 0 };
  setSpin(false);
  markHome(true);
}

const ray = new THREE.Vector3();
function pick(ev) {
  const r = canvas.getBoundingClientRect();
  const mx = ev.clientX - r.left, my = ev.clientY - r.top;
  let best = -1, bestD = Infinity;
  const radius = 8;
  for (let i = 0; i < N; i++) {
    if (alpha[i] < 0.5) continue;
    ray.set(pos[i*3], pos[i*3+1], pos[i*3+2]).project(camera);
    if (ray.z > 1) continue;
    const sx = (ray.x + 1) / 2 * r.width, sy = (1 - ray.y) / 2 * r.height;
    const d = Math.hypot(sx - mx, sy - my);
    const depth = camera.position.distanceTo(new THREE.Vector3(pos[i*3], pos[i*3+1], pos[i*3+2]));
    const reach = Math.max(radius, pointSize * SCALE[i] * r.height * POINT_SCALE / 2 * depthScale(depth));
    if (d < reach && depth + d * 0.002 < bestD) { bestD = depth + d * 0.002; best = i; }
  }
  return best;
}

let downAt = null;
canvas.addEventListener("pointerdown", (e) => { downAt = e.button === 0 ? [e.clientX, e.clientY] : null; });
canvas.addEventListener("pointerup", (e) => {
  if (!downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 5) return;
  const i = pick(e);
  if (i >= 0 && e.shiftKey && DATA.live) toggleMark(i);
  else if (i >= 0) select(i); else { selected = null; recolor(); }
});
canvas.addEventListener("pointermove", (e) => {
  const tip = $("tip");
  if (e.buttons) { if (!WALK.on) hideTip(); return; }  // map_walk.js: a walk keeps its picture shown
  const i = pick(e);
  if (i < 0) { if (!WALK.on) hideTip(); canvas.style.cursor = "grab"; return; }
  canvas.style.cursor = "pointer";
  if (tip.style.display !== "block") {  // a fresh preview stands on the side away from the cursor
    const r = canvas.getBoundingClientRect();
    tipSide = e.clientX - r.left < r.width / 2 ? 1 : -1;
  }
  if (WALK.on && i !== WALK.at) walkPause();  // map_walk.js: the mouse took over
  if (tipAt !== i) showTipPicture(tip, i);
  if (!WALK.on) tip.querySelector(".cap").textContent = `${PTS[i].n} · ${clusterName(PTS[i].c)}`;
  tip.style.display = "block";
  placeTip(tip, e.clientX, e.clientY);
});

// The preview: as large as half the map allows, on the half away from the cursor (it moves across
// when the cursor comes to it), so it never covers the picture pointed at. The small thumbnail
// shows at once, the 512 px view next, and the original once the cursor rests on the picture.
const PEEK_MARGIN = 16;  // px from the map's edges
const PEEK_WIDTH = 0.46;  // of the map's width, at most
const PEEK_REST_MS = 140;  // the cursor rests this long before the original is read
const PEEK_UPSCALE = 2;  // a shared map file's picture is shown at most this much enlarged (more blurs)
let tipAt = -1, tipXY = [0, 0], tipSide = 1, peekTimer = 0, tipTier = -1;  // tier: 0 thumbnail, 1 view, 2 original

function hideTip() { $("tip").style.display = "none"; tipAt = -1; clearTimeout(peekTimer); }

function placeTip(tip, x, y) {
  const r = canvas.getBoundingClientRect(), mx = x - r.left;
  tipXY = [x, y];
  const w = tip.offsetWidth, h = tip.offsetHeight;
  const at = (side) => (side > 0 ? r.width - w - PEEK_MARGIN : PEEK_MARGIN);
  if (mx > at(tipSide) - PEEK_MARGIN && mx < at(tipSide) + w + PEEK_MARGIN) tipSide = -tipSide;
  tip.style.left = Math.max(0, at(tipSide)) + "px";
  tip.style.top = Math.max(PEEK_MARGIN, (r.height - h) / 2) + "px";
}

function fitTip(tip, img) {  // the picture as large as the room allows, its own shape kept
  const r = canvas.getBoundingClientRect(), cap = tip.querySelector(".cap"), keys = tip.querySelector(".keys");
  const lines = (cap.offsetHeight || 24) + keys.offsetHeight;  // the keys line shows while walking (map_walk.js)
  const roomW = r.width * PEEK_WIDTH - 16, roomH = r.height - 2 * PEEK_MARGIN - 16 - lines;
  const most = img.dataset.final ? PEEK_UPSCALE : Infinity;  // a shared file's own picture: not blown up
  const w = img.naturalWidth || 1, h = img.naturalHeight || 1, k = Math.min(roomW / w, roomH / h, most);
  img.style.width = `${Math.max(1, Math.round(w * k))}px`; img.style.height = `${Math.max(1, Math.round(h * k))}px`;
  cap.style.maxWidth = keys.style.maxWidth = img.style.width;  // a long file name wraps under the picture
}

function swapTipPicture(tip, i, url, tier, then = null) {  // shown once it is decoded: no blank between
  const next = new Image();
  next.alt = ""; next.src = url;
  if (tier === 1 && !DATA.live) next.dataset.final = "1";  // the sharpest a shared file has
  next.decode().then(() => {
    if (tipAt !== i || tier < tipTier) return;  // a sharper one is in already
    tipTier = tier;
    tip.querySelector("img").replaceWith(next);
    fitTip(tip, next);
    if (tip.style.display === "block") placeTip(tip, ...tipXY);
    if (then) then();
  }).catch(() => {});  // a file gone or unreadable: the sharper one so far stays
}

function showTipPicture(tip, i) {
  tipAt = i;
  clearTimeout(peekTimer);
  tip.querySelector("img").style.visibility = "hidden";  // not the last picture's while this one loads
  tipTier = -1;
  swapTipPicture(tip, i, PTS[i].t, 0);
  if (!DATA.live) {  // a shared map file: its own sharper picture, if it was saved with them
    if (PTS[i].v) swapTipPicture(tip, i, PTS[i].v, 1);
    return;
  }
  swapTipPicture(tip, i, `view/${i}`, 1, () => {
    peekTimer = setTimeout(() => { if (tipAt === i) swapTipPicture(tip, i, PTS[i].f, 2); }, PEEK_REST_MS);
  });
}
canvas.addEventListener("pointerleave", () => { if (!WALK.on) hideTip(); });

const TIMES = PTS.map((p) => p.ts).filter((v) => v !== null && v !== undefined);
const TMIN = TIMES.reduce((a, b) => Math.min(a, b), Infinity);
const TMAX = TIMES.reduce((a, b) => Math.max(a, b), -Infinity);
const HAS_TIME = DATA.time_source && DATA.time_source !== "none" && TIMES.length > 1 && TMAX > TMIN;

const SORTED_TIMES = [...TIMES].sort((a, b) => a - b);

const DATE_NUMBER = /^(19|20)\d\d(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])$/;  // 20230512 from a name
// months only when every time in the folder reads as a date: a Pixiv id like 20121215 alone is not
const NAME_DATES = TIMES.length > 0 && TIMES.every((v) => DATE_NUMBER.test(String(Math.round(v))));

function fmtTime(v) {  // a month, or null for an id in a file name (its number says no date)
  if (DATA.time_source === "mtime") return new Date(v * 1000).toISOString().slice(0, 7);
  const s = String(Math.round(v));
  return NAME_DATES ? `${s.slice(0, 4)}-${s.slice(4, 6)}` : null;
}

function timeRank(v) {  // 0 the folder's oldest .. 1 its newest: ids far apart do not squash the rest
  let lo = 0, hi = SORTED_TIMES.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (SORTED_TIMES[mid] < v) lo = mid + 1; else hi = mid; }
  return lo / Math.max(1, SORTED_TIMES.length - 1);
}

function timeStrip(members, color) {
  const ts = members.map((i) => PTS[i].ts).filter((v) => v !== null && v !== undefined);
  if (!HAS_TIME || !ts.length) return null;
  const BINS = 30, W = 120, H = 16;
  const bins = new Array(BINS).fill(0);
  ts.forEach((v) => bins[Math.min(BINS - 1, Math.floor(timeRank(v) * BINS))]++);
  const cv = document.createElement("canvas"); cv.width = W; cv.height = H;
  const g = cv.getContext("2d"); const top = Math.max(...bins);
  g.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--line"); g.fillRect(0, H - 1, W, 1);
  g.fillStyle = color;
  bins.forEach((b, i) => { if (b) { const h = Math.max(2, b / top * (H - 2)); g.fillRect(i * (W / BINS), H - 1 - h, W / BINS - 1, h); } });
  const wrap = document.createElement("div"); wrap.className = "when";
  const label = document.createElement("span");
  const [first, last] = [fmtTime(Math.min(...ts)), fmtTime(Math.max(...ts))];
  label.textContent = first && last ? `${first} – ${last}` : t("whenOrder");
  wrap.title = t(DATA.time_source === "mtime" ? "whenMtime" : "whenName");
  wrap.append(cv, label);
  return wrap;
}

function clusterName(c) {
  if (c < 0) return t("unassigned");
  const named = ((DATA.live && DATA.live.names) || DATA.names || {})[String(c)];
  const word = t(DATA.method === "timeline" ? "periodName" : DATA.families ? "familyName" : "style");  // periods: earliest first
  if (named && DATA.method !== "timeline") return named;  // a name given (or a folder's) says it
  return named ? `${word} ${c + 1} · ${named}` : `${word} ${c + 1}`;
}

function thumb(i, onClick) {
  const img = document.createElement("img");
  img.src = PTS[i].t; img.alt = PTS[i].n; img.title = PTS[i].n; img.loading = "lazy";
  if (EXCLUDED.has(i)) { img.classList.add("excluded"); img.title += ` · ${t("excludedMark")}`; }
  img.addEventListener("click", onClick || ((e) => (e.shiftKey && DATA.live ? toggleMark(i) : select(i))));
  img.addEventListener("dblclick", () => openViewer(i, gridOrder(img)));  // map_viewer.js
  return img;
}

function noteBox(i) {  // live app: a note on this image, saved with Enter, shown on the map
  const box = document.createElement("input"); box.type = "text"; box.maxLength = 80;
  box.className = "note"; box.placeholder = t("notePlaceholder"); box.title = t("noteTip");
  box.value = NOTES[String(i)] || ""; box.setAttribute("aria-label", t("notePlaceholder"));
  box.addEventListener("keydown", async (e) => {
    e.stopPropagation();
    if (e.key !== "Enter" || e.isComposing || e.keyCode === 229) return;  // not while an IME picks
    try {
      const r = await post("api/note", JSON.stringify({ i, text: box.value }), "application/json");
      NOTES = r.notes; drawNames(); setStatus(t(box.value.trim() ? "noteSaved" : "noteCleared"));
    } catch (err) { setStatus(String(err.message || err)); }
  });
  return box;
}

function captionLine(i) {  // live app: the caption's tags, filled in when they arrive
  const box = document.createElement("div"); box.className = "meta tags";
  post("api/caption", JSON.stringify({ i }), "application/json").then((r) => {
    box.textContent = r.file ? `${r.file}${lang === "zh" ? "：" : ": "}${r.tags.join(", ") || t("captionEmpty")}` : t("captionNone");
  }).catch(() => { box.textContent = ""; });
  return box;
}

function select(i) {
  selected = i; searchHits = null; recolor();
  focusOn([i, ...PTS[i].k.slice(0, 4)]);
  const pane = $("pane-selected");
  pane.replaceChildren();
  const big = document.createElement("img");
  big.className = "big"; big.src = PTS[i].f; big.alt = PTS[i].n;
  big.onerror = () => { big.onerror = null; big.src = PTS[i].t; };
  big.title = t("keyViewer");
  big.addEventListener("click", () => openViewer(i, [i, ...PTS[i].k]));  // map_viewer.js
  pane.append(big);
  if (DATA.live) pane.append(findSimilarButton(i));  // map_browse.js: the one thing people want here
  const kv = document.createElement("div"); kv.className = "kv";
  const b = document.createElement("b"); b.textContent = PTS[i].n;
  kv.append(b, document.createElement("br"),
    document.createTextNode(`${clusterName(PTS[i].c)} · ${t("m_outlier")} ${PTS[i].o.toFixed(3)}` +
      paren(t("outlierRank").replace("{p}", outlierRank(PTS[i].o))) + " · " +
      (HAS_TIME && PTS[i].ts !== null && fmtTime(PTS[i].ts) ? `${fmtTime(PTS[i].ts)} · ` : "") +
      (DATA.reference && PTS[i].r !== null ? `${t("m_ref")} ${PTS[i].r.toFixed(3)} (${PTS[i].rn}) · ` : "")));
  const a = document.createElement("a"); a.href = PTS[i].f; a.target = "_blank"; a.rel = "noopener";
  a.textContent = t(DATA.live ? "open" : "openShared"); a.style.color = "var(--accent)"; kv.append(a);
  if (DATA.live) a.addEventListener("click", (e) => { e.preventDefault(); openOriginal(i, false); });  // map_viewer.js
  if (!DATA.live) a.title = t("openSharedTip");  // a shared file links to the sender's folder
  pane.append(kv);
  if (DATA.live) pane.append(voteButtons(i), captionLine(i), noteBox(i));
  else if (NOTES[String(i)]) { const n = document.createElement("div"); n.className = "meta"; n.textContent = `${t("noteLabel")}${NOTES[String(i)]}`; pane.append(n); }
  const h = document.createElement("h3"); h.textContent = t("nearest"); pane.append(h);
  const order = document.createElement("div"); order.className = "kv"; order.textContent = t("nearestOrder");
  const g = document.createElement("div"); g.className = "grid";
  PTS[i].k.forEach((j) => g.append(thumb(j)));
  pane.append(order, g);
  showPane("selected");
}

const LORA_SUBS = ["outliers", "dups"];  // the check and the duplicates sit inside the LoRA tab
function showPane(name) {  // the details tab shows once something is in it
  if (name === "selected") document.querySelector('.tabs button[data-pane="selected"]').hidden = false;
  const sub = LORA_SUBS.includes(name) ? name : null;
  const pane = sub ? "lora" : name;
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.pane === pane));
  document.querySelectorAll(".pane").forEach((p) => p.classList.toggle("on", p.id === "pane-" + pane));
  if (!sub) return;
  document.querySelectorAll(".subtabs button").forEach((b) => b.classList.toggle("on", b.dataset.sub === sub));
  document.querySelectorAll(".subpane").forEach((p) => p.classList.toggle("on", p.id === "pane-" + sub));
}
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showPane(b.dataset.pane)));
document.querySelectorAll(".subtabs button").forEach((b) => b.addEventListener("click", () => showPane(b.dataset.sub)));

function buildClusters() {
  const pane = $("pane-clusters");
  pane.replaceChildren();
  MAIN_FOLDERS = null;
  const groups = [...DATA.clusters.map((c) => ({ ...c, members: [] }))];
  const un = { id: -1, size: 0, medoid: -1, members: [] };
  PTS.forEach((p, i) => (p.c >= 0 ? groups[p.c].members : un.members).push(i));
  un.size = un.members.length; if (un.size) un.medoid = un.members[0];
  GROUPS = [...groups, ...(un.size ? [un] : [])];
  if (DATA.live) $("loraAdvice").replaceChildren(loraAdvice());  // map_browse.js: in the LoRA tab
  for (const c of GROUPS) {
    const row = document.createElement("div"); row.className = "cl"; row.dataset.id = String(c.id);
    row.tabIndex = 0; row.setAttribute("role", "button"); row.title = t("gvOpenTip");
    const img = document.createElement("img"); img.src = PTS[c.medoid]?.t || ""; img.alt = "";
    img.style.borderColor = colorOf(c.id);
    row.append(img, clusterCard(c));
    row.addEventListener("click", () => (viewGroup === c.id ? closeGroup() : openGroup(c.id)));  // map_group.js
    row.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target === row) row.click(); });
    pane.append(row);
  }
}

function clusterCard(c) {  // the side list: name, size and spread in words, one line of what it is
  const txt = document.createElement("div");
  const nm = document.createElement("div"); nm.className = "name"; nm.textContent = clusterName(c.id);
  const mt = document.createElement("div"); mt.className = "meta";
  const out = c.members.filter((i) => EXCLUDED.has(i)).length;
  const lora = Boolean(DATA.live);  // how tight a group is and its time strip: the live app's cards
  mt.textContent = `${c.size} ${t(DATA.families ? "folderUnit" : "size")}` + (out ? t("excludedOf").replace("{n}", out) : "") +
    (lora && c.cohesion !== undefined && c.cohesion >= SPREAD_TIGHT ? ` · ${t(spreadWord(c.cohesion))}` : "");
  if (lora && c.cohesion !== undefined) mt.title = t("cohesionTip");
  txt.append(nm, mt);
  // which artists, or else the look (one group per folder: its name says the artist already)
  const what = (DATA.method === "folders" ? "" : folderMix(c.members)) || lookLine(c.members);
  if (what) { const w = document.createElement("div"); w.className = "meta"; w.textContent = what; txt.append(w); }
  // old to new, for one artist's periods (across several artists' folders the order says little)
  const strip = lora && folderNames().length < 2 ? timeStrip(c.members, colorOf(c.id)) : null;
  if (strip) txt.append(strip);
  return txt;
}

function clusterText(c, pane) {  // the group view: size, tags, folders, closest groups, look, time strip
  const txt = document.createElement("div");
  const nm = document.createElement("div"); nm.className = "name"; nm.textContent = clusterName(c.id);
  const mt = document.createElement("div"); mt.className = "meta";
  const out = c.members.filter((i) => EXCLUDED.has(i)).length;
  mt.textContent = `${c.size} ${t(DATA.families ? "folderUnit" : "size")}` + (out ? t("excludedOf").replace("{n}", out) : "") +
    (c.cohesion !== undefined ? ` · ${t("cohesion")} ${c.cohesion.toFixed(3)}` : "") +
    (c.cohesion !== undefined && !DATA.families ? paren(t(spreadWord(c.cohesion))) : "");  // a family's points are folder means: another scale
  if (c.cohesion !== undefined && !DATA.families) mt.title = t("cohesionTip");
  txt.append(nm, mt);
  if (c.tags && c.tags.length) {
    const tg = document.createElement("div"); tg.className = "meta tags"; tg.textContent = c.tags.join(", ");
    txt.append(tg);
  }
  const mix = folderMix(c.members);
  if (mix) {
    const fm = document.createElement("div"); fm.className = "meta"; fm.textContent = mix; txt.append(fm);
  }
  const twins = sameFolderGroups(c);
  if (twins.length) {  // one sub-folder (e.g. one artist) split over several groups: say why
    const tw = document.createElement("div"); tw.className = "meta";
    tw.textContent = t("sameFolder").replace("{g}", twins.map(clusterName).join(lang === "zh" ? "、" : ", ")).replace("{f}", mainFolder(c.members));
    txt.append(tw);
  }
  const copies = copiesIn(c.members);
  if (copies >= 2) {  // a group that is mostly versions of a few pictures is not a style
    const dp = document.createElement("div"); dp.className = "meta"; dp.textContent = t("groupCopies").replace("{n}", copies);
    txt.append(dp);
  }
  if (c.near && c.near.length) txt.append(nearLinks(c, pane));
  const look = lookWords(c.members);
  if (look) {
    const lk = document.createElement("div"); lk.className = "meta look"; lk.textContent = look;
    lk.title = t("lookTitle"); txt.append(lk);
  }
  const strip = timeStrip(c.members, colorOf(c.id));
  if (strip) txt.append(strip);
  return txt;
}

// one artist's whole works spread 0.15-0.29 (10th-90th percentile, median 0.20) on 393 Danbooru
// artists (docs/BENCHMARKS.md, "How spread is one artist?")
const SPREAD_TIGHT = 0.15, SPREAD_LOOSE = 0.29;  // most tool-made groups are tight: said only when not
function spreadWord(s) { return s < SPREAD_TIGHT ? "spreadTight" : s > SPREAD_LOOSE ? "spreadLoose" : "spreadArtist"; }
function paren(text) { return lang === "zh" ? `（${text}）` : ` (${text})`; }  // hoisted: used while the page builds

function outlierRank(o) {  // share of this folder's images less of an outlier than o (the scale depends on the folder)
  const sorted = outlierRank.sorted || (outlierRank.sorted = PTS.map((p) => p.o).sort((a, b) => a - b));
  let lo = 0, hi = sorted.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (sorted[mid] < o) lo = mid + 1; else hi = mid; }
  return Math.round((100 * lo) / Math.max(1, sorted.length));
}

function copiesIn(members) {  // images of the group that have a near-duplicate inside the group
  const inGroup = new Set(members);
  let n = 0;
  for (const g of DATA.duplicates || []) {
    const here = g.filter((i) => inGroup.has(i)).length;
    if (here >= 2) n += here;
  }
  return n;
}

const folderOf = (i) => {  // an artist map's points are named after their folders
  const n = PTS[i].n; const k = n.indexOf("/");
  return DATA.families ? n : k < 0 ? "." : n.slice(0, k);
};
const SEVERAL_FOLDERS = new Set(PTS.map((_, i) => folderOf(i))).size > 1;
const LIBRARY_FOLDERS = 20;  // from 20 artists "by artist" follows them better (README, BENCHMARKS)

function manyGroupsHint() {  // a library of many artists, or one varied artist
  const byArtist = DATA.live && DATA.live.settings && DATA.live.settings.method === "artists";
  const folders = folderCount();
  return folders >= LIBRARY_FOLDERS && !byArtist ? t("manyGroupsLibrary").replace("{n}", folders) : t("manyGroups");
}

function folderCount() { return new Set(PTS.map((_, i) => folderOf(i)).filter((f) => f !== ".")).size; }

const MAIN_SHARE = 0.8;  // a group "comes from" a sub-folder when this share of it does

function mainFolder(members) {  // the sub-folder most of a group comes from, or null
  if (!SEVERAL_FOLDERS || !members.length) return null;
  const counts = new Map();
  members.forEach((i) => { const f = folderOf(i); counts.set(f, (counts.get(f) || 0) + 1); });
  const [folder, n] = [...counts].sort((a, b) => b[1] - a[1])[0];
  return n / members.length >= MAIN_SHARE ? folder : null;
}

let MAIN_FOLDERS = null;  // group id -> its main sub-folder; one pass per rebuild of the list

function mainFolders() {
  if (MAIN_FOLDERS) return MAIN_FOLDERS;
  const members = new Map();  // DATA.clusters carry no member lists: gather them from the points
  PTS.forEach((p, i) => { if (p.c >= 0) (members.get(p.c) || members.set(p.c, []).get(p.c)).push(i); });
  MAIN_FOLDERS = new Map([...members].map(([id, m]) => [id, mainFolder(m)]));
  return MAIN_FOLDERS;
}

function sameFolderGroups(c) {  // the other groups that come from the same sub-folder as c
  if (c.id < 0 || !SEVERAL_FOLDERS) return [];
  const own = mainFolders().get(c.id);
  if (own === null || own === undefined || own === ".") return [];  // "." = images in the root
  return [...mainFolders()].filter(([id, f]) => id !== c.id && f === own).map(([id]) => id).sort((a, b) => a - b);
}

function folderMix(members) {  // which sub-folders a group's images come from, most first
  if (!SEVERAL_FOLDERS) return "";
  const counts = new Map();
  members.forEach((i) => counts.set(folderOf(i), (counts.get(folderOf(i)) || 0) + 1));
  const top = [...counts].sort((a, b) => b[1] - a[1]);
  const shown = top.slice(0, 3).map(([f, n]) => (DATA.families ? f : `${f} ${n}`));  // an artist map: one point each
  return `${t("fromFolders")}${shown.join(" · ")}${top.length > 3 ? " …" : ""}`;
}

function nearLinks(c, pane, numbers = true) {  // the closest groups, each a link that opens it
  const nr = document.createElement("div"); nr.className = "meta near";
  nr.append(`${t("nearGroups")} `);
  c.near.forEach(([id, d], k) => {
    const a = document.createElement("a"); a.href = "#"; a.textContent = numbers ? `${clusterName(id)} (${d.toFixed(2)})` : clusterName(id);
    a.title = t("nearTip");
    a.addEventListener("click", (e) => {
      e.preventDefault(); e.stopPropagation();
      const target = [...pane.querySelectorAll(".cl")].find((r) => r.dataset.id === String(id));
      if (target) { target.scrollIntoView({ block: "nearest" }); target.click(); }
    });
    if (k) nr.append(" · ");
    nr.append(a);
  });
  return nr;
}

function groupBar(c) {  // live app only: the edits for a group, or placing the unassigned ones
  if (!DATA.live || (c.id < 0 && !DATA.clusters.length)) return null;
  const bar = document.createElement("div"); bar.style.cssText = "grid-column:1/-1;margin-bottom:4px";
  const button = (label, onClick) => {
    const b = document.createElement("button"); b.textContent = label; b.style.marginLeft = "6px";
    b.addEventListener("click", (e) => { e.stopPropagation(); onClick(); });
    return b;
  };
  if (c.id < 0) {
    const place = button(t("placeUnassigned"), placeUnassigned);
    place.style.marginLeft = ""; place.title = t("placeUnassignedTip"); place.dataset.role = "place";
    bar.append(place);
    return bar;
  }
  const confirmMerge = document.createElement("span"); confirmMerge.dataset.role = "merge-ok";  // its own button
  const closest = (c.near || []).map(([id]) => id);  // the likeliest picks first
  const merge = groupSelect(t("mergeInto"), c.id, false, (into) => {
    const go = button(t("mergeConfirm").replace("{a}", clusterName(c.id)).replace("{b}", clusterName(into)),
      () => editPost("api/merge", { from: c.id, into }));
    go.classList.add("on"); confirmMerge.replaceChildren(go);
  }, closest);
  merge.dataset.role = "merge";
  bar.append(merge, confirmMerge);
  if (DATA.clusters.length >= 2) {
    const compare = groupSelect(t("compareWith"), c.id, false, (other) => showCompare(c.id, other), closest);
    compare.dataset.role = "compare"; bar.append(compare);
  }
  const nameBox = document.createElement("input"); nameBox.name = "groupName"; nameBox.setAttribute("aria-label", t("nameGroup"));
  nameBox.placeholder = t("nameGroup"); nameBox.title = t("nameGroupTip"); nameBox.value = (DATA.live.names || {})[String(c.id)] || "";
  nameBox.dataset.role = "name";
  const look = lookWords(c.members);  // a name to start from when there is none yet
  if (!nameBox.value && look && look !== t("lookAverage")) nameBox.placeholder = t("nameGroupHint").replace("{w}", look);
  nameBox.style.cssText = "margin-left:6px;width:10rem;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:999px;padding:.35em .6em;font:inherit;font-size:.95rem";
  nameBox.addEventListener("click", (e) => e.stopPropagation());
  nameBox.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter" && !e.isComposing && e.keyCode !== 229) editPost("api/rename", { group: c.id, name: nameBox.value });
  });
  const like = button(t("moreLike"), () => showSimilar(c.id)); like.dataset.role = "more-like";
  bar.append(nameBox, like);
  if (c.size >= 2) {
    const split = button(t("splitGroup"), () => editPost("api/split", { group: c.id }));
    split.dataset.role = "split"; bar.append(split);
  }
  return bar;
}

const CHECK_KEYS = ["smaller_than_min_side", "soft_or_enlarged", "low_jpeg_quality",
  "greyscale_in_colour_set", "greyscale_untagged", "greyscale_tag_on_colour", "extreme_aspect_ratio",
  "watermark_or_signature", "tag_spelling_mixed", "no_caption", "empty_caption", "animated", "exif_rotated", "truncated",
  "unreadable"];
let CHECK = null;  // the last dataset check (live app only)

function checkSection() {
  const box = document.createElement("div");
  const h = document.createElement("h3"); h.textContent = t("checkTitle");
  const side = document.createElement("select"); side.name = "minSide"; side.setAttribute("aria-label", t("checkTitle"));
  [512, 768, 1024].forEach((n) => {
    const o = document.createElement("option"); o.value = String(n); o.textContent = t("minSide").replace("{n}", n); side.append(o);
  });
  if (CHECK) side.value = String(CHECK.min_side);
  const run = document.createElement("button"); run.textContent = t("checkRun"); run.style.marginLeft = "6px";
  run.addEventListener("click", () => { run.disabled = true; runCheck(parseInt(side.value, 10)); });
  const what = document.createElement("div"); what.className = "kv"; what.textContent = t("checkFor");
  box.append(h, what, side, run);
  if (!CHECK) return box;
  const found = CHECK_KEYS.filter((k) => (CHECK.issues[k] || []).length);
  box.append(checkVerdict(found));
  if (CHECK.consistency) box.append(consistencyLine(CHECK.consistency));
  const details = document.createElement("details"); details.className = "gv-numbers";  // trainer talk, folded
  const label = document.createElement("summary"); label.textContent = t("checkDetails"); details.append(label);
  if (CHECK.buckets && Object.keys(CHECK.buckets).length) details.append(bucketLine(CHECK.buckets));
  if (CHECK.frequent_tags && CHECK.frequent_tags.length) {  // content a style LoRA learns along
    const common = document.createElement("div"); common.className = "kv"; common.title = t("frequentTip");
    const list = CHECK.frequent_tags.map(([tag, share]) => `${tag} ${Math.round(share * 100)}%`).join(lang === "zh" ? "、" : ", ");
    common.textContent = t("frequentLine").replace("{t}", list);
    details.append(common);
  }
  if (details.children.length > 1) box.append(details);
  if (found.length) {  // one line first: how much there is to look at
    const flagged = new Set(found.flatMap((k) => CHECK.issues[k]));
    const sum = document.createElement("div"); sum.className = "kv";
    sum.textContent = t("checkSummary").replace("{k}", found.length).replace("{n}", flagged.size);
    box.append(sum);
  }
  if (!found.length) {
    const ok = document.createElement("div"); ok.className = "kv"; ok.textContent = t("checkClean"); box.append(ok);
  }
  found.forEach((k) => box.append(...issueBlock(k, CHECK.issues[k])));
  return box;
}

// the check's answer in one line: ready, or how many pictures to fix first (problems that blur or
// spoil training), the small things being listed below either way
const CHECK_SERIOUS = ["unreadable", "truncated", "smaller_than_min_side", "soft_or_enlarged", "low_jpeg_quality",
  "exif_rotated", "animated", "watermark_or_signature"];
function checkVerdict(found) {
  const serious = found.filter((k) => CHECK_SERIOUS.includes(k));
  const line = document.createElement("div"); line.className = "kv verdict-line";
  const n = new Set(serious.flatMap((k) => CHECK.issues[k])).size;
  line.textContent = serious.length ? t("checkFixFirst").replace("{n}", n) : t(found.length ? "checkMinorOnly" : "checkReady");
  return line;
}

function consistencyLine(c) {  // how spread the folder's style is, next to single artists
  const line = document.createElement("div");
  line.className = c.verdict === "mixed" ? "kv consist mixed" : "kv consist"; line.title = t("consistTip");
  const key = c.percentile >= 99.5 ? "beyond" : c.verdict.replaceAll(" ", "_");  // past every reference artist
  line.textContent = t("consist_" + key).replace("{p}", Math.round(c.percentile));
  if (c.folders >= 2) line.textContent += " " + t("consistFolders").replace("{n}", c.folders);  // a library
  return line;
}

function bucketLine(buckets) {  // kohya's aspect-ratio buckets
  const entries = Object.entries(buckets);
  const sparse = entries.filter(([, n]) => n < 4).length;
  const line = document.createElement("div"); line.className = "kv"; line.title = t("bucketTip");
  line.textContent = t("bucketLine").replace("{k}", entries.length)
    .replace("{top}", entries.slice(0, 3).map(([b, n]) => `${b.replace("x", "×")} ${n}`).join(" · "))
    + (sparse ? " " + t("bucketSparse").replace("{s}", sparse) : "");
  return line;
}

function issueBlock(k, list) {  // one kind of problem: its count, and the images unless nearly all
  const sub = document.createElement("div"); sub.className = "meta";
  const many = list.length > 0.9 * N;  // e.g. a folder without any captions: say so, no grid
  const tags = k === "tag_spelling_mixed" && CHECK.spelt_two_ways && CHECK.spelt_two_ways.length
    ? (lang === "zh" ? `（${CHECK.spelt_two_ways.join("、")}）` : ` (${CHECK.spelt_two_ways.join(", ")})`) : "";
  sub.textContent = `${t("chk_" + k).replace("{n}", CHECK.min_side).replace("{q}", CHECK.low_jpeg)}${tags}${lang === "zh" ? "：" : ": "}${many ? t("checkAll").replace("{n}", list.length) : list.length}`;
  if (many) {
    const why = T[lang]["checkAllWhy_" + k];
    if (!why) return [sub];
    const hint = document.createElement("div"); hint.className = "kv"; hint.textContent = why;
    return [sub, hint];
  }
  const pick = document.createElement("button"); pick.textContent = t("selectThese");
  pick.style.cssText = "margin:2px 0 4px";
  pick.addEventListener("click", () => { MARKED = new Set(list); showMarks(); });  // then exclude at once
  const g = document.createElement("div"); g.className = "grid"; list.slice(0, 60).forEach((i) => g.append(thumb(i)));
  return [sub, pick, g];
}

async function runCheck(minSide) {
  setStatus(t("checking"));
  try {
    CHECK = await post("api/check", JSON.stringify({ min_side: minSide }), "application/json");
    setStatus(""); markStep("check");  // map_browse.js
  } catch (e) { setStatus(String(e.message || e)); }
  buildOutliers();  // also brings the button back
}

const OUTLIERS_SHARE = 0.1, OUTLIERS_MIN = 5, OUTLIERS_MAX = 60;  // least typical tenth, 5..60

function buildOutliers() {
  const pane = $("pane-outliers"); pane.replaceChildren();
  if (DATA.live) pane.append(checkSection());
  const oh = document.createElement("h3"); oh.textContent = t("outliersTitle");
  const help = document.createElement("div"); help.className = "kv"; help.textContent = t("outlierHelp");
  const g = document.createElement("div"); g.className = "grid";
  const shown = Math.min(OUTLIERS_MAX, Math.max(OUTLIERS_MIN, Math.ceil(N * OUTLIERS_SHARE)));
  [...PTS.keys()].sort((a, b) => PTS[b].o - PTS[a].o).slice(0, shown).forEach((i) => g.append(thumb(i)));
  pane.append(oh, help, g);
  if (DATA.live && EXCLUDED.size) {
    const h = document.createElement("h3"); h.textContent = t("excludedList").replace("{n}", EXCLUDED.size);
    const eg = document.createElement("div"); eg.className = "grid";
    [...EXCLUDED].forEach((i) => eg.append(thumb(i)));
    const more = document.createElement("button"); more.textContent = t("moreLikeThese");
    more.title = t("moreLikeTheseHelp"); more.style.margin = "2px 0 6px";
    more.addEventListener("click", () => showSimilar("excluded"));
    pane.append(h, more, eg);
  }
}

function buildDups() {
  const pane = $("pane-dups"); pane.replaceChildren();
  const groups = DATA.duplicates || [];
  const help = document.createElement("div"); help.className = "kv";
  help.textContent = groups.length ? t(DATA.live ? "dupHelp" : "dupHelpShared") : t("noDups");
  pane.append(help);
  const keep = (DATA.live && DATA.live.dup_keep) || [];  // live app: the copy each export keeps
  groups.forEach((g, n) => {
    const h = document.createElement("h3"); h.textContent = `#${n + 1} · ${g.length}`;
    const grid = document.createElement("div"); grid.className = "grid";
    g.forEach((i) => grid.append(dupTile(i, keep.length ? keep[n] === i : null)));
    pane.append(h, grid);
  });
}

function dupTile(i, kept) {  // a near-duplicate with its file name; kept: true / false / null (unknown)
  const fig = document.createElement("figure"); fig.className = "dup" + (kept ? " kept" : "");
  const cap = document.createElement("figcaption");
  cap.textContent = PTS[i].n.split("/").pop(); cap.title = PTS[i].n;
  fig.append(thumb(i), cap);
  if (kept) {
    const b = document.createElement("span"); b.className = "badge"; b.textContent = t("dupKept"); fig.append(b);
  } else if (kept === false) {
    const b = document.createElement("button"); b.textContent = t("dupKeepThis"); b.title = t("dupKeepTip");
    b.addEventListener("click", () => keepCopy(i));  // map_app.js
    fig.append(b);
  }
  return fig;
}

// How the groups were made, in words: "auto cut 0.43", "3 periods", ...
function methodText() {
  const p = DATA.params || {};
  if (DATA.method === "kmeans") return t("periodsN").replace("{n}", p.n_clusters);
  if (DATA.method === "folders") return t("byFolders");
  if (DATA.method === "timeline") return t("timelineN").replace("{n}", p.n_clusters);
  if (DATA.method === "hdbscan") return "HDBSCAN";
  if (p.n_clusters === 1) return t("oneGroupLabel");
  if (p.n_clusters) return t("forcedN").replace("{n}", p.n_clusters);
  if (p.threshold === undefined) return DATA.method;
  return (p.auto ? t("autoCut") : t("cut")).replace("{t}", Number(p.threshold).toFixed(2));
}

let shownHint = "";  // the start-up hint on the status line, as last drawn
function applyText() {
  document.documentElement.lang = lang === "zh" ? "zh-Hans" : "en";
  $("title").querySelector("h1").textContent = DATA.title;
  $("title").querySelector(".sub").textContent = (DATA.families  // the artist map: artists and families
    ? `${N} ${t("folderUnit")} · ${DATA.clusters.length} ${t("familiesWord")}`
    : `${N} ${t("images")} · ${DATA.clusters.length} ${t("clusters").toLowerCase()} · ${methodText()}`) +
    (DATA.params && DATA.params.edited ? ` · ${t("edited")}` : "") +
    (EXCLUDED.size ? ` · ${t("excludedN").replace("{n}", EXCLUDED.size)}` : "");
  $("find").placeholder = t(DATA.live ? "findLive" : "find");
  $("home").textContent = t("home"); $("names").textContent = t("names");
  $("names").title = t("tipNames"); homeShown();
  if (!recordingNow) $("rec").textContent = t("rec");
  $("rec").title = t("tipRec");
  shellText();  // map_shell.js: the layout switch, the View menu, the desktop button
  $("helpBtn").title = t("keys");
  if (!$("help").hidden) showHelp(true);
  const tab = (name) => document.querySelector(`.tabs button[data-pane="${name}"]`);
  tab("clusters").textContent = t("clusters"); tab("selected").textContent = t("selected");
  tab("lora").textContent = t(DATA.live ? "loraTab" : "loraTabShared");
  const sub = (name) => document.querySelector(`.subtabs button[data-sub="${name}"]`);
  sub("outliers").textContent = t(DATA.live ? "checkTab" : "outliers");
  sub("dups").textContent = `${t("dups")}${(DATA.duplicates || []).length ? " " + DATA.duplicates.length : ""}`;
  document.querySelector("#pane-lora .lora-intro").textContent = t("loraIntro");
  document.querySelector("footer").textContent = t("foot");
  const details = $("pane-selected");  // results shown there (search, compare) stay
  if (selected === null && (!details.childElementCount || details.firstElementChild.className === "empty")) {
    const e = document.createElement("div"); e.className = "empty"; e.textContent = t("pick");
    tab("selected").hidden = !details.classList.contains("on");  // nothing picked yet: no empty tab
    details.replaceChildren(e);
  }
  buildClusters(); buildOutliers(); buildDups(); liveText(); if (DATA.live) buildTaste();
  refreshGroupView();  // map_group.js: an open group view, rebuilt where it was
  const many = DATA.clusters.length > Math.max(12, N / 8);  // e.g. one varied artist cut into dozens
  const chosen = DATA.live && DATA.live.settings && DATA.live.settings.k === 1;  // "one group" on purpose
  // a hint already showing is redrawn in the new language; other messages are left alone
  const free = !$("status").textContent || $("status").textContent === shownHint;
  let hint = "";
  if (DATA.live && DATA.clusters.length <= 1 && N > 10 && !chosen) hint = t("oneGroup");
  else if (DATA.live && many && !DATA.live.restored && !(DATA.params || {}).edited) hint = manyGroupsHint();
  else if (DATA.live && free) hint = t(DATA.live.restored ? "restored" : "firstHint");
  if (hint) { shownHint = hint; setStatus(hint); }
  setupAxes(); if (layoutMode === "measures") drawAxes();
  drawNames();
}


let tagTimer = null;
let filterMessage = "";  // the "N images match" line, cleared with the filter
$("find").addEventListener("input", (e) => {
  const text = e.target.value.trim();
  clearTimeout(tagTimer);
  folderFilter = null; tagOnly = null;
  if (DATA.live && text.startsWith("#")) {  // a caption tag: the server reads the captions
    filter = "";
    if (text.length < 2) { searchHits = null; recolor(); return; }
    tagTimer = setTimeout(() => findTag(text.slice(1)), 300);
    return;
  }
  filter = text; searchHits = null;
  if (text && selected !== null) { selected = null; showPane("clusters"); }  // else it hides the matches
  if (text) focusCluster = null;
  const lit = recolor();
  if (text) {
    filterMessage = t("filterHits").replace("{n}", lit);
    setStatus(filterMessage);
  } else if (filterMessage && $("status").textContent === filterMessage) {
    setStatus(""); filterMessage = "";
  }
});

async function findTag(tag) {
  try {
    const r = await post("api/tagged", JSON.stringify({ tag }), "application/json");
    if ($("find").value.trim() !== "#" + tag) return;  // the box changed while the captions were read
    selected = null; searchHits = new Set(r.hits); recolor(); tagOnly = { tag, hits: r.hits };
    setStatus(t("tagHits").replace("{n}", r.hits.length).replace("{t}", tag));
  } catch (e) { setStatus(String(e.message || e)); }
}
$("mode").addEventListener("click", () => {
  mode = mode === "thumbs" ? "dots" : "thumbs";
  pages.forEach((pg) => (pg.mat.uniforms.uMode.value = mode === "dots" ? 1 : 0));
  applyText();
});
const SPIN_KEY = "styleAtlasSpin";  // per tab: an edit reloads the page
function setSpin(on) {
  controls.autoRotate = on; $("spin").classList.toggle("on", on);
  try { sessionStorage.setItem(SPIN_KEY, on ? "1" : "0"); } catch (e) { /* storage off */ }
}
let spinPref = null;
try { spinPref = sessionStorage.getItem(SPIN_KEY); } catch (e) { /* storage off */ }
setSpin(spinPref === "1");  // still by default: a turning map moves pictures under the cursor
$("spin").addEventListener("click", () => setSpin(!controls.autoRotate));
$("savePng").addEventListener("click", snapNow);
canvas.addEventListener("pointerdown", () => { if (controls.autoRotate) setSpin(false); });
// "Whole map": back from a zoom, a drag, a group or a picture, with the filters cleared. Greyed
// out when the map already shows all of it (pressing it then changed nothing and read as broken)
let AWAY = false;  // the camera left the whole-map view
function markHome(away) { AWAY = away; homeShown(); }
function homeShown() {
  const filtered = focusCluster !== null || selected !== null || searchHits !== null || filter !== ""
    || folderFilter !== null || tagOnly !== null;
  const on = AWAY || filtered;
  $("home").disabled = !on; $("home").title = t(on ? "tipHome" : "tipHomeHere");
}
function goHome() {
  focusCluster = null; selected = null; searchHits = null; filter = ""; folderFilter = null; tagOnly = null;
  $("find").value = ""; recolor();
  flyHome();  // map_layout.js
  document.querySelectorAll(".cl").forEach((r) => r.classList.remove("on"));
}
$("home").addEventListener("click", goHome);
controls.addEventListener("start", () => markHome(true));  // a drag or the wheel
$("lang").addEventListener("click", () => { lang = lang === "zh" ? "en" : "zh"; store(LANG_KEY, lang); applyText(); });

// The keyboard and mouse shortcuts, toggled by "?" (built with textContent, like the rest).
function showHelp(on) {
  const box = $("help");
  box.hidden = !on;
  if (!on) return;
  const rows = [["leftDrag", "keyPan"], ["rightDrag", layoutMode === "groups" ? "keyPanWall" : "keyRotate"], ["wheel", "keyZoom"],
    ["← →", "keyWalk"], ...(layoutMode === "groups" ? [["↑ ↓", "keyWalkRow"]] : []),
    ["dblPic", "keyViewer"], ["spaceKey", "keyViewer"], ["dblEmpty", "keyZoomHere"], ["sizeKeys", "keySize"], ["uiKeys", "keyUi"], ["Esc", "keyHome"], ["P", "keySnap"],
    ...(DATA.live ? [["shiftKeys", "keyMark"], ["L / D", "keyVote"], ["X", "keyExclude"], ["Ctrl + Z", "keyUndo"]] : [])];
  const named = ["leftDrag", "rightDrag", "wheel", "dblPic", "spaceKey", "dblEmpty", "sizeKeys", "uiKeys", "shiftKeys"];
  const close = document.createElement("button"); close.className = "close"; close.textContent = "✕";
  close.title = t("close"); close.setAttribute("aria-label", t("close")); close.addEventListener("click", () => showHelp(false));
  const start = document.createElement("h4"); start.textContent = t("quickStart");
  const steps = document.createElement("ol"); steps.className = "quick";
  const last = DATA.live ? ["quick4"] : [];
  ["quick1", "quickWalk", "quick2", "quick3", ...last].forEach((key) => {
    const li = document.createElement("li"); li.textContent = t(key); steps.append(li);
  });
  const about = ["helpWhat1", "helpWhat2", "helpWhat3", ...(DATA.live ? ["helpNotes"] : [])].map((key) => {
    const p = document.createElement("p"); p.className = "about"; p.textContent = t(key); return p;
  });
  const keys = document.createElement("h4"); keys.textContent = t("keysTitle");
  box.replaceChildren(close, start, steps, ...about, keys, ...rows.map(([key, what]) => {
    const line = document.createElement("div");
    const b = document.createElement("b"); b.textContent = named.includes(key) ? t(key) : key;
    line.append(b, document.createTextNode(t(what)));
    return line;
  }));
}
$("helpBtn").addEventListener("click", () => showHelp($("help").hidden));
document.addEventListener("pointerdown", (e) => {  // a click elsewhere closes the help
  if (!$("help").hidden && !$("help").contains(e.target) && e.target !== $("helpBtn")) showHelp(false);
});
$("theme").addEventListener("click", () => {
  const root = document.documentElement;
  root.dataset.theme = root.dataset.theme === "light" ? "dark" : "light";
  store(THEME_KEY, root.dataset.theme);
  setBackground();
});
addEventListener("keydown", (e) => {
  if (viewerKey(e)) { e.preventDefault(); return; }  // map_viewer.js: the big picture takes the keys first
  if (e.key === "Escape" && !$("help").hidden) { showHelp(false); return; }  // also from a text box
  if (e.key === "Escape" && !$("exportPanel").hidden) { closeExport(); return; }  // map_export.js
  if (["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
  if (groupViewKey(e)) { e.preventDefault(); return; }  // map_group.js: arrows step, Esc closes
  if (walkKeyDown(e)) { e.preventDefault(); return; }  // map_walk.js: arrows, Enter, Space, Esc
  if (e.repeat) return;  // holding a key must not vote on images never looked at
  if (DATA.live && DATA.live.can_undo && (e.ctrlKey || e.metaKey) && !e.altKey && (e.key === "z" || e.key === "Z")) {
    e.preventDefault(); editPost("api/undo", {}); return;
  }
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === "?") showHelp($("help").hidden);
  if (e.key === "Escape") {
    RATING = false; PATH_FROM = null; setStatus(""); showHelp(false);
    if (MARKED.size) { MARKED = new Set(); showMarks(); }
    goHome();
  }
  if (DATA.live && selected !== null && (e.key === "l" || e.key === "L")) castVote(selected, true);
  if (DATA.live && selected !== null && (e.key === "d" || e.key === "D")) castVote(selected, false);
  if (DATA.live && selected !== null && (e.key === "x" || e.key === "X")) toggleExclude(selected);
  if (e.key === "p" || e.key === "P") snapNow();
  if (e.key === "+" || e.key === "=") setSize(pointSize * 1.2);
  if (e.key === "-") setSize(pointSize / 1.2);
});
canvas.addEventListener("wheel", (e) => { if (e.altKey) { e.preventDefault(); setSize(pointSize * (e.deltaY < 0 ? 1.1 : 1 / 1.1)); } }, { passive: false });
function setSize(s) { pointSize = Math.min(0.6, Math.max(0.02, s)); pages.forEach((pg) => (pg.mat.uniforms.uSize.value = pointSize)); }

// P, or the button in Advanced: draw a frame now and save it, so it works in a background tab too
// (no animation frames run there); toBlob reads the canvas right after the render
function snapNow() { lastDeclutter = 0; declutterNames(performance.now()); updateSharp(performance.now()); renderer.render(scene, camera); saveSnapshot(); }
function saveSnapshot() {  // right after render(), while the frame is still in the canvas
  canvas.toBlob((blob) => {
    if (!blob) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${(DATA.title || document.title || "style-map").replace(/[\\/:*?"<>|]+/g, "_")}.png`;
    a.click();
    setStatus(t("downloaded").replace("{f}", a.download));
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }, "image/png");
}

const clock = new THREE.Clock();
function animate() {
  requestAnimationFrame(animate);
  stepMorph();
  if (flyTo) {
    flyTo.k = Math.min(1, flyTo.k + 0.06);
    controls.target.lerp(flyTo.target, flyTo.k);
    camera.position.lerp(flyTo.cam, flyTo.k);
    if (flyTo.k >= 1) flyTo = null;
  }
  controls.update(Math.min(clock.getDelta(), 0.1));  // real time: same turn speed at any frame rate
  if (viewGroup !== null) return;  // the group view covers the map: no need to draw it
  declutterNames(performance.now());
  updateSharp(performance.now());  // map_sharp.js: close-up pictures from sharper files
  placeWalkMarker();  // map_walk.js
  renderer.render(scene, camera);
}
