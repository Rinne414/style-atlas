# Changelog

## Unreleased

Fixed, from four Sonnet usability tests of the web app (a newcomer with a downloads folder, a
LoRA trainer with one artist's 60 works, a collector with 3,800 images of 108 artists, a UI
designer on the demo):

- The map no longer turns by default (pictures moved under the cursor); the 旋轉 button still
  turns it.
- Theme and language are remembered (an edit reloads the page and used to reset both).
- The ? help starts with a quick start, has a close button, and Esc closes it from a text box too.
- Group cards in the side list are three lines: name, size and spread in words, and the artists
  it comes from (or its look). The rest moved to the group view.
- Every edit says what it did, and Undo says what it took back ("已復原：已把 畫風 3 合併到 畫風 1").
- The steps ① ② ③ work while the group view is open (③ opened the export bar behind it).
- **Near-duplicates show which copy the export keeps** (file names, a 保留 badge) and
  「改留這張」 picks another (kept in `kept_copies.json`; `plan_folders(prefer=...)`).
- **Export: one group is named by the LoRA name alone** (`12_artistX`, was `12_artistX_style01`,
  which made `artistX_style01` the trigger), and repeats can be set on the export bar (empty:
  automatic).
- **Periods along the timeline keep their time order after hand edits** (they were renumbered by
  size, so period 1 could become the newest).
- **Artist-map families no longer swallow the library**: the fixed cut 0.35 put 106 of 108
  artists in one family (35-50 works each sit closer than the 10 the cut was set on); the cut now
  drops until no family holds more than a quarter of the folders (108 artists: 16 families, the
  largest 21; 306: 37, the largest 62).
- **Comparing groups that mix artists** no longer reads the distance against pairs of artists
  (two different-looking groups of 6-8 artists each read "closer than 95% of pairs"): it says
  whether the two can be told apart, and why.
- English: no words broken mid-word, the start-up hint follows the language switch; orange links
  in the light theme reach 5.5:1 contrast (were 3.8:1).
- **The map no longer disappears after a long scroll.** The wheel could zoom the camera past the
  far plane (the whole map gone) or into the points; zoom now stops at both ends.
- **No more tracebacks in the console when the browser cancels a thumbnail** (scrolling a list,
  closing the tab): `ConnectionAbortedError` and other dropped connections are ignored.
- **File-name times from mixed sources are no longer used.** `--time name` (the launcher's
  default) read the largest number in each file name; in a downloads folder mixing tweet ids (19
  digits) with Pixiv or Danbooru ids, group cards showed ranges like "#583 - #1,928,042,784,..."
  and timelines followed the id lengths. Times now count only when 80% of them lie within 1.5
  orders of magnitude of their median (one numbering over the years does); otherwise no
  timeline is drawn, periods by time say why, and the time strip bins by order, not by raw value,
  and shows a month only for dates.
- The side list no longer scrolls sideways when a line holds a long word or number.

Changed output (scripts that parse the text should use `--json`):

- `compare` prints a readable summary by default; the JSON it printed before needs `--json`.
  With 5 or more images a side, the text reads the distance next to real artists instead of the
  z scale (z and its verdict stay in `--json`, and in the text with fewer images or
  `--noise-floor`); `--json` adds `separable` and `artist_reading`; the near-copy line shows only
  when there are near-copies (or with few images). `--noise-floor` must be above 0.
- `taste score` lines add each image's closest rated picture; the header no longer calls the
  score a probability.
- `calibrate` prints each sub-folder's noise and the `--noise-floor` to pass to `compare`; the
  JSON it printed before needs `--json`.
- `duplicates` prints a header line per group and one file per line (was one line per group).
- On a Chinese system `audit` adds the meaning to each item name (`no_caption（沒有標註檔）`).
- `cluster.fit_to_groups` takes plain CSD vectors and whitens them itself: code that passed
  whitened vectors must pass the plain ones now (docs/API.md).
- `map` writes `<folder>_style_atlas/style_atlas_map.html` by default (it wrote into the image
  folder; every other command already kept out of it).
- `compare A A` (the same folder twice) is refused.
- `search --combine`, the web app's search with several images and "more like this group" rank by
  the examples' mean style below 10 examples (the learned model is used from 10, was 3): on 137
  artists the search whitening never saw it was worse with 3 examples (-0.014 AP, CI
  [-0.025, -0.005]) and not better with 5.

New:

- **A group view for going through the groups one by one** (asked for by the owner): clicking a
  group in the list fills the map area with that group, its most typical images first (by style
  distance to the group's centre, a new per-image field `g` in the map data), the ones that sit
  apart from it (past Tukey's upper fence) in their own row, and its 3 closest groups side by
  side with a two-click merge; the edits of the old in-list panel sit above. Arrow keys step
  through the groups, Esc goes back to the map, a size menu sets the tile size (remembered), and
  the live app sends sharper 320 px tiles (`/view/<i>`). After an edit reloads the page, the view
  opens again on the same group (or the merged one). Shared HTML maps get the view without the
  edits.
- **`style-atlas demo`** (or double-click `scripts\StyleAtlas-demo.bat`) makes the 72 demo
  images (four procedural styles, no one's artwork) and opens them in the web app, in one step
  (`scripts/make_demo_images.py` moved into the package as `styleatlas.demo`).
- **The web app opens at once.** `serve` (and `StyleAtlas.bat`) opens the browser before the
  model download and the embedding, shows their progress on a waiting page, and turns into the
  map when ready; if the folder cannot be opened, the page says why.
- **The first model download fits where it should.** The 2.4 GB checkpoint is downloaded into the
  style-atlas cache folder (so `STYLE_ATLAS_CACHE` moves it too) and removed once the 1.2 GB copy
  is made; it used to stay in the Hugging Face cache on C:. The free space (3.9 GB) is checked
  before the download, with how to move the cache. A Hugging Face cache of your own (`HF_HOME`,
  `HF_HUB_CACHE`) is used and left alone; `doctor` points at an old checkpoint there.
- **Search scores with a scale.** Each web image-search result shows its style similarity, with a
  line on what the numbers mean (measured on 306 Danbooru artists; 0.85 and up highlighted);
  for one query image, 「只看很像的」 shows only those (and copies only those to a folder).
- **「存圖」/Save PNG in the top toolbar** of every map, shared HTML maps included (it was under
  More… or the P key).
- **Group spread with a scale**: cards say "very consistent" (< 0.15), "about one artist's range"
  (0.15-0.29) or "loose" (> 0.29) next to the number, from one artist's whole works on 393 Danbooru
  artists (median 0.20; BENCHMARKS "How spread is one artist?").
- **Shared map files work for the person they are sent to** (from a Sonnet test of someone who
  received one): messages (saved picture, recording, filter) show in a toast instead of the hidden
  bottom bar; the file link says it needs the sender's folder; the Duplicates tab no longer talks
  about exporting; the file-name filter clears an earlier selection so its matches show, and counts
  them.
- **The taste tab explains itself** (from a Sonnet first-time-user test of the taste features, which
  learned its acted-out taste at AUC 0.98 from 27 ratings): rating mode shows the like/dislike
  counts, the AUC says how many ratings it rests on and that few or very different ones read high,
  the two lists say what p(like) is and what they are for, and a press right after the next image
  appears is ignored (it rated an image not yet seen). WEB_GUIDE now covers the taste tab and the
  Duplicates tab, and says why the report (278 artists) and the consistency check (114) differ.
- **Which artist, and how sure?** `search --by-folder` and the web app's closest sub-folders say how far
  to trust the first folder from its lead over the second, with the rate measured on 137 artists the
  whitening never saw (one image: 95% / 60% / 35% right for leads of 0.08+ / 0.05-0.08 / less;
  three combined: 99% / 87% / 51%), and that an artist's much earlier or later works can look like
  someone else's (a first-time-user test hit exactly that). `search --copy-to` and the web app's
  copy put the results straight into the new folder, led by their rank (01_ first; it was
  `matches\matches`).
- **「畫師地圖」/Artist map in the web app**: with three or more sub-folders (e.g. one per artist), one
  click writes and opens the map `map --by-folder` makes (one point per sub-folder at its average
  style, grouped into families), saved as `artist_map.html` next to the exports.
- **Clearer exploring** (from a Sonnet first-time-user test of an illustration fan with 12 artists):
  search results below 0.43 (the median of pairs by different artists) are faded and the legend
  says why the numbers do not always go down (the order comes from the search itself); the
  closest sub-folders say what their number and count mean; the consistency check says that a
  folder with sub-folders is measured as one artist, so a collection reads as spread; a group card
  says how many of its images are near-duplicates of each other.
- **「全部一群（訓一個 LoRA）」 in the web app's grouping menu** puts every image in one group (one
  export folder) in one click; the timeline's verdicts point at it (a Sonnet web first-time-user
  test merged periods by hand, two merges of two clicks each). The first image search says it
  loads the model (10-20 s); the check's advice on missing captions and small images matches
  `audit`; edge verdicts say what to do ("not enough to train the periods apart").
- **Clearer `cluster` and `audit` output for a first LoRA** (from a Sonnet first-time-user test): one line
  accounts for every image (in folders, set aside and why); when the timeline finds no link or only
  drift, or the automatic groups split a folder as consistent as one artist, the command says how to
  get one folder (`--k 1`); edge verdicts say which way they lean in plain words; kohya exports say
  how repeats were chosen; `audit` says what to do when no image has a caption or most are small
  (Danbooru/Pixiv 'sample' downloads).
- **Rating mode ignores a second L/D press** made before the next image is shown (it rated the
  same image again).
- **`sort --merged`** (with `--export` and `--by-folder`) also writes `<out>/merged`: the dataset
  plus the new images that fit, ready to train. kohya folders whose automatic repeats change are
  renamed and the trainer configs list the new repeats; images excluded in the web app go to
  `_excluded`; the dataset itself is not changed. (A Sonnet first-time-user test of `sort` built
  that folder by hand.)
- **Clearer `sort` output** (same test): the placed count is broken down into style folders,
  `_unsure` and `_already_in_dataset`; each near-copy is named with the dataset image it repeats;
  `_unsure` is listed closest to a group first, as a hint (an artist's own work comes before a
  stranger's about 2 times in 3; BENCHMARKS); the small-image note says it counts the images
  placed in style folders (in `cluster` exports too); the last line says what to do next.
- **`compare` places real artists' folders among real artists** (from a Sonnet first-time-user
  test: one artist's oldest and newest works read "same style" on the AI-render z scale while
  the images showed a clear change). With 5 or more images a side it says whether the sides
  likely differ (permutation p), where the distance falls among pairs of different Danbooru
  artists (closer than 95% / the closer half / farther than half: a position, not a verdict on
  who drew them; BENCHMARKS "What a compare distance means"), which images to open, and what
  training them together does. The web app's group comparison does the same, on plain CSD. A
  Sonnet review of the first version removed its over-claims.
- **`taste` says how far to trust it and why it ranks so** (from a Sonnet first-time-user test
  that read a CV AUC of 0.993 as "99% reliable"): training also reports the AUC with whole
  look-alike groups held out, closer to how it does on artists never rated (simulated 0.66-0.76
  against 0.96, new artists 0.47-0.64; BENCHMARKS "Taste: new artists"; the web app's taste tab too), and how the liked
  folder looks next to the disliked one; scoring names each image's closest rated picture,
  flags images unlike every rated one (their scores are near chance), and `--copy-to` copies the
  best (20, `--top`) into a new folder by rank. The model file keeps the rated vectors and file
  names (so whoever gets it sees what you rated; a damaged one is refused); older files still
  load. The grouped AUC needs 4 look-alike groups a side (with 2, a Sonnet review's test read
  0.04). The taste command moved to `cli_taste.py`.
- **`sort` never writes into the dataset** (from a Sonnet code review): with the new images in a
  sub-folder of the dataset, the results go next to the dataset, and an `-o` inside either folder
  is refused; `sorted\` no longer gets trainer configs that list only the new images; `--merged`
  says why a kohya folder was renamed (its new image count), warns when a rename is blocked by an
  existing folder, names unreadable dataset files, and says that `--export link` makes the
  dataset's images there hard links.
- **The report answers "which of my artists draw alike"** (from a Sonnet first-time-user test of
  a 12-artist collection, which could not tell from the page): with 3 or more sub-folders it lists
  each one's two closest sub-folders by average style, with its most typical image, and the
  families the artist map makes. The consistency scale and the six look scales label both ends;
  a folder with sub-folders is told that it is measured as one artist (so a collection reads as
  spread); group cards show one image of each set of near-duplicates and say how many sets there
  are; a short line at the top says what the page shows.
- **The web app's Dataset check says it is for LoRA training sets** and can be skipped when
  browsing styles.
- **`report --renders` lists every render** (from a Sonnet first-time-user test that could not
  tell which renders were off-style): likely copies of a training image first, with their
  similarity and the training image beside them, then renders outside the training set's style
  groups, then the rest, each with its closest training image; the check comes first on the page;
  the distance is read as in `compare` (5+ images a side: among pairs of artists, not the z
  scale). In the test, the 4 off-style renders were the first 4 outside the groups.
- **A library of many artists is pointed at 「依畫師」/by artist**: when the automatic cut makes
  many small groups in a folder with 20 or more sub-folders, the hint suggests grouping by artist
  instead of "medium"/"period" (checked on 3,800 works by 106 artists: ready in 52 s on the CPU
  with cached vectors, a 2 MB page). `cluster` says the same (`--granularity artists`); on those 106 artists
  it matched them at ARI 0.258 against 0.138 for the automatic cut.
- **`doctor` speaks Chinese on a Chinese system** and, when an NVIDIA card is present but torch is
  the CPU build, gives the pip command that swaps it (`--force-reinstall`: running setup.bat again
  would keep the CPU build, which pip counts as installed).
- **`scripts\setup.bat` swaps a CPU torch for the CUDA build** when an NVIDIA card is found (pip
  counted the CPU build as installed and kept it); an installed CUDA build is left alone (both
  paths checked with a dry run of the script).
- **Periods along the timeline** (`--granularity timeline --time name|mtime`): one artist's works,
  in time order, cut into contiguous periods where the style changes most. Two tests on the same
  cuts say whether no link to time was found, the style only drifts smoothly (one LoRA is usually
  fine) or changes more abruptly than a smooth curve explains (training the periods apart makes
  sense); with too few distinct works it does not guess, and a verdict on the p = 0.05 edge says
  so. Near-duplicates and runs of alike consecutive works (series) count once. On 14 Danbooru
  artists: 1 turns, 5 drift, 6 no link found, 2 too few
  (BENCHMARKS.md). In the web app (opened with `--time`) it is 「依時間分時期」 in the grouping
  menu, and the verdict shows after regrouping. A folder last grouped this way and reopened
  without `--time` falls back to automatic grouping.
  Periods export as `<repeats>_<name>_period01`… folders and show as 「時期 1」… in the web app.
- **LoRA render check in the report.** `style-atlas report TRAIN --renders RENDERS` adds a section
  that checks a LoRA's test images against its training set: the style distance and verdict (as
  `compare`), how many renders fall inside a training style group (the rule `sort` uses, with
  the same batch reading), how the look changed, renders that nearly repeat a training image
  (shown side by side: a sign of memorisation), and the renders least like the training set.
  Chinese and English; one HTML file to keep or send.
- **Command output in Chinese.** On a Chinese Windows (or a `zh` locale) the messages of
  every command (progress, notes, option errors, `--help`), `audit` labels, `doctor` and the
  web app's console window (what `StyleAtlas.bat` shows) are in Traditional Chinese, with the
  look words the web page uses ("偏亮、線條多") and columns aligned by display width. The web
  page's error lines a person can meet (merge, split, undo, compare, a stale page, a bad folder
  or image) follow too. `STYLE_ATLAS_LANG=en` or `zh` chooses. `report` writes its page in the same
  language unless `--lang` says otherwise. LORA_GUIDE section 7 explains the English wording.
- **Readable `compare`.** It prints a short summary (verdict, distance, look change,
  near-copies); `--json` keeps every number as before.
- `sort --export ... --trigger-captions` starts each placed caption with its group's trigger, as
  `cluster --trigger-captions` did for the dataset (kohya folder names lose their repeats);
  `--strip-tags` works as in `cluster`.
- `report --time name|mtime` (and the web app's saved report, with the page's time setting)
  shows where each style group sits in the folder's timeline, as `cluster --time` does.
- `report` and `sort` say which saved web-app groups they use and when they were saved;
  `--fresh` groups afresh instead.
- `doctor` shows how big the vector cache and the thumbnail cache have grown, and that the
  thumbnails can be deleted at any time.
- Windows scripts (`setup.bat`, `StyleAtlas.bat`, `StyleAtlas-console.bat`) speak Chinese and
  English; checked with dry runs of every branch they reach.
- `.jfif` files (what Chrome on Windows often saves JPEGs from X/Twitter as) are found.
- `python -m styleatlas ...` runs the command when Python's Scripts folder is not on PATH.
- **Exports write EXIF-turned photos upright** (`cluster`/`sort --export`, the web export): the
  pixels are turned and the tag removed, so kohya sd-scripts trains them the right way up; the
  source files are never changed (such an image is copied even in link mode). Among duplicates
  of equal size, an upright copy is kept for training.
- Exports name the trigger words they wrote into the captions, and warn when one is not plain
  English (SD 1.5 / SDXL text encoders split CJK into byte pieces); the web app's trigger
  checkbox explains the `<name>_<group>` form and that it is pinned first.
- **Greyscale tags checked against the picture** (`audit` and the web app's Check tab):
  greyscale pictures in a colour set whose caption lacks `monochrome` / `greyscale` (the
  LoRA would learn grey as part of the trigger; 15% of greyscale Danbooru works miss both
  tags), and captions tagged `greyscale` on a clearly coloured picture. Measured on 2,000
  Danbooru works (BENCHMARKS.md).
- **Photos turned only by EXIF** are listed by `audit` and the Check tab (`exif_rotated`):
  kohya sd-scripts reads the pixels as stored and ignores the EXIF orientation (checked in
  its `library/utils.py`), so a phone photo trains sideways; ai-toolkit and OneTrainer turn
  it upright.
- Web app, from an explore-and-share test: the home view fits every point whatever the window's
  shape (it cut off the top and bottom); notes keep a readable size at any zoom and start at
  their image (in Chinese 備註, apart from 標註 captions); a saved PNG or recording says where it
  went, and P works in a background tab too; the style path says to pick an end image; the
  help box closes on a click elsewhere; a group card says when another group comes from the same
  sub-folder (one artist in two styles or periods) and how to merge them; voting shows the
  running like/dislike count; the quantified axes say low → high; the comparison's footnote says
  plainly where its z scale comes from.
- Web app, after a code review: Enter in the note and group-name boxes waits for a Chinese input
  method to finish picking characters (it saved half-typed text); the same-sub-folder note is
  worked out once per list (it took about a second per rebuild at 10k images and 400 groups).
- **Notes on the map** (web app): a short note on an image (type it under the image's buttons,
  Enter) is drawn at its point on the map, kept next to the folder in `notes.json` and carried
  into saved shareable maps, so what someone found while exploring can be shown to others.
- `compare` names, for each side, the 3 images that best show the difference (typical of their
  side and unlike the other); the web comparison puts them first in each strip.
- `--time name` also reads dates written with separators in file names (`2023-05-12`, `2023_05_12`)
  as `20230512`, so they sort with undashed dates; tweet ids already sorted by time.
- Shareable maps (`map`, the web app's 「存成分享用地圖」) say their file size, and above 10 MB (Discord's
  free limit) suggest `--thumb 64`.
- **Export preview** (web: 「預覽」 next to 開始匯出): the folders, image counts and repeats an export
  would write, the set-aside folders, small groups, trigger words and steps per epoch, without
  writing anything (`cluster` without `--export` already prints its plan).
- **Common tags in the check** (`audit`, the Check tab; JSON `frequent_tags`): the tags in half or
  more of the captions with their share, since content in nearly every training image (one
  character, one outfit) is learned along with the style.
- **Same tag spelling on export**: `cluster`/`sort --export ... --fix-tag-spelling` (web: 「統一標籤寫法」)
  writes each tag the folder spells two ways the way most captions do, in the exported copies
  only, and lists the tags it respelt.
- **One tag spelt two ways** (`tag_spelling_mixed` in `audit` and the Check tab): when the
  captions write the same tag both as `long_hair` and as `long hair`, the captions using the
  less common way are listed; the text encoder reads the two as different words.

Clearer output (from three first-time-user tests: English, Chinese, and searching in Chinese):

- Wording that matches the measurements (from a product review by a second model): a folder
  more spread than 90% of single artists "may be a mix" (about 1 in 10 single artists lands
  there too) instead of "probably a mix"; the README states the search numbers, that periods
  are a first pass, what the taste model is, and that the ComfyUI nodes are experimental.
- `search` looks further down the ranking when near-copies are folded out, so each query gets
  `--top` results (it could show fewer); a query that does not exist or cannot be read is
  named; the folder ranking is in Chinese and says what a score of 0 or below means; the
  "all queries" heading and the folded count say they cover all queries together.
- `map --by-folder` speaks of families of sub-folders (it said "0 groups, 3 images
  unassigned, cut 0.35 set" for three folders), and `map` says how to open the file.
- `compare` lists at most 10 near-copy pairs (`--json` has all) and says that `calibrate`
  measures the z scale on your own folders.
- Every option has a `--help` line; `search` and `outliers` refuse `--top 0`.
- Web app, from a first-time web user test: the ? box first says what the map shows (closeness,
  colours, spread); the map stops turning when you grab it and stays still after an edit, which
  now keeps the camera where it was; excluded images are faded on the map and counted in the
  header; the outlier list shows the least typical tenth (5 to 60) instead of up to 60; a check
  that flags every image says why that may be; the image details say 離群度 instead of
  "outlier".
- Web app, continued: picking a group in "merge into" shows a confirm button instead of merging
  at once (arrow keys on the list used to merge), and the page then says Undo takes it back; a
  comparison opens with its verdict and says how many images each strip shows; the export
  message says how many images go to training and names the groups that fell under 3 images
  after duplicates and exclusions; the duplicates tab says that the export keeps one per group
  by itself; an image search shows each sub-folder's score next to its name.
- Web app: the export bar keeps its settings (layout, name, trigger, open or closed) across
  the reload that follows an edit.
- From a LoRA-preparation web test: the tag-spelling check names the tags (`audit` prints them,
  JSON `tags_spelt_two_ways`); excluded images are faded in every image list and counted on
  their group's card; exports say how many training images have a short side under 512 px
  (a 1024 training size enlarges them) and how repeats are balanced (about 100 images per group
  per epoch); an image's details show its caption tags.
- Each style group says which sub-folders its images come from ("來自：dayama 9"), in the report
  and on the web map, when the folder has several: a gallery sorted by artist shows which group
  is which artist.
- Chinese look words after 比 use the comparative form ("B 比 A 更亮、線條更多", "比 67% 的畫師
  色彩更淡"), and the report says what its two reference sets of Danbooru artists are.
- `search` prints each query once and says the list is ranked in the search space while the
  number shown is the plain cosine (so it is not always in order); `--by-folder` explains its
  score.
- `cluster` says when a style kept too few images after duplicates, outliers and exclusions to
  get a folder (its number is then skipped), says that folder names are only a plan without
  `--export`, names the small groups and warns that automatic repeats can overfit them, and
  warns when grouping by artist finds few groups.
- "In the range of one artist" adds that a mix of two or three artists often reads that way too
  (CLI, report, web page).
- `sort` names the dataset and the new folder, says "k of n fit", states the real minimum group
  size (3), and `sorted.csv` has each image's `limit` (it fits when distance <= limit).
- `outliers` and `taste score` say what their score column means (on stderr, so the table on
  stdout is unchanged); `taste train` says what its AUC means.
- `duplicates` lists one file per line with how alike each group is; `audit` lists paths
  relative to the folder, the buckets on one line, and how many files a list leaves out.

Fixes:

- **16-bit grey PNGs.** Pillow clips them when converting to RGB, so such an image was read as
  nearly all white (mean 254 instead of 127), and its style vector, look and softness were
  wrong. They are now scaled to 8 bits first (also 32-bit and float grey images). Vectors cached
  by an earlier version stay in the cache: to redo them, delete `vectors.sqlite` in the cache
  folder (`style-atlas doctor` shows where); everything is then embedded again once.
- In the web app, opening an original WebP image downloaded it instead of showing it (Windows
  did not know the WebP type, and the server sends nosniff); image types now come from the
  tool's own table.
- A caption saved with a UTF-8 byte order mark (Windows Notepad) hid its first tag from the
  watermark check, tag search and the per-group tags.
- Folders unzipped from a Mac no longer report their `__MACOSX` folder and `._name.png`
  metadata files as unreadable images.
- The render check no longer fails when no training group has 3 images or more.

Internal and docs:

- `cluster.fit_to_groups` takes plain CSD vectors and whitens inside, like `search`,
  `rank_folders`, `consistency` and `cluster_by_artist`; `cluster.batch_verdict` holds the batch
  reading shared by `sort` and the report (docs/API.md).
- README (Chinese and English): a command table, what `-o` means and where outputs go without
  it, `--fresh`, `.jfif`, the message language.
- Checked while CI is blocked: the full test suite on Python 3.10 and 3.12 (Windows), and a
  built wheel installed and run.

## 0.43.0 - 2026-10-10

- **Group by artist, for galleries of many artists.** `--granularity artists` (web: "by artist")
  groups in the search whitening's space at a fixed cut. On mixtures of held-out Danbooru
  artists it matched the artists better than `auto`: ARI 0.517 against 0.388 for 20 artists and
  0.420 against 0.349 for 50, about the same for 2-5. It is not for splitting one artist (whitening
  turns down the differences inside one artist), so it is an option, not the default.
- Tried and not used: a cut relative to the folder's own distances (BENCHMARKS.md).

## 0.42.0 - 2026-10-10

- Internal: every Python and page function is under 50 lines and every test file under 800
  (no change in behaviour).
- Docs: the number of groups is not a sign of a mix (two thirds of single artists split into 2+
  groups; consistency flags 7%). BENCHMARKS.md and the LoRA guide say so.

## 0.41.0 - 2026-10-10

- Web page: the map area is the page's main landmark and the page has a description
  (Lighthouse accessibility, best practices and SEO all at 100).
- Web app: a batch of fewer than 8 dropped images gets its count but no verdict ("too few
  images to judge the batch"), as `sort` does.

## 0.40.0 - 2026-10-10

- **`sort --by-folder` suggests new kohya repeats.** When new images that fit are added to a
  kohya folder whose repeats were set automatically (images x repeats near 100), it prints the
  new folder name, e.g. `10_x_style01: 10 + 5 images; rename it 7_x_style01`.
- Docs: a command table in the Chinese part of the README.

## 0.39.0 - 2026-10-10

- **A fairer "fits" rule, now the same in `sort` and the web app.** A new image fits a group
  when it is as close to the centre as 70% of the group's own images, each measured against the
  centre of the *others*, in the whitened space; only groups of 3 or more take images. The old
  rule (90% of members, measured against the full centre) let almost nothing into small groups:
  with 5 works per sub-folder only 11% of an artist's own new works fitted, now 68%. On large
  groups the two agree (69% own, 9% other artists, against 72% and 6%). In the web app's
  one-folder case, own works fitting rose from 46% to 61% with 1% of another artist's. Small
  groups let in more strangers (14% at 10 images, 24% at 5). BENCHMARKS.md has the tables.
- Docs: the README's bulk-exclude button is named as on the page, and the command list includes
  `embed` and `map --by-folder`. BENCHMARKS.md gives the source of the report's 278 artists.

## 0.38.0 - 2026-10-10

- **Web app: put unassigned images in their closest style.** New images added to a folder start
  as unassigned; a button on the Unassigned row now moves each one that fits its closest style
  (the rule `sort` uses: whitened CSD, as close to the centre as 90% of the style's own images)
  and leaves the rest. One undo step.

## 0.37.0 - 2026-10-10

- **`style-atlas sort`: add new images to a sorted dataset.** Each new image goes to the dataset
  group it is closest to (a sub-folder with `--by-folder`, e.g. an exported kohya dataset; else
  the style groups, as saved by the web app). It goes to `_unsure` when it is less alike than
  90% of that group's own images, and to `_already_in_dataset` when it is a near-copy of a dataset
  image. `sorted.csv` lists every image; `--export copy|link` places the files. Placement uses the
  search whitening: on 19 artists the tool never saw, with 10 as sub-folders, 91.5% of new works
  went to the right folder and 6% of other artists' works were let in (plain CSD: 85.7% and
  47%). BENCHMARKS.md has the tables.
- The web app's drop check no longer counts excluded images as members of their group.
- CI note: the 0.36.0 commit failed CI on Windows because of one new test (a t-SNE layout check
  that depended on the platform's scikit-learn); the 0.36.0 code itself was unaffected. The test
  now checks neighbour purity instead.

## 0.36.0 - 2026-10-10

- **Faster embedding**: the next images are opened, measured and scaled on 4 threads while the
  model works, so it no longer waits for files. 20% faster on CPU with large images (519 -> 415
  ms per image); the vectors are identical bit for bit. On a GPU, where loading was the slow part,
  the gain should be larger (not measured here).
- **The style report leaves out excluded images**: images excluded by hand (X) in the web app no
  longer count in the report's consistency, look, closest artists or group sizes, whether it is
  saved from the web app or made with `style-atlas report`; the header says how many were left
  out. Groups keep their numbers and names.
- **Fixes**: a report title such as `{body}` stays text (the page was filled in one pass per
  placeholder before); an image that fails to open no longer stops the report; the compare panel
  no longer shows, on side B, images that side A already holds (the numbers already left them
  out).

## 0.35.0 - 2026-10-10

- **Consistency reference from unseen artists**: the percentile is now read against 114 artists
  the whitening never saw (it was 250 artists it had seen, which put new single artists at the
  60th percentile instead of the 50th). Tested on held-out halves: 11% false alarms; 49% of
  two-artist, 85% of three and 100% of five-artist mixes flagged.

## 0.34.0 - 2026-10-10

- **Held-out re-check of search with several examples**: the learned model's gain over the
  examples' mean vector (+0.055 / +0.066 / +0.116 AP) had been measured on artists the search
  whitening was fitted on. On new artists it is about even (-0.016 to +0.042). It stays the
  default; the README no longer claims a gain. BENCHMARKS.md has both tables.

## 0.33.0 - 2026-10-10

- **Held-out re-check.** Style consistency and the which-artist ranking had been measured on
  artists the search whitening was fitted on. On 114 artists it never saw: consistency flags 51%
  of two-artist mixes, 91% of three and 100% of five, with 13% false alarms on single artists
  (was quoted as 63% / 93% / 100% and 8%); the folder mean names the right artist first for
  70.7% against 63.4% for the closest image (was 74.8%). The docs and the page now quote these.
  Plain CSD did worse on both, so the methods stay. BENCHMARKS.md has the tables.
- **Training buckets in the Check tab and `audit`**: how the images split into kohya's
  aspect-ratio buckets at 1024 (the same bucket list and nearest-ratio rule as sd-scripts), and
  how many buckets hold fewer than 4 images, which makes short batches at batch size 2 and up.

## 0.32.0 - 2026-10-10

- **Compare two selections**: pick images on the map, "Remember as A", pick another batch, then
  "Compare with A" (style distance, z, p-value and how they look different). Images in both
  batches count for A only.

## 0.31.0 - 2026-10-10

- **Save the 3D view as a PNG**: press P (in the web app and in a saved map), or "Save view as
  PNG" in the web app's "Advanced…" panel. The picture is the map as it is on screen.
- A folder with a single image lays out without a warning.

## 0.30.0 - 2026-10-10

- **Style report from the web app**: "Save style report" in the "Advanced…" panel writes the
  same page as `style-atlas report`, with the groups and names as they are on the page.
- The README is shorter: how it works, accuracy and research findings moved to
  `docs/ACCURACY.md` (nothing was cut).

## 0.29.0 - 2026-10-10

- **One-page style report.** `style-atlas report DIR` writes one HTML file: style consistency,
  the folder's look next to 278 Danbooru artists ("brighter than 89% of artists"), the closest
  artists of a reference library (`--artists LIB`), and each group's most typical images. It
  uses the groups and names saved by the web app. `--lang en` for English.

## 0.28.0 - 2026-10-10

- A failed model download now says so plainly (no traceback) and suggests
  `HF_ENDPOINT=https://hf-mirror.com` where huggingface.co cannot be reached; the README says it
  too. The web page shows the same message.
- `cluster` lists the groups by style number, and its consistency line is clearer.
- Fixes from a review (Sonnet): the count of folded near-copies was too low when fewer results
  than asked for remained; a search inside a #tag ranks against the whole folder before keeping
  the tagged images (the learned model's negatives were limited to the tag); a selection is
  compared with the rest of a group it belongs to; copying search results skips excluded images.

## 0.27.0 - 2026-10-10

- **Compare a selection with a group.** Images picked on the map (Shift+click or Shift+drag)
  can be compared with any group from the selection bar: style distance, z, p-value and how
  they look different.

## 0.26.0 - 2026-10-10

- **Search inside a caption tag.** With `#tag` in the filter box, a search by image only looks at
  the images whose captions have that tag (for example `#solo`); clearing the box searches all.
- After a kohya-layout export, the web page and `cluster` say how many steps one epoch takes at
  batch size 1 (images x repeats over the style folders).
- Larger axis names in the measures layout, starting at the end of each axis; the tool row
  stays on one line at 1280 px.

## 0.25.0 - 2026-10-10

- **Copy search results to a folder from the web page**: under the results, "Copy these to a
  folder" puts them with their captions into a new `search_matches` folder next to the folder,
  as `search --copy-to` does.
- **Search results without near-copies.** A hit that is a near-copy of a better hit (same picture,
  crop or recolour; the `duplicates` threshold) is left out and the next one moves up, so the
  results are not filled with variants of one picture. The web page says how many were folded;
  `search --keep-duplicates` lists them.
- **Clearer web page** (from a Sonnet product critique): the "Selected" tab is now "Details"
  (it holds search results, comparisons and the clicked image); the threshold box and the export
  fields have labels; the style consistency line stands out (accented when the folder looks
  mixed); the Check tab starts with a count of findings.

## 0.24.0 - 2026-10-10

- **Map of artists.** `map --by-folder` draws one point per sub-folder (an artist, a style)
  at its mean style, shown by its most typical image. The colours are loose families (cut 0.35,
  split-half agreement ARI 0.32; BENCHMARKS.md).
- **ai-toolkit config.** A kohya-layout export also writes `ai_toolkit_datasets.yaml`: one
  dataset entry per style folder (`folder_path`, `num_repeats`, `keep_tokens` ...) to paste
  under `datasets:`. Fields checked against ai-toolkit's `DatasetConfig`.
- Fixes from a review (Sonnet): the web check measured consistency in the current space (with
  "ignore characters" on, mixes looked tight) and pushed the searched folder out of the search
  cache; `cluster` shows consistency only on plain vectors; copies skip excluded images and no
  longer fail on an empty folder; folder names with DEL, C1 controls or line separators now
  survive the TOML and YAML configs.

## 0.23.0 - 2026-10-10

- **Copies of a folder image among dropped images.** When you search with images in the web app,
  those that are near-duplicates of one in the folder (same picture, crop or recolour; the
  0.95 threshold of `duplicates`) are listed first: for LoRA test renders a sign that the LoRA
  repeats a training image, for found images a sign that the folder already has them.
  `compare A B` lists them too, as `b_copies_of_a`.
- **Docs from a newcomer's review** (Sonnet, as a LoRA trainer reading the docs for the first time):
  LORA_GUIDE is pointed to first; manual install creates the `.venv`; a warning before the CLI
  export that it ignores the web app's hand edits; the same button names in every document;
  plain words for ARI, AMI, z and hub; a repeats-to-steps example; a new "after training"
  section (check a batch of LoRA renders); the full `cluster` option list.
- **Demo images** vary more inside each style (10 near-duplicates of 72 instead of 42), and all
  screenshots were retaken.
- A whole drive picked as the folder gets results in `D_style_atlas` instead of `_style_atlas`.

## 0.22.0 - 2026-10-10

- **Style consistency.** The Check tab and `cluster` say how spread the folder's style is
  next to 250 single Danbooru artists, on random 10-image samples. More spread than 90% of
  them reads as a probable mix: 63% of two-artist and 93% of three-artist mixes, 8% of
  single artists (BENCHMARKS.md). Not meant for AI renders from one model with the same
  characters, which always look tight.
- **Faster search in the web app.** Each search of a large folder recomputed the library's
  neighbour density: 4.1 s per search at 20,000 images. It is now kept (and prepared when the
  app starts), so later searches take milliseconds.
- **Check: watermarks and signatures.** Images whose caption has a tag such as `watermark`,
  `signature`, `artist name` or `web address` (Danbooru and WD14 tags) are listed: a LoRA
  learns the mark along with the style.
- **Which artist does this look like?** `search --by-folder` ranks the sub-folders of `--in`
  (one per artist or style) by their mean style and names each one's closest image. On 284
  Danbooru artists, the right one came first for 74.8% of held-out works, against 63.4% for the
  artist of the closest image (BENCHMARKS.md). The web app lists the closest sub-folders too
  when you search by image in a folder that has them; a click shows only that folder. Loose
  images at the top level and images you excluded do not count.

## 0.21.0 - 2026-10-10

- **Configs for more trainers.** A kohya-layout export now also writes
  `diffusion_pipe_dataset.toml` (diffusion-pipe, often used for Anima) and
  `onetrainer_concepts.json` (OneTrainer), with the same folders and repeats as
  `dataset_config.toml`. Formats checked against both projects' sources.
- **Check: enlarged and heavily compressed images.** `audit` and the Check tab list images
  enlarged from a smaller original (or blurred) and JPEGs under quality 70. The style map
  cannot find enlarged images: CSD looks at 224 px, and a copy enlarged from half the size sits
  0.0006 from its original, against 0.139 between two seeds of one recipe. Softness (the finest
  octave's detail over two octaves coarser, judged at training size, about 1024 x 1024) below
  0.10 flagged 0 of 2,093 clean images, large originals included, and 92-100% of 2x and 100%
  of 3x enlargements (BENCHMARKS.md).
- Pillow 10.3 or newer is required (CVE-2024-28219 was fixed there; the images a folder holds
  are untrusted input). torch stays at 2.4+: the CSD weights are loaded with `weights_only=True`
  from a pinned Hugging Face revision, and newer torch would shut out older ComfyUI setups.
- Internal: `cli.py` (782 lines) split into `cli_common.py` (shared helpers) and `cli_lora.py`
  (the `cluster` command); the commands and options are unchanged.
- Internal: the web app's group edits (move, merge, rename, split, exclude, undo) moved from
  `serve.py` (711 lines) to `serve_edits.py`.

## 0.20.0 - 2026-10-10

- **Illustrated web guide** in Traditional Chinese, `docs/WEB_GUIDE.md`: the three steps (check, sort
  the styles, export) and the other tools, with screenshots. All screenshots were retaken with the
  corrected colours.
- **Fix: true colours on the 3D map.** The thumbnails were decoded from sRGB but never encoded
  back for the screen, so every image on the map looked darker and more saturated than the file
  (the demo's yellow 255,183,3 showed as orange 255,121,0; group-colour dots likewise). Group
  names and axis labels had the opposite error and looked washed out. Checked by pixel counts
  on a screenshot: 12,018 pixels of the true yellow, 0 of the wrong orange.

## 0.19.0 - 2026-10-10

- **Workflow steps** at the top of the web app's side panel: "① Check → ② Sort the styles →
  ③ Export", each jumping to its tab or opening the export panel.
- **A calmer bottom bar** (a Sonnet review of screenshots at 1366x768): one row with search,
  grouping, "Export folders…", "Save shareable map" and "More…". The export options open in a
  panel above it, ending in "Export now"; the character-axis switch and the reference folder
  are under "More…" (shown open when one of them is on).
- Each finding in the Check tab has "Select these", so the images can be excluded or moved at
  once; the selection bar now says "Exclude these N" / "Restore these N".
- Clearer export labels ("LoRA name (folder name)", "max per style", "tags to remove"), more
  solid group-name labels on the map, a backdrop behind the title, a tooltip on the theme button.

## 0.18.0 - 2026-10-10

- Fixes from a Sonnet review of this release:
  - Selected images are now shown on top of the normal view instead of replacing it, so a box
    drawn while one group is in focus no longer picks up hidden images.
  - A per-style cap below the minimum group size no longer sends every image to unassigned
    (group size is judged before trimming).
  - The box selection resets if the drag is interrupted.
  - A late `#tag` answer no longer overwrites a changed filter, and `#__` matches nothing.
  - `--max-per-group` takes 1 or more, and the diverse pick never takes one image twice.
  - The open_clip message is filtered by itself instead of all warnings.
  - `StyleAtlas.bat` handles a whole drive (`D:\`), and says what to do if no picker opened.
  - `.gitattributes` keeps CRLF in `.bat` and `.ps1` files, also in GitHub zip downloads.
- **Remove tags in the exported captions** (`--strip-tags "sketch, monochrome"`; web: "remove tags"
  in the export row): whole tags only, case, spaces and underscores ignored; your own captions
  are never changed. Useful with trigger captions, so the trigger takes the style.
- **Check a batch against the folder**: dropping several images now also reports how many fall
  inside one of the folder's style groups (as close as 90% of that group's own images), with
  a verdict for the batch and the closest group on each image. Measured on held-out Danbooru
  works: 69% of an artist's own landed inside, 15% of other artists' (BENCHMARKS.md).
  Suggested by a Sonnet product review.
- **Find by caption tag**: `#monochrome` (or any part of a tag, `#mono`) in the web app's filter
  box lights up the images whose captions have it; case, spaces and underscores are ignored.
  Suggested by a Sonnet product review.
- **Select several images at once**: Shift+click (map or lists) or Shift+drag a box on the
  map, then exclude, un-exclude or move them all from the bar that appears; a batch move is
  one undo step, and Esc clears the selection. `api/exclude` and `api/move` take `items`.
  Suggested by a Sonnet product review.
- **Cap per style** (`--max-per-group N`; web: "max per style" in the export row): a larger
  group keeps N images that cover it, picked by farthest-point sampling from its most central
  image; the rest go to `_trimmed/`, after duplicates, outliers and exclusions, and repeats
  follow the kept count. On a group made of six sub-styles, 8 picks covered all six and beat
  95% of random picks. Suggested by a Sonnet product review.
- Double-clicking `scripts\StyleAtlas.bat` without dragging a folder onto it opens a folder
  picker (`scripts\pick_folder.ps1`) instead of an error. Paths with spaces and Chinese
  characters pass through intact (checked with a stand-in path), and the dialog was seen
  opening on top of other windows.
- Each group card lists its 3 closest groups (style distance between the groups' centres),
  linked: handy for deciding what to merge, and for seeing which styles are related.
- When "auto" cuts a folder into many small groups (more than 12, and more than one per 8
  images), the web app suggests "medium" or "period" for a single artist's folder. The varied
  artist that auto had cut into 46 groups now gets this hint.
- The open_clip warning "Model initialized randomly" no longer appears while the model loads.
  It was harmless (the CSD weights load right after, strictly checked) but alarming. The built
  wheel was checked end to end with the real model on CPU.

## 0.17.0 - 2026-10-10

- **Reference folder in the web app**: type a folder of styles you know and press "Load
  reference" (or clear it). The measures layout gets its originality axis without restarting with
  `--reference`; groups, edits and positions stay. Network folders (`\\host\share`, mapped
  network drives) are refused there, since on Windows opening one sends the user's credentials
  to that host (a Sonnet security review); `--reference` still takes them.
- A first-time hint in the status line says where to start, when a folder is opened for the
  first time.
- Fixes from a Sonnet review:
  - The map turns at the same speed at any frame rate, so a recording is one turn on a
    120/144 Hz screen too.
  - Recording stops cleanly if the tab goes to the background (no broken file), always restores
    rotation, and frees its capture stream; the Record and Rotate buttons are disabled meanwhile.
  - Check also lists files that can no longer be opened.
  - The static map's tab is labelled "Outliers" again; "Check" is the web app's.

## 0.16.0 - 2026-10-10

- **Record a turn**: one button saves an 8-second video (MP4 where the browser can, else WebM) of the 3D map
  turning once, made in the browser, for sharing. It works in the shareable HTML map too.
- Every control in the web app has a one-line tooltip (Chinese and English), and the form fields
  made on the fly carry names and labels.
- **Check tab** in the web app (the Outliers tab, renamed): "Check" runs the dataset audit of
  `audit` and lists small, extreme, animated and truncated images, missing or empty captions and
  greyscale images in a colour set, with thumbnails to exclude (X). With this, the whole LoRA
  preparation can be done in the browser.
- **Compare with…** on an open group in the web app: style distance, z and verdict, a
  permutation p-value, and how the other group looks next to this one, as `compare` does for
  two folders.
- **Group names float in the 3D map** at each group's centre (the 16 largest groups; the
  "Names" button hides them). With one group in focus the other names fade.
- **Find more like these** in the web app's excluded list: exclude two or three strays by
  another artist, and the rest are listed first. From three strays the top 30 held 98% of the
  others, while outlier scores found only half (BENCHMARKS.md).
- `cluster --export` sends the images you excluded with X in the web app to `_excluded/`, as
  the web app's own export does. Hand moves, merges and names stay with the web export. An
  unreadable `excluded.json` is reported and left as it is (a Sonnet review found that a CLI
  run used to rename it). `--drop-outliers N` now picks N among the images not already excluded.
- The "measures" layout frames the whole axis cube when it opens or on Reset, with larger axis
  labels.
- README and LoRA guide: commands no longer carry trailing `#` notes (Windows cmd passed them on
  as arguments), and the docs say that `serve` keeps its console busy, which edits need the
  web export, and where `taste_model.npz` comes from.

## 0.15.0 - 2026-10-10

- **Look measures**: six readable image statistics per image (brightness, contrast,
  colourfulness, warmth, lines, flatness) that say *how* styles differ. Each image is measured
  once and cached, and images embedded from now on are measured while they are open.
  - Web app: words on every group card ("cooler, more line work") and six new axes in the
    "measures" layout.
  - `clusters.csv` gets a column per measure; `clusters.json` a per-group profile and words;
    `cluster` prints the words per group; `compare` reports B minus A in pooled SDs.
  - Chosen on 3,259 Danbooru works by 306 artists: 13-40% of each measure's spread is between
    artists; three candidates were dropped as near-duplicates of the others (BENCHMARKS.md).
- `audit` lists greyscale images mixed into a colour set (sketches, comic pages), unless most of
  the folder is greyscale. 8% of the Danbooru works were greyscale, with a clear gap at
  colourfulness 0.02.

## 0.14.0 - 2026-10-10

- **`--ignore-characters`** (cluster, map, serve, search): finds the characters from the CSD
  content vectors and compares styles as if all were drawn on the same character. On 16 Anima
  recipes x 4 characters, same-recipe search rose from 58% (`--neutralize 1`) to 70% and
  recipe-pair AUC from 0.75 to 0.89; with 2 characters the two corrections are about equal.
  Not for mixed artists. `--neutralize N` stays.
- The web app's **Ignore the character axis** switch uses it. The page now posts to `api/space`
  (`{"space": "plain" | "characters" | "neutralize-N"}`) instead of `api/neutralize`, and
  `groups.json` keeps a `space` name; files with the old `neutralize` count still load.
- `bench` also reports retrieval with `--neutralize 1` and with `--ignore-characters`, so a
  labelled sample shows whether either correction helps a collection.
- **`dataset_config.toml`** is written with every kohya export (CLI and web app): a kohya
  sd-scripts dataset config listing each style folder with its repeats, with `keep_tokens = 1`
  when trigger captions are on. Resolution and batch size are starting points.

## 0.13.0 - 2026-10-10

- **README screenshots**, made from generated abstract images, so no one's artwork appears.
  `scripts/make_demo_images.py` makes the same 72 images (four styles) for trying the tool.
- `StyleAtlas-console.bat` opens in the project folder and lists the demo-image command;
  `setup.bat` says how large the torch download is.
- Tests: the CLI commands run end to end with a stand-in encoder (package coverage 75% -> 88%),
  and `pytest -m model` checks the real CSD model on the demo styles (four groups, ARI 1.0).
- Docs: a development section, the console window noted for commands, the GitHub sign-in, the
  Style Gate's distance scale measured (same artist 0.405, different 0.566), old labels in
  BENCHMARKS marked as history.

## 0.12.0 - 2026-10-10

- **Shortcut list**: "?" (key or button) shows the keyboard and mouse shortcuts.
- The map subtitle no longer runs under the top controls on laptop-size screens; loading dots are
  smaller.
- The server keeps up to 64 waiting connections (was 5) and the page retries a failed thumbnail
  once: one load saw thumbnails refused while the server was busy.
- Code: the HTTP side of `serve` moved to `webserver.py`.

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
