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
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np

from styleatlas.atlas import LOAD_ERRORS, Atlas, EncodeOptions, build_atlas, get_encoder
from styleatlas.cluster import (
    GRANULARITY,
    METHODS,
    PERIODS,
    cluster_styles,
)
from styleatlas.consistency import consistency
from styleatlas.dataset import (
    LAYOUTS,
    MAX_PER_GROUP_RANGE,
    SET_ASIDE,
    audit,
    clean_group_name,
    distinctive_tags,
    is_unassigned,
    norm_tag,
    plan_folders,
    read_tags,
    tag_summary,
)
from styleatlas.duplicates import copies_of
from styleatlas.export import (
    KOHYA_CONFIG,
    export_folders,
    output_dir,
    parse_tags,
    steps_per_epoch,
    write_table,
)
from styleatlas.groupfile import carry_names, load_groups
from styleatlas.images import cached_thumbnail, labels_from_folders, load_rgb
from styleatlas.look import LOOK_NAMES, difference
from styleatlas.metrics import (
    CHARACTERS,
    MAX_NEUTRALIZE,
    PLAIN,
    StyleScale,
    StyleSpace,
    centroid,
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
from styleatlas.search import fold_hits, rank_folders, search, style_path, warm
from styleatlas.serve_edits import GroupEdits
from styleatlas.taste_session import TasteSession

SEARCH_TOP = 48
FOLDER_TOP = 5  # closest sub-folders listed with a search
MAX_QUERY_IMAGES = 32
EXPORT_MIN_GROUP = 3  # groups left smaller after set-asides go to _unassigned (as in the CLI)
COMPARE_ROUNDS = 199  # permutations for a group comparison's p-value (resolution 0.005)
FIT_PERCENTILE = 90  # a new image fits a group when it is as close as this share of its members
MIN_SIDE_RANGE = (64, 8192)  # the check tab's smallest-side setting
MAX_PATH_TEXT = 1000  # longest folder path accepted from the page
MAX_TAG_TEXT = 200


DRIVE_REMOTE = 4  # GetDriveTypeW: a mapped network drive


def local_folder(text: str) -> Path:
    """A folder typed into the page, on a local disk. Network paths are refused: on Windows,
    merely opening \\\\host\\share sends the user's credentials to that host. Give those with
    --reference when starting instead."""
    path = Path(text).expanduser()
    if str(path).startswith(("\\\\", "//")):
        raise ValueError("network folders are not accepted here; start with --reference instead")
    if os.name == "nt" and path.drive:
        import ctypes

        if ctypes.windll.kernel32.GetDriveTypeW(path.drive + "\\") == DRIVE_REMOTE:
            raise ValueError("network drives are not accepted here; start with --reference instead")
    if not path.is_dir():
        raise ValueError(f"not a folder: {text}")
    return path


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
        self._apply_space(space)
        self.restored = saved is not None
        if saved:
            self._restore(saved)
        self.taste = TasteSession(self.atlas, self.out_dir)
        self._excluded = RelPathMap(self.out_dir / "excluded.json", atlas)
        self.excluded: set[int] = {i for i, v in self._excluded.values.items() if v is True}

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
        self.clustering = cluster_styles(
            self.atlas.style,
            method=s.get("method", "agglomerative"),
            threshold=s.get("threshold"),
            n_clusters=s.get("k"),
        )
        self.settings = {key: v for key, v in s.items() if key != "edited"}
        if self.taste is not None:
            self.taste.atlas = self.atlas
            self.taste._refit()

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
            }
        return render_html(payload)

    def _read_tags(self) -> None:
        tags = [_tags_or_none(p) for p in self.atlas.paths]
        with self._lock:
            if self._tag_sets is None:
                self._tag_sets = tags

    def tagged(self, body: dict) -> dict:
        """Images whose caption has a tag containing the text (case, spaces and underscores
        ignored): "#mono" finds monochrome and greyscale-monochrome alike."""
        text = body.get("tag")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TAG_TEXT:
            raise ValueError("tag must be some text")
        want = norm_tag(text)
        if not want:
            raise ValueError("tag must have a letter or a digit")
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
        they are now, next to the exports."""
        from styleatlas.report_card import write_report

        lang = body.get("lang", "zh")
        if lang not in ("zh", "en"):
            raise ValueError("lang must be zh or en")
        with self._lock:
            raw, clustering, names = self.raw, self.clustering, self.names_by_group()
        title = self.title or self.raw.root.name or "style report"
        out = write_report(
            raw, clustering, self.out_dir / "style_report.html", title, names=names, lang=lang
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
        return {"file": str(write_payload(payload, out))}

    def copy_hits(self, body: dict) -> dict:
        """Copy images ("items", e.g. search results) with their captions into a new
        `search_matches` folder in the output folder, as `search --copy-to` does."""
        with self._lock:
            items = [i for i in self._indices(body) if i not in self.excluded]
            subset = self.raw.subset(items)
        if not items:
            raise ValueError("all of these images are excluded")
        result = export_folders(subset, ["matches"] * len(items), self.out_dir / "search_matches")
        return {
            "placed": result.placed,
            "failed": len(result.failed),
            "folder": str(result.folder / "matches"),
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

    def thumb(self, i: int) -> bytes:
        if i not in self._thumbs:
            try:
                self._thumbs[i] = cached_thumbnail(self.atlas.paths[i], size=self.thumb_px)
            except LOAD_ERRORS:
                self._thumbs[i] = b""
        return self._thumbs[i]

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
        if method not in METHODS:
            raise ValueError(f"method must be one of {METHODS}")
        threshold = body.get("threshold")  # None: chosen from the data
        k = body.get("k")
        is_number = isinstance(threshold, (int, float)) and not isinstance(threshold, bool)
        if threshold is not None and not (is_number and 0.05 <= threshold <= 1.5):
            raise ValueError("threshold must be a number from 0.05 to 1.5, or null for auto")
        if k is not None and (type(k) is not int or not 1 <= k <= len(self.atlas)):
            raise ValueError("k must be a whole number between 1 and the image count")
        with self._lock:
            clustering = cluster_styles(
                self.atlas.style, method=method, threshold=threshold, n_clusters=k
            )
            self._remember()
            self._swap(clustering)
            self.settings = {"method": method, "threshold": threshold, "k": k}
            self.revision += 1
            self._save_groups()
        return {"clusters": self.clustering.n_clusters, "unassigned": self.clustering.n_unassigned}

    def search_image(self, data: bytes, top: int = SEARCH_TOP) -> dict:
        query, raw = self._embed([data])
        found = search(query, self.atlas.style, top=2 * top)[0]
        hits, folded = fold_hits(found, self.raw.style, self.raw.content, top)
        return {
            "hits": [{"i": h.index, "cos": round(h.cosine, 4)} for h in hits],
            "folded": folded,
            "folders": self.closest_folders(query),
            "copies": self.copies(*raw),
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
        return [
            {"folder": h.folder, "score": round(h.score, 3), "size": h.size, "best": h.best}
            for h in hits
        ]

    def fit(self, query: np.ndarray) -> list[dict]:
        """Where each new image would go: its closest group (by centre) and whether it is as close
        as FIT_PERCENTILE% of that group's own images are. One artist's held-out works fitted 69%
        of the time, other artists' 15%: judge a batch by its share, not one image."""
        with self._lock:
            groups = [c for c in self.clustering.clusters if c.size >= 2]
            x = self.atlas.style
        if not groups:
            return []
        cents = np.stack([centroid(x[c.members]) for c in groups])
        limits = [
            float(np.percentile(1.0 - x[c.members] @ cents[k], FIT_PERCENTILE))
            for k, c in enumerate(groups)
        ]
        out = []
        for row in query @ cents.T:
            k = int(np.argmax(row))
            dist = 1.0 - float(row[k])
            out.append({"group": groups[k].id, "dist": round(dist, 3), "fits": dist <= limits[k]})
        return out

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
        only = body.get("only")
        if only is None:
            found = search(query, self.atlas.style, top=2 * SEARCH_TOP, combine=True)[0]
        else:  # rank against the whole library (the learned model's negatives), then keep the tag
            allowed = set(self._indices({"items": only}))
            ranked = search(query, self.atlas.style, top=len(self.atlas), combine=True)[0]
            found = [h for h in ranked if h.index in allowed][: 2 * SEARCH_TOP]
        hits, folded = fold_hits(found, self.raw.style, self.raw.content, SEARCH_TOP)
        return {
            "hits": [{"i": h.index, "cos": round(h.cosine, 4)} for h in hits],
            "folded": folded,
            "fit": self.fit(query),
            "folders": self.closest_folders(query, combine=True),
            "copies": self.copies(*raw),
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
                raise ValueError(f"not a readable image: {e}") from e
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
        another artist, the top 30 held 98% of the rest of them (docs/BENCHMARKS.md)."""
        with self._lock:
            if body.get("excluded") is True:
                members = sorted(self.excluded)
                if not members:
                    raise ValueError("no image is excluded yet")
            else:
                group = self._group(body.get("group"), allow_unassigned=False)
                members = list(self.clustering.clusters[group].members)
            labels = self.clustering.labels.copy()
            x = self.atlas.style
        hits = search(x[members], x, top=SEARCH_TOP, combine=True, exclude=set(members))[0]
        return {"hits": [{"i": h.index, "group": int(labels[h.index])} for h in hits]}

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
            "buckets": report["summary"]["buckets"],
            "consistency": None
            if tight is None
            else {"spread": tight.spread, "percentile": tight.percentile, "verdict": tight.verdict},
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
            mb = [m for m in mb if m not in set(ma)]
        else:
            a = self._group(body.get("a"), allow_unassigned=False)
            b = self._group(body.get("b"), allow_unassigned=False)
            if a == b:
                raise ValueError("pick two different groups")
            ma = list(self.clustering.clusters[a].members)
            mb = list(self.clustering.clusters[b].members)
        if len(ma) < 2 or len(mb) < 2:
            raise ValueError("each side needs at least 2 images that the other does not have")
        return ma, mb

    def compare(self, body: dict) -> dict:
        """Two groups side by side, as `style-atlas compare`: centroid distance, its z and verdict
        on the default scale, a permutation p-value, and how group b looks next to group a.
        "items" (images picked on the map) can stand in for group a, and "items_b" for b."""
        with self._lock:
            ma, mb = self._compare_sides(body)
            x, looks = self.atlas.style, self.atlas.looks
        dist, p = group_difference(x[ma], x[mb], rounds=COMPARE_ROUNDS)
        scale = StyleScale()
        out = {
            "distance": round(dist, 4),
            "z": round(scale.z(dist), 2),
            "verdict": scale.verdict(dist),
            "p": round(p, 4),
            "sizes": [len(ma), len(mb)],
        }
        if looks is not None:
            d = difference(looks[ma], looks[mb])
            out["look"] = dict(zip(LOOK_NAMES, (round(float(v), 2) for v in d), strict=True))
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

    def export(self, body: dict) -> dict:
        mode = body.get("mode", "copy")
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
        out = self.out_dir
        with self._lock:
            folders = plan_folders(
                self.atlas.paths,
                self.clustering,
                layout=layout,
                name=name,
                duplicate_groups=self.layout.duplicates,
                excluded=sorted(self.excluded),
                group_names=self.names_by_group(),
                min_size=EXPORT_MIN_GROUP,
                max_per_group=cap,
                style=self.atlas.style,
            )
            write_table(self.atlas, self.clustering, out, folders)
            result = export_folders(
                self.atlas,
                folders,
                out / "folders",
                mode=mode,
                trigger_captions=trigger,
                layout=layout,
                strip_tags=parse_tags(strip),
            )
            trimmed = sum(f == SET_ASIDE["trimmed"] for f in folders)
            labels = self.clustering.labels
            small = {
                int(labels[i]) for i, f in enumerate(folders) if labels[i] >= 0 and is_unassigned(f)
            }
        return {
            "placed": result.placed,
            "failed": len(result.failed),
            "folder": str(result.folder),
            "small_groups": len(small),  # left with < EXPORT_MIN_GROUP images: in unassigned
            "trimmed": trimmed,
            "config": (result.folder / KOHYA_CONFIG).exists(),
            "steps": steps_per_epoch(folders) if layout == "kohya" else None,
        }


def _tags_or_none(path: Path) -> set[str]:
    """Caption tags, or none when the caption cannot be read (a broken caption must not take
    the whole page down)."""
    try:
        return set(read_tags(path))
    except OSError:
        return set()
