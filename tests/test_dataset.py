from __future__ import annotations

from pathlib import Path

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


def test_periods_along_the_timeline_export_as_periods(tmp_path):
    from styleatlas.timeline import cluster_timeline

    x, _ = make_blobs([6, 6])
    paths = [_img(tmp_path / f"i{i}.png") for i in range(12)]
    result = cluster_timeline(x, np.arange(12, dtype=float), 2)
    assert set(plan_folders(paths, result, "kohya", "a", "3")) == {"3_a_period01", "3_a_period02"}


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
    marked = _img(tmp_path / "marked.png", (768, 768)).with_suffix(".txt")
    marked.write_text("1girl, Artist_Name, smile", encoding="utf-8")
    _img(tmp_path / "small.png", (300, 300))
    _img(tmp_path / "strip.png", (2000, 600)).with_suffix(".txt").write_text("")
    (tmp_path / "broken.png").write_bytes(b"not an image")
    whole = _img(tmp_path / "cut.png", (64, 64)).read_bytes()
    (tmp_path / "cut.png").write_bytes(whole[: len(whole) - 20])
    paths = sorted(tmp_path.glob("*.png"))
    report = audit(paths, min_side=512)
    s = report["summary"]
    assert s["images"] == 6 and s["unreadable"] == 1 and s["truncated"] == 1
    assert [Path(f).name for f in report["files"]["watermark_or_signature"]] == ["marked.png"]
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


def test_keep_rows_keeps_group_ids_and_drops_emptied_groups():
    from styleatlas.cluster import edit_groups, keep_rows

    x, _ = make_blobs([6, 4, 2])
    full = edit_groups(x, cluster_styles(x, n_clusters=3, min_size=1), {})
    small = next(c for c in full.clusters if c.size == 2)
    kept = [i for i in range(len(x)) if i not in small.members and i != 0]
    sub = keep_rows(x, full, kept)
    assert len(sub.labels) == len(kept) and sub.labels.tolist() == full.labels[kept].tolist()
    assert sorted(c.id for c in sub.clusters) == sorted(
        c.id for c in full.clusters if c is not small
    )
    assert sum(c.size for c in sub.clusters) == len(kept)
    assert all(c.medoid in c.members and max(c.members) < len(kept) for c in sub.clusters)


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


def test_distinctive_tags_name_what_sets_a_group_apart():
    from styleatlas.dataset import distinctive_tags

    summary = {
        0: [
            {"tag": "1girl", "share": 1.0, "lift": 1.0},
            {"tag": "sketch", "share": 0.8, "lift": 2.5},
        ],
        1: [{"tag": "1girl", "share": 1.0, "lift": 1.0}],
    }
    assert distinctive_tags(summary) == {0: ["sketch"], 1: []}


def test_diverse_subset_covers_a_group_better_than_chance():
    from styleatlas.dataset import diverse_subset
    from styleatlas.metrics import unit

    rng = np.random.default_rng(0)
    centres = unit(rng.normal(size=(6, 64)))  # six sub-styles inside one group, uneven sizes
    rows = np.repeat(np.arange(6), [30, 12, 8, 5, 3, 2])
    x = unit(centres[rows] * 3 + rng.normal(0, 0.3, size=(len(rows), 64)))

    def coverage(picked):  # mean distance from each image to its nearest kept image
        return float(np.mean(1 - (x @ x[picked].T).max(axis=1)))

    picked = diverse_subset(x, 8)
    assert len(set(picked)) == 8 and len({int(rows[i]) for i in picked}) == 6  # every sub-style
    randoms = [coverage(rng.choice(len(x), 8, replace=False)) for _ in range(200)]
    assert coverage(picked) < np.percentile(randoms, 5)
    assert diverse_subset(x[:3], 8) == [0, 1, 2]


def test_a_cap_per_group_trims_the_rest_and_sets_repeats_by_what_is_kept(tmp_path):
    x, y = make_blobs([10, 7])
    paths = [_img(tmp_path / f"i{i}.png") for i in range(len(x))]
    result = cluster_styles(x, min_size=3)
    folders = plan_folders(paths, result, "kohya", "a", "auto", max_per_group=4, style=x)
    kept = [f for f in folders if not f.startswith("_")]
    assert folders.count("_trimmed") == (10 - 4) + (7 - 4)
    assert all(kept.count(f) == 4 for f in set(kept))
    assert all(f.split("_")[0] == str(auto_repeats(4)) for f in kept)


def test_a_cap_below_the_minimum_group_size_keeps_the_groups(tmp_path):
    from styleatlas.dataset import diverse_subset

    x, _ = make_blobs([10, 7])
    paths = [_img(tmp_path / f"i{i}.png") for i in range(len(x))]
    result = cluster_styles(x, min_size=3)
    folders = plan_folders(paths, result, "plain", max_per_group=2, style=x, min_size=3)
    assert "unassigned" not in folders and folders.count("_trimmed") == len(x) - 4
    same = np.tile(x[:1], (6, 1))  # identical rows: still n different picks
    assert sorted(diverse_subset(same, 4)) == sorted(set(diverse_subset(same, 4)))
    assert len(diverse_subset(same, 4)) == 4 and diverse_subset(x, 0) == []


def test_images_fall_into_kohya_buckets():
    from styleatlas.dataset import bucket_counts, bucket_resolutions

    resos = bucket_resolutions()
    assert (1024, 1024) in resos and (704, 1024) in resos and all(max(r) <= 1024 for r in resos)
    counts = bucket_counts([(1024, 1024), (2048, 2048), (832, 1216), (1216, 832), (832, 1216)])
    assert counts == {"704x1024": 2, "1024x1024": 2, "1024x704": 1}


def test_caption_tags_ignore_a_utf8_byte_order_mark(tmp_path):
    from styleatlas.dataset import read_tags

    img = tmp_path / "a.png"
    Image.new("RGB", (8, 8)).save(img)
    img.with_suffix(".txt").write_bytes("\ufeffwatermark, 1girl".encode())  # as Notepad saves
    assert read_tags(img) == ["watermark", "1girl"]


def test_audit_compares_greyscale_tags_with_the_picture(tmp_path):
    from styleatlas.look import LOOK_NAMES

    captions = {
        "a": ("1girl", 0.20),
        "b": ("1girl, smile", 0.15),
        "c": ("1girl", 0.10),
        "grey_tagged": ("1girl, monochrome", 0.0),
        "grey_untagged": ("1girl, sketch", 0.0),
        "tinted": ("1girl, greyscale", 0.05),  # a faint tint: not flagged
        "coloured": ("1girl, Greyscale", 0.12),
        "spot": ("greyscale, spot_color", 0.12),
    }
    paths, looks = [], np.zeros((len(captions), len(LOOK_NAMES)), np.float32)
    for i, (name, (text, colour)) in enumerate(captions.items()):
        paths.append(_img(tmp_path / f"{name}.png", (768, 768)))
        paths[-1].with_suffix(".txt").write_text(text, encoding="utf-8")
        looks[i, LOOK_NAMES.index("colourfulness")] = colour
    files = audit(paths, looks=looks)["files"]
    names = {k: sorted(Path(f).stem for f in v) for k, v in files.items()}
    assert names["greyscale_in_colour_set"] == ["grey_tagged", "grey_untagged"]
    assert names["greyscale_untagged"] == ["grey_untagged"]
    assert names["greyscale_tag_on_colour"] == ["coloured"]


def test_audit_leaves_a_monochrome_artist_alone(tmp_path):
    from styleatlas.look import LOOK_NAMES

    paths = [_img(tmp_path / f"{i}.png", (768, 768)) for i in range(4)]
    for p in paths:
        p.with_suffix(".txt").write_text("1girl", encoding="utf-8")
    looks = np.zeros((4, len(LOOK_NAMES)), np.float32)  # every picture greyscale
    files = audit(paths, looks=looks)["files"]
    assert files["greyscale_in_colour_set"] == [] and files["greyscale_untagged"] == []


def test_audit_flags_pictures_turned_only_by_exif(tmp_path):
    turned = tmp_path / "phone.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # stored sideways, shown turned 90 degrees
    Image.new("RGB", (800, 600), (200, 120, 90)).save(turned, exif=exif)
    _img(tmp_path / "upright.png", (800, 600))
    report = audit(sorted(tmp_path.iterdir()), min_side=512)
    assert [Path(f).name for f in report["files"]["exif_rotated"]] == ["phone.jpg"]
    assert report["summary"]["buckets"]  # sizes as stored, as kohya reads them


def test_audit_finds_a_tag_spelt_two_ways(tmp_path):
    captions = {
        "a": "artistx_style01, 1girl, long hair, blue eyes",
        "b": "1girl, long hair, smile",
        "c": "1girl, long_hair, blue_eyes",  # the less common way for both tags
        "d": "1girl, blue eyes, ^_^, score_9",
        "e": "1girl, short hair",
    }
    paths = []
    for name, text in captions.items():
        paths.append(_img(tmp_path / f"{name}.png", (768, 768)))
        paths[-1].with_suffix(".txt").write_text(text, encoding="utf-8")
    report = audit(paths)
    assert [Path(f).stem for f in report["files"]["tag_spelling_mixed"]] == ["c"]
    assert report["tags_spelt_two_ways"] == ["blue eyes", "long hair"]


def test_audit_accepts_one_spelling_throughout(tmp_path):
    for name, text in {"a": "long_hair, blue_eyes", "b": "long_hair, ^_^"}.items():
        _img(tmp_path / f"{name}.png", (768, 768)).with_suffix(".txt").write_text(text)
    assert audit(sorted(tmp_path.glob("*.png")))["files"]["tag_spelling_mixed"] == []


def test_spelling_fixes_follow_the_more_common_spelling(tmp_path):
    from styleatlas.dataset import spelling_fixes

    for name, text in {
        "a": "long hair, blue eyes",
        "b": "long hair",
        "c": "long_hair, blue_eyes",
    }.items():
        _img(tmp_path / f"{name}.png").with_suffix(".txt").write_text(text, encoding="utf-8")
    paths = sorted(tmp_path.glob("*.png"))
    assert spelling_fixes(paths) == {"long hair": "long hair", "blue eyes": "blue eyes"}
    (tmp_path / "a.txt").write_text("long_hair, blue_eyes", encoding="utf-8")
    assert spelling_fixes(paths) == {"long hair": "long_hair"}  # blue_eyes is now one way only


def test_frequent_tags_lists_what_most_captions_share(tmp_path):
    from styleatlas.dataset import frequent_tags

    texts = [
        "1girl, white shirt, smile",
        "1girl, white_shirt",
        "1girl, white shirt, hat",
        "1girl, hat",
        "1boy",
    ]
    for k, text in enumerate(texts):
        _img(tmp_path / f"{k}.png").with_suffix(".txt").write_text(text, encoding="utf-8")
    _img(tmp_path / "bare.png")  # no caption: not counted
    common = frequent_tags(sorted(tmp_path.glob("*.png")))
    assert common == [("1girl", 0.8), ("white shirt", 0.6)]  # spellings merged; hat 40% left out
    assert frequent_tags(sorted(tmp_path.glob("*.png"))[:3]) == []  # too few captions to say
