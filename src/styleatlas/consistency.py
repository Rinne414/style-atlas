"""How consistent is a folder's style? Compared with single artists, so the number means
something: "spread" is the mean distance of each image to the centre of the others (whitened
CSD), averaged over random 10-image samples because it shrinks as a set grows (0.76 at 5 images,
0.71 at 10, 0.65 at all of the same artists' works). The reference is 250 Danbooru artists.

On 114 artists the whitening and the reference never saw, 13% of single artists were more
spread than 90% of the reference, against 51% of two-artist mixes, 91% of three and 100% of five
(docs/BENCHMARKS.md, "Style consistency")."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from styleatlas.metrics import unit
from styleatlas.whiten import whiten

SAMPLE = 10  # images per draw; the reference was measured the same way
DRAWS = 30
SEED = 0
# spread at SAMPLE of 250 single Danbooru artists, at percentiles 0, 5, ..., 100
REFERENCE = np.array(
    [
        0.000, 0.381, 0.476, 0.506, 0.553, 0.577, 0.603, 0.617, 0.640, 0.654, 0.675,
        0.690, 0.703, 0.719, 0.734, 0.751, 0.773, 0.790, 0.801, 0.834, 0.887,
    ]
)  # fmt: skip
MIXED = 90  # above this percentile of single artists, a folder is probably a mix


@dataclass(frozen=True)
class Consistency:
    spread: float
    percentile: float  # share of single artists whose style is tighter (0-100)

    @property
    def verdict(self) -> str:
        """One of: tight, like one artist, mixed."""
        if self.percentile <= 50:
            return "tight"
        return "like one artist" if self.percentile <= MIXED else "mixed"


def _spread(x: np.ndarray) -> float:
    others = unit(x.sum(axis=0)[None, :] - x)
    return float(np.mean(1.0 - np.sum(x * others, axis=1)))


def consistency(style: np.ndarray) -> Consistency | None:
    """The style consistency of a set of CSD style vectors; None below SAMPLE images."""
    if len(style) < SAMPLE:
        return None
    x = unit(whiten(style, keep=False))
    rng = np.random.default_rng(SEED)
    spread = float(
        np.mean([_spread(x[rng.choice(len(x), SAMPLE, replace=False)]) for _ in range(DRAWS)])
    )
    percentile = float(np.interp(spread, REFERENCE, np.arange(0, 101, 5)))
    return Consistency(round(spread, 3), round(percentile, 1))
