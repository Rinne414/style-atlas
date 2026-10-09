"""Search whitening: a fixed linear map learned from 306 Danbooru artists that turns down the
directions CSD vectors vary along within one artist's work (within-class covariance
normalization). On artists never seen when it was learned it raised same-artist top-1 by 1.9-3.1
points and also helped on AI renders (+1.4); docs/BENCHMARKS.md, "Search whitening".

Only search ranking uses it. Distances that are compared with fixed thresholds (groups,
duplicates, the Style Gate, taste) stay in plain CSD space, where those thresholds were set.
Refit with scripts/fit_whitening.py."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources

import numpy as np

from styleatlas.metrics import unit


@lru_cache(maxsize=1)
def _params() -> tuple[np.ndarray, np.ndarray]:
    with resources.files("styleatlas").joinpath("data/whiten_csd.npz").open("rb") as f:
        z = np.load(f)
        return z["mean"].astype(np.float32), z["matrix"].astype(np.float32)


def whiten(x: np.ndarray) -> np.ndarray:
    """Unit vectors in the whitened space (same shape as `x`)."""
    mean, matrix = _params()
    return unit((np.asarray(x, dtype=np.float32) - mean) @ matrix)
