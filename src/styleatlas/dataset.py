"""Training-dataset helpers: caption tags, keeper choice among duplicates, folder plans, audit.

Folder plans map every image to a destination folder name. The kohya layout writes style groups
as `<repeats>_<name>_styleNN`, so sd-scripts / kohya_ss read them as separate concepts. Images
set aside (unassigned, duplicates, outliers) go to folders without a number prefix, which those
trainers skip.
"""

from __future__ import annotations

import functools
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from styleatlas.cluster import UNASSIGNED, Clustering
from styleatlas.lang import tr
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
    text = side.read_text(encoding="utf-8-sig", errors="replace")  # Notepad writes a BOM
    return [t.strip().lower() for t in text.replace("\n", ",").split(",") if t.strip()]


@dataclass(frozen=True)
class ImageInfo:
    width: int
    height: int
    frames: int
    file_size: int
    truncated: bool = False
    jpeg_quality: int | None = None
    orientation: int = 1  # EXIF orientation: 1 upright, 2-8 mirrored or turned


END_MARKERS = {"JPEG": b"\xff\xd9", "PNG": b"IEND"}
EXIF_ORIENTATION = 0x0112
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


INFO_CACHE = 65536  # images whose info is kept (a PNG's EXIF can mean decoding the whole file)


def image_info(path: Path) -> ImageInfo | None:
    """Size without decoding pixels (kept while the file is unchanged); None when the file cannot
    be opened."""
    try:
        st = Path(path).stat()
    except OSError:
        return None
    return _image_info(str(path), st.st_mtime_ns, st.st_size)


@functools.lru_cache(maxsize=INFO_CACHE)
def _image_info(path: str, mtime_ns: int, size: int) -> ImageInfo | None:  # time and size: the key
    try:
        with Image.open(path) as im:
            frames = 2 if getattr(im, "is_animated", False) else 1
            cut = _looks_truncated(Path(path), im.format)
            turn = _orientation(im)
            return ImageInfo(im.width, im.height, frames, size, cut, jpeg_quality(im), turn)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return None


def _orientation(im: Image.Image) -> int:
    """The EXIF orientation (1 when absent). A damaged EXIF block does not make the picture
    unreadable, so any error while parsing it counts as upright."""
    try:
        return int(im.getexif().get(EXIF_ORIENTATION, 1))
    except Exception:  # noqa: BLE001 - Pillow raises many kinds on malformed EXIF
        return 1


def best_in_group(paths: list[Path], blocked: set[int] | None = None) -> int:
    """Index of the copy to keep: most pixels, then not turned only by EXIF, then has a
    caption, then the larger file.
    Copies in `blocked` (excluded or outliers) are chosen only when nothing else is left."""
    blocked = blocked or set()

    def rank(i: int) -> tuple[int, int, int, int, int]:
        info = image_info(paths[i])
        pixels = info.width * info.height if info else 0
        size = info.file_size if info else 0
        upright = int(info is not None and info.orientation not in range(2, 9))
        has_caption = int(caption_of(paths[i]) is not None)
        return (int(i not in blocked), pixels, upright, has_caption, size)

    return max(range(len(paths)), key=rank)


def kept_copy(
    paths: list[Path], group: list[int], aside: set[int] | dict, prefer: set[int] | None = None
) -> int:
    """The image of a near-duplicate group an export keeps: one picked by hand (and not set
    aside), else best_in_group."""
    for i in group:
        if i in (prefer or ()) and i not in aside:
            return i
    blocked = {k for k, i in enumerate(group) if i in aside}
    return group[best_in_group([paths[i] for i in group], blocked)]


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
        raise ValueError(
            tr(
                f"repeats must be 'auto' or a whole number >= 1, got {repeats!r}",
                f"repeats 必須是 'auto' 或 >= 1 的整數，收到 {repeats!r}",
            )
        )
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
        raise ValueError(
            tr(
                "group name is empty after removing characters folders cannot use",
                "拿掉資料夾不能用的字元後，群名稱是空的",
            )
        )
    stem, dot, rest = out.partition(".")
    if stem.rstrip().upper() in RESERVED_NAMES:  # CON, nul.txt, COM1 ...: Windows refuses them
        out = f"{stem}_{dot}{rest}"
    return out


def is_unassigned(folder: str) -> bool:
    return folder in ("unassigned", SET_ASIDE["unassigned"])


def group_labels(
    clustering: Clustering, layout: str = "plain", group_names: dict[int, str] | None = None
) -> dict[int, str]:
    """Folder label per group: its name, else style_01 (plain) / style01 (kohya), or period_01 /
    period01 for periods along the timeline. Labels are made unique ignoring case (Windows folders
    are case-insensitive); names are placed first."""
    n_groups = clustering.n_clusters
    stem = "period" if clustering.method == "timeline" else "style"
    width = max(2, len(str(n_groups)))
    names = group_names or {}
    taken = {"unassigned"}
    out: dict[int, str] = {}
    order = sorted(range(n_groups), key=lambda c: (c not in names, c))
    for cid in order:
        sep = "_" if layout == "plain" else ""
        base = names.get(cid) or f"{stem}{sep}{cid + 1:0{width}d}"
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
    prefer: set[int] | None = None,
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
    for group in duplicate_groups or []:  # prefer: copies picked by hand to keep
        keep = kept_copy(paths, group, aside, prefer)
        aside.update({i: SET_ASIDE["duplicate"] for i in group if i != keep and i not in aside})
    full = Counter(int(c) for i, c in enumerate(clustering.labels) if i not in aside)
    if max_per_group is not None and style is not None:
        aside.update(_trimmed(clustering, style, aside, max_per_group))
    sizes = Counter(int(c) for i, c in enumerate(clustering.labels) if i not in aside)
    labels = group_labels(clustering, layout, group_names)
    trained = {c for c in sizes if c != UNASSIGNED and full[c] >= min_size}
    # one kohya folder: the LoRA's name is the whole trigger ("12_artistX", not "..._style01")
    alone = len(trained) == 1 and not (group_names or {}).get(next(iter(trained)))
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
            folders.append(f"{n}_{name}" if alone else f"{n}_{name}_{labels[cid]}")
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
    "exif_rotated",
    "no_caption",
    "empty_caption",
    "watermark_or_signature",
    "tag_spelling_mixed",
    "greyscale_in_colour_set",
    "greyscale_untagged",
    "greyscale_tag_on_colour",
)
GREY_TAGS = frozenset({"monochrome", "greyscale", "grayscale"})
# a greyscale caption is wrong on a picture with spot colour unless the caption says so
SPOT_TAGS = frozenset({"spot color", "partially colored", "limited palette", "sepia"})
# From this colourfulness a picture tagged greyscale clearly has colour: on 185 Danbooru works
# tagged greyscale, 6 reached it (framed photos, spot colour, a teal tint); between 0.03 and 0.08
# were photos of paper and faint tints, not worth a warning (docs/BENCHMARKS.md).
CLEARLY_COLOURED = 0.08


def audit(
    paths: list[Path],
    min_side: int = 512,
    max_ratio: float = 2.5,
    looks: np.ndarray | None = None,
) -> dict:
    """Problems a trainer would hit: small, extreme, enlarged or heavily compressed images,
    animations, missing captions, captions that mention a watermark or signature, and (given
    the look measures of `paths`) greyscale images mixed into a colour set and captions whose
    greyscale tags disagree with the picture. Finding enlarged images decodes every image (in
    parallel)."""
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
    report["tag_spelling_mixed"], spelt_two_ways = mixed_spellings(readable)
    if looks is not None and len(paths):
        report |= _colour_problems(paths, looks[:, LOOK_NAMES.index("colourfulness")])
    summary = _audit_summary(report, len(paths), sizes)
    return {
        "summary": summary,
        "files": report,
        "tags_spelt_two_ways": spelt_two_ways,
        "frequent_tags": frequent_tags(readable),
    }


FREQUENT_SHARE = 0.5  # a tag in at least this share of the captions is listed
FREQUENT_SHOWN = 12
FREQUENT_MIN_CAPTIONS = 5


def frequent_tags(paths: list[Path]) -> list[tuple[str, float]]:
    """Tags in at least FREQUENT_SHARE of the non-empty captions, most common first, with their
    share: content in nearly every training image (one character, one outfit) is learned along
    with the style. Spellings are merged (long_hair = long hair)."""
    counts: dict[str, int] = {}
    captioned = 0
    for p in paths:
        tags = {norm_tag(t) for t in read_tags(p)}
        tags.discard("")
        if not tags:
            continue
        captioned += 1
        for t in tags:
            counts[t] = counts.get(t, 0) + 1
    if captioned < FREQUENT_MIN_CAPTIONS:
        return []
    common = [(t, n / captioned) for t, n in counts.items() if n / captioned >= FREQUENT_SHARE]
    common.sort(key=lambda item: (-item[1], item[0]))
    return [(t, round(share, 2)) for t, share in common[:FREQUENT_SHOWN]]


def mixed_spellings(paths: list[Path]) -> tuple[list[str], list[str]]:
    """Captions that write a tag the less common way, when the dataset writes that same tag
    both with underscores and with spaces (`long_hair` here, `long hair` there): the text
    encoder reads the two as different words, so the tag's meaning is split between them.
    Which way is more common is counted over all such tags together. Also returns those
    tags (written with spaces)."""
    split, rare = _two_spellings(paths)
    if not split:
        return [], []
    files = [str(paths[i]) for i in sorted(set().union(*(f[rare] for f in split.values())))]
    return files, sorted(split)


def spelling_fixes(paths: list[Path]) -> dict[str, str]:
    """For each tag the captions write both ways, the spelling the dataset uses more (normalised
    tag -> "long hair" or "long_hair"), to respell the exported captions with."""
    split, rare = _two_spellings(paths)
    common = " " if rare == "_" else "_"
    return {tag: tag.replace(" ", common) for tag in split}


def _two_spellings(paths: list[Path]) -> tuple[dict[str, dict[str, set[int]]], str]:
    """Tags written with underscores in some captions and with spaces in others (normalised tag
    -> "_" or " " -> the captions using it), and the less common way over all of them."""
    forms: dict[str, dict[str, set[int]]] = {}
    for i, p in enumerate(paths):
        for t in read_tags(p):
            if ("_" in t) != (" " in t):  # one way or the other, not both
                forms.setdefault(norm_tag(t), {}).setdefault("_" if "_" in t else " ", set()).add(i)
    split = {tag: f for tag, f in forms.items() if len(f) == 2}
    under = sum(len(f["_"]) for f in split.values())
    rare = "_" if under <= sum(len(f[" "]) for f in split.values()) else " "
    return split, rare


def _colour_problems(paths: list[Path], colour: np.ndarray) -> dict[str, list[str]]:
    """Greyscale pictures in a colour set (and those of them whose caption lacks monochrome or
    greyscale, so the LoRA would learn greyscale as part of the style), and captions tagged
    greyscale on a clearly coloured picture. A mostly greyscale folder is a monochrome artist:
    its grey pictures are not flagged, and leaving the tag out there may be deliberate."""
    out: dict[str, list[str]] = {}
    grey = colour < GREYSCALE  # NaN (unreadable) compares False
    if grey.mean() < 0.5:
        out["greyscale_in_colour_set"] = [str(paths[i]) for i in np.flatnonzero(grey)]
        out["greyscale_untagged"] = [
            str(paths[i]) for i in np.flatnonzero(grey) if _tags_lack(paths[i], GREY_TAGS)
        ]
    out["greyscale_tag_on_colour"] = [
        str(paths[i])
        for i in np.flatnonzero(colour >= CLEARLY_COLOURED)
        if _says_greyscale(paths[i])
    ]
    return out


def _tags_lack(path: Path, wanted: frozenset[str]) -> bool:
    """The image has a non-empty caption without any of `wanted`."""
    tags = {norm_tag(t) for t in read_tags(path)}
    return bool(tags) and not tags & wanted


def _says_greyscale(path: Path) -> bool:
    tags = {norm_tag(t) for t in read_tags(path)}
    return bool(tags & {"greyscale", "grayscale"}) and not tags & SPOT_TAGS


def _image_problems(info, min_side: int, max_ratio: float) -> list[str]:
    short, long = min(info.width, info.height), max(info.width, info.height)
    checks = {
        "truncated": info.truncated,
        "low_jpeg_quality": info.jpeg_quality is not None and info.jpeg_quality < LOW_JPEG,
        "smaller_than_min_side": short < min_side,
        "extreme_aspect_ratio": long / max(1, short) > max_ratio,
        "animated": info.frames > 1,
        # kohya sd-scripts reads the pixels as stored, ignoring the EXIF rotation that viewers
        # (and this tool) apply, so a phone photo trains sideways (ai-toolkit, OneTrainer turn it)
        "exif_rotated": info.orientation in range(2, 9),
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
