// The group view: one style group over the whole map area, for going through the groups one by
// one. Its most typical images first, the ones that sit apart from it, the closest groups side by
// side, and the group's edits. Joined after map_layout.js, before map_app.js (whose start-up opens
// the view again after an edit reloads the page).

let GROUPS = [];  // as the side list shows them: the groups, then the unassigned
let viewGroup = null;  // the group in the view, or null when the map shows
let viewAnchor = null;  // set by an edit's reload: an image whose group the view opens on
let viewAll = false;  // "show all" pressed: kept while the open view is rebuilt
const VIEW_FIRST = 80;  // typical images shown before "show all"
const NEAR_SHOWN = 3;  // closest groups compared side by side
const NEAR_THUMBS = 8;  // images of each of them
const MIN_FOR_STRAYS = 8;  // smaller groups have no quartiles worth reading
const SIZE_KEY = "styleAtlasViewSize";
const SIZES = [72, 96, 128, 176, 240];

function typicalOrder(members) {  // closest to the group's centre first (unassigned: as listed)
  return [...members].sort((a, b) => (PTS[a].g ?? 0) - (PTS[b].g ?? 0));
}

function straysOf(c) {  // members far past the group's spread: beyond Tukey's upper fence
  const d = c.members.map((i) => PTS[i].g).filter((v) => v !== null && v !== undefined).sort((a, b) => a - b);
  if (c.id < 0 || d.length < MIN_FOR_STRAYS) return [];
  const q = (p) => d[Math.min(d.length - 1, Math.floor(p * (d.length - 1)))];
  const fence = q(0.75) + 1.5 * (q(0.75) - q(0.25));
  return c.members.filter((i) => PTS[i].g > fence).sort((a, b) => PTS[b].g - PTS[a].g);
}

function tile(i) {  // the live app sends a sharper picture for these larger tiles
  const img = thumb(i);
  img.dataset.i = String(i);
  img.classList.toggle("marked", MARKED.has(i));
  if (DATA.live) { img.onerror = () => { img.onerror = null; img.src = PTS[i].t; }; img.src = `view/${i}`; }
  return img;
}

function storedSize() {
  try { const v = parseInt(localStorage.getItem(SIZE_KEY), 10); return SIZES.includes(v) ? v : 128; }
  catch (e) { return 128; }
}

function openGroup(id) {
  const c = GROUPS.find((g) => g.id === id);
  if (!c) return;
  viewGroup = id; viewAll = false;
  focusCluster = id; selected = null; recolor();
  setSpin(false);
  const view = $("groupView");
  fillView(c);
  view.hidden = false; view.scrollTop = 0;
  document.body.classList.add("gv-open");
  view.focus({ preventScroll: true });
}

function refreshGroupView() {  // after the list is rebuilt (language, exclusions, dots): same place
  if (viewGroup === null) return;
  const c = GROUPS.find((g) => g.id === viewGroup);
  if (!c) { closeGroup(false); return; }
  const view = $("groupView"), top = view.scrollTop;
  fillView(c);
  view.scrollTop = top;
}

function fillView(c) {
  document.querySelectorAll("#pane-clusters .cl").forEach((r) => {
    const on = r.dataset.id === String(c.id);
    r.classList.toggle("on", on);
    if (on) r.scrollIntoView({ block: "nearest" });
  });
  $("groupView").replaceChildren(viewHead(c), viewBody(c));
}

function closeGroup(showOnMap = true) {
  if (viewGroup === null) return;
  const id = viewGroup;
  viewGroup = null;
  $("groupView").hidden = true;
  document.body.classList.remove("gv-open");
  const c = GROUPS.find((g) => g.id === id);
  if (showOnMap && c && c.members.length) focusOn(c.members);
}

function stepGroup(by) {
  const k = GROUPS.findIndex((g) => g.id === viewGroup);
  if (k >= 0 && GROUPS.length > 1) openGroup(GROUPS[(k + by + GROUPS.length) % GROUPS.length].id);
}

function groupViewKey(e) {  // true when the key was the view's (Alt+Left and the like are not)
  if (viewGroup === null || e.ctrlKey || e.metaKey || e.altKey) return false;
  if (e.key === "Escape") {
    if (!$("help").hidden) showHelp(false); else closeGroup();
    return true;
  }
  if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return false;
  if (!e.repeat) stepGroup(e.key === "ArrowLeft" ? -1 : 1);  // a held key would rebuild per repeat
  return true;
}

function viewHead(c) {
  const head = document.createElement("header"); head.className = "gv-head";
  const button = (text, title, fn) => {
    const b = document.createElement("button"); b.textContent = text; b.title = title;
    b.setAttribute("aria-label", title); b.addEventListener("click", fn); return b;
  };
  const dot = document.createElement("span"); dot.className = "dot"; dot.style.background = colorOf(c.id);
  const name = document.createElement("h2"); name.append(dot, clusterName(c.id));
  const k = GROUPS.findIndex((g) => g.id === c.id);
  const where = document.createElement("span"); where.className = "gv-count";
  where.textContent = `${k + 1} / ${GROUPS.length}`;
  const size = document.createElement("select"); size.setAttribute("aria-label", t("gvSize")); size.title = t("gvSize");
  SIZES.forEach((px) => { const o = document.createElement("option"); o.value = String(px); o.textContent = `${t("gvSize")} ${px}`; size.append(o); });
  size.value = String(storedSize());
  size.addEventListener("change", () => {
    $("groupView").style.setProperty("--gv-size", `${size.value}px`);
    try { localStorage.setItem(SIZE_KEY, size.value); } catch (e) { /* storage off: this visit only */ }
  });
  $("groupView").style.setProperty("--gv-size", `${storedSize()}px`);
  const keys = document.createElement("span"); keys.className = "gv-keys"; keys.textContent = t("gvKeys");
  head.append(button("‹", t("gvPrev"), () => stepGroup(-1)), name, where, button("›", t("gvNext"), () => stepGroup(1)),
    keys, size, button(t("gvBack"), t("gvBack"), () => closeGroup()));
  return head;
}

function viewBody(c) {
  const body = document.createElement("div"); body.className = "gv-body";
  const about = clusterText(c, $("pane-clusters"));  // the side list's lines, the name aside
  about.classList.add("gv-about");
  body.append(about);
  const bar = groupBar(c);
  if (bar) { bar.style.cssText = ""; bar.className = "gv-bar"; body.append(bar); }
  const strays = straysOf(c);
  const stray = new Set(strays);
  const typical = typicalOrder(c.members).filter((i) => !stray.has(i));
  const typicalTitle = t(c.id < 0 ? "gvUnassigned" : "gvTypical").replace("{n}", typical.length);
  body.append(section(typicalTitle, typical, viewAll ? Infinity : VIEW_FIRST, () => { viewAll = true; }));
  if (c.id >= 0) {
    const s = section(strays.length ? t("gvStrays").replace("{n}", strays.length) : t("gvNoStrays"), strays, Infinity);
    if (strays.length) {
      s.classList.add("strays");
      const why = document.createElement("p"); why.className = "gv-note";
      why.textContent = t(DATA.live ? "gvStraysLive" : "gvStraysWhy");
      s.insertBefore(why, s.children[1]);
    }
    body.append(s);
  }
  if (c.near && c.near.length) body.append(nearSection(c));
  return body;
}

function section(title, indices, first, onAll = null) {
  const box = document.createElement("section");
  const h = document.createElement("h3"); h.textContent = title;
  const grid = document.createElement("div"); grid.className = "grid gv-grid";
  indices.slice(0, first).forEach((i) => grid.append(tile(i)));
  box.append(h, grid);
  if (indices.length > first) {
    const more = document.createElement("button"); more.className = "gv-more";
    more.textContent = t("gvShowAll").replace("{n}", indices.length);
    more.addEventListener("click", () => {
      indices.slice(first).forEach((i) => grid.append(tile(i)));
      more.remove();
      if (onAll) onAll();
    });
    box.append(more);
  }
  return box;
}

function nearSection(c) {  // the closest groups, a row of each one's typical images
  const box = document.createElement("section");
  const h = document.createElement("h3"); h.textContent = t("gvNear"); box.append(h);
  c.near.slice(0, NEAR_SHOWN).forEach(([id, d]) => {
    const other = GROUPS.find((g) => g.id === id);
    if (!other) return;
    const row = document.createElement("div"); row.className = "gv-near";
    const label = document.createElement("div"); label.className = "gv-near-label";
    const name = document.createElement("a"); name.href = "#"; name.textContent = clusterName(id);
    name.style.borderColor = colorOf(id);
    name.addEventListener("click", (e) => { e.preventDefault(); openGroup(id); });
    const dist = document.createElement("span"); dist.className = "meta";
    dist.textContent = `${t("gvDistance")} ${d.toFixed(2)} · ${other.size} ${t("size")}`;
    label.append(name, dist);
    if (DATA.live) label.append(mergeButton(c, other));
    const strip = document.createElement("div"); strip.className = "grid gv-strip";
    typicalOrder(other.members).slice(0, NEAR_THUMBS).forEach((i) => strip.append(tile(i)));
    row.append(label, strip);
    box.append(row);
  });
  return box;
}

function mergeButton(c, into) {  // two clicks: the first only asks
  const b = document.createElement("button");
  b.textContent = t("gvMerge").replace("{b}", clusterName(into.id));
  b.addEventListener("click", () => {
    if (!b.classList.contains("on")) { b.classList.add("on"); b.textContent = t("gvMergeSure"); return; }
    const anchor = typicalOrder(into.members)[0];  // the merged group: where the view reopens
    editPost("api/merge", { from: c.id, into: into.id }, "", anchor);
  });
  return b;
}

function markTiles() {  // Shift+click marks: shown on the view's tiles too
  document.querySelectorAll("#groupView img[data-i]").forEach((img) => img.classList.toggle("marked", MARKED.has(Number(img.dataset.i))));
}

function anchorForReload() {  // the view's group after an edit: one of its images left in place
  if (viewGroup === null) return null;
  const c = GROUPS.find((g) => g.id === viewGroup);  // marked images are the ones being moved
  return c ? typicalOrder(c.members).find((i) => !MARKED.has(i)) ?? null : null;
}

function reopenGroup(anchor) {  // after an edit's reload
  if (Number.isInteger(anchor) && anchor >= 0 && anchor < N) openGroup(PTS[anchor].c);
}
