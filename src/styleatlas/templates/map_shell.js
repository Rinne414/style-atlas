// The frame around the map: the View menu (less used map tools, colours, language), the interface
// size (text and buttons, kept for the next visit; the page head applies it before anything is
// drawn) and, inside the desktop program, the way back to its start page. Joined after
// map_viewer.js, before map_app.js.

const UI_KEY = "styleAtlasUi";
const UI_SIZES = [["uiS", 0.9], ["uiM", 1], ["uiL", 1.15], ["uiXL", 1.3]];
const UI_MIN = 0.8, UI_MAX = 1.6, UI_STEP = 0.1;

function uiSize() {
  const v = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--ui"));
  return Number.isFinite(v) && v > 0 ? v : 1;
}

function setUiSize(v) {
  const size = Math.round(Math.min(UI_MAX, Math.max(UI_MIN, v)) * 100) / 100;
  document.documentElement.style.setProperty("--ui", String(size));
  store(UI_KEY, String(size));
  uiSizeButtons();
  resize();  // map.js: the side panel changed width, so did the map
}

function uiSizeButtons() {
  const now = uiSize();
  document.querySelectorAll("#uiSize button").forEach((b) => b.classList.toggle("on", Math.abs(Number(b.dataset.size) - now) < 0.01));
}

function setupUiSize() {
  const row = $("uiSize");
  UI_SIZES.forEach(([key, v]) => {
    const b = document.createElement("button"); b.dataset.size = String(v); b.dataset.key = key;
    b.addEventListener("click", () => setUiSize(v));
    row.append(b);
  });
  addEventListener("keydown", (e) => {  // Ctrl + / Ctrl - / Ctrl 0, instead of zooming the whole page
    if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
    if (e.key === "=" || e.key === "+") setUiSize(uiSize() + UI_STEP);
    else if (e.key === "-" || e.key === "_") setUiSize(uiSize() - UI_STEP);
    else if (e.key === "0") setUiSize(1);
    else return;
    e.preventDefault();
  });
}

/* ---------- the View menu ---------- */
function closeViewMenu() { $("viewMenu").hidden = true; $("viewMenuBtn").setAttribute("aria-expanded", "false"); }

function setupViewMenu() {
  const menu = $("viewMenu"), button = $("viewMenuBtn");
  button.addEventListener("click", () => {
    menu.hidden = !menu.hidden; button.setAttribute("aria-expanded", String(!menu.hidden));
  });
  document.addEventListener("pointerdown", (e) => {  // a click elsewhere closes it
    if (!menu.hidden && !menu.contains(e.target) && e.target !== button) closeViewMenu();
  });
  addEventListener("keydown", (e) => { if (e.key === "Escape" && !menu.hidden) closeViewMenu(); });
  // the one-shot items close it; the switches (dots, turning) and the size stay open to see the change
  ["savePng", "rec", "theme", "lang"].forEach((id) => $(id).addEventListener("click", closeViewMenu));
  $("theme").addEventListener("click", shellText);  // map.js switched the colours first
  $("spin").addEventListener("click", shellText);
}

/* ---------- inside the desktop program (desktop.py) ---------- */
function desktopApi() { return window.pywebview && window.pywebview.api; }

function setupDesktop() {
  const show = () => { if (desktopApi() && desktopApi().home) $("openOther").hidden = false; };
  show();
  window.addEventListener("pywebviewready", show);
  $("openOther").addEventListener("click", () => {
    $("openOther").disabled = true;
    Promise.resolve(desktopApi()?.home()).catch((e) => { $("openOther").disabled = false; setStatus(String(e.message || e)); });
  });
}

function shellText() {  // called by applyText (map.js)
  document.querySelectorAll("#layoutSeg button").forEach((b) => {
    b.textContent = t(b.dataset.layout === "groups" ? "layoutGroups" : "layoutStyle"); b.title = t("tipLayoutSwitch");
  });
  $("layoutMeasures").textContent = t("layoutMeasures");
  $("viewMenuBtn").textContent = `${t("viewMenu")} ▾`; $("viewMenuBtn").title = t("tipViewMenu");
  $("mode").textContent = t(mode === "thumbs" ? "toDots" : "toThumbs"); $("mode").title = t("tipMode");
  $("spin").textContent = t("spin");
  $("savePng").textContent = t("savePngItem"); $("savePng").title = t("tipSavePng");
  $("theme").textContent = t(document.documentElement.dataset.theme === "light" ? "toDark" : "toLight");
  $("theme").title = t("tipTheme");
  $("lang").textContent = t("langSwitch");
  $("uiSize").querySelector(".lbl").textContent = t("uiSize"); $("uiSize").title = t("tipUiSize");
  document.querySelectorAll("#uiSize button").forEach((b) => { b.textContent = t(b.dataset.key); });
  uiSizeButtons();
  $("openOther").textContent = t("openOther"); $("openOther").title = t("tipOpenOther");
  layoutShown();  // map_layout.js: the switch and the line under the title
}

setupUiSize();
setupViewMenu();
setupDesktop();
