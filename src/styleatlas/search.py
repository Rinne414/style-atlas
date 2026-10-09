"""Find images whose style is closest to one or more query images."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from styleatlas.metrics import DEFAULT_K, centroid, hub_scores


@dataclass(frozen=True)
class Hit:
    index: int
    score: float  # hub-corrected similarity used for ranking
    cosine: float


def knn(x: np.ndarray, k: int = 8, hub_k: int = DEFAULT_K, chunk: int = 2048) -> np.ndarray:
    """(n, k) indices of each row's nearest other rows by hub-corrected similarity (chunked)."""
    n = len(x)
    k = max(0, min(k, n - 1))
    if k == 0:
        return np.zeros((n, 0), dtype=int)
    density = neighbor_density_chunked(x, hub_k, chunk)
    out = np.zeros((n, k), dtype=int)
    for s in range(0, n, chunk):
        scores = hub_scores(x[s : s + chunk], x, k=hub_k, base_density=density)
        rows = np.arange(s, min(s + chunk, n))
        scores[rows - s, rows] = -np.inf
        part = np.argpartition(-scores, k, axis=1)[:, :k]
        order = np.take_along_axis(scores, part, axis=1).argsort(axis=1)[:, ::-1]
        out[s : s + chunk] = np.take_along_axis(part, order, axis=1)
    return out


def neighbor_density_chunked(x: np.ndarray, k: int = DEFAULT_K, chunk: int = 2048) -> np.ndarray:
    """neighbor_density(x, x, same_set=True) without an n x n matrix."""
    n = len(x)
    k = max(1, min(k, n - 1))
    out = np.zeros(n, dtype=np.float32)
    for s in range(0, n, chunk):
        sims = x[s : s + chunk] @ x.T
        rows = np.arange(s, min(s + chunk, n))
        sims[rows - s, rows] = -np.inf
        out[s : s + chunk] = np.partition(sims, -k, axis=1)[:, -k:].mean(axis=1)
    return out


def search(
    queries: np.ndarray,
    base: np.ndarray,
    top: int = 20,
    hub_k: int = DEFAULT_K,
    combine: bool = False,
    exclude: set[int] | None = None,
) -> list[list[Hit]]:
    """Top matches in `base` per query (or for the queries' shared style when `combine`)."""
    if len(base) == 0:
        return [[] for _ in range(1 if combine else len(queries))]
    q = centroid(queries)[None, :] if combine else queries
    scores = hub_scores(q, base, k=hub_k)
    cos = q @ base.T
    if exclude:
        scores[:, sorted(exclude)] = -np.inf
    results = []
    for row in range(len(q)):
        order = np.argsort(-scores[row])[:top]
        results.append(
            [
                Hit(int(i), float(scores[row, i]), float(cos[row, i]))
                for i in order
                if np.isfinite(scores[row, i])
            ]
        )
    return results
