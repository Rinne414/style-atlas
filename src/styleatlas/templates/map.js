import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const DATA = JSON.parse(document.getElementById("atlas-data").textContent);
const PTS = DATA.points;
const N = PTS.length;
const T = {
  en: { images: "images", clusters: "Styles", selected: "Selected", outliers: "Outliers",
    find: "filter by file name", thumbs: "Thumbnails", dots: "Dots", spin: "Rotate", home: "Reset",
    unassigned: "Unassigned", style: "Style", size: "images", cohesion: "spread",
    pick: "Click an image in the map to see its closest styles.", nearest: "Closest styles",
    members: "Members", cluster: "style", outlierHelp: "Images least like the rest of the set (candidates to drop from a LoRA dataset).",
    loading: "building map…", open: "open file", searchImg: "Search by image…",
    drop: "Drop an image to find its closest styles", regroup: "Regroup", export: "Export folders",
    searching: "embedding the query…", exported: "copied {n} images to {f}", query: "Your image",
    custom: "custom", regrouping: "regrouping…", period: "period (one artist)", dups: "Duplicates",
    dupHelp: "Groups of near-identical pictures (same image, crops, frames of one scene). Keep one per group for LoRA training.",
    noDups: "No near-duplicates found.",
    moveTo: "Move to group…", mergeInto: "Merge this group into…", splitGroup: "Split in two", edited: "edited by hand (Regroup discards edits)",
    exclude: "Exclude from export (X)", included: "Excluded - undo (X)",
    excludedList: "Excluded by you ({n}) - exported to _excluded",
    layoutStyle: "Layout: style similarity", layoutMeasures: "Layout: measures",
    m_map: "(map position)", m_taste: "taste p(like)", m_ref: "distance to reference (originality)",
    m_time: "time", m_outlier: "atypical (outlier)",
    pathFrom: "Style path: start here", pathTo: "Style path: end here",
    pathTitle: "Style path (from the start image to this one)",
    neutral: "Ignore the character axis", neutralBusy: "recomputing…",
    oneGroup: "Everything landed in one group: try the fine or period granularity, then Regroup.",
    nameGroup: "name (Enter)",
    rateNext: "Rate the most useful next image", ratingHint: "Rating mode: press L or D, the next image follows (Esc stops)",
    allRated: "Every image is rated.",
    taste: "Taste", like: "Like (L)", dislike: "Dislike (D)", clearVote: "Clear",
    tasteHelp: "Rate images with Like / Dislike (select one on the map, then press L or D). After {n} of each, a model learns your taste from the style vectors and ranks the unrated images.",
    tasteCount: "liked {a} · disliked {b}", tasteAuc: "cross-validated AUC {x} (0.5 = guessing). Treat it as a rough filter: it separates liked from disliked, not good from better.",
    tasteTop: "Most likely to like (unrated)", tasteBottom: "Least likely (unrated)", fine: "fine", medium: "medium", coarse: "coarse", foot: "Style vectors: CSD ViT-L (Somepalli et al. 2024, CC-BY-4.0). Map layout is for viewing only; groups are computed in the full space." },
  zh: { images: "張圖", clusters: "畫風群", selected: "選取", outliers: "離群",
    find: "以檔名篩選", thumbs: "縮圖", dots: "圓點", spin: "旋轉", home: "重置",
    unassigned: "未歸類", style: "畫風", size: "張", cohesion: "分散度",
    pick: "在地圖上點一張圖，看最接近的畫風。", nearest: "最接近的畫風", members: "成員",
    cluster: "畫風群", outlierHelp: "和整組最不像的圖（訓 LoRA 前可考慮剔除）。",
    loading: "建立地圖中…", open: "開啟檔案", searchImg: "以圖搜尋…",
    drop: "放開圖片，找最接近的畫風", regroup: "重新分群", export: "匯出資料夾",
    searching: "計算查詢圖中…", exported: "已複製 {n} 張到 {f}", query: "你的圖",
    custom: "自訂", regrouping: "重新分群中…", period: "時期（單一畫師）", dups: "重複",
    dupHelp: "幾乎相同的圖（同一張、裁切、同場景連續畫面）。訓 LoRA 時每組留一張即可。",
    noDups: "沒有找到近重複的圖。",
    moveTo: "移到其他群…", mergeInto: "把這群合併到…", splitGroup: "拆成兩群", edited: "已手動調整（重新分群會清除）",
    exclude: "匯出時排除 (X)", included: "已排除，取消 (X)",
    excludedList: "你排除的圖（{n}）：匯出時放到 _excluded",
    layoutStyle: "版面：畫風相似", layoutMeasures: "版面：量化軸",
    m_map: "（地圖位置）", m_taste: "口味分數", m_ref: "離參考集距離（原創度）",
    m_time: "時間", m_outlier: "離群度",
    pathFrom: "畫風漸變：從這張開始", pathTo: "畫風漸變：到這張",
    pathTitle: "畫風漸變（從起點到這張）",
    neutral: "忽略角色軸", neutralBusy: "重新計算中…",
    oneGroup: "所有圖都在同一群：試試把顆粒度改成「細」或「時期」，再按重新分群。",
    nameGroup: "取名（Enter）",
    rateNext: "評下一張最有用的圖", ratingHint: "評分模式：按 L 或 D，自動跳下一張（Esc 結束）",
    allRated: "全部都評過了。",
    taste: "口味", like: "喜歡 (L)", dislike: "不喜歡 (D)", clearVote: "清除",
    tasteHelp: "在地圖上選一張圖，按喜歡或不喜歡（鍵盤 L / D）。兩種各滿 {n} 張後，模型會用畫風向量學你的口味，替還沒評的圖排序。",
    tasteCount: "喜歡 {a} · 不喜歡 {b}", tasteAuc: "交叉驗證 AUC {x}（0.5 = 亂猜）。只適合粗篩：分得出喜歡和不喜歡，分不出好和更好。",
    tasteTop: "最可能喜歡（未評分）", tasteBottom: "最不可能喜歡（未評分）", fine: "細", medium: "中", coarse: "粗", foot: "風格向量：CSD ViT-L（Somepalli 等，2024，CC-BY-4.0）。地圖排版只供瀏覽，分群是在完整向量空間計算。" },
};
let lang = (navigator.language || "en").toLowerCase().startsWith("zh") ? "zh" : "en";
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
camera.position.copy(HOME);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.autoRotate = true;
controls.autoRotateSpeed = 0.6;
const SPREAD = 1.6;
const pos = new Float32Array(N * 3);
PTS.forEach((p, i) => { pos[i*3] = p.p[0]*SPREAD; pos[i*3+1] = p.p[1]*SPREAD; pos[i*3+2] = p.p[2]*SPREAD; });
const basePos = pos.slice();
let morph = null;

function setBackground() {
  scene.background = new THREE.Color(getComputedStyle(document.documentElement).getPropertyValue("--bg").trim());
}
setBackground();

const CELL = N <= 2048 ? 128 : 64;   // atlas pages are 4096 px squares
const PER_ROW = 4096 / CELL;
const PER_PAGE = PER_ROW * PER_ROW;
const pages = [];
const alpha = new Float32Array(N).fill(1);
let mode = N <= 6000 ? "thumbs" : "dots";
let pointSize = Math.min(0.4, Math.max(0.05, 1.6 / Math.cbrt(Math.max(N, 1))));

const VERT = `
  attribute float aAlpha; attribute vec2 aCell; attribute vec3 aColor;
  uniform float uSize; uniform float uScale;
  varying float vAlpha; varying vec2 vCell; varying vec3 vColor;
  void main() {
    vAlpha = aAlpha; vCell = aCell; vColor = aColor;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = uSize * uScale / -mv.z * (0.55 + 0.45 * aAlpha);
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
      return;
    }
    vec4 c = texture2D(uAtlas, (vCell + pc) * uCell);
    if (c.a < 0.08) discard;
    gl_FragColor = vec4(c.rgb * (0.35 + 0.65 * vAlpha), c.a * (0.2 + 0.8 * vAlpha));
  }`;

async function loadImage(src) {
  const img = new Image();
  img.src = src;
  try { await img.decode(); return img; } catch { return null; }
}

async function buildPages() {
  for (let start = 0; start < N; start += PER_PAGE) {
    const count = Math.min(PER_PAGE, N - start);
    const rows = Math.ceil(count / PER_ROW);
    const cv = document.createElement("canvas");
    cv.width = PER_ROW * CELL; cv.height = PER_ROW * CELL;
    const g = cv.getContext("2d");
    const imgs = await Promise.all(PTS.slice(start, start + count).map((p) => p.t ? loadImage(p.t) : null));
    imgs.forEach((img, j) => {
      const x0 = (j % PER_ROW) * CELL, y0 = Math.floor(j / PER_ROW) * CELL;
      const col = colorOf(PTS[start + j].c);
      if (img) {
        const s = (CELL - 8) / Math.max(img.width, img.height);
        const w = img.width * s, h = img.height * s;
        const x = x0 + (CELL - w) / 2, y = y0 + (CELL - h) / 2;
        g.fillStyle = col; g.fillRect(x - 4, y - 4, w + 8, h + 8);
        g.drawImage(img, x, y, w, h);
      } else {
        g.fillStyle = col; g.beginPath(); g.arc(x0 + CELL/2, y0 + CELL/2, CELL/4, 0, 7); g.fill();
      }
    });
    pages.push(makePage(start, count, cv));
    $("loading").textContent = `${t("loading")} ${Math.min(start + count, N)} / ${N}`;
  }
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
  const mat = new THREE.ShaderMaterial({
    vertexShader: VERT, fragmentShader: FRAG, transparent: true, depthWrite: true,
    uniforms: { uAtlas: { value: tex }, uCell: { value: 1 / PER_ROW }, uSize: { value: pointSize },
      uScale: { value: 1 }, uMode: { value: mode === "dots" ? 1 : 0 } },
  });
  const obj = new THREE.Points(geo, mat);
  scene.add(obj);
  return { start, count, obj, mat, geo };
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
  const scale = r.height * renderer.getPixelRatio() * 0.9;
  for (const pg of pages) pg.mat.uniforms.uScale.value = scale;
}
addEventListener("resize", resize);

/* ---------- interaction ---------- */
let focusCluster = null, selected = null, filter = "", searchHits = null;
let flyTo = null;

function recolor() {
  const q = filter.toLowerCase();
  for (let i = 0; i < N; i++) {
    let on = true;
    if (focusCluster !== null) on = PTS[i].c === focusCluster;
    if (q) on = on && PTS[i].n.toLowerCase().includes(q);
    if (selected !== null) on = i === selected || PTS[selected].k.includes(i);
    else if (searchHits) on = searchHits.has(i);
    alpha[i] = on ? 1 : 0.12;
  }
  pushAlpha();
}

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
  controls.autoRotate = false; $("spin").classList.remove("on");
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
    const reach = Math.max(radius, pointSize * r.height * 0.45 / depth);
    if (d < reach && depth + d * 0.002 < bestD) { bestD = depth + d * 0.002; best = i; }
  }
  return best;
}

let downAt = null;
canvas.addEventListener("pointerdown", (e) => { downAt = [e.clientX, e.clientY]; });
canvas.addEventListener("pointerup", (e) => {
  if (!downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 5) return;
  const i = pick(e);
  if (i >= 0) select(i); else { selected = null; recolor(); }
});
canvas.addEventListener("pointermove", (e) => {
  const tip = $("tip");
  if (e.buttons) { tip.style.display = "none"; return; }
  const i = pick(e);
  if (i < 0) { tip.style.display = "none"; canvas.style.cursor = "grab"; return; }
  canvas.style.cursor = "pointer";
  tip.querySelector("img").src = PTS[i].t;
  tip.querySelector(".cap").textContent = `${PTS[i].n} · ${clusterName(PTS[i].c)}`;
  const r = canvas.getBoundingClientRect();
  tip.style.display = "block";
  tip.style.left = Math.min(e.clientX - r.left + 14, r.width - 250) + "px";
  tip.style.top = Math.min(e.clientY - r.top + 14, r.height - 290) + "px";
});
canvas.addEventListener("pointerleave", () => { $("tip").style.display = "none"; });

const TIMES = PTS.map((p) => p.ts).filter((v) => v !== null && v !== undefined);
const TMIN = TIMES.reduce((a, b) => Math.min(a, b), Infinity);
const TMAX = TIMES.reduce((a, b) => Math.max(a, b), -Infinity);
const HAS_TIME = DATA.time_source && DATA.time_source !== "none" && TIMES.length > 1 && TMAX > TMIN;

function fmtTime(v) {
  if (DATA.time_source === "mtime") return new Date(v * 1000).toISOString().slice(0, 7);
  return "#" + Math.round(v).toLocaleString();
}

function timeStrip(members, color) {
  const ts = members.map((i) => PTS[i].ts).filter((v) => v !== null && v !== undefined);
  if (!HAS_TIME || !ts.length) return null;
  const BINS = 30, W = 120, H = 16;
  const bins = new Array(BINS).fill(0);
  ts.forEach((v) => bins[Math.min(BINS - 1, Math.floor((v - TMIN) / (TMAX - TMIN) * BINS))]++);
  const cv = document.createElement("canvas"); cv.width = W; cv.height = H;
  const g = cv.getContext("2d"); const top = Math.max(...bins);
  g.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--line"); g.fillRect(0, H - 1, W, 1);
  g.fillStyle = color;
  bins.forEach((b, i) => { if (b) { const h = Math.max(2, b / top * (H - 2)); g.fillRect(i * (W / BINS), H - 1 - h, W / BINS - 1, h); } });
  const wrap = document.createElement("div"); wrap.className = "when";
  const label = document.createElement("span");
  label.textContent = `${fmtTime(Math.min(...ts))} – ${fmtTime(Math.max(...ts))}`;
  wrap.append(cv, label);
  return wrap;
}

function clusterName(c) {
  if (c < 0) return t("unassigned");
  const named = DATA.live && DATA.live.names && DATA.live.names[String(c)];
  return named ? `${t("style")} ${c + 1} · ${named}` : `${t("style")} ${c + 1}`;
}

function thumb(i, onClick) {
  const img = document.createElement("img");
  img.src = PTS[i].t; img.alt = PTS[i].n; img.title = PTS[i].n; img.loading = "lazy";
  img.addEventListener("click", onClick || (() => select(i)));
  return img;
}

function select(i) {
  selected = i; searchHits = null; recolor();
  focusOn([i, ...PTS[i].k.slice(0, 4)]);
  const pane = $("pane-selected");
  pane.replaceChildren();
  const big = document.createElement("img");
  big.className = "big"; big.src = PTS[i].f; big.alt = PTS[i].n;
  big.onerror = () => { big.onerror = null; big.src = PTS[i].t; };
  pane.append(big);
  const kv = document.createElement("div"); kv.className = "kv";
  const b = document.createElement("b"); b.textContent = PTS[i].n;
  kv.append(b, document.createElement("br"),
    document.createTextNode(`${clusterName(PTS[i].c)} · outlier ${PTS[i].o.toFixed(3)} · ` +
      (HAS_TIME && PTS[i].ts !== null ? `${fmtTime(PTS[i].ts)} · ` : "") +
      (DATA.reference && PTS[i].r !== null ? `${t("m_ref")} ${PTS[i].r.toFixed(3)} (${PTS[i].rn}) · ` : "")));
  const a = document.createElement("a"); a.href = PTS[i].f; a.target = "_blank"; a.rel = "noopener";
  a.textContent = t("open"); a.style.color = "var(--accent)"; kv.append(a);
  pane.append(kv);
  if (DATA.live) pane.append(voteButtons(i));
  const h = document.createElement("h3"); h.textContent = t("nearest"); pane.append(h);
  const g = document.createElement("div"); g.className = "grid";
  PTS[i].k.forEach((j) => g.append(thumb(j)));
  pane.append(g);
  showPane("selected");
}

function showPane(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.pane === name));
  document.querySelectorAll(".pane").forEach((p) => p.classList.toggle("on", p.id === "pane-" + name));
}
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showPane(b.dataset.pane)));

function buildClusters() {
  const pane = $("pane-clusters");
  pane.replaceChildren();
  const groups = [...DATA.clusters.map((c) => ({ ...c, members: [] }))];
  const un = { id: -1, size: 0, medoid: -1, members: [] };
  PTS.forEach((p, i) => (p.c >= 0 ? groups[p.c].members : un.members).push(i));
  un.size = un.members.length; if (un.size) un.medoid = un.members[0];
  for (const c of [...groups, ...(un.size ? [un] : [])]) {
    const row = document.createElement("div"); row.className = "cl";
    const img = document.createElement("img"); img.src = PTS[c.medoid]?.t || ""; img.alt = "";
    img.style.borderColor = colorOf(c.id);
    const txt = document.createElement("div");
    const nm = document.createElement("div"); nm.className = "name"; nm.textContent = clusterName(c.id);
    const mt = document.createElement("div"); mt.className = "meta";
    mt.textContent = `${c.size} ${t("size")}` + (c.cohesion !== undefined ? ` · ${t("cohesion")} ${c.cohesion.toFixed(3)}` : "");
    txt.append(nm, mt);
    const strip = timeStrip(c.members, colorOf(c.id));
    if (strip) txt.append(strip);
    row.append(img, txt);
    const grid = document.createElement("div"); grid.className = "grid"; grid.style.display = "none";
    grid.style.margin = "4px 0 10px";
    row.addEventListener("click", () => {
      const on = focusCluster !== c.id;
      focusCluster = on ? c.id : null; selected = null; recolor();
      pane.querySelectorAll(".cl").forEach((r) => r.classList.remove("on"));
      pane.querySelectorAll(".grid").forEach((g) => (g.style.display = "none"));
      if (on) {
        row.classList.add("on"); grid.style.display = "grid";
        if (!grid.childElementCount) {
          if (DATA.live && c.id >= 0) {
            const bar = document.createElement("div"); bar.style.cssText = "grid-column:1/-1;margin-bottom:4px";
            bar.append(groupSelect(t("mergeInto"), c.id, false, (into) => editPost("api/merge", { from: c.id, into })));
            const nameBox = document.createElement("input");
            nameBox.placeholder = t("nameGroup"); nameBox.value = (DATA.live.names || {})[String(c.id)] || "";
            nameBox.style.cssText = "margin-left:6px;width:120px;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:999px;padding:5px 8px;font:inherit;font-size:12px";
            nameBox.addEventListener("click", (e) => e.stopPropagation());
            nameBox.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter") editPost("api/rename", { group: c.id, name: nameBox.value }); });
            bar.append(nameBox);
            if (c.size >= 2) {
              const sp = document.createElement("button"); sp.textContent = t("splitGroup"); sp.style.marginLeft = "6px";
              sp.addEventListener("click", (e) => { e.stopPropagation(); editPost("api/split", { group: c.id }); });
              bar.append(sp);
            }
            grid.append(bar);
          }
          c.members.slice(0, 120).forEach((j) => grid.append(thumb(j)));
        }
        focusOn(c.members);
      }
    });
    pane.append(row, grid);
  }
}

function buildOutliers() {
  const pane = $("pane-outliers"); pane.replaceChildren();
  const help = document.createElement("div"); help.className = "kv"; help.textContent = t("outlierHelp");
  const g = document.createElement("div"); g.className = "grid";
  [...PTS.keys()].sort((a, b) => PTS[b].o - PTS[a].o).slice(0, 60).forEach((i) => g.append(thumb(i)));
  pane.append(help, g);
  if (DATA.live && EXCLUDED.size) {
    const h = document.createElement("h3"); h.textContent = t("excludedList").replace("{n}", EXCLUDED.size);
    const eg = document.createElement("div"); eg.className = "grid";
    [...EXCLUDED].forEach((i) => eg.append(thumb(i)));
    pane.append(h, eg);
  }
}

function buildDups() {
  const pane = $("pane-dups"); pane.replaceChildren();
  const groups = DATA.duplicates || [];
  const help = document.createElement("div"); help.className = "kv";
  help.textContent = groups.length ? t("dupHelp") : t("noDups");
  pane.append(help);
  groups.forEach((g, n) => {
    const h = document.createElement("h3"); h.textContent = `#${n + 1} · ${g.length}`;
    const grid = document.createElement("div"); grid.className = "grid";
    g.forEach((i) => grid.append(thumb(i)));
    pane.append(h, grid);
  });
}

function applyText() {
  document.documentElement.lang = lang === "zh" ? "zh-Hant" : "en";
  $("title").querySelector("h1").textContent = DATA.title;
  $("title").querySelector(".sub").textContent =
    `${N} ${t("images")} · ${DATA.clusters.length} ${t("clusters").toLowerCase()} · ${DATA.method} · ${DATA.projection}` +
    (DATA.params && DATA.params.edited ? ` · ${t("edited")}` : "");
  $("find").placeholder = t("find");
  $("mode").textContent = mode === "thumbs" ? t("dots") : t("thumbs");
  $("spin").textContent = t("spin"); $("home").textContent = t("home");
  $("lang").textContent = lang === "zh" ? "EN" : "中";
  const tabs = document.querySelectorAll(".tabs button");
  tabs[0].textContent = t("clusters"); tabs[1].textContent = t("selected"); tabs[2].textContent = t("outliers");
  tabs[3].textContent = `${t("dups")}${(DATA.duplicates || []).length ? " " + DATA.duplicates.length : ""}`;
  document.querySelector("footer").textContent = t("foot");
  if (selected === null) {
    const e = document.createElement("div"); e.className = "empty"; e.textContent = t("pick");
    $("pane-selected").replaceChildren(e);
  }
  buildClusters(); buildOutliers(); buildDups(); liveText(); if (DATA.live) buildTaste();
  if (DATA.live && DATA.clusters.length <= 1 && N > 10) setStatus(t("oneGroup"));
  setupAxes(); if (layoutMode === "measures") drawAxes();
}

function setStatus(msg) { $("status").textContent = msg || ""; }

async function post(url, body, type) {
  const r = await fetch(url, { method: "POST", body,
    headers: { "X-Style-Atlas": "1", "Content-Type": type } });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`);
  return j;
}

async function searchFile(file) {
  if (!file || !file.type.startsWith("image/")) return;
  setStatus(t("searching"));
  try {
    const { hits } = await post("api/search", file, file.type);
    setStatus("");
    showSearch(file, hits);
  } catch (e) { setStatus(String(e.message || e)); }
}

function showSearch(file, hits) {
  selected = null; focusCluster = null; searchHits = new Set(hits.map((h) => h.i)); recolor();
  if (hits.length) focusOn(hits.slice(0, 8).map((h) => h.i));
  const pane = $("pane-selected"); pane.replaceChildren();
  const h = document.createElement("h3"); h.textContent = t("query");
  const q = document.createElement("img"); q.className = "query"; q.alt = file.name;
  q.src = URL.createObjectURL(file);
  const h2 = document.createElement("h3"); h2.textContent = t("nearest");
  const g = document.createElement("div"); g.className = "grid";
  hits.forEach((x) => { const im = thumb(x.i); im.title = `${PTS[x.i].n} · cos ${x.cos.toFixed(3)}`; g.append(im); });
  pane.append(h, q, h2, g);
  showPane("selected");
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
  const sel = document.createElement("select");
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

function setupLive() {
  $("neutral").checked = (DATA.live.neutralize || 0) > 0;
  $("neutral").addEventListener("change", async (e) => {
    setStatus(t("neutralBusy"));
    try {
      await post("api/neutralize", JSON.stringify({ k: e.target.checked ? 1 : 0 }), "application/json");
      location.reload();
    } catch (err) { setStatus(String(err.message || err)); }
  });
  TASTE = DATA.live.taste;
  EXCLUDED = new Set(DATA.live.excluded || []);
  $("live").style.display = "flex";
  const s = DATA.live.settings;
  $("thr").value = (s.threshold ?? DATA.live.granularity.medium).toFixed(2);
  $("pickBtn").addEventListener("click", () => $("pickFile").click());
  $("pickFile").addEventListener("change", (e) => searchFile(e.target.files[0]));
  $("gran").addEventListener("change", (e) => {
    if (e.target.value in DATA.live.granularity) $("thr").value = DATA.live.granularity[e.target.value].toFixed(2);
  });
  $("thr").addEventListener("input", () => { $("gran").value = "custom"; });
  $("regroup").addEventListener("click", async () => {
    setStatus(t("regrouping"));
    try {
      await post("api/regroup", JSON.stringify({ threshold: parseFloat($("thr").value) }), "application/json");
      location.reload();
    } catch (e) { setStatus(String(e.message || e)); }
  });
  $("export").addEventListener("click", async () => {
    try {
      const r = await post("api/export", JSON.stringify({ mode: "copy" }), "application/json");
      setStatus(t("exported").replace("{n}", r.placed).replace("{f}", r.folder));
    } catch (e) { setStatus(String(e.message || e)); }
  });
  let depth = 0;
  addEventListener("dragenter", (e) => { e.preventDefault(); depth++; document.body.classList.add("dragging"); });
  addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; document.body.classList.remove("dragging"); } });
  addEventListener("dragover", (e) => e.preventDefault());
  addEventListener("drop", (e) => {
    e.preventDefault(); depth = 0; document.body.classList.remove("dragging");
    searchFile(e.dataTransfer.files[0]);
  });
}

function liveText() {
  if (!DATA.live) return;
  $("pickBtn").textContent = t("searchImg"); $("regroup").textContent = t("regroup");
  $("export").textContent = t("export"); $("drop").textContent = t("drop");
  $("neutralWrap").querySelector("span").textContent = t("neutral");
  const cur = $("gran").value;
  $("gran").replaceChildren(...[...Object.keys(DATA.live.granularity), "custom"].map((k) => {
    const o = document.createElement("option"); o.value = k; o.textContent = t(k); return o;
  }));
  const thr = parseFloat($("thr").value);
  const match = Object.entries(DATA.live.granularity).find(([, v]) => Math.abs(v - thr) < 1e-6);
  $("gran").value = cur && cur !== "custom" ? cur : (match ? match[0] : "custom");
}

$("find").addEventListener("input", (e) => { filter = e.target.value.trim(); recolor(); });
$("mode").addEventListener("click", () => {
  mode = mode === "thumbs" ? "dots" : "thumbs";
  pages.forEach((pg) => (pg.mat.uniforms.uMode.value = mode === "dots" ? 1 : 0));
  applyText();
});
$("spin").classList.add("on");
$("spin").addEventListener("click", () => {
  controls.autoRotate = !controls.autoRotate; $("spin").classList.toggle("on", controls.autoRotate);
});
$("home").addEventListener("click", () => {
  focusCluster = null; selected = null; searchHits = null; filter = ""; $("find").value = ""; recolor();
  flyTo = { target: new THREE.Vector3(), cam: HOME.clone(), k: 0 };
  document.querySelectorAll(".cl").forEach((r) => r.classList.remove("on"));
});
$("lang").addEventListener("click", () => { lang = lang === "zh" ? "en" : "zh"; applyText(); });
$("theme").addEventListener("click", () => {
  const root = document.documentElement;
  root.dataset.theme = root.dataset.theme === "light" ? "dark" : "light";
  setBackground();
});
addEventListener("keydown", (e) => {
  if (["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
  if (e.repeat) return;  // holding a key must not vote on images never looked at
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === "Escape") { RATING = false; PATH_FROM = null; setStatus(""); $("home").click(); }
  if (DATA.live && selected !== null && (e.key === "l" || e.key === "L")) castVote(selected, true);
  if (DATA.live && selected !== null && (e.key === "d" || e.key === "D")) castVote(selected, false);
  if (DATA.live && selected !== null && (e.key === "x" || e.key === "X")) toggleExclude(selected);
  if (e.key === "+" || e.key === "=") setSize(pointSize * 1.2);
  if (e.key === "-") setSize(pointSize / 1.2);
});
canvas.addEventListener("wheel", (e) => { if (e.altKey) { e.preventDefault(); setSize(pointSize * (e.deltaY < 0 ? 1.1 : 1 / 1.1)); } }, { passive: false });
function setSize(s) { pointSize = Math.min(0.6, Math.max(0.02, s)); pages.forEach((pg) => (pg.mat.uniforms.uSize.value = pointSize)); }

/* ---------- measure axes ---------- */
let layoutMode = "style";
let axisLines = null;

function measure(key) {
  if (key === "outlier") return PTS.map((p) => p.o);
  if (key === "time") return HAS_TIME ? PTS.map((p) => p.ts) : null;
  if (key === "ref") return DATA.reference ? PTS.map((p) => p.r) : null;
  if (key === "taste") return (typeof TASTE !== "undefined" && TASTE && TASTE.scores) ? TASTE.scores : null;
  return null;
}

function availableMeasures() {
  return ["taste", "ref", "time", "outlier"].filter((k) => measure(k));
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
  if (morph.k >= 1) morph = null;
}

function label(text, at) {
  const cv = document.createElement("canvas"); cv.width = 1024; cv.height = 64;
  const g = cv.getContext("2d"); g.font = "28px system-ui, sans-serif";
  g.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--accent");
  g.fillText(text, 8, 42);
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(cv), depthTest: false }));
  sp.position.copy(at); sp.scale.set(2.4, 0.15, 1);
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
});
["axX", "axY", "axZ"].forEach((id) => $(id).addEventListener("change", applyLayout));

function animate() {
  requestAnimationFrame(animate);
  stepMorph();
  if (flyTo) {
    flyTo.k = Math.min(1, flyTo.k + 0.06);
    controls.target.lerp(flyTo.target, flyTo.k);
    camera.position.lerp(flyTo.cam, flyTo.k);
    if (flyTo.k >= 1) flyTo = null;
  }
  controls.update();
  renderer.render(scene, camera);
}

if (DATA.live) setupLive();
applyText();
await buildPages();
resize();
$("loading").style.display = "none";
animate();
