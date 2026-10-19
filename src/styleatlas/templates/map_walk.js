// One picture after another with the keyboard, so none is skipped: → ← the next and the one before
// (group by group as the side list orders them; on the wall row by row, elsewhere most typical
// first), ↑ ↓ the row above and below on the wall, Enter or Space the picture large (the viewer
// goes on through every group), Esc stops. The current picture is framed on the map and shown
// large on the other side; the map moves along when it leaves the view. A filter or search in
// force: only the pictures it lights. Where one stopped is kept for the next visit of the folder.
// Joined after map_viewer.js, before map_shell.js.

const WALK = { at: -1, on: false, order: null, marker: null };
const WALK_KEY = "styleAtlasWalk";
const WALK_EDGE = 0.8;  // the map moves when the picture is this far out from the middle (1 = the edge)
const WALK_PAD = 3;  // px between the picture and its frame
const WALK_MIN_PX = 10;  // the frame is never smaller than this, however far out the map is

function walkOrder() {  // every picture once, in the order the walk takes
  if (WALK.order) return WALK.order;
  const wall = layoutMode === "groups" && MOSAIC;  // map_layout.js
  WALK.order = GROUPS.flatMap((g) => (wall && MOSAIC.rows.has(g.id) ? MOSAIC.rows.get(g.id).flat() : typicalOrder(g.members)));
  return WALK.order;
}

function walkList() {  // the walk's pictures: those lit by a filter or search, else all
  const order = walkOrder(), lit = order.filter((i) => alpha[i] >= 0.5);
  return lit.length ? lit : order;
}

function walkKey() { return `${WALK_KEY}:${DATA.title || ""}:${N}`; }

function walkStart() {  // the picture under the cursor, else where the last walk stopped, else the first
  const list = walkList();  // a filter in force: only a picture it lights
  if (tipAt >= 0 && list.includes(tipAt)) return tipAt;
  let name = null;
  try { name = localStorage.getItem(walkKey()); } catch (e) { /* storage off */ }
  const i = name ? PTS.findIndex((p) => p.n === name) : -1;
  if (i >= 0 && list.includes(i)) { setStatus(t("walkResume").replace("{f}", name)); return i; }
  return list[0];
}

function walkStep(by) {
  const list = walkList();
  if (!list.length) return;
  if (WALK.at < 0) { walkShow(walkStart()); return; }  // the first press on this page
  // on from the picture the mouse points at, else the last one; one outside the list (a filter
  // came on): from the list's start or end
  const from = tipAt >= 0 && list.includes(tipAt) ? tipAt : WALK.at;
  const k = list.indexOf(from);
  walkShow(k < 0 ? list[by > 0 ? 0 : list.length - 1] : list[(k + by + list.length) % list.length]);
}

function walkRow(by) {  // the wall's row above or below, same column; past the block, the next group
  const i = WALK.at, list = walkList(), lit = new Set(list);
  const all = layoutMode === "groups" && MOSAIC && i >= 0 && lit.has(i) ? MOSAIC.rows.get(PTS[i].c) : null;
  if (!all) { walkStep(by); return; }
  const rows = all.map((row) => row.filter((j) => lit.has(j))).filter((row) => row.length);  // a filter: its pictures only
  const r = rows.findIndex((row) => row.includes(i)), col = rows[r].indexOf(i);
  const next = rows[r + by];
  if (next) { walkShow(next[Math.min(col, next.length - 1)]); return; }
  const k = list.indexOf(by > 0 ? rows[rows.length - 1].at(-1) : rows[0][0]);
  walkShow(list[(k + by + list.length) % list.length]);
}

function walkShow(i) {
  if (!(i >= 0 && i < N)) return;
  WALK.on = true; WALK.at = i;
  try { localStorage.setItem(walkKey(), PTS[i].n); } catch (e) { /* storage off */ }
  walkMarker().hidden = false;
  walkFollow(i);
  const tip = $("tip"), list = walkList(), same = list.filter((j) => PTS[j].c === PTS[i].c);
  const where = `${same.indexOf(i) + 1} / ${same.length}`;
  const all = same.length === list.length ? "" : t("walkAll").replace("{k}", list.indexOf(i) + 1).replace("{n}", list.length);
  tip.querySelector(".cap").textContent = `${PTS[i].n} · ${clusterName(PTS[i].c)} · ${where}${all}`;
  tip.querySelector(".keys").textContent = t("walkKeys");
  tip.classList.add("walking");
  if (tipAt !== i) showTipPicture(tip, i);  // map.js
  else fitTip(tip, tip.querySelector("img"));  // the same picture: room for the keys line
  tip.style.display = "block";
  const [x, y] = walkScreen(i);
  const r = canvas.getBoundingClientRect();
  tipSide = x - r.left < r.width / 2 ? 1 : -1;  // on the side away from the picture
  placeTip(tip, x, y);
  markHome(true);  // map.js: the view is no longer the whole map
}

function walkPause() {  // the mouse points at another picture: its preview, no frame; → goes on from it
  WALK.on = false;
  if (WALK.marker) WALK.marker.hidden = true;
  $("tip").classList.remove("walking");
}

function walkEnd() {
  if (!WALK.on) return false;
  WALK.on = false;
  if (WALK.marker) WALK.marker.hidden = true;
  $("tip").classList.remove("walking");
  hideTip();
  return true;
}

function walkScreen(i) {  // the picture's place in the window (px)
  const r = canvas.getBoundingClientRect();
  const v = new THREE.Vector3(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]).project(camera);
  return [r.left + (v.x + 1) / 2 * r.width, r.top + (1 - v.y) / 2 * r.height, v];
}

function walkFollow(i) {  // the map moves (same distance and angle) to bring the picture to the middle
  camera.updateMatrixWorld();
  const [, , v] = walkScreen(i);
  if (Math.abs(v.x) < WALK_EDGE && Math.abs(v.y) < WALK_EDGE && v.z < 1) return;
  const point = new THREE.Vector3(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]);
  flyTo = { target: point, cam: point.clone().add(camera.position.clone().sub(controls.target)), k: 0 };
}

function walkMarker() {  // a frame over the current picture: a page element, so its line stays 3 px at any zoom
  if (!WALK.marker) WALK.marker = $("walkFrame");
  return WALK.marker;
}

function placeWalkMarker() {  // every frame: the frame follows its picture (zoom, drags, morphs)
  const el = WALK.marker;
  if (!el || el.hidden || WALK.at < 0) return;
  const i = WALK.at, v = new THREE.Vector3(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]);
  camera.updateMatrixWorld();
  const [x, y, p] = walkScreen(i), r = canvas.getBoundingClientRect();
  // map_sharp.js: the picture's size inside its cell, device px to page px
  const px = screenSize(i, depthOf(v, new THREE.Vector3())) * (CELL - 8) / CELL / renderer.getPixelRatio();
  const ar = ASPECT[i] || 1;
  const w = Math.max(WALK_MIN_PX, px * Math.min(1, ar)), h = Math.max(WALK_MIN_PX, px * Math.min(1, 1 / ar));
  el.style.visibility = p.z < 1 ? "visible" : "hidden";  // behind the camera: nothing to frame
  el.style.left = `${x - r.left - w / 2 - WALK_PAD}px`; el.style.top = `${y - r.top - h / 2 - WALK_PAD}px`;
  el.style.width = `${w + 2 * WALK_PAD}px`; el.style.height = `${h + 2 * WALK_PAD}px`;
}

// true when the walk took the key
function walkKeyDown(e) {
  if (e.ctrlKey || e.metaKey || e.altKey || VIEWER || viewGroup !== null || !$("exportPanel").hidden) return false;
  if (e.target.closest && e.target.closest("aside, .menu, #help")) return false;  // lists and menus keep their keys
  const onMap = e.target === document.body || e.target === canvas;
  if ((e.key === "Enter" || e.key === " ") && !onMap) return false;  // a focused button presses itself
  if (e.key === "ArrowRight" || e.key === "ArrowLeft") { walkStep(e.key === "ArrowRight" ? 1 : -1); return true; }
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    if (!WALK.on) walkStep(1); else walkRow(e.key === "ArrowDown" ? 1 : -1);
    return true;
  }
  if ((e.key === "Enter" || e.key === " ") && !e.repeat) {
    const i = WALK.on && WALK.at >= 0 ? WALK.at : tipAt;
    if (i < 0) return false;
    const list = walkList();
    hideTip(); openViewer(i, list.includes(i) ? list : walkOrder());  // map_viewer.js
    return true;
  }
  if (e.key === "Escape") return walkEnd();
  return false;
}

function walkAfterViewer(i) {  // the viewer closed: the walk goes on from the picture it showed
  if (WALK.on && i >= 0) walkShow(i);
}

function walkLayoutChanged() { WALK.order = null; walkEnd(); }  // the wall's rows differ from the 3D order
