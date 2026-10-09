from __future__ import annotations

import numpy as np
import pytest
from sklearn.metrics import adjusted_rand_score

from styleatlas.cluster import UNASSIGNED, cluster_styles, outlier_scores
from styleatlas.metrics import hub_scores
from styleatlas.search import knn, search

from .conftest import make_blobs


@pytest.mark.parametrize("method", ["agglomerative", "hdbscan"])
def test_recovers_synthetic_styles(blobs, method):
    x, y = blobs
    result = cluster_styles(x, method=method)
    assigned = result.labels != UNASSIGNED
    assert assigned.mean() > 0.8
    assert adjusted_rand_score(y[assigned], result.labels[assigned]) > 0.95


def test_clusters_are_numbered_by_size(blobs):
    x, _ = blobs
    result = cluster_styles(x)
    sizes = [c.size for c in result.clusters]
    assert sizes == sorted(sizes, reverse=True)
    assert [c.id for c in result.clusters] == list(range(len(sizes)))


def test_forced_cluster_count(blobs):
    x, _ = blobs
    assert cluster_styles(x, n_clusters=2, min_size=1).n_clusters == 2


def test_small_groups_become_unassigned():
    x, _ = make_blobs([12, 2])
    result = cluster_styles(x, min_size=3)
    assert result.n_clusters == 1
    assert result.n_unassigned == 2


def test_medoid_belongs_to_its_cluster(blobs):
    x, _ = blobs
    for c in cluster_styles(x).clusters:
        assert c.medoid in c.members


def test_single_image_does_not_crash():
    x, _ = make_blobs([1])
    assert cluster_styles(x).labels.tolist() == [0]


def test_outlier_scores_flag_the_odd_one():
    x, _ = make_blobs([20, 1])
    assert int(np.argmax(outlier_scores(x))) == 20


def test_knn_matches_brute_force(blobs):
    x, _ = blobs
    got = knn(x, k=5, chunk=7)  # small chunk exercises the chunk boundaries
    scores = hub_scores(x, x)
    np.fill_diagonal(scores, -np.inf)
    want = np.argsort(-scores, axis=1)[:, :5]
    assert (got == want).all()


def test_chunked_density_matches_dense(blobs, monkeypatch):
    from styleatlas import metrics

    x, _ = blobs
    sims = x @ x.T
    np.fill_diagonal(sims, -np.inf)
    dense = np.sort(sims, axis=1)[:, -10:].mean(axis=1)
    monkeypatch.setattr(metrics, "CHUNK", 7)  # exercise the block boundaries
    assert np.allclose(metrics.neighbor_density(x, x, k=10, same_set=True), dense, atol=1e-6)


def test_one_image_gallery_still_returns_a_hit():
    x, _ = make_blobs([1, 1])
    hits = search(x[:1], x[1:], top=5)[0]
    assert [h.index for h in hits] == [0]


def test_search_finds_same_style_and_honours_exclude(blobs):
    x, y = blobs
    hits = search(x[:1], x, top=5, exclude={0})[0]
    assert 0 not in [h.index for h in hits]
    assert all(y[h.index] == y[0] for h in hits)


def test_combined_search_returns_one_list(blobs):
    x, _ = blobs
    assert len(search(x[:3], x, top=4, combine=True)) == 1
