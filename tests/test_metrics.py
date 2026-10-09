from __future__ import annotations

from pathlib import Path

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


def test_neutralizer_removes_a_dominant_subject_axis():
    from styleatlas.metrics import Neutralizer

    rng = np.random.default_rng(0)
    styles = unit(rng.normal(size=(20, 768)))
    subject = unit(rng.normal(size=(1, 768)))[0] * 3.0  # two subjects far apart on one axis
    x = unit(np.vstack([styles + subject, styles - subject]))  # style i = rows i and i + 20
    style_id = np.r_[np.arange(20), np.arange(20)]

    def twin_rate(v):
        s = v @ v.T
        np.fill_diagonal(s, -np.inf)
        return float(np.mean(style_id[s.argmax(1)] == style_id))

    assert twin_rate(x) < 0.1  # before: nearest neighbour = same subject, other style
    n = Neutralizer.fit(x, 1)
    assert twin_rate(n.apply(x)) > 0.9
    assert np.allclose(np.linalg.norm(n.apply(x), axis=1), 1.0, atol=1e-5)
    assert Neutralizer.fit(x, 0).apply(x) is x


def test_cli_reference_uses_the_folders_neutralizer(monkeypatch, tmp_path):
    import argparse

    from styleatlas import cli
    from styleatlas.atlas import Atlas

    rng = np.random.default_rng(1)
    folder = unit(rng.normal(size=(12, 768)))
    ref = unit(rng.normal(size=(4, 768)))
    fake = {
        "folder": Atlas(tmp_path, [tmp_path / f"f{i}.png" for i in range(12)], folder, folder, "s"),
        "ref": Atlas(tmp_path, [tmp_path / f"r{i}.png" for i in range(4)], ref, ref, "s"),
    }
    monkeypatch.setattr(cli, "build_atlas", lambda root, *a, **k: fake[Path(root).name])
    monkeypatch.setattr(cli, "_opts", lambda a: None)
    args = argparse.Namespace(neutralize=1, reference="ref", no_recursive=False)
    atlas = cli._atlas(args, "folder")
    got = cli._reference(args)
    assert np.allclose(got.style, args.neutralizer.apply(ref))
    assert not np.allclose(atlas.style, folder)


def test_neighbor_density_reuses_only_the_same_arrays():
    from styleatlas.metrics import neighbor_density

    from .conftest import make_blobs

    x, _ = make_blobs([10, 10])
    first = neighbor_density(x, x, same_set=True)
    first[:] = -1  # callers may change what they get back
    again = neighbor_density(x, x, same_set=True)
    assert (again > 0).all()
    other = x.copy()
    other[0] = -other[0]
    assert not np.allclose(neighbor_density(other, other, same_set=True), again)
