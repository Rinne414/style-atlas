# Python API

Everything the CLI does is available as plain functions. Vectors are unit-length float32 numpy
arrays, so you can mix them with your own code.

```python
from pathlib import Path

from styleatlas.atlas import EncodeOptions, build_atlas
from styleatlas.cluster import cluster_styles, outlier_scores
from styleatlas.duplicates import near_duplicate_groups
from styleatlas.search import search
from styleatlas.safety import limit_resources

limit_resources(threads=8)                      # optional: cap CPU threads, lower priority
opts = EncodeOptions(device="auto")             # "cpu", "cuda"; crop="tiles"; resolution=336
atlas = build_atlas(Path("D:/lora/artistX"), opts, progress=print)

atlas.paths        # list[Path], images that could be read
atlas.style        # (n, 768) style vectors
atlas.content      # (n, 768) content vectors (used for near-duplicates)

groups = cluster_styles(atlas.style)            # cut chosen from the data; threshold=0.47, n_clusters=3
groups.params["threshold"]                       # the cut that was used
periods = cluster_styles(atlas.style, method="kmeans", n_clusters=3)  # one artist's periods
for g in groups.clusters:
    print(g.id, g.size, atlas.rel(g.medoid))    # medoid = most central image of the group
groups.labels                                    # cluster id per image, -1 = unassigned

dups = near_duplicate_groups(atlas.style, atlas.content)   # [[i, j, ...], ...]
odd = outlier_scores(atlas.style)                          # higher = less like the rest

gallery = build_atlas(Path("D:/gallery"), opts)
hits = search(atlas.style[:1], gallery.style, top=10)[0]   # whitened + hub-corrected ranking
plain = search(atlas.style[:1], gallery.style, whitened=False)[0]  # plain CSD space
print([(gallery.rel(h.index), round(h.cosine, 3)) for h in hits])

# several examples of one style: from 3 up, a model learned from them ranks the gallery
more = search(atlas.style[:10], gallery.style, top=100, combine=True)[0]
```

## Embedding images you already have in memory

```python
from PIL import Image

from styleatlas.atlas import get_encoder

encoder = get_encoder(opts)                     # loaded once per process
vectors = encoder.encode([Image.open("a.png").convert("RGB")])
vectors.style.shape                             # (1, 768)
```

## Writing the 3D map yourself

```python
from styleatlas.report import write_map

write_map(atlas, groups, Path("map.html"), time_source="name")
```

## Look measures

```python
from styleatlas.atlas import EncodeOptions, measure_looks
from styleatlas.look import LOOK_NAMES, describe, difference, measure, profile

looks = measure_looks(paths, EncodeOptions())   # (n, 6), cached; LOOK_NAMES order
z = profile(looks, member_indices)              # a group against the whole set, in SDs
describe(z)                                     # "cooler, more line work" ("" if nothing stands out)
difference(looks_a, looks_b)                    # B minus A in pooled SDs
measure(pil_image)                              # one image, no cache
```

## The search space

`styleatlas.whiten.whiten(vectors)` maps CSD vectors into the space search ranks in (learned from
306 Danbooru artists; see BENCHMARKS.md, "Search whitening"). Keep it for ranking: distances
compared with thresholds (groups, duplicates, the Style Gate) are meant for plain CSD vectors.

## Comparing two sets of images

```python
from styleatlas.metrics import StyleScale, group_difference

distance, p_value = group_difference(set_a_vectors, set_b_vectors)
StyleScale().verdict(distance)   # "same style" / "related" / "clearly different"
```

The default scale comes from one person's calibration on NovelAI renders. Get your own with
`style-atlas calibrate`, or with `metrics.split_half_noise(vectors)` on a set you know is one
style, and pass it as `StyleScale(noise_floor=...)`.
