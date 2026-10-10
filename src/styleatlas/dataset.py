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
from styleatlas.look import GREYSCALE, LOOK_NAMES
from styleatlas.quality import LOW_JPEG, SOFT, jpeg_quality, softness_of_files

CAPTION_SUFFIXES = (".txt", ".caption")
LAYOUTS = ("plain", "kohya")
AUTO_REPEATS_TARGET = 100  # images x repeats per style folder per epoch, a common kohya default
SET_ASIDE = {
    "duplicate": "_duplicates",
    "outlier": "_outliers",
    "unassigned": "_unassigned",
    "excluded": "_excluded",
    "trimmed": "_trimmed",
}
MAX_PER_GROUP_RANGE = (1, 100_000)


def diverse_subset(x: np.ndarray, n: int) -> list[int]:
    """n rows of `x` (unit vectors) that cover the set: the most central one first, then each
    time the row farthest from everything picked so far (farthest-point sampling)."""
    if n <= 0:
        return []
    if n >= len(x):
        return list(range(len(x)))
    x = np.nan_to_num(x)
    centre = x.mean(axis=0)
    picked = [int(np.argmax(x @ centre))]
    nearest = 1.0 - x @ x[picked[0]]  # distance from each row to its closest pick
    nearest[picked[0]] = -np.inf  # never picked twice, even among identical rows
    while len(picked) < n:
        i = int(np.argmax(nearest))
        picked.append(i)
        nearest = np.minimum(nearest, 1.0 - x @ x[i])
        nearest[picked] = -np.inf
    return picked


def caption_of(image: Path) -> Path | None:
    for suffix in CAPTION_SUFFIXES:
        side = image.with_suffix(suffix)
        if side.exists():
            return side
    return None


# Caption tags (Danbooru, WD14) for marks drawn on the image, which a LoRA learns along with
# the style: crop them out, exclude the image, or keep the tag in the caption.
MARK_TAGS = frozenset(
    {
        "watermark",
        "sample watermark",
        "signature",
        "artist name",
        "dated",
        "web address",
        "twitter username",
        "patreon username",
        "pixiv username",
        "weibo username",
    }
)


def norm_tag(tag: str) -> str:
    """Tags compare without case, and with spaces and underscores alike."""
    return " ".join(tag.lower().replace("_", " ").split())


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
    jpeg_quality: int | None = None


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
            size = Path(path).stat().st_size
            return ImageInfo(im.width, im.height, frames, size, cut, jpeg_quality(im))
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
    paths: list[Path],
    clustering: Clustering,
    top: int = 8,
    min_count: int = 2,
    tags: list[set[str]] | None = None,
) -> dict[int, list[dict]]:
    """Per style group: its most frequent caption tags and how over-represented each is
    (lift = share in the group / share in the whole folder). `tags` are the images' tag sets,
    when already read."""
    tags = tags if tags is not None else [set(read_tags(p)) for p in paths]
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


def distinctive_tags(
    summary: dict[int, list[dict]], top: int = 4, min_lift: float = 1.3
) -> dict[int, list[str]]:
    """The few tags that set each group apart (over-represented by `min_lift` or more), for a
    one-line description in the map."""
    return {
        g: [r["tag"] for r in rows if r["lift"] >= min_lift][:top] for g, rows in summary.items()
    }


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


# folder-name characters Windows refuses, plus "," (it would split a caption's trigger word)
INVALID_NAME_CHARS = set('<>:"/\\|?*,') | {chr(c) for c in range(32)}
RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{d}{i}" for d in ("COM", "LPT") for i in range(1, 10)
}
MAX_NAME = 60


def clean_group_name(name: str) -> str:
    """A group name usable as a folder name and trigger word on every OS (CJK is fine)."""
    out = "".join("_" if ch in INVALID_NAME_CHARS else ch for ch in str(name))
    out = out.strip(" ._")[:MAX_NAME].strip(" ._")  # Windows drops trailing dots and spaces
    if not out:
        raise ValueError("group name is empty after removing characters folders cannot use")
    stem, dot, rest = out.partition(".")
    if stem.rstrip().upper() in RESERVED_NAMES:  # CON, nul.txt, COM1 ...: Windows refuses them
        out = f"{stem}_{dot}{rest}"
    return out


def is_unassigned(folder: str) -> bool:
    return folder in ("unassigned", SET_ASIDE["unassigned"])


def group_labels(
    clustering: Clustering, layout: str = "plain", group_names: dict[int, str] | None = None
) -> dict[int, str]:
    """Folder label per group: its name, else style_01 (plain) / style01 (kohya). Labels are made
    unique ignoring case (Windows folders are case-insensitive); names are placed first."""
    n_groups = clustering.n_clusters
    width = max(2, len(str(n_groups)))
    names = group_names or {}
    taken = {"unassigned"}
    out: dict[int, str] = {}
    order = sorted(range(n_groups), key=lambda c: (c not in names, c))
    for cid in order:
        sep = "_" if layout == "plain" else ""
        base = names.get(cid) or f"style{sep}{cid + 1:0{width}d}"
        label, n = base, 2
        while label.casefold() in taken:
            label, n = f"{base}_{n}", n + 1
        taken.add(label.casefold())
        out[cid] = label
    return out


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
    group_names: dict[int, str] | None = None,
    max_per_group: int | None = None,
    style: np.ndarray | None = None,
) -> list[str]:
    """Destination folder name for every image. A style group left with fewer than `min_size`
    images after duplicates and outliers are set aside counts as unassigned. With
    max_per_group (and the style vectors), a larger group keeps that many images that cover it
    (see diverse_subset); the rest go to _trimmed."""
    if layout not in LAYOUTS:
        raise ValueError(f"layout must be one of {LAYOUTS}")
    fixed = parse_repeats(repeats)
    aside: dict[int, str] = {i: SET_ASIDE["outlier"] for i in outliers or []}
    aside.update({i: SET_ASIDE["excluded"] for i in excluded or []})  # a person's call wins
    for group in duplicate_groups or []:
        local = {k for k, i in enumerate(group) if i in aside}
        keep = group[best_in_group([paths[i] for i in group], local)]
        aside.update({i: SET_ASIDE["duplicate"] for i in group if i != keep and i not in aside})
    full = Counter(int(c) for i, c in enumerate(clustering.labels) if i not in aside)
    if max_per_group is not None and style is not None:
        aside.update(_trimmed(clustering, style, aside, max_per_group))
    sizes = Counter(int(c) for i, c in enumerate(clustering.labels) if i not in aside)
    labels = group_labels(clustering, layout, group_names)
    folders = []
    for i, cid in enumerate(int(c) for c in clustering.labels):
        if i in aside:
            folders.append(aside[i])
        elif cid == UNASSIGNED or full[cid] < min_size:  # judged before any trimming
            folders.append(SET_ASIDE["unassigned"] if layout == "kohya" else "unassigned")
        elif layout == "plain":
            folders.append(labels[cid])
        else:
            n = auto_repeats(sizes[cid]) if fixed is None else fixed
            folders.append(f"{n}_{name}_{labels[cid]}")
    return folders


def _trimmed(clustering: Clustering, style: np.ndarray, aside: dict, cap: int) -> dict:
    """Images beyond `cap` in each group (after other set-asides), by diverse_subset."""
    out = {}
    for c in clustering.clusters:
        left = [i for i in c.members if i not in aside]
        if len(left) > cap:
            keep = {left[k] for k in diverse_subset(style[left], cap)}
            out.update({i: SET_ASIDE["trimmed"] for i in left if i not in keep})
    return out


BUCKET_RESOLUTION = 1024  # kohya sd-scripts defaults for SDXL-class models
BUCKET_MIN, BUCKET_MAX, BUCKET_STEP = 256, 1024, 64
SPARSE_BUCKET = 4  # buckets with fewer images make short batches at batch size 2 and up


def bucket_resolutions(resolution: int = BUCKET_RESOLUTION) -> list[tuple[int, int]]:
    """The aspect-ratio buckets kohya sd-scripts makes (library/model_util.py,
    make_bucket_resolutions) for a square training resolution."""
    area = resolution * resolution
    side = int(math.sqrt(area) // BUCKET_STEP) * BUCKET_STEP
    resos = {(side, side)}
    for width in range(BUCKET_MIN, BUCKET_MAX + 1, BUCKET_STEP):
        height = min(BUCKET_MAX, int((area // width) // BUCKET_STEP) * BUCKET_STEP)
        if height >= BUCKET_MIN:
            resos.update({(width, height), (height, width)})
    return sorted(resos)


def bucket_counts(sizes: list[tuple[int, int]]) -> dict[str, int]:
    """How many images fall in each bucket ("832x1216": n, most first): kohya picks the bucket
    with the closest aspect ratio (library/dataset.py, select_bucket, with upscaling allowed)."""
    resos = bucket_resolutions()
    ratios = np.array([w / h for w, h in resos])
    counts: Counter[str] = Counter()
    for w, h in sizes:
        bw, bh = (w, h) if (w, h) in resos else resos[int(np.abs(ratios - w / h).argmin())]
        counts[f"{bw}x{bh}"] += 1
    return dict(counts.most_common())


AUDIT_KEYS = (
    "unreadable",
    "truncated",
    "smaller_than_min_side",
    "extreme_aspect_ratio",
    "soft_or_enlarged",
    "low_jpeg_quality",
    "animated",
    "no_caption",
    "empty_caption",
    "watermark_or_signature",
    "greyscale_in_colour_set",
)


def audit(
    paths: list[Path],
    min_side: int = 512,
    max_ratio: float = 2.5,
    looks: np.ndarray | None = None,
) -> dict:
    """Problems a trainer would hit: small, extreme, enlarged or heavily compressed images,
    animations, missing captions, captions that mention a watermark or signature, and (given
    the look measures of `paths`) greyscale images mixed into a colour set. Finding enlarged
    images decodes every image (in parallel)."""
    report: dict[str, list[str]] = {k: [] for k in AUDIT_KEYS}
    sizes: list[tuple[int, int]] = []
    readable = []
    for p in paths:
        info = image_info(p)
        if info is None:
            report["unreadable"].append(str(p))
            continue
        readable.append(p)
        sizes.append((info.width, info.height))
        for key in _image_problems(info, min_side, max_ratio) + _caption_problems(p):
            report[key].append(str(p))
    for p, soft in zip(readable, softness_of_files(readable), strict=True):
        if soft is not None and soft < SOFT:
            report["soft_or_enlarged"].append(str(p))
    if looks is not None and len(paths):
        grey = looks[:, LOOK_NAMES.index("colourfulness")] < GREYSCALE
        if grey.mean() < 0.5:  # a mostly greyscale folder is a monochrome artist, not a mistake
            report["greyscale_in_colour_set"] = [str(paths[i]) for i in np.flatnonzero(grey)]
    return {"summary": _audit_summary(report, len(paths), sizes), "files": report}


def _image_problems(info, min_side: int, max_ratio: float) -> list[str]:
    short, long = min(info.width, info.height), max(info.width, info.height)
    checks = {
        "truncated": info.truncated,
        "low_jpeg_quality": info.jpeg_quality is not None and info.jpeg_quality < LOW_JPEG,
        "smaller_than_min_side": short < min_side,
        "extreme_aspect_ratio": long / max(1, short) > max_ratio,
        "animated": info.frames > 1,
    }
    return [k for k, found in checks.items() if found]


def _caption_problems(path: Path) -> list[str]:
    side = caption_of(path)
    if side is None:
        return ["no_caption"]
    tags = read_tags(path)
    if not tags:
        return ["empty_caption"]
    return ["watermark_or_signature"] if any(norm_tag(t) in MARK_TAGS for t in tags) else []


def _audit_summary(report: dict, n: int, sizes: list[tuple[int, int]]) -> dict:
    summary = {k: len(v) for k, v in report.items()}
    summary["images"] = n
    summary["buckets"] = bucket_counts(sizes)
    sides = sorted(min(w, h) for w, h in sizes)
    if sides:
        summary["short_side_median"] = sides[len(sides) // 2]
        summary["short_side_p10"] = sides[max(0, math.ceil(len(sides) * 0.1) - 1)]
    return summary
