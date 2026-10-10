"""Group images by style when the number of styles is unknown.

Default: average-linkage agglomerative clustering on hub-corrected distances, cut at a distance
threshold. On mixtures of 2-5 Danbooru artists a threshold of 0.45-0.50 gave the best agreement
with the artist labels (ARI ~0.5), but the best cut falls as more artists are mixed (0.34 for
300), so by default the cut is chosen from the data (auto_threshold); see docs/BENCHMARKS.md.
HDBSCAN is offered too: it leaves ambiguous images unassigned instead of forcing them into a
group.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.sparse import csr_matrix
from scipy.spatial.distance import squareform
from sklearn.cluster import HDBSCAN, KMeans, MiniBatchKMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score

from styleatlas.duplicates import keep_one_per_group, near_duplicate_groups
from styleatlas.lang import tr
from styleatlas.metrics import DEFAULT_K, centroid, hub_distance, neighbor_density, unit

# medium / fine / coarse were tuned on blind mixtures of different artists. Splitting ONE
# artist's work into periods uses k-means instead (method "kmeans", PERIODS groups): on 13
# artists it followed posting time as well as a 0.35 cut and puts every image in a period
# (groups under min_size aside), where the cut left 36-77% unassigned for 4 artists. Three is a
# convention: choosing k by silhouette did worse.
GRANULARITY = {"fine": 0.40, "medium": 0.47, "coarse": 0.55}
PERIODS = 3
METHODS = ("agglomerative", "hdbscan", "kmeans")
AUTO_CUTS = np.round(np.arange(0.20, 0.605, 0.01), 2)  # cuts auto_threshold tries
AUTO_OFFSET = 0.04
AUTO_SAMPLE = 3000  # images the silhouette is computed on
AUTO_DUP = 0.80  # style cosine at which images count once when choosing the cut
MAX_DENSE = 8000  # the n x n float64 distance matrix (+ sklearn's copy) above this is too large
KMEANS_SEED = 0
_TREE_CACHE: dict = {}  # last large set: (micro-group per image, linkage tree)
UNASSIGNED = -1
FIT_PERCENTILE = 70  # a new image fits a group when it is as close as this share of its members
FIT_MIN = 3  # smallest group a new image can be placed in
BATCH_MIN, BATCH_IN, BATCH_OUT = 8, 0.5, 0.25  # reading a batch's share that fits
ARTISTS = "artists"  # the grouping that follows artists in a gallery of many
ARTISTS_CUT = 0.90  # its cut in the search whitening's space (docs/BENCHMARKS.md)
ARTISTS_FEW = 10  # fewer groups than this: the folder is probably not a big gallery


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
    """Cluster unit style vectors `x`. `n_clusters` forces a count; otherwise `threshold` cuts,
    and without a threshold the cut is chosen from the data (auto_threshold)."""
    if method not in METHODS:
        raise ValueError(f"method must be one of {METHODS}")
    n = len(x)
    if n < 2:
        return _finish(x, np.zeros(n, dtype=int), method, {}, min_size=1)
    params: dict = {"hub_k": hub_k, "min_size": min_size}
    if method == "kmeans":  # periods of one artist: a set number of groups covering everything
        k = min(n_clusters or PERIODS, n)
        raw = KMeans(n_clusters=k, n_init=10, random_state=KMEANS_SEED).fit_predict(x)
        return _finish(x, raw, method, params | {"n_clusters": k}, min_size)
    if method == "agglomerative":
        part, tree, dist = _average_tree(x, hub_k)
        if n > MAX_DENSE:
            params["note"] = (
                f"{n} images is above {MAX_DENSE}: average linkage joined {MAX_DENSE} k-means "
                "micro-groups instead of single images"
            )
        if n_clusters:
            raw = _cut(tree, part, n_clusters=n_clusters)
            params["n_clusters"] = n_clusters
        else:
            thr = threshold if threshold is not None else auto_threshold(x, tree, part, dist, hub_k)
            raw = _cut(tree, part, thr)
            params |= {"threshold": thr, "auto": threshold is None}
    else:
        raw = _hdbscan(x, min_size, hub_k)
    return _finish(x, raw, method, params, min_size)


def _average_tree(x: np.ndarray, hub_k: int) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """Average-linkage tree on hub-corrected distances: (node of each image, tree, distance
    matrix). Above MAX_DENSE images the nodes are k-means micro-groups and there is no matrix."""
    if len(x) > MAX_DENSE:
        part, tree = _micro_tree(x, hub_k, MAX_DENSE)
        return part, tree, None
    dist = hub_distance(x, k=hub_k)
    tree = linkage(squareform(dist, checks=False), method="average")
    return np.arange(len(x)), tree, dist


def _cut(
    tree: np.ndarray, part: np.ndarray, thr: float = 0.0, n_clusters: int | None = None
) -> np.ndarray:
    """Group id per image from cutting `tree` at distance `thr` (or into `n_clusters`)."""
    if len(tree) == 0:  # a single node
        return np.zeros(len(part), dtype=int)
    if n_clusters:
        flat = fcluster(tree, t=min(n_clusters, len(tree) + 1), criterion="maxclust")
    else:
        flat = fcluster(tree, t=thr, criterion="distance")
    return flat[part] - 1


def auto_threshold(
    x: np.ndarray,
    tree: np.ndarray,
    part: np.ndarray,
    dist: np.ndarray | None,
    hub_k: int = DEFAULT_K,
) -> float:
    """The cut used when none is given: the cut with the best silhouette, plus AUTO_OFFSET (the
    silhouette's best sits a little below the cut that best matches artists), never above
    medium. On Danbooru mixtures it was within noise of the fixed medium cut for 2-20 artists and
    0.16-0.21 ARI better for 50-306 (with 5-9% unassigned instead of 1-2%); with stacks of
    copies it stayed at medium. docs/BENCHMARKS.md."""
    n = len(part)
    idx = np.arange(n)
    if n > AUTO_SAMPLE:
        idx = np.sort(np.random.default_rng(0).choice(n, AUTO_SAMPLE, replace=False))
    idx = _one_per_stack(x, idx)
    if dist is None:
        d = hub_distance(x[idx], k=hub_k)
    else:
        d = dist if len(idx) == n else dist[np.ix_(idx, idx)]
    best, score = GRANULARITY["medium"], -np.inf
    for t in AUTO_CUTS:
        labels = _cut(tree, part, float(t))[idx]
        if 1 < len(np.unique(labels)) < len(idx):
            s = silhouette_score(d, labels, metric="precomputed")
            if s > score:
                best, score = float(t), s
    return round(min(GRANULARITY["medium"], best + AUTO_OFFSET), 2)


def _one_per_stack(x: np.ndarray, idx: np.ndarray) -> np.ndarray:
    """`idx` with very similar images (style cosine >= AUTO_DUP) reduced to one. Stacks of
    copies or same-prompt variants look like perfect tiny groups to the silhouette and would drag
    the cut down until whole artists shatter (a guard at 0.92 still failed on variants at cosine
    0.85-0.94; at 0.80 auto matched medium on them, docs/BENCHMARKS.md)."""
    groups = near_duplicate_groups(x[idx], x[idx], AUTO_DUP)
    return idx[keep_one_per_group(len(idx), groups)]


def _micro_tree(x: np.ndarray, hub_k: int, parts: int) -> tuple[np.ndarray, np.ndarray]:
    """k-means micro-groups and their average-linkage tree. The tree uses the exact mean
    hub-corrected distance between the micro-groups' images (cosine and the density terms are
    bilinear, so per-group sums give it). The last set's tree is kept, so a new threshold (the
    web app's slider) only cuts it again."""
    key = (hashlib.blake2b(x.tobytes(), digest_size=16).hexdigest(), hub_k, parts, KMEANS_SEED)
    if key not in _TREE_CACHE:
        km = MiniBatchKMeans(
            n_clusters=parts, init="random", random_state=KMEANS_SEED, batch_size=4096, n_init=1
        )
        part = np.unique(km.fit_predict(x), return_inverse=True)[1]  # no empty micro-groups
        r = neighbor_density(x, x, k=hub_k, same_set=True).astype(np.float64)
        d = _group_distances(x, r, part)
        tree = linkage(squareform(d, checks=False), method="average") if len(d) > 1 else []
        _TREE_CACHE.clear()
        _TREE_CACHE[key] = (part, np.asarray(tree))
    return _TREE_CACHE[key]


def _group_distances(x: np.ndarray, r: np.ndarray, part: np.ndarray) -> np.ndarray:
    """Mean hub-corrected distance between the images of every two groups in `part`."""
    m = int(part.max()) + 1
    member = csr_matrix((np.ones(len(x)), (part, np.arange(len(x)))), shape=(m, len(x)))
    sums = np.asarray(member @ x.astype(np.float64))
    count = np.bincount(part, minlength=m).astype(np.float64)
    mean_r = np.bincount(part, weights=r, minlength=m) / count
    d = sums @ sums.T  # built in place below, as in hub_distance
    d /= count[:, None]
    d /= count[None, :]
    np.subtract(1.0 - r.mean(), d, out=d)
    d += mean_r[:, None] / 2.0
    d += mean_r[None, :] / 2.0
    np.maximum(d, 0.0, out=d)
    np.fill_diagonal(d, 0.0)
    return d


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
    clusters = [_info(x, cid, np.flatnonzero(labels == cid)) for cid in range(len(keep))]
    return Clustering(labels, clusters, method, params)


def _info(x: np.ndarray, cid: int, members: np.ndarray) -> ClusterInfo:
    d = 1.0 - x[members] @ centroid(x[members])
    return ClusterInfo(
        id=cid,
        size=len(members),
        medoid=int(members[int(np.argmin(d))]),
        cohesion=float(d.mean()),
        members=members.tolist(),
    )


def cluster_by_artist(style: np.ndarray, min_size: int = 3) -> Clustering:
    """Groups that follow artists in a gallery of many: average linkage in the search
    whitening's space at ARTISTS_CUT (plain CSD in, medoids and spreads in plain CSD out). On
    mixtures of 20 / 50 held-out Danbooru artists it matched them +0.13 / +0.07 ARI better than
    `auto`, but only +0.02 to +0.04 for 2-5, and whitening turns down the variation inside one
    artist, so it is an option for galleries, not the default."""
    from styleatlas.whiten import whiten

    grouped = cluster_styles(whiten(style, keep=False), threshold=ARTISTS_CUT, min_size=min_size)
    out = from_labels(style, grouped.labels, ARTISTS)
    return Clustering(out.labels, out.clusters, ARTISTS, grouped.params | {"space": "whitened"})


def from_labels(x: np.ndarray, labels: np.ndarray, method: str) -> Clustering:
    """Groups given as integer labels (e.g. sub-folders; UNASSIGNED left out), renumbered by
    size with their medoids and spreads."""
    return _finish(x, np.asarray(labels, dtype=int), method, {}, min_size=1)


@dataclass(frozen=True)
class Fit:
    group: int  # id of the closest group (by centre)
    dist: float  # cosine distance to that centre
    fits: bool  # as close as FIT_PERCENTILE% of the group's own images (left out in turn)
    limit: float = 0.0  # the distance within which an image fits that group


def fit_to_groups(
    style: np.ndarray,
    clustering: Clustering,
    query: np.ndarray,
    skip: set[int] | frozenset[int] = frozenset(),
    percentile: float = FIT_PERCENTILE,
) -> list[Fit]:
    """Where each query row would go: its closest group of FIT_MIN or more images (rows in
    `skip`, e.g. excluded by hand, left out of the groups), and whether it is as close to the
    centre as `percentile`% of the group's own images are to the centre of the others. Leaving
    each member out keeps the limit fair for small groups: measured against the full centre, a
    group of 5 let only 11% of its artist's new works fit. Plain CSD in (`style` the grouped
    rows, `query` the new ones); placed in the search whitening's space (docs/BENCHMARKS.md,
    "Sorting new images into a dataset"). Judge a batch by its share."""
    from styleatlas.whiten import whiten

    x, query = whiten(style), whiten(query, keep=False)
    groups = []
    for c in clustering.clusters:
        members = np.array([m for m in c.members if m not in skip], dtype=int)
        if len(members) >= FIT_MIN:
            groups.append((c.id, members))
    if not groups or not len(query):
        return []
    cents = np.stack([centroid(x[m]) for _, m in groups])
    limits = [float(np.percentile(_left_out_distances(x[m]), percentile)) for _, m in groups]
    out = []
    for row in query @ cents.T:
        k = int(np.argmax(row))
        dist = 1.0 - float(row[k])
        out.append(Fit(groups[k][0], dist, dist <= limits[k], limits[k]))
    return out


def _left_out_distances(rows: np.ndarray) -> np.ndarray:
    """Each row's cosine distance to the centre of the other rows."""
    rest = rows.sum(axis=0)[None] - rows
    rest /= np.maximum(np.linalg.norm(rest, axis=1, keepdims=True), 1e-12)
    return 1.0 - (rows * rest).sum(axis=1)


def batch_verdict(share: float, n: int) -> str:
    """How to read the share of a batch of `n` new images that fits: "few" (under BATCH_MIN
    images, too noisy to say), "in" (mostly the folder's styles), "some" or "out" (mostly
    unlike them). docs/BENCHMARKS.md, "Sorting new images into a dataset"."""
    if n < BATCH_MIN:
        return "few"
    if share > BATCH_IN:
        return "in"
    return "out" if share <= BATCH_OUT else "some"


def keep_rows(x: np.ndarray, clustering: Clustering, kept: np.ndarray | list[int]) -> Clustering:
    """The clustering of the rows `kept` only (`x`: the vectors of all rows), re-indexed to
    them. Group ids stay as they are, so names and "Style N" still match the full set; groups
    left with no rows are dropped."""
    kept = np.asarray(kept, dtype=int)
    labels = clustering.labels[kept]
    sub = x[kept]
    clusters = [
        _info(sub, c.id, members)
        for c in clustering.clusters
        if len(members := np.flatnonzero(labels == c.id))
    ]
    return Clustering(labels, clusters, clustering.method, clustering.params)


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
        raise ValueError(tr("a group needs at least 2 images to be split", "至少要 2 張圖才能拆群"))
    halves = cluster_styles(x[members], n_clusters=2, min_size=1).labels
    if len(set(halves.tolist())) < 2:
        raise ValueError(tr("these images are too alike to split", "這些圖太像了，拆不開"))
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
