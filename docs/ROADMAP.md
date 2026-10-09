# Roadmap and open questions

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
5. **README screenshots.** Real images make the README much clearer. Which images may be shown?
   The owner's own renders? Public-domain art?

## Known limits, measured

All of these are in `docs/BENCHMARKS.md`.

- **Mixed artists**: clustering of 2-5 mixed artists reaches ARI about 0.5. Groups are a first
  pass; review them in the map.
- **Periods within one artist**: clustering at `--granularity period` follows posting time for
  4 of 6 artists.
- **Subject pull**: CSD style vectors are pulled by character looks. `--neutralize 1` fixes this
  for collections where the same characters recur, but must not be used on mixed artists.
- **Taste model**: it separates like from dislike (AUC about 0.77 on one person's votes). It does
  not rank degrees of liking, and it may fail on a new generator.

6. **External anime benchmark.** LSASRD (CVPRW 2022) has 20,937 images from 190 anime works, with
   a cross-role protocol. It would be the strongest public test of "style, not character". Access
   needs a signed release agreement e-mailed to the authors, so only the owner can request it:
   https://github.com/nkjcqvcpi/ASR

## Ideas not done yet

- **Web app**:
  - toggle `--neutralize` and change the reference set at runtime;
  - rename groups before export.
  - Moving images, merging groups and splitting a group are done.
- **Speed**:
  - fp16 on CUDA;
  - a background thread that loads images. GPU throughput has not been measured here.
- **Large galleries (50k+)**: an approximate nearest-neighbour index (faiss / hnswlib) for
  `search`, and a server-side tiled map instead of one HTML file.
- **ComfyUI node**: a "style distance to reference" score for generation loops. The owner already
  writes ComfyUI custom nodes.
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
