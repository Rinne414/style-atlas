// The picture viewer: one picture over the whole window, from its original file, with the
// pictures it was opened among a key away (← →). Opened by a click in the group view, a double
// click on the map or in a list, or a click on the details tab's picture. Also the map's double
// click on empty space (zoom in there). Joined after map_browse.js, before map_shell.js.

let VIEWER = null;  // { list, at }: the pictures stepped through and the one shown
const VIEWER_UPSCALE = 2;  // small pictures are enlarged to fit the window, at most this much (more blurs)
const VIEWER_ZOOM_MAX = 4;  // the wheel zooms in up to this many screen pixels per picture pixel
const VIEWER_WHEEL = 1.25;  // per wheel step
const VIEWER_DRAG = 4;  // px: a press that moves less is a click
let VZ = { k: 1, x: 0, y: 0 };  // the zoom over the fitted picture: its scale and shift (px)

function gridOrder(img) {  // the pictures of the grid a tile sits in, in their order
  const grid = img.closest(".grid");
  const list = grid ? [...grid.querySelectorAll("img[data-i]")].map((el) => Number(el.dataset.i)) : [];
  return list.length ? list : null;
}

function groupOrder(i) {  // a picture's group, most typical first (map_group.js)
  return typicalOrder(PTS.map((p, j) => j).filter((j) => PTS[j].c === PTS[i].c));
}

function openViewer(i, list) {
  const order = Array.isArray(list) && list.includes(i) ? list : [i];
  VIEWER = { list: order, at: order.indexOf(i) };
  $("tip").style.display = "none";
  $("viewer").hidden = false;
  showViewerPicture();
}

function closeViewer() {
  if (!VIEWER) return;
  const last = VIEWER.list[VIEWER.at];
  VIEWER = null;
  $("viewer").hidden = true;
  $("viewer").querySelector("img").removeAttribute("src");
  walkAfterViewer(last);  // map_walk.js: a keyboard walk goes on from here
}

function viewerWhere(i) {  // "12 / 241" in its group; over several groups also the place in all
  const list = VIEWER.list, same = list.filter((j) => PTS[j].c === PTS[i].c);
  const here = `${same.indexOf(i) + 1} / ${same.length}`;
  return same.length === list.length ? here : here + t("walkAll").replace("{k}", VIEWER.at + 1).replace("{n}", list.length);
}

function stepViewer(by) {
  if (!VIEWER || VIEWER.list.length < 2) return;
  VIEWER.at = (VIEWER.at + by + VIEWER.list.length) % VIEWER.list.length;
  showViewerPicture();
}

function showViewerPicture() {
  const box = $("viewer"), i = VIEWER.list[VIEWER.at], many = VIEWER.list.length > 1;
  const stage = box.querySelector(".stage"), img = stage.querySelector("img");
  VZ = { k: 1, x: 0, y: 0 }; applyViewerZoom(img);
  img.onerror = () => { img.onerror = null; img.src = PTS[i].t; };  // a shared map without the folder
  img.onload = () => fitViewerPicture(img, stage);
  img.style.width = ""; img.src = !DATA.live && PTS[i].v ? PTS[i].v : PTS[i].f;  // a shared file: its own preview
  img.alt = PTS[i].n; img.title = t("viewerFit");
  box.querySelectorAll(".nav").forEach((b) => { b.hidden = !many; });
  box.querySelector(".nav.prev").title = t("viewerPrev"); box.querySelector(".nav.next").title = t("viewerNext");
  box.querySelector(".what b").textContent = PTS[i].n;
  box.querySelector(".what em").textContent = t("viewerKeys");
  box.querySelector(".what span").textContent = `${clusterName(PTS[i].c)}` +
    (many ? ` · ${viewerWhere(i)}` : "") + (EXCLUDED.has(i) ? ` · ${t("excludedMark")}` : "");
  box.querySelector(".bar").replaceChildren(box.querySelector(".what"), ...viewerButtons(i));
  if (many && DATA.live) new Image().src = PTS[VIEWER.list[(VIEWER.at + 1) % VIEWER.list.length]].f;  // the next one, ahead
}

function fitViewerPicture(img, stage) {  // fit the window; a small picture grows, up to VIEWER_UPSCALE
  const room = stage.getBoundingClientRect();
  const w = img.naturalWidth, h = img.naturalHeight;
  VZ = { k: 1, x: 0, y: 0 }; applyViewerZoom(img);
  if (!w || !h) { img.style.width = ""; return; }
  const k = Math.min(VIEWER_UPSCALE, (room.width - 112) / w, (room.height - 32) / h);
  img.style.width = `${Math.max(1, Math.round(w * k))}px`;
}

function viewerButtons(i) {
  const button = (key, fn, cls = "") => {
    const b = document.createElement("button"); b.textContent = t(key); if (cls) b.className = cls;
    b.addEventListener("click", fn); return b;
  };
  const out = [];
  if (DATA.live) {
    out.push(button("findSimilar", () => { closeViewer(); showSimilar({ items: [i] }); }, "primary"));  // map_app.js
    out.push(button("viewerFile", () => openOriginal(i, false)), button("reveal", () => openOriginal(i, true)));
  } else {
    const a = document.createElement("a"); a.href = PTS[i].f; a.target = "_blank"; a.rel = "noopener";
    a.textContent = t("openShared"); a.title = t("openSharedTip"); a.style.color = "#f2c38b";
    out.push(a);
  }
  out.push(button("viewerClose", closeViewer));
  return out;
}

async function openOriginal(i, reveal) {  // in the picture program, or selected in its folder
  try { await post("api/open_file", JSON.stringify({ i, reveal }), "application/json"); }  // map_app.js
  catch (e) { setStatus(String(e.message || e)); }
}

// true when the viewer took the key. While it is open the map's own keys stay off; Tab, Enter and
// Space still work its buttons, and the browser keeps F5, F11 and the like
const VIEWER_MAP_KEYS = new Set(["?", "p", "P", "+", "=", "-"]);
function viewerKey(e) {
  if (!VIEWER || e.ctrlKey || e.metaKey || e.altKey) return false;
  const i = VIEWER.list[VIEWER.at], key = e.key.toLowerCase(), live = DATA.live && !e.repeat;
  if (e.key === "Escape") closeViewer();
  else if (e.key === "ArrowLeft") stepViewer(-1);
  else if (e.key === "ArrowRight") stepViewer(1);
  else if (live && key === "l") castVote(i, true);  // map_app.js
  else if (live && key === "d") castVote(i, false);
  else if (live && key === "x") toggleExclude(i).then(() => VIEWER && showViewerPicture());
  else return VIEWER_MAP_KEYS.has(e.key);  // swallowed: they would act on the map under the viewer
  return true;
}

function applyViewerZoom(img) {  // transform-origin is the top left (map.css)
  img.style.transform = VZ.k === 1 ? "" : `translate(${VZ.x}px, ${VZ.y}px) scale(${VZ.k})`;
  img.classList.toggle("zoomed", VZ.k > 1);
}

// zoom to k times the fitted size, the picture's point under (cx, cy) staying there; 1 = fitted
function zoomViewer(img, k, cx, cy) {
  const r = img.getBoundingClientRect();  // as drawn now, zoom included
  const fitW = r.width / VZ.k;
  const most = Math.max(1, (img.naturalWidth * VIEWER_ZOOM_MAX) / Math.max(1, fitW * devicePixelRatio));
  const next = Math.min(most, Math.max(1, k));
  const px = (cx - r.left) / VZ.k, py = (cy - r.top) / VZ.k;  // that point on the fitted picture
  const left = r.left - VZ.x, top = r.top - VZ.y;  // the fitted picture's corner
  VZ = next === 1 ? { k: 1, x: 0, y: 0 } : { k: next, x: cx - left - px * next, y: cy - top - py * next };
  applyViewerZoom(img);
}

function actualSize(img) {  // the zoom that shows the picture's own pixels one to one
  const fitW = img.getBoundingClientRect().width / VZ.k;
  return img.naturalWidth / Math.max(1, fitW * devicePixelRatio);
}

// the wheel zooms where it points; a drag moves a zoomed picture; a click switches between the
// fitted picture and its own pixels at the point clicked
function setupViewerZoom(stage, img) {
  stage.addEventListener("wheel", (e) => {
    e.preventDefault();
    zoomViewer(img, VZ.k * (e.deltaY < 0 ? VIEWER_WHEEL : 1 / VIEWER_WHEEL), e.clientX, e.clientY);
  }, { passive: false });
  let press = null;
  img.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault(); img.setPointerCapture(e.pointerId);
    press = { x: e.clientX, y: e.clientY, vx: VZ.x, vy: VZ.y, moved: false };
  });
  img.addEventListener("pointermove", (e) => {
    if (!press) return;
    const dx = e.clientX - press.x, dy = e.clientY - press.y;
    if (Math.hypot(dx, dy) > VIEWER_DRAG) press.moved = true;
    if (press.moved && VZ.k > 1) { VZ.x = press.vx + dx; VZ.y = press.vy + dy; applyViewerZoom(img); }
  });
  img.addEventListener("pointerup", (e) => {
    if (!press) return;
    const click = !press.moved; press = null;
    if (click) zoomViewer(img, VZ.k > 1 ? 1 : Math.max(2, actualSize(img)), e.clientX, e.clientY);
  });
  img.addEventListener("pointercancel", () => { press = null; });
}

function setupViewer() {
  const box = $("viewer"), stage = box.querySelector(".stage");
  box.querySelector(".nav.prev").addEventListener("click", () => stepViewer(-1));
  box.querySelector(".nav.next").addEventListener("click", () => stepViewer(1));
  const img = stage.querySelector("img");
  img.draggable = false;
  setupViewerZoom(stage, img);
  addEventListener("resize", () => { if (VIEWER) fitViewerPicture(img, stage); });
  stage.addEventListener("click", (e) => { if (e.target === stage) closeViewer(); });  // the dark around it
}
setupViewer();

// the map: a double click on a picture shows it large; next to pictures it zooms in on the closest
// one (twice as close); far from any it does nothing (zooming into empty space only loses the map)
const DBL_REACH = 120;  // px from the click to the closest picture

function closestOnScreen(e) {
  const r = canvas.getBoundingClientRect();
  const mx = e.clientX - r.left, my = e.clientY - r.top;
  let best = -1, bestD = DBL_REACH;
  const v = new THREE.Vector3();
  for (let i = 0; i < N; i++) {
    if (alpha[i] < 0.5) continue;
    v.set(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]).project(camera);
    if (v.z > 1) continue;
    const d = Math.hypot((v.x + 1) / 2 * r.width - mx, (1 - v.y) / 2 * r.height - my);
    if (d < bestD) { bestD = d; best = i; }
  }
  return best;
}

canvas.addEventListener("dblclick", (e) => {
  const i = pick(e);
  if (i >= 0) { openViewer(i, walkList().includes(i) ? walkList() : walkOrder()); return; }  // map_walk.js: every group in turn
  const near = closestOnScreen(e);
  if (near < 0) return;
  const point = new THREE.Vector3(pos[near * 3], pos[near * 3 + 1], pos[near * 3 + 2]);
  const back = camera.position.clone().sub(controls.target).multiplyScalar(0.5);  // half as far as now
  if (back.length() < controls.minDistance) back.setLength(controls.minDistance);
  flyTo = { target: point, cam: point.clone().add(back), k: 0 };
  markHome(true);  // map.js
  setSpin(false);
});
