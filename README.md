# style-atlas

**量化、聚類、搜尋與視覺化插畫畫風。全部在本機運算。**
Measure, cluster, search and map illustration art styles, entirely on your machine.

[繁體中文](#繁體中文) · [English](#english)

---

## 繁體中文

style-atlas 會用 CSD 風格嵌入模型，把每張圖轉成一個「畫風向量」。這個模型學的是「怎麼畫」，不是「畫了什麼」。有了這些向量，可以做下面幾件事：

| 你想做的事 | 怎麼做 |
|---|---|
| **訓 LoRA 前整理資料集**：分出不同畫風或時期，排除重複圖與離群圖，匯出成 kohya 資料夾 | `cluster --layout kohya --dedupe` |
| **找畫風相近的圖** | 網頁介面拖圖進去，或用 `search` |
| **3D 畫風地圖**：縮圖浮在 3D 空間，可轉動，點一下就看最接近的畫風 | `map`（單一 HTML 檔，可直接傳給朋友） |
| **檢查資料集**：解析度、極端比例、缺標註、近重複 | `audit`、`duplicates` |
| **量化畫風與口味**：兩組圖是否同一畫風、個人喜好模型 | `compare`、`taste`、網頁介面的「喜歡／不喜歡」 |

### Windows：三步開始

1. 安裝 [Python 3.10 以上](https://www.python.org/downloads/)，安裝時勾選「Add python.exe to PATH」。
2. 下載本專案：在 GitHub 頁面按 **Code → Download ZIP** 再解壓縮（本專案目前是私人專案，要先請作者給你存取權），會用 git 的話也可以 `git clone`。然後雙擊 `scripts\setup.bat`。它會在專案資料夾裡建立 `.venv`，偵測到 NVIDIA 顯卡就裝 CUDA 版的 torch，沒有就裝 CPU 版，再安裝本工具。
3. 把圖片資料夾**拖到 `scripts\StyleAtlas.bat` 上**，瀏覽器會打開網頁介面。

**要打指令時**（下面的 `audit`、`cluster`、`search` 等），請雙擊 `scripts\StyleAtlas-console.bat`，它會開一個已經設定好的命令視窗，在裡面輸入指令即可。直接開一般的命令提示字元打 `style-atlas` 會出現「不是內部或外部命令」，因為工具裝在 `.venv` 裡。

不確定環境有沒有裝好時，可以在這個視窗執行 `style-atlas doctor`，它會檢查 Python、torch、有沒有抓到顯卡、模型是否已下載、磁碟空間。

**第一次使用會遇到的事**
- 開著網頁介面時，**不要關掉黑色的命令視窗**，關掉網頁就停了。瀏覽器沒自動打開的話，手動開 `http://127.0.0.1:8770`（埠號被占用時會往後找，以視窗裡印出的網址為準）。
- 標註檔請放在圖片旁邊、同檔名的 `.txt`（例如 `001.png` 配 `001.txt`），匯出時會一起複製。子資料夾裡的圖也會一起讀進來，不要的話加 `--no-recursive`。
- 建議先拿 100 張左右的資料夾試一次，熟悉流程後再跑大量的圖。

**幾個名詞**
- **kohya 格式**：kohya_ss／sd-scripts 訓 LoRA 用的資料夾結構，資料夾名稱像 `10_artistX_style01`，開頭的數字是 repeats。
- **repeats**：每個 epoch 裡這個資料夾的圖要重複幾次。張數少的群 repeats 高一點，各群的份量就會接近。
- **觸發詞（trigger word）**：寫在標註最前面的詞，訓練後在提示詞裡寫它就能叫出這種畫風。

**第一次分析前**，程式會從 Hugging Face 下載 CSD 模型。下載量 2.4 GB，之後另存成 1.2 GB 的精簡檔，存在 `%USERPROFILE%\.cache\style-atlas`，只會下載一次。同一個資料夾也存放向量與縮圖快取（每張圖約幾 KB），刪掉不影響原始檔案，之後會重新產生。下載時畫面可能停很久，這是正常的。

速度參考：只用 CPU 時，8 執行緒約每秒 4 張，1,000 張約 4 分鐘（實測）。有 NVIDIA 顯卡通常會快很多，但這點沒有實測過。每張圖的向量都會快取，第二次開同一個資料夾就不用重算向量。

### 手動安裝

```bash
git clone https://github.com/Rinne414/style-atlas
cd style-atlas
pip install -e .            # 有 NVIDIA 顯卡時，請先依 pytorch.org 裝好 CUDA 版 torch
pip install -e ".[umap]"    # 選用：地圖改用 UMAP 版面
```

### 訓 LoRA 前的建議流程

```bash
# 1. 檢查：太小的圖、極端長寬比、動圖、缺標註或標註是空的
style-atlas audit "D:\lora\artistX" --min-side 768

# 2. 在網頁介面先看一遍：哪些是重複圖（「重複」分頁）、哪些離群（「離群」分頁），分群是否合理
style-atlas serve "D:\lora\artistX" --time name

# 3. 匯出成 kohya 資料夾。步驟依序是：
#    先排除重複圖（每組留解析度最高、有標註的那張）
#    再分群，並另外放出最不合群的 5 張
#    最後依每群張數自動算 repeats
style-atlas cluster "D:\lora\artistX" --layout kohya --name artistX --dedupe --drop-outliers 5 --export copy
```

匯出結果在資料集旁邊的 `D:\lora\artistX_style_atlas\folders\`，不會寫進原本的資料夾：

```
11_artistX_style01\   ← 一種畫風，標註 .txt 會一起複製
20_artistX_style02\
_duplicates\          ← 沒有數字前綴，kohya 會忽略
_outliers\
_unassigned\
_excluded\            ← 在網頁介面按 X 排除的圖
```

- 每群的 repeats 會讓「張數 × repeats」接近 100。也可以用 `--repeats 10` 固定。
- 想在同一個 LoRA 裡用不同觸發詞叫出不同畫風，可以加 `--trigger-captions`：
  - 匯出的標註開頭會自動加上該群名稱，例如 `artistX_style01, `；
  - 原始標註不會被改。
  - 完整流程見 [docs/LORA_GUIDE.md](docs/LORA_GUIDE.md)。
- `clusters.json` 會列出每群最常見的標註 tag，以及 tag 在這群裡比整體多出幾倍。例如某群特別多 `monochrome`、`sketch`，大概就是草稿那一群。
- 原始檔案永遠不會被移動或刪除。每次匯出都寫到新的資料夾（`folders`、`folders_2` …），不會和上一次混在一起。
- `--export link` 改用硬連結，不佔額外空間，但連結檔和原檔是**同一個檔案**，在匯出資料夾裡改標註，原本的也會一起改。不確定的話就用 `copy`。

**要把同一位畫師的作品分成不同時期**，請用 `--granularity period`（門檻 0.35），並加上 `--time name` 看時間分佈。預設是 `auto`：依圖片自動挑門檻（最多到 medium 的 0.47）。畫師越多、最佳門檻越低，固定的 medium 在幾十位畫師混在一起時會把很多人併成少數幾個大群，auto 在 50～300 位畫師時的 ARI 比 medium 高 0.13～0.18，少數畫師時兩者差不多。其他選擇：`fine`／`medium`／`coarse`，或用 `--k 3` 直接指定群數。網頁介面裡也能選「自動」或調門檻，再按「重新分群」。

### 其他用法

```bash
style-atlas search ref1.png ref2.png --combine --in "D:\gallery" --top 30   # 以圖找圖
style-atlas search "D:\examples" --combine --in "D:\gallery" --top 100 --copy-to "D:\lora\more"  # 擴充訓練集
style-atlas map "D:\gallery" -o gallery_map.html     # 單一 HTML 3D 地圖，離線可開
style-atlas duplicates "D:\gallery"                  # 近重複圖分組
style-atlas outliers "D:\lora\artistX" --top 20      # 最不合群的圖
style-atlas compare "D:\old_works" "D:\new_works"    # 兩組圖是否同一畫風（距離、p 值）
style-atlas taste score "D:\new_batch" --model "D:\lora\artistX_style_atlas\taste_model.npz"
```

**用幾張範例圖找更多同風格的圖**（例如擴充 LoRA 訓練集）：把範例放進一個資料夾，用 `--combine` 搜尋，再用 `--copy-to` 把結果連同標註複製出來。範例有 3 張以上時，會用範例對圖庫訓練一個小模型來排序，比單純取範例的平均向量準：在 3,689 張的圖庫裡找 13 位畫師的其他作品，平均精確度在 3／5／10 張範例時分別高 0.055／0.066／0.116。

**同樣的角色出現在很多種畫風裡**時（例如用固定角色測試不同畫師組合），請加 `--neutralize 1`，或在網頁介面勾選「忽略角色軸」。CSD 的畫風向量仍會被角色外觀（髮色、服裝）強烈拉扯。在 96 種畫風 × 2 個角色的 NovelAI 算圖上：
- 不加時，最接近的圖 89% 是「同角色、別的畫風」。
- 加了之後，同畫風配對的 AUC 從 0.83 提高到 0.98。

但**混合不同畫師時不要用**：那時最主要的差異就是畫風本身，移除後分群會壞掉。

`--time name` 會從檔名裡的 Pixiv／Danbooru 作品編號推出先後順序（編號會隨上傳時間遞增），`--time mtime` 則用檔案修改時間。開了之後，每個畫風群旁都會畫出時間分佈，可以看出哪種畫風是早期、哪種是近期。

支援 png、jpg、webp、bmp、gif；avif 需要 Pillow 本身支援。動圖只看第一格。CPU 預設最多用 8 個執行緒並降低優先權，不會拖垮整台電腦；`--threads 0` 可取消限制。

### 網頁介面與 3D 地圖

- 縮圖浮在 3D 空間中，外框顏色代表畫風群。可以拖曳旋轉、滾輪縮放，`+` / `-` 調整縮圖大小。
- 點右側的畫風群，鏡頭會飛過去並列出成員。點地圖上任一張圖，會列出最接近的 12 張。
- 「離群」「重複」分頁分別列出最不合群的圖和近重複圖組。
- 右上角可以把「版面」從「畫風相似」切到「量化軸」。切換後，三個軸可以各自選一種指標，縮圖會移動到對應位置。可選的指標有：
  - 口味分數：用網頁介面評過分之後才有。
  - 離參考集距離（原創度）：要先用 `--reference 資料夾` 指定已知的畫風，例如畫師作品或論壇配方。
  - 時間。
  - 離群度。
- 只有網頁介面才有的功能：
  - 拖一張圖進畫面就能以圖搜尋。一次拖多張同一種畫風的圖，會當成同一種畫風一起搜尋（3 張以上時用它們訓練的小模型排序）。
  - 畫風漸變：選一張圖按「畫風漸變：從這張開始」，再選另一張按「畫風漸變：到這張」，會列出在畫風上從前一張漸變到後一張的一串圖。適合找兩種畫風之間的過渡風格。
  - 調門檻後重新分群、一鍵匯出資料夾。匯出時可以選一般資料夾或 kohya 格式、填概念名稱、勾選「標註加觸發詞」。
  - 按「匯出時排除」（鍵盤 X）手動剔除不要的圖，清單會存檔，匯出時放到 `_excluded\`。
  - 手動修正分群，修正會反映在之後的匯出：
    - 選取一張圖，用「移到其他群…」把它改放到別群；
    - 打開一個群，用「把這群合併到…」併進另一群，或按「拆成兩群」。
    - 打開一個群按「找更多像這群的」，會列出不在這群裡、但最像它的圖（用這群的圖訓練的小模型排序），方便把被分錯或沒分到的圖找回來。
    - 打開一個群，在「取名」欄輸入名字並按 Enter，例如「早期」「線稿期」。匯出時資料夾與觸發詞會用這個名字，像是 `10_artistX_早期`。
    - 修正、名稱和「忽略角色軸」開關會自動存到 `<資料夾>_style_atlas/groups.json`，下次打開同一個資料夾時會還原（開關以網頁上最後的狀態為準）。
    - 名稱跟著圖走：移動、合併、拆群或重新分群後，名稱會留在包含原本大部分圖的那一群；合併時以被併入的那群的名稱為準。
    - 按錯了可以按「復原」或 Ctrl+Z，最多可退回 30 步。「重新分群」會清除手動修正，但同樣可以復原。
  - 圖片有標註 `.txt` 時，每個畫風群下面會列出這群特別常見的標籤（例如「sketch, white background」），方便一眼看出這群是什麼。
  - 用「喜歡／不喜歡」（鍵盤 L / D）評圖。各評滿 5 張後，「口味」分頁會用你的評分訓練模型，替還沒評的圖排序，並顯示交叉驗證的 AUC。
  - 按「評下一張最有用的圖」可進入評分模式：只要一直按 L／D，系統會自動挑下一張和已評過的最不像的圖。用一位使用者的 140 筆真實投票模擬，這樣評 10 張就能達到隨機挑約 25 張的水準。
- `map` 產生的是單一 HTML 檔，three.js 和縮圖都已內嵌，離線也能開。**分享地圖等於分享這些縮圖。**
- `serve` 只監聽本機 127.0.0.1，會檢查 Host 標頭，也只提供掃描過的檔案，不會把你的資料夾開放到網路上。

### ComfyUI 節點

`comfyui/` 資料夾裡有三個節點，可以把畫風檢查直接接進生成流程：

- **Load Style References**：讀一個資料夾當參考集，例如畫師作品、以前生成過的圖、論壇配方的成品。
- **Style Distance**：計算每張生成圖離參考集多遠，並列出最接近的是哪一張。
- **Style Gate**：只讓夠原創的圖通過（keep original），或只讓夠像的圖通過（keep matching）。

安裝步驟（兩步都要做）：
1. 在 ComfyUI 自己的 Python 裡安裝本工具，例如 `python_embeded\python.exe -m pip install -e <repo 路徑>`。節點的程式碼在這個套件裡。
2. 把 `comfyui` 資料夾複製或連結到 `ComfyUI\custom_nodes\style-atlas`。這個資料夾只是讓 ComfyUI 找到節點的入口。

Style Gate 的預設門檻是 0.5。在 Danbooru 上，單張圖之間的距離，同畫師的中位數約 0.40，不同畫師約 0.56。

（節點已在 Python 裡用真正的 CSD 模型跑過；還沒裝進實際的 ComfyUI 測試。）

### 準不準？限制在哪？

詳細數據在 [docs/BENCHMARKS.md](docs/BENCHMARKS.md)。主要測試資料是 297 位畫師的 2,956 張 Danbooru 作品，都是 512 px 縮圖，平均每位約 10 張。測試前已先移除 294 張近重複圖，因為重複圖會讓分數虛高。

- 同畫師檢索：top-1 是 46.5%，隨機約 0.3%；top-10 是 70.5%。
- 去 hub 校正（CSLS）把同畫師配對的 AUC 從 0.78 提高到 0.83。在 Pixiv 的 AI 插畫帳號上也有同樣效果，從 0.75 提高到 0.80。
- 把 2 到 5 位**不同畫師**的作品混在一起，不告訴模型有幾位，分群結果和畫師標籤的吻合度（ARI）約 0.5。

要老實說的限制：

- **同一位畫師的時期拆分有用，但沒那麼準。** 測了 13 位作品多的畫師，每位約 50 張、平均分佈在整段作品史上：
  - 13 位中有 12 位，畫風距離會隨發表時間差而變大，而且顯著。
  - 用 `period` 門檻分群時，13 位中有 9 位的分群和發表時間顯著對應；medium 只有 4 位，預設的 auto 有 8 位。
  - 有些畫師會被切得很碎，請在網頁上看時間分佈並合併。分群結果請當作**初步整理**。
- **先排除重複圖再分群**，也就是加 `--dedupe`。否則同一張圖的多個版本會自成一群。近重複的門檻刻意設得保守（0.95）：在 0.92～0.95 之間，常常是同一角色換了姿勢的不同圖，對 LoRA 來說那是有效的訓練圖。
- `compare` 的 z 值門檻（z ≥ 2.3 為「明顯不同」、z < 1.5 為「同一畫風」）來自一位使用者在固定內容的 NovelAI 算圖上的人眼校準，不是通用標準。換了資料，最好先用 `calibrate` 重新校準。

### 從研究得到的幾個結論

這個工具整理自一段長時間的畫風研究。以下是會影響使用方式的發現：

1. **畫風向量要「去 hub」**。少數圖在高維空間裡和什麼都很近，用原始 cosine 找最近鄰時，結果常被這幾張佔滿。做了 CSLS 校正之後，檢索與分群都明顯變好。arXiv 2605.09030 也得到相同結論。
2. **單張圖之間的距離雜訊很大**。比較兩種畫風時，應該用多張圖的平均來比（`compare`），並用同一畫風內部的雜訊當尺度（`calibrate`）。
3. **公開的美學評分模型不等於個人口味**。在一位使用者的實際選擇上，7 個現成評分器的準確率都只有 36–52%，和亂猜差不多。用他自己的喜歡／不喜歡訓練的小模型，交叉驗證 AUC 是 0.76。所以本工具只提供**個人**口味模型，不內建通用美學分數。
4. **口味模型只適合粗篩**。它分得出喜歡和不喜歡，但分不出「好」和「更好」，換了新的生成來源也可能失準。
5. **CSD 的 content 向量幾乎和 style 向量一樣**，兩者的配對相似度相關係數是 0.95。把內容成分扣掉並不會讓分群變好，所以 content 向量只拿來判斷近重複。

### 授權與致謝

- 風格嵌入使用 CSD（Somepalli et al., *Measuring Style Similarity in Diffusion Models*, 2024）。程式碼 [learn2phoenix/CSD](https://github.com/learn2phoenix/CSD) 採 MIT 授權，權重 [tomg-group-umd/CSD-ViT-L](https://huggingface.co/tomg-group-umd/CSD-ViT-L) 採 CC-BY-4.0，在執行時才下載，本 repo 不重新散布。
- 3D 地圖使用 [three.js](https://threejs.org) r160（MIT），已內嵌在 `src/styleatlas/templates/vendor/`，授權檔在同一個資料夾。
- 本專案目前為私有，授權尚未決定。

---

## English

style-atlas turns every image into a *style vector* with CSD, an embedding trained to capture
how a picture is drawn rather than what it shows. On top of those vectors it can:

- **Prepare LoRA datasets**: split a folder by style or period, set aside duplicates and
  outliers, and export kohya-style folders (`cluster --layout kohya --dedupe`).
- **Find images in a similar style**: drop an image into the web app, or use `search`. A
  "style path" lists the images that lead from one picked style to another.
- **Explore a 3D style map** (`map`): one HTML file you can send to anyone.
- **Check a dataset** (`audit`, `duplicates`): sizes, aspect ratios, captions, near-duplicates.
- **Fix groups by hand** in the web app: "Find more like this" lists the images outside a group
  that look most like it; move an image to another group, merge two groups,
  split a group in two, or exclude images (X), which are then exported to `_excluded/`.
  Groups, edits, names and the character-axis switch are saved and restored the next time the
  folder is opened. Names follow their images: after a move, merge, split or regroup a name
  stays with the group that holds most of its images.
  Undo (or Ctrl+Z) steps back through the last 30 edits, regroups and renames.
- **Quantify style and taste**: `compare` two sets, or train a personal like/dislike model in
  the web app or with `taste`.

### Windows quick start

1. Install Python 3.10+ and tick "Add python.exe to PATH".
2. Get the project (GitHub: **Code -> Download ZIP** and unzip, or `git clone`; the repository is
   private, so ask the author for access). Double-click `scripts\setup.bat`. It creates `.venv`,
   installs CUDA torch when an NVIDIA GPU is present (otherwise CPU torch), then installs
   style-atlas.
3. Drag an image folder onto `scripts\StyleAtlas.bat`. The browser opens the web app.

For commands (`audit`, `cluster`, `search` ...), double-click `scripts\StyleAtlas-console.bat`: it
opens a console where `style-atlas` works. A plain console does not know the command, because it
is installed in `.venv`.

First-run notes:

- Keep the console window open while you use the web app; closing it stops the app. If no
  browser opens, go to the address the window prints (usually `http://127.0.0.1:8770`).
- Captions are `.txt` files next to their images with the same name. Sub-folders are included
  unless you pass `--no-recursive`.
- Try a folder of about 100 images first.

Terms: the **kohya** layout is the folder structure kohya_ss / sd-scripts train from
(`10_artistX_style01`, where 10 is the **repeats**: how often each image is seen per epoch). A
**trigger word** is the tag at the start of each caption that calls up the style after
training.

The first analysis downloads the CSD model once from Hugging Face (2.4 GB). It is kept as a slim
1.2 GB file in `~/.cache/style-atlas`; set `STYLE_ATLAS_CACHE` to move it.

Speed:

- 8 CPU threads embed about 4 images per second (measured).
- An NVIDIA GPU is usually much faster (not benchmarked here).
- Vectors are cached by file content, so reopening a folder does not re-embed anything.

Manual install:

```bash
git clone https://github.com/Rinne414/style-atlas && cd style-atlas
pip install -e .          # install the CUDA build of torch first for GPU use; ".[umap]" adds UMAP
```

### LoRA workflow

```bash
style-atlas audit DIR --min-side 768        # small / extreme / animated images, missing captions
style-atlas serve DIR --time name           # review duplicates, outliers and groups in the browser
style-atlas cluster DIR --layout kohya --name artistX --dedupe --drop-outliers 5 --export copy
```

The output goes to `DIR_style_atlas/folders/`, next to the dataset and never inside it:

- `<repeats>_artistX_styleNN/` folders, with captions copied alongside. Repeats are chosen so
  that images x repeats is about 100; use `--repeats N` to fix them.
- `_duplicates/`, `_outliers/`, `_unassigned/` and `_excluded/` (images you excluded with X in
  the web app). Kohya skips these because they lack a number prefix.
- `clusters.json`, which lists each group's characteristic caption tags.
- With `--trigger-captions`, every exported caption starts with its group's trigger
  (`artistX_style01, ...`). Images without a caption get one, and source captions are never
  touched. The full workflow is in [docs/LORA_GUIDE.md](docs/LORA_GUIDE.md).

Source files are never moved or deleted. Each export goes to a fresh folder.

With `--export link` the files are hard links, so editing an exported caption also edits the
original.

### Commands

```bash
style-atlas cluster DIR [--granularity auto|period|fine|medium|coarse | --threshold T | --k N]
                        [--layout plain|kohya --name X --repeats auto|N]
                        [--dedupe] [--drop-outliers N] [--export copy|link] [-o OUT]
style-atlas doctor                 # check Python, torch, GPU, model download, disk space
style-atlas serve DIR [--port 8770] [--no-browser] [--time none|name|mtime]
style-atlas map DIR [-o map.html] [--projection auto|umap|tsne|pca] [--time ...]
style-atlas search QUERY... --in DIR [--top 20] [--combine] [--copy-to DIR] [--json]
style-atlas audit DIR [--min-side 512] [--max-ratio 2.5] [--json]
style-atlas duplicates DIR [--threshold 0.95] [--json]
style-atlas outliers DIR [--top 30]
style-atlas compare DIR_A DIR_B [--noise-floor X]
style-atlas calibrate DIR          # sub-folders = groups known to share one style
style-atlas bench DIR              # sub-folders = labels (e.g. one artist each)
style-atlas taste train --like DIR --dislike DIR [--model taste.npz]
style-atlas taste score DIR [--model taste.npz]
```

Common options:

- `--device auto|cpu|cuda`
- `--resolution 224|336`: 336 is about 1 point better at retrieval and 2.5x slower.
- `--reference DIR` (cluster, map, serve): a folder of styles you already know. It adds an
  originality measure, the distance from each image to its closest reference. The map's
  "measures" layout can then put taste, originality, time and atypicality on the X / Y / Z axes.
- `--neutralize 1` (cluster, map, serve, search): use it when the same characters appear in many
  styles. On 96 NovelAI styles x 2 characters it raised same-style AUC from 0.83 to 0.98. Do not
  use it on a mix of different artists, where it removes the style difference itself.
- `--crop center|tiles`
- `--threads N` (default 8)
- `--cache-db PATH`

### How it works

- **Embedding**: CSD ViT-L/14, loaded through `open_clip` with QuickGELU. The output matches the
  reference implementation (cosine 1.0000). It gives 768-d style and content vectors.
- **Hub correction**: CSLS with k=10. `d = 1 - cos + (r_i + r_j)/2 - mean(r)`, where `r` is each
  image's mean similarity to its 10 nearest neighbours.
- **Clustering**: average-linkage agglomerative clustering on hub-corrected distances. By
  default (`auto`) the cut is the best-silhouette cut plus 0.04, at most 0.47: the best cut falls
  as more artists are mixed, and auto beat the fixed 0.47 by 0.13-0.18 ARI on mixtures of 50-306
  artists while matching it on 2-20. Fixed cuts: 0.35 (period), 0.40 (fine), 0.47 (medium),
  0.55 (coarse). HDBSCAN is optional. Above 8,000 images, k-means first makes 8,000 micro-groups and the linkage joins
  those, using exact mean distances between them (50,000 images: 39 s, then 0.5 s per new
  threshold).
- **Near-duplicates**: min(style cosine, content cosine) >= 0.95, grouped with union-find. The
  threshold is deliberately conservative: between 0.92 and 0.95 the pairs were often different
  poses of one character.
- **Map**: UMAP if installed, else t-SNE, in 3D. The layout is for viewing only; groups are
  computed in the full space.
- **Taste**: PCA-20, then standardisation, then logistic regression. It is saved as plain `.npz`
  with no pickle.

### Accuracy and limits

The full numbers are in [docs/BENCHMARKS.md](docs/BENCHMARKS.md). The corpus is 2,956 Danbooru
works by 297 artists (512 px thumbnails, near-duplicates removed). Same-artist retrieval gives:

- top-1 46.5% (chance 0.3%)
- top-10 70.5%
- pair AUC 0.832, against 0.781 without hub correction

Blind clustering of 2-5 mixed artists scores ARI about 0.5.

Splitting one artist's periods: use `--granularity period` (cut 0.35), with `--time name` to
see each group's time span. On 13 prolific Danbooru artists (about 50 works each, spread
over their history):

- Style distance grew with posting-time distance for 12 of 13 (Mantel test).
- `period` groups matched time quartiles beyond chance for 9 of 13, the default `auto` for 8,
  `medium` for 4.
- Some artists fragment into many small groups at 0.35; merge them in the web app.

Style drift is gradual, so treat groups as a first pass and review them in the map.

The `compare` z thresholds come from one person's calibration on fixed-content NovelAI renders.
Re-run `calibrate` on your own data.

### ComfyUI nodes

`comfyui/` provides three nodes:

- **Load Style References**: reads a folder of known styles.
- **Style Distance**: the distance from each generated image to its closest reference.
- **Style Gate**: keeps original or matching images.

Install (both steps are needed):
1. Install style-atlas into ComfyUI's own Python, e.g.
   `python_embeded\python.exe -m pip install -e <repo path>`. The node code lives in the package.
2. Copy or link the `comfyui` folder into `ComfyUI/custom_nodes/style-atlas`. It is only the
   entry point ComfyUI looks for.

The Gate's default threshold is 0.5. For single images on Danbooru, the median distance is about
0.40 between works by the same artist and 0.56 between different artists. The nodes have run with
the real CSD model from Python, but not yet inside ComfyUI.

### Credits

- CSD: Somepalli et al. 2024. Code under MIT, weights under CC-BY-4.0, downloaded at runtime.
- three.js r160 (MIT), vendored in `src/styleatlas/templates/vendor/`.
- This repository is private; its license is undecided.
