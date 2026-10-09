# Benchmarks

All numbers come from `style-atlas bench`, run on real data. When the encoder, the
preprocessing or a default changes, re-run the benchmark and update this file in the same commit.

`bench` first reduces near-duplicates to one image each (see `duplicates`). Copies, crops and
frames of one scene otherwise find each other and inflate retrieval scores.

## Danbooru artists (2026-10-09)

- **Data**: 3,253 general-rated Danbooru works by 306 artists (median 12 each), 512 px
  thumbnails. Posts with minor or multi-panel tags were excluded when the corpus was collected.
- **Deduplication**: 294 near-duplicates were removed at 0.92, every pair inside a group at or above the threshold, leaving 2,956 images by 297 artists.
- **Labels**: the artist. One artist's works vary in character, scene and period, so the label
  means "who drew it", not "one fixed style". That makes this a hard test.
- **Encoder**: CSD ViT-L at 224 px with a centre crop. Its vectors match the reference CSD
  implementation (cosine 1.0000).
- **Command**: `style-atlas bench <thumbs> --labels prefix --trials 60`.

| Score | Raw cosine | Hub-corrected (CSLS, k=10) |
|---|---|---|
| Top-1 nearest neighbour, same artist | 44.9% | **46.5%** |
| Top-5 | 61.3% | **64.5%** |
| Top-10 | 67.7% | **70.5%** |
| Same-artist pair AUC | 0.781 | **0.832** |

Chance at top-1 is about 0.3%. Before deduplication the same run gave top-1 54.5% and AUC 0.845.
That gap is how much the duplicates inflated the score.

### Cross-character retrieval: style without help from character looks (2026-10-10)

- **Data**: the same deduplicated corpus, restricted to the 2,532 works that have Danbooru
  character tags (296 artists). Tags were fetched from the Danbooru API.
- **Cross-character top-1**: the gallery for each query holds only works that share **no**
  character with it. This measures style alone, because the subject cannot help.
- **Character pull**: the nearest work is by a *different* artist but shows a *shared*
  character.

| | Same-artist top-1 | Cross-character top-1 | Character pull |
|---|---|---|---|
| CSD, hub-corrected | 45.5% | **28.2%** | 2.9% |
| CSD, `--neutralize 1` | 45.6% | 28.1% | 3.4% |

**Character drives part of the score.** About 40% of the plain same-artist score comes from
artists drawing the same characters again. 28% is the honest pure-style figure.

**On human artwork the pull is small.** Different artists draw one character very differently,
so the nearest neighbour is rarely another artist's version of it. It is the other way round for
AI renders, where the same characters are repeated in every style (89% pull on r93, see
`--neutralize`). That is why `--neutralize` changes nothing here.

### Blind mixture clustering: the LoRA case

Each trial draws 2, 3 or 5 random artists, each with at least 5 works, and mixes their works
into one set. The set is clustered without the number of artists being given. The score is the
adjusted Rand index (ARI) against the artist labels, averaged over 60 draws: 1 is perfect,
0 is chance.

| Granularity (threshold) | 2 artists | 3 artists | 5 artists |
|---|---|---|---|
| period (0.35, meant for one artist) | 0.26 | 0.21 | 0.27 |
| fine (0.40) | 0.43 | 0.36 | 0.43 |
| **medium (0.47, default)** | **0.55** | **0.49** | **0.51** |
| coarse (0.55) | 0.46 | 0.41 | 0.35 |

`period` over-splits a mixture of different artists. Use it only inside one artist's work (see
"One artist over time").

**Distance (development run, 90 draws, before deduplication):**

| Distance | ARI at threshold 0.45 (2 / 3 / 5 artists) |
|---|---|
| Raw cosine | 0.48 / 0.48 / 0.47 |
| Hub-corrected | 0.50 / 0.46 / 0.56 |

**True number of artists given.** ARI was 0.59 / 0.55 / 0.53 with hub correction and only
0.22 / 0.28 / 0.27 without. Average linkage on raw cosine collapses into one giant cluster plus
singletons, and hub correction removes most of that failure.

**Full 300-artist set, true count given (k=300):**

| Method | NMI | ARI |
|---|---|---|
| Average linkage, raw cosine | 0.55 | 0.02 |
| Average linkage, hub-corrected | 0.70 | 0.17 |
| HDBSCAN (PCA-64), non-noise points only | 0.87 | 0.49 |

HDBSCAN left 49% of points as noise.

### Splitting one artist into periods: k-means (2026-10-10)

The period corpus above (8 artists with 30-60 works) plus 5 artists with 112-300 works, all
deduplicated: 13 artists. Score: adjusted mutual information (AMI, corrected for chance, so
different group counts compare fairly) between the groups and posting-time quartiles;
unassigned images count as single-image groups; permutation p < 0.05.

| Method | Mean AMI | Beyond chance | Largest group |
|---|---|---|---|
| medium (0.47) / auto | 0.077 / 0.075 | 6 / 6 of 13 | 75% / 74% |
| Cut at 0.35 (the old `period`) | 0.117 | 9 | 36% |
| Average linkage forced to 3 / 4 groups | 0.107 / 0.115 | 9 / 9 | 78% / 66% |
| Ward, 3 / 4 groups | 0.109 / 0.129 | 9 / 9 | 50% / 42% |
| **k-means, 3 groups** | **0.123** | **11** | 46% |
| k-means, 4 groups | 0.128 | 10 | 39% |

- k-means with 3 groups vs the 0.35 cut, per artist: AMI +0.006 (95% CI -0.029 to +0.041),
  better for 7 of 13. Time alignment is a tie.
- The difference is what happens to the rest: the 0.35 cut left 36%, 50%, 60% and 77% of the
  images unassigned for 4 of the 13 artists; k-means assigns every image.
- With about 50 works the k-means split depends on the seed (agreement between seeds ARI
  0.33-0.98, mean 0.66). The tool fixes the seed, so results repeat, but the boundaries are soft.
- `--granularity period` and the web app's "時期" now mean k-means into 3 groups (`--k` sets
  the number). The old cut is still available as `--threshold 0.35`.

### Choosing the cut automatically (2026-10-10)

The medium cut (0.47) was tuned on mixtures of 2-5 artists. On larger mixtures the best cut is
lower, and 0.47 chains many artists into a few big groups. Users rarely know how many artists a
gallery holds, so the default is now `auto`.

**Rule.** Cut the average-linkage tree at 0.20, 0.21 ... 0.60. Take the cut with the best
silhouette (hub-corrected distances, on up to 3,000 sampled images, with very similar images
counted once). Add 0.04, because the silhouette's best sits a little below the cut that best
matches artists. Never go above 0.47.

**First sweep.** Danbooru, deduplicated (3,000 images, 306 artists). Mixtures of m random
artists; ARI with the artists, small groups (< 3) counted as single images.

| Artists in the mix | 2 | 3 | 5 | 10 | 20 | 50 | 100 | 306 |
|---|---|---|---|---|---|---|---|---|
| Fixed medium (0.47) | 0.397 | 0.508 | 0.468 | 0.435 | 0.366 | 0.200 | 0.128 | 0.044 |
| Best fixed cut in hindsight | 0.433 (0.44) | 0.517 (0.48) | 0.468 (0.47) | 0.501 (0.44) | 0.444 (0.42) | 0.384 (0.38) | 0.302 (0.38) | 0.220 (0.34) |
| Silhouette alone | 0.525 | 0.415 | 0.339 | 0.288 | 0.373 | 0.332 | 0.261 | 0.174 |
| Silhouette + 0.04, at most 0.47 | 0.414 | 0.504 | 0.478 | 0.461 | 0.435 | 0.375 | 0.298 | 0.220 |

The largest jump between merge heights (a classic "elbow" rule) was useless (ARI near 0 from 10
artists up). Choosing the offset on half of the artists picked +0.04 once and +0.06 once; on the
other half the rule stayed within -0.02 to +0.12 of medium for 2-20 artists and was +0.13 to
+0.18 better for 50 and 100.

**Stacks of copies (found in review).** Folders full of near-copies or same-prompt variants broke
the first version: tight stacks look like perfect tiny groups to the silhouette, the cut fell to
0.24-0.35 and artists shattered (3 artists with 30% of images stacked x4: ARI 0.28, medium 0.57).
Counting very similar images once when choosing the cut fixes it. A guard at style cosine 0.92
still failed on looser variants (cosine 0.85-0.94); at 0.80 auto matched medium on every stacked
case tried.

**Final check** with the shipped code (guard 0.80), on fresh random draws. Cells: ARI with small
groups as single images / ARI over assigned images only / share unassigned.

| Set | Medium (0.47) | Auto |
|---|---|---|
| 3 artists, copy stacks (4 variants, 30-100% of images, cosine 0.85-0.98) | 0.36-0.68 | -0.04 to +0.00 vs medium, cut 0.47 |
| 10 artists, copy stacks | 0.39-0.51 | -0.01 to +0.00 vs medium, cut 0.47 |
| Raw Danbooru (not deduplicated), 2 artists | 0.399 / 0.524 / 18% | 0.443 / 0.601 / 19% |
| Raw, 5 artists | 0.488 / 0.514 / 4% | 0.498 / 0.528 / 5% |
| Raw, 20 artists | 0.295 / 0.299 / 2% | 0.338 / 0.361 / 5% |
| Raw, 50 artists | 0.186 / 0.187 / 1% | **0.358 / 0.383 / 6%** |
| Deduplicated, 20 artists | 0.361 / 0.367 / 2% | 0.392 / 0.415 / 5% |
| Deduplicated, 50 artists | 0.166 / 0.166 / 1% | **0.379 / 0.422 / 9%** |
| Deduplicated, 306 artists | 0.044 / 0.044 / 0% | **0.208 / 0.222 / 6%** |

- **The cost is more unassigned images** on large mixtures (5-9% against 1-2%): auto makes
  more, smaller groups, and groups under 3 images count as unassigned.
- **One artist over time** (the 13 artists above, raw folders): auto's groups followed posting
  time beyond chance for 7 of 13, medium for 5, period for 9. Auto left at most 8% unassigned;
  period left 50-95% unassigned for 4 artists. `period` stays the advice for splitting one
  artist by time, then review the groups.
- 3,000 images take about 3 s; 8,000 about 4 s (8 CPU cores).

**Artists with many works** (5 Danbooru artists, 112-300 general-rated works each, sampled evenly
over their history, deduplicated):

- **One artist alone:** auto picked 0.45-0.47 for 4 of 5 artists, the same groups as medium. Both
  put 79-100% of the images in one group, so neither splits periods; `period` did (5-21 groups,
  NMI with posting time 0.12-0.16, all beyond chance). For the most varied artist
  (onikobe_rin) auto picked 0.41 and made 46 groups (medium 14).
- **Two artists, 300 + 300:** auto chose 0.47 for all 10 pairs, so it matched medium (ARI
  0.001-0.971 depending on how alike the two artists are).
- **One artist plus 15 works of another** (a scraped set with strays), 60 draws: mostly identical
  to medium, but the varied artists drag the cut down. yaegashi_nan + 15 of ojipon gave ARI
  0.03-0.06 against 0.37-0.50 for medium in all 3 draws. On average auto was 0.03 below medium
  here.
- Requiring the silhouette's best to beat its value at 0.47 by a margin before leaving medium did
  not separate the cases: a margin of 0.05 fixed these pairs (+0.03) but cost 20-artist mixtures
  0.07, and 0.08 gave up the gains at 50-306 artists. The rule was left as it is.
- **Advice:** for one artist's folder, if auto returns many small groups, use `medium` (or
  `period` to split by time).

**Limits of this evidence** (from a Sonnet review):
- All of it is one Danbooru corpus with about 10 works per artist, and the 306-artist row is a
  single draw on the data the offset was tuned on.
- Not tested:
  - another source, such as Pixiv or AI renders (the local sets have 1-2 works per label);
  - real sets above 8,000 images.
- Checked afterwards:
  - **Sampling** (silhouette on 3,000 of the 3,245 raw images): 8 sampling seeds chose 0.37
    seven times and 0.36 once; the full silhouette chose 0.37.
  - **The micro-group path** (forced on the same 3,245 images with 800 or 1,600 micro-groups):
    auto chose 0.40-0.42 instead of 0.37 and reached ARI 0.11-0.15 instead of 0.24. That is
    still well above medium on that path (0.04).
- `--granularity medium` keeps the old behaviour.

### Searching with several example images (2026-10-10)

Task: given a few works by one artist, find the rest of that artist's works in a library.

Library: the deduplicated Danbooru corpus (3,000 images) plus 13 artists with 30-60 works each
(the period corpus), 3,689 images in all. For each of the 13 artists, 5 random draws of the
examples; the targets are that artist's other works. AP = average precision; paired bootstrap
95% CI against the mean vector.

| Scoring | 3 examples | 5 examples | 10 examples |
|---|---|---|---|
| Mean vector (`--combine` before) | 0.345 | 0.388 | 0.427 |
| Logistic regression, examples vs 1,000 random library images | **0.400** (+0.055 [+0.038, +0.071]) | **0.454** (+0.066 [+0.042, +0.090]) | **0.544** (+0.116 [+0.092, +0.141]) |

- Regularisation: C = 1 was best (C = 0.1 and 10 were tried); 1,000 negatives beat 300.
- Scoring each image by its best match among the examples (max) was worse than the mean vector
  every time (-0.04 to -0.09 AP). The mean of the top 3 or 5 matches was no better than the mean.
- When the examples come from an artist's earliest third and the targets are the latest third,
  the gain shrinks to +0.00 to +0.02 (every CI touches 0): a model learned from one period does not
  reach far into another.
- On the plain Danbooru corpus (about 12 works per artist) the gain is smaller: +0.014 AP with 3
  examples, +0.019 with 5.

`search --combine` now uses the learned model from 3 example images up.

### More than 8,000 images (2026-10-10)

Average linkage needs an n x n distance matrix, which is too large above 8,000 images. Until
now the tool then switched to HDBSCAN on PCA-64 vectors, which ignored the threshold (the web
app's granularity did nothing) and left half of the images unassigned.

The large-set path now runs k-means (random init) into 8,000 micro-groups and joins whole
micro-groups by average linkage. Distances between micro-groups are exact: the mean
hub-corrected distance between their images is `1 - S_a.S_b / (n_a n_b)` plus the mean density
terms, where `S` is a group's vector sum. The tree is kept, so another threshold only cuts it
again.

Test: the 3,245-image Danbooru corpus (300 artists), with the micro-group count lowered to keep
the ratio realistic. 500 parts is about 6 images per micro-group, like 8,000 parts for 50,000
images. Unassigned images count as single-image groups in the ARI. Three k-means seeds.

| Method, threshold 0.35 | ARI with artists | Unassigned |
|---|---|---|
| Full average linkage (reference, possible below 8,000) | 0.255 | 7% |
| Micro-groups, 1,600 parts (2 images each) | 0.222 +- 0.006 | 6% |
| Micro-groups, 500 parts (6.5 images each) | 0.180 +- 0.007 | 4% |
| Random sample of 500 + join nearest group (tried) | 0.16 | 10-13% |
| Old fallback: HDBSCAN on PCA-64 | 0.223 | **49%** |

- Micro-groups beat clustering a sample and joining the rest at every size tried.
- Weighting micro-groups by size in the linkage (own nearest-neighbour-chain code) changed ARI
  by at most 0.01, so the plain linkage on the exact distances is used.
- k-means++ init took 302 s on 50,000 vectors; random init takes 11 s and costs about 0.01 ARI.
- Time on 50,000 vectors (8 CPU cores): 39 s for the first grouping, 0.5 s for each new
  threshold.
- At 0.47 on 300 artists every method scores near 0 (ARI 0.03-0.05): the medium cut chains
  hundreds of artists into a few large groups. Use `fine` or `period` for big mixed galleries.

### Input variants (2026-10-09)

This is a paired comparison on the same 2,941 deduplicated images. The bootstrap gives the
95% CI of the per-image difference against the default (centre crop, 224 px).

| Variant | Cost | Top-1 | Top-10 | Mixture ARI (medium) |
|---|---|---|---|---|
| centre 224 (default) | 1x | 46.2% | 70.4% | 0.51 / 0.50 / 0.47 |
| `--crop tiles` (up to 3 crops along the long side) | 1.87x crops | +1.0 [+0.0, +2.0] | **+1.2 [+0.3, +2.0]** | 0.51 / 0.50 / 0.46 |
| `--resolution 336` (interpolated position embeddings) | about 2.5x | +0.8 [-0.3, +1.8] | **+1.3 [+0.2, +2.2]** | 0.50 / 0.50 / 0.46 |

Both variants give a small, real gain in retrieval and no change in clustering. The default
stays at centre 224, because embedding there costs half as much or less. For the best
search-by-image results, use `--crop tiles` or `--resolution 336`. Vectors from different
variants are cached separately and cannot be mixed.

## One artist over time (2026-10-10, 13 artists)

This is the LoRA case where one artist's style changes between periods.

- **Data**: 18 prolific Danbooru artists, general-rated only, with posts sampled evenly across
  each artist's posting history (10 pages, up to 60 works each). Near-duplicates were removed,
  and the 13 artists who kept 30 or more works were tested.
- **Labels**: none exist for "periods". Posting order (post id) stands in for time.
- **Mantel test**: Spearman correlation between hub-corrected style distance and time-rank
  difference, with a permutation p-value.
- **Groups against time**: the NMI between the style groups and posting-time quartiles. A star
  marks p < 0.05 against shuffled times. Each cell gives the number of groups, then the NMI.

| Artist | n | Mantel r | cut 0.35 (`period`) | cut 0.40 (`fine`) | cut 0.47 (`medium`) |
|---|---|---|---|---|---|
| bow_(bhp) | 48 | -0.03 | 30g 0.40 | 20g 0.31 | 8g 0.19 |
| ebifurya | 51 | +0.24* | 4g 0.27* | 2g 0.14* | 2g 0.14* |
| hammer_(sunset_beach) | 53 | +0.28* | 6g 0.35* | 1g 0.00 | 1g 0.00 |
| haruyama_kazunori | 60 | +0.14* | 33g 0.37 | 20g 0.31 | 8g 0.18 |
| itomugi-kun | 54 | +0.27* | 15g 0.50* | 9g 0.44* | 2g 0.26* |
| kanon_(kurogane_knights) | 59 | +0.17* | 2g 0.03 | 1g 0.00 | 1g 0.00 |
| matsunaga_kouyou | 46 | +0.14* | 3g 0.07 | 1g 0.00 | 1g 0.00 |
| naga_u | 60 | +0.11* | 9g 0.27* | 4g 0.12 | 2g 0.03 |
| ojipon | 59 | +0.10* | 22g 0.38* | 11g 0.26* | 5g 0.14 |
| onikobe_rin | 60 | +0.20* | 46g 0.49* | 26g 0.44* | 9g 0.26* |
| pageratta | 30 | +0.43* | 11g 0.46* | 7g 0.42* | 3g 0.34* |
| rebecca_(keinelove) | 60 | +0.26* | 5g 0.26* | 2g 0.04 | 1g 0.00 |
| yaegashi_nan | 49 | +0.12* | 12g 0.36* | 5g 0.18* | 2g 0.04 |
| **significant** | | **12 / 13** | **9 / 13** | 6 / 13 | 4 / 13 |

- **Drift is real.** Works far apart in time differ more in CSD style for 12 of 13 artists.
- **The default `medium` cut is too coarse here.** It usually leaves one artist in one group,
  because the drift is gradual. Groups at 0.35 follow posting time for 9 of 13 artists. This is
  the basis for the `period` granularity.
- **0.35 fragments some artists.** Some artists split into many small groups: onikobe_rin went
  to 46 groups from 60 works. Look at the time strips in the web app and merge groups by hand,
  or raise the cut.

## Same subjects in many styles: `--neutralize` (2026-10-09)

This is the style-exploration case, where the same characters are rendered in many styles.

- **Data**: 96 NovelAI V5 style recipes, each rendered with the same 2 characters, 192 SFW
  images. Labels are the recipes.
- **Problem**: before any correction, an image's nearest neighbour was the *same character in
  another style* 89% of the time, and its style twin only 10%. Even CSD style vectors are pulled
  strongly by character looks (hair colour, outfit).

| Correction | Twin is nearest | Recipe-pair AUC | Mixture ARI (Danbooru, 2/3/5 artists) | Period Mantel r |
|---|---|---|---|---|
| none (default) | 10% | 0.827 | 0.55 / 0.50 / 0.48 | +0.19 |
| `--neutralize 1` (flatten the strongest direction, keep the mean) | **46%** | **0.980** | 0.02 / 0.14 / 0.27 | +0.12 |
| centring each character separately (needs labels) | 51% | 0.976 | (n/a) | (n/a) |

Removing the strongest direction of variation has opposite effects depending on the collection:

- **Same subjects, many styles**: the strongest direction is the subject, so removing it fixes
  style search. Danbooru
  same-artist retrieval was unchanged (top-1 46.3% vs 46.3%).
- **Different artists mixed**: the strongest direction *is* the style difference, so removing it
  wrecks clustering.

That is why `--neutralize` is opt-in. It is meant only for collections where the same characters
recur across styles.

**Second check, different characters.** 131 other recipes were each rendered with Carlotta and
Changli; no Jane or Nicole image was involved. `--neutralize` learns nothing in advance. It
computes the direction from the collection itself, so it carries over:

| Correction | Twin is nearest | Same character is nearest | Recipe-pair AUC |
|---|---|---|---|
| none | 11% | 95% | 0.866 |
| `--neutralize 1` | 31% | 70% | **0.967** |
| `--neutralize 2` | 40% | 59% | 0.967 |

## Near-duplicate threshold (2026-10-09)

Pairs were checked by eye at each score of min(style cos, content cos):

| Score | What the pairs were |
|---|---|
| >= 0.97 | Recolours, crops, frames of one picture |
| 0.95-0.965 | Mostly variants (7 of 8 sampled); 1 was a different picture of the same character |
| 0.92-0.95 | Often different poses of one character on the same plain background |

The product default is **0.95**, which is conservative so that it never drops valid training
images. `bench` removes near-duplicates at 0.92 to keep benchmark numbers honest.

## Pixiv: followed AI-illustration accounts (2026-10-09)

- **Data**: 467 all-ages works by 176 AI-illustration accounts (median 2 works each). The
  vectors came from the research pipeline.
- **Labels**: the account.
- **Mixtures**: too few works per account for the mixture test.

| Score | Raw cosine | Hub-corrected |
|---|---|---|
| Top-1 | 17.1% | **19.1%** |
| Top-10 | 45.4% | **48.6%** |
| Pair AUC | 0.745 | **0.799** |

Hub correction helps on AI illustration as much as on human artwork.

## Taste model (2026-10-09)

The question is whether `taste` (and the web app's Like / Dislike) reproduces the research
result.

- **Data**: one person's 140 like/dislike votes on single NovelAI renders (81 liked).
- **Protocol**: 5-fold cross-validation repeated 5 times.

| Pipeline | CV AUC |
|---|---|
| research (scaler, PCA-20, logistic C=0.1) | 0.761 |
| **style-atlas `train_taste`** (PCA-20, scaler, balanced logistic C=0.5) | **0.769** |
| same, C between 0.05 and 1.0 | 0.766-0.778 |

The product matches the research result. Two known limits, from the research: the model does
not rank *degrees* of liking among good candidates, and it dropped to chance on images from a
new generator.

## Which image to rate next (2026-10-10)

This is a pool-based simulation on the same 140 real votes:

- Each trial holds out 40 images and uses the other 100 as the pool.
- A strategy picks which image is rated next, and its real vote is revealed.
- The score is the AUC on the held-out 40 after n ratings, averaged over 50 trials.

| Strategy | 10 | 15 | 20 | 30 | 40 | 60 |
|---|---|---|---|---|---|---|
| random | 0.615 | 0.668 | 0.680 | 0.717 | 0.730 | 0.749 |
| **farthest-first** (least like anything already rated) | **0.691** | 0.682 | **0.702** | 0.710 | 0.731 | 0.755 |
| most uncertain (classic active learning) | 0.622 | 0.660 | 0.680 | 0.708 | 0.735 | 0.755 |
| uncertain + diverse | 0.685 | 0.680 | 0.699 | 0.719 | 0.733 | 0.734 |

- **Farthest-first** gets to AUC about 0.69 after 10 ratings; random picking needs about 25.
- **From 40 ratings on**, every strategy scores the same.
- **Uncertainty sampling** does not beat random.

The web app's "rate the most useful next image" therefore uses farthest-first. The model now
trains from 5 ratings of each kind, down from 8.

## Tried and rejected

### Subtracting the CSD content head (2026-10-09)

CSD outputs a style vector and a content vector. On the Danbooru corpus the two heads carry
almost the same information, so subtracting content buys almost nothing:

- Their pairwise similarities correlate at 0.95.
- Content vectors find the same artist as often as style vectors do (top-10 74.7% vs 74.7%,
  before deduplication).

The approaches tried:

- **Regressing content out of style** (ridge, then the residual): top-10 rose 74.7 to 76.0%
  and AUC 0.844 to 0.867, but clustering at the tuned thresholds collapsed (ARI 0.5 to 0.2).
  That scale change would need new thresholds for a gain of about 1 point.
- **Subtracting content similarity** (`hub(S) - b * hub(C)`): slightly worse at every b tried.

Not adopted. The content vectors are still used, for near-duplicate detection.

### Clustering variants (2026-10-09)

The test is the blind-mixture ARI over 60 draws per size on the deduplicated corpus. The
differences below about 0.02-0.03 are within noise.

| Variant | 2 / 3 / 5 artists |
|---|---|
| **average linkage, CSLS k=10, cut 0.47 (default)** | 0.51 / 0.50 / 0.47 |
| CSLS k=5 | 0.51 / 0.48 / 0.44 |
| CSLS k=20 | 0.49 / 0.50 / 0.49 |
| complete linkage, cut 0.60 / 0.70 | 0.37 / 0.26 / 0.20 and 0.12 / 0.08 / 0.06 |
| default, then reassign each image to its nearest group centre | 0.52 / 0.51 / 0.48 |

None of these beats the default by more than noise, so the limit is the embedding and not the
grouping algorithm.

### MegaStyle-Encoder (Tencent, 2026) instead of CSD (2026-10-10)

MegaStyle is a SigLIP so400m-384 model fine-tuned for style similarity on 1.4M synthetic
text-to-image style pairs. HF `Gaojunyao/MegaStyle`, revision 8ac053fb.

- **Reported**: on its own synthetic StyleRetrieval benchmark, mAP@1 87.3 against 45.6 for CSD.
- **How it was run**: exactly as the reference `style_score.py` does it. SigLIP processor,
  `pooler_output`, L2 norm. The checkpoint was loaded with `strict=True` after stripping the
  `vision_model.` prefix that transformers 5.x does not use; with `strict=False` the weights load
  nothing, and silently.

| Test | CSD | MegaStyle | Concatenated |
|---|---|---|---|
| Danbooru same-artist top-1 (2,956 works, 297 artists) | **46.5%** | 11.5% | 34.6% |
| Danbooru cross-character top-1 | **28.2%** | 6.7% | 20.5% |
| Danbooru pair AUC | **0.832** | 0.679 | 0.785 |
| Blind 2/3/5-artist mixtures, best cut | **0.51** | 0.23 | 0.42 |
| NovelAI r93 recipe-pair AUC (2 characters) | **0.827** | 0.662 | 0.777 |
| Unseen characters, recipe-pair AUC | **0.866** | 0.671 | 0.796 |
| Period drift, Mantel r | **+0.185** | +0.055 | (n/a) |

MegaStyle is pulled less by characters: the same-character nearest neighbour drops from 89% to
70%. But it separates anime artists far worse, and combining it with CSD only dilutes CSD.

Its synthetic "styles" are coarse medium or movement categories, not artist-level anime styles,
so the published gain does not transfer here.

Not adopted. It would also add a non-commercial code licence and a 0.65 image/s CPU cost.

### Fixed "nuisance" directions learned from renders (2026-10-09)

The idea was nuisance attribute projection. Directions of "same recipe, different
character/seed" variation were learned from 2,204 within-recipe deviations in the other
NovelAI research rounds, then projected out of every vector, with r93 held out.

- **Held-out r93**: recipe-pair AUC went from 0.83 to 0.99 with 8 directions. Danbooru top-1
  rose +1.25 points (paired CI +0.3 to +2.2), and the mixture ARIs held.
- **Why that was misleading**: r93 uses the same two characters as the training rounds. With
  directions trained without any Carlotta or Changli image, the unseen pair did not improve at
  all: AUC 0.866, then 0.848 at 8 directions.
- **What the directions are**: they encode "Jane vs Nicole", not general subject variation.

Not adopted. The per-collection `--neutralize` does generalise; see above.

## Demo: 3 artists, 10 works each

```
style-atlas cluster demo3 --export copy
-> 4 styles, 0 unassigned
   abubu  10 -> style_01
   dayama 10 -> style_02
   inoino  7 -> style_03, 3 -> style_04   (the 3 are copies of one picture)
```

The default `auto` picks the same cut (0.47) and the same 4 groups (ARI 0.88). Before the
near-copy guard it picked 0.43 and split dayama 5 + 5 (ARI 0.73): the 3 copies of one inoino
picture were enough to drag the cut down.
