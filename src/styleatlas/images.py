"""Find and open images."""

from __future__ import annotations

import base64
import hashlib
import io
import os
import re
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import BinaryIO

import numpy as np
from PIL import Image, ImageOps

from styleatlas.cachedir import cache_dir

IMAGE_TYPES = {  # suffix -> media type; Windows' registry may lack some (.webp)
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".jfif": "image/jpeg",  # what Chrome on Windows often saves JPEGs from X/Twitter as
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
    ".avif": "image/avif",
}
IMAGE_SUFFIXES = set(IMAGE_TYPES)
SKIP_DIRS = {".styleatlas", ".git", "__pycache__", "style_atlas_out", "__MACOSX"}
OUTPUT_SUFFIX = "_style_atlas"  # default result folders (export.output_dir) are never scanned


# A 164 KB PNG can decode to 500 MB; CSD looks at 224 px anyway. 100 M pixels is 10,000 x 10,000.
MAX_PIXELS = 100_000_000
WIDE_GREY = ("I;16", "I;16B", "I;16L", "I;16N", "I", "F")  # more than 8 bits per pixel


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
    real_root = root.resolve()
    inside: dict[Path, bool] = {}  # per folder: does it really lie under root (no junctions)?
    found = []
    for p in pattern:
        if p.is_symlink() or not p.is_file() or p.suffix.lower() not in IMAGE_SUFFIXES:
            continue  # a symlink in a downloaded dataset could point at any file
        if p.name.startswith("._"):
            continue  # macOS metadata ("AppleDouble") next to each file in zips made on a Mac
        if p.parent not in inside:
            inside[p.parent] = p.parent.resolve().is_relative_to(real_root)
        if not inside[p.parent]:
            continue
        parents = p.relative_to(root).parts[:-1]
        if SKIP_DIRS.intersection(parents) or any(d.endswith(OUTPUT_SUFFIX) for d in parents):
            continue
        if skip and any(p.resolve().is_relative_to(e) for e in skip):
            continue
        found.append(p)
    return sorted(found)


def load_rgb(
    path: Path | BinaryIO,
    background: tuple[int, int, int] = (255, 255, 255),
    max_side: int | None = None,
) -> Image.Image:
    """Open as RGB: EXIF orientation applied, transparency flattened onto `background`.
    With max_side, JPEGs are decoded at a reduced scale (much faster for thumbnails)."""
    with Image.open(path) as im:
        if im.width * im.height > MAX_PIXELS:  # checked before anything is decoded
            raise ValueError(f"image too large to open safely ({im.width} x {im.height})")
        if max_side and im.format == "JPEG":
            im.draft("RGB", (max_side, max_side))
        im = to_8bit(ImageOps.exif_transpose(im))
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            rgba = im.convert("RGBA")
            flat = Image.new("RGB", rgba.size, background)
            flat.paste(rgba, mask=rgba.getchannel("A"))
            return flat
        return im.convert("RGB")


def to_8bit(im: Image.Image) -> Image.Image:
    """Grey images with more than 8 bits per pixel (16-bit PNGs) as 8-bit grey. Pillow's own
    conversion clips them instead of scaling: a 16-bit grey PNG came out nearly all white."""
    if im.mode not in WIDE_GREY:
        return im
    if im.mode == "F":
        a = np.asarray(im, dtype=np.float32)
        if float(a.max(initial=0.0)) <= 1.0:
            a = a * 255.0  # 0-1 floats
        return Image.fromarray(np.clip(np.rint(a), 0, 255).astype(np.uint8))
    a = np.asarray(im)  # integers: 16-bit, or 32-bit holding 8- or 16-bit values
    if im.mode.startswith("I;16") or int(a.max(initial=0)) > 255:
        a = np.clip(a, 0, 65535) >> 8  # 0-65535 to 0-255 without float copies
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def thumbnail_bytes(path: Path, size: int = 96, quality: int = 70) -> bytes:
    """Small WebP thumbnail (longest side `size`)."""
    im = load_rgb(path, max_side=size * 2)
    im.thumbnail((size, size), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="WEBP", quality=quality)
    return buf.getvalue()


def cached_thumbnail(path: Path, size: int = 96) -> bytes:
    """thumbnail_bytes, kept on disk (keyed by path, size and modification time) so a folder
    opens instantly the second time."""
    st = Path(path).stat()
    key = hashlib.sha1(
        f"{Path(path).resolve()}|{st.st_size}|{st.st_mtime_ns}|{size}".encode()
    ).hexdigest()
    folder = cache_dir() / "thumbs" / key[:2]
    file = folder / f"{key}.webp"
    if file.exists():
        return file.read_bytes()
    data = thumbnail_bytes(path, size)
    folder.mkdir(parents=True, exist_ok=True)
    tmp = file.with_name(f"{file.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, file)
    return data


def thumbnail_data_url(path: Path, size: int = 96, quality: int = 70) -> str:
    """Small WebP thumbnail as a data URL, for self-contained HTML reports."""
    data = cached_thumbnail(path, size) if quality == 70 else thumbnail_bytes(path, size, quality)
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
