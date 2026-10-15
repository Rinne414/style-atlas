"""Periods along the timeline: contiguous cuts where the style changes, and their test."""

from __future__ import annotations

import numpy as np
import pytest

from styleatlas.cluster import UNASSIGNED
from styleatlas.timeline import cluster_timeline, segment


def _styles(sizes, spread=0.15, seed=0):
    rng = np.random.default_rng(seed)
    centres = np.eye(len(sizes), 32)
    x = np.vstack(
        [c + spread * rng.normal(size=(n, 32)) for c, n in zip(centres, sizes, strict=True)]
    )
    return x / np.linalg.norm(x, axis=1, keepdims=True)


def test_segment_cuts_where_the_style_changes():
    x = _styles([12, 9, 15])
    assert segment(x, 3, 5).tolist() == [0] * 12 + [1] * 9 + [2] * 15


def test_periods_follow_time_and_are_tested():
    x = _styles([12, 9, 15])
    times = np.arange(len(x), dtype=float)[::-1]  # newest first on disk: time order is reversed
    result = cluster_timeline(x[::-1], times, 3)
    assert [c.size for c in result.clusters] == [12, 9, 15]  # numbered earliest first
    assert result.params["p"] < 0.05 and result.params["separation"] > 0.3


def test_no_era_when_the_style_does_not_follow_time():
    x = _styles([12, 9, 15])
    times = np.random.default_rng(1).permutation(len(x)).astype(float)
    assert cluster_timeline(x, times, 3).params["p"] > 0.05


def test_images_without_a_time_are_unassigned():
    x = _styles([10, 10, 10])
    times = np.arange(30, dtype=float)
    times[[3, 17]] = np.nan
    result = cluster_timeline(x, times, 3)
    assert (result.labels[[3, 17]] == UNASSIGNED).all() and result.n_unassigned == 2
    with pytest.raises(ValueError):
        cluster_timeline(x[:12], np.arange(12, dtype=float), 3)  # 3 periods of 5 need 15
