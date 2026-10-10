"""Hand edits on the groups for the web app: move, merge, rename, split, exclude and undo, each
checked against the page's revision and saved next to the folder so a restart keeps the work."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np

from styleatlas.atlas import Atlas
from styleatlas.cluster import (
    ARTISTS,
    UNASSIGNED,
    Clustering,
    edit_groups,
    fit_to_groups,
    split_group,
)
from styleatlas.dataset import clean_group_name
from styleatlas.groupfile import GROUPS_FILE, SavedGroups, carry_names, save_groups
from styleatlas.metrics import StyleSpace
from styleatlas.persist import RelPathMap

UNDO_STEPS = 30
MAX_SPLIT = 4000  # splitting runs under the lock; larger groups would stall every request
MAX_NAME = 120


class GroupEdits:
    """Mixed into StyleAtlasApp, which sets these attributes."""

    atlas: Atlas
    raw: Atlas
    clustering: Clustering
    settings: dict
    group_names: dict[int, str]
    revision: int
    space: StyleSpace
    excluded: set[int]
    _excluded: RelPathMap
    _history: list[tuple]
    _lock: threading.Lock
    progress: Callable[[str], None]
    out_dir: Path

    def _apply_space(self, name: str) -> None:
        raise NotImplementedError

    def _group(self, value: object, allow_unassigned: bool) -> int:
        if type(value) is not int:
            raise ValueError("group must be a whole number")
        if value == UNASSIGNED and allow_unassigned:
            return value
        if not 0 <= value < self.clustering.n_clusters:
            raise ValueError("no such group")
        return value

    @property
    def _edit_vectors(self):
        """The vectors hand edits recompute medoids and spreads in: those the groups were made
        in (plain CSD for the by-artist grouping, else the current space)."""
        return self.raw.style if self.clustering.method == ARTISTS else self.atlas.style

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
        self.clustering = edit_groups(self._edit_vectors, self.clustering, moves)
        self.settings = {**self.settings, **saved.settings, "edited": True}
        self.group_names = carry_names(saved.labels, self.clustering.labels, saved.names)

    def move(self, body: dict) -> dict:
        """Hand edit: put one image ("i") or several ("items") into another group (or
        unassigned), as one undo step."""
        items = self._indices(body)
        with self._lock:
            self._check_revision(body)
            target = self._group(body.get("to"), allow_unassigned=True)
            moves = dict.fromkeys(items, target)
            return self._edited(edit_groups(self._edit_vectors, self.clustering, moves))

    def place_unassigned(self, body: dict) -> dict:
        """Hand edit, as one undo step: each unassigned image (not excluded) that fits its
        closest group moves there, by the rule `style-atlas sort` uses (cluster.fit_to_groups on
        whitened CSD); the others stay unassigned."""
        with self._lock:
            self._check_revision(body)
            rows = [
                int(i)
                for i in np.flatnonzero(self.clustering.labels == UNASSIGNED)
                if i not in self.excluded
            ]
            if not rows:
                raise ValueError("no unassigned images")
            raw = self.raw.style
            fits = fit_to_groups(raw, self.clustering, raw[rows], set(self.excluded))
            moves = {i: f.group for i, f in zip(rows, fits, strict=False) if f.fits}
            if not moves:
                return {"moved": 0, "left": len(rows), "revision": self.revision}
            done = self._edited(edit_groups(self._edit_vectors, self.clustering, moves))
            return {**done, "moved": len(moves), "left": len(rows) - len(moves)}

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
            return self._edited(edit_groups(self._edit_vectors, self.clustering, moves), target)

    def rename(self, body: dict) -> dict:
        """Name a group for export (an empty name removes it). Names follow their images
        through later edits and regroupings."""
        name = body.get("name", "")
        if not isinstance(name, str) or len(name) > MAX_NAME:
            raise ValueError(f"name must be text (at most {MAX_NAME} characters)")
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
            return self._edited(split_group(self._edit_vectors, self.clustering, group))

    def _indices(self, body: dict) -> list[int]:
        """The images an edit applies to: "items" (a list of indices) or the single "i"."""
        items = body.get("items")
        if items is None:
            return [self._index(body)]
        n = len(self.atlas)
        if (
            not isinstance(items, list)
            or not 1 <= len(items) <= n
            or not all(type(i) is int and 0 <= i < n for i in items)
        ):
            raise ValueError("items must be a list of image indices")
        return sorted(set(items))

    def _index(self, body: dict) -> int:
        i = body.get("i")
        if type(i) is not int or not 0 <= i < len(self.atlas):
            raise ValueError("i must be an image index")
        return i

    def exclude(self, body: dict) -> dict:
        items = self._indices(body)
        excluded = body.get("excluded", True)
        if not isinstance(excluded, bool):
            raise ValueError("excluded must be true or false")
        with self._lock:
            if excluded:
                self.excluded.update(items)
            else:
                self.excluded.difference_update(items)
            self._excluded.values = {j: True for j in self.excluded}
            self._excluded.save()
            return {"excluded": sorted(self.excluded)}
