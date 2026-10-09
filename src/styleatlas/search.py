"""Find images whose style is closest to one or more query images."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from styleatlas.metrics import CHUNK, DEFAULT_K, centroid, hub_scores, neighbor_density


@dataclass(frozen=True)
class Hit:
    index: int
    score: float  # hub-corrected similarity used for ranking
    cosine: float


def knn(x: np.ndarray, k: int = 8, hub_k: int = DEFAULT_K, chunk: int = CHUNK) -> np.ndarray:
    """(n, k) indices of each row's nearest other rows by hub-corrected similarity (chunked)."""
    n = len(x)
    k = max(0, min(k, n - 1))
    if k == 0:
        return np.zeros((n, 0), dtype=int)
    density = neighbor_density(x, x, k=hub_k, same_set=True)
    out = np.zeros((n, k), dtype=int)
    for s in range(0, n, chunk):
        scores = hub_scores(x[s : s + chunk], x, k=hub_k, base_density=density)
        rows = np.arange(s, min(s + chunk, n))
        scores[rows - s, rows] = -np.inf
        part = np.argpartition(-scores, k, axis=1)[:, :k]
        order = np.take_along_axis(scores, part, axis=1).argsort(axis=1)[:, ::-1]
        out[s : s + chunk] = np.take_along_axis(part, order, axis=1)
    return out


def nearest_reference(
    x: np.ndarray, ref: np.ndarray, chunk: int = CHUNK
) -> tuple[np.ndarray, np.ndarray]:
    """(distance, index) of each row's closest reference vector; distance = 1 - cosine.
    Used as an originality measure: how far an image is from every style you already know."""
    dist = np.empty(len(x), dtype=np.float32)
    which = np.empty(len(x), dtype=int)
    for s in range(0, len(x), chunk):
        sims = x[s : s + chunk] @ ref.T
        which[s : s + chunk] = sims.argmax(axis=1)
        dist[s : s + chunk] = 1.0 - sims.max(axis=1)
    return dist, which


def style_path(
    x: np.ndarray, a: int, b: int, steps: int = 8, skip: set[int] | None = None
) -> list[int]:
    """Images along the way from style a to style b: for evenly spaced points on the great
    circle between the two vectors, the closest image not used yet (a first, b last)."""
    if a == b:
        return [a]
    va, vb = x[a], x[b]
    angle = float(np.arccos(np.clip(va @ vb, -1.0, 1.0)))
    path, used = [a], {a, b} | (skip or set())
    for t in np.linspace(0.0, 1.0, steps + 2)[1:-1]:
        if angle < 1e-6 or angle > np.pi - 1e-3:  # same style, or no unique path between
            break
        point = (np.sin((1 - t) * angle) * va + np.sin(t * angle) * vb) / np.sin(angle)
        sims = np.nan_to_num(x @ point, nan=-np.inf)
        sims[list(used)] = -np.inf
        best = int(np.argmax(sims))
        if not np.isfinite(sims[best]):
            break
        path.append(best)
        used.add(best)
    return path + [b]


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
    density = neighbor_density(base, base, k=hub_k, same_set=True)
    scores = hub_scores(q, base, k=hub_k, base_density=density)
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
