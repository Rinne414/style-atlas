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

## One artist over time (2026-10-09)

This is the LoRA case where one artist's style changes between periods.

- **Data**: 8 prolific Danbooru artists, general-rated only, with posts sampled evenly across
  each artist's posting history (10 pages, 60 works each). Near-duplicates were removed. Six
  artists kept 46-60 works; dairi was mostly sprite variants (11 left), so it was skipped.
- **Labels**: none exist for "periods". Posting order (post id) stands in for time.

**Mantel test.** It asks whether works far apart in time differ more in style. It uses the
Spearman correlation between hub-corrected style distance and time-rank difference, with a
2,000-permutation p-value:

| Artist | n | Mantel r | p |
|---|---|---|---|
| ebifurya | 50 | +0.24 | 0.002 |
| hammer_(sunset_beach) | 52 | +0.25 | 0.002 |
| haruyama_kazunori | 60 | +0.14 | 0.002 |
| matsunaga_kouyou | 46 | +0.14 | 0.002 |
| naga_u | 60 | +0.11 | 0.002 |
| yaegashi_nan | 49 | +0.12 | 0.004 |
| mizuki_hitoshi | 19 | +0.15 | 0.036 |

CSD sees each artist's style drift over time.

**Groups against time.** The score is the NMI between the style groups and posting-time
quartiles. A star marks p < 0.05 against shuffled times. Each cell gives the number of groups,
then the NMI.

| Artist | cut 0.47 (medium) | 0.40 | **0.35 (`period`)** | 0.30 | k=3 |
|---|---|---|---|---|---|
| ebifurya | 2g 0.14* | 2g 0.14* | 4g 0.28* | 11g 0.35* | 0.26* |
| hammer | 1g | 1g | 6g 0.34* | 14g 0.48* | 0.27* |
| haruyama_kazunori | 8g 0.18 | 20g 0.31 | 33g 0.37 | 49g 0.47 | 0.06 |
| matsunaga_kouyou | 1g | 1g | 3g 0.07 | 9g 0.27* | 0.07 |
| naga_u | 1g | 4g 0.12 | 9g 0.27* | 19g 0.34* | 0.08 |
| yaegashi_nan | 1g | 5g 0.18* | 12g 0.36* | 22g 0.43* | 0.13* |

At the default cut most artists stay in one group, because the drift is gradual. At 0.35, groups
follow time for 4 of 6 artists with a manageable number of groups. 0.30 fragments the set.
haruyama_kazunori varies a lot, but not in step with time. This test is the basis for the
`period` granularity.

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

## Demo: 3 artists, 10 works each

```
style-atlas cluster demo3 --export copy
-> 4 styles, 0 unassigned
   abubu  10 -> style_01
   dayama 10 -> style_02
   inoino  7 -> style_03, 3 -> style_04   (the 3 are copies of one picture)
```
