# Changelog

## Unreleased

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
