"""Two cheap checks for training images that would teach the wrong thing (thresholds and how they
were set: docs/BENCHMARKS.md, "Low-quality images").

- JPEG quality, estimated from the file's quantisation table, without decoding the pixels.
- Softness: the detail in the finest octave relative to the octave two steps coarser, at the
  size a trainer uses. An image enlarged 2x or more from a smaller one has almost nothing in its
  finest octave, whatever it shows; sharp originals keep a ratio of 0.2 or more. Larger images
  are first shrunk to about 1024 x 1024 pixels, as trainers do, so softness that shrinking
  removes (a soft brush on a 4,000 px canvas) does not count.
"""

from __future__ import annotations

import math
import os
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from styleatlas.images import to_8bit

# The JPEG standard's example luminance table (Annex K). Encoders built on libjpeg scale it by
# the quality setting; comparing sums makes the estimate independent of the table's order.
STD_LUMA = np.array(
    [
        16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55,
        14, 13, 16, 24, 40, 57, 69, 56, 14, 17, 22, 29, 51, 87, 80, 62,
        18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92,
        49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99,
    ],
    dtype=np.float64,
)  # fmt: skip


def _scaled(quality: int) -> np.ndarray:
    scale = 5000 / quality if quality < 50 else 200 - 2 * quality
    return np.clip(np.floor((STD_LUMA * scale + 50) / 100), 1, 255)


TABLES = np.stack([_scaled(q) for q in range(1, 101)])
TABLE_SUMS = TABLES.sum(axis=1)

LOW_JPEG = 70  # below this, a JPEG is flagged
SOFT = 0.10  # below this softness ratio, an image looks enlarged or blurred
TRAIN_PIXELS = 1024 * 1024  # trainers shrink to about this area (SDXL, Illustrious, Anima)
WINDOW = 1024  # the centre, at training size
MIN_WINDOW = 128  # smaller images are not judged
FLAT = 1.0  # coarse-octave detail below this (grey levels squared): nothing to judge
MAX_PIXELS = 25_000_000  # larger decoded images are not judged (8 are decoded at a time)
STANDARD_FIT = 0.05  # a table further than this (mean relative difference) is not libjpeg's


def jpeg_quality(image: Image.Image) -> int | None:
    """Quality (1-100) of an opened JPEG saved with the standard (libjpeg) tables; None for other
    formats, and for encoders with tables of their own, whose quality cannot be read this way."""
    tables = getattr(image, "quantization", None)
    if not tables or 0 not in tables or len(tables[0]) != len(STD_LUMA):
        return None
    table = np.asarray(tables[0], dtype=np.float64)  # Pillow gives it in natural order
    best = int(np.argmin(np.abs(TABLE_SUMS - table.sum())))
    if np.mean(np.abs(table - TABLES[best])) > STANDARD_FIT * np.mean(TABLES[best]):
        return None
    return best + 1


def _octave(grey: Image.Image, step: int) -> float:
    """Mean squared detail between 1/2^(step+1) and 1/2^step of the sampling rate."""
    w, h = grey.size
    level = grey if step == 0 else grey.resize((w >> step, h >> step), Image.Resampling.BOX)
    half = level.resize((level.width // 2, level.height // 2), Image.Resampling.BOX)
    rebuilt = np.asarray(half.resize(level.size, Image.Resampling.BICUBIC), dtype=np.float32)
    return float(np.mean((np.asarray(level, dtype=np.float32) - rebuilt) ** 2))


def training_size(width: int, height: int) -> tuple[int, int]:
    """The size a trainer shrinks an image to (about TRAIN_PIXELS); smaller images keep theirs."""
    scale = min(1.0, math.sqrt(TRAIN_PIXELS / max(1, width * height)))
    return max(1, round(width * scale)), max(1, round(height * scale))


def softness(image: Image.Image) -> float | None:
    """Finest-octave detail over the detail two octaves coarser, on the centre window at
    training size. None when the image is too small, too large or too flat to judge."""
    if image.width * image.height > MAX_PIXELS:
        return None
    size = training_size(*image.size)
    grey = image.convert("L")
    if grey.size != size:
        grey = grey.resize(size, Image.Resampling.LANCZOS, reducing_gap=3.0)
    w, h = size
    cw, ch = min(w, WINDOW), min(h, WINDOW)
    cw, ch = cw - cw % 16, ch - ch % 16  # whole pixels at every level
    if min(cw, ch) < MIN_WINDOW:
        return None
    left, top = (w - cw) // 32 * 16, (h - ch) // 32 * 16  # on the grid of a 2x or 4x enlargement
    grey = grey.crop((left, top, left + cw, top + ch))
    coarse = _octave(grey, 2)
    if coarse < FLAT:
        return None
    return _octave(grey, 0) / coarse


@lru_cache(maxsize=65536)
def _softness_of(path: str, stamp: tuple[int, int]) -> float | None:
    """Cached by path and (mtime, size); a failure raises, so it is not cached."""
    with Image.open(path) as im:
        if getattr(im, "is_animated", False):
            im.seek(0)
        if im.format == "JPEG":  # decode at a reduced scale that is still >= the training size
            im.draft("L", training_size(*im.size))
        return softness(to_8bit(im))


def softness_of_file(path: Path) -> float | None:
    """Softness of an image file, cached while the file is unchanged. None when the file cannot
    be decoded: the check reports such files elsewhere and must not stop on one."""
    try:
        st = os.stat(path)
        return _softness_of(str(path), (st.st_mtime_ns, st.st_size))
    except Exception:  # noqa: BLE001 - Pillow raises many types on damaged or exotic files
        return None


def softness_of_files(paths: list[Path]) -> list[float | None]:
    """Softness of many files, decoded in parallel (Pillow releases the GIL while decoding)."""
    workers = max(1, min(8, os.cpu_count() or 1))
    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(softness_of_file, paths))
