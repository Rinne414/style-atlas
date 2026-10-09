"""Group images by style when the number of styles is unknown.

Default: average-linkage agglomerative clustering on hub-corrected distances, cut at a distance
threshold. On mixtures of 2-5 Danbooru artists (90 random draws) a threshold of 0.45-0.50 gave the
best agreement with the artist labels (ARI ~0.5); see docs/BENCHMARKS.md. HDBSCAN is offered too:
it leaves ambiguous images unassigned instead of forcing them into a group.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from sklearn.cluster import HDBSCAN, AgglomerativeClustering
from sklearn.decomposition import PCA

from styleatlas.metrics import DEFAULT_K, centroid, hub_distance, neighbor_density, unit

# medium / fine / coarse were tuned on blind mixtures of different artists. `period` is for
# splitting ONE artist's work: on 13 prolific artists its groups matched posting-time quartiles
# beyond chance for 9 (medium: 4), docs/BENCHMARKS.md.
GRANULARITY = {"period": 0.35, "fine": 0.40, "medium": 0.47, "coarse": 0.55}
METHODS = ("agglomerative", "hdbscan")
MAX_DENSE = 8000  # the n x n float64 distance matrix (+ sklearn's copy) above this is too large
UNASSIGNED = -1


@dataclass
class ClusterInfo:
    id: int
    size: int
    medoid: int  # index of the most central member
    cohesion: float  # mean distance of members to their centroid
    members: list[int] = field(default_factory=list)


@dataclass
class Clustering:
    labels: np.ndarray  # cluster id per image, UNASSIGNED (-1) for noise / tiny groups
    clusters: list[ClusterInfo]
    method: str
    params: dict

    @property
    def n_clusters(self) -> int:
        return len(self.clusters)

    @property
    def n_unassigned(self) -> int:
        return int((self.labels == UNASSIGNED).sum())


def cluster_styles(
    x: np.ndarray,
    method: str = "agglomerative",
    threshold: float | None = None,
    n_clusters: int | None = None,
    min_size: int = 3,
    hub_k: int = DEFAULT_K,
) -> Clustering:
    """Cluster unit style vectors `x`. `n_clusters` forces a count; otherwise `threshold` cuts."""
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}")
    n = len(x)
    if n < 2:
        return _finish(x, np.zeros(n, dtype=int), method, {}, min_size=1)
    params: dict = {"hub_k": hub_k, "min_size": min_size}
    if n > MAX_DENSE and method != "hdbscan":
        method = "hdbscan"
        params["note"] = (
            f"{n} images is above {MAX_DENSE}: used HDBSCAN on PCA-64 vectors; "
            "threshold and k were ignored"
        )
    if method == "agglomerative":
        thr = GRANULARITY["medium"] if threshold is None else threshold
        dist = hub_distance(x, k=hub_k)
        model = AgglomerativeClustering(
            n_clusters=n_clusters,
            metric="precomputed",
            linkage="average",
            distance_threshold=None if n_clusters else thr,
        )
        raw = model.fit_predict(dist)
        params |= {"n_clusters": n_clusters} if n_clusters else {"threshold": thr}
    else:
        raw = _hdbscan(x, min_size, hub_k)
    return _finish(x, raw, method, params, min_size)


def _hdbscan(x: np.ndarray, min_size: int, hub_k: int) -> np.ndarray:
    model = HDBSCAN(min_cluster_size=max(2, min_size), min_samples=2, copy=True)
    if len(x) <= MAX_DENSE:
        model.set_params(metric="precomputed")
        return model.fit_predict(hub_distance(x, k=hub_k))
    reduced = unit(PCA(n_components=64, random_state=0).fit_transform(x))
    return model.fit_predict(reduced)


def _finish(x: np.ndarray, raw: np.ndarray, method: str, params: dict, min_size: int) -> Clustering:
    """Drop groups smaller than min_size, renumber by size (0 = largest), compute summaries."""
    ids, counts = np.unique(raw[raw >= 0], return_counts=True)
    by_size = sorted(zip(ids, counts, strict=True), key=lambda t: -t[1])
    keep = [i for i, c in by_size if c >= min_size]
    remap = {old: new for new, old in enumerate(keep)}
    labels = np.array([remap.get(int(v), UNASSIGNED) for v in raw], dtype=int)
    clusters = []
    for cid in range(len(keep)):
        members = np.flatnonzero(labels == cid)
        c = centroid(x[members])
        d = 1.0 - x[members] @ c
        clusters.append(
            ClusterInfo(
                id=cid,
                size=len(members),
                medoid=int(members[int(np.argmin(d))]),
                cohesion=float(d.mean()),
                members=members.tolist(),
            )
        )
    return Clustering(labels, clusters, method, params)


def edit_groups(x: np.ndarray, clustering: Clustering, moves: dict[int, int]) -> Clustering:
    """Apply hand edits: {image index: target group id or UNASSIGNED}. Groups are then renumbered
    by size again (0 = largest) and their medoid and spread recomputed. Merging group a into b
    is moves = {i: b for i in a.members}."""
    labels = clustering.labels.copy()
    for i, target in moves.items():
        labels[int(i)] = int(target)
    params = {**clustering.params, "edited": True}
    return _finish(x, labels, clustering.method, params, min_size=1)


def split_group(x: np.ndarray, clustering: Clustering, group: int) -> Clustering:
    """Hand edit: cut one group in two (2-way clustering of its members only)."""
    members = np.array(clustering.clusters[group].members)
    if len(members) < 2:
        raise ValueError("a group needs at least 2 images to be split")
    halves = cluster_styles(x[members], n_clusters=2, min_size=1).labels
    new_id = clustering.n_clusters  # renumbered by size afterwards
    moves = {int(m): new_id for m, h in zip(members, halves, strict=True) if h == 1}
    return edit_groups(x, clustering, moves)


def expand_clustering(sub: Clustering, kept: np.ndarray, n: int) -> Clustering:
    """A clustering of the rows `kept` of an n-image set, re-indexed to the full set; the rows
    left out are UNASSIGNED."""
    labels = np.full(n, UNASSIGNED, dtype=int)
    labels[kept] = sub.labels
    clusters = [
        ClusterInfo(
            id=c.id,
            size=c.size,
            medoid=int(kept[c.medoid]),
            cohesion=c.cohesion,
            members=[int(kept[m]) for m in c.members],
        )
        for c in sub.clusters
    ]
    return Clustering(labels, clusters, sub.method, sub.params)


def outlier_scores(x: np.ndarray, k: int = DEFAULT_K) -> np.ndarray:
    """1 - mean cosine to the k nearest other images: high = unlike the rest of the set."""
    if len(x) < 2:
        return np.zeros(len(x), dtype=np.float32)
    return 1.0 - neighbor_density(x, x, k=k, same_set=True)
