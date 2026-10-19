# Style Atlas

Sort a folder of pictures by art style, find pictures drawn in a similar style, and prepare LoRA
training sets. Everything runs on your own computer.

[简体中文](README.zh-CN.md) · English

![Pictures grouped by style, with each group's look described on the right](docs/images/map.jpg)

(The pictures in the screenshots are abstract styles made by `style-atlas demo`, not anyone's
artwork.)

## Download and start

### Windows 10 / 11

1. Download **`StyleAtlas-<version>-windows.zip`** from the
   [latest release](https://github.com/Rinne414/style-atlas/releases/latest).
2. Unzip it somewhere ordinary, for example `D:\StyleAtlas`. Not inside `C:\Program Files`, and
   not in a very deep folder: Windows limits path length, and the launcher stops with a message
   when the folder's path is too long.
3. In the unzipped `StyleAtlas` folder, double-click **`Style Atlas.bat`**.
   - The first time, a console window installs what the program needs into this folder: torch
     (about 2.5 GB with an NVIDIA graphics card, about 200 MB without) and about 100 MB of other
     packages. You do not need to install Python; nothing outside the folder is changed except
     the shortcut. If the download breaks off, double-click again and it carries on.
   - Then it puts a **Style Atlas** shortcut on the desktop and opens the program. The console
     closes by itself.
4. From then on, open it with the desktop shortcut.

Windows may say "Windows protected your PC" the first time you double-click the .bat (the files
are not code-signed): press **More info → Run anyway**.

### Linux (x86-64)

1. Download **`StyleAtlas-<version>-linux.tar.gz`** from the
   [latest release](https://github.com/Rinne414/style-atlas/releases/latest).
2. In a terminal:

   ```sh
   tar xzf StyleAtlas-<version>-linux.tar.gz
   cd StyleAtlas
   ./style-atlas.sh
   ```

3. The first run installs what the program needs into the folder, as on Windows, plus about
   300 MB for the window (Qt WebEngine). It adds **Style Atlas** to the application menu and opens
   the program.

The window is drawn with Qt. Most desktop Linux systems already have the system libraries it needs. When some are missing, `./style-atlas.sh` names them and prints the install command. On a minimal Ubuntu 24.04 that was `sudo apt install libxkbfile1`, and for an X11 session also `libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-shape0 libxcb-util1 libxcb-xkb1 libxkbcommon-x11-0`.

## Using it

1. Press **Open an image folder…**, or drop a folder onto the window. Folders opened before are
   listed on the start page.
2. The first folder downloads the style model once (2.4 GB; a 1.2 GB copy is kept). Then each
   picture's style is computed: about 2.5–4 pictures a second on 8 CPU threads (measured); an
   NVIDIA card is usually much faster. Results are cached, so opening the folder again is quick.
3. The map shows the pictures grouped by style. Click a group on the right to see all of its
   pictures, double-click a picture to see it large, press → to go through every picture one by
   one.
4. To train a LoRA, open the **LoRA dataset** tab: check the pictures, tidy the groups, export.
   The export writes kohya folders and dataset configs for kohya sd-scripts, diffusion-pipe,
   OneTrainer and ai-toolkit.
5. **← Start page** (top left) closes the folder; **New window** opens another folder beside it.
   Starting the program again while it is open also opens a new window.

Step by step with pictures: [docs/WEB_GUIDE.md](docs/WEB_GUIDE.md). The LoRA workflow in full:
[docs/LORA_GUIDE.md](docs/LORA_GUIDE.md).

## Updating

At each start the program asks GitHub whether a newer version exists; untick **Check for updates
at start** on the start page to stop that. When there is one, the start page and the map say so.
Nothing changes until you press **Update**: it downloads the new program code (a few MB), checks
it against the release's SHA256 sums (a mismatch is thrown away), and **Restart now** puts it in
place. Your pictures, results, groups, names and settings are not touched. When a version needs a
newer bundled Python, the program says so and you download the full package again.

## What goes online

| When | What | From |
|---|---|---|
| First start | Python packages (torch, numpy …), into the program's folder | pypi.org, download.pytorch.org |
| First folder | The CSD style model (2.4 GB) | huggingface.co |
| Each start, unless turned off | The newest version number and its notes | api.github.com |
| When you press Update | The new program code | github.com |

Nothing else: your pictures, results, ratings and names stay on your computer. There is no
account and no usage statistics. The program's local server only answers this computer
(127.0.0.1). A map saved with **Save shareable map** contains the pictures you chose; whoever
you send it to can see them.

## Requirements

- Windows 10 / 11 (64-bit) or Linux x86-64. macOS is not supported.
- About 10 GB of free space with an NVIDIA card (5 GB without).
- An NVIDIA graphics card is optional; it needs a recent driver for torch's CUDA 12.8 build.
  Without one, everything runs on the CPU, more slowly.

## When something goes wrong

- **The first start stopped halfway** (network): double-click `Style Atlas.bat` again; it
  continues where it stopped.
- **Slow or blocked downloads** (for example in mainland China): set the environment variable
  `HF_ENDPOINT=https://hf-mirror.com` for the style model and `PIP_INDEX_URL` (for example
  `https://pypi.tuna.tsinghua.edu.cn/simple`) for the packages, then start again. torch itself
  always comes from download.pytorch.org.
- **You moved the folder**: double-click `Style Atlas.bat` once more; the shortcut then points
  to the new place.
- **An error on the screen**: the program's messages are in `style-atlas.log` in the program's
  folder. Please attach it when you report a problem.
- **Force the CPU or the GPU build of torch**: set `STYLE_ATLAS_TORCH=cpu` (or `cuda`) and
  double-click `Style Atlas.bat`.

## What it can do

style-atlas turns every image into a *style vector* with CSD, an embedding trained to capture
how a picture is drawn rather than what it shows. On top of those vectors it can:

- **Prepare LoRA datasets**: split a folder by style, or one artist into periods
  (`--granularity period`), set aside duplicates and outliers, and export kohya-style folders
  (`cluster --layout kohya --dedupe`), with group names as folder and trigger names.
- **Check a batch against the folder**: drop several images (LoRA test renders, newly found
  pictures) and the web app says how many fall inside one of the folder's style groups. On
  held-out works, 61% of an artist's own landed inside, 1% of another artist's. Dropped images
  that are near-duplicates of a folder image are listed first: for LoRA renders, a sign that the
  LoRA repeats a training image (`compare A B` lists them; with `--json` they are in
  `b_copies_of_a`).
- **Find images in a similar style**: drop one image, or several of one style, into the web app,
  or use `search` (`--combine` treats several examples as one style, `--copy-to` gathers the matches). A
  "style path" lists the images that lead from one picked style to another.
- **Which artist does this look like?** `search --by-folder` ranks the sub-folders of a library
  (one per artist or style) by their overall style. On 284 Danbooru artists it named the right
  one first for 70.7% of held-out works by 114 artists the tool had never seen, against 63.4%
  for the artist of the closest image.
- **Explore a 3D style map** (`map`, or "Save shareable map" in the web app): one HTML file you
  can send to anyone. Group names float at each group's centre ("Names" hides them), and groups
  show their characteristic caption tags. "Record a turn" saves an 8-second video of the map
  turning once (MP4 in Chrome and Edge, WebM in Firefox), for sharing.
- **One-page style report** (`report`): consistency, where the folder's look falls among 278
  Danbooru artists, the closest artists of a reference library (`--artists`), which sub-folders
  (e.g. artists) draw alike, and each group's most typical images, in one HTML file to keep or
  send. It reuses the web app's groups and names.
- **Map of artists** (`map --by-folder`): one point per sub-folder of a library, at the folder's
  mean style and shown by its most typical image, so artists with similar styles sit together.
  The colours are loose "families": grouping two halves of each artist's works separately agreed
  only at ARI 0.32.
- **Check a dataset** (`audit`, `duplicates`, or the web app's Check tab): sizes, aspect ratios,
  captions, near-duplicates, greyscale images mixed into a colour set (and captions whose
  `monochrome` / `greyscale` tags disagree with the picture), images enlarged from a
  smaller original, heavily compressed JPEGs, photos turned only by an EXIF tag (kohya
  sd-scripts trains them sideways), one tag spelt two ways across captions (`long_hair` and
  `long hair`), and captions that mention a watermark, signature or URL (`watermark`,
  `signature`, `artist name`, `web address` ...). The style map cannot find enlarged images
  (CSD looks at 224 px), so the check measures their sharpness at training size
  (BENCHMARKS.md).
- **Style consistency** (Check tab, `cluster`): how spread the folder's style is next to 114
  single Danbooru artists. Folders more spread than 90% of them are flagged as a possible mix;
  on artists the tool had never seen this caught 49% of two-artist and 85% of three-artist
  mixes, and 11% of single artists.
- **Fix groups by hand** in the web app: "Find more like this" lists the images outside a group
  that look most like it; move an image to another group, merge two groups,
  split a group in two, or exclude images (X), which are then exported to `_excluded/`.
  Type `#tag` in the filter box (`#monochrome`, `#sketch`) to light up the images whose captions
  have that tag.
  Shift+click (on the map or in a list) or Shift+drag a box on the map to select several
  images, then exclude or move them all at once (one undo step); Esc clears the selection.
  Strays by another artist: exclude two or three, then "Find more like these" in the excluded
  list ranks the rest first (from three, the top 30 held 98% of them).
  Groups, edits, names and the character-axis switch are saved and restored the next time the
  folder is opened. Names follow their images: after a move, merge, split or regroup a name
  stays with the group that holds most of its images.
  Undo (or Ctrl+Z) steps back through the last 30 edits, regroups and renames.
- **Quantify style and taste**: say how a group looks ("cooler, more line work"), compare two
  groups in the web app ("Compare with…") or two folders with `compare`, or train a personal
  like/dislike model in the web app or with `taste`.

## Command line

Type the `style-atlas ...` commands below in a console: in the program's folder, double-click `Style Atlas console.bat` (Linux: `./style-atlas-cli.sh <command>`); from source, `scripts\StyleAtlas-console.bat`.

### LoRA workflow

Check for small, extreme, animated and stray greyscale images, photos turned only by an EXIF
tag (kohya sd-scripts trains them sideways), missing captions and greyscale tags that
disagree with the picture; then review duplicates, outliers and groups in the browser (exclude
images with X); then export.
`serve` keeps its console busy until you press Ctrl+C, so run the export in a second console.

```bat
style-atlas audit DIR --min-side 768
style-atlas serve DIR --time name
style-atlas cluster DIR --layout kohya --name artistX --dedupe --drop-outliers 5 --export copy
```

`cluster` also sends the images you excluded in the web app to `_excluded/`, but it groups
afresh: moves, merges, splits and names made in the web app are kept only by the web app's own
Export button.

The output goes to `DIR_style_atlas/folders/`, next to the dataset and never inside it:

- `<repeats>_artistX_styleNN/` folders, with captions copied alongside. Repeats are chosen so
  that images x repeats is about 100; use `--repeats N` to fix them.
- `dataset_config.toml`, a kohya sd-scripts dataset config (`--dataset_config`) with every style
  folder and its repeats; set the resolution and batch size for your model.
- `diffusion_pipe_dataset.toml` (diffusion-pipe: the training config's `dataset` file) and
  `onetrainer_concepts.json` (OneTrainer: copy it into OneTrainer's `training_concepts` folder
  and pick it on the concepts tab), and `ai_toolkit_datasets.yaml` (ai-toolkit: paste the
  entries under `datasets:`), with the same folders and repeats.
- `_duplicates/`, `_outliers/`, `_unassigned/` and `_excluded/` (images you excluded with X in
  the web app). Kohya skips these because they lack a number prefix.
- With `--max-per-group N` (web: "Export training set…", "max per style"), a larger style keeps N images that cover
  it (farthest-point sampling from its most central image); the rest go to `_trimmed/`, and
  repeats follow the kept count.
- `clusters.json`, which lists each group's characteristic caption tags.
- With `--trigger-captions`, every exported caption starts with its group's trigger
  (`artistX_style01, ...`). Images without a caption get one, and source captions are never
  touched. The full workflow is in [docs/LORA_GUIDE.md](docs/LORA_GUIDE.md).

Source files are never moved or deleted. Each export goes to a fresh folder.

With `--export link` the files are hard links, so editing an exported caption also edits the
original.

**Adding new images to a sorted dataset.** `style-atlas sort NEW --into DATASET --by-folder
--export copy` places each new image in the dataset sub-folder it is closest to. It goes to
`_unsure` instead when it is farther from the centre than 70% of that folder's own images
(each measured against the centre of the others), and to
`_already_in_dataset` when it is a near-copy of a dataset image. `sorted.csv` lists the closest
group, the distance and the copy for every image. Without `--by-folder` the dataset's style
groups are used: those saved by the web app (`--fresh` groups afresh instead), else a fresh
grouping. Groups of fewer than 3 images take no new images. On artists the tool never
saw, with 10 of them as sub-folders, 91.5% of their new works went to the right folder, 69%
fitted (99% of those in the right folder), and 9% of other artists' works were let in (14% when
each folder held only 10 images; docs/BENCHMARKS.md). `sort` lists the `_unsure` images closest
to a group first, as a hint (an artist's own work comes first about 2 times in 3). Add `--merged`
for `<out>/merged`: the dataset plus the new images that fit, ready to train, with kohya repeats
and trainer configs updated; the dataset itself is not changed. In the web app, new images added
to the folder start as "Unassigned"; open that row and press "Put each in its closest style" to
apply the same rule (one undo step).

### Commands

Square brackets mark optional parts; `#` starts a note, not part of the command.

```text
style-atlas cluster DIR [--granularity auto|period|artists|fine|medium|coarse | --threshold T | --k N]
                        [--layout plain|kohya --name X --repeats auto|N] [--dedupe]
                        [--drop-outliers N] [--max-per-group N] [--strip-tags TAGS]
                        [--trigger-captions] [--export copy|link] [--no-map] [--no-recursive]
                        [-o OUT]
style-atlas embed DIR             # embed and cache only
style-atlas sort NEW --into DATASET [--by-folder] [--export copy|link] [--merged]
                 [--trigger-captions] [--strip-tags TAGS] [--fresh] [-o OUT]
style-atlas report DIR [-o style_report.html] [--artists DIR] [--renders DIR] [--lang zh|en]
                       [--time none|name|mtime] [--fresh]
style-atlas doctor                 # check Python, torch, GPU, model download, disk space
style-atlas serve DIR [--port 8770] [--no-browser] [--time none|name|mtime]
style-atlas map DIR [-o map.html] [--projection auto|umap|tsne|pca] [--time ...] [--by-folder]
style-atlas search QUERY... --in DIR [--top 20] [--combine] [--copy-to DIR] [--by-folder]
                   [--keep-duplicates] [--json]
style-atlas audit DIR [--min-side 512] [--max-ratio 2.5] [--json]
style-atlas duplicates DIR [--threshold 0.95] [--json]
style-atlas outliers DIR [--top 30]
style-atlas compare DIR_A DIR_B [--noise-floor X] [--json]   # 5+ images a side: placed among artist pairs
style-atlas calibrate DIR          # sub-folders = groups known to share one style
style-atlas bench DIR              # sub-folders = labels (e.g. one artist each)
style-atlas taste train --like DIR --dislike DIR [--model taste_model.npz]
style-atlas taste score DIR [--model taste_model.npz] [--copy-to DIR] [--top N]
```

`-o` is an output folder for `cluster` and `sort` and an HTML file for `report` and `map`;
`search` copies its results with `--copy-to`. Messages are in Chinese on a Chinese Windows (or
locale) and in English elsewhere; `set STYLE_ATLAS_LANG=en` (or `zh`) chooses. Image files: png,
jpg, jfif, webp, bmp, gif, and avif where Pillow supports it.

Common options:

- `--device auto|cpu|cuda`
- `--resolution 224|336`: 336 is about 1 point better at retrieval and 2.5x slower.
- `--reference DIR` (cluster, map, serve): a folder of styles you already know. It adds an
  originality measure, the distance from each image to its closest reference. The map's
  "measures" layout can then put taste, originality, time and atypicality on the X / Y / Z axes,
  along with the six look measures (see "Look measures" below). In the web app the reference
  folder can also be loaded (or cleared) under "More…" at the bottom.
- `--ignore-characters` (cluster, map, serve, search): use it when the same characters appear in
  many styles. It finds the characters from the CSD content vectors (no labels needed) and moves
  each character's style vectors to a shared centre. On 16 Anima recipes x 4 characters,
  same-recipe search rose from 58% (`--neutralize 1`) to 70%. The web app's "Ignore the
  character axis" switch uses it. Do not use it on a mix of different artists.
- `--neutralize N` (cluster, map, serve, search): the older correction, which removes the N
  strongest directions of variation. On 96 NovelAI styles x 2 characters it raised same-style AUC
  from 0.83 to 0.98 (centring: 0.98 too). It learns no characters, so it is the safer choice when
  queries show characters the folder does not. Do not use it on a mix of different artists,
  where it removes the style difference itself.
- Not sure whether a correction helps? Sort some images into one sub-folder per style and run
  `style-atlas bench DIR`: compare `top1` under `hub` (no correction), `neutralize-1` and
  `characters`.
  - It helps search much more than grouping. AI renders from one model with fixed characters
    differ by less than any threshold cut. On 16 Anima recipes x 8 renders, every cut gave one
    group or a split by character, and search found the same recipe 56% of the time (62% with
    `--neutralize 2`, 70% with `--ignore-characters`).
  - `--neutralize 2 --method kmeans --k 16`, which sets the number of groups, reached ARI 0.22
    there (0.53 on another set of 7 recipes).
- `--crop center|tiles`
- `--threads N` (default 8)
- `--cache-db PATH`

### How it works, accuracy and limits

How the style vectors, grouping and search work, how accurate they are and where they fail: [docs/ACCURACY.md](docs/ACCURACY.md). Every number comes from [docs/BENCHMARKS.md](docs/BENCHMARKS.md).

### ComfyUI nodes (experimental)

`comfyui/` provides three nodes:

- **Load Style References**: reads a folder of known styles.
- **Style Distance**: the distance from each generated image to its closest reference.
- **Style Gate**: keeps original or matching images.

Install (both steps are needed):
1. Install style-atlas into ComfyUI's own Python, e.g.
   `python_embeded\python.exe -m pip install -e <repo path>`. The node code lives in the package.
2. Copy or link the `comfyui` folder into `ComfyUI/custom_nodes/style-atlas`. It is only the
   entry point ComfyUI looks for.

The Gate's default threshold is 0.5. For single images on Danbooru, the median distance is about
0.40 between works by the same artist and 0.56 between different artists. The nodes have run with
the real CSD model from Python, but not yet inside ComfyUI.

## Run from source (developers)

### Windows, from source

1. Install Python 3.10+ (3.10 to 3.14 are tested) and tick "Add python.exe to PATH".
2. Get the source (**Code -> Download ZIP** on GitHub and unzip, or `git clone`). Double-click
   `scripts\setup.bat`. It creates `.venv`,
   installs CUDA torch when an NVIDIA GPU is present (about a 2.5 GB download; otherwise CPU
   torch, about 200 MB), then installs style-atlas.
3. Double-click **Style Atlas** on the desktop (`setup.bat` makes the shortcut), then press
   "Open an image folder…" or drop a folder onto the window. Folders opened before are listed
   on the start page. "← Start page" at the top left of the map closes the folder and goes back
   to it; "New window" opens another folder in a second window, and so does the desktop shortcut
   while the program is open. Closing a window closes its folder; closing the last one ends the
   program. To use the browser instead, drag an image folder onto `scripts\StyleAtlas.bat` as
   before.

**Updating**: extract the new ZIP over the old folder (keep its `.venv`) and run
`scripts\setup.bat` again; torch is already installed, so it takes seconds. With git: `git pull`,
then `setup.bat`. Results next to your image folders and the vector cache are kept.

For commands (`audit`, `cluster`, `search` ...), double-click `scripts\StyleAtlas-console.bat`: it
opens a console where `style-atlas` works. A plain console does not know the command, because it
is installed in `.venv`.

First-run notes:

- Keep the console window open while you use the web app; closing it stops the app. If no
  browser opens, go to the address the window prints (usually `http://127.0.0.1:8770`).
- Captions are `.txt` files next to their images with the same name. Sub-folders are included
  unless you pass `--no-recursive`.
- Try a folder of about 100 images first.

Terms: the **kohya** layout is the folder structure kohya_ss / sd-scripts train from
(`10_artistX_style01`, where 10 is the **repeats**: how often each image is seen per epoch). A
**trigger word** is the tag at the start of each caption that calls up the style after
training.

The first analysis downloads the CSD model once from Hugging Face (2.4 GB). It is kept as a slim
1.2 GB file in `~/.cache/style-atlas`; set `STYLE_ATLAS_CACHE` to move it.

Speed:

- 8 CPU threads embed about 2.5-4 images per second (measured; large images are slower).
- An NVIDIA GPU is usually much faster (not benchmarked here).
- Vectors are cached by file content, so reopening a folder does not re-embed anything.

Manual install:

For GPU use, install the CUDA build of torch first; `pip install -e ".[umap]"` adds UMAP.

```bat
git clone https://github.com/Rinne414/style-atlas
cd style-atlas
pip install -e .
```

If `style-atlas` is not found (Python's Scripts folder is not on PATH), `python -m styleatlas`
takes the same arguments.

### Development

```bash
pip install -e ".[dev]"
pytest                 # fast tests, no model needed (they run in CI)
pytest -m model        # end to end with the real CSD model on generated demo styles (CPU is fine)
ruff check src tests && ruff format src tests
```

Benchmarks and how each default was chosen: [docs/BENCHMARKS.md](docs/BENCHMARKS.md). The search
whitening is refit with `scripts/fit_whitening.py`.

## Credits

- CSD: Somepalli et al. 2024. Code under MIT, weights under CC-BY-4.0, downloaded at runtime.
- three.js r160 (MIT), vendored in `src/styleatlas/templates/vendor/`.
- style-atlas itself: MIT, see [LICENSE](LICENSE).
