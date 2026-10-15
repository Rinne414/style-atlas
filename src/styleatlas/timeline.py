"""Periods along the timeline: one artist's works, in time order, cut into contiguous periods where
the style changes most (optimal change points), with a test of whether those changes are more
than chance.

On 13 Danbooru artists (docs/BENCHMARKS.md, "Periods along the timeline") the optimal cuts were
beyond shuffled time orders for 8 and gave clearer style differences than equal time thirds for
11; k-means (`--granularity period`) separates styles more but mixes the eras."""

from __future__ import annotations

import numpy as np

from styleatlas.cluster import UNASSIGNED, Clustering, _info

TIMELINE = "timeline"
SEGMENT_MIN = 5  # works per period at least
SEGMENT_DIMS = 32  # PCA dimensions the cuts are searched in (keeps the search fast)
NULL_ROUNDS = 99  # shuffled time orders for the p-value
NULL_SAMPLE = 400  # works the test uses at most (evenly through time): the search is quadratic
CLEAR_P = 0.05


def cluster_timeline(
    style: np.ndarray,
    times: np.ndarray,
    k: int,
    min_size: int = SEGMENT_MIN,
    content: np.ndarray | None = None,
    seed: int = 0,
) -> Clustering:
    """Periods 0 (earliest) .. k-1 of the images with a known time (`times`, NaN when unknown, e.g.
    from images.timeline); the rest are unassigned. params: the period sizes, the p-value of the
    cuts against shuffled time orders (how often periods there are as distinct), and the
    periods' separation (cosine silhouette). With `content`, near-duplicates count once in the
    test: variants posted one after another would otherwise make the cuts look real."""
    times = np.asarray(times, dtype=float)
    known = np.flatnonzero(np.isfinite(times))
    order = known[np.argsort(times[known], kind="stable")]
    min_size = max(1, min_size)
    if len(order) < k * min_size:
        raise ValueError(f"need at least {k * min_size} images with a known time for {k} periods")
    x = np.asarray(style, dtype=np.float64)[order]
    z = _reduce(x)
    cuts = segment(z, k, min_size)
    labels = np.full(len(style), UNASSIGNED, dtype=int)
    labels[order] = cuts
    clusters = [_info(style, c, np.flatnonzero(labels == c)) for c in range(k)]
    once = np.arange(len(order))
    if content is not None:
        from styleatlas.duplicates import keep_one_per_group, near_duplicate_groups

        groups = near_duplicate_groups(np.asarray(style)[order], np.asarray(content)[order])
        once = np.sort(np.asarray(keep_one_per_group(len(order), groups), dtype=int))
    separation = _separation(x, cuts)
    p = _p_value(z[once], x[once], k, min_size, np.random.default_rng(seed))
    params = {"n_clusters": k, "p": round(p, 3), "separation": round(separation, 3)}
    return Clustering(labels, clusters, TIMELINE, params)


def segment(z: np.ndarray, k: int, min_size: int) -> np.ndarray:
    """Labels 0..k-1 for the rows of `z` (in time order): the contiguous split with the least
    within-period squared distance to the period's mean (dynamic programming)."""
    n = len(z)
    csum = np.vstack([np.zeros(z.shape[1]), np.cumsum(z, axis=0)])
    csq = np.concatenate([[0.0], np.cumsum((z * z).sum(axis=1))])
    best = np.full((k + 1, n + 1), np.inf)
    back = np.zeros((k + 1, n + 1), dtype=int)
    best[0, 0] = 0.0
    for j in range(1, k + 1):
        for b in range(j * min_size, n + 1):
            a = np.arange((j - 1) * min_size, b - min_size + 1)
            s = csum[b] - csum[a]
            cost = best[j - 1, a] + csq[b] - csq[a] - (s * s).sum(axis=1) / (b - a)
            i = int(np.argmin(cost))
            best[j, b], back[j, b] = cost[i], a[i]
    labels = np.empty(n, dtype=int)
    b = n
    for j in range(k, 0, -1):
        a = back[j, b]
        labels[a:b] = j - 1
        b = a
    return labels


def _reduce(x: np.ndarray) -> np.ndarray:
    from sklearn.decomposition import PCA

    dims = min(SEGMENT_DIMS, len(x) - 1, x.shape[1])
    return PCA(n_components=dims, random_state=0).fit_transform(x) if dims >= 1 else x


def _separation(x: np.ndarray, labels: np.ndarray) -> float:
    """How distinct the periods' styles are: the cosine silhouette (-1..1; 0 = not at all)."""
    from sklearn.metrics import silhouette_score

    return float(silhouette_score(x, labels, metric="cosine")) if len(set(labels)) > 1 else 0.0


def _p_value(
    z: np.ndarray, x: np.ndarray, k: int, min_size: int, rng: np.random.Generator
) -> float:
    """How often the best cuts of a shuffled time order give periods as distinct (on at most
    NULL_SAMPLE works, evenly through time, the observed cuts made on the same works). Drift
    alone is common (12 of 13 artists); this asks whether the periods are told apart."""
    if len(z) > NULL_SAMPLE:
        pick = np.linspace(0, len(z) - 1, NULL_SAMPLE).round().astype(int)
        z, x = z[pick], x[pick]
    if len(z) < k * min_size:
        return 1.0  # too few distinct works left to tell
    observed = _separation(x, segment(z, k, min_size))
    hits = 0
    for _ in range(NULL_ROUNDS):
        perm = rng.permutation(len(z))
        hits += _separation(x[perm], segment(z[perm], k, min_size)) >= observed
    return (1 + hits) / (1 + NULL_ROUNDS)
