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
    whole = _img(tmp_path / "cut.png", (64, 64)).read_bytes()
    (tmp_path / "cut.png").write_bytes(whole[: len(whole) - 20])
    paths = sorted(tmp_path.glob("*.png"))
    report = audit(paths, min_side=512)
    s = report["summary"]
    assert s["images"] == 5 and s["unreadable"] == 1 and s["truncated"] == 1
    assert s["smaller_than_min_side"] == 2 and s["extreme_aspect_ratio"] == 1
    assert s["no_caption"] == 2 and s["empty_caption"] == 1
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


def test_repeats_must_be_auto_or_a_positive_whole_number(tmp_path):
    import pytest

    from styleatlas.dataset import parse_repeats

    assert parse_repeats("auto") is None and parse_repeats("10") == 10
    for bad in ("0", "-3", "abc", "2.5"):
        with pytest.raises(ValueError):
            parse_repeats(bad)


def test_keeper_avoids_excluded_copies(tmp_path):
    big = _img(tmp_path / "big.png", (256, 256))
    small = _img(tmp_path / "small.png", (64, 64))
    assert best_in_group([big, small]) == 0
    assert best_in_group([big, small], blocked={0}) == 1
    x, _ = make_blobs([2, 3])
    paths = [big, small] + [_img(tmp_path / f"o{i}.png") for i in range(3)]
    result = cluster_styles(x, min_size=1)
    folders = plan_folders(paths, result, duplicate_groups=[[0, 1]], excluded=[0])
    assert folders[0] == "_excluded" and folders[1] != "_duplicates"  # the picture survives


def test_duplicate_chains_do_not_swallow_distinct_images():
    from styleatlas.duplicates import near_duplicate_groups
    from styleatlas.metrics import unit

    rng = np.random.default_rng(3)
    a, b = unit(rng.normal(size=(2, 768)))
    steps = [unit(a * (1 - t) + b * t) for t in np.linspace(0, 1, 12)]  # gradual morph a -> b
    x = np.vstack(steps)
    groups = near_duplicate_groups(x, x, threshold=0.95)
    for g in groups:
        sims = x[g] @ x[g].T
        assert sims.min() >= 0.95 - 1e-6  # every pair in a group is a near-duplicate
    assert not any({0, 11} <= set(g) for g in groups)  # the two ends are never "duplicates"


def test_truncation_check_tolerates_trailers(tmp_path):
    from styleatlas.dataset import image_info

    good = _img(tmp_path / "trailer.png", (64, 64))
    good.write_bytes(good.read_bytes() + b"\x00" * 500 + b"EXTRA-METADATA" * 20)
    assert image_info(good).truncated is False


def test_group_names_in_folder_plans(tmp_path):
    import pytest

    from styleatlas.dataset import clean_group_name

    x, _ = make_blobs([4, 4])
    paths = [_img(tmp_path / f"i{i}.png") for i in range(8)]
    result = cluster_styles(x, min_size=2)
    folders = plan_folders(paths, result, "kohya", "a", "3", group_names={0: "early"})
    assert set(folders) == {"3_a_early", "3_a_style02"}
    assert clean_group_name('a<b>:c"d/e') == "a_b__c_d_e"
    with pytest.raises(ValueError):
        clean_group_name(" ..// ")


def test_group_names_are_safe_on_windows_and_unique():
    from styleatlas.dataset import clean_group_name

    assert clean_group_name("CON") == "CON_" and clean_group_name("nul.txt") == "nul_.txt"
    assert clean_group_name("com1") == "com1_" and clean_group_name("console") == "console"
    assert clean_group_name("a" * 59 + ".b").endswith("a")  # no trailing dot after the cut
    assert clean_group_name("early, sketch") == "early_ sketch"


def test_duplicate_names_get_distinct_folders(tmp_path):
    x, _ = make_blobs([4, 4, 4])
    paths = [_img(tmp_path / f"i{i}.png") for i in range(12)]
    result = cluster_styles(x, min_size=2)
    names = {0: "Early", 1: "early", 2: "unassigned"}
    plain = set(plan_folders(paths, result, "plain", group_names=names))
    assert plain == {"Early", "early_2", "unassigned_2"}
    kohya = set(plan_folders(paths, result, "kohya", "a", "3", group_names={0: "style02"}))
    assert kohya == {"3_a_style02", "3_a_style02_2", "3_a_style03"}
