// The export dialog (live app): tick the groups to export, as one LoRA per group or one for all,
// choose where; what it will write updates as you go, and the folder opens when it is done.
// Joined after map_shell.js, before map_app.js (whose setupLive calls setupExport).

const EXPORT_KEY = "styleAtlasExport";  // the dialog's choices for this folder, kept for the next visit
const EXPORT_FIELDS = ["expLayout", "expName", "expMax", "expRep", "expStrip", "expDest"];
const EXPORT_MIN = 3;  // smaller groups start unticked (too few pictures for a LoRA of their own)
const EXPORT_THUMBS = 6;  // pictures shown on each group's row
const PLAN_DELAY_MS = 150;  // a change waits this long, so typing a name asks once
const EXP = { ticked: new Set(), words: {}, how: "separate", timer: 0, asked: 0, plan: null, busy: false, ready: false };

function exportGroups() { return GROUPS.filter((g) => g.id >= 0); }  // map_group.js; not the unassigned

function groupsSeen() { return exportGroups().map((g) => `${g.id}:${g.size}`).join(","); }  // which groups the ticks mean
function exportKey() { return `${EXPORT_KEY}:${DATA.title || ""}:${N}`; }  // this folder's (by name and size)

function saveExportOptions() {
  const options = Object.fromEntries(EXPORT_FIELDS.map((id) => [id, $(id).value]));
  options.expTrig = $("expTrig").checked; options.expSpell = $("expSpell").checked;
  options.ticked = [...EXP.ticked]; options.words = EXP.words; options.how = EXP.how; options.groups = groupsSeen();
  try { localStorage.setItem(exportKey(), JSON.stringify(options)); } catch (e) { /* storage off */ }
}

// the folder opened again (or the page reloaded by an edit): the dialog comes back as it was.
// True when the ticks and trigger words came back too: after a regroup, merge or split the same
// numbers mean other groups, so those start afresh
function restoreExportOptions() {
  let options = null;
  try { options = JSON.parse(localStorage.getItem(exportKey()) || "null"); } catch (e) { return false; }
  if (!options) return false;
  EXPORT_FIELDS.forEach((id) => { if (typeof options[id] === "string") $(id).value = options[id]; });
  if (typeof options.expTrig === "boolean") $("expTrig").checked = options.expTrig;  // else the page's default (on)
  $("expSpell").checked = Boolean(options.expSpell);
  if (options.how === "one" || options.how === "separate") EXP.how = options.how;
  if (!Array.isArray(options.ticked) || options.groups !== groupsSeen()) return false;
  EXP.ticked = new Set(options.ticked);
  const words = options.words && typeof options.words === "object" ? options.words : {};
  EXP.words = Object.fromEntries(Object.entries(words).filter(([, w]) => typeof w === "string" && w.trim()));
  return true;
}

function defaultTicks() { EXP.ticked = new Set(exportGroups().filter((g) => g.size >= EXPORT_MIN).map((g) => g.id)); }

function openExport(only = null) {  // only: the groups to tick (the group view's "export this group")
  if (!EXP.ready) {  // the first time: the groups are listed by now (they are not when setupExport runs)
    EXP.ready = true;
    if (!restoreExportOptions()) defaultTicks();
  }
  if (only) EXP.ticked = new Set(only);
  $("morePanel").hidden = true; $("moreOpen").classList.remove("on");
  $("exportPanel").hidden = false; $("exportOpen").classList.add("on");
  buildExportList(); howShown(); replan(0);
  saveExportOptions();
}

function closeExport() { $("exportPanel").hidden = true; $("exportOpen").classList.remove("on"); }

function wordField(g) {  // the group's trigger word (and folder name): empty = made from the name
  const wrap = document.createElement("label"); wrap.className = "exp-word";
  const cap = document.createElement("span"); cap.textContent = t("lblWord");
  const field = document.createElement("input"); field.type = "text"; field.spellcheck = false; field.maxLength = 120;
  field.value = EXP.words[g.id] || ""; field.title = t("tipWord"); field.name = `word-${g.id}`;
  field.setAttribute("aria-label", `${t("lblWord")} · ${clusterName(g.id)}`);
  field.addEventListener("input", () => {
    if (field.value.trim()) EXP.words[g.id] = field.value; else delete EXP.words[g.id];
    saveExportOptions(); replan();
  });
  wrap.append(cap, field);
  return wrap;
}

function buildExportList() {
  const rows = exportGroups().map((g) => {
    const row = document.createElement("div"); row.className = "exp-row"; row.dataset.id = String(g.id);
    const pick = document.createElement("label"); pick.className = "exp-pick";
    const box = document.createElement("input"); box.type = "checkbox"; box.checked = EXP.ticked.has(g.id);
    const word = wordField(g);
    box.addEventListener("change", () => {
      if (box.checked) EXP.ticked.add(g.id); else EXP.ticked.delete(g.id);
      row.classList.toggle("on", box.checked); word.querySelector("input").disabled = !box.checked;
      saveExportOptions(); replan();
    });
    const pics = document.createElement("span"); pics.className = "exp-pics";
    typicalOrder(g.members).slice(0, EXPORT_THUMBS).forEach((i) => {  // map_group.js
      const img = document.createElement("img"); img.src = PTS[i].t; img.alt = ""; img.loading = "lazy"; pics.append(img);
    });
    const who = document.createElement("span"); who.className = "exp-who";
    const name = document.createElement("b"); name.textContent = clusterName(g.id); name.style.borderColor = colorOf(g.id);
    const meta = document.createElement("span"); meta.className = "exp-meta";
    who.append(name, meta);
    pick.append(box, pics, who);
    word.querySelector("input").disabled = !box.checked;
    row.append(pick, word);
    row.classList.toggle("on", box.checked);
    return row;
  });
  $("expList").replaceChildren(...rows);
  rowsShown();
}

function rowsShown() {  // each row: what of it trains and where it goes (from the plan), or "not exported"
  const byId = new Map(((EXP.plan && EXP.plan.groups) || []).map((r) => [r.id, r]));
  document.querySelectorAll("#expList .exp-row").forEach((row) => {
    const g = GROUPS.find((x) => x.id === Number(row.dataset.id));
    const meta = row.querySelector(".exp-meta"), r = byId.get(g.id), field = row.querySelector(".exp-word input");
    field.placeholder = r ? r.word : "";  // the automatic word while nothing is typed
    if (!EXP.ticked.has(g.id)) {
      meta.textContent = `${g.size} ${t("size")} · ${t(g.size < EXPORT_MIN ? "expRowSmall" : "expRowOut")}`;
      return;
    }
    if (!r) { meta.textContent = `${g.size} ${t("size")}`; return; }
    const where = [r.dataset, r.folder].filter(Boolean).join("\\");  // shown when it says more than the word beside it
    meta.textContent = t("expRowIn").replace("{k}", r.training) + (r.aside ? t("expRowAside").replace("{r}", r.aside) : "")
      + (where && where !== r.word ? ` → ${where}` : "");
  });
  const n = exportGroups().length;
  $("expPicked").textContent = t("expPicked").replace("{g}", EXP.ticked.size).replace("{n}", n);
}

function howShown() {
  document.querySelectorAll("#expHow button").forEach((b) => b.classList.toggle("on", b.dataset.how === EXP.how));
  $("expHowNote").textContent = t(EXP.how === "separate" ? "expHowSeparateNote" : "expHowOneNote");
  const kohya = $("expLayout").value === "kohya";  // repeats are a kohya folder's prefix
  $("expRep").hidden = !kohya; $("expRepLbl").hidden = !kohya;
}

function exportBody() {  // the dialog's choices, as the server reads them
  const cap = parseInt($("expMax").value, 10), rep = parseInt($("expRep").value, 10);
  const kohya = $("expLayout").value === "kohya";
  return { mode: "copy", layout: $("expLayout").value, name: $("expName").value.trim(),
    trigger: $("expTrig").checked, fix_spelling: $("expSpell").checked, max_per_group: cap > 0 ? cap : null,
    repeats: kohya && rep > 0 ? rep : null, strip_tags: $("expStrip").value.trim(),
    groups: [...EXP.ticked].sort((a, b) => a - b), separate: EXP.how === "separate", dest: $("expDest").value.trim(),
    words: Object.fromEntries(Object.entries(EXP.words).filter(([id, w]) => EXP.ticked.has(Number(id)) && w.trim())) };
}

function replan(delay = PLAN_DELAY_MS) {  // what the export would write, asked again after a change
  clearTimeout(EXP.timer);
  EXP.timer = setTimeout(async () => {
    const asked = ++EXP.asked;
    $("expPlan").classList.add("busy");  // the numbers shown are the last answer's until this one is in
    try {
      const r = await post("api/export_plan", JSON.stringify(exportBody()), "application/json");  // map_app.js
      if (asked !== EXP.asked) return;  // a newer question is on its way
      EXP.plan = r; $("expDest").placeholder = r.dest; $("expPlan").classList.remove("busy");
      rowsShown(); planShown(r);
    } catch (e) {
      if (asked !== EXP.asked) return;
      EXP.plan = null; rowsShown(); planError(String(e.message || e)); $("expPlan").classList.remove("busy");
    }
  }, delay);
}

function planError(text) {
  const p = document.createElement("p"); p.className = "exp-error"; p.textContent = text;
  $("expPlan").replaceChildren(p);
  $("export").disabled = true; $("export").textContent = t("exportGo");
}

function listJoin(items) { return items.join(lang === "zh" ? "、" : ", "); }

function planShown(r) {  // the summary beside the button: the sets, where, and what is set aside
  const box = document.createElement("div"); box.className = "exp-sum";
  const sets = r.datasets.filter((d) => d.training > 0);
  const head = document.createElement("b");
  head.textContent = EXP.ticked.size ? t("expSumSets").replace("{s}", sets.length).replace("{k}", r.training) : t("expNoneTicked");
  box.append(head);
  if (sets.length) {
    const shown = sets.slice(0, 6).map((d) => d.name + paren(d.training));  // map.js
    const names = document.createElement("div"); names.className = "exp-sets";
    names.textContent = listJoin(sets.length > 6 ? [...shown, "…"] : shown);
    const where = document.createElement("div"); where.className = "kv"; where.textContent = t("expWhere").replace("{f}", r.dest);
    box.append(names, where);
  }
  box.append(notesList(planNotes(r)));
  $("expPlan").replaceChildren(box);
  const go = $("export");
  go.disabled = !r.training || EXP.busy;
  go.textContent = r.training ? t("expGoN").replace("{k}", r.training) : t("exportGo");
}

function planNotes(r) {  // the lines under the summary, before and after an export
  const aside = r.rows.filter((row) => !row.training).reduce((s, row) => s + row.images, 0);
  const one = r.datasets.length === 1;
  return [
    aside > 0 && t("expSumAside").replace("{r}", aside),
    r.small_groups && t("smallGroups").replace("{n}", r.small_groups).replace("{g}", listJoin(r.small_ids.map(clusterName))),
    one && r.steps && t("stepsNote").replace("{n}", r.steps) + (exportBody().repeats ? "" : " " + t("repeatsNote")),
    r.triggers.length && t("triggersNote").replace("{w}", listJoin(r.triggers.slice(0, 8)) + (r.triggers.length > 8 ? " …" : "")),
    r.triggers.some((w) => /[^\x00-\x7f]/.test(w)) && t("nonAsciiTrigger"),
  ].filter(Boolean);
}

function notesList(lines) {
  const list = document.createElement("ul"); list.className = "notes";
  lines.forEach((text) => { const li = document.createElement("li"); li.textContent = text; list.append(li); });
  return list;
}

function exportDone(r) {  // after an export: what was written, where, and a way to open it
  const box = document.createElement("div"); box.className = "exp-sum done";
  const head = document.createElement("b");
  const aside = r.placed - r.training;  // duplicates, exclusions, trimmed: in the _ folders
  head.textContent = t("exportedHead").replace("{k}", r.training) + (aside > 0 ? t("exportedAside").replace("{r}", aside) : "");
  const where = document.createElement("div"); where.className = "kv"; where.textContent = t("expWhere").replace("{f}", r.folder);
  const open = document.createElement("button"); open.textContent = t("openFolder"); open.className = "primary";
  open.addEventListener("click", () => post("api/open_export", "{}", "application/json").catch((e) => setStatus(String(e.message || e))));
  const notes = [
    r.failed && t("expFailed").replace("{n}", r.failed),
    r.trimmed && t("trimmedNote").replace("{n}", r.trimmed),
    r.small_training && t("smallTraining").replace("{n}", r.small_training),
    r.upright && t("uprightNote").replace("{n}", r.upright),
    r.respelt && r.respelt.length && t("respeltNote").replace("{w}", r.respelt.join(", ")),
    r.config && t("configWritten"),
  ].filter(Boolean);
  box.append(head, where, open, notesList(notes));
  return box;
}

async function runExport() {
  EXP.busy = true; $("export").disabled = true; $("export").textContent = t("exporting");
  try {
    const r = await post("api/export", JSON.stringify(exportBody()), "application/json");
    setStatus(t("exportedHead").replace("{k}", r.training)); markStep("export");  // map_browse.js
    $("expPlan").replaceChildren(exportDone(r));
    $("export").textContent = t("exportAgain");
  } catch (e) { planError(String(e.message || e)); }
  finally { EXP.busy = false; $("export").disabled = false; }
}

async function chooseDest() {  // the desktop program's folder dialog
  const api = desktopApi();  // map_shell.js
  if (!api || !api.choose_folder) return;
  const r = await api.choose_folder($("expDest").value.trim() || (EXP.plan && EXP.plan.dest) || "");
  if (r && r.path) { $("expDest").value = r.path; saveExportOptions(); replan(0); }
}

function setupExport() {
  const changed = () => { saveExportOptions(); howShown(); replan(); };
  [...EXPORT_FIELDS, "expTrig", "expSpell"].forEach((id) => {
    $(id).addEventListener("change", changed); $(id).addEventListener("input", changed);
  });
  document.querySelectorAll("#expHow button").forEach((b) => b.addEventListener("click", () => { EXP.how = b.dataset.how; changed(); }));
  $("expAll").addEventListener("click", () => { EXP.ticked = new Set(exportGroups().map((g) => g.id)); buildExportList(); saveExportOptions(); replan(0); });
  $("expNone").addEventListener("click", () => { EXP.ticked = new Set(); buildExportList(); saveExportOptions(); replan(0); });
  $("exportOpen").addEventListener("click", () => ($("exportPanel").hidden ? openExport() : closeExport()));
  $("exportClose").addEventListener("click", closeExport);
  $("exportPanel").addEventListener("click", (e) => { if (e.target === $("exportPanel")) closeExport(); });  // the dim around it
  $("export").addEventListener("click", runExport);
  $("expPick").addEventListener("click", () => chooseDest().catch((e) => setStatus(String(e.message || e))));
  const pickShown = () => { $("expPick").hidden = !(desktopApi() && desktopApi().choose_folder); };
  pickShown(); window.addEventListener("pywebviewready", pickShown);
}

function exportText() {
  $("exportTitle").textContent = t("exportTitle"); $("exportWhere").textContent = t("exportWhere");
  $("exportOpen").textContent = t("exportOpen"); $("export").textContent = t("exportGo");
  $("expAll").textContent = t("expAll"); $("expNone").textContent = t("expNone");
  document.querySelectorAll("#expHow button").forEach((b) => { b.textContent = t(b.dataset.how === "separate" ? "expHowSeparate" : "expHowOne"); });
  $("expLayoutLbl").textContent = t("lblLayout"); $("expMoreLbl").textContent = t("moreOptions");
  $("expLayout").options[0].textContent = t("plainFolders"); $("expLayout").options[1].textContent = t("kohyaFolders");
  $("expName").placeholder = DATA.title || t("conceptName");
  $("expNameLbl").textContent = t("lblName"); $("expDestLbl").textContent = t("lblDest"); $("expPick").textContent = t("expPick");
  $("expMax").placeholder = t("maxPerGroup"); $("expStrip").placeholder = t("stripTags");
  $("expMaxLbl").textContent = t("lblMax"); $("expStripLbl").textContent = t("lblStrip");
  $("expRepLbl").textContent = t("lblRepeats"); $("expRep").placeholder = t("repeatsAuto"); $("expRep").title = t("repeatsTip");
  $("expTrigWrap").querySelector("span").textContent = t("triggerCaptions");
  document.querySelectorAll("#expList .exp-word").forEach((w) => {
    w.querySelector("span").textContent = t("lblWord"); w.querySelector("input").title = t("tipWord");
  });
  $("expSpellWrap").querySelector("span").textContent = t("fixSpelling");
  const tips = { exportOpen: "tipExport", expMax: "tipMax", expStrip: "tipStrip", expLayout: "tipLayout", expName: "tipName",
    expTrigWrap: "tipTrig", expSpellWrap: "tipSpell", export: "tipExport", expDest: "tipDest" };
  Object.entries(tips).forEach(([id, key]) => { $(id).title = t(key); });
  if (!$("exportPanel").hidden) { howShown(); rowsShown(); if (EXP.plan) planShown(EXP.plan); }
}
