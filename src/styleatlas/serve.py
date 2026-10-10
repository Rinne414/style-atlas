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

from styleatlas.atlas import LOAD_ERRORS, Atlas, EncodeOptions, get_encoder
from styleatlas.cluster import (
    GRANULARITY,
    METHODS,
    PERIODS,
    UNASSIGNED,
    cluster_styles,
    edit_groups,
    split_group,
)
from styleatlas.dataset import (
    LAYOUTS,
    clean_group_name,
    distinctive_tags,
    is_unassigned,
    plan_folders,
    read_tags,
    tag_summary,
)
from styleatlas.export import KOHYA_CONFIG, export_folders, output_dir, write_table
from styleatlas.groupfile import GROUPS_FILE, SavedGroups, carry_names, load_groups, save_groups
from styleatlas.images import cached_thumbnail, load_rgb
from styleatlas.look import LOOK_NAMES, difference
from styleatlas.metrics import (
    CHARACTERS,
    MAX_NEUTRALIZE,
    PLAIN,
    StyleScale,
    StyleSpace,
    group_difference,
    space_name,
)
from styleatlas.persist import RelPathMap
from styleatlas.report import (
    build_payload,
    compute_layout,
    default_thumb_px,
    map_payload,
    render_html,
    write_payload,
)
from styleatlas.search import search, style_path
from styleatlas.taste_session import TasteSession

SEARCH_TOP = 48
MAX_QUERY_IMAGES = 32
UNDO_STEPS = 30
EXPORT_MIN_GROUP = 3  # groups left smaller after set-asides go to _unassigned (as in the CLI)
MAX_SPLIT = 4000  # splitting runs under the lock; larger groups would stall every request
COMPARE_ROUNDS = 199  # permutations for a group comparison's p-value (resolution 0.005)


class StyleAtlasApp:
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
        self._lock = threading.Lock()
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

    def _group_tags(self) -> dict[int, list[str]]:
        """Each group's characteristic caption tags (captions are read once per session)."""
        if self._tag_sets is None:
            self._tag_sets = [_tags_or_none(p) for p in self.atlas.paths]
        summary = tag_summary(self.atlas.paths, self.clustering, tags=self._tag_sets)
        return distinctive_tags(summary)

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
        """Read the captions and make every thumbnail in the background, so the page is ready
        when it is opened (19,554 images: 5.8 s of caption reads on the first page load)."""
        pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="thumbs")
        pool.submit(self._read_tags)
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

    def search_image(self, data: bytes, top: int = SEARCH_TOP) -> list[dict]:
        hits = search(self._embed([data]), self.atlas.style, top=top)[0]
        return [{"i": h.index, "cos": round(h.cosine, 4)} for h in hits]

    def search_set(self, body: dict) -> dict:
        """Several dropped images searched as one style (as `search --combine`)."""
        images = body.get("images")
        if (
            not isinstance(images, list)
            or not 1 <= len(images) <= MAX_QUERY_IMAGES
            or not all(isinstance(s, str) for s in images)
        ):
            raise ValueError(f"images must be a list of 1 to {MAX_QUERY_IMAGES} base64 strings")
        query = self._embed([base64.b64decode(s, validate=True) for s in images])
        hits = search(query, self.atlas.style, top=SEARCH_TOP, combine=True)[0]
        return {"hits": [{"i": h.index, "cos": round(h.cosine, 4)} for h in hits]}

    def _embed(self, datas: list[bytes]):
        """Style vectors of uploaded images, decoded one at a time (each can be large), in the
        current space (the content vectors place them with a character)."""
        styles, contents = [], []
        for d in datas:
            try:
                image = load_rgb(io.BytesIO(d))
            except LOAD_ERRORS as e:
                raise ValueError(f"not a readable image: {e}") from e
            with self._lock:
                emb = get_encoder(self.opts).encode([image])
            styles.append(emb.style[0])
            contents.append(emb.content[0])
            del image
        with self._lock:
            return self.space.apply(np.stack(styles), np.stack(contents))

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

    def compare(self, body: dict) -> dict:
        """Two groups side by side, as `style-atlas compare`: centroid distance, its z and verdict
        on the default scale, a permutation p-value, and how group b looks next to group a."""
        with self._lock:
            a = self._group(body.get("a"), allow_unassigned=False)
            b = self._group(body.get("b"), allow_unassigned=False)
            if a == b:
                raise ValueError("pick two different groups")
            ma = list(self.clustering.clusters[a].members)
            mb = list(self.clustering.clusters[b].members)
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

    def _group(self, value: object, allow_unassigned: bool) -> int:
        if type(value) is not int:
            raise ValueError("group must be a whole number")
        if value == UNASSIGNED and allow_unassigned:
            return value
        if not 0 <= value < self.clustering.n_clusters:
            raise ValueError("no such group")
        return value

    def _check_revision(self, body: dict) -> None:
        """Group ids change after every edit; refuse an edit made on an outdated page."""
        if body.get("rev") != self.revision:
            raise ValueError("the groups changed in another tab or edit; reload the page")

    def _remember(self) -> None:
        state = (self.clustering, dict(self.settings), dict(self.group_names), self.space.name)
        self._history.append(state)
        del self._history[:-UNDO_STEPS]

    def _swap(self, clustering, prefer: int | None = None) -> None:
        """Make `clustering` current; names move to the groups that hold most of their images."""
        old = self.clustering.labels
        self.group_names = carry_names(old, clustering.labels, self.group_names, prefer)
        self.clustering = clustering

    def undo(self, body: dict) -> dict:
        with self._lock:
            self._check_revision(body)
            if not self._history:
                raise ValueError("nothing to undo")
            clustering, settings, names, space = self._history.pop()
            if space != self.space.name:
                self._apply_space(space)
            self.clustering, self.settings, self.group_names = clustering, settings, names
            self.revision += 1
            self._save_groups()
            return {"clusters": self.clustering.n_clusters, "revision": self.revision}

    def _edited(self, clustering, prefer: int | None = None) -> dict:
        self._remember()
        self._swap(clustering, prefer)
        self.settings = {**self.settings, "edited": True}
        self.revision += 1
        self._save_groups()
        return {"clusters": self.clustering.n_clusters, "revision": self.revision}

    @property
    def _groups_path(self) -> Path:
        return self.out_dir / GROUPS_FILE

    def _save_groups(self) -> None:
        """Groups, hand edits and names, by relative path, so a restart keeps the work."""
        try:
            save_groups(
                self._groups_path,
                self.atlas,
                self.clustering,
                self.settings,
                self.space.name,
                self.group_names,
            )
        except OSError as e:  # the edit itself worked; only the copy on disk is behind
            self.progress(f"could not save {self._groups_path}: {e}")

    def _restore(self, saved: SavedGroups) -> None:
        """Saved groups (new images start unassigned), with their names."""
        moves = dict(enumerate(saved.labels.tolist()))
        self.clustering = edit_groups(self.atlas.style, self.clustering, moves)
        self.settings = {**self.settings, **saved.settings, "edited": True}
        self.group_names = carry_names(saved.labels, self.clustering.labels, saved.names)

    def move(self, body: dict) -> dict:
        """Hand edit: put one image into another group (or unassigned)."""
        i = self._index(body)
        with self._lock:
            self._check_revision(body)
            target = self._group(body.get("to"), allow_unassigned=True)
            return self._edited(edit_groups(self.atlas.style, self.clustering, {i: target}))

    def merge(self, body: dict) -> dict:
        """Hand edit: merge one group into another."""
        with self._lock:
            self._check_revision(body)
            source = self._group(body.get("from"), allow_unassigned=False)
            target = self._group(body.get("into"), allow_unassigned=False)
            if source == target:
                raise ValueError("pick two different groups")
            members = self.clustering.clusters[source].members
            moves = {m: target for m in members}
            return self._edited(edit_groups(self.atlas.style, self.clustering, moves), target)

    def rename(self, body: dict) -> dict:
        """Name a group for export (an empty name removes it). Names follow their images
        through later edits and regroupings."""
        name = body.get("name", "")
        if not isinstance(name, str) or len(name) > 120:
            raise ValueError("name must be text (at most 120 characters)")
        new = clean_group_name(name) if name.strip() else None
        with self._lock:
            self._check_revision(body)
            group = self._group(body.get("group"), allow_unassigned=False)
            others = {n.casefold() for g, n in self.group_names.items() if g != group}
            if new is not None and new.casefold() in others:
                raise ValueError(f"another group is already called {new}")
            if new == self.group_names.get(group):
                return {"names": self.names_by_group()}
            self._remember()
            names = {g: n for g, n in self.group_names.items() if g != group}
            self.group_names = names if new is None else {**names, group: new}
            self._save_groups()
            return {"names": self.names_by_group()}

    def names_by_group(self) -> dict[int, str]:
        return dict(self.group_names)

    def split(self, body: dict) -> dict:
        """Hand edit: cut one group in two."""
        with self._lock:
            self._check_revision(body)
            group = self._group(body.get("group"), allow_unassigned=False)
            if self.clustering.clusters[group].size > MAX_SPLIT:
                raise ValueError("group too large to split here; regroup into smaller groups")
            return self._edited(split_group(self.atlas.style, self.clustering, group))

    def _index(self, body: dict) -> int:
        i = body.get("i")
        if type(i) is not int or not 0 <= i < len(self.atlas):
            raise ValueError("i must be an image index")
        return i

    def exclude(self, body: dict) -> dict:
        i = self._index(body)
        excluded = body.get("excluded", True)
        if not isinstance(excluded, bool):
            raise ValueError("excluded must be true or false")
        with self._lock:
            if excluded:
                self.excluded.add(i)
            else:
                self.excluded.discard(i)
            self._excluded.values = {j: True for j in self.excluded}
            self._excluded.save()
            return {"excluded": sorted(self.excluded)}

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
            )
            write_table(self.atlas, self.clustering, out, folders)
            result = export_folders(
                self.atlas,
                folders,
                out / "folders",
                mode=mode,
                trigger_captions=trigger,
                layout=layout,
            )
            labels = self.clustering.labels
            small = {
                int(labels[i]) for i, f in enumerate(folders) if labels[i] >= 0 and is_unassigned(f)
            }
        return {
            "placed": result.placed,
            "failed": len(result.failed),
            "folder": str(result.folder),
            "small_groups": len(small),  # left with < EXPORT_MIN_GROUP images: in unassigned
            "config": (result.folder / KOHYA_CONFIG).exists(),
        }


def _tags_or_none(path: Path) -> set[str]:
    """Caption tags, or none when the caption cannot be read (a broken caption must not take
    the whole page down)."""
    try:
        return set(read_tags(path))
    except OSError:
        return set()
