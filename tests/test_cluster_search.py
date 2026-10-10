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


def test_near_duplicates_are_grouped_and_reduced():
    from styleatlas.duplicates import keep_one_per_group, near_duplicate_groups
    from styleatlas.metrics import unit

    x, _ = make_blobs([6, 6])
    twin = unit(x[0] + 0.01 * x[1])  # almost the same picture as x[0]
    style = np.vstack([x, twin])
    groups = near_duplicate_groups(style, style, threshold=0.99)
    assert groups == [[0, 12]]
    assert len(keep_one_per_group(len(style), groups)) == 12
    other, _ = make_blobs([13], seed=5)
    other = unit(np.random.default_rng(1).normal(size=other.shape))  # unrelated content
    assert near_duplicate_groups(style, other, threshold=0.99) == []  # content must agree too


def test_nearest_reference_distance_and_index():
    from styleatlas.search import nearest_reference

    x, y = make_blobs([5, 5])
    ref = x[[0, 5]]
    dist, which = nearest_reference(x, ref, chunk=3)
    assert (which == (y == 1).astype(int)).all()
    assert dist[0] < 1e-5 and (dist >= -1e-6).all()


def test_edit_groups_merges_moves_and_renumbers():
    from styleatlas.cluster import edit_groups

    x, _ = make_blobs([8, 5, 3])
    result = cluster_styles(x, min_size=1)
    small = result.clusters[-1]
    merged = edit_groups(x, result, {i: result.clusters[0].id for i in small.members})
    assert merged.n_clusters == result.n_clusters - 1
    assert merged.clusters[0].size == result.clusters[0].size + small.size
    moved = edit_groups(x, merged, {0: UNASSIGNED})
    assert moved.labels[0] == UNASSIGNED
    assert all(c.medoid in c.members for c in moved.clusters)
    assert moved.params["edited"] is True


def test_style_path_walks_from_a_to_b_without_repeats():
    from styleatlas.search import style_path

    x, y = make_blobs([6, 6, 6])
    path = style_path(x, 0, 6, steps=5)
    assert path[0] == 0 and path[-1] == 6
    assert len(path) == len(set(path)) == 7
    assert style_path(x, 3, 3) == [3]


def test_style_path_skips_excluded_and_survives_bad_rows():
    from styleatlas.search import style_path

    x, _ = make_blobs([6, 6])
    x = x.copy()
    x[3] = np.nan
    path = style_path(x, 0, 6, steps=6, skip={1})
    assert 1 not in path and 3 not in path and path[-1] == 6
    assert style_path(x, 0, 0) == [0]


def test_large_sets_join_micro_groups_and_keep_the_threshold(monkeypatch):
    from sklearn.metrics import adjusted_rand_score

    import styleatlas.cluster as cluster

    monkeypatch.setattr(cluster, "MAX_DENSE", 30)  # 120 images > 30: the micro-group path
    x, labels = make_blobs([40, 30, 30, 20])
    result = cluster_styles(x, threshold=0.5)
    assert "micro-groups" in result.params["note"]
    assert adjusted_rand_score(labels, result.labels) > 0.9
    assert cluster_styles(x, n_clusters=2).n_clusters == 2
    assert cluster_styles(x, threshold=1.4).n_clusters == 1  # a coarse cut still merges
    runs = []
    real = cluster.MiniBatchKMeans
    monkeypatch.setattr(cluster, "MiniBatchKMeans", lambda **kw: runs.append(kw) or real(**kw))
    cluster_styles(x, threshold=0.3)  # same set, new threshold: the cached tree is cut again
    cluster_styles(x[:100], threshold=0.3)  # another set: k-means runs
    assert len(runs) == 1


def test_a_set_of_examples_learns_a_style_with_two_looks():
    x, y = make_blobs([20, 20, 20, 20])
    examples = [0, 1, 2, 20, 21, 22]  # one style, drawn in two looks (groups 0 and 1)
    hits = search(x[examples], x, top=30, combine=True, exclude=set(examples))[0]
    assert not {h.index for h in hits} & set(examples)
    assert all(y[h.index] in (0, 1) for h in hits[:30])
    assert any(abs(h.score - h.cosine) > 1e-3 for h in hits)  # ranked by the learned logit


def test_matches_are_copied_with_captions_once(tmp_path):
    from PIL import Image

    from styleatlas.atlas import Atlas
    from styleatlas.cli import _copy_matches

    x, _ = make_blobs([3])
    paths = []
    for i in range(3):
        p = tmp_path / "lib" / f"m{i}.png"
        p.parent.mkdir(exist_ok=True)
        Image.new("RGB", (8, 8)).save(p)
        p.with_suffix(".txt").write_text(f"tag{i}", encoding="utf-8")
        paths.append(p)
    _copy_matches(Atlas(tmp_path / "lib", paths, x, x, "sig"), [2, 0, 2], tmp_path / "out")
    got = sorted(f.name for f in (tmp_path / "out" / "matches").iterdir())
    assert got == ["m0.png", "m0.txt", "m2.png", "m2.txt"]


def test_without_a_threshold_the_cut_is_chosen_from_the_data():
    from sklearn.metrics import adjusted_rand_score

    x, labels = make_blobs([6] * 30, spread=0.9)  # many small, looser styles
    auto = cluster_styles(x)
    assert auto.params["auto"] and auto.params["threshold"] <= 0.47
    assert adjusted_rand_score(labels, auto.labels) > 0.8
    fixed = cluster_styles(x, threshold=0.47)
    assert fixed.params["auto"] is False and fixed.params["threshold"] == 0.47


def test_stacks_of_copies_do_not_drag_the_automatic_cut_down():
    from styleatlas.metrics import unit

    x, _ = make_blobs([12, 12, 12], spread=0.9)
    rng = np.random.default_rng(3)
    copies = unit(np.repeat(x, 4, axis=0) + rng.normal(size=(len(x) * 4, x.shape[1])) * 0.01)
    alone = cluster_styles(x).params["threshold"]
    stacked = cluster_styles(np.vstack([x, copies])).params["threshold"]
    assert stacked >= alone - 0.02  # without the guard the copies pulled it to 0.24


def test_identical_images_cannot_be_split():
    from styleatlas.cluster import split_group

    x = np.tile(make_blobs([1])[0], (5, 1))
    with pytest.raises(ValueError, match="too alike"):
        split_group(x, cluster_styles(x, min_size=1), 0)


def test_periods_put_every_image_into_one_of_k_groups():
    x, _ = make_blobs([20, 15, 3])
    result = cluster_styles(x, method="kmeans", n_clusters=3)
    assert result.n_clusters == 3 and result.n_unassigned == 0
    assert cluster_styles(x, method="kmeans").n_clusters == 3  # the default number of periods


def test_whitening_keeps_unit_vectors_and_search_can_skip_it(blobs):
    from styleatlas.whiten import whiten

    x, y = blobs
    w = whiten(x)
    assert w.shape == x.shape and np.allclose(np.linalg.norm(w, axis=1), 1.0, atol=1e-4)
    plain = search(x[:1], x, top=5, exclude={0}, whitened=False)[0]
    white = search(x[:1], x, top=5, exclude={0})[0]
    assert all(y[h.index] == y[0] for h in plain + white)
    plain_cos = {round(float(x[0] @ x[i]), 5) for i in range(len(x))}
    assert {round(h.cosine, 5) for h in white} <= plain_cos  # shown cosine stays plain CSD


def test_rank_folders_names_the_folder_and_its_closest_image():
    from styleatlas.search import rank_folders

    x, labels = make_blobs([8, 8, 8], seed=3)
    folders = [f"artist{k}" for k in labels]
    query = x[[9]]  # a work of artist1
    hits = rank_folders(query, x, folders, top=3, exclude={9})[0]
    assert [h.folder for h in hits][0] == "artist1" and len(hits) == 3
    assert hits[0].size == 7  # the query itself is left out
    assert labels[hits[0].best] == 1 and hits[0].best != 9
    assert hits[0].score > hits[1].score
    both = rank_folders(x[[0, 1, 2]], x, folders, combine=True)
    assert len(both) == 1 and both[0][0].folder == "artist0"
    assert rank_folders(query, x, folders, exclude=set(range(len(x)))) == [[]]
    loose = ["" if k == 2 else f for k, f in zip(labels, folders, strict=True)]  # top-level files
    assert {h.folder for h in rank_folders(query, x, loose, top=5)[0]} == {"artist0", "artist1"}


def test_a_large_library_is_whitened_once_and_kept_read_only():
    from styleatlas.whiten import CACHE_ROWS, whiten

    x, _ = make_blobs([CACHE_ROWS // 2, CACHE_ROWS // 2])
    first = whiten(x)
    assert whiten(x) is first and not first.flags.writeable
    assert whiten(x.copy()) is not first  # another array: computed again
    np.testing.assert_allclose(whiten(x.copy()), first)
    small = x[:10]
    assert whiten(small) is not whiten(small)  # queries are not kept


def test_copies_of_handles_empty_sets_and_one_off_whitening_is_not_kept():
    from styleatlas.duplicates import copies_of
    from styleatlas.whiten import CACHE_ROWS, whiten

    x, _ = make_blobs([4])
    assert copies_of(x, x, x[:0], x[:0]) == [] and copies_of(x[:0], x[:0], x, x) == []
    assert [(q, i) for q, i, _ in copies_of(x[:2], x[:2], x, x)] == [(0, 0), (1, 1)]
    big, _ = make_blobs([CACHE_ROWS])
    assert whiten(big, keep=False) is not whiten(big, keep=False)


def test_fold_copies_keeps_the_first_of_each_picture():
    from styleatlas.duplicates import fold_copies

    x, _ = make_blobs([3, 3], spread=0.01)  # two pictures, three near-copies each
    kept, folded = fold_copies([0, 3, 1, 4, 2], x, x)
    assert kept == [0, 3] and folded == 3
