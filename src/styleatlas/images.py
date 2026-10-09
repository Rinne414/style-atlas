"""Find and open images."""

from __future__ import annotations

import base64
import io
from collections.abc import Iterable
from pathlib import Path

from PIL import Image, ImageOps

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".avif"}
SKIP_DIRS = {".styleatlas", ".git", "__pycache__"}


def find_images(root: Path, recursive: bool = True) -> list[Path]:
    """All image files under `root`, sorted, skipping tool folders. `root` may be a single file."""
    root = Path(root)
    if root.is_file():
        return [root] if root.suffix.lower() in IMAGE_SUFFIXES else []
    pattern = root.rglob("*") if recursive else root.iterdir()
    found = [
        p
        for p in pattern
        if p.is_file()
        and p.suffix.lower() in IMAGE_SUFFIXES
        and not SKIP_DIRS.intersection(p.relative_to(root).parts[:-1])
    ]
    return sorted(found)


def load_rgb(path: Path, background: tuple[int, int, int] = (255, 255, 255)) -> Image.Image:
    """Open as RGB: EXIF orientation applied, transparency flattened onto `background`."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
            rgba = im.convert("RGBA")
            flat = Image.new("RGB", rgba.size, background)
            flat.paste(rgba, mask=rgba.getchannel("A"))
            return flat
        return im.convert("RGB")


def thumbnail_data_url(path: Path, size: int = 96, quality: int = 70) -> str:
    """Small WebP thumbnail as a data URL, for self-contained HTML reports."""
    im = load_rgb(path)
    im.thumbnail((size, size), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="WEBP", quality=quality)
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def labels_from_folders(paths: Iterable[Path], root: Path) -> list[str]:
    """Label = first sub-folder under `root` (used by `bench` and `taste`)."""
    out = []
    for p in paths:
        parts = Path(p).relative_to(root).parts
        out.append(parts[0] if len(parts) > 1 else "")
    return out
