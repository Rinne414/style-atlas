"""Readable style measures: six numbers per image that say *how* styles differ.

CSD vectors tell how far apart two styles are, not in what way. These measures are plain image
statistics on a copy whose long side is 256 px:

  brightness     mean luma (0 dark .. 1 light)
  contrast       spread of luma (standard deviation)
  colourfulness  Hasler and Suesstrunk (2003) colourfulness, about 0 (greyscale) .. 0.4 (neon)
  warmth         mean red minus mean blue (below 0 cool, above 0 warm)
  lines          share of pixels on a strong luma edge (line art, hatching, fine texture)
  flatness       share of pixels in flat areas (cel colour, plain backgrounds)

On 3,259 Danbooru works by 306 artists, 13-40% of each measure's spread was between artists
(ICC: lines 0.40, flatness 0.37, colourfulness 0.32, brightness 0.32, contrast 0.26, warmth
0.13). A single image says little; the mean of a group is what to compare (docs/BENCHMARKS.md).
"""

from __future__ import annotations

import numpy as np
from PIL import Image

LOOK_NAMES = ("brightness", "contrast", "colourfulness", "warmth", "lines", "flatness")
LOOK_VERSION = 1  # bump when a formula changes: cached values of older versions are ignored
SIDE = 256
EDGE = 0.12  # luma gradient that counts as a line
FLAT = 0.01  # luma gradient below which an area is flat


def measure(image: Image.Image) -> np.ndarray:
    """The six measures of one image, in LOOK_NAMES order (float32)."""
    im = image.convert("RGB")
    im.thumbnail((SIDE, SIDE), Image.Resampling.LANCZOS)
    a = np.asarray(im, dtype=np.float32) / 255
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    rg, yb = r - g, 0.5 * (r + g) - b
    colourful = np.hypot(rg.std(), yb.std()) + 0.3 * np.hypot(rg.mean(), yb.mean())
    gx = np.zeros_like(y)
    gy = np.zeros_like(y)
    gx[:, 1:-1] = (y[:, 2:] - y[:, :-2]) / 2
    gy[1:-1, :] = (y[2:, :] - y[:-2, :]) / 2
    grad = np.hypot(gx, gy)
    values = (
        y.mean(),
        y.std(),
        colourful,
        (r - b).mean(),
        (grad > EDGE).mean(),
        (grad < FLAT).mean(),
    )
    return np.array(values, dtype=np.float32)


def profile(looks: np.ndarray, members: np.ndarray | list[int]) -> np.ndarray:
    """How a group differs from the whole collection: each measure's group mean minus the
    collection mean, in units of the collection's spread (z). Zeros for a constant measure."""
    spread = looks.std(axis=0)
    diff = looks[members].mean(axis=0) - looks.mean(axis=0)
    return np.divide(diff, spread, out=np.zeros_like(diff), where=spread > 1e-9)


WORDS = {  # (above the collection, below it)
    "brightness": ("brighter", "darker"),
    "contrast": ("more contrast", "less contrast"),
    "colourfulness": ("more colourful", "less colourful"),
    "warmth": ("warmer", "cooler"),
    "lines": ("more line work", "less line work"),
    "flatness": ("flatter colour", "more texture"),
}
NOTABLE = 0.5  # |z| from which a difference is worth putting into words


def describe(z: np.ndarray) -> str:
    """Words for a profile (see `profile`), strongest first: "more line work, cooler"; empty
    when no measure differs by NOTABLE or more."""
    order = np.argsort(-np.abs(z))
    words = [WORDS[LOOK_NAMES[j]][0 if z[j] > 0 else 1] for j in order if abs(z[j]) >= NOTABLE]
    return ", ".join(words)


def difference(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """B minus A for each measure, in pooled standard deviations (Cohen's d)."""
    pooled = np.sqrt((a.var(axis=0, ddof=1) + b.var(axis=0, ddof=1)) / 2)
    diff = b.mean(axis=0) - a.mean(axis=0)
    return np.divide(diff, pooled, out=np.zeros_like(diff), where=pooled > 1e-9)
