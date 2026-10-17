"""Local web app: the 3D map plus live search (drop an image), re-grouping and folder export.

Security model: the server binds to 127.0.0.1 only, answers only requests whose Host header is
the local address (blocks DNS-rebinding pages from reading your images), serves files only by
index into the scanned folder (no paths from the client), and requires a custom header on every
POST (a cross-site form or simple request cannot set it).
"""

from __future__ import annotations

import base64
import io
import os
import subprocess
import sys
import threading
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np

from styleatlas.atlas import (
    LOAD_ERRORS,
    MIN_FOLDERS,
    Atlas,
    EncodeOptions,
    build_atlas,
    folder_atlas,
    get_encoder,
)
from styleatlas.cluster import (
    ARTISTS,
    FOLDERS,
    GRANULARITY,
    METHODS,
    PERIODS,
    cluster_by_artist,
    cluster_by_folder,
    cluster_styles,
    fit_to_groups,
    folder_families,
)
from styleatlas.consistency import consistency
from styleatlas.dataset import (
    LAYOUTS,
    MAX_PER_GROUP_RANGE,
    SET_ASIDE,
    audit,
    caption_of,
    clean_group_name,
    distinctive_tags,
    is_unassigned,
    kept_copy,
    norm_tag,
    plan_folders,
    read_tags,
    spelling_fixes,
    tag_summary,
)
from styleatlas.duplicates import copies_of
from styleatlas.export import (
    KOHYA_CONFIG,
    copy_ranked,
    export_folders,
    output_dir,
    parse_tags,
    steps_per_epoch,
    trigger_of,
    write_table,
)
from styleatlas.groupfile import carry_names, load_groups
from styleatlas.images import (
    cached_thumbnail,
    file_times,
    labels_from_folders,
    load_rgb,
    mixed_names_error,
    mixed_numbering,
)
from styleatlas.lang import tr
from styleatlas.look import LOOK_NAMES, difference
from styleatlas.metrics import (
    CHARACTERS,
    MAX_NEUTRALIZE,
    PLAIN,
    StyleScale,
    StyleSpace,
    artist_reading,
    distinctive_order,
    group_difference,
    space_name,
)
from styleatlas.persist import RelPathMap
from styleatlas.quality import LOW_JPEG
from styleatlas.report import (
    build_payload,
    compute_layout,
    default_thumb_px,
    map_payload,
    render_html,
    with_reference,
    write_payload,
)
from styleatlas.search import fold_hits, folder_verdict, rank_folders, search, style_path, warm
from styleatlas.serve_edits import MAX_NAME, GroupEdits
from styleatlas.taste_session import TasteSession
from styleatlas.timeline import TIMELINE, cluster_timeline, on_edge, verdict

SEARCH_TOP = 48
FOLDER_TOP = 5  # closest sub-folders listed with a search
MAX_QUERY_IMAGES = 32
EXPORT_MIN_GROUP = 3  # groups left smaller after set-asides go to _unassigned (as in the CLI)
MAX_NOTE = 80  # characters of a note on an image (it is drawn on the map)
COMPARE_ROUNDS = 199  # permutations for a group comparison's p-value (resolution 0.005)
# a side whose largest sub-folder holds less than this share is several artists: the artist scale
# (one artist against another) does not read it
MIXED_SHARE = 0.8
MIN_SIDE_RANGE = (64, 8192)  # the check tab's smallest-side setting
MAX_PATH_TEXT = 1000  # longest folder path accepted from the page
MAX_TAG_TEXT = 200
MAX_REPEATS = 100  # kohya repeats set by hand on the export bar
NEAR_ARTISTS = 8  # closest folders listed for each in the artists tab
VIEW_PX = 320  # the group view's tiles go up to 240 px wide, sharp on 1.25x screens


DRIVE_REMOTE = 4  # GetDriveTypeW: a mapped network drive


def local_folder(text: str) -> Path:
    """A folder typed into the page, on a local disk. Network paths are refused: on Windows,
    merely opening \\\\host\\share sends the user's credentials to that host. Give those with
    --reference when starting instead."""
    path = Path(text).expanduser()
    if str(path).startswith(("\\\\", "//")):
        raise ValueError(
            tr(
                "network folders are not accepted here; start with --reference instead",
                "這裡不接受網路資料夾；請在啟動時用 --reference 指定",
            )
        )
    if os.name == "nt" and path.drive:
        import ctypes

        if ctypes.windll.kernel32.GetDriveTypeW(path.drive + "\\") == DRIVE_REMOTE:
            raise ValueError(
                tr(
                    "network drives are not accepted here; start with --reference instead",
                    "這裡不接受網路磁碟機；請在啟動時用 --reference 指定",
                )
            )
    if not path.is_dir():
        raise ValueError(tr(f"not a folder: {text}", f"不是資料夾：{text}"))
    return path


def _besides(found: list, copies: list[dict]) -> list:
    """Search hits other than the folder's copies of a query image, which the page lists apart
    (an image dragged in from the folder would otherwise lead its own results at 1.00)."""
    shown = {c["i"] for c in copies}
    return [h for h in found if h.index not in shown]


ARTIST_MAP = "artist_map.html"


def mixes_artists(folders: list[str], rows: list[int]) -> bool:
    """Whether these images come from several sub-folders (artists, in a library), none holding
    MIXED_SHARE of them. A folder without sub-folders is one artist's work."""
    if len(set(folders) - {""}) < 2 or not rows:
        return False
    counts = Counter(folders[i] for i in rows)
    return max(counts.values()) / len(rows) < MIXED_SHARE


class StyleAtlasApp(GroupEdits):
    """Holds one scanned folder in memory and answers the web page's requests."""

    def __init__(
        self,
        atlas: Atlas,
        opts: EncodeOptions,
        projection: str = "auto",
        title: str | None = None,
        progress: Callable[[str], None] = lambda _: None,
        time_source: str = "none",
        space: str = PLAIN,
        reference: Atlas | None = None,
    ):
        self.opts = opts
        self.title = title
        self.time_source = time_source
        atlas = atlas.with_looks(opts, progress)
        self.raw = atlas  # vectors as embedded; `atlas` is the view in the current space
        self.raw_reference = reference
        self.projection = projection
        self.progress = progress
        self.settings: dict = {"method": "agglomerative", "threshold": None}  # None: auto
        self.revision = 0  # bumped on every regroup / hand edit; edits must name the one they saw
        self.thumb_px = default_thumb_px(len(atlas))
        self._thumbs: dict[int, bytes] = {}
        self._tag_sets: list[set[str]] | None = None
        self.folders = labels_from_folders(atlas.paths, atlas.root)  # first sub-folder
        self._lock = threading.Lock()
        self._model_lock = threading.Lock()  # one embedding at a time (uploads, a reference)
        self.taste: TasteSession | None = None
        self.group_names: dict[int, str] = {}  # group id -> name, carried across regroupings
        self._history: list[tuple] = []  # earlier (clustering, settings, names, space) for undo
        self._spaces: dict[str, tuple] = {}  # name -> (space, layout); the raw vectors never change
        saved = load_groups(self._groups_path, atlas)
        if saved and saved.space is not None:
            space = saved.space  # the switch as it was left in the page
        if saved:  # group as the page last did (e.g. by artist), then put the saved labels on
            self.settings = {**self.settings, **saved.settings}
        self._apply_space(space)
        self.restored = saved is not None
        if saved:
            self._restore(saved)
        self.taste = TasteSession(self.atlas, self.out_dir)
        self._excluded = RelPathMap(self.out_dir / "excluded.json", atlas)
        self.excluded: set[int] = {i for i, v in self._excluded.values.items() if v is True}
        # the copy picked by hand to keep in a near-duplicate group (else the largest is kept)
        self._kept = RelPathMap(self.out_dir / "kept_copies.json", atlas)
        self.kept_copies: set[int] = {i for i, v in self._kept.values.items() if v is True}
        self._notes = RelPathMap(self.out_dir / "notes.json", atlas)  # rel path -> note

    def _apply_space(self, name: str) -> None:
        """(Re)build everything that depends on the vector space (see metrics.StyleSpace)."""
        raw = self.raw
        self.space = self._fitted(name)
        self.atlas = replace(raw, style=self.space.apply(raw.style, raw.content))
        if name not in self._spaces:  # switching back (or Undo) reuses the first layout
            ref = self.raw_reference
            if ref is not None:
                ref = replace(ref, style=self.space.apply(ref.style, ref.content))
            layout = compute_layout(self.atlas, self.projection, self.progress, ref)
            self._spaces[name] = (self.space, layout)
        self.layout = self._spaces[name][1]
        s = self.settings
        try:
            self.clustering = self._grouped(
                s.get("method", "agglomerative"), s.get("threshold"), s.get("k")
            )
        except ValueError as e:  # e.g. saved as periods along the timeline, reopened without --time
            self.progress(
                tr(f"{e}; the grouping menu is back to automatic", f"{e}；分群方式改回自動")
            )
            s = {"method": "agglomerative", "threshold": None}
            self.clustering = self._grouped("agglomerative", None, None)
        self.settings = {key: v for key, v in s.items() if key != "edited"}
        if self.taste is not None:
            self.taste.atlas = self.atlas
            self.taste._refit()

    def _grouped(self, method: str, threshold: float | None, k: int | None, atlas=None):
        atlas = atlas or self.atlas
        if method == ARTISTS:  # on the plain vectors, whatever the space (cluster_by_artist)
            return cluster_by_artist(self.raw.style)
        if method == FOLDERS:
            return cluster_by_folder(atlas.style, labels_from_folders(atlas.paths, atlas.root))
        if method == TIMELINE:  # contiguous periods in time order (timeline.py)
            if self.time_source == "none":
                raise ValueError(
                    tr(
                        "periods along the timeline need a time: open the folder with --time name "
                        "(ids or dates in the file names) or --time mtime",
                        "依時間分時期需要時間資訊：開啟資料夾時加 --time name（檔名裡的編號或日期）"
                        "或 --time mtime",
                    )
                )
            times = file_times(atlas.paths, self.time_source)
            if self.time_source == "name" and mixed_numbering(times):
                raise mixed_names_error()
            return cluster_timeline(
                atlas.style, times, k or PERIODS, content=self.raw.content, plain=self.raw.style
            )
        return cluster_styles(atlas.style, method=method, threshold=threshold, n_clusters=k)

    def _fitted(self, name: str) -> StyleSpace:
        if name in self._spaces:
            return self._spaces[name][0]
        return StyleSpace.fit(name, self.raw.style, self.raw.content)

    def set_space(self, body: dict) -> dict:
        """Switch the vector space. Groups are rebuilt in it (names follow their images); Undo
        returns to the old space with its groups and hand edits."""
        name = space_name(body.get("space"))
        if name is None:
            choices = f"{PLAIN}, {CHARACTERS} or neutralize-1 to neutralize-{MAX_NEUTRALIZE}"
            raise ValueError(f"space must be {choices}")
        with self._lock:
            if name != self.space.name:
                self._fitted(name)  # the step that can fail, before anything changes
                self._remember()
                old, names = self.clustering.labels, self.group_names
                self._apply_space(name)
                self.group_names = carry_names(old, self.clustering.labels, names)
                self.revision += 1
                self._save_groups()
            return {"space": name, "clusters": self.clustering.n_clusters}

    @property
    def out_dir(self) -> Path:
        return output_dir(self.raw.root)

    def page(self) -> str:
        with self._lock:  # votes and exclusions may change in another request thread
            payload = build_payload(
                self.atlas,
                self.clustering,
                self.layout,
                lambda i: f"thumb/{i}",
                lambda i: f"image/{i}",
                self.title,
                self.time_source,
                self._group_tags(),
            )
            payload["live"] = {
                "settings": dict(self.settings),
                "granularity": GRANULARITY,
                "periods": PERIODS,
                "cut": self.clustering.params.get("threshold"),  # the auto cut, when auto
                "taste": self.taste.state(),
                "excluded": sorted(self.excluded),
                "revision": self.revision,
                "space": self.space.name,
                "names": {str(k): v for k, v in self.names_by_group().items()},
                "restored": self.restored,
                "can_undo": bool(self._history),
                "dup_keep": self._dup_keep(),
                "timeline": self._timeline_reading(),
            }
            payload["notes"] = self.notes()
        return render_html(payload)

    def _timeline_reading(self) -> dict | None:
        """Periods along the timeline: their tests' verdict for the page's LoRA advice."""
        params = self.clustering.params
        if self.clustering.method != TIMELINE or "p_time" not in params:
            return None
        return {
            "verdict": verdict(params),
            "edge": on_edge(params),
            "distinct": params.get("distinct"),
        }

    def _dup_keep(self) -> list[int]:
        """The image each near-duplicate group keeps at export (call under the lock)."""
        aside = set(self.excluded)
        return [
            kept_copy(self.atlas.paths, group, aside, self.kept_copies)
            for group in self.layout.duplicates
        ]

    def keep_copy(self, body: dict) -> dict:
        """Keep image "i" at export instead of the other copies in its near-duplicate group."""
        i = self._index(body)
        with self._lock:
            group = next((g for g in self.layout.duplicates if i in g), None)
            if group is None:
                raise ValueError(tr("this image has no near-duplicates", "這張圖沒有近重複的圖"))
            self.kept_copies = (self.kept_copies - set(group)) | {i}
            self._kept.values = {j: True for j in self.kept_copies}
            self._kept.save()
            return {"dup_keep": self._dup_keep()}

    def notes(self) -> dict[str, str]:
        """The notes on images, by index (as the page numbers them)."""
        return {str(i): v for i, v in self._notes.values.items() if isinstance(v, str) and v}

    def note(self, body: dict) -> dict:
        """Set ("text") or clear (empty text) the note on image "i"; kept next to the folder in
        notes.json by relative path, like the exclusions, and drawn at the image on the map."""
        i = self._index(body)
        text = body.get("text", "")
        if not isinstance(text, str) or len(text) > MAX_NOTE:
            raise ValueError(
                tr(f"a note is text of up to {MAX_NOTE} characters", f"註記最多 {MAX_NOTE} 個字")
            )
        text = " ".join(text.split())
        with self._lock:
            if text:
                self._notes.values[i] = text
            else:
                self._notes.values.pop(i, None)
            self._notes.save()
            return {"notes": self.notes()}

    def _read_tags(self) -> None:
        tags = [_tags_or_none(p) for p in self.atlas.paths]
        with self._lock:
            if self._tag_sets is None:
                self._tag_sets = tags

    def caption(self, body: dict) -> dict:
        """One image's caption tags, in the caption's order (none without a caption file)."""
        i = self._index(body)
        side = caption_of(self.atlas.paths[i])
        return {"tags": read_tags(self.atlas.paths[i]), "file": side.name if side else None}

    def tagged(self, body: dict) -> dict:
        """Images whose caption has a tag containing the text (case, spaces and underscores
        ignored): "#mono" finds monochrome and greyscale-monochrome alike."""
        text = body.get("tag")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TAG_TEXT:
            raise ValueError(tr("tag must be some text", "請輸入標籤"))
        want = norm_tag(text)
        if not want:
            raise ValueError(tr("tag must have a letter or a digit", "標籤至少要有一個字母或數字"))
        if self._tag_sets is None:
            self._read_tags()
        with self._lock:
            sets = self._tag_sets or []
        hits = [i for i, tags in enumerate(sets) if any(want in norm_tag(t) for t in tags)]
        return {"hits": hits}

    def _group_tags(self) -> dict[int, list[str]]:
        """Each group's characteristic caption tags (captions are read once per session)."""
        if self._tag_sets is None:
            self._tag_sets = [_tags_or_none(p) for p in self.atlas.paths]
        summary = tag_summary(self.atlas.paths, self.clustering, tags=self._tag_sets)
        return distinctive_tags(summary)

    def save_report(self, body: dict) -> dict:
        """Write the one-page style report (`style-atlas report`) for the groups and names as
        they are now, without the excluded images, next to the exports."""
        from styleatlas.report_card import write_report

        lang = body.get("lang", "zh")
        if lang not in ("zh", "en"):
            raise ValueError("lang must be zh or en")
        with self._lock:
            raw, clustering, names = self.raw, self.clustering, self.names_by_group()
            excluded = sorted(self.excluded)
            title = self.title or raw.root.name or "style report"
        out = write_report(
            raw,
            clustering,
            self.out_dir / "style_report.html",
            title,
            names=names,
            lang=lang,
            excluded=excluded,
            time_source=self.time_source,
        )
        return {"file": str(out)}

    def save_map(self, body: dict) -> dict:
        """Write the map as it is now (groups, hand edits, names) as one shareable HTML file with
        the thumbnails inside, next to the exports."""
        with self._lock:
            atlas, clustering, layout = self.atlas, self.clustering, self.layout
            names = {str(k): v for k, v in self.names_by_group().items()}
        out = self.out_dir / "map.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = map_payload(
            atlas, clustering, out, title=self.title, time_source=self.time_source, layout=layout
        )
        payload["names"] = names
        with self._lock:
            payload["notes"] = self.notes()
        path = write_payload(payload, out)
        return {"file": str(path), "mb": round(path.stat().st_size / 1e6, 1)}

    def artist_map(self, body: dict) -> dict:
        """The sub-folders (e.g. one per artist) as one point each at their average style,
        grouped into families of similar folders, as `map --by-folder`: written next to the
        exports and served at /artist_map."""
        with self._lock:  # images excluded by hand do not pull their folder's average
            kept = [i for i in range(len(self.raw)) if i not in self.excluded]
        folders = folder_atlas(self.raw.subset(kept))  # plain CSD, as the cut was measured
        if len(folders) < MIN_FOLDERS:
            raise ValueError(
                tr(
                    f"the artist map needs {MIN_FOLDERS} or more sub-folders (e.g. one per "
                    f"artist); this folder has {len(folders)}",
                    f"畫師地圖需要 {MIN_FOLDERS} 個以上的子資料夾（例如每位畫師一個）；"
                    f"這個資料夾有 {len(folders)} 個",
                )
            )
        families = folder_families(folders.style)
        title = tr(
            f"{self.title or self.raw.root.name}: artists",
            f"{self.title or self.raw.root.name}：畫師地圖",
        )
        path = self.out_dir / ARTIST_MAP
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = map_payload(folders, families, path, self.projection, title=title)
        payload["families"] = True
        names = labels_from_folders(folders.paths, folders.root)
        for point, name in zip(payload["points"], names, strict=True):
            point["n"] = name  # each point is an artist: its name, not its typical file
        write_payload(payload, path)  # the shareable file: links relative to it
        index = {p: i for i, p in enumerate(self.raw.paths)}
        for k, point in enumerate(payload["points"]):  # the served copy: the app's own images
            point["f"] = f"image/{index[folders.paths[k]]}"
        self._artist_map_page = render_html(payload).encode("utf-8")
        return {
            "file": str(path),
            "folders": len(folders),
            "families": families.n_clusters,
            "url": "artist_map",
        }

    def artist_map_html(self) -> bytes | None:
        """The artist map made in this session (its images served by this app), or None."""
        return getattr(self, "_artist_map_page", None)

    def copy_hits(self, body: dict) -> dict:
        """Copy images ("items", e.g. search results) with their captions into a new
        `search_matches` folder in the output folder, as `search --copy-to` does; with a "name"
        (a group's), into copies/<name> instead."""
        name = body.get("name")
        if name is not None and (
            not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME
        ):
            raise ValueError(f"name must be text (at most {MAX_NAME} characters)")
        folder = self.out_dir / ("copies" if name else "")
        with self._lock:
            items = [i for i in self._indices(body) if i not in self.excluded]
            subset = self.raw.subset(items)
        if not items:
            raise ValueError(tr("all of these images are excluded", "這些圖都已經排除了"))
        result = copy_ranked(
            subset, folder / (clean_group_name(name) if name else "search_matches")
        )
        return {
            "placed": result.placed,
            "failed": len(result.failed),
            "folder": str(result.folder),
        }

    def open_output(self, body: dict) -> dict:
        """Show the output folder (exports, saved map) in the file manager. Only this one fixed
        folder can be opened."""
        folder = self.out_dir
        folder.mkdir(parents=True, exist_ok=True)
        if hasattr(os, "startfile"):
            os.startfile(folder)  # noqa: S606 - our own output folder, no user input
        else:
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen([opener, str(folder)])  # noqa: S603
        return {"folder": str(folder)}

    def thumb(self, i: int) -> bytes:  # the map's and the lists' small tiles, kept in memory
        if i not in self._thumbs:
            try:
                self._thumbs[i] = cached_thumbnail(self.atlas.paths[i], size=self.thumb_px)
            except LOAD_ERRORS:
                self._thumbs[i] = b""
        return self._thumbs[i]

    def view_thumb(self, i: int) -> bytes:
        """A sharper thumbnail for the group view's large tiles (kept in the disk cache only)."""
        try:
            return cached_thumbnail(self.atlas.paths[i], size=VIEW_PX)
        except LOAD_ERRORS:
            return b""

    def prewarm(self, workers: int = 4) -> None:
        """Read the captions, prepare search and make every thumbnail in the background, so the
        page is ready when it is opened (19,554 images: 5.8 s of caption reads on the first page
        load, about 4 s before the first search)."""
        pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="thumbs")
        pool.submit(self._read_tags)
        pool.submit(warm, self.atlas.style)  # the first search of a large folder is instant too
        for i in range(len(self.atlas)):
            pool.submit(self.thumb, i)
        pool.shutdown(wait=False)

    def regroup(self, body: dict) -> dict:
        method = body.get("method", "agglomerative")
        if method not in (*METHODS, ARTISTS, FOLDERS, TIMELINE):
            raise ValueError(f"method must be one of {(*METHODS, ARTISTS, FOLDERS, TIMELINE)}")
        threshold = body.get("threshold")  # None: chosen from the data
        k = body.get("k")
        is_number = isinstance(threshold, (int, float)) and not isinstance(threshold, bool)
        if threshold is not None and not (is_number and 0.05 <= threshold <= 1.5):
            raise ValueError("threshold must be a number from 0.05 to 1.5, or null for auto")
        if k is not None and (type(k) is not int or not 1 <= k <= len(self.atlas)):
            raise ValueError("k must be a whole number between 1 and the image count")
        atlas = self.atlas  # grouped outside the lock: the timeline's tests take a few seconds
        clustering = self._grouped(method, threshold, k, atlas)
        with self._lock:
            if self.atlas is not atlas:
                raise ValueError(
                    tr("the space changed meanwhile; try again", "向量空間剛剛換過，請再試一次")
                )
            self._remember()
            self._swap(clustering)
            if method == FOLDERS:  # each group is named after its folder (an artist, a style)
                folders = labels_from_folders(atlas.paths, atlas.root)
                self.group_names = {
                    c.id: clean_group_name(folders[c.members[0]]) for c in clustering.clusters
                }
            self.settings = {"method": method, "threshold": threshold, "k": k}
            self.revision += 1
            self._save_groups()
        done = {"clusters": clustering.n_clusters, "unassigned": clustering.n_unassigned}
        if method == TIMELINE:  # the tests' verdict, shown by the page (timeline.verdict)
            keys = ("distinct", "p_time", "p_turns", "separation", "tied")
            done |= {key: clustering.params.get(key) for key in keys}
            done["verdict"] = verdict(clustering.params)
            done["edge"] = on_edge(clustering.params)  # which way it could tip, or None
        return done

    def search_image(self, data: bytes, top: int = SEARCH_TOP) -> dict:
        query, raw = self._embed([data])
        copies = self.copies(*raw)
        found = _besides(search(query, self.atlas.style, top=2 * top)[0], copies)
        hits, folded = fold_hits(found, self.raw.style, self.raw.content, top)
        return {
            "hits": [{"i": h.index, "cos": round(h.cosine, 4)} for h in hits],
            "folded": folded,
            "folders": self.closest_folders(query),
            "copies": copies,
        }

    def copies(self, style: np.ndarray, content: np.ndarray) -> list[dict]:
        """Dropped images that are near-duplicates of one in the folder (the same picture, a
        crop or a recolour; duplicates.py): a LoRA render that repeats a training image, or a
        found image the folder already has. Plain CSD, where that threshold was set."""
        with self._lock:
            skip = set(self.excluded)  # not trained on, so not a copy the LoRA could have learned
        found = copies_of(style, content, self.raw.style, self.raw.content)
        return [{"q": k, "i": i, "score": round(s, 3)} for k, i, s in found if i not in skip]

    def closest_folders(self, query: np.ndarray, combine: bool = False) -> list[dict]:
        """The opened folder's sub-folders ranked by style, as `search --by-folder` (the first
        query's, or all queries' as one style); empty unless there are two or more."""
        if len(set(self.folders) - {""}) < 2:
            return []
        with self._lock:
            skip = set(self.excluded)  # a stray the user excluded must not pull its folder's mean
        hits = rank_folders(query, self.atlas.style, self.folders, FOLDER_TOP, combine, skip)[0]
        verdict = folder_verdict(hits, several=combine and len(query) > 1)
        return [
            {"folder": h.folder, "score": round(h.score, 3), "size": h.size, "best": h.best}
            | (
                {"verdict": verdict[0], "right": verdict[1], "lead": round(verdict[2], 3)}
                if k == 0 and verdict
                else {}
            )
            for k, h in enumerate(hits)
        ]

    def fit(self, style: np.ndarray) -> list[dict]:
        """Where each new image (plain CSD `style`) would go, by the rule `sort` uses
        (cluster.fit_to_groups); excluded images do not count as members."""
        with self._lock:
            raw, clustering, skip = self.raw.style, self.clustering, set(self.excluded)
        fits = fit_to_groups(raw, clustering, style, skip)
        return [{"group": f.group, "dist": round(f.dist, 3), "fits": f.fits} for f in fits]

    def search_set(self, body: dict) -> dict:
        """Several dropped images searched as one style (as `search --combine`); with "only"
        (image indices, e.g. those with a caption tag) the other images are left out."""
        images = body.get("images")
        if (
            not isinstance(images, list)
            or not 1 <= len(images) <= MAX_QUERY_IMAGES
            or not all(isinstance(s, str) for s in images)
        ):
            raise ValueError(f"images must be a list of 1 to {MAX_QUERY_IMAGES} base64 strings")
        query, raw = self._embed([base64.b64decode(s, validate=True) for s in images])
        copies = self.copies(*raw)
        only = body.get("only")
        if only is None:
            found = search(query, self.atlas.style, top=2 * SEARCH_TOP, combine=True)[0]
        else:  # rank against the whole library (the learned model's negatives), then keep the tag
            allowed = set(self._indices({"items": only}))
            ranked = search(query, self.atlas.style, top=len(self.atlas), combine=True)[0]
            found = [h for h in ranked if h.index in allowed][: 2 * SEARCH_TOP]
        hits, folded = fold_hits(
            _besides(found, copies), self.raw.style, self.raw.content, SEARCH_TOP
        )
        return {
            "hits": [{"i": h.index, "cos": round(h.cosine, 4)} for h in hits],
            "folded": folded,
            "fit": self.fit(raw[0]),
            "folders": self.closest_folders(query, combine=True),
            "copies": copies,
        }

    def _embed(self, datas: list[bytes]) -> tuple[np.ndarray, tuple[np.ndarray, np.ndarray]]:
        """Style vectors of uploaded images, decoded one at a time (each can be large), in the
        current space (the content vectors place them with a character), and the plain
        (style, content) vectors."""
        styles, contents = [], []
        for d in datas:
            try:
                image = load_rgb(io.BytesIO(d))
            except LOAD_ERRORS as e:
                raise ValueError(tr(f"not a readable image: {e}", f"讀不了這張圖：{e}")) from e
            with self._model_lock:
                emb = get_encoder(self.opts).encode([image])
            styles.append(emb.style[0])
            contents.append(emb.content[0])
            del image
        style, content = np.stack(styles), np.stack(contents)
        with self._lock:
            return self.space.apply(style, content), (style, content)

    def similar(self, body: dict) -> dict:
        """Images outside a group that look most like it (a model learned from the group, as in
        `search --combine`): strays that belong in it, or more of the same style. With
        {"excluded": true} the images excluded by hand are the examples: from three strays by
        another artist, the top 30 held 98% of the rest of them (docs/BENCHMARKS.md). With
        {"items": [...]} the examples are those images (one: "find similar" on a picture)."""
        with self._lock:
            if body.get("items") is not None:
                members = self._indices(body)
                if len(members) > MAX_QUERY_IMAGES:
                    raise ValueError(f"at most {MAX_QUERY_IMAGES} example images")
            elif body.get("excluded") is True:
                members = sorted(self.excluded)
                if not members:
                    raise ValueError(tr("no image is excluded yet", "還沒有排除任何圖"))
            else:
                group = self._group(body.get("group"), allow_unassigned=False)
                members = list(self.clustering.clusters[group].members)
            labels = self.clustering.labels.copy()
            x = self.atlas.style
        hits = search(x[members], x, top=SEARCH_TOP, combine=True, exclude=set(members))[0]
        return {
            "hits": [
                {"i": h.index, "group": int(labels[h.index]), "cos": round(h.cosine, 4)}
                for h in hits
            ]
        }

    def artists(self, body: dict) -> dict:
        """The sub-folders (artists, in a library) for the artists tab: name, image count, the
        most typical image (as a page index) and the NEAR_ARTISTS folders closest in mean style."""
        with self._lock:  # images excluded by hand do not pull their folder's average
            kept = [i for i in range(len(self.raw)) if i not in self.excluded]
            raw = self.raw.subset(kept)
            index = {p: i for i, p in enumerate(self.atlas.paths)}
        folders = labels_from_folders(raw.paths, raw.root)
        sizes = Counter(f for f in folders if f)
        means = folder_atlas(raw)  # plain CSD; one row per folder, in sorted name order
        names = sorted(sizes)
        if len(names) < MIN_FOLDERS:
            return {"artists": []}
        sims = means.style @ means.style.T
        np.fill_diagonal(sims, -np.inf)
        near = np.argsort(-sims, axis=1)[:, : min(NEAR_ARTISTS, len(names) - 1)]  # never itself
        return {
            "artists": [
                {
                    "name": name,
                    "size": sizes[name],
                    "rep": index[means.paths[k]],
                    "near": [[int(j), round(float(sims[k, j]), 3)] for j in near[k]],
                }
                for k, name in enumerate(names)
            ]
        }

    def set_reference(self, body: dict) -> dict:
        """A folder of styles you already know becomes the reference: the measures layout gets
        an originality axis (distance to the closest reference image). An empty folder clears it.
        Groups, edits and map positions stay."""
        folder = body.get("folder", "")
        if not isinstance(folder, str) or len(folder) > MAX_PATH_TEXT:
            raise ValueError("folder must be a path")
        folder = folder.strip().strip('"').strip()
        ref = None
        if folder:
            path = local_folder(folder)
            with self._model_lock:  # the first time this embeds every image: not under _lock
                ref = build_atlas(path, self.opts, self.progress)
        with self._lock:
            self.raw_reference = ref
            view = None
            if ref is not None:
                view = replace(ref, style=self.space.apply(ref.style, ref.content))
            self.layout = with_reference(self.layout, self.atlas, view)
            self._spaces = {self.space.name: (self.space, self.layout)}  # others: old reference
            self.revision += 1
        return {"reference": self.layout.ref_title, "images": 0 if ref is None else len(ref)}

    def check(self, body: dict) -> dict:
        """The dataset audit (`style-atlas audit`) for the images on the map, by index: small,
        extreme, enlarged, heavily compressed, animated or truncated images, missing or empty
        captions, and greyscale images in a colour set."""
        side = body.get("min_side", 512)
        if type(side) is not int or not MIN_SIDE_RANGE[0] <= side <= MIN_SIDE_RANGE[1]:
            raise ValueError(
                f"min_side must be a whole number from {MIN_SIDE_RANGE[0]} to {MIN_SIDE_RANGE[1]}"
            )
        with self._lock:
            paths, looks = list(self.raw.paths), self.raw.looks
            kept = [i for i in range(len(paths)) if i not in self.excluded]
            style = self.raw.style[kept]  # plain CSD, as the reference was measured
        report = audit(paths, min_side=side, looks=looks)  # decodes every image: outside the lock
        tight = consistency(style)  # of the images not excluded, so a re-check shows the effect
        index = {str(p): i for i, p in enumerate(paths)}
        issues = {
            key: [index[f] for f in files if f in index] for key, files in report["files"].items()
        }
        return {
            "min_side": side,
            "low_jpeg": LOW_JPEG,
            "issues": issues,
            "spelt_two_ways": report["tags_spelt_two_ways"],
            "frequent_tags": report["frequent_tags"],
            "buckets": report["summary"]["buckets"],
            "consistency": None
            if tight is None
            else {
                "spread": tight.spread,
                "percentile": tight.percentile,
                "verdict": tight.verdict,
                "folders": len(set(self.folders) - {""}),  # sub-folders: often one per artist
            },
        }

    def _compare_sides(self, body: dict) -> tuple[list[int], list[int]]:
        """Members of side a and side b: two groups, a selection and a group (the selection
        against the rest of it), or two selections (b without what a already holds)."""
        if "items" in body:
            ma = self._indices({"items": body.get("items")})
            if "items_b" in body:
                mb = self._indices({"items": body.get("items_b")})
            else:
                b = self._group(body.get("b"), allow_unassigned=False)
                mb = list(self.clustering.clusters[b].members)
            held = set(ma)
            mb = [m for m in mb if m not in held]
        else:
            a = self._group(body.get("a"), allow_unassigned=False)
            b = self._group(body.get("b"), allow_unassigned=False)
            if a == b:
                raise ValueError(tr("pick two different groups", "請選兩個不同的群"))
            ma = list(self.clustering.clusters[a].members)
            mb = list(self.clustering.clusters[b].members)
        if len(ma) < 2 or len(mb) < 2:
            raise ValueError(
                tr(
                    "each side needs at least 2 images that the other does not have",
                    "兩邊都至少要有 2 張對方沒有的圖",
                )
            )
        return ma, mb

    def compare(self, body: dict) -> dict:
        """Two groups side by side, as `style-atlas compare`: centroid distance, its z and verdict
        on the default scale, a permutation p-value, and how group b looks next to group a.
        "items" (images picked on the map) can stand in for group a, and "items_b" for b."""
        with self._lock:
            ma, mb = self._compare_sides(body)
            # plain CSD whatever space the map is in: the z scale and ARTIST_SCALE were made there
            x, looks = self.raw.style, self.atlas.looks
            folders = labels_from_folders(self.atlas.paths, self.atlas.root)
        dist, p = group_difference(x[ma], x[mb], rounds=COMPARE_ROUNDS)
        scale = StyleScale()
        out = {
            "distance": round(dist, 4),
            "z": round(scale.z(dist), 2),
            "verdict": scale.verdict(dist),
            "p": round(p, 4),
            "sizes": [len(ma), len(mb)],
            # each side's images, the ones that best show the difference first
            "order_a": [ma[k] for k in distinctive_order(x[ma], x[mb])],
            "order_b": [mb[k] for k in distinctive_order(x[mb], x[ma])],
        }
        if looks is not None:
            d = difference(looks[ma], looks[mb])
            out["look"] = dict(zip(LOOK_NAMES, (round(float(v), 2) for v in d), strict=True))
        if mixes_artists(folders, ma) or mixes_artists(folders, mb):
            out["mixed"] = True
            return out
        reading = artist_reading(dist, len(ma), len(mb))
        if reading is not None:
            out["reading"] = {
                "position": reading.position,
                "n": reading.n,
                "p5": round(reading.others_p5, 3),
                "median": round(reading.others_median, 3),
                "change": round(reading.one_artist_change, 3),
            }
        return out

    def path(self, body: dict) -> dict:
        a = self._index({"i": body.get("a")})
        b = self._index({"i": body.get("b")})
        steps = body.get("steps", 8)
        if type(steps) is not int or not 1 <= steps <= 40:
            raise ValueError("steps must be a whole number from 1 to 40")
        with self._lock:
            skip = set(self.excluded)
        return {"path": style_path(self.atlas.style, a, b, steps, skip=skip)}

    def next_to_rate(self, body: dict) -> dict:
        with self._lock:
            return {"i": self.taste.next_to_rate(skip=set(self.excluded))}

    def vote(self, body: dict) -> dict:
        i = self._index(body)
        like = body.get("like")
        if like is not None and not isinstance(like, bool):
            raise ValueError("like must be true, false or null")
        with self._lock:
            return self.taste.vote(i, like)

    def _export_options(self, body: dict) -> tuple[str, bool, str, str, int | None, str]:
        """(layout, trigger, name, strip_tags, max_per_group, repeats) from the page, checked."""
        layout = body.get("layout", "plain")
        trigger = body.get("trigger", False)
        if layout not in LAYOUTS or not isinstance(trigger, bool):
            raise ValueError(f"layout must be one of {LAYOUTS}; trigger must be true or false")
        name = clean_group_name(body.get("name") or self.atlas.root.name or "style")
        strip = body.get("strip_tags") or ""
        if not isinstance(strip, str) or len(strip) > MAX_TAG_TEXT * 10:
            raise ValueError("strip_tags must be a comma-separated list of tags")
        cap = body.get("max_per_group")
        low, high = MAX_PER_GROUP_RANGE
        if cap is not None and (type(cap) is not int or not low <= cap <= high):
            raise ValueError(f"max_per_group must be empty or a whole number from {low} to {high}")
        repeats = body.get("repeats")
        if repeats is not None and (type(repeats) is not int or not 1 <= repeats <= MAX_REPEATS):
            raise ValueError(f"repeats must be empty (automatic) or a whole number 1-{MAX_REPEATS}")
        return layout, trigger, name, strip, cap, "auto" if repeats is None else str(repeats)

    def _plan(self, layout: str, name: str, cap: int | None, repeats: str = "auto") -> list[str]:
        """Each image's export folder, as the export would place it (call under the lock)."""
        return plan_folders(
            self.atlas.paths,
            self.clustering,
            layout=layout,
            name=name,
            repeats=repeats,
            duplicate_groups=self.layout.duplicates,
            excluded=sorted(self.excluded),
            group_names=self.names_by_group(),
            min_size=EXPORT_MIN_GROUP,
            max_per_group=cap,
            style=self.atlas.style,
            prefer=self.kept_copies,
        )

    def _plan_summary(self, folders: list[str], layout: str, trigger: bool) -> dict:
        """What an export of `folders` gives: groups too small to keep, how many images train,
        the trigger words and the steps per epoch."""
        labels = self.clustering.labels
        small = {
            int(labels[i]) for i, f in enumerate(folders) if labels[i] >= 0 and is_unassigned(f)
        }
        return {
            "small_groups": len(small),  # left with < EXPORT_MIN_GROUP images: in unassigned
            "small_ids": sorted(small),
            # the rest go to the set-aside folders (_duplicates, _excluded, unassigned ...)
            "training": sum(not (f.startswith("_") or is_unassigned(f)) for f in folders),
            "triggers": sorted(
                {t for f in folders if trigger and (t := trigger_of(f, layout)) is not None}
            ),
            "trimmed": sum(f == SET_ASIDE["trimmed"] for f in folders),
            "steps": steps_per_epoch(folders) if layout == "kohya" else None,
        }

    def export_plan(self, body: dict) -> dict:
        """The export's plan without writing anything: one row per folder (images, and the
        repeats of a kohya folder), and the same summary as an export."""
        layout, trigger, name, _, cap, repeats = self._export_options(body)
        with self._lock:
            folders = self._plan(layout, name, cap, repeats)
        rows = []
        for folder, n in sorted(Counter(folders).items()):
            head, _, rest = folder.partition("_")
            kohya = layout == "kohya" and head.isdigit() and bool(rest)
            training = not (folder.startswith("_") or is_unassigned(folder))
            rows.append(
                {
                    "folder": folder,
                    "images": n,
                    "repeats": int(head) if kohya else None,
                    "training": training,
                }
            )
        return {"rows": rows, **self._plan_summary(folders, layout, trigger)}

    def export(self, body: dict) -> dict:
        mode = body.get("mode", "copy")
        layout, trigger, name, strip, cap, repeats = self._export_options(body)
        fix = body.get("fix_spelling", False)
        if not isinstance(fix, bool):
            raise ValueError("fix_spelling must be true or false")
        out = self.out_dir
        respell = spelling_fixes(self.atlas.paths) if fix else None  # reads captions: no lock
        with self._lock:
            folders = self._plan(layout, name, cap, repeats)
            write_table(self.atlas, self.clustering, out, folders)
            result = export_folders(
                self.atlas,
                folders,
                out / "folders",
                mode=mode,
                trigger_captions=trigger,
                layout=layout,
                strip_tags=parse_tags(strip),
                respell=respell,
            )
            summary = self._plan_summary(folders, layout, trigger)
        return {
            "placed": result.placed,
            "failed": len(result.failed),
            "folder": str(result.folder),
            "upright": result.upright,
            "respelt": sorted(respell.values()) if respell else [],
            "small_training": result.small_training,
            "config": (result.folder / KOHYA_CONFIG).exists(),
            **summary,
        }


def _tags_or_none(path: Path) -> set[str]:
    """Caption tags, or none when the caption cannot be read (a broken caption must not take
    the whole page down)."""
    try:
        return set(read_tags(path))
    except OSError:
        return set()
