import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const DATA = JSON.parse(document.getElementById("atlas-data").textContent);
const PTS = DATA.points;
const N = PTS.length;
const T = {
  en: { images: "images", clusters: "Styles", selected: "Selected", outliers: "Outliers", checkTab: "Check",
    find: "filter by file name", thumbs: "Thumbnails", dots: "Dots", spin: "Rotate", home: "Reset", names: "Names", rec: "Record a turn", recording: "recording {s}s",
    recNo: "This browser cannot record video", recHidden: "Recording stopped: keep this tab in front while it records", tipRec: "Record one turn of the map as a video to share (MP4, or WebM)",
    unassigned: "Unassigned", style: "Style", size: "images", cohesion: "spread",
    pick: "Click an image in the map to see its closest styles.", nearest: "Closest styles",
    members: "Members", cluster: "style", outlierHelp: "Images least like the rest of the set (candidates to drop from a LoRA dataset).",
    loading: "building map…", open: "open file", searchImg: "Search by image…",
    drop: "Drop one image, or several of one style, to find the closest styles", regroup: "Regroup", export: "Export folders",
    searching: "embedding the query…", exported: "Copied {n} images to {f}.", saveMap: "Save shareable map", openFolder: "Open folder",
    configWritten: "dataset_config.toml for kohya sd-scripts is in the same folder.", savingMap: "writing the map…",
    savedMap: "Saved {f}. The thumbnails are inside it: send this one file to share the map (and the thumbnails).", query: "Your image", queries: "Your {n} images, searched as one style",
    custom: "custom", regrouping: "regrouping…", period: "period (one artist)", periods: "number of periods",
    keys: "Shortcuts (?)", drag: "drag", wheel: "wheel", sizeKeys: "Alt+wheel, + -", keyRotate: "turn the map",
    keyZoom: "zoom", keySize: "bigger / smaller pictures", keyHome: "back to the whole map",
    keyVote: "like / dislike the selected image", keyExclude: "exclude it from exports",
    keyUndo: "undo the last edit", periodsN: "{n} periods",
    forcedN: "{n} groups (set)", autoCut: "auto cut {t}", cut: "cut {t}", dups: "Duplicates",
    dupHelp: "Groups of near-identical pictures (same image, crops, frames of one scene). Keep one per group for LoRA training.",
    noDups: "No near-duplicates found.",
    moveTo: "Move to group…", mergeInto: "Merge this group into…", splitGroup: "Split in two", edited: "edited by hand",
    moreLike: "Find more like this", moreLikeTitle: "Outside {g}, most like it (click one to move it)",
    exclude: "Exclude from export (X)", included: "Excluded - undo (X)",
    excludedList: "Excluded by you ({n}) - exported to _excluded",
    compareWith: "Compare with…", compareTitle: "{a} compared with {b}",
    firstHint: "Start here: click a style on the right to see its images · the Check tab checks the dataset · ? lists every shortcut",
    refPath: "reference folder (styles you know)", refLoad: "Load reference", refClear: "Clear reference",
    refBusy: "loading the reference… the first time, every image in it is embedded (minutes)",
    tipRef: "A folder of styles you already know (artists, recipes): the measures layout gets an originality axis, the distance to the closest one",
    tipSearch: "Pick one or more images (or drop them on the map) to find this style in the folder",
    tipGran: "How finely to split: auto picks a cut from the images; period splits one artist into N parts",
    tipThr: "The cut used by Regroup: lower = more, smaller groups",
    tipRegroup: "Group again with the setting on the left (Undo goes back)", tipUndo: "Undo the last edit or regroup (Ctrl+Z)",
    tipLayout: "Export as plain folders, or as kohya folders (10_name_style01) with dataset_config.toml",
    tipName: "Name used in the exported folders and trigger words", tipTrig: "Start every exported caption with its group's trigger word",
    tipExport: "Copy the groups into a new folder next to this one (your files are never moved)",
    tipSaveMap: "Save this map as one HTML file you can send to anyone",
    tipNeutral: "When the same characters appear in many styles: compare styles as if all were the same character",
    tipMode: "Show thumbnails or coloured dots", tipNames: "Show or hide the group names on the map",
    tipHome: "Back to the whole map (Esc)", tipLayoutSel: "Arrange by style similarity, or by measures on three axes",
    checkTitle: "Dataset check", minSide: "short side < {n} px", checkRun: "Check", checking: "checking…",
    checkClean: "No problems found.", checkAll: "all {n} images", outliersTitle: "Least like the rest",
    chk_smaller_than_min_side: "Short side under {n} px", chk_extreme_aspect_ratio: "Extreme aspect ratio",
    chk_greyscale_in_colour_set: "Greyscale in a colour set (sketches, comic pages?)",
    chk_no_caption: "No caption file", chk_empty_caption: "Empty caption",
    chk_animated: "Animated (only the first frame is used)", chk_truncated: "Truncated file",
    chk_unreadable: "Cannot be opened (moved, deleted or damaged since the scan?)",
    cmpDistance: "Style distance", cmpP: "Chance that the difference is noise",
    cmpLook: "How {b} looks next to {a}", cmpLookSame: "about the same look",
    v_same: "same style", v_related: "related", v_different: "clearly different",
    cmpNote: "Distance in z: one person's calibration on fixed-content renders (z >= 2.3 looked clearly different, z < 1.5 the same). Groups the tool split are usually clearly different; the size and the look are what to read.",
    moreLikeThese: "Find more like these", moreLikeTheseHelp: "Strays by another artist: exclude two or three, then find the rest",
    moreLikeExcluded: "Most like the images you excluded (click one, then X to exclude it)",
    layoutStyle: "Layout: style similarity", layoutMeasures: "Layout: measures",
    m_map: "(map position)", m_taste: "taste p(like)", m_ref: "distance to reference (originality)",
    m_time: "time", m_outlier: "atypical (outlier)",
    m_brightness: "brightness", m_contrast: "contrast", m_colourfulness: "colourfulness",
    m_warmth: "warmth (cool to warm)", m_lines: "line work", m_flatness: "flat colour",
    w_brightness: ["brighter", "darker"], w_contrast: ["more contrast", "less contrast"],
    w_colourfulness: ["more colourful", "less colourful"], w_warmth: ["warmer", "cooler"],
    w_lines: ["more line work", "less line work"], w_flatness: ["flatter colour", "more texture"],
    lookAverage: "average look", lookTitle: "Look compared with the whole folder (image statistics)",
    pathFrom: "Style path: start here", pathTo: "Style path: end here",
    pathTitle: "Style path (from the start image to this one)",
    neutral: "Ignore the character axis", neutralBusy: "recomputing…",
    oneGroup: "Everything landed in one group: pick 'fine' or 'period (one artist)' in the grouping menu (bottom left), then Regroup.",
    undo: "Undo", plainFolders: "plain folders",
    smallGroups: "{n} group(s) with fewer than 3 images went to unassigned.", conceptName: "concept name", triggerCaptions: "trigger in captions",
    nameGroup: "name (Enter)", restored: "Groups, hand edits and names restored from your last session (Regroup to start over).",
    rateNext: "Rate the most useful next image", ratingHint: "Rating mode: press L or D, the next image follows (Esc stops)",
    allRated: "Every image is rated.",
    taste: "Taste", like: "Like (L)", dislike: "Dislike (D)", clearVote: "Clear",
    tasteHelp: "Rate images with Like / Dislike (select one on the map, then press L or D). After {n} of each, a model learns your taste from the style vectors and ranks the unrated images.",
    tasteCount: "liked {a} · disliked {b}", tasteAuc: "cross-validated AUC {x} (0.5 = guessing). Treat it as a rough filter: it separates liked from disliked, not good from better.",
    tasteTop: "Most likely to like (unrated)", tasteBottom: "Least likely (unrated)", fine: "fine", medium: "medium", coarse: "coarse", auto: "auto (picked from the images)", foot: "Style vectors: CSD ViT-L (Somepalli et al. 2024, CC-BY-4.0). Map layout is for viewing only; groups are computed in the full space." },
  zh: { images: "張圖", clusters: "畫風群", selected: "選取", outliers: "離群", checkTab: "檢查",
    find: "以檔名篩選", thumbs: "縮圖", dots: "圓點", spin: "旋轉", home: "重置", names: "群名", rec: "錄一圈", recording: "錄影中 {s} 秒",
    recNo: "這個瀏覽器不支援錄影", recHidden: "錄影中斷：錄影時請讓這個分頁保持在最前面", tipRec: "把地圖轉一圈錄成影片（MP4 或 WebM），可以直接分享",
    unassigned: "未歸類", style: "畫風", size: "張", cohesion: "分散度",
    pick: "在地圖上點一張圖，看最接近的畫風。", nearest: "最接近的畫風", members: "成員",
    cluster: "畫風群", outlierHelp: "和整組最不像的圖（訓 LoRA 前可考慮剔除）。",
    loading: "建立地圖中…", open: "開啟檔案", searchImg: "以圖搜尋…",
    drop: "放開一張圖，或同一種畫風的多張圖，找最接近的畫風", regroup: "重新分群", export: "匯出資料夾",
    searching: "計算查詢圖中…", exported: "已複製 {n} 張到 {f}。", saveMap: "存成分享用地圖", openFolder: "打開資料夾",
    configWritten: "同一個資料夾裡也寫了 kohya sd-scripts 用的 dataset_config.toml。", savingMap: "寫入地圖中…",
    savedMap: "已存成 {f}。縮圖已內嵌在檔案裡，把這一個檔案傳給別人就能看（也等於分享了這些縮圖）。", query: "你的圖", queries: "你的 {n} 張圖（當成同一種畫風搜尋）",
    custom: "自訂", regrouping: "重新分群中…", period: "時期（單一畫師）", periods: "分成幾段",
    keys: "快捷鍵（?）", drag: "拖曳", wheel: "滾輪", sizeKeys: "Alt+滾輪、+ -", keyRotate: "轉動地圖",
    keyZoom: "縮放", keySize: "圖片放大／縮小", keyHome: "回到整張地圖",
    keyVote: "喜歡／不喜歡選取的圖", keyExclude: "匯出時排除這張",
    keyUndo: "復原上一個修改", periodsN: "分成 {n} 個時期",
    forcedN: "指定 {n} 群", autoCut: "自動門檻 {t}", cut: "門檻 {t}", dups: "重複",
    dupHelp: "幾乎相同的圖（同一張、裁切、同場景連續畫面）。訓 LoRA 時每組留一張即可。",
    noDups: "沒有找到近重複的圖。",
    moveTo: "移到其他群…", mergeInto: "把這群合併到…", splitGroup: "拆成兩群", edited: "已手動調整",
    moreLike: "找更多像這群的", moreLikeTitle: "不在「{g}」裡、但最像它的圖（點一張可移進來）",
    exclude: "匯出時排除 (X)", included: "已排除，取消 (X)",
    excludedList: "你排除的圖（{n}）：匯出時放到 _excluded",
    compareWith: "和…比較", compareTitle: "{a} 和 {b} 比較",
    firstHint: "從這裡開始：點右側的畫風群看成員 ·「檢查」分頁可以檢查資料集 · 按 ? 看所有操作",
    refPath: "參考資料夾（已知畫風）", refLoad: "載入參考", refClear: "清除參考",
    refBusy: "載入參考資料夾中…第一次會嵌入裡面的每張圖，可能要幾分鐘",
    tipRef: "放已知畫風（畫師作品、配方）的資料夾：量化軸會多一個「離參考集距離（原創度）」",
    tipSearch: "選一張或幾張圖（也可以直接拖到地圖上），在這個資料夾裡找同樣畫風的圖",
    tipGran: "分得多細：自動會依圖片決定；時期會把同一位畫師分成幾段",
    tipThr: "重新分群用的門檻：越小，群越多、越小",
    tipRegroup: "用左邊的設定重新分群（可以按復原回去）", tipUndo: "復原上一個修改或分群（Ctrl+Z）",
    tipLayout: "匯出成一般資料夾，或 kohya 格式（10_名稱_style01）並附 dataset_config.toml",
    tipName: "匯出的資料夾名稱和觸發詞會用這個名字", tipTrig: "匯出的每個標註開頭加上該群的觸發詞",
    tipExport: "把各群複製到這個資料夾旁邊的新資料夾（原始檔案不會被移動）",
    tipSaveMap: "把這張地圖存成單一 HTML 檔，可以直接傳給別人",
    tipNeutral: "同樣的角色出現在很多畫風時勾選：比較畫風時當作都是同一個角色",
    tipMode: "切換縮圖或圓點", tipNames: "顯示或隱藏地圖上的群名",
    tipHome: "回到整張地圖（Esc）", tipLayoutSel: "依畫風相似排列，或依三個量化軸排列",
    checkTitle: "資料集檢查", minSide: "短邊 < {n} px", checkRun: "開始檢查", checking: "檢查中…",
    checkClean: "沒有發現問題。", checkAll: "全部 {n} 張", outliersTitle: "最不合群的圖",
    chk_smaller_than_min_side: "短邊小於 {n} px", chk_extreme_aspect_ratio: "長寬比極端",
    chk_greyscale_in_colour_set: "混在彩色圖裡的黑白圖（草稿、漫畫頁？）",
    chk_no_caption: "沒有標註檔", chk_empty_caption: "標註是空的",
    chk_animated: "動圖（只看第一格）", chk_truncated: "檔案不完整",
    chk_unreadable: "無法開啟（掃描後被移動、刪除或損壞？）",
    cmpDistance: "畫風距離", cmpP: "差異只是雜訊的機率",
    cmpLook: "{b} 和 {a} 相比的外觀", cmpLookSame: "外觀差不多",
    v_same: "同一畫風", v_related: "相近", v_different: "明顯不同",
    cmpNote: "z 是以一位使用者在固定內容算圖上的校準為尺度（z ≥ 2.3 看起來明顯不同，z < 1.5 看起來相同）。工具分出來的群通常都會「明顯不同」，重點是距離大小與外觀差異。",
    moreLikeThese: "找更多像這些的", moreLikeTheseHelp: "混進來的別人的圖：先排除兩三張，再用這個找出其餘的",
    moreLikeExcluded: "最像你排除的圖（點一張，再按 X 排除）",
    layoutStyle: "版面：畫風相似", layoutMeasures: "版面：量化軸",
    m_map: "（地圖位置）", m_taste: "口味分數", m_ref: "離參考集距離（原創度）",
    m_time: "時間", m_outlier: "離群度",
    m_brightness: "亮度", m_contrast: "對比", m_colourfulness: "鮮豔度",
    m_warmth: "冷暖（冷到暖）", m_lines: "線條量", m_flatness: "平塗度",
    w_brightness: ["偏亮", "偏暗"], w_contrast: ["對比強", "對比弱"],
    w_colourfulness: ["色彩鮮豔", "色彩淡"], w_warmth: ["偏暖", "偏冷"],
    w_lines: ["線條多", "線條少"], w_flatness: ["色塊平", "質感多"],
    lookAverage: "外觀接近平均", lookTitle: "和整個資料夾相比的外觀（影像統計）",
    pathFrom: "畫風漸變：從這張開始", pathTo: "畫風漸變：到這張",
    pathTitle: "畫風漸變（從起點到這張）",
    neutral: "忽略角色軸", neutralBusy: "重新計算中…",
    oneGroup: "所有圖都在同一群：把左下的分群選單改成「細」或「時期（單一畫師）」，再按重新分群。",
    undo: "復原", plainFolders: "一般資料夾",
    smallGroups: "有 {n} 個群不足 3 張，已放進未分群。", conceptName: "概念名稱", triggerCaptions: "標註加觸發詞",
    nameGroup: "取名（Enter）", restored: "已還原上次的分群、手動調整與名稱（按重新分群可重來）。",
    rateNext: "評下一張最有用的圖", ratingHint: "評分模式：按 L 或 D，自動跳下一張（Esc 結束）",
    allRated: "全部都評過了。",
    taste: "口味", like: "喜歡 (L)", dislike: "不喜歡 (D)", clearVote: "清除",
    tasteHelp: "在地圖上選一張圖，按喜歡或不喜歡（鍵盤 L / D）。兩種各滿 {n} 張後，模型會用畫風向量學你的口味，替還沒評的圖排序。",
    tasteCount: "喜歡 {a} · 不喜歡 {b}", tasteAuc: "交叉驗證 AUC {x}（0.5 = 亂猜）。只適合粗篩：分得出喜歡和不喜歡，分不出好和更好。",
    tasteTop: "最可能喜歡（未評分）", tasteBottom: "最不可能喜歡（未評分）", fine: "細", medium: "中", coarse: "粗", auto: "自動（依圖片決定）", foot: "風格向量：CSD ViT-L（Somepalli 等，2024，CC-BY-4.0）。地圖排版只供瀏覽，分群是在完整向量空間計算。" },
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
  const named = ((DATA.live && DATA.live.names) || DATA.names || {})[String(c)];
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
    if (c.tags && c.tags.length) {
      const tg = document.createElement("div"); tg.className = "meta tags"; tg.textContent = c.tags.join(", ");
      txt.append(tg);
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
  $("find").placeholder = t("find");
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
  if (DATA.live && DATA.clusters.length <= 1 && N > 10) setStatus(t("oneGroup"));
  else if (DATA.live && DATA.live.restored && !$("status").textContent) setStatus(t("restored"));
  else if (DATA.live && !DATA.live.restored && !$("status").textContent) setStatus(t("firstHint"));
  setupAxes(); if (layoutMode === "measures") drawAxes();
  drawNames();
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
    ["Esc", "keyHome"], ...(DATA.live ? [["L / D", "keyVote"], ["X", "keyExclude"], ["Ctrl + Z", "keyUndo"]] : [])];
  box.replaceChildren(...rows.map(([key, what]) => {
    const line = document.createElement("div");
    const b = document.createElement("b"); b.textContent = ["drag", "wheel", "sizeKeys"].includes(key) ? t(key) : key;
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
  if (e.key === "Escape") { RATING = false; PATH_FROM = null; setStatus(""); showHelp(false); $("home").click(); }
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
