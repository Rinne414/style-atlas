// Sharp pictures close up. The map's pictures come from small atlas cells (CELL px), so a picture
// drawn larger than its cell is a blur. Every few frames the pictures that are large on screen get
// a sprite of their own from a sharper file (the live app's view/N, the original when very large),
// drawn exactly over the atlas picture (same size, frame and colour) and a hair in front of it.
// Joined after map_layout.js, before map_group.js.

const SHARP_MAX = 60;  // sprites at once: the largest pictures on screen first
const SHARP_FROM = 1.25;  // a picture drawn this many times its cell's size gets a sharp sprite
const SHARP_ORIGINAL_PX = 700;  // drawn larger than this (device px): the original file
const SHARP_CANVAS = { view: 512, original: 1024 };  // sprite canvas sizes
const SHARP_WEIGHT = { view: 1, original: 4 };  // texture memory, in 512-px canvases (about 1.3 MB)
const SHARP_CACHE = 160;  // that much kept, with pictures that left the screen (a step back and forth)
const SHARP_EVERY_MS = 120;  // how often the candidates are chosen again
const sharpGroup = new THREE.Group();
scene.add(sharpGroup);
const SHARP = new Map();  // "i:tier" -> { i, tier, sprite (when ready), used, failed }
let lastSharp = 0;

function sharpUrl(i, tier) {  // the shared map file has only the originals (from the sender's folder)
  if (DATA.live) return tier === "view" ? `view/${i}` : PTS[i].f;
  // a map file opened from disk: its pictures would taint the canvas, and WebGL refuses those
  return location.protocol === "file:" ? null : PTS[i].f;
}

function drawSharp(img, tier, col) {  // the atlas cell's look (drawThumb), at a sharper size
  const size = SHARP_CANVAS[tier], k = size / CELL, edge = 4 * k;
  const cv = document.createElement("canvas"); cv.width = size; cv.height = size;
  const g = cv.getContext("2d");
  const s = (size - 2 * edge) / Math.max(img.naturalWidth, img.naturalHeight);
  const w = img.naturalWidth * s, h = img.naturalHeight * s, x = (size - w) / 2, y = (size - h) / 2;
  g.fillStyle = col; g.fillRect(x - edge, y - edge, w + 2 * edge, h + 2 * edge);
  g.imageSmoothingQuality = "high";
  g.drawImage(img, x, y, w, h);
  return cv;
}

function loadSharp(entry) {
  const url = sharpUrl(entry.i, entry.tier);
  if (!url) { entry.failed = true; return; }
  const img = new Image();
  img.decoding = "async";
  img.onload = () => {
    const tex = srgbTexture(drawSharp(img, entry.tier, colorOf(PTS[entry.i].c)));  // map_layout.js
    tex.anisotropy = 4;
    const mat = new THREE.SpriteMaterial({ map: tex, sizeAttenuation: false, transparent: true, alphaTest: 0.08,
      depthTest: true, depthWrite: true, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -8 });
    entry.sprite = new THREE.Sprite(mat);
    entry.sprite.renderOrder = 1;
    entry.sprite.visible = false;
    sharpGroup.add(entry.sprite);
  };
  img.onerror = () => { entry.failed = true; };
  img.src = url;
}

function screenSize(i, depth) {  // the picture's size on screen in device px, as the point shader draws it
  return pointSize * pages[0].mat.uniforms.uScale.value * depthScale(depth) * (0.55 + 0.45 * alpha[i]);
}

function depthOf(v, scratch) {  // distance in front of the camera
  return -scratch.copy(v).applyMatrix4(camera.matrixWorldInverse).z;
}

function sharpCandidates() {  // [i, size px, tier] of the pictures drawn well past their cell
  const out = [], v = new THREE.Vector3(), w = new THREE.Vector3(), from = (CELL - 8) * SHARP_FROM;
  for (let i = 0; i < N; i++) {
    if (alpha[i] < 0.5) continue;
    v.set(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]);
    const depth = depthOf(v, w);
    if (depth <= 0) continue;
    const px = screenSize(i, depth);
    if (px < from) continue;
    v.project(camera);
    const mx = px / Math.max(1, renderer.domElement.width), my = px / Math.max(1, renderer.domElement.height);
    if (Math.abs(v.x) > 1 + mx || Math.abs(v.y) > 1 + my) continue;  // off screen
    out.push([i, px, px > SHARP_ORIGINAL_PX ? "original" : "view"]);
  }
  return out.sort((a, b) => b[1] - a[1]).slice(0, SHARP_MAX);
}

function pickSharp(now) {  // which pictures get a sprite now; start loading the missing ones
  lastSharp = now;
  const want = new Set();
  for (const [i, , tier] of sharpCandidates()) {
    const key = `${i}:${tier}`;
    want.add(key);
    let entry = SHARP.get(key);
    if (!entry) { entry = { i, tier, sprite: null, used: now, failed: false }; SHARP.set(key, entry); loadSharp(entry); }
    entry.used = now;
  }
  for (const [key, entry] of SHARP) {  // not wanted: hidden; the least recently used are let go
    entry.wanted = want.has(key);
    if (!entry.wanted && entry.sprite) entry.sprite.visible = false;
  }
  let weight = 0;
  SHARP.forEach((e) => { weight += SHARP_WEIGHT[e.tier]; });
  if (weight <= SHARP_CACHE) return;
  const old = [...SHARP.entries()].filter(([, e]) => !e.wanted).sort((a, b) => a[1].used - b[1].used);
  for (const [key, e] of old) {
    if (weight <= SHARP_CACHE) break;
    dropSharp(e); SHARP.delete(key); weight -= SHARP_WEIGHT[e.tier];
  }
}

function dropSharp(entry) {
  if (!entry.sprite) return;
  sharpGroup.remove(entry.sprite);
  entry.sprite.material.map.dispose(); entry.sprite.material.dispose();
}

function sharpShown() {  // picture -> the sprite to draw: its wanted size, else one loaded before
  const wanted = new Set(), out = new Map();
  for (const e of SHARP.values()) if (e.wanted) wanted.add(e.i);
  for (const e of SHARP.values()) {
    if (!e.sprite) continue;
    e.sprite.visible = false;
    if (wanted.has(e.i) && alpha[e.i] >= 0.5 && (e.wanted || !out.has(e.i))) out.set(e.i, e.sprite);
  }
  return out;  // a picture going from view to original keeps its view sprite until the original is in
}

function placeSharp() {  // every frame: the sprites follow their points (morphs, size, dimming)
  const tanV = Math.tan((camera.fov * Math.PI) / 360), v = new THREE.Vector3(), w = new THREE.Vector3();
  for (const [i, sprite] of sharpShown()) {
    v.set(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]);
    // full height on screen = scale * P11 * height / 2 (sizeAttenuation off): match the point's size
    const k = screenSize(i, depthOf(v, w)) * 2 * tanV / Math.max(1, renderer.domElement.height);
    sprite.position.copy(v);
    sprite.scale.set(k, k, 1);
    sprite.material.color.setScalar(0.35 + 0.65 * alpha[i]);
    sprite.visible = true;
  }
}

function updateSharp(now) {  // from the render loop
  const on = mode === "thumbs" && pages.length > 0;
  sharpGroup.visible = on;
  if (!on) return;
  camera.updateMatrixWorld();  // this frame's camera, or the sprites trail the points by a frame
  if (now - lastSharp >= SHARP_EVERY_MS) pickSharp(now);
  placeSharp();
}
