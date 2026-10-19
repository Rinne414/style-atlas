# 准不准、限制在哪 / How it works, accuracy and limits

（从 README 移过来，内容没有删减；数字的出处见 [BENCHMARKS.md](BENCHMARKS.md)。）

## 准不准？限制在哪？

详细数据在 [docs/BENCHMARKS.md](BENCHMARKS.md)。主要测试数据是 297 位画师的 2,956 张 Danbooru 作品，都是 512 px 缩略图，平均每位约 10 张。测试前已先移除 294 张近重复图，因为重复图会让分数虚高。

- 同画师检索：top-1 是 46.5%，随机约 0.3%；top-10 是 70.5%。
- 去 hub 校正（CSLS）把同画师配对的 AUC 从 0.78 提高到 0.83。在 Pixiv 的 AI 插画账号上也有同样效果，从 0.75 提高到 0.80。
- 把 2 到 5 位**不同画师**的作品混在一起，不告诉模型有几位，分组结果和画师标签的吻合度（ARI）约 0.5。

要老实说的限制：

- **同一位画师的时期拆分有用，但没那么准。** 测了 13 位作品多的画师，每位 30~300 张、平均分布在整段作品史上：
  - 13 位中有 12 位，画风距离会随发表时间差而变大，而且显著。
  - `period`（分成 3 段）和发表时间的吻合度，跟以前用的固定阈值 0.35 差不多（两者都远好于“中”）；差别在 0.35 有 4 位画师有 36~77% 的图没分到任何组，新的几乎每张图都有分到。
  - 作品少（约 50 张）时，分段结果不太稳定，请在网页上看时间分布，必要时合并或移动。分组结果请当作**初步整理**。
  - 文件名有时间时，`--granularity timeline` 按时间顺序在画风变化最大的地方切段，再用两个检验区分“没找到和时间的关系”、“只有渐变”和“有转折”。14 位画师里只有 1 位有转折，5 位只有渐变，6 位没找到和时间的明显关系，2 位作品太少；14 位里有 6 位的 p 值在阈值边缘，指令和网页会注明“结论可能翻转”。画师常连续发表一系列相像的作品，检验会把连续的相似作品（cos 0.80 以上）当成一个系列只算一次，否则纯噪声也会被当成和时间有关。结论请当成“去地图上看一看”的提示，不是定论。只检验“切点比打乱时间顺序明显”是不够的：单纯的渐变也会显著，旧版因此高估成 8 位。“有转折”的意思是“变化比随时间平滑变化的曲线（二次曲线）更突然”：一开始和最后变很快、中间很稳定的画风也会判成有转折。
- **先排除重复图再分组**，也就是加 `--dedupe`。否则同一张图的多个版本会自成一组。近重复的阈值刻意设得保守（0.95）：在 0.92~0.95 之间，常常是同一角色换了姿势的不同图，对 LoRA 来说那是有效的训练图。
- `compare` 两边都有 5 张以上时，会把距离放到“两位不同画师”的分布里看：每边 20 张时（87 位画师），两位不同画师有 95% 相差 0.130 以上，同一位画师最早和最新的作品中位数相差 0.086，同一位画师的作品随机分两半中位数只差 0.034。这只是位置，不是判断是不是同一位画师画的：画风很像的两位画师也会落在“比 95% 都接近”，而同一位画师早期和近期的作品，每 5 位约有 1 位比这更远。p 值说的是两边是否很可能不同（画师常连续发表很像的系列作品，p 会显得偏小）；p 很小时合在一起训练，LoRA 会学到两边混合的画风。
- 张数更少（例如 LoRA 出图）或给了 `--noise-floor` 时，改用 z 值阈值（z ≥ 2.3 为“明显不同”、z < 1.5 为“同一画风”），它来自一位用户在固定内容的 NovelAI 出图上的人眼校准，不是通用标准；换了数据，最好先用 `calibrate` 重新校准。

### 数据集检查准不准？

- **放大过的图**：放大 2 倍以上的图，各组测试抓到 92~100%；原图都没有被误判。整组 3,259 张 Danbooru 图只标出 1 张，确认是放大过的动画截屏。放大 1.5 倍的图和 AI 放大的图多半抓不到。
- **JPEG 压缩**：质量是直接从文件的量化表读的。Pillow 存的文件完全准，其他软件存的文件是估计值。质量 60 就会让画风向量偏移约三分之一个“同配方换种子”的差距，所以阈值定在 70。
- **近重复图**：分数 0.97 以上是重新上色、裁切或同一张图的不同帧；0.95~0.965 大多是变体。默认 0.95 偏保守，不会删掉有效的训练图。
- **黑白标签**：Danbooru 的 226 张黑白图里，有 35 张（15%）`monochrome`、`greyscale` 都没标，抽看的都确实是黑白图。标了 `greyscale` 但色彩度在 0.08 以上的 6 张，都有明显的颜色。

## 从研究得到的几个结论

这个工具整理自一段长时间的画风研究。以下是会影响使用方式的发现：

1. **画风向量要“去 hub”**。少数图在高维空间里和什么都很近（称为 hub），用原始 cosine 找最近邻时，结果常被这几张占满。做了 CSLS 校正之后，检索与分组都明显变好。arXiv 2605.09030 也得到相同结论。
2. **单张图之间的距离噪声很大**。比较两种画风时，应该用多张图的平均来比（`compare`），并用同一画风内部的噪声当尺度（`calibrate`）。
3. **公开的美学评分模型不等于个人偏好**。在一位用户的实际选择上，7 个现成评分器的准确率都只有 36–52%，和乱猜差不多。用他自己的喜欢/不喜欢训练的小模型，交叉验证 AUC 是 0.76。所以本工具只提供**个人**偏好模型，不内置通用美学分数。
4. **偏好模型只适合粗筛**。它分得出喜欢和不喜欢，但分不出“好”和“更好”，换了新的生成来源也可能失准。一般的交叉验证会把同一位画师的图同时放在训练和验证两边，所以数字偏高（模拟：0.96）；把整组相似画风留出来验证比较接近遇到新画师的情况（模拟：0.66~0.76，新画师实际约 0.47~0.64；喜欢和不喜欢各需要 4 组相似画风才算得出来）。`taste train` 和网页的偏好标签页两个数字都会列出；`taste score` 会标出和所有评过的图都不太像的图（最高相似度低于 0.6），它们的分数接近乱猜。
5. **CSD 的 content 向量几乎和 style 向量一样**，两者的配对相似度相关系数是 0.95。把内容成分扣掉并不会让分组变好，所以 content 向量只拿来判断近重复，以及在 `--ignore-characters` 时找出角色（用它分组可以正确找出固定角色）。

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
