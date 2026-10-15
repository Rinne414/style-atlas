"""Periods along the timeline: contiguous cuts where the style changes, and their test."""

from __future__ import annotations

import numpy as np
import pytest

from styleatlas.cluster import UNASSIGNED
from styleatlas.timeline import cluster_timeline, on_edge, segment, verdict


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
    assert verdict(result.params) == "turns" and result.params["separation"] > 0.3


def test_no_era_when_the_style_does_not_follow_time():
    x = _styles([12, 9, 15])
    times = np.random.default_rng(1).permutation(len(x)).astype(float)
    assert verdict(cluster_timeline(x, times, 3).params) == "none"


def test_smooth_drift_is_told_from_turns():
    # the style moves steadily along one direction: it follows time, but has no turning point
    rng = np.random.default_rng(2)
    n, d = 80, 32
    t = np.linspace(0, 1, n)[:, None]
    x = 3 * np.eye(1, d) + 2 * t * np.eye(1, d, 1) + 0.5 * rng.normal(size=(n, d))
    params = cluster_timeline(x, np.arange(n, dtype=float), 3).params
    assert params["p_time"] < 0.05 and verdict(params) == "drift"


def test_a_single_turn_is_told_from_drift():
    # one abrupt change halfway: a quadratic trend cannot explain it
    rng = np.random.default_rng(3)
    n, d = 60, 64
    step = (np.arange(n) >= n // 2)[:, None] * 6 * np.eye(1, d)
    params = cluster_timeline(step + rng.normal(size=(n, d)), np.arange(n, dtype=float), 3).params
    assert verdict(params) == "turns"


def test_a_series_of_alike_neighbours_is_not_a_time_effect():
    # no change over time, but each work is a bit like the one before (series posted together):
    # plain shuffles of such works made pure noise look time-dependent
    rng = np.random.default_rng(4)
    n, d, phi = 60, 64, 0.4
    x = np.empty((n, d))
    x[0] = rng.normal(size=d)
    for i in range(1, n):
        x[i] = phi * x[i - 1] + np.sqrt(1 - phi**2) * rng.normal(size=d)
    assert verdict(cluster_timeline(x, np.arange(n, dtype=float), 3).params) == "none"


def test_a_series_of_alike_consecutive_works_counts_once():
    x = _styles([12, 9, 15])
    rng = np.random.default_rng(5)
    series = x[5] + 0.1 * rng.normal(size=(5, 32))  # cosine about 0.87 to x[5]: alike, no copy
    style = np.vstack([x[:6], series / np.linalg.norm(series, axis=1, keepdims=True), x[6:]])
    alone = cluster_timeline(x, np.arange(len(x), dtype=float), 3).params["distinct"]
    result = cluster_timeline(style, np.arange(len(style), dtype=float), 3)
    assert result.params["distinct"] == alone  # the five count as the work they follow
    assert sum(c.size for c in result.clusters) == len(style)  # and are still in a period


def test_too_few_distinct_works_are_not_tested():
    x = _styles([8, 8, 8])
    params = cluster_timeline(x, np.arange(24, dtype=float), 3).params
    assert params["p_time"] is None and verdict(params) == "few"


def test_mostly_copies_of_a_few_pictures_are_not_tested():
    # 13 pictures, each posted 4 times in a row: the copies would make any cut look real
    x = np.repeat(_styles([5, 4, 4]), 4, axis=0)
    params = cluster_timeline(x, np.arange(len(x), dtype=float), 3, content=x).params
    assert params["distinct"] == 13 and verdict(params) == "few"


def test_near_duplicates_count_once_and_take_the_period_of_their_time():
    x = _styles([12, 9, 15])
    copies = np.repeat(x[11:12], 6, axis=0)  # six re-posts of the last early work, all at once
    style = np.vstack([x[:12], copies, x[12:]])
    result = cluster_timeline(style, np.arange(len(style), dtype=float), 3, content=style)
    assert [c.size for c in result.clusters] == [18, 9, 15]


def test_large_folders_cut_on_a_sample_and_stay_contiguous(monkeypatch):
    import styleatlas.timeline as tl

    monkeypatch.setattr(tl, "SEGMENT_MAX", 20)
    x = _styles([30, 25, 35])
    result = cluster_timeline(x, np.arange(90, dtype=float), 3)
    assert (np.diff(result.labels) >= 0).all()  # each period one stretch of time
    assert abs(result.clusters[0].size - 30) <= 3 and abs(result.clusters[2].size - 35) <= 3


def test_tied_times_are_reported():
    x = _styles([12, 9, 15])
    times = np.repeat(np.arange(12, dtype=float), 3)  # three images per time stamp
    assert cluster_timeline(x, times, 3).params["tied"] == pytest.approx(0.67, abs=0.01)


def test_images_without_a_time_are_unassigned():
    x = _styles([10, 10, 10])
    times = np.arange(30, dtype=float)
    times[[3, 17]] = np.nan
    result = cluster_timeline(x, times, 3)
    assert (result.labels[[3, 17]] == UNASSIGNED).all() and result.n_unassigned == 2
    with pytest.raises(ValueError):
        cluster_timeline(x[:12], np.arange(12, dtype=float), 3)  # 3 periods of 5 need 15


def test_a_verdict_decided_near_the_line_is_flagged():
    assert on_edge({"p_time": 0.05, "p_turns": 0.5}) == "weak_link"  # "none" by p_time
    assert on_edge({"p_time": 0.01, "p_turns": 0.04}) == "maybe_drift"  # "turns" by p_turns
    assert on_edge({"p_time": 0.04, "p_turns": 0.5}) == "barely_time"  # "drift", nearly "none"
    assert on_edge({"p_time": 0.01, "p_turns": 0.06}) == "maybe_turn"  # "drift", nearly "turns"
    assert on_edge({"p_time": 0.4, "p_turns": 0.9}) is None
    assert on_edge({"p_time": None, "p_turns": None}) is None  # "few"
