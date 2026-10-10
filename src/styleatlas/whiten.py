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


CACHE_ROWS = 1000  # a library this large is kept whitened while it is searched again
_LAST: list[tuple[np.ndarray, np.ndarray]] = []  # (input, read-only result), by identity


def whiten(x: np.ndarray) -> np.ndarray:
    """Unit vectors in the whitened space (same shape as `x`). A large input that is passed
    again as the very same array (never modified in place) gets the same read-only result, so
    the neighbour density computed from it is reused too: a search of a 20,000-image folder
    took 4.3 s with the density recomputed every time."""
    for src, out in _LAST:
        if src is x:
            return out
    mean, matrix = _params()
    out = unit((np.asarray(x, dtype=np.float32) - mean) @ matrix)
    if len(out) >= CACHE_ROWS:
        out.flags.writeable = False
        _LAST.append((x, out))
        del _LAST[:-2]
    return out
