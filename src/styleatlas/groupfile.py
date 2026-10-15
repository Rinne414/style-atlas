"""The web app's saved groups (`groups.json`): the grouping, hand edits and group names, keyed by
relative path, so a restart (or a few images added or removed) keeps the work."""

from __future__ import annotations

import contextlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from styleatlas.atlas import Atlas
from styleatlas.cluster import ARTISTS, METHODS, UNASSIGNED, Clustering
from styleatlas.dataset import clean_group_name
from styleatlas.metrics import PLAIN, space_name

GROUPS_FILE = "groups.json"
MIN_KNOWN = 0.5  # restore only when the file covers at least this share of the current images


@dataclass(frozen=True)
class SavedGroups:
    labels: np.ndarray  # saved group id per current image (UNASSIGNED for new images)
    names: dict[int, str]  # saved group id -> name
    settings: dict
    space: str | None  # metrics.StyleSpace name; None: not saved


def save_groups(
    path: Path,
    atlas: Atlas,
    clustering: Clustering,
    settings: dict,
    space: str,
    names: dict[int, str],
) -> None:
    data = {
        "settings": settings,
        "space": space,
        "labels": {atlas.rel(i): int(c) for i, c in enumerate(clustering.labels)},
        "group_names": {str(g): n for g, n in names.items()},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load_groups(path: Path, atlas: Atlas) -> SavedGroups | None:
    """None when there is no file or it covers under half of the images. A file that cannot be
    parsed is kept as groups.json.<time>.bad, so the next save cannot overwrite it."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return _parse(json.loads(text), atlas)
    except (ValueError, TypeError, AttributeError, KeyError):  # JSON errors are ValueErrors
        stamp = time.strftime("%Y%m%d-%H%M%S")
        with contextlib.suppress(OSError):
            os.replace(path, path.with_name(f"{path.name}.{stamp}.bad"))
        return None


def _parse(data: dict, atlas: Atlas) -> SavedGroups | None:
    raw = data["labels"]
    if not isinstance(raw, dict) or not all(type(v) is int for v in raw.values()):
        raise ValueError("labels must map relative paths to group ids")
    rels = [atlas.rel(i) for i in range(len(atlas))]
    if sum(r in raw for r in rels) < MIN_KNOWN * len(rels):
        return None
    labels = np.array([max(raw.get(r, UNASSIGNED), UNASSIGNED) for r in rels], dtype=int)
    names = {}  # file content is untrusted: names become folder names on export
    for g, n in data.get("group_names", {}).items():
        if g.isdigit() and isinstance(n, str) and n:
            try:
                names[int(g)] = clean_group_name(n)
            except ValueError:
                continue
    return SavedGroups(labels, names, _settings(data.get("settings"), len(atlas)), _space(data))


def _space(data: dict) -> str | None:
    """The saved space; files from before 0.14 kept a "neutralize" count instead."""
    if "space" in data:
        return space_name(data["space"])
    k = data.get("neutralize")
    if type(k) is int and k >= 0:
        return space_name(f"neutralize-{k}" if k else PLAIN)
    return None


def _settings(raw: object, n: int) -> dict:
    """Only well-formed settings come back: they are reused when the vector space is rebuilt."""
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    if raw.get("method") in (*METHODS, ARTISTS, "timeline"):
        out["method"] = raw["method"]
    thr = raw.get("threshold")  # null: auto
    if isinstance(thr, (int, float)) and not isinstance(thr, bool) and 0.05 <= thr <= 1.5:
        out["threshold"] = float(thr)
    elif "threshold" in raw and thr is None:
        out["threshold"] = None
    if type(raw.get("k")) is int and 1 <= raw["k"] <= n:
        out["k"] = raw["k"]
    return out


def carry_names(
    old_labels: np.ndarray,
    new_labels: np.ndarray,
    names: dict[int, str],
    prefer: int | None = None,
) -> dict[int, str]:
    """Group names after a regrouping: each name moves to the new group that holds most of its
    old group's images. When two names land on one group, `prefer` (the group merged into) wins,
    then the name that brought more images."""
    best: dict[int, tuple[float, str]] = {}
    for gid, name in names.items():
        hits = new_labels[(old_labels == gid) & (new_labels >= 0)]
        if not len(hits):
            continue
        counts = np.bincount(hits)
        target = int(counts.argmax())
        weight = np.inf if gid == prefer else float(counts[target])
        if target not in best or weight > best[target][0]:
            best[target] = (weight, name)
    return {g: n for g, (_, n) in sorted(best.items())}
