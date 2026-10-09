"""Style distances: cosine, hub-corrected (CSLS) distances, and calibrated style units.

Hubness: in high-dimensional embedding spaces a few "hub" images sit close to everything, so raw
nearest neighbours are dominated by them. CSLS (Lample et al. 2018) subtracts each point's mean
similarity to its k nearest neighbours. On 3,245 Danbooru works by 306 artists, CSLS raised
same-artist pair AUC from 0.79 to 0.85 and clustering NMI from 0.55 to 0.70
(see docs/BENCHMARKS.md).

`hub_distance` keeps the cosine-distance scale:
    d = 1 - cos + (r_i + r_j) / 2 - mean(r), clipped at 0,
so thresholds read like cosine distances.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DEFAULT_K = 10
CHUNK = 2048  # rows per block, so no n x n similarity matrix is ever held


def unit(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    norms = np.linalg.norm(x, axis=-1, keepdims=True)
    return x / np.maximum(norms, 1e-12)


def neighbor_density(
    queries: np.ndarray, base: np.ndarray, k: int = DEFAULT_K, same_set: bool = False
) -> np.ndarray:
    """Mean cosine of each query to its k nearest rows of `base` (row i of base excluded for
    query i when same_set). Processed in blocks of CHUNK query rows."""
    others = base.shape[0] - (1 if same_set else 0)
    if others <= 0:
        return np.zeros(len(queries), dtype=np.float32)
    k = max(1, min(k, others))
    out = np.empty(len(queries), dtype=np.float32)
    for s in range(0, len(queries), CHUNK):
        sims = queries[s : s + CHUNK] @ base.T
        if same_set:
            rows = np.arange(s, s + len(sims))
            sims[rows - s, rows] = -np.inf
        out[s : s + len(sims)] = np.partition(sims, -k, axis=1)[:, -k:].mean(axis=1)
    return out


@dataclass(frozen=True)
class Neutralizer:
    """Removes each vector's deviation along the strongest directions of variation in a
    collection, keeping the shared mean so distances keep their scale.

    When the same characters appear in many styles (style-exploration renders), the strongest
    direction is the character: on 96 NovelAI styles x 2 characters, removing one direction
    raised same-style retrieval AUC from 0.83 to 0.98. When a collection mixes different artists,
    the strongest direction IS the style difference, and removing it wrecked clustering (ARI 0.55
    to 0.02). So this is opt-in, for subject-heavy collections only."""

    mean: np.ndarray
    axes: np.ndarray  # (k, d)

    @classmethod
    def fit(cls, x: np.ndarray, k: int) -> Neutralizer:
        from sklearn.decomposition import PCA

        mean = x.mean(axis=0)
        k = max(0, min(k, len(x) - 1))
        axes = (
            PCA(n_components=k, random_state=0).fit(x - mean).components_
            if k
            else np.zeros((0, x.shape[1]), np.float32)
        )
        return cls(mean.astype(np.float32), axes.astype(np.float32))

    def apply(self, x: np.ndarray) -> np.ndarray:
        if not len(self.axes):
            return x
        return unit(x - ((x - self.mean) @ self.axes.T) @ self.axes)


def cosine_distance(x: np.ndarray) -> np.ndarray:
    d = 1.0 - x @ x.T
    d = np.maximum(d, 0.0)
    np.fill_diagonal(d, 0.0)
    return d.astype(np.float64)


def hub_distance(x: np.ndarray, k: int = DEFAULT_K) -> np.ndarray:
    """Pairwise hub-corrected distance within one set (n x n, float64, zero diagonal)."""
    if len(x) < 3:
        return cosine_distance(x)
    r = neighbor_density(x, x, k=k, same_set=True).astype(np.float64)
    d = (x @ x.T).astype(np.float64)  # built in place below to keep peak memory at ~12 bytes/pair
    np.subtract(1.0 - r.mean(), d, out=d)
    d += r[:, None] / 2.0
    d += r[None, :] / 2.0
    np.maximum(d, 0.0, out=d)
    np.fill_diagonal(d, 0.0)
    return d


def hub_scores(
    queries: np.ndarray,
    base: np.ndarray,
    k: int = DEFAULT_K,
    base_density: np.ndarray | None = None,
) -> np.ndarray:
    """Query-vs-base similarity for ranking: cos - r_base / 2 (CSLS up to a per-query constant)."""
    r = base_density if base_density is not None else neighbor_density(base, base, k, same_set=True)
    return queries @ base.T - r[None, :] / 2.0


@dataclass(frozen=True)
class StyleScale:
    """Express centroid distances in noise units.

    `noise_floor` is the distance you get between two halves of the *same* style. The default 0.071
    was measured on NovelAI V5 renders: the mean distance between the 2-image centroids of two seed
    pairs of one recipe (21 recipes). In those units, z >= 2.3 read as clearly different to a human
    judge and z < 1.5 as the same style. Recalibrate on your own data with `style-atlas calibrate`.
    """

    noise_floor: float = 0.071
    same_below: float = 1.5
    different_above: float = 2.3

    def z(self, distance: float) -> float:
        return float(distance) / self.noise_floor

    def verdict(self, distance: float) -> str:
        z = self.z(distance)
        if z < self.same_below:
            return "same style"
        if z >= self.different_above:
            return "clearly different"
        return "related"


def centroid(x: np.ndarray) -> np.ndarray:
    return unit(np.asarray(x).mean(axis=0))


def group_difference(
    a: np.ndarray, b: np.ndarray, rounds: int = 999, seed: int = 0
) -> tuple[float, float]:
    """(centroid distance, permutation p-value) for 'do these two image sets differ in style?'."""
    if len(a) < 2 or len(b) < 2:
        raise ValueError("each group needs at least 2 images")
    observed = 1.0 - float(centroid(a) @ centroid(b))
    pooled = np.vstack([a, b])
    rng = np.random.default_rng(seed)
    hits = 0
    for _ in range(rounds):
        perm = rng.permutation(len(pooled))
        pa, pb = pooled[perm[: len(a)]], pooled[perm[len(a) :]]
        if 1.0 - float(centroid(pa) @ centroid(pb)) >= observed:
            hits += 1
    return observed, (hits + 1) / (rounds + 1)


def split_half_noise(x: np.ndarray, rounds: int = 200, seed: int = 0) -> float:
    """Mean distance between centroids of two random halves of one style group."""
    n = len(x)
    if n < 4:
        raise ValueError("need at least 4 images of one style to estimate its noise floor")
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(rounds):
        perm = rng.permutation(n)
        a, b = perm[: n // 2], perm[n // 2 : 2 * (n // 2)]
        out.append(1.0 - float(centroid(x[a]) @ centroid(x[b])))
    return float(np.mean(out))
