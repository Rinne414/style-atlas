"""Training-dataset helpers: caption tags, keeper choice among duplicates, folder plans, audit.

Folder plans map every image to a destination folder name. The kohya layout writes style groups
as `<repeats>_<name>_styleNN`, so sd-scripts / kohya_ss read them as separate concepts. Images
set aside (unassigned, duplicates, outliers) go to folders without a number prefix, which those
trainers skip.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from styleatlas.cluster import UNASSIGNED, Clustering

CAPTION_SUFFIXES = (".txt", ".caption")
LAYOUTS = ("plain", "kohya")
AUTO_REPEATS_TARGET = 100  # images x repeats per style folder per epoch, a common kohya default
SET_ASIDE = {
    "duplicate": "_duplicates",
    "outlier": "_outliers",
    "unassigned": "_unassigned",
    "excluded": "_excluded",
}


def caption_of(image: Path) -> Path | None:
    for suffix in CAPTION_SUFFIXES:
        side = image.with_suffix(suffix)
        if side.exists():
            return side
    return None


def read_tags(image: Path) -> list[str]:
    """Comma-separated tags from the caption sidecar (Danbooru / WD14 style), lower-cased."""
    side = caption_of(image)
    if side is None:
        return []
    text = side.read_text(encoding="utf-8", errors="replace")
    return [t.strip().lower() for t in text.replace("\n", ",").split(",") if t.strip()]


@dataclass(frozen=True)
class ImageInfo:
    width: int
    height: int
    frames: int
    file_size: int
    truncated: bool = False


END_MARKERS = {"JPEG": b"\xff\xd9", "PNG": b"IEND"}
TAIL_BYTES = 64 * 1024  # camera / phone trailers and zero padding can follow the end marker


def _looks_truncated(path: Path, fmt: str | None) -> bool:
    """Cheap check without decoding: JPEG and PNG files end with a fixed marker."""
    marker = END_MARKERS.get(fmt or "")
    if marker is None:
        return False
    with open(path, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - TAIL_BYTES))
        return marker not in f.read()


def image_info(path: Path) -> ImageInfo | None:
    """Size without decoding pixels; None when the file cannot be opened."""
    try:
        with Image.open(path) as im:
            frames = 2 if getattr(im, "is_animated", False) else 1
            cut = _looks_truncated(Path(path), im.format)
            return ImageInfo(im.width, im.height, frames, Path(path).stat().st_size, cut)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return None


def best_in_group(paths: list[Path], blocked: set[int] | None = None) -> int:
    """Index of the copy to keep: most pixels, then has a caption, then the larger file.
    Copies in `blocked` (excluded or outliers) are chosen only when nothing else is left."""
    blocked = blocked or set()

    def rank(i: int) -> tuple[int, int, int, int]:
        info = image_info(paths[i])
        pixels = info.width * info.height if info else 0
        size = info.file_size if info else 0
        return (int(i not in blocked), pixels, int(caption_of(paths[i]) is not None), size)

    return max(range(len(paths)), key=rank)


def duplicate_keepers(
    paths: list[Path], groups: list[list[int]], blocked: set[int] | None = None
) -> np.ndarray:
    """Indices left after keeping only the best copy of every near-duplicate group."""
    blocked = blocked or set()
    drop = set()
    for group in groups:
        local = {k for k, i in enumerate(group) if i in blocked}
        keep = group[best_in_group([paths[i] for i in group], local)]
        drop.update(i for i in group if i != keep)
    return np.array([i for i in range(len(paths)) if i not in drop], dtype=int)


def tag_summary(
    paths: list[Path], clustering: Clustering, top: int = 8, min_count: int = 2
) -> dict[int, list[dict]]:
    """Per style group: its most frequent caption tags and how over-represented each is
    (lift = share in the group / share in the whole folder)."""
    tags = [set(read_tags(p)) for p in paths]
    if not any(tags):
        return {}
    overall = Counter(t for ts in tags for t in ts)
    n = len(paths)
    out: dict[int, list[dict]] = {}
    for c in clustering.clusters:
        counts = Counter(t for i in c.members for t in tags[i])
        rows = [
            {
                "tag": t,
                "share": round(k / c.size, 3),
                "lift": round((k / c.size) / (overall[t] / n), 2),
            }
            for t, k in counts.items()
            if k >= min_count
        ]
        rows.sort(key=lambda r: (-r["share"] * min(r["lift"], 3.0), r["tag"]))
        out[c.id] = rows[:top]
    return out


def parse_repeats(repeats: str | int) -> int | None:
    """None for "auto", else a whole number >= 1 (kohya skips folders like 0_name)."""
    if repeats == "auto":
        return None
    try:
        n = int(repeats)
    except (TypeError, ValueError):
        n = 0
    if n < 1 or str(n) != str(repeats).strip():
        raise ValueError(f"repeats must be 'auto' or a whole number >= 1, got {repeats!r}")
    return n


def auto_repeats(size: int, target: int = AUTO_REPEATS_TARGET) -> int:
    return max(1, round(target / max(1, size)))


def plan_folders(
    paths: list[Path],
    clustering: Clustering,
    layout: str = "plain",
    name: str = "style",
    repeats: str = "auto",
    duplicate_groups: list[list[int]] | None = None,
    outliers: list[int] | None = None,
    min_size: int = 1,
    excluded: list[int] | None = None,
) -> list[str]:
    """Destination folder name for every image. A style group left with fewer than `min_size`
    images after duplicates and outliers are set aside counts as unassigned."""
    if layout not in LAYOUTS:
        raise ValueError(f"layout must be one of {LAYOUTS}")
    fixed = parse_repeats(repeats)
    aside: dict[int, str] = {i: SET_ASIDE["outlier"] for i in outliers or []}
    aside.update({i: SET_ASIDE["excluded"] for i in excluded or []})  # a person's call wins
    for group in duplicate_groups or []:
        local = {k for k, i in enumerate(group) if i in aside}
        keep = group[best_in_group([paths[i] for i in group], local)]
        aside.update({i: SET_ASIDE["duplicate"] for i in group if i != keep and i not in aside})
    sizes = Counter(int(c) for i, c in enumerate(clustering.labels) if i not in aside)
    width = max(2, len(str(clustering.n_clusters)))
    folders = []
    for i, cid in enumerate(int(c) for c in clustering.labels):
        if i in aside:
            folders.append(aside[i])
        elif cid == UNASSIGNED or sizes[cid] < min_size:
            folders.append(SET_ASIDE["unassigned"] if layout == "kohya" else "unassigned")
        elif layout == "plain":
            folders.append(f"style_{cid + 1:0{width}d}")
        else:
            n = auto_repeats(sizes[cid]) if fixed is None else fixed
            folders.append(f"{n}_{name}_style{cid + 1:0{width}d}")
    return folders


def audit(paths: list[Path], min_side: int = 512, max_ratio: float = 2.5) -> dict:
    """Problems a trainer would hit: small or extreme images, animations, missing captions."""
    report: dict[str, list[str]] = {
        "unreadable": [],
        "truncated": [],
        "smaller_than_min_side": [],
        "extreme_aspect_ratio": [],
        "animated": [],
        "no_caption": [],
        "empty_caption": [],
    }
    sides = []
    for p in paths:
        info = image_info(p)
        if info is None:
            report["unreadable"].append(str(p))
            continue
        if info.truncated:
            report["truncated"].append(str(p))
        sides.append(min(info.width, info.height))
        if min(info.width, info.height) < min_side:
            report["smaller_than_min_side"].append(str(p))
        if max(info.width, info.height) / max(1, min(info.width, info.height)) > max_ratio:
            report["extreme_aspect_ratio"].append(str(p))
        if info.frames > 1:
            report["animated"].append(str(p))
        side = caption_of(p)
        if side is None:
            report["no_caption"].append(str(p))
        elif not read_tags(p):
            report["empty_caption"].append(str(p))
    summary = {k: len(v) for k, v in report.items()}
    summary["images"] = len(paths)
    if sides:
        sides.sort()
        summary["short_side_median"] = sides[len(sides) // 2]
        summary["short_side_p10"] = sides[max(0, math.ceil(len(sides) * 0.1) - 1)]
    return {"summary": summary, "files": report}
