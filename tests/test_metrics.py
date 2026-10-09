from __future__ import annotations

import numpy as np
import pytest

from styleatlas.metrics import (
    StyleScale,
    centroid,
    cosine_distance,
    group_difference,
    hub_distance,
    neighbor_density,
    split_half_noise,
    unit,
)


def test_unit_rows_have_norm_one():
    x = unit(np.array([[3.0, 4.0], [0.0, 2.0]]))
    assert np.allclose(np.linalg.norm(x, axis=1), 1.0)


def test_neighbor_density_excludes_self(blobs):
    x, _ = blobs
    r = neighbor_density(x, x, k=3, same_set=True)
    assert r.shape == (len(x),)
    assert (r < 0.999).all()  # self-similarity (1.0) never counted


def test_hub_distance_is_symmetric_nonnegative_zero_diagonal(blobs):
    x, _ = blobs
    d = hub_distance(x)
    assert np.allclose(d, d.T)
    assert (d >= 0).all()
    assert np.allclose(np.diag(d), 0.0)


def test_hub_distance_keeps_groups_apart(blobs):
    x, y = blobs
    d = hub_distance(x)
    same = y[:, None] == y[None, :]
    off = ~np.eye(len(y), dtype=bool)
    assert d[same & off].mean() < d[~same].mean()


def test_tiny_sets_fall_back_to_cosine():
    x = unit(np.eye(2, 5))
    assert np.allclose(hub_distance(x), cosine_distance(x))


def test_style_scale_verdicts():
    s = StyleScale(noise_floor=0.1)
    assert s.z(0.23) == pytest.approx(2.3)
    assert s.verdict(0.1) == "same style"
    assert s.verdict(0.2) == "related"
    assert s.verdict(0.3) == "clearly different"


def test_group_difference_detects_different_styles(blobs):
    x, y = blobs
    dist, p = group_difference(x[y == 0], x[y == 1], rounds=199)
    assert dist > 0.5
    assert p < 0.01


def test_group_difference_same_style_is_not_significant(blobs):
    x, y = blobs
    a = x[y == 0]
    _, p = group_difference(a[:10], a[10:], rounds=199)
    assert p > 0.05


def test_split_half_noise_is_small_within_one_style(blobs):
    x, y = blobs
    within = split_half_noise(x[y == 0], rounds=50)
    between = 1.0 - float(centroid(x[y == 0]) @ centroid(x[y == 1]))
    assert within < between / 5


def test_split_half_noise_needs_four_images():
    with pytest.raises(ValueError):
        split_half_noise(unit(np.eye(3, 8)))
