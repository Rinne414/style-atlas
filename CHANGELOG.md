# Changelog

## Unreleased

- **Search with several examples**: `search --combine` with 3 or more example images ranks the
  library with a logistic model of the examples against the library, instead of their mean
  vector (+0.055 to +0.116 average precision, BENCHMARKS.md).
- **`search --copy-to DIR`** copies the matches, with their captions, into a new folder.
- **Drop several images** (web app): they are searched as one style, like `search --combine`.
- **Find more like this group** (web app): the images outside a group that look most like it,
  ranked by a model learned from the group. Click one to move it in.

## 0.5.0 - 2026-10-10

- **Ignore the character axis** in the web app: a live `--neutralize` switch. It rebuilds the
  layout, groups and taste model in the new space.
- **Group names**: name a group in the web app, and the name is used for its export folder and
  trigger word.
- **Web export options**: kohya layout, concept name and trigger captions. Groups left with fewer
  than 3 images after set-asides go to `_unassigned/`.
- **Saved groups**: groups, hand edits and names are written to `groups.json` and restored when
  the folder is opened again.
- **Undo**: a button and Ctrl+Z step back through the last 30 hand edits, regroups, renames and
  character-axis switches (undoing a switch restores the old space with its groups).
- Fixes from the fifth review:
  - Group names follow their images through moves, merges, splits, regroups and axis switches;
    before, a name was tied to the group's most central image and could vanish after an edit.
  - Switching the character axis no longer erases hand edits without a way back.
  - A failed or unchanged rename no longer adds an undo step; two groups cannot share a name.
  - Names are safe as Windows folders (CON, NUL, COM1 ... get a suffix; no trailing dot after
    the 60-character cut) and commas are replaced, so a trigger stays one tag.
  - Folder labels are unique ignoring case; a plain-layout folder such as `2024_summer` keeps its
    whole name as the trigger.
  - Web export reports how many groups were too small and went to unassigned.
  - A damaged `groups.json` is kept as `.bad` instead of stopping the server; the last axis
    switch is restored with the groups.
- **Large sets**: above 8,000 images, grouping no longer switches to HDBSCAN (which ignored
  the threshold and left about half the images unassigned). k-means micro-groups are joined by
  average linkage on exact mean distances, and a new threshold re-cuts the saved tree in under a
  second. See BENCHMARKS.md.
- **One-group hint**: suggests a finer granularity when everything lands in one group.
- **Style Gate**: the default threshold is now 0.5. The nodes were verified with the real CSD
  model on CPU.

## 0.4.0 - 2026-10-10

### New

- **Measures layout**: the map can put taste, originality, time and atypicality on the X / Y / Z
  axes. Originality is the distance to the closest image in `--reference DIR`.
- **Hand edits in the web app**: move an image to another group, merge two groups, or split a
  group in two.
- **Audit**: flags truncated JPEG / PNG files without decoding them.
- **Rating mode**: the web app picks the most useful next image to rate (farthest-first), and the
  taste model trains from 5 ratings of each kind.
- **`--trigger-captions`**: each group's trigger word is written into the exported captions.
- **Style path**: the images that lead from one chosen style to another.
- **Cross-character benchmark** and `docs/LORA_GUIDE.md`.
- **Small-group warning**: `cluster` flags groups too small for their own LoRA.
- **Faster thumbnails**: JPEGs are decoded at reduced scale, thumbnails are cached on disk, and
  `serve` makes them in the background.
- **ComfyUI nodes**: Load Style References, Style Distance and Style Gate. The gate keeps
  original or matching generations.

### Fixes from the third review

- Reference vectors share the folder's `--neutralize` transform.
- Tied measures share their rank.
- Axis objects are disposed when the axes are redrawn.
- Unreadable saved files are kept as timestamped `.bad` copies.
- Large duplicate components no longer build a dense matrix.

### Verified, not changed

- `--neutralize` also works on characters it never saw (AUC 0.866 to 0.967).
- The taste model reproduces the research result (CV AUC 0.769 vs 0.761).

### Rejected

Fixed nuisance directions learned from renders do not generalise to unseen characters.

## 0.3.0 - 2026-10-09

### Subject-heavy collections

`--neutralize N` (cluster, map, serve, search) removes the N strongest directions of variation.

- **Where it helps**: with the same characters in many styles, style search across characters
  works. Same-style AUC went from 0.83 to 0.98 on 96 NovelAI styles x 2 characters.
- **Where it hurts**: mixtures of different artists. It is opt-in for that reason.

Near-duplicate groups are split by complete linkage, so every pair in a group meets the
threshold.

Second Sonnet review fixes:

- Saved votes and exclusions survive renames.
- Startup is robust.
- Request validation is strict.
- The web export sets duplicates aside.
- The keeper avoids excluded copies.
- `--repeats` is validated.

### Period splitting and duplicate threshold

- `--granularity period` (cut 0.35) splits one artist's work into periods. On 6 prolific
  artists it matched posting-time quartiles beyond chance for 4; style distance grew with time
  distance for 6 of 7 (Mantel test).
- The near-duplicate default is now 0.95. Pairs at 0.92-0.95 were often different poses of one
  character. `bench` still deduplicates at 0.92.
- New `docs/API.md` (verified against the demo set) and this changelog.

### LoRA dataset tools

- `cluster --layout kohya --name X --repeats auto|N`:
  - writes `<repeats>_<name>_styleNN` folders;
  - auto repeats aim at about 100 images x repeats per group.
- `cluster --dedupe`:
  - keeps the best copy of each near-duplicate group (most pixels, then has a caption, then the larger file);
  - groups only the kept copies; the other copies go to `_duplicates/`.
- `cluster --drop-outliers N` moves the least typical images to `_outliers/`.
- Groups left below `--min-size` go to `_unassigned/`.
- `audit` flags unreadable, small, extreme-ratio and animated images, and missing or empty captions.
- `clusters.json` lists each group's characteristic caption tags, with their lift.
- Web app: exclude images by hand (X). The list is saved to `excluded.json`; excluded images are exported to `_excluded/`.

### Taste

Like / dislike in the web app (L / D):

- votes are saved;
- after 8 of each, the model refits on every vote, shows its cross-validated AUC and ranks the unrated images.

### Output and installation

- The default output folder is `<folder>_style_atlas`, beside the dataset rather than inside it. Such folders are never scanned.
- Windows:
  - `scripts/setup.bat` sets up a venv and installs CUDA or CPU torch;
  - `scripts/StyleAtlas.bat` is a drag-and-drop launcher.

### Measured but not adopted

These are documented in `docs/BENCHMARKS.md`:

- `--crop tiles` and `--resolution 336` each gain about 1 point top-10 at 1.9-2.5x the cost, so they stay options.
- Clustering variants were all within noise of the default.
- Subtracting the content head did not help.

## 0.2.0 - 2026-10-09

### Commands

- `serve`: local web app with search by dropped image, live regrouping and folder export. It is localhost-only, with Host-header and custom-header guards.
- `duplicates`: near-duplicate groups, using min(style cos, content cos) >= 0.92. The map gets a Duplicates tab.
- `--time name|mtime` draws per-style time strips, showing which style belongs to which period.
- `--resolution 336` (interpolated position embeddings).

### Map and benchmarks

- The map inlines three.js r160, so it opens offline.
- Thumbnails are larger on small sets, and the camera follows the group size.
- `bench` removes near-duplicates first, which gives honest numbers: top-1 46.2%, AUC 0.831.

### Review fixes (Sonnet code review)

- No n x n matrices outside clustering.
- `--threads` is honoured.
- Exports never mix runs.
- CSV formula guard.
- URL-encoded links.
- SQLite WAL.
- Plus about a dozen smaller fixes.

## 0.1.0 - 2026-10-09

### Embedding and grouping

- CSD ViT-L style vectors loaded via open_clip with QuickGELU. Parity with the reference is 1.0000.
- Content-addressed SQLite vector cache; CPU-capped, resumable embedding.
- Hub-corrected (CSLS) agglomerative clustering, with fine / medium / coarse cuts tuned on blind artist mixtures. HDBSCAN is an option.

### Map

Self-contained three.js 3D map with floating thumbnails, nearest styles and outliers.

### Commands

`cluster`, `map`, `search`, `outliers`, `compare`, `calibrate`, `bench`, `taste`.
