"""How consistent is a folder's style? Compared with single artists, so the number means
something: "spread" is the mean distance of each image to the centre of the others (whitened
CSD), averaged over random 10-image samples because it shrinks as a set grows (0.76 at 5 images,
0.71 at 10, 0.65 at all of the same artists' works). The reference is 114 Danbooru artists that
neither the search whitening nor anything else here was fitted on, so new folders are read on a
fair scale.

Built on half of those artists and tested on the other half, 11% of single artists were more
spread than 90% of the reference, against 49% of two-artist mixes, 85% of three and 100% of five
(docs/BENCHMARKS.md, "Style consistency")."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from styleatlas.metrics import unit
from styleatlas.whiten import whiten

SAMPLE = 10  # images per draw; the reference was measured the same way
DRAWS = 30
SEED = 0
# spread at SAMPLE of 114 single Danbooru artists unseen by the whitening, percentiles 0..100
REFERENCE = np.array(
    [
        0.349, 0.478, 0.507, 0.595, 0.620, 0.632, 0.637, 0.660, 0.674, 0.697, 0.707,
        0.715, 0.725, 0.742, 0.758, 0.777, 0.783, 0.790, 0.813, 0.842, 0.894,
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
