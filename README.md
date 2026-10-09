# style-atlas

**量化、聚類、搜尋與視覺化插畫畫風。全部在本機運算。**
Measure, cluster, search and map illustration art styles, entirely on your machine.

[繁體中文](#繁體中文) · [English](#english)

---

## 繁體中文

style-atlas 把每張圖轉成一個「畫風向量」。轉換用的是 CSD 風格嵌入模型，它專門學「怎麼畫」，而不是「畫了什麼」。在這些向量上可以做四件事：

| 你想做的事 | 指令 |
|---|---|
| **訓 LoRA 前整理資料集**：同一位畫師不同時期的畫風不同，先分群再訓 | `style-atlas cluster 資料夾 --export copy` |
| **找畫風相近的圖** | `style-atlas search 參考圖.png --in 圖庫資料夾` |
| **3D 畫風地圖**：縮圖浮在 3D 空間，可轉動，點一下就看最接近的畫風 | `style-atlas map 資料夾` |
| **網頁介面**：在瀏覽器裡拖圖搜尋、調門檻重新分群、一鍵匯出資料夾 | `style-atlas serve 資料夾` |
| **找近重複圖**：同一張圖、裁切、同場景連續畫面（訓 LoRA 前每組留一張） | `style-atlas duplicates 資料夾` |
| **量化畫風**：判斷兩組圖是否同一畫風、找出離群圖、訓練個人口味模型 | `compare`、`outliers`、`calibrate`、`taste` |

### 安裝

需要 Python 3.10 以上。有 NVIDIA 顯卡的話，請先依 [pytorch.org](https://pytorch.org) 的說明裝好 CUDA 版的 torch。

```bash
git clone https://github.com/Rinne414/style-atlas
cd style-atlas
pip install -e .            # 想用 UMAP 版面就裝 pip install -e ".[umap]"
```

Windows 使用者也可以直接把圖片資料夾**拖到 `scripts/StyleAtlas.bat` 上**，瀏覽器會自動打開網頁介面。

第一次執行會從 Hugging Face 下載 CSD 權重（2.4 GB），並另存成 1.2 GB 的精簡檔，之後啟動會比較快。快取位置是 `~/.cache/style-atlas/`，可用環境變數 `STYLE_ATLAS_CACHE` 改位置。

### 快速開始

```bash
# 1. 把一個 LoRA 資料集依畫風分群，另外複製到 style_01、style_02 …
#    同名的 .txt / .caption 標註會一起複製；原始檔案不會被移動或刪除
style-atlas cluster "D:/lora/artistX" --export copy
#    輸出在旁邊的 D:/lora/artistX_style_atlas/（不會寫進資料集資料夾本身）：
#    clusters.csv、clusters.json、map.html、folders/

# 2. 分太細或太粗？換顆粒度，或直接指定群數
style-atlas cluster "D:/lora/artistX" --granularity fine     # fine / medium（預設）/ coarse
style-atlas cluster "D:/lora/artistX" --k 3

# 3. 找和這幾張參考圖畫風最接近的 30 張
style-atlas search ref1.png ref2.png --combine --in "D:/gallery" --top 30

# 4. 只畫 3D 地圖（單一 HTML 檔，離線也能開，可以直接傳給朋友）
style-atlas map "D:/gallery" -o gallery_map.html

# 5. 網頁介面：自動開瀏覽器；把圖拖進畫面就能搜尋，調門檻後按「重新分群」，再按「匯出資料夾」
style-atlas serve "D:/lora/artistX"

# 加上 --time name（用檔名裡的 Pixiv / Danbooru 作品編號）或 --time mtime（檔案修改時間），
# 每個畫風群旁會畫出時間分佈：一眼看出哪種畫風是早期、哪種是近期
style-atlas serve "D:/lora/artistX" --time name

# 6. 資料集裡哪些圖最「不合群」（訓練前可考慮剔除）
style-atlas outliers "D:/lora/artistX" --top 20
style-atlas duplicates "D:/lora/artistX"      # 近重複圖分組

# 7. 兩組圖是不是同一種畫風？（距離、z 值、置換檢定 p 值）
style-atlas compare "D:/old_works" "D:/new_works"
```

匯出時每次都會寫到新的資料夾（`folders`、`folders_2` …），不會和上一次的結果混在一起。`--export link` 用硬連結，不佔額外空間，但連結檔和原檔是**同一個檔案**：在匯出資料夾裡改標註，原本的標註也會跟著變。不確定的話就用 `copy`。

所有向量都會快取，同一張圖（以內容雜湊判斷，改名或搬移都算同一張）只會計算一次。CPU 預設最多用 8 個執行緒並降低優先權，避免拖垮整台電腦。用 `--threads 0` 取消限制，`--device cpu` 可強制只用 CPU。

### 3D 畫風地圖

- 縮圖直接浮在 3D 空間中，外框顏色代表畫風群，可拖曳旋轉、滾輪縮放。
- 點右側的畫風群，鏡頭會飛過去並顯示成員；點地圖上的圖，會列出最接近的 12 張。
- 「離群」分頁列出和整組最不像的圖；「重複」分頁列出近重複圖組。
- 支援中／英文介面與深／淺色主題，可用檔名篩選，`+` / `-` 調整縮圖大小。
- 地圖是單一 HTML 檔，three.js 和縮圖都已內嵌，離線也能開。**分享地圖等於分享這些縮圖。**
- `serve` 只監聽本機 127.0.0.1，會檢查 Host 標頭，也只提供掃描過的檔案，不會把你的資料夾開放到網路上。

### 準不準？

詳細數據在 [docs/BENCHMARKS.md](docs/BENCHMARKS.md)。測試資料是 296 位畫師的 2,941 張 Danbooru 作品，已先移除 308 張近重複圖，因為重複圖會讓檢索分數虛高：

- 同畫師檢索 top-1 為 46.2%（隨機約 0.3%），top-10 為 70.4%。
- 去 hub 校正（CSLS）把同畫師配對的 AUC 從 0.78 提高到 0.83。在 Pixiv AI 插畫帳號上也一樣有效，從 0.75 提高到 0.80。
- 把 2 到 5 位畫師的作品混在一起、不告訴模型有幾位，盲分的 ARI 約 0.5。

真實作品的內容變化很大，所以分群結果適合當**初步整理**，最後仍要看圖確認。內容較一致的 LoRA 資料集通常會分得更乾淨。

### 從研究得到的幾個結論

這個工具整理自一段長時間的畫風研究。以下是會影響使用方式的發現：

1. **畫風向量要「去 hub」**。少數圖在高維空間裡和什麼都很近，原始 cosine 的最近鄰常被它們佔據。CSLS 校正後檢索與分群都明顯變好。arXiv 2605.09030 也得到相同結論。
2. **單張圖之間的距離雜訊很大**。比較兩種畫風時，應該用多張圖的平均（`compare`），並用同一畫風內部的雜訊當尺度（`calibrate`）。在固定內容的算圖上，同一配方兩組種子之間的距離約 0.071；以此為單位，z ≥ 2.3 在人眼看來是「明顯不同」，z < 1.5 則是「同一畫風」。
3. **公開的美學評分模型不等於個人口味**。7 個現成評分器預測使用者實際選擇的準確率都在 36–52%，和亂猜差不多。用自己的喜歡／不喜歡訓練的小模型，交叉驗證 AUC 為 0.76。所以本工具只提供**個人**口味模型（`taste`），不內建通用美學分數。
4. **口味模型只適合粗篩**。它分得出喜歡和不喜歡，但分不出「好」和「更好」，換了新的生成來源也可能失準。

### 授權與致謝

- 風格嵌入使用 CSD（Somepalli et al., *Measuring Style Similarity in Diffusion Models*, 2024）。程式碼 [learn2phoenix/CSD](https://github.com/learn2phoenix/CSD) 採 MIT 授權，權重 [tomg-group-umd/CSD-ViT-L](https://huggingface.co/tomg-group-umd/CSD-ViT-L) 採 CC-BY-4.0，執行時才下載，本 repo 不重新散布。
- 3D 地圖使用 [three.js](https://threejs.org)（MIT），從 jsDelivr 載入。
- 本專案目前為私有，授權尚未決定。

---

## English

style-atlas turns every image into a *style vector*. It uses CSD, an embedding trained to capture
how a picture is drawn rather than what it shows. You can then:

| Task | Command |
|---|---|
| **Split a LoRA dataset by style or period** before training | `style-atlas cluster DIR --export copy` |
| **Find images with a similar style** | `style-atlas search ref.png --in GALLERY` |
| **Explore a 3D style map**: thumbnails floating in 3D; click one to see its closest styles | `style-atlas map DIR` |
| **Use the web app**: drop an image to search, re-group with a slider, export folders | `style-atlas serve DIR` |
| **Find near-duplicates**: same picture, crops, frames of one scene | `style-atlas duplicates DIR` |
| **Quantify style**: same style or not, outliers, a personal taste model | `compare`, `outliers`, `calibrate`, `taste` |

### Install

Python 3.10 or newer. For GPU use, install the CUDA build of torch first; see pytorch.org.

```bash
git clone https://github.com/Rinne414/style-atlas && cd style-atlas
pip install -e .          # or pip install -e ".[umap]" for UMAP layouts
```

On Windows you can also drag an image folder onto `scripts/StyleAtlas.bat` to open the web app.

On first use, the CSD weights (2.4 GB) are downloaded from Hugging Face. They are then cached as
a slim 1.2 GB safetensors file in `~/.cache/style-atlas/`. Set `STYLE_ATLAS_CACHE` to move it.

### Commands

```bash
style-atlas cluster DIR [--granularity fine|medium|coarse | --threshold T | --k N]
                        [--method agglomerative|hdbscan] [--export copy|link] [-o OUT]
style-atlas map DIR [-o map.html] [--projection auto|umap|tsne|pca]
style-atlas serve DIR [--port 8770] [--no-browser] [--time none|name|mtime]
style-atlas search QUERY... --in DIR [--top 20] [--combine] [--json]
style-atlas outliers DIR [--top 30]
style-atlas duplicates DIR [--threshold 0.92] [--json]
style-atlas compare DIR_A DIR_B [--noise-floor X]
style-atlas calibrate DIR          # sub-folders = groups known to share one style
style-atlas bench DIR              # sub-folders = labels (e.g. one artist each)
style-atlas taste train --like DIR --dislike DIR [--model taste.npz]
style-atlas taste score DIR [--model taste.npz]
```

Common options:

- `--device auto|cpu|cuda`
- `--crop center|tiles`: `tiles` averages crops along the long side of tall images.
- `--threads N`: CPU cap, default 8.
- `--cache-db PATH`

Vectors are cached by file content, so each image is embedded only once.

Each export goes to a fresh folder (`folders`, `folders_2`, ...), so runs never mix. With
`--export link`, files are hard links: editing a caption in the export also edits the original.

The map is one HTML file with three.js and the thumbnails inlined, so it works offline.
`serve` listens on 127.0.0.1 only, checks the Host header, needs a custom header on every POST,
and serves only files it scanned.

### How it works

- **Embedding**: CSD ViT-L/14. It is loaded through `open_clip` with QuickGELU, and its output
  matches the reference implementation (cosine 1.0000). It gives 768-d style and content vectors.
- **Hub correction**: CSLS with k=10. `d = 1 - cos + (r_i + r_j)/2 - mean(r)`, where `r` is each
  image's mean similarity to its 10 nearest neighbours. Thresholds therefore read like cosine
  distances.
- **Clustering**: average-linkage agglomerative clustering on hub-corrected distances. It cuts at
  0.40, 0.47 or 0.55 (fine / medium / coarse), the defaults tuned on blind artist mixtures.
  Groups smaller than `--min-size` become *unassigned*. HDBSCAN is also available; it leaves
  ambiguous images unassigned.
- **Map**: UMAP if installed, else t-SNE, in 3D. The layout is for viewing only; clusters are
  computed in the full 768-d space.
- **Taste**: PCA-20, then standardisation, then logistic regression. It is saved as plain `.npz`
  arrays with no pickle.

- **Near-duplicates**: min(style cosine, content cosine) >= 0.92, grouped with union-find.

Accuracy and its limits are in [docs/BENCHMARKS.md](docs/BENCHMARKS.md). After removing
near-duplicates, 2,941 Danbooru works by 296 artists give these same-artist scores:

- top-1: 46.2% (chance about 0.3%)
- top-10: 70.4%
- pair AUC: 0.831, against 0.780 without hub correction

### Credits

- CSD: Somepalli et al. 2024. Code under MIT, weights under CC-BY-4.0, downloaded at runtime.
- three.js (MIT).
- This repository is private; its license is undecided.
