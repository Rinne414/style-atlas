# Changelog

## Unreleased

- **Shortcut list**: "?" (key or button) shows the keyboard and mouse shortcuts.
- The map subtitle no longer runs under the top controls on laptop-size screens; loading dots are
  smaller.

## 0.11.0 - 2026-10-10

Security fixes from a Sonnet security review:
- **HIGH: a crafted `groups.json` could make Export write outside its folder.** Group names read
  from the file were not cleaned like names typed in the page, so `../../x` or an absolute path
  became an export folder. Names from the file are now cleaned, and Export refuses any folder
  that resolves outside the export.
- Images over 100 million pixels are refused before decoding (decompression bombs), and search
  uploads are decoded one at a time.
- Symlinked files, and folders that resolve outside the dataset (junctions), are skipped when a
  folder is scanned.
- Thumbnails and images refuse requests that the browser marks as coming from another site.
- `doctor` checks scipy and that the search data loads.

## 0.10.0 - 2026-10-10

- `cluster --time name|mtime` shows where each group sits on the folder's timeline ("when 9%
  [3%-28%]" = median and middle half), so periods read as early / middle / late in the console.
- **Large galleries open faster**: the map shows at once and thumbnails fill in behind a small
  corner note. On 19,554 images the map appeared after 4 s instead of about 70 s.
- Faster start-up and page loads for big folders: relative paths are worked out once (page build
  0.14 -> 0.04 s on 3,259 images), the same neighbour density is no longer computed four times,
  and captions are read in the background at start-up.

## 0.9.0 - 2026-10-10

- **Search whitening**: search ranks in a whitened space learned from 306 Danbooru artists
  (within-artist variation turned down). On artists never seen when it was learned: single-image
  top-1 +2 to +5 points, learned set search +0.05 to +0.07 AP, and a small gain on AI renders.
  Groups, duplicates, the Style Gate and taste keep plain CSD distances.
- `bench` reports the whitened space too.
- Docs: grouping in the whitened space (better on Danbooru, collapses AI renders, so not used),
  and what `--neutralize` does and does not fix for AI renders with fixed characters.

## 0.8.0 - 2026-10-10

- The map subtitle says how groups were made in words ("auto cut 0.43", "3 periods").

- **Periods are now k-means** (`--granularity period`, the web app's "時期"): one artist's work
  is split into 3 groups (`--k` or the web box sets the number) that cover nearly every image.
  On 13 artists it followed posting time about as well as the old 0.35 cut, which left 36-77%
  of the images unassigned for 4 artists. Periods under `--min-size` are set aside, conflicting
  flags (`--method`) are refused, and below 100 images `cluster` notes that the boundaries are
  soft (all from a Sonnet review). The old cut is `--threshold 0.35`.

- An unreadable caption no longer blanks the web page, and an image deleted while the app runs
  gives "not found" instead of a dropped connection.
- **Open folder** button after an export or a saved map (opens only the output folder).
- Any other unexpected error in the web app now answers with a short message (and the full
  traceback in the console) instead of leaving the page waiting.

## 0.7.0 - 2026-10-10

- **Automatic cut (new default)**: `--granularity auto` and the web app's "自動" pick the cut from
  the data (best silhouette + 0.04, at most 0.47). The fixed medium cut chained large mixed
  galleries into a few big groups; auto beat it by 0.16-0.21 ARI on 50-306 artists (with 5-9%
  unassigned instead of 1-2%) and matched it on 2-20 (BENCHMARKS.md). Very similar images count
  once when the cut is chosen, so folders full of copies or variants do not shatter (found in a
  Sonnet review). `--granularity medium` keeps the old behaviour.
- Splitting a group of identical images now says so instead of doing nothing.
- **Save shareable map** (web app): writes the map as it is now, with hand edits and group names,
  to one HTML file with the thumbnails inside, ready to send to friends.
- Clustering builds one average-linkage tree and cuts it (scipy), for both normal and large sets.
- **Group tags in the map**: when images have caption `.txt` files, each group's row shows the
  tags that set it apart (e.g. "sketch, white background"), in the web app and in `map`.

## 0.6.0 - 2026-10-10

- **Search with several examples**: `search --combine` with 3 or more example images ranks the
  library with a logistic model of the examples against the library, instead of their mean
  vector (+0.055 to +0.116 average precision, BENCHMARKS.md).
- **`search --copy-to DIR`** copies the matches, with their captions, into a new folder.
- **`scripts\StyleAtlas-console.bat`** opens a console where the `style-atlas` command works.
  Before, the README's commands failed after `setup.bat` with "not recognized", because the tool
  lives in `.venv`.
- **README**: how to download the private repo, first-run notes (keep the console open, the
  fallback address, captions as `.txt` beside images), a short glossary (kohya, repeats, trigger
  word), `period` in the granularity list, `_excluded/` in the output list, ComfyUI install steps
  in the right order. Found by a first-time-user review.
- **Tests** now syntax-check the page script (`node --check` silently skips `.js` files that use
  `import`, so the check runs on an `.mjs` copy).
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
