import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const DATA = JSON.parse(document.getElementById("atlas-data").textContent);
const PTS = DATA.points;
const N = PTS.length;
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
const HOME_MEASURES = new THREE.Vector3(3.0, 2.2, 4.6);  // the whole axis cube, at an angle
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

async function fillPages() {
  let done = 0;
  for (const pg of pages) {
    const g = pg.cv.getContext("2d");
    const imgs = await Promise.all(PTS.slice(pg.start, pg.start + pg.count).map((p) => p.t ? loadImage(p.t) : null));
    imgs.forEach((img, j) => { if (img) drawThumb(g, j, img, colorOf(PTS[pg.start + j].c)); });
    pg.mat.uniforms.uAtlas.value.needsUpdate = true;
    done += pg.count;
    $("loading").textContent = `${t("loading")} ${done} / ${N}`;
  }
  $("loading").style.display = "none";
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
    if (MARKED.size) { alpha[i] = MARKED.has(i) ? 1 : 0.5; continue; }  // the rest stay clickable
    let on = true;
    if (focusCluster !== null) on = PTS[i].c === focusCluster;
    if (q) on = on && PTS[i].n.toLowerCase().includes(q);
    if (selected !== null) on = i === selected || PTS[selected].k.includes(i);
    else if (searchHits) on = searchHits.has(i);
    alpha[i] = on ? 1 : 0.12;
  }
  pushAlpha();
  fadeNames();
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
  if (i >= 0 && e.shiftKey && DATA.live) toggleMark(i);
  else if (i >= 0) select(i); else { selected = null; recolor(); }
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
  const named = ((DATA.live && DATA.live.names) || DATA.names || {})[String(c)];
  return named ? `${t("style")} ${c + 1} · ${named}` : `${t("style")} ${c + 1}`;
}

function thumb(i, onClick) {
  const img = document.createElement("img");
  img.src = PTS[i].t; img.alt = PTS[i].n; img.title = PTS[i].n; img.loading = "lazy";
  img.addEventListener("click", onClick || ((e) => (e.shiftKey && DATA.live ? toggleMark(i) : select(i))));
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
    const row = document.createElement("div"); row.className = "cl"; row.dataset.id = String(c.id);
    const img = document.createElement("img"); img.src = PTS[c.medoid]?.t || ""; img.alt = "";
    img.style.borderColor = colorOf(c.id);
    const txt = document.createElement("div");
    const nm = document.createElement("div"); nm.className = "name"; nm.textContent = clusterName(c.id);
    const mt = document.createElement("div"); mt.className = "meta";
    mt.textContent = `${c.size} ${t("size")}` + (c.cohesion !== undefined ? ` · ${t("cohesion")} ${c.cohesion.toFixed(3)}` : "");
    txt.append(nm, mt);
    if (c.tags && c.tags.length) {
      const tg = document.createElement("div"); tg.className = "meta tags"; tg.textContent = c.tags.join(", ");
      txt.append(tg);
    }
    if (c.near && c.near.length) {
      const nr = document.createElement("div"); nr.className = "meta near";
      nr.append(`${t("nearGroups")} `);
      c.near.forEach(([id, d], k) => {
        const a = document.createElement("a"); a.href = "#"; a.textContent = `${clusterName(id)} (${d.toFixed(2)})`;
        a.title = t("nearTip");
        a.addEventListener("click", (e) => {
          e.preventDefault(); e.stopPropagation();
          const target = [...pane.querySelectorAll(".cl")].find((r) => r.dataset.id === String(id));
          if (target) { target.scrollIntoView({ block: "nearest" }); target.click(); }
        });
        if (k) nr.append(" · ");
        nr.append(a);
      });
      txt.append(nr);
    }
    const look = lookWords(c.members);
    if (look) {
      const lk = document.createElement("div"); lk.className = "meta look"; lk.textContent = look;
      lk.title = t("lookTitle"); txt.append(lk);
    }
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
            if (DATA.clusters.length >= 2) bar.append(groupSelect(t("compareWith"), c.id, false, (other) => showCompare(c.id, other)));
            const nameBox = document.createElement("input"); nameBox.name = "groupName"; nameBox.setAttribute("aria-label", t("nameGroup"));
            nameBox.placeholder = t("nameGroup"); nameBox.value = (DATA.live.names || {})[String(c.id)] || "";
            nameBox.style.cssText = "margin-left:6px;width:120px;background:var(--panel);color:var(--ink);border:1px solid var(--line);border-radius:999px;padding:5px 8px;font:inherit;font-size:12px";
            nameBox.addEventListener("click", (e) => e.stopPropagation());
            nameBox.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter") editPost("api/rename", { group: c.id, name: nameBox.value }); });
            bar.append(nameBox);
            const more = document.createElement("button"); more.textContent = t("moreLike"); more.style.marginLeft = "6px";
            more.addEventListener("click", (e) => { e.stopPropagation(); showSimilar(c.id); });
            bar.append(more);
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

const CHECK_KEYS = ["smaller_than_min_side", "greyscale_in_colour_set", "extreme_aspect_ratio",
  "no_caption", "empty_caption", "animated", "truncated", "unreadable"];
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
  box.append(h, side, run);
  if (!CHECK) return box;
  const found = CHECK_KEYS.filter((k) => (CHECK.issues[k] || []).length);
  if (!found.length) {
    const ok = document.createElement("div"); ok.className = "kv"; ok.textContent = t("checkClean"); box.append(ok);
  }
  found.forEach((k) => {
    const list = CHECK.issues[k];
    const sub = document.createElement("div"); sub.className = "meta";
    const many = list.length > 0.9 * N;  // e.g. a folder without any captions: say so, no grid
    sub.textContent = `${t("chk_" + k).replace("{n}", CHECK.min_side)}: ${many ? t("checkAll").replace("{n}", list.length) : list.length}`;
    box.append(sub);
    if (!many) {
      const g = document.createElement("div"); g.className = "grid"; list.slice(0, 60).forEach((i) => g.append(thumb(i)));
      box.append(g);
    }
  });
  return box;
}

async function runCheck(minSide) {
  setStatus(t("checking"));
  try {
    CHECK = await post("api/check", JSON.stringify({ min_side: minSide }), "application/json");
    setStatus("");
  } catch (e) { setStatus(String(e.message || e)); }
  buildOutliers();  // also brings the button back
}

function buildOutliers() {
  const pane = $("pane-outliers"); pane.replaceChildren();
  if (DATA.live) pane.append(checkSection());
  const oh = document.createElement("h3"); oh.textContent = t("outliersTitle");
  const help = document.createElement("div"); help.className = "kv"; help.textContent = t("outlierHelp");
  const g = document.createElement("div"); g.className = "grid";
  [...PTS.keys()].sort((a, b) => PTS[b].o - PTS[a].o).slice(0, 60).forEach((i) => g.append(thumb(i)));
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
  help.textContent = groups.length ? t("dupHelp") : t("noDups");
  pane.append(help);
  groups.forEach((g, n) => {
    const h = document.createElement("h3"); h.textContent = `#${n + 1} · ${g.length}`;
    const grid = document.createElement("div"); grid.className = "grid";
    g.forEach((i) => grid.append(thumb(i)));
    pane.append(h, grid);
  });
}

// How the groups were made, in words: "auto cut 0.43", "3 periods", ...
function methodText() {
  const p = DATA.params || {};
  if (DATA.method === "kmeans") return t("periodsN").replace("{n}", p.n_clusters);
  if (DATA.method === "hdbscan") return "HDBSCAN";
  if (p.n_clusters) return t("forcedN").replace("{n}", p.n_clusters);
  if (p.threshold === undefined) return DATA.method;
  return (p.auto ? t("autoCut") : t("cut")).replace("{t}", Number(p.threshold).toFixed(2));
}

function applyText() {
  document.documentElement.lang = lang === "zh" ? "zh-Hant" : "en";
  $("title").querySelector("h1").textContent = DATA.title;
  $("title").querySelector(".sub").textContent =
    `${N} ${t("images")} · ${DATA.clusters.length} ${t("clusters").toLowerCase()} · ${methodText()}` +
    (DATA.params && DATA.params.edited ? ` · ${t("edited")}` : "");
  $("find").placeholder = t(DATA.live ? "findLive" : "find");
  $("mode").textContent = mode === "thumbs" ? t("dots") : t("thumbs");
  $("spin").textContent = t("spin"); $("home").textContent = t("home"); $("names").textContent = t("names");
  $("mode").title = t("tipMode"); $("names").title = t("tipNames"); $("home").title = t("tipHome");
  if (!recordingNow) $("rec").textContent = t("rec");
  $("rec").title = t("tipRec");
  $("layoutSel").title = t("tipLayoutSel");
  $("lang").textContent = lang === "zh" ? "EN" : "中";
  $("helpBtn").title = t("keys");
  if (!$("help").hidden) showHelp(true);
  const tabs = document.querySelectorAll(".tabs button");
  tabs[0].textContent = t("clusters"); tabs[1].textContent = t("selected"); tabs[2].textContent = t(DATA.live ? "checkTab" : "outliers");
  tabs[3].textContent = `${t("dups")}${(DATA.duplicates || []).length ? " " + DATA.duplicates.length : ""}`;
  document.querySelector("footer").textContent = t("foot");
  if (selected === null) {
    const e = document.createElement("div"); e.className = "empty"; e.textContent = t("pick");
    $("pane-selected").replaceChildren(e);
  }
  buildClusters(); buildOutliers(); buildDups(); liveText(); if (DATA.live) buildTaste();
  const many = DATA.clusters.length > Math.max(12, N / 8);  // e.g. one varied artist cut into dozens
  if (DATA.live && DATA.clusters.length <= 1 && N > 10) setStatus(t("oneGroup"));
  else if (DATA.live && many && !DATA.live.restored && !(DATA.params || {}).edited) setStatus(t("manyGroups"));
  else if (DATA.live && DATA.live.restored && !$("status").textContent) setStatus(t("restored"));
  else if (DATA.live && !DATA.live.restored && !$("status").textContent) setStatus(t("firstHint"));
  setupAxes(); if (layoutMode === "measures") drawAxes();
  drawNames();
}


let tagTimer = null;
$("find").addEventListener("input", (e) => {
  const text = e.target.value.trim();
  clearTimeout(tagTimer);
  if (DATA.live && text.startsWith("#")) {  // a caption tag: the server reads the captions
    filter = "";
    if (text.length < 2) { searchHits = null; recolor(); return; }
    tagTimer = setTimeout(() => findTag(text.slice(1)), 300);
    return;
  }
  filter = text; searchHits = null; recolor();
});

async function findTag(tag) {
  try {
    const r = await post("api/tagged", JSON.stringify({ tag }), "application/json");
    selected = null; searchHits = new Set(r.hits); recolor();
    setStatus(t("tagHits").replace("{n}", r.hits.length).replace("{t}", tag));
  } catch (e) { setStatus(String(e.message || e)); }
}
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
  flyTo = { target: new THREE.Vector3(), cam: homeView(), k: 0 };
  document.querySelectorAll(".cl").forEach((r) => r.classList.remove("on"));
});
$("lang").addEventListener("click", () => { lang = lang === "zh" ? "en" : "zh"; applyText(); });

// The keyboard and mouse shortcuts, toggled by "?" (built with textContent, like the rest).
function showHelp(on) {
  const box = $("help");
  box.hidden = !on;
  if (!on) return;
  const rows = [["drag", "keyRotate"], ["wheel", "keyZoom"], ["sizeKeys", "keySize"],
    ["Esc", "keyHome"], ...(DATA.live ? [["shiftKeys", "keyMark"], ["L / D", "keyVote"], ["X", "keyExclude"], ["Ctrl + Z", "keyUndo"]] : [])];
  box.replaceChildren(...rows.map(([key, what]) => {
    const line = document.createElement("div");
    const b = document.createElement("b"); b.textContent = ["drag", "wheel", "sizeKeys", "shiftKeys"].includes(key) ? t(key) : key;
    line.append(b, document.createTextNode(t(what)));
    return line;
  }));
}
$("helpBtn").addEventListener("click", () => showHelp($("help").hidden));
$("theme").addEventListener("click", () => {
  const root = document.documentElement;
  root.dataset.theme = root.dataset.theme === "light" ? "dark" : "light";
  setBackground();
});
addEventListener("keydown", (e) => {
  if (["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
  if (e.repeat) return;  // holding a key must not vote on images never looked at
  if (DATA.live && DATA.live.can_undo && (e.ctrlKey || e.metaKey) && !e.altKey && (e.key === "z" || e.key === "Z")) {
    e.preventDefault(); editPost("api/undo", {}); return;
  }
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === "?") showHelp($("help").hidden);
  if (e.key === "Escape") {
    RATING = false; PATH_FROM = null; setStatus(""); showHelp(false);
    if (MARKED.size) { MARKED = new Set(); showMarks(); }
    $("home").click();
  }
  if (DATA.live && selected !== null && (e.key === "l" || e.key === "L")) castVote(selected, true);
  if (DATA.live && selected !== null && (e.key === "d" || e.key === "D")) castVote(selected, false);
  if (DATA.live && selected !== null && (e.key === "x" || e.key === "X")) toggleExclude(selected);
  if (e.key === "+" || e.key === "=") setSize(pointSize * 1.2);
  if (e.key === "-") setSize(pointSize / 1.2);
});
canvas.addEventListener("wheel", (e) => { if (e.altKey) { e.preventDefault(); setSize(pointSize * (e.deltaY < 0 ? 1.1 : 1 / 1.1)); } }, { passive: false });
function setSize(s) { pointSize = Math.min(0.6, Math.max(0.02, s)); pages.forEach((pg) => (pg.mat.uniforms.uSize.value = pointSize)); }

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
  renderer.render(scene, camera);
}
