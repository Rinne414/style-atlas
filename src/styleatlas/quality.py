"""Two cheap checks for training images that would teach the wrong thing (thresholds and how they
were set: docs/BENCHMARKS.md, "Low-quality images").

- JPEG quality, estimated from the file's quantisation table, without decoding the pixels.
- Softness: the detail in the finest octave relative to the octave two steps coarser. An image
  enlarged 2x or more from a smaller one has almost nothing in its finest octave, whatever it
  shows; sharp originals keep a ratio of 0.2 or more.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

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


def _scaled_sum(quality: int) -> float:
    scale = 5000 / quality if quality < 50 else 200 - 2 * quality
    return float(np.clip(np.floor((STD_LUMA * scale + 50) / 100), 1, 255).sum())


TABLE_SUMS = np.array([_scaled_sum(q) for q in range(1, 101)])

LOW_JPEG = 70  # below this, a JPEG is flagged
SOFT = 0.10  # below this softness ratio, an image looks enlarged or blurred
WINDOW = 1024  # measured on the centre at full size: shrinking first would hide an enlargement
MIN_WINDOW = 128  # smaller images are not judged
FLAT = 1.0  # coarse-octave detail below this (grey levels squared): nothing to judge


def jpeg_quality(image: Image.Image) -> int | None:
    """Estimated quality (1-100) of an opened JPEG, or None for other formats."""
    tables = getattr(image, "quantization", None)
    if not tables or 0 not in tables:
        return None
    total = float(np.sum(tables[0]))
    return int(np.argmin(np.abs(TABLE_SUMS - total))) + 1


def _octave(grey: Image.Image, step: int) -> float:
    """Mean squared detail between 1/2^(step+1) and 1/2^step of the sampling rate."""
    w, h = grey.size
    level = grey if step == 0 else grey.resize((w >> step, h >> step), Image.Resampling.BOX)
    half = level.resize((level.width // 2, level.height // 2), Image.Resampling.BOX)
    rebuilt = np.asarray(half.resize(level.size, Image.Resampling.BICUBIC), dtype=np.float32)
    return float(np.mean((np.asarray(level, dtype=np.float32) - rebuilt) ** 2))


def softness(image: Image.Image) -> float | None:
    """Finest-octave detail over the detail two octaves coarser, on the centre window at full
    size. None when the image is too small or too flat to judge."""
    w, h = image.size
    cw, ch = min(w, WINDOW), min(h, WINDOW)
    cw, ch = cw - cw % 16, ch - ch % 16  # whole pixels at every level
    if min(cw, ch) < MIN_WINDOW:
        return None
    left, top = (w - cw) // 2, (h - ch) // 2
    grey = image.crop((left, top, left + cw, top + ch)).convert("L")
    coarse = _octave(grey, 2)
    if coarse < FLAT:
        return None
    return _octave(grey, 0) / coarse


@lru_cache(maxsize=65536)
def _softness_of(path: str, stamp: tuple[int, int]) -> float | None:
    try:
        with Image.open(path) as im:
            if getattr(im, "is_animated", False):
                im.seek(0)
            return softness(im)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return None


def softness_of_file(path: Path) -> float | None:
    """Softness of an image file; cached while the file is unchanged."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return _softness_of(str(path), (st.st_mtime_ns, st.st_size))


def softness_of_files(paths: list[Path]) -> list[float | None]:
    """Softness of many files, decoded in parallel (Pillow releases the GIL while decoding)."""
    workers = max(1, min(8, os.cpu_count() or 1))
    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(softness_of_file, paths))
