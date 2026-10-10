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
   - Publish to PyPI. A wheel builds with all its data files (templates, three.js, the
     whitening map, the look reference), installs, and runs `report` and `map` from the
     installed package (checked 2026-10-10).
4. **Integration.** Should style-atlas become a module inside `sd-image-sorter`, which already has
   a gallery, tagging and similarity tools, or stay a separate tool?
5. **README screenshots.** For now the README shows the real interface on generated abstract
   images (`scripts/make_demo_images.py`), so no artwork is involved. Real art would show the
   tool better. Should the owner's own renders, or public-domain art, replace them?
6. **External anime benchmark.** LSASRD (CVPRW 2022) has 20,937 images from 190 anime works, with
   a cross-role protocol. It would be the strongest public test of "style, not character". Access
   needs a signed release agreement e-mailed to the authors, so only the owner can request it:
   https://github.com/nkjcqvcpi/ASR
7. **GPU run.** The development machine has an RTX 3090 and `setup.bat` installs CUDA torch there,
   but no embedding has run on the GPU: the machine has hard-reset under load before, so a short
   GPU test (speed, fp16) waits for the owner's go-ahead.

8. **GitHub Actions billing.** Since 2026-10-10 CI jobs do not start: GitHub reports failed
   payments or a spending limit that needs raising (private repositories have a monthly quota of
   Actions minutes, and Windows minutes count twice). Until the owner sorts this out, changes are
   checked with the local test run only and no new release is tagged (0.44.0 waits in the
   changelog). The workflow now runs one quick Linux job per push and the full matrix only for
   pull requests, tags and by hand, to use fewer minutes.

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
  not rank degrees of liking, and it may fail on a new generator. The look measures add nothing
  to it (AUC 0.53 alone).
- **Strays by another artist** in one artist's folder: neither the grouping nor the outlier
  scores find them reliably (about half). From two or three that the user excludes, "Find more
  like these" lists the rest first (98% in the top 30).
- **Style consistency**: on artists the whitening never saw, two-artist mixes are caught 49% of
  the time (three 85%, five 100%), with 11% false alarms on single artists. AI renders from one
  model with fixed characters always read "tight". A per-group version was rejected: no cut
  carries across folders.
- **Sorting new images** (`sort`, and the web app's fit check): about 31-39% of an artist's own
  new works land in `_unsure`. Other artists' works are let in 9% of the time with 25 images per
  sub-folder, 14% with 10 and 24% with 5; with the tool's own groups of a mixed folder, 11%.
  Look through `_unsure` and through what landed in small groups.
- **Enlarged images**: 2x enlargements (relative to the training size) are caught 92-100% of the
  time, 1.5x mostly not. AI upscalers were not tested.
- **Families of artists** (`map --by-folder`): loose, with a split-half ARI of 0.32 at the default
  cut; the positions on the map mean more than the colours.

## Ideas not done yet

- **Web app**: done since 0.4.0: moving, merging, splitting and naming groups, the
  character-axis switch, undo, saved groups, the dataset check, comparing groups, the reference
  folder at runtime, recording a turn.
- **Speed**: images are loaded ahead on 4 threads since 0.36 (20% faster on CPU,
  BENCHMARKS.md). Still open: fp16 on CUDA. GPU throughput has not been measured here.
- **Large galleries (50k+)**: grouping above 8,000 images is done (k-means micro-groups, 0.5.0).
  Still open: a server-side tiled map instead of one HTML file with every thumbnail. Search does
  not need an approximate index yet: one query against 50,000 vectors is a single matrix product.
- **ComfyUI nodes**: written and checked with the real CSD model on CPU (`comfyui/`), but not yet
  run inside the owner's ComfyUI. Installing them into `I:\ComfyUI-aki-v1.6` needs the owner's
  go-ahead.
- **Grouping in the whitened space**: a fixed cut of 0.90 there beat the product's `auto` by
  +0.13 / +0.07 ARI on mixtures of 20 / 50 held-out artists but only +0.02 to +0.04 for 2-5, and
  merged a set of AI renders into one group. A cut relative to the folder's median distance did
  not carry across sizes (BENCHMARKS.md). Offered as `--granularity artists` since 0.43, not
  the default.
- **Better embedding**: CSD is the ceiling for every number above. Candidates are fine-tuning on
  style-labelled anime data, or newer style encoders when they appear. Any candidate must beat
  CSD on `style-atlas bench` and on the unseen-character test.
  - Looked at on 2026-10-10, not run. Baragi-AI/Anima-Style-Embedding v2 is an anime style
    encoder (1,024-d, 52M parameters). It needs Anima VAE latents, DINOv3 features and Anima
    text descriptors as inputs, but the extraction is not bundled. The weights are
    non-commercial, and the card has no comparison with CSD. Worth a bench run if a full
    raw-image pipeline is released.
  - Mitchins/anime-style-classifier-v5 sorts anime frames into 4 production styles, not
    artists.

- **From the v0.24 product critique, not done yet**:
  - Search inside a caption tag is done (0.26). Negative examples were measured and dropped
    (BENCHMARKS.md, "Tried and rejected").
  - Caption checks against the image, for example `monochrome` on a colourful picture.
  - Comparing selections is done (against a group 0.27, two selections 0.32).
  - An aspect-ratio bucket report as the trainer will see it.
  - A one-page report for a folder (consistency, looks, nearest artists, originality).
  - Rejected: hiding the taste model. Quantifying taste is one of the owner's goals.
- **Watermarks without captions**: only caption tags are checked. Detecting marks in the pixels
  needs a detector model.

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
