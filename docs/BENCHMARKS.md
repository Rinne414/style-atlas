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
| cut 0.35 (`period` until 0.8.0) | 0.26 | 0.21 | 0.27 |
| fine (0.40) | 0.43 | 0.36 | 0.43 |
| **medium (0.47, the default until 0.7.0)** | **0.55** | **0.49** | **0.51** |
| coarse (0.55) | 0.46 | 0.41 | 0.35 |

A 0.35 cut over-splits a mixture of different artists. The default is now `auto`, and `period`
is now k-means within one artist. Both are covered further down.

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

Caveats (from a Sonnet review):
- **Scoring.** The "beyond chance" counts (11 vs 9) partly depend on scoring unassigned images
  as single-image groups, which penalizes the cut. The safe reading is a tie on time alignment.
  The practical difference is coverage.
- **Coverage is not always good.** k-means also puts sketches and off-style images into a
  period. Pair it with `--drop-outliers N` (or the 離群 tab and X in the web app) to set those
  aside. Trimming could not be scored fairly with this metric.
- **Three periods is a convention.** Choosing k by silhouette (2-6) did worse (mean AMI 0.086)
  and picked k = 2 for 9 of 13 artists. Centering the vectors per artist changed nothing (0.120).
- **Small groups.** A period can come out small (4 of 46 images for one artist). Periods under
  `--min-size` (3) count as unassigned, and `cluster` warns about groups under 8.
- **Below about 100 images** the boundaries move with the seed; `cluster` prints a note.
- Tried afterwards, no gain (13 artists, k-means with 3 groups, mean AMI 0.126 as is):
  - Removing the artist's own 1-5 strongest directions first (as `--neutralize` does):
    0.078 / 0.048 / 0.015, worse every time. The time signal lives in those directions.
  - Keeping only the top 2-50 principal components: 0.108-0.119 (-0.006 to -0.018). It is much
    more stable across seeds (agreement 0.90-1.00 at 2-5 components, against 0.67), but the
    seed is fixed anyway.
  - The search whitening: -0.005 (above).

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

**Finding the strays instead (2026-10-10).** The setup was the same, run on all 20 ordered
pairs of the 5 big artists: one artist (deduplicated, 95-299 works) plus 15 works of another.
- **Automatic** (no help):
  - auto grouping reached ARI 0.18 on average;
  - outlier scores found half of the strays in their top 30 (kNN k=10 50%, k=30 55%, distance
    to the centroid 56%). The strays look like each other, so none of them is "unlike its
    neighbours";
  - the most separated k-means sub-group held most strays in 11 of 20 pairs. In the others the
    artist's own period was as far from the rest (separation 0.16-0.26) as the strays were.
    Another artist and another period are about equally far apart in CSD.
- **From strays the user has spotted**:
  - one clicked stray had 63% of the other strays among its 12 nearest images (86% among 30);
  - three strays searched as one set (`--combine`) put 98% of the rest in the top 30 (worst
    pair 75%).
- So the web app's excluded list has **Find more like these**: exclude two or three strays
  with X, then the button lists the images most like them.

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

### Search whitening (2026-10-10)

CSD vectors vary within one artist's work along some directions more than others. Within-class
covariance normalization (WCCN) learned from labelled artists turns those directions down: a
fixed 768 x 768 linear map, then re-normalization. It is used for **search ranking only**.
Everything compared with a fixed threshold (groups, duplicates, the Style Gate, taste) stays in
plain CSD space, where those thresholds were set.

**Held-out artists only.** Danbooru, deduplicated (3,000 images, 306 artists), 5 folds split by
artist: learn on 4/5 of the artists, test retrieval (hub-corrected, as the tool ranks) on the
others.

| Map | Top-1 | Top-10 | Pair AUC |
|---|---|---|---|
| None (plain CSD) | 0.617 | 0.855 | 0.845 |
| WCCN, shrinkage 0.1 / **0.3** / 1.0 | 0.650 / **0.649** / 0.649 | 0.891 / 0.893 / 0.891 | 0.860 / 0.873 / 0.884 |
| LDA to 256 dims, shrinkage 1.0 | 0.658 | 0.890 | 0.888 |

Top-1 gain of WCCN 0.3: +3.1 points (95% CI +1.7 to +4.5).

**Transfer.**
- *Artists with many works*, learned without them (16 artists, 1,658 images): top-1
  0.859 -> 0.878 (+1.9, CI +0.5 to +3.3), AUC 0.755 -> 0.783.
- *The owner's NovelAI renders* (285 recipes, each drawn with 2 characters; is the nearest other
  render the same recipe?): WCCN 0.3 went 0.040 -> 0.054 (+1.4, CI +0.4 to +2.6), AUC 0.904 ->
  0.915. LDA was slightly worse here (-0.7), so WCCN 0.3 was chosen. It was the only map that
  helped on all three.
- *Through the shipped `search()`*, with a map learned without the 13 test artists, hidden in a
  4,465-image library:

| | Plain CSD | Whitened |
|---|---|---|
| One example, top-1 / top-10 | 0.765 / 0.950 | **0.812** / 0.942 |
| 5 examples (learned model), AP | 0.546 | **0.616** |
| 10 examples, AP | 0.677 | **0.729** |

The shipped map (`src/styleatlas/data/whiten_csd.npz`, 2.2 MB) is fit on all 306 artists by
`scripts/fit_whitening.py`. It was learned with the default encoder settings (centre crop, 224
px); with `--crop tiles` or 336 px it is untested. `search(..., whitened=False)` ranks in plain
CSD space.

Not used for periods: k-means periods on whitened vectors (map learned without the 13 artists)
changed AMI with posting time by -0.005 (CI -0.04 to +0.04), better for only 4 of 13. Whitening
turns down within-artist variation, which is where periods live.

Not used for taste: on the owner's 140 votes, the taste model's cross-validated AUC fell from
0.785 to 0.735 on whitened vectors (5 x 5-fold, C 0.1 or 0.5). What a person likes is partly in
the variation whitening turns down.

Not used for grouping (yet). Danbooru mixtures of held-out artists (5 folds): in the whitened
space one fixed cut, 0.90, was best for every mixture size. It beat the best plain cut at each
size by +0.06 to +0.10 ARI:

| Artists | 2 | 5 | 20 | 50 |
|---|---|---|---|---|
| Plain, best fixed cut | 0.414 | 0.496 | 0.416 | 0.357 |
| Whitened, cut 0.90 | 0.492 | 0.564 | 0.517 | 0.420 |

But on the owner's Anima renders (16 recipes x 8 renders, one model) whitened distances are
smaller: the largest merge was 0.66, so 0.90 put everything in one group. Silhouette-based cuts in
the whitened space did worse than the fixed cut on Danbooru. A fixed cut needs calibration per
kind of collection, so grouping stays in plain space with `auto`. (No setting recovered the Anima
recipes in either space: the characters dominate, which is what `--neutralize` is for.)

### Single-image distances (the Style Gate's scale)

Danbooru, deduplicated: plain CSD distance (1 - cosine) between single images.
- Same artist: median 0.405 (middle half 0.31-0.51).
- Different artists: median 0.566 (0.48-0.67).
- At the Style Gate's default of 0.5, 72.5% of same-artist pairs and 31% of different-artist
  pairs fall below it.

### Query expansion for single-image search (tried, not used)

Average query expansion: search, add the top 3 hits to the query, search again, all in the
whitened space.
- **Danbooru, artist-held-out:** more right answers in view. Precision@10 went 0.360 -> 0.406,
  precision@5 0.481 -> 0.518 and mAP 0.351 -> 0.399, with top-1 unchanged. But queries that start
  wrong drift further: "at least one right in the top 10" fell 0.893 -> 0.840.
- **AI renders, where the nearest neighbours are often the same character:** it hurt.
  - Anima a03: top-1 0.555 -> 0.438, precision@10 0.179 -> 0.147.
  - NovelAI recipes: "any right in the top 10" 0.358 -> 0.268.

It is not used.

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

| Artist | n | Mantel r | cut 0.35 (the old `period`) | cut 0.40 (`fine`) | cut 0.47 (`medium`) |
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
  the basis for the first `period` granularity. Since 0.8.0 `period` is k-means (see
  "Splitting one artist into periods: k-means").
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

### Centring per character, without labels: `--ignore-characters` (2026-10-10)

The table above shows that centring each character separately did best, but it needed
character labels. CSD also returns a *content* vector, and k-means on it (k from 2 to 8, picked
by silhouette) finds the characters by itself: agreement with the true characters was ARI 0.98,
0.98 and 1.0 on the three sets below. Each image's style vector is then moved by its
character's offset from the overall mean (`metrics.SubjectCentring`).

Three sets of renders, labels = recipes. Top-1 is plain cosine; k-means ARI uses k = the number
of recipes.

| Set | Correction | Recipe-pair AUC | Same-recipe top-1 | k-means ARI |
|---|---|---|---|---|
| NovelAI, 96 recipes x 2 characters (192) | `--neutralize 1` | **0.980** | 48% | **0.29** |
| | `--ignore-characters` | 0.977 | **52%** | 0.28 |
| Anima, 16 recipes x 4 characters (128) | `--neutralize 1` | 0.754 | 58% | 0.08 |
| | `--ignore-characters` | **0.893** | **70%** | **0.36** |
| Anima, 7 recipes x 2 characters (28) | `--neutralize 1` | 0.857 | 75% | 0.35 |
| | `--ignore-characters` | **0.859** | **79%** | **0.40** |

- With two characters the two are about equal: the strongest direction *is* the line between the
  two characters. With four, one direction cannot hold them all, and centring is far better.
- Centring and then neutralizing gave no further gain.
- It always finds at least 2 subjects (k from 2 to 8, at most one per 5 images). The best
  content silhouette was 0.14-0.20 on the three character sets and 0.06 and 0.10 on two Danbooru
  artists' own work (271 and 300 images). That gap is too small for an automatic off switch, so
  the user turns it on.
- On mixed Danbooru artists centring is as harmful as neutralizing: the "characters" it finds are
  mostly the artists. k-means ARI fell from 0.42 to 0.00 with 2 artists and from 0.50 to 0.07
  with 5; with 20 it was unchanged. So it is opt-in too.
- The web app's 「忽略角色軸」 switch uses it since 0.14.0.
- A new image (a search query or a `--reference` image) is moved by the offset of its nearest
  character. A character the collection never showed gets a wrong offset; `--neutralize`, which
  learns no characters, is the safer choice there.
  - Measured on the Anima 4-character set, leaving one character out of the folder and querying
    with its renders (128 queries in all). Same-recipe top-1: plain 68%, nearest character's
    offset 71%, `--neutralize 1` 74%, no offset at all 76%.
  - Tried: giving no offset to a query farther from every character centre than 95% of the
    folder's images. Unseen-character queries reached 74%, and queries of known characters were
    unchanged (74%). The gain was one query in 32 for each held-out character, within noise, so
    it was not adopted.

## Readable look measures (2026-10-10)

`look.py` computes six image statistics per image on a copy whose long side is 256 px. The
question was which ones carry style, and which are redundant.

**Data**: 3,259 Danbooru works by 306 artists (about 11 each). ICC(1) is the share of a
measure's variance that lies between artists: 0 means the artist does not matter, 1 means every
work of an artist has the same value.

| Measure | ICC | Kept |
|---|---|---|
| detail (mean absolute Laplacian) | 0.417 | no: r = 0.97 with lines |
| **lines** (share of pixels with luma gradient > 0.12) | **0.402** | yes |
| palette (log of colours covering 90% of pixels) | 0.376 | no: r = 0.72 with colourfulness, -0.58 with flatness |
| dark lines (lines below median luma) | 0.369 | no: r = 0.80 with lines |
| **flatness** (share of pixels with luma gradient < 0.01) | **0.367** | yes |
| **colourfulness** (Hasler and Suesstrunk 2003) | **0.321** | yes |
| **brightness** (mean luma) | **0.320** | yes |
| **contrast** (luma standard deviation) | **0.263** | yes |
| **warmth** (mean red minus mean blue) | **0.133** | yes: scene-dependent, but it is what people ask about |

Among the six kept, the largest correlation is lines vs flatness (-0.51). The rest are below
0.4 in absolute value.

**Visual check** on 192 NovelAI renders: the five lowest and five highest images of each
measure were put side by side.
- lines: soft painting vs heavy line art and sketches;
- flatness: busy textured scenes vs flat colour and plain backgrounds;
- colourfulness: greyscale vs neon;
- warmth: blue night scenes vs red and orange light.

Each matched its name.

**Image size**: 80 of the renders (832 x 1216) were also measured from smaller copies.
- From a 512 px copy, nothing moved by more than 0.06 SD.
- From a 192 px copy, which is smaller than the 256 px measuring size, lines rose by 0.46 SD
  and flatness fell by 0.66 SD.
- Enlarging small images to 256 px first did not fix it: at 192 px both lines and flatness fell
  by about 0.3 SD, and at 96 px lines fell by 1.75 SD.
- So images are only ever shrunk, and the docs say to compare groups of similar sizes.

**Taste**: the look measures do not predict personal taste. On one person's 140 like/dislike
votes (81 liked):
- the six measures alone reached CV AUC 0.53;
- CSD alone (the taste model) reached 0.76;
- CSD plus the measures reached 0.75.

The single best measure was warmth, at AUC 0.39 (cooler images were liked slightly more). So
the taste model stays CSD-only, and the measures describe styles; they do not rank them.

**What it means for use**: a single image is noisy (most of the spread is within one artist:
scene, lighting, composition). Group means are what the product shows: the group cards, the
`clusters.json` profile and `compare` all compare means.

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

## Does a new image fit the folder? (2026-10-10)

When several images are dropped into the web app, each is placed in its closest group (by
centre) and called *inside* when it is as close as p% of that group's own images. This was
measured on the 20 ordered pairs of the 5 big Danbooru artists. The dataset was 80% of one
artist, grouped as the product groups it. The queries were the other 20% of that artist
and 20 works of another artist.

| Cut | Held-out works of the artist inside | Other artist inside |
|---|---|---|
| p80 | 59% | 7% |
| **p90 (used)** | **69%** | **15%** |
| p95 | 76% | 23% |
| p100 (the farthest member) | 81% | 55% |

Single images are noisy, so the page reports the share of a batch. More than half inside reads
as "mostly this folder's style", and a quarter or less as "mostly unlike it".

## Tried and rejected

### Look measures for periods (2026-10-10)

This was tested on 13 Danbooru artists (30-299 works), scored by AMI with posting-time quartiles
and k-means k=3. Each artist's six look measures were standardised and appended to the CSD
vector at three weights.

| Features | Mean AMI | Better than CSD |
|---|---|---|
| CSD (the product) | **0.124** | (n/a) |
| looks only | 0.030 | 2 of 13 |
| CSD + looks, weight 0.5 | 0.066 | 1 of 13 |
| CSD + looks, weight 1 | 0.034 | 1 of 13 |
| CSD + looks, weight 2 | 0.031 | 2 of 13 |

The measures follow scene and lighting more than an artist's drift over time, so periods stay
CSD-only.

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
