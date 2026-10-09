# Benchmarks

All numbers come from `style-atlas bench`, run on real data. Re-run them whenever the encoder,
the preprocessing or a default changes, and update this file in the same commit.

## Danbooru artists (2026-10-09)

- **Data**: 3,239 general-rated Danbooru works by 300 artists (median 12 per artist), 512 px
  thumbnails. Posts with minor or multi-panel tags were excluded when the corpus was collected.
- **Labels**: the artist. One artist's works vary in character, scene and period, so this is a
  hard test: the label is "who drew it", not "one fixed style".
- **Encoder**: CSD ViT-L at 224 px, centre crop.
- **Vectors**: computed by the research pipeline. They match `style-atlas embed` output with
  cosine 1.0000, checked on 6 images.
- **Command**: `style-atlas bench --npz <vectors> --trials 60`.

| Score | Raw cosine | Hub-corrected (CSLS, k=10) |
|---|---|---|
| Top-1 nearest neighbour, same artist | 52.8% | **54.5%** |
| Top-5 | 66.4% | **69.5%** |
| Top-10 | 71.8% | **74.4%** |
| Same-artist pair AUC | 0.790 | **0.845** |

Chance for top-1 is about 0.3%.

### Blind mixture clustering: the LoRA case

Each trial draws 2, 3 or 5 random artists (each with at least 5 works) and mixes their works into
one set. The set is clustered without being told how many artists it holds. The score is the
adjusted Rand index (ARI) against the artist labels, averaged over 60 draws: 1 is perfect and
0 is chance.

| Granularity (threshold) | 2 artists | 3 artists | 5 artists |
|---|---|---|---|
| fine (0.40) | 0.42 | 0.41 | 0.49 |
| **medium (0.47, default)** | **0.47** | **0.49** | **0.51** |
| coarse (0.55) | 0.36 | 0.41 | 0.31 |

The same test, run in development on 90 draws, compared distances:

| Distance | ARI, threshold 0.45 (2 / 3 / 5 artists) |
|---|---|
| Raw cosine | 0.48 / 0.48 / 0.47 |
| Hub-corrected within the set | 0.50 / 0.46 / 0.56 |

With the true artist count given, hub-corrected distance reached ARI 0.59 / 0.55 / 0.53 and raw
cosine only 0.22 / 0.28 / 0.27. Average linkage on raw cosine collapses into one giant cluster
plus singletons; hub correction removes most of that failure.

On the full 300-artist set with the true count given (k=300), the results were:

| Method | NMI | ARI |
|---|---|---|
| Average linkage, raw cosine | 0.55 | 0.02 |
| Average linkage, hub-corrected | 0.70 | 0.17 |
| HDBSCAN (PCA-64), non-noise points only | 0.87 | 0.49 |

HDBSCAN left 49% of the images as noise.

### What this means in practice

- **Within one artist's work**, CSD style vectors separate artists well above chance, but not
  perfectly. Many artists share a look, and one artist's work spans several looks. An ARI of
  about 0.5 on mixed real artwork means the groups are useful to review, not final.
- **On a LoRA dataset**, the content (pose, outfit, scene) usually varies less than across these
  Danbooru works, so groups come out cleaner. In the demo below, 30 works by 3 artists split
  exactly by artist, and one artist's works split again into two groups (7 and 3).
- **Always look at the groups**: open `map.html`, or the `--export` folders, before deleting
  anything.

## Demo: 3 artists, 10 works each

```
style-atlas cluster demo3 --export copy
-> 4 styles, 0 unassigned
   abubu  10 -> style_01
   dayama 10 -> style_02
   inoino  7 -> style_03, 3 -> style_04
```
