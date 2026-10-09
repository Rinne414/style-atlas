"""Find and open images."""

from __future__ import annotations

import base64
import io
import re
from collections.abc import Iterable
from pathlib import Path
from typing import BinaryIO

from PIL import Image, ImageOps

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".avif"}
SKIP_DIRS = {".styleatlas", ".git", "__pycache__", "style_atlas_out"}
OUTPUT_SUFFIX = "_style_atlas"  # default result folders (export.output_dir) are never scanned


def find_images(
    root: Path, recursive: bool = True, exclude: list[Path] | None = None
) -> list[Path]:
    """All image files under `root`, sorted. Skips tool folders (including earlier style-atlas
    output) and anything under `exclude`. `root` may be a single file."""
    root = Path(root)
    if root.is_file():
        return [root] if root.suffix.lower() in IMAGE_SUFFIXES else []
    skip = [Path(e).resolve() for e in exclude or []]
    pattern = root.rglob("*") if recursive else root.iterdir()
    found = []
    for p in pattern:
        if not p.is_file() or p.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        parents = p.relative_to(root).parts[:-1]
        if SKIP_DIRS.intersection(parents) or any(d.endswith(OUTPUT_SUFFIX) for d in parents):
            continue
        if skip and any(p.resolve().is_relative_to(e) for e in skip):
            continue
        found.append(p)
    return sorted(found)


def load_rgb(
    path: Path | BinaryIO, background: tuple[int, int, int] = (255, 255, 255)
) -> Image.Image:
    """Open as RGB: EXIF orientation applied, transparency flattened onto `background`."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            rgba = im.convert("RGBA")
            flat = Image.new("RGB", rgba.size, background)
            flat.paste(rgba, mask=rgba.getchannel("A"))
            return flat
        return im.convert("RGB")


def thumbnail_bytes(path: Path, size: int = 96, quality: int = 70) -> bytes:
    """Small WebP thumbnail (longest side `size`)."""
    im = load_rgb(path)
    im.thumbnail((size, size), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="WEBP", quality=quality)
    return buf.getvalue()


def thumbnail_data_url(path: Path, size: int = 96, quality: int = 70) -> str:
    """Small WebP thumbnail as a data URL, for self-contained HTML reports."""
    data = thumbnail_bytes(path, size, quality)
    return "data:image/webp;base64," + base64.b64encode(data).decode("ascii")


TIME_SOURCES = ("none", "name", "mtime")
_DIGITS = re.compile(r"\d{5,}")


def file_time(path: Path, source: str) -> float | None:
    """A sortable time for `path`: the file's modified time, or the largest run of 5+ digits in
    its name (Pixiv and Danbooru ids grow with upload date). None when unavailable."""
    if source == "mtime":
        try:
            return Path(path).stat().st_mtime
        except OSError:
            return None
    if source == "name":
        runs = _DIGITS.findall(Path(path).stem)
        return float(max(int(r) for r in runs)) if runs else None
    return None


def labels_from_folders(paths: Iterable[Path], root: Path) -> list[str]:
    """Label = first sub-folder under `root` (used by `bench` and `taste`)."""
    out = []
    for p in paths:
        parts = Path(p).relative_to(root).parts
        out.append(parts[0] if len(parts) > 1 else "")
    return out
