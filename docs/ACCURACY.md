# 準不準、限制在哪 / How it works, accuracy and limits

（從 README 移過來，內容沒有刪減；數字的出處見 [BENCHMARKS.md](BENCHMARKS.md)。）

## 準不準？限制在哪？

詳細數據在 [docs/BENCHMARKS.md](BENCHMARKS.md)。主要測試資料是 297 位畫師的 2,956 張 Danbooru 作品，都是 512 px 縮圖，平均每位約 10 張。測試前已先移除 294 張近重複圖，因為重複圖會讓分數虛高。

- 同畫師檢索：top-1 是 46.5%，隨機約 0.3%；top-10 是 70.5%。
- 去 hub 校正（CSLS）把同畫師配對的 AUC 從 0.78 提高到 0.83。在 Pixiv 的 AI 插畫帳號上也有同樣效果，從 0.75 提高到 0.80。
- 把 2 到 5 位**不同畫師**的作品混在一起，不告訴模型有幾位，分群結果和畫師標籤的吻合度（ARI）約 0.5。

要老實說的限制：

- **同一位畫師的時期拆分有用，但沒那麼準。** 測了 13 位作品多的畫師，每位 30～300 張、平均分佈在整段作品史上：
  - 13 位中有 12 位，畫風距離會隨發表時間差而變大，而且顯著。
  - `period`（分成 3 段）和發表時間的吻合度，跟以前用的固定門檻 0.35 差不多（兩者都遠好於「中」）；差別在 0.35 有 4 位畫師有 36～77% 的圖沒分到任何群，新的幾乎每張圖都有分到。
  - 作品少（約 50 張）時，分段結果不太穩定，請在網頁上看時間分佈，必要時合併或移動。分群結果請當作**初步整理**。
  - 檔名有時間時，`--granularity timeline` 依時間順序在畫風變化最大的地方切段，再用兩個檢定區分「沒找到和時間的關係」、「只有漸變」和「有轉折」。14 位畫師裡只有 1 位有轉折，5 位只有漸變，6 位沒找到和時間的明顯關係，2 位作品太少；14 位裡有 6 位的 p 值在門檻邊緣，指令和網頁會註明「結論可能翻轉」。畫師常連續發表一系列相像的作品，檢定會把連續的相似作品（cos 0.80 以上）當成一個系列只算一次，否則純雜訊也會被當成和時間有關。結論請當成「去地圖上看一看」的提示，不是定論。只檢驗「切點比打亂時間順序明顯」是不夠的：單純的漸變也會顯著，舊版因此高估成 8 位。「有轉折」的意思是「變化比隨時間平滑變化的曲線（二次曲線）更突然」：一開始和最後變很快、中間很穩定的畫風也會判成有轉折。
- **先排除重複圖再分群**，也就是加 `--dedupe`。否則同一張圖的多個版本會自成一群。近重複的門檻刻意設得保守（0.95）：在 0.92～0.95 之間，常常是同一角色換了姿勢的不同圖，對 LoRA 來說那是有效的訓練圖。
- `compare` 兩邊都有 5 張以上時，會把距離放到「兩位不同畫師」的分布裡看：每邊 20 張時（87 位畫師），兩位不同畫師有 95% 相差 0.130 以上，同一位畫師最早和最新的作品中位數相差 0.086，同一位畫師的作品隨機分兩半中位數只差 0.034。這只是位置，不是判斷是不是同一位畫師畫的：畫風很像的兩位畫師也會落在「比 95% 都接近」，而同一位畫師早期和近期的作品，每 5 位約有 1 位比這更遠。p 值說的是兩邊是否很可能不同（畫師常連續發表很像的系列作品，p 會顯得偏小）；p 很小時合在一起訓練，LoRA 會學到兩邊混合的畫風。
- 張數更少（例如 LoRA 算圖）或給了 `--noise-floor` 時，改用 z 值門檻（z ≥ 2.3 為「明顯不同」、z < 1.5 為「同一畫風」），它來自一位使用者在固定內容的 NovelAI 算圖上的人眼校準，不是通用標準；換了資料，最好先用 `calibrate` 重新校準。

### 資料集檢查準不準？

- **放大過的圖**：放大 2 倍以上的圖，各組測試抓到 92～100%；原圖都沒有被誤判。整組 3,259 張 Danbooru 圖只標出 1 張，確認是放大過的動畫截圖。放大 1.5 倍的圖和 AI 放大的圖多半抓不到。
- **JPEG 壓縮**：品質是直接從檔案的量化表讀的。Pillow 存的檔完全準，其他軟體存的檔是估計值。品質 60 就會讓畫風向量偏移約三分之一個「同配方換種子」的差距，所以門檻定在 70。
- **近重複圖**：分數 0.97 以上是重新上色、裁切或同一張圖的不同格；0.95～0.965 大多是變體。預設 0.95 偏保守，不會刪掉有效的訓練圖。
- **黑白標籤**：Danbooru 的 226 張黑白圖裡，有 35 張（15%）`monochrome`、`greyscale` 都沒標，抽看的都確實是黑白圖。標了 `greyscale` 但色彩度在 0.08 以上的 6 張，都有明顯的顏色。

## 從研究得到的幾個結論

這個工具整理自一段長時間的畫風研究。以下是會影響使用方式的發現：

1. **畫風向量要「去 hub」**。少數圖在高維空間裡和什麼都很近（稱為 hub），用原始 cosine 找最近鄰時，結果常被這幾張佔滿。做了 CSLS 校正之後，檢索與分群都明顯變好。arXiv 2605.09030 也得到相同結論。
2. **單張圖之間的距離雜訊很大**。比較兩種畫風時，應該用多張圖的平均來比（`compare`），並用同一畫風內部的雜訊當尺度（`calibrate`）。
3. **公開的美學評分模型不等於個人口味**。在一位使用者的實際選擇上，7 個現成評分器的準確率都只有 36–52%，和亂猜差不多。用他自己的喜歡／不喜歡訓練的小模型，交叉驗證 AUC 是 0.76。所以本工具只提供**個人**口味模型，不內建通用美學分數。
4. **口味模型只適合粗篩**。它分得出喜歡和不喜歡，但分不出「好」和「更好」，換了新的生成來源也可能失準。一般的交叉驗證會把同一位畫師的圖同時放在訓練和驗證兩邊，所以數字偏高（模擬：0.96）；把整組相似畫風留出來驗證比較接近遇到新畫師的情況（模擬：0.66～0.76，新畫師實際約 0.47～0.64；喜歡和不喜歡各需要 4 群相似畫風才算得出來）。`taste train` 和網頁的口味分頁兩個數字都會列出；`taste score` 會標出和所有評過的圖都不太像的圖（最高相似度低於 0.6），它們的分數接近亂猜。
5. **CSD 的 content 向量幾乎和 style 向量一樣**，兩者的配對相似度相關係數是 0.95。把內容成分扣掉並不會讓分群變好，所以 content 向量只拿來判斷近重複，以及在 `--ignore-characters` 時找出角色（用它分群可以正確找出固定角色）。

---

## How it works

- **Embedding**: CSD ViT-L/14, loaded through `open_clip` with QuickGELU. The output matches the
  reference implementation (cosine 1.0000). It gives 768-d style and content vectors.
- **Search whitening**: search ranks after a fixed linear map learned from 306 Danbooru artists
  that turns down within-artist variation (WCCN); on artists it never saw, top-1 rose 2-5 points
  and set search AP 0.05-0.07. Grouping and every thresholded distance use plain CSD.
- **Hub correction**: CSLS with k=10. `d = 1 - cos + (r_i + r_j)/2 - mean(r)`, where `r` is each
  image's mean similarity to its 10 nearest neighbours.
- **Clustering**: average-linkage agglomerative clustering on hub-corrected distances. By
  default (`auto`) the cut is the best-silhouette cut plus 0.04, at most 0.47: the best cut falls
  as more artists are mixed, and auto beat the fixed 0.47 by 0.16-0.21 ARI on mixtures of 50-306
  artists (leaving 5-9% unassigned instead of 1-2%) while matching it on 2-20 and on folders full
  of near-copies. Fixed cuts: 0.40 (fine), 0.47 (medium), 0.55 (coarse). `period` is k-means
  into N groups (default 3) for splitting one artist. HDBSCAN is optional. Above 8,000 images, k-means first makes 8,000 micro-groups and the linkage joins
  those, using exact mean distances between them (50,000 images: 39 s, then 0.5 s per new
  threshold).
- **Near-duplicates**: min(style cosine, content cosine) >= 0.95, grouped with union-find. The
  threshold is deliberately conservative: between 0.92 and 0.95 the pairs were often different
  poses of one character.
- **Map**: UMAP if installed, else t-SNE, in 3D. The layout is for viewing only; groups are
  computed in the full space.
- **Taste**: PCA-20, then standardisation, then logistic regression. It is saved as plain `.npz`
  with no pickle.
- **Look measures**: six image statistics that say *how* styles differ, computed on a copy whose
  long side is 256 px:
  - brightness (mean luma);
  - contrast (luma standard deviation);
  - colourfulness (Hasler and Suesstrunk 2003; 0 greyscale, about 0.4 neon);
  - warmth (mean red minus mean blue);
  - lines (share of pixels on a strong luma edge);
  - flatness (share of pixels in flat areas).

  Each image is measured once and cached; images analysed by 0.15 or later are measured while they
  are open for embedding, and older ones are measured on first use (about 70 832 x 1216 PNGs a
  second on 8 CPU threads). They appear as words on each group card ("cooler, more line work"),
  as axes of the map's "measures" layout, as columns in `clusters.csv`, as a per-group profile
  in `clusters.json`, and as B minus A in `compare`. A single image is noisy: on 3,259 Danbooru
  works by 306 artists, 13-40% of each measure's spread was between artists (lines 0.40,
  flatness 0.37, colourfulness 0.32, brightness 0.32, contrast 0.26, warmth 0.13), so compare
  group means. They describe; they do not judge quality. Images are shrunk, never enlarged:
  below 256 px (long side), lines read higher and flatness lower (about +0.4 and -0.6 SD at
  192 px), so compare groups of similar image sizes.

## Accuracy and limits

The full numbers are in [docs/BENCHMARKS.md](BENCHMARKS.md). The corpus is 2,956 Danbooru
works by 297 artists (512 px thumbnails, near-duplicates removed). Same-artist retrieval gives:

- top-1 46.5% (chance 0.3%)
- top-10 70.5%
- pair AUC 0.832, against 0.781 without hub correction

Blind clustering of 2-5 mixed artists scores ARI about 0.5.

Splitting one artist's periods: when the file names carry a time, use `--granularity timeline
--time name`: contiguous periods cut where the style changes most, and two tests that tell a
style with no clear link to time, a smooth drift and turns apart. Of 14 artists, 1 had turns, 5
only drifted, 6 showed no clear link to time and 2 had too few distinct works; 6 verdicts were on
the p = 0.05 edge, which the output says. Runs of alike consecutive works (series) count once; a test against shuffled time orders alone passes smooth drift too, and the first
version counted 8 of 13 that way. "Turns" means more abrupt than a quadratic trend over time: a
style that changes fast at the start and the end with a long stable middle counts too.
Without a time, use `--granularity period`, with `--time name` to see each
group's time span. It splits the work into 3 groups with k-means (`--k 4` for four), and every
image lands in one of them. On 13 prolific Danbooru artists (30-300 works each, spread over
their history):

- Style distance grew with posting-time distance for 12 of 13 (Mantel test).
- `period` follows posting time about as well as the old 0.35 cut (AMI +0.006, CI -0.03 to
  +0.04), and both clearly better than `medium`. The old cut left 36-77% of the images
  unassigned for 4 artists; k-means puts nearly every image in a period, sketches included, so
  combine it with `--drop-outliers N`.
- Three periods is a convention (choosing k from the data did worse). Below about 100 works the
  split changes with the k-means seed; review it in the web app.

Style drift is gradual, so treat groups as a first pass and review them in the map.

With 5 or more images a side, `compare` places the distance among pairs of different Danbooru
artists: at 20 works a side (87 artists), 95% of them are 0.130 or more apart, one artist's
oldest and newest works 0.086 (median), random halves of one artist's works 0.034 (median). It
is a position, not a verdict on who drew them: two similar artists also sit low, and about 1
artist in 5 has older and newer works farther apart than that. The p value says
whether the two sides likely differ; a small p means a LoRA trained on both learns both looks
mixed. With fewer images (LoRA renders) or `--noise-floor`, the z
thresholds are used; they come from one person's calibration on fixed-content NovelAI renders,
so re-run `calibrate` on your own data.

### Dataset checks

- **Enlarged images**: 2x and larger enlargements were caught in 92-100% of each test set, with
  no original flagged; on all 3,259 Danbooru works one image was flagged, an enlarged anime
  frame. 1.5x enlargements and AI upscales mostly pass.
- **JPEG compression**: the quality is read from the file's quantisation table, exact for Pillow
  files and an estimate for other encoders. Quality 60 already moves the style vector by a third
  of a seed difference, hence the cut at 70.
- **Near-duplicates**: scores of 0.97 and up are recolours, crops and frames of one picture;
  0.95-0.965 are mostly variants. The default of 0.95 is conservative and keeps valid training
  images.
- **Greyscale tags**: 35 of 226 greyscale Danbooru works (15%) carry neither `monochrome` nor
  `greyscale`, and the ones looked at were plainly greyscale. All 6 works tagged `greyscale` at
  a colourfulness of 0.08 or more had clear colour.
