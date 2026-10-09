from __future__ import annotations

import numpy as np
from PIL import Image

from styleatlas.cluster import cluster_styles
from styleatlas.dataset import audit, auto_repeats, best_in_group, plan_folders, tag_summary

from .conftest import make_blobs


def _img(path, size=(64, 64)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (90, 90, 90)).save(path)
    return path


def test_kohya_plan_names_repeats_and_set_aside(tmp_path):
    x, _ = make_blobs([10, 5, 2])
    paths = [_img(tmp_path / f"i{i}.png") for i in range(len(x))]
    result = cluster_styles(x, min_size=3)
    folders = plan_folders(paths, result, "kohya", "artistX", "auto", [[0, 1]], [12])
    assert folders[0] in {"_duplicates", folders[2]} and folders[1] in {"_duplicates", folders[2]}
    assert folders.count("_duplicates") == 1
    assert folders[12] == "_outliers"
    assert folders[15] == "_unassigned"  # the 2-image group is below min_size
    style_dirs = {f for f in folders if not f.startswith("_")}
    # group 1 keeps 9 of 10 (one duplicate set aside), group 2 keeps 4 of 5 (one outlier)
    assert style_dirs == {"11_artistX_style01", "25_artistX_style02"}


def test_plain_plan_and_fixed_repeats(tmp_path):
    x, _ = make_blobs([4, 4])
    paths = [_img(tmp_path / f"i{i}.png") for i in range(8)]
    result = cluster_styles(x, min_size=2)
    assert set(plan_folders(paths, result)) == {"style_01", "style_02"}
    assert set(plan_folders(paths, result, "kohya", "a", "3")) == {"3_a_style01", "3_a_style02"}
    assert auto_repeats(1000) == 1


def test_best_copy_is_largest_then_captioned(tmp_path):
    small = _img(tmp_path / "small.png", (64, 64))
    big = _img(tmp_path / "big.png", (128, 128))
    assert best_in_group([small, big]) == 1
    same = _img(tmp_path / "same.png", (64, 64))
    (tmp_path / "same.txt").write_text("1girl")
    assert best_in_group([small, same]) == 1


def test_tag_summary_finds_distinctive_tags(tmp_path):
    x, y = make_blobs([5, 5])
    paths = []
    for i in range(10):
        p = _img(tmp_path / f"i{i}.png")
        p.with_suffix(".txt").write_text(
            "1girl, " + ("monochrome, sketch" if y[i] == 0 else "color")
        )
        paths.append(p)
    result = cluster_styles(x, min_size=2)
    tags = tag_summary(paths, result)
    first = {r["tag"] for r in tags[0][:2]}
    second = {r["tag"] for r in tags[1][:2]}
    assert {"monochrome", "sketch"} <= first or {"monochrome", "sketch"} <= second
    lifts = {r["tag"]: r["lift"] for rows in tags.values() for r in rows}
    assert lifts["1girl"] == 1.0 and lifts["color"] == 2.0


def test_audit_flags_problems(tmp_path):
    _img(tmp_path / "ok.png", (768, 768)).with_suffix(".txt").write_text("1girl")
    _img(tmp_path / "small.png", (300, 300))
    _img(tmp_path / "strip.png", (2000, 600)).with_suffix(".txt").write_text("")
    (tmp_path / "broken.png").write_bytes(b"not an image")
    paths = sorted(tmp_path.glob("*.png"))
    report = audit(paths, min_side=512)
    s = report["summary"]
    assert s["images"] == 4 and s["unreadable"] == 1
    assert s["smaller_than_min_side"] == 1 and s["extreme_aspect_ratio"] == 1
    assert s["no_caption"] == 1 and s["empty_caption"] == 1
    assert np.isclose(s["short_side_median"], 600)


def test_groups_shrunk_below_min_size_become_unassigned(tmp_path):
    x, _ = make_blobs([6, 3])
    paths = [_img(tmp_path / f"i{i}.png") for i in range(9)]
    result = cluster_styles(x, min_size=3)
    folders = plan_folders(paths, result, "kohya", "a", "auto", outliers=[6], min_size=3)
    assert folders[7] == folders[8] == "_unassigned"  # 3 - 1 outlier = 2 < 3


def test_expand_clustering_reindexes_to_the_full_set():
    from styleatlas.cluster import UNASSIGNED, expand_clustering

    x, _ = make_blobs([5, 5])
    kept = np.array([0, 1, 2, 3, 5, 6, 7, 8])
    full = expand_clustering(cluster_styles(x[kept], min_size=2), kept, 10)
    assert full.labels[4] == UNASSIGNED and full.labels[9] == UNASSIGNED
    assert all(m in kept for c in full.clusters for m in c.members)
    assert all(c.medoid in c.members for c in full.clusters)
