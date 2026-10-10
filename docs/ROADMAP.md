# Roadmap and open questions

(The author's working notes: decisions still to make, measured limits, ideas.)

## Decisions waiting for the owner

1. **"3D 圖"**: which 3D views did friends mean? Both are now in the tool.
   - The style-similarity map: a t-SNE/UMAP layout with floating thumbnails.
   - The research catalog's metric view: taste x originality x distance. This is the map's
     "measures" layout, which uses `--reference` for originality.
2. **Licence and visibility.** The repository is private and its licence is undecided. Licences
   of third-party pieces:
   - CSD weights: CC-BY-4.0. They are downloaded at runtime and need attribution.
   - CSD code: MIT. It is not vendored.
   - three.js: MIT. It is vendored, with its licence file.
3. **Distribution to friends.** Options, from simplest to most work:
   - Give them repo access and `scripts\setup.bat`. This works today.
   - Publish a portable Windows zip (embedded Python plus wheels) like `sd-image-sorter` does.
   - Publish to PyPI.
4. **Integration.** Should style-atlas become a module inside `sd-image-sorter`, which already has
   a gallery, tagging and similarity tools, or stay a separate tool?
5. **README screenshots.** For now the README shows the real interface on generated abstract
   images (`scripts/make_demo_images.py`), so no artwork is involved. Real art would show the
   tool better. Should the owner's own renders, or public-domain art, replace them?
6. **External anime benchmark.** LSASRD (CVPRW 2022) has 20,937 images from 190 anime works, with
   a cross-role protocol. It would be the strongest public test of "style, not character". Access
   needs a signed release agreement e-mailed to the authors, so only the owner can request it:
   https://github.com/nkjcqvcpi/ASR

## Known limits, measured

All of these are in `docs/BENCHMARKS.md`.

- **Mixed artists**: clustering of 2-5 mixed artists reaches ARI about 0.5; with hundreds of
  artists it falls to about 0.2 even with the automatic cut. Groups are a first pass; review them
  in the map.
- **Periods within one artist**: style drift is significant for 12 of 13 artists;
  `--granularity period` (k-means, 3 groups) follows posting time beyond chance for 11 of 13, but
  the alignment is weak (AMI about 0.12) and unstable for artists with about 50 works.
- **Subject pull**: CSD style vectors are pulled by character looks. `--ignore-characters`
  (or `--neutralize 1`) fixes much of this for collections where the same characters recur, but
  must not be used on mixed artists. A character the folder never showed gets a wrong offset.
- **Taste model**: it separates like from dislike (AUC about 0.77 on one person's votes). It does
  not rank degrees of liking, and it may fail on a new generator.

## Ideas not done yet

- **Web app**: change the reference set (`--reference`) at runtime. Done since 0.4.0: moving,
  merging, splitting and naming groups, the character-axis switch, undo, saved groups.
- **Speed**:
  - fp16 on CUDA;
  - a background thread that loads images. GPU throughput has not been measured here.
- **Large galleries (50k+)**: grouping above 8,000 images is done (k-means micro-groups, 0.5.0).
  Still open: a server-side tiled map instead of one HTML file with every thumbnail. Search does
  not need an approximate index yet: one query against 50,000 vectors is a single matrix product.
- **ComfyUI nodes**: written and checked with the real CSD model on CPU (`comfyui/`), but not yet
  run inside the owner's ComfyUI. Installing them into `I:\ComfyUI-aki-v1.6` needs the owner's
  go-ahead.
- **Grouping in the whitened space**: a fixed cut of 0.90 there beat plain-space grouping by
  0.06-0.10 ARI on Danbooru mixtures but merged a set of AI renders into one group. It needs a
  cut that adapts to the collection, or calibration per kind of collection (BENCHMARKS.md).
- **Better embedding**: CSD is the ceiling for every number above. Candidates are fine-tuning on
  style-labelled anime data, or newer style encoders when they appear. Any candidate must beat
  CSD on `style-atlas bench` and on the unseen-character test.

## Tried and rejected

Each of these is in `docs/BENCHMARKS.md`:

- subtracting the CSD content head;
- clustering variants (k, linkage, centroid reassignment);
- fixed nuisance directions learned from the owner's renders, which did not generalise to unseen
  characters;
- `tiles` / 336 px as the default: real but small gains at 1.9-2.5x cost, so they stay options.
- MegaStyle-Encoder (2026) as the embedding: about 4x worse than CSD on real anime artists, despite
  its benchmark.
- clustering a random sample and joining the other images to the nearest group, for sets above
  8,000 images: k-means micro-groups did better at every size tried.
