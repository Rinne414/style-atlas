"""The command line end to end, with a stand-in encoder: each image's style vector comes from its
average colour, so folders of red, green and blue pictures are three clean styles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from styleatlas.cli import main
from styleatlas.encoder import Embeddings, encoder_signature
from styleatlas.look import LOOK_NAMES

COLOURS = {"red": (220, 40, 40), "green": (40, 200, 60), "blue": (40, 60, 220)}


class FakeEncoder:
    device = "cpu"
    signature = encoder_signature("center")

    def encode(self, images: list[Image.Image]) -> Embeddings:
        rows = []
        for im in images:
            a = np.asarray(im.convert("RGB").resize((16, 16)), dtype=np.float32) / 255
            v = np.zeros(768, np.float32)
            v[:3] = a.mean(axis=(0, 1)) * 4
            seed = int(a.sum() * 1000) % 2**32  # same picture, same vector
            v += np.random.default_rng(seed).normal(0, 0.05, 768).astype(np.float32)
            rows.append(v / np.linalg.norm(v))
        s = np.stack(rows)
        return Embeddings(s, s)

    def prepare(self, im: Image.Image) -> Image.Image:
        return im

    def encode_prepared(self, prepared: list[Image.Image]) -> Embeddings:
        return self.encode(prepared)


@pytest.fixture
def lib(tmp_path, monkeypatch):
    """lib/<colour>/<colour>__<id>.png, 6 per colour, with captions; a tmp cache."""
    monkeypatch.setenv("STYLE_ATLAS_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr("styleatlas.atlas.get_encoder", lambda opts: FakeEncoder())
    root = tmp_path / "lib"
    for name, rgb in COLOURS.items():
        (root / name).mkdir(parents=True)
        for i in range(6):
            im = Image.new("RGB", (64, 64), rgb)
            ImageDraw.Draw(im).ellipse([i * 8, i * 6, i * 8 + 10, i * 6 + 10], fill=(255, 255, 255))
            p = root / name / f"{name}__{100000 + 10 * i + len(name)}.png"
            im.save(p)
            p.with_suffix(".txt").write_text(f"1girl, {name}_tag", encoding="utf-8")
    return root


def test_cluster_exports_kohya_folders_with_triggers(lib, tmp_path, capsys):
    out = tmp_path / "out"
    web = tmp_path / "lib_style_atlas"  # where the web app keeps its exclusions
    web.mkdir()
    (web / "excluded.json").write_text(json.dumps({"red/red__100003.png": True}), "utf-8")
    code = main(
        ["cluster", str(lib), "--device", "cpu", "--layout", "kohya", "--name", "art",
         "--export", "copy", "--trigger-captions", "--no-map", "--time", "name", "-o", str(out)]
    )  # fmt: skip
    assert code == 0
    folders = sorted(p.name for p in (out / "folders").iterdir() if p.is_dir() and p.name[0] != "_")
    assert len(folders) == 3 and all(f.split("_", 1)[1].startswith("art_style") for f in folders)
    caption = next((out / "folders" / folders[0]).glob("*.txt")).read_text(encoding="utf-8")
    assert caption.startswith(folders[0].split("_", 1)[1] + ", 1girl")
    assert (out / "clusters.csv").exists()
    groups = json.loads((out / "clusters.json").read_text(encoding="utf-8"))["clusters"]
    assert all(set(g["look"]) == set(LOOK_NAMES) and g["look_words"] for g in groups)
    assert "warmth" in (out / "clusters.csv").read_text(encoding="utf-8-sig").splitlines()[0]
    tomllib = pytest.importorskip("tomllib")  # Python 3.11+
    config = tomllib.loads((out / "folders" / "dataset_config.toml").read_text(encoding="utf-8"))
    subsets = config["datasets"][0]["subsets"]
    assert sorted(Path(s["image_dir"]).name for s in subsets) == folders
    assert all(s["num_repeats"] == int(Path(s["image_dir"]).name.split("_")[0]) for s in subsets)
    assert config["general"]["keep_tokens"] == 1  # the trigger stays first
    assert [p.name for p in (out / "folders" / "_excluded").glob("*.png")] == ["red__100003.png"]
    assert "1 image(s) you excluded in the web app" in capsys.readouterr().err


def test_period_split_and_refused_flag_mix(lib, tmp_path, capsys):
    out = tmp_path / "out"
    args = ["cluster", str(lib / "red"), "--device", "cpu", "--granularity", "period", "--k", "2"]
    assert main([*args, "--no-map", "-o", str(out)]) == 0
    err = capsys.readouterr().err
    assert "(kmeans)" in err and "soft" in err  # 6 images: the boundaries note
    assert main([*args, "--method", "hdbscan", "--no-map", "-o", str(out)]) == 1


def test_search_combines_examples_and_copies_the_matches(lib, tmp_path, capsys):
    examples = [str(p) for p in sorted((lib / "red").glob("*.png"))[:3]]
    out = tmp_path / "found"
    code = main(
        ["search", *examples, "--in", str(lib), "--combine", "--top", "3", "--device", "cpu",
         "--copy-to", str(out), "--keep-duplicates"]
    )  # fmt: skip
    assert code == 0
    copied = sorted(p.name for p in out.glob("*.png"))  # straight into --copy-to, by rank
    assert [name[:3] for name in copied] == ["01_", "02_", "03_"]
    assert all(name[3:].startswith("red__") for name in copied)
    capsys.readouterr()
    # the stand-in encoder gives some of one colour's pictures the same vector: they fold
    assert main(["search", *examples, "--in", str(lib), "--combine", "--top", "3", "--json",
                 "--device", "cpu"]) == 0  # fmt: skip
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 3 and sum(Path(r["path"]).name.startswith("red__") for r in rows) < 3


def test_search_by_folder_names_the_closest_sub_folder(lib, tmp_path, capsys):
    query = tmp_path / "query.png"
    Image.new("RGB", (64, 64), (60, 70, 210)).save(query)  # a bluish picture from elsewhere
    assert main(["search", str(query), "--in", str(lib), "--by-folder", "--json",
                 "--device", "cpu"]) == 0  # fmt: skip
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 3 and rows[0]["folder"] == "blue"
    assert rows[0]["images"] == 6 and rows[0]["closest"].startswith("blue/")
    one = lib / "red"  # no sub-folders below it: nothing to rank
    assert main(["search", str(query), "--in", str(one), "--by-folder", "--device", "cpu"]) == 1


def test_audit_duplicates_outliers_and_compare(lib, capsys):
    assert main(["audit", str(lib), "--json", "--device", "cpu"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["smaller_than_min_side"] == 18  # 64 px pictures

    copy = lib / "red" / "copy.png"
    copy.write_bytes((lib / "red" / "red__100003.png").read_bytes())
    assert main(["duplicates", str(lib), "--json", "--device", "cpu"]) == 0
    groups = json.loads(capsys.readouterr().out)
    assert any("red/copy.png" in g for g in groups)

    assert main(["outliers", str(lib), "--top", "3", "--device", "cpu"]) == 0
    assert len(capsys.readouterr().out.strip().splitlines()) == 3

    assert main(["compare", str(lib / "red"), str(lib / "blue"), "--device", "cpu"]) == 0
    text = capsys.readouterr().out
    assert "style distance" in text and "look: B is" in text and "cooler" in text
    assert "the two sides likely differ" in text  # 7 and 6 images: read next to real artists
    assert "farther apart than half of pairs of different artists" in text
    assert "train one side alone" in text
    assert "red/" in text and "nearly repeat" not in text  # no copies: no line
    assert main(["compare", str(lib / "red"), str(lib / "blue"), "--json", "--device", "cpu"]) == 0
    verdict = json.loads(capsys.readouterr().out)
    assert verdict["images"] == [7, 6] and verdict["centroid_distance"] > 0.5
    assert verdict["look_b_minus_a"]["warmth"] < 0 and "cooler" in verdict["look_words"]
    assert verdict["separable"] and verdict["artist_reading"]["position"] == "above_median"
    args = ["compare", str(lib / "red"), str(lib / "blue"), "--noise-floor", "0.05"]
    assert main([*args, "--device", "cpu"]) == 0  # a calibrated scale: z and its verdict
    captured = capsys.readouterr()
    assert "(z " in captured.out and "comparison with real artists is left out" in captured.err
    assert main([*args, "--json", "--device", "cpu"]) == 0
    assert json.loads(capsys.readouterr().out)["artist_reading"] is None
    with pytest.raises(SystemExit):  # 0 would divide; it used to mean "unset"
        main(["compare", str(lib / "red"), str(lib / "blue"), "--noise-floor", "0"])


def test_a_compare_distance_is_placed_among_pairs_of_different_artists():
    from styleatlas.metrics import ARTIST_SCALE, artist_reading

    (n5, p5_5, med_5, _), (n10, p5_10, _, _), (n20, p5_20, med_20, _) = ARTIST_SCALE
    assert artist_reading(p5_20 - 0.01, n20, n20).position == "below_p5"
    assert artist_reading(p5_20, n20, n20).position == "p5_to_median"  # the cut as printed
    assert artist_reading(med_20, n20, n20).position == "above_median"
    assert artist_reading(0.3, 4, 50) is None  # a side under 5: the z scale instead
    assert artist_reading(0.1, n5, n5).others_p5 == p5_5  # the rows themselves
    assert artist_reading(0.1, n10, n10).others_p5 == p5_10
    uneven = artist_reading(0.1, 10, 40)  # 2 / (1/10 + 1/40) = 16 works a side
    assert uneven.n == 16.0 and p5_20 < uneven.others_p5 < p5_10
    big = artist_reading(0.1, 400, 400).others_p5  # noise shrinks on past 20 a side
    limit = p5_20 - (p5_10 - p5_20) / (1 / n10 - 1 / n20) / n20  # the last segment at 1/n = 0
    assert limit < big < p5_20 and abs(artist_reading(0.1, 10**9, 10**9).others_p5 - limit) < 1e-6


def test_compare_training_line_offers_options_for_each_case():
    from styleatlas.cli_inspect import _training_line
    from styleatlas.metrics import ArtistReading

    def line(position, separable, n=20.0):
        return _training_line(ArtistReading(n, position, 0.13, 0.23, 0.09), separable)

    assert "no sign that the two sides need splitting" in line("below_p5", False)
    assert "may not show" in line("below_p5", False, n=6.0)  # few images: no proof of sameness
    assert "timeline" in line("below_p5", True) and "timeline" not in line("p5_to_median", True)
    assert "mix two looks" in line("above_median", True)


def test_map_and_bench(lib, tmp_path, capsys):
    html = tmp_path / "map.html"
    folders = tmp_path / "folders.html"
    assert main(["map", str(lib), "--by-folder", "-o", str(folders), "--projection", "pca",
                 "--device", "cpu"]) == 0  # fmt: skip
    assert folders.exists()
    assert "families" in capsys.readouterr().err  # the points are folders, grouped in families
    assert main(["map", str(lib), "--projection", "pca", "--device", "cpu"]) == 0
    assert (tmp_path / "lib_style_atlas" / "style_atlas_map.html").exists()  # next to, not in
    assert not list(lib.glob("*.html"))
    assert main(["map", str(lib), "-o", str(html), "--projection", "pca", "--device", "cpu"]) == 0
    text = html.read_text(encoding="utf-8")
    assert "atlas-data" in text and '"look_names":["brightness"' in text
    capsys.readouterr()  # map prints where it wrote the file
    assert main(["bench", str(lib), "--trials", "2", "--device", "cpu"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["whitened"]["top1"] == 1.0 and report["labels"] == 3


def test_an_unreadable_web_exclusion_file_is_reported_and_left_alone(lib, tmp_path, capsys):
    web = tmp_path / "lib_style_atlas"
    web.mkdir()
    (web / "excluded.json").write_text("", "utf-8")  # e.g. cut short by a crash
    out = tmp_path / "out"
    assert main(["cluster", str(lib), "--device", "cpu", "--no-map", "-o", str(out)]) == 0
    assert "exclusions are NOT applied" in capsys.readouterr().err
    assert [p.name for p in web.iterdir()] == ["excluded.json"]  # not renamed to .bad


def test_ignore_characters_and_neutralize_are_alternatives(lib, tmp_path, capsys):
    out = tmp_path / "out"
    base = ["cluster", str(lib), "--device", "cpu", "--no-map", "-o", str(out)]
    assert main([*base, "--ignore-characters"]) == 0
    assert "3 subjects found in the picture content" in capsys.readouterr().err  # the 3 colours
    for bad in (["--ignore-characters", "--neutralize", "1"], ["--neutralize", "9"]):
        with pytest.raises(SystemExit):  # refused by argparse, before any image is read
            main([*base, *bad])


def test_cluster_can_cap_each_group(lib, tmp_path, capsys):
    out = tmp_path / "out"
    args = ["cluster", str(lib), "--device", "cpu", "--no-map", "--export", "copy", "-o", str(out)]
    assert main([*args, "--max-per-group", "4"]) == 0
    assert "6 image(s) beyond 4 per group go to _trimmed" in capsys.readouterr().err
    assert len(list((out / "folders" / "_trimmed").glob("*.png"))) == 6  # 2 of each colour
    with pytest.raises(SystemExit):
        main([*args, "--max-per-group", "0"])


def test_calibrate_taste_embed_and_audit_text(lib, tmp_path, capsys):
    assert main(["calibrate", str(lib), "--json", "--device", "cpu"]) == 0
    floors = json.loads(capsys.readouterr().out)
    assert set(floors["per_group"]) == {"red", "green", "blue"} and floors["noise_floor"] >= 0
    assert main(["calibrate", str(lib), "--device", "cpu"]) == 0
    out = capsys.readouterr().out
    assert f"--noise-floor {floors['noise_floor']}" in out and "(6 images)" in out
    assert main(["calibrate", str(lib / "red"), "--device", "cpu"]) == 1  # no sub-folders

    votes = tmp_path / "votes"  # shades, so that no two pictures share a vector
    for name, (r, g, b) in (("like", (220, 40, 40)), ("dislike", (40, 60, 220))):
        (votes / name).mkdir(parents=True)
        for i in range(6):
            shade = (r - 9 * i, g + 7 * i, b - 5 * i)
            Image.new("RGB", (64, 64), shade).save(votes / name / f"{i}.png")
    model = tmp_path / "taste.npz"
    train = ["--like", str(votes / "like"), "--dislike", str(votes / "dislike")]
    assert main(["taste", "train", *train, "--model", str(model), "--device", "cpu"]) == 0
    err = capsys.readouterr().err
    assert "how well it tells them apart" in err and "the rated artists' other works" in err
    assert "the pictures you like" in err  # the look of the two folders
    score = ["taste", "score", str(lib), "--model", str(model), "--device", "cpu"]
    assert main(score) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    ranked = [line.split()[1] for line in lines]
    assert ranked[0].startswith("red/") and ranked[-1].startswith("blue/")
    assert "closest rated: liked like/" in lines[0]  # which rated picture it resembles
    assert main([*score, "--copy-to", str(tmp_path / "best"), "--top", "3"]) == 0
    copied = sorted(p.name for p in (tmp_path / "best").glob("*.png"))
    assert len(copied) == 3 and copied[0].startswith("01_red")

    assert main(["embed", str(lib), "--device", "cpu"]) == 0
    assert main(["audit", str(lib), "--device", "cpu"]) == 0
    out = capsys.readouterr().out
    assert "smaller_than_min_side" in out and "[smaller_than_min_side]" in out


def test_report_sums_up_a_folder(lib, tmp_path, capsys):
    out = tmp_path / "report.html"
    args = ["report", str(lib), "-o", str(out), "--artists", str(lib), "--lang", "zh"]
    assert main([*args, "--device", "cpu"]) == 0
    page = out.read_text(encoding="utf-8")
    assert "畫風一致性" in page and "最像的畫師" in page and page.count('<div class="card">') >= 3
    assert "data:image/webp;base64," in page  # thumbnails inside, so the file can be sent alone
    assert "來自：red 6" in page or "來自：green 6" in page  # each group's sub-folders
    assert "子資料夾：哪些畫風相近" in page and page.count("最像：") == 3  # red, green, blue
    assert "這個資料夾有 3 個子資料夾" in page  # a collection reads as spread by design
    assert page.count('<div class="ends">') == 7  # consistency and the 6 look measures
    assert main(["report", str(lib), "-o", str(out), "--lang", "en", "--device", "cpu"]) == 0
    page = out.read_text(encoding="utf-8")
    assert "Style consistency" in page and "Sub-folders: which draw alike" in page
    args = ["report", str(lib), "-o", str(out), "--lang", "en", "--neutralize", "1"]
    assert main([*args, "--device", "cpu"]) == 0  # another space: the families' cut does not hold
    assert "Sub-folders: which draw alike" not in out.read_text(encoding="utf-8")


def test_report_cards_show_one_image_of_each_set_of_near_duplicates():
    from styleatlas.report_card import _copies_in, _one_of_each

    dups = [[1, 2, 3], [4, 5], [8, 9]]  # sets of near-duplicates in the folder
    copy_set = {i: g for g, group in enumerate(dups) for i in group}
    assert _one_of_each(np.array([3, 0, 1, 5, 4, 2, 6]), copy_set) == [3, 0, 5, 6]
    assert _copies_in(np.array([0, 1, 2, 3, 4, 8]), dups) == (3, 1)  # 4 and 8 alone here


def test_folder_mix_names_the_largest_sub_folders_first():
    from styleatlas.report_card import folder_mix

    assert folder_mix(["b", "a", "b", "", "c", "d", "b"]) == [("b", 3), ("a", 1), (".", 1)]


def test_report_leaves_out_images_excluded_in_the_web_app(lib, tmp_path, capsys):
    web = tmp_path / "lib_style_atlas"
    web.mkdir()
    (web / "excluded.json").write_text(json.dumps({"red/red__100003.png": True}), "utf-8")
    out = tmp_path / "report.html"
    assert main(["report", str(lib), "-o", str(out), "--lang", "en", "--device", "cpu"]) == 0
    assert "1 excluded images left out" in out.read_text(encoding="utf-8")
    assert "1 image(s) you excluded in the web app are left out" in capsys.readouterr().err


def test_a_broken_image_is_listed_as_failed_and_the_rest_keep_their_order(lib, tmp_path):
    from styleatlas.atlas import EncodeOptions, embed_paths
    from styleatlas.images import find_images

    (lib / "red" / "broken.png").write_bytes(b"not a png")
    paths = find_images(lib)
    opts = EncodeOptions(device="cpu", batch_size=4, db_path=tmp_path / "v.sqlite")
    kept, style, _, failed = embed_paths(paths, opts)
    assert [p.name for p, _ in failed] == ["broken.png"] and "cannot open" in failed[0][1]
    assert kept == [p for p in paths if p.name != "broken.png"] and len(style) == len(kept)


def test_vectors_are_saved_when_the_last_batch_fails_entirely(lib, tmp_path):
    from styleatlas.atlas import EncodeOptions, embed_paths
    from styleatlas.images import find_images

    (lib / "zzz").mkdir()
    (lib / "zzz" / "broken.png").write_bytes(b"not a png")
    paths = find_images(lib)
    assert paths[-1].name == "broken.png"
    opts = EncodeOptions(device="cpu", batch_size=1, db_path=tmp_path / "v.sqlite")
    kept, _, _, failed = embed_paths(paths, opts)
    again = embed_paths(paths, opts)  # everything that worked was saved
    assert len(kept) == len(paths) - 1 and again[0] == kept and len(again[3]) == 1


def test_report_refuses_a_folder_whose_images_are_all_excluded(lib, tmp_path, capsys):
    from styleatlas.images import find_images

    web = tmp_path / "lib_style_atlas"
    web.mkdir()
    marks = {p.relative_to(lib).as_posix(): True for p in find_images(lib)}
    (web / "excluded.json").write_text(json.dumps(marks), "utf-8")
    out = tmp_path / "report.html"
    assert main(["report", str(lib), "-o", str(out), "--device", "cpu"]) == 1
    assert "every image is excluded" in capsys.readouterr().err and not out.exists()


def _new_images(lib, tmp_path):
    """3 new red images, one already in the dataset, one grey that is like no group."""
    import shutil

    new = tmp_path / "new"
    new.mkdir()
    for i in range(3):
        im = Image.new("RGB", (64, 64), COLOURS["red"])
        ImageDraw.Draw(im).rectangle([i * 9, 40, i * 9 + 12, 52], fill=(255, 255, 255))
        im.save(new / f"red_new_{i}.png")
    shutil.copy(sorted((lib / "red").glob("*.png"))[0], new / "again.png")
    Image.new("RGB", (64, 64), (128, 128, 128)).save(new / "grey.png")
    return new


def _sorted_rows(out):
    import csv

    with open(out / "sorted.csv", encoding="utf-8-sig", newline="") as f:
        return {r["path"]: r for r in csv.DictReader(f)}


def test_sort_places_new_images_into_the_dataset_sub_folders(lib, tmp_path, capsys):
    new, out = _new_images(lib, tmp_path), tmp_path / "out"
    args = ["sort", str(new), "--into", str(lib), "-o", str(out), "--by-folder"]
    assert main([*args, "--export", "copy", "--device", "cpu"]) == 0
    rows = _sorted_rows(out)
    assert rows["again.png"]["folder"] == "_already_in_dataset"
    assert rows["again.png"]["copy_of"].startswith("red/")
    assert all(float(r["limit"]) > 0 for r in rows.values())  # each image's group limit
    assert all(rows[f"red_new_{i}.png"]["closest_group"] == "red" for i in range(3))
    assert rows["grey.png"]["fits"] == "no" and rows["grey.png"]["folder"] == "_unsure"
    placed = {p.name for p in (out / "sorted").rglob("*.png")}
    assert placed == set(rows) and (out / "sorted" / "_unsure" / "grey.png").is_file()
    err = capsys.readouterr().err
    assert "near-copies of images the dataset already holds" in err and "fit their group" in err
    assert "again.png  =  red/" in err  # which dataset image each near-copy repeats
    assert "0 in style folders, 4 in _unsure, 1 in _already_in_dataset" in err
    assert "_unsure, the closest to a group first" in err and "grey.png  (" in err
    assert "next: look through" in err and "style-atlas audit" in err


def test_sort_uses_the_dataset_style_groups_without_sub_folders(lib, tmp_path):
    new, out = _new_images(lib, tmp_path), tmp_path / "out"
    assert main(["sort", str(new), "--into", str(lib), "-o", str(out), "--device", "cpu"]) == 0
    rows = _sorted_rows(out)
    groups = {rows[f"red_new_{i}.png"]["closest_group"] for i in range(3)}
    assert len(groups) == 1 and groups.pop().startswith("style_")
    assert not (out / "sorted").exists()  # nothing placed without --export


def test_sort_needs_groups_to_sort_into(lib, tmp_path, capsys):
    flat = tmp_path / "flat"
    flat.mkdir()
    for p in sorted((lib / "red").glob("*.png"))[:3]:
        (flat / p.name).write_bytes(p.read_bytes())
    new = _new_images(lib, tmp_path)
    assert main(["sort", str(new), "--into", str(flat), "--by-folder", "--device", "cpu"]) == 1
    assert "no sub-folders" in capsys.readouterr().err


def test_sort_of_images_the_dataset_already_holds_gives_no_verdict(lib, tmp_path, capsys):
    again = tmp_path / "again"
    again.mkdir()
    for p in (lib / "red").glob("*.png"):
        (again / p.name).write_bytes(p.read_bytes())
    out = tmp_path / "out"
    args = ["sort", str(again), "--into", str(lib), "-o", str(out), "--by-folder"]
    assert main([*args, "--device", "cpu"]) == 0
    assert {r["folder"] for r in _sorted_rows(out).values()} == {"_already_in_dataset"}
    assert "fit their group" not in capsys.readouterr().err


def test_sort_keeps_new_images_and_set_aside_folders_out_of_the_dataset(lib, tmp_path, capsys):
    inside = lib / "new_batch"  # new images kept inside the dataset folder
    inside.mkdir()
    for p in _new_images(lib, tmp_path).iterdir():
        if p.name != "again.png":
            (inside / p.name).write_bytes(p.read_bytes())
    (lib / "unassigned").mkdir()  # left over by a plain-layout export
    for p in sorted((lib / "blue").glob("*.png"))[:2]:
        (lib / "unassigned" / p.name).write_bytes(p.read_bytes())
    out = tmp_path / "out"
    args = ["sort", str(inside), "--into", str(lib), "-o", str(out), "--by-folder"]
    assert main([*args, "--device", "cpu"]) == 0
    rows = _sorted_rows(out)
    assert {r["closest_group"] for r in rows.values()} <= {"red", "green", "blue"}
    assert "_already_in_dataset" not in {r["folder"] for r in rows.values()}
    assert "too few images to judge the batch" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["sort", str(lib), "--device", "cpu"])  # --into is required
    assert main(["sort", str(lib), "--into", str(lib), "--device", "cpu"]) == 1
    assert "the same folder" in capsys.readouterr().err


def test_sort_names_small_groups_and_keeps_reserved_names_apart(lib, tmp_path, capsys):
    from styleatlas.cli_sort import _unreserved

    assert _unreserved({0: "_Unsure", 1: "early"}) == {0: "_Unsure_group", 1: "early"}
    (lib / "solo").mkdir()
    (lib / "solo" / "one.png").write_bytes(next((lib / "green").glob("*.png")).read_bytes())
    new = _new_images(lib, tmp_path)
    args = ["sort", str(new), "--into", str(lib), "-o", str(tmp_path / "o"), "--by-folder"]
    assert main([*args, "--device", "cpu"]) == 0
    assert "too few images (under 3) to sort into: solo" in capsys.readouterr().err


def test_sort_judges_a_batch_of_eight_or_more(lib, tmp_path, capsys):
    from styleatlas.cli_sort import UNSURE, _summary
    from styleatlas.cluster import Fit

    greys = tmp_path / "greys"
    greys.mkdir()
    for i in range(9):
        grey = 100 + i * 8
        Image.new("RGB", (64, 64), (grey, grey, grey)).save(greys / f"g{i}.png")
    args = ["sort", str(greys), "--into", str(lib), "-o", str(tmp_path / "out")]
    assert main([*args, "--by-folder", "--device", "cpu"]) == 0
    assert "mostly unlike" in capsys.readouterr().err
    labels = {0: "a"}
    for fitting, verdict in ((6, "mostly the dataset's styles"), (3, "partly")):
        fits = [Fit(0, 0.1, i < fitting) for i in range(9)]
        names = [f"g{i}.png" for i in range(9)]
        _summary(fits, labels, ["a" if f.fits else UNSURE for f in fits], names, {})
        assert verdict in capsys.readouterr().err
    args = ["sort", str(greys), "--into", str(lib), "-o", str(tmp_path)]
    assert main([*args, "--device", "cpu"]) == 1
    assert "must not hold the new images" in capsys.readouterr().err


def test_sort_suggests_new_kohya_repeats_for_folders_that_grow(capsys):
    from styleatlas.cli_sort import UNSURE, _repeats_notes
    from styleatlas.cluster import from_labels

    x = np.eye(30, 8, dtype=np.float32) + 0.01
    labels = np.array([0] * 10 + [1] * 20)  # 10 images at 10 repeats, 20 at 5: auto repeats
    groups = from_labels(x, labels, "folders")
    names = {c.id: ("10_x_style01" if c.size == 10 else "5_x_style02") for c in groups.clusters}
    _repeats_notes(groups, names, ["10_x_style01"] * 5 + ["5_x_style02", UNSURE])
    err = capsys.readouterr().err
    assert "10_x_style01: 10 + 5 images; rename it 7_x_style01" in err
    assert "5_x_style02" not in err  # 21 images still round to 5 repeats


def test_cluster_by_artist_and_its_refused_combinations(lib, tmp_path, capsys):
    base = ["cluster", str(lib), "--device", "cpu", "--no-map", "-o", str(tmp_path / "o")]
    assert main([*base, "--granularity", "artists"]) == 0
    assert "by artist: whitened, cut 0.9" in capsys.readouterr().err
    assert main([*base, "--granularity", "artists", "--neutralize", "1"]) == 1
    assert "takes plain style vectors" in capsys.readouterr().err
    assert main([*base, "--granularity", "artists", "--method", "hdbscan"]) == 1
    assert "--method" in capsys.readouterr().err


def test_report_says_where_saved_groups_come_from_and_fresh_ignores_them(lib, tmp_path, capsys):
    from styleatlas.atlas import EncodeOptions, build_atlas
    from styleatlas.cluster import cluster_styles
    from styleatlas.groupfile import GROUPS_FILE, save_groups

    atlas = build_atlas(lib, EncodeOptions(device="cpu"))
    web = tmp_path / "lib_style_atlas"
    web.mkdir()
    groups = cluster_styles(atlas.style)
    save_groups(web / GROUPS_FILE, atlas, groups, {}, "plain", {0: "saved-name"})
    out = tmp_path / "r.html"
    assert main(["report", str(lib), "-o", str(out), "--lang", "en", "--device", "cpu"]) == 0
    assert "saved in" in capsys.readouterr().err and "saved-name" in out.read_text("utf-8")
    assert main(["report", str(lib), "-o", str(out), "--fresh", "--device", "cpu"]) == 0
    assert "saved in" not in capsys.readouterr().err and "saved-name" not in out.read_text("utf-8")


def test_duplicate_groups_show_how_alike_they_are(lib, tmp_path, capsys):
    import shutil

    one = next((lib / "red").glob("*.png"))
    shutil.copy(one, lib / "red" / "again.png")
    assert main(["duplicates", str(lib), "--device", "cpu"]) == 0
    assert "(similarity 1.000+)" in capsys.readouterr().out


def test_report_checks_lora_renders_against_the_training_set(lib, tmp_path, capsys):
    renders = tmp_path / "renders"
    renders.mkdir()
    for p in sorted((lib / "red").glob("*.png"))[:3]:  # memorised training images
        (renders / f"copy_{p.name}").write_bytes(p.read_bytes())
    for i in range(5):
        Image.new("RGB", (64, 64), (90 + 20 * i,) * 3).save(renders / f"grey{i}.png")
    out = tmp_path / "r.html"
    base = ["report", str(lib), "-o", str(out), "--renders", str(renders), "--device", "cpu"]
    assert main([*base, "--lang", "en"]) == 0
    page = out.read_text(encoding="utf-8")
    assert "LoRA renders (8, against this training set)" in page
    assert page.index("LoRA renders") < page.index("Style consistency")  # the renders first
    assert "Possibly memorised: 3 renders" in page and "of 8 fall inside a style group" in page
    rows = page.split('<table class="renders">')[1].split("</table>")[0].split("<tr ")[1:]
    assert len(rows) == 8  # every render, with its verdict and closest training image
    assert all('class="copy"' in row and "copy_red" in row for row in rows[:3])  # copies first
    assert "likely repeats a training image (similarity 1.000" in rows[0]
    assert "closest training image" in rows[-1]
    assert "Next to Danbooru artists" in page and "z_note" not in page  # 5+ a side: no z
    assert main([*base, "--lang", "zh"]) == 0
    assert "LoRA 算圖檢查" in out.read_text(encoding="utf-8")
    assert main([*base, "--neutralize", "1"]) == 1
    assert "--renders compares plain style vectors" in capsys.readouterr().err


def test_render_check_without_any_training_group_of_three(lib, tmp_path):
    small = tmp_path / "small"
    small.mkdir()
    for colour in ("red", "blue"):
        for p in sorted((lib / colour).glob("*.png"))[:2]:
            (small / p.name).write_bytes(p.read_bytes())
    out = tmp_path / "r.html"
    args = ["report", str(small), "-o", str(out), "--renders", str(lib / "green"), "--lang", "en"]
    assert main([*args, "--device", "cpu"]) == 0  # was a ZeroDivisionError
    page = out.read_text(encoding="utf-8")
    assert "no style group of 3 images or more" in page
    assert page.count("closest training image (") == 6  # every render is still listed


def test_messages_are_in_chinese_when_asked(lib, tmp_path, monkeypatch, capsys):
    from styleatlas.lang import chinese

    monkeypatch.setenv("STYLE_ATLAS_LANG", "zh")
    assert chinese()
    base = ["cluster", str(lib), "--device", "cpu", "--no-map", "-o", str(tmp_path / "o")]
    assert main(base) == 0
    err = capsys.readouterr().err
    assert "群，" in err and "張未分群" in err and "上面的資料夾名稱只是規劃" in err
    assert main(["audit", str(lib), "--device", "cpu"]) == 0
    assert "images（圖片數）" in capsys.readouterr().out
    monkeypatch.setenv("STYLE_ATLAS_LANG", "en")
    assert not chinese()


def test_sort_can_add_the_group_trigger_to_placed_captions(lib, tmp_path, monkeypatch):
    from styleatlas import cli_sort
    from styleatlas.cluster import Fit

    data = tmp_path / "data"
    for colour in ("red", "blue"):
        folder = data / f"10_x_{colour}"
        folder.mkdir(parents=True)
        for p in sorted((lib / colour).glob("*.png")):
            (folder / p.name).write_bytes(p.read_bytes())
    new = tmp_path / "new"
    new.mkdir()
    img = Image.new("RGB", (64, 64), COLOURS["red"])
    ImageDraw.Draw(img).rectangle([3, 3, 20, 20], fill=(255, 255, 255))
    img.save(new / "n.png")
    (new / "n.txt").write_text("1girl, red_tag", encoding="utf-8")

    def fits_all(style, clustering, query, skip=frozenset()):  # every new image fits group 0
        return [Fit(clustering.clusters[0].id, 0.1, True, 0.5) for _ in query]

    monkeypatch.setattr(cli_sort, "fit_to_groups", fits_all)
    out = tmp_path / "o"
    args = ["sort", str(new), "--into", str(data), "--by-folder", "-o", str(out)]
    extra = ["--export", "copy", "--trigger-captions", "--strip-tags", "red_tag"]
    assert main([*args, *extra, "--device", "cpu"]) == 0
    placed = list((out / "sorted").rglob("n.txt"))
    assert len(placed) == 1 and placed[0].parent.name.startswith("10_x_")
    trigger = placed[0].parent.name.partition("_")[2]  # repeats removed: x_red or x_blue
    assert placed[0].read_text(encoding="utf-8").strip() == f"{trigger}, 1girl"  # red_tag gone
    assert main([*args, "--trigger-captions", "--device", "cpu"]) == 1  # needs --export


def test_report_puts_each_group_on_the_timeline(lib, tmp_path):
    out = tmp_path / "r.html"
    args = ["report", str(lib), "-o", str(out), "--lang", "en", "--device", "cpu"]
    assert main([*args, "--time", "name"]) == 0  # ids in the file names give the order
    assert "When: median at" in out.read_text(encoding="utf-8")
    assert main(args) == 0 and "When: median at" not in out.read_text(encoding="utf-8")


def test_python_dash_m_runs_the_command():
    import subprocess
    import sys

    from styleatlas import __version__

    done = subprocess.run(
        [sys.executable, "-m", "styleatlas", "--version"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0
    assert __version__ in done.stdout


def _all_parsers(parser):
    """The parser and every sub-parser below it (commands, then the taste sub-commands)."""
    found = [parser]
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for sub in action.choices.values():
                found.extend(_all_parsers(sub))
    return found


def test_help_formats_in_both_languages(monkeypatch):
    import styleatlas.cli as cli

    monkeypatch.setenv("STYLE_ATLAS_LANG", "zh")
    zh = [p.format_help() for p in _all_parsers(cli.build_parser())]
    monkeypatch.setenv("STYLE_ATLAS_LANG", "en")
    en = [p.format_help() for p in _all_parsers(cli.build_parser())]

    assert len(zh) == len(en) > 15  # top, every command, the taste sub-commands
    assert any("畫風" in text for text in zh)
    assert any("資料夾" in text for text in zh)
    assert any("kohya" in text and "重複次數" in text for text in zh)
    assert "group a folder by style" in "\n".join(en)
    assert not any("畫風" in text for text in en)


def test_search_looks_further_down_when_near_copies_fold():
    from types import SimpleNamespace

    import styleatlas.cli as cli

    rng = np.random.default_rng(0)
    x = rng.normal(size=(40, 768)).astype(np.float32)
    x[1:10] = x[0]  # ten copies of one picture
    x /= np.linalg.norm(x, axis=1, keepdims=True)
    gallery = type("Gallery", (), {"style": x, "content": x, "__len__": lambda self: 40})()
    a = SimpleNamespace(top=5, combine=False)
    hits = cli._search_folded(a, gallery, x[:1], x, set())
    assert len(hits[0]) == 5  # one of the copies, then four other pictures


def test_search_names_a_query_that_does_not_exist(lib, tmp_path, capsys):
    missing = tmp_path / "nothere.png"
    assert main(["search", str(missing), "--in", str(lib), "--device", "cpu"]) == 1
    err = capsys.readouterr().err
    assert "not found" in err and "nothere.png" in err


def test_compare_refuses_the_same_folder_twice(lib, capsys):
    red = str(lib / "red")
    assert main(["compare", red, red, "--device", "cpu"]) == 1
    assert "same folder" in capsys.readouterr().err


def test_combined_search_json_names_the_query_the_same_in_every_language(lib, monkeypatch, capsys):
    examples = [str(p) for p in sorted((lib / "red").glob("*.png"))[:2]]
    monkeypatch.setenv("STYLE_ATLAS_LANG", "zh")
    args = ["search", *examples, "--in", str(lib), "--combine", "--top", "2", "--json"]
    assert main([*args, "--device", "cpu"]) == 0
    assert {r["query"] for r in json.loads(capsys.readouterr().out)} == {"(all queries)"}
    with pytest.raises(SystemExit):  # --top must be 1 or more
        main(["search", *examples, "--in", str(lib), "--top", "0", "--device", "cpu"])


def test_wrap_keeps_curly_quotes_and_brackets_with_their_text():
    from styleatlas.lang import wrap

    lines = wrap("ab “中文中文” …… 中文，中文。", 6)
    assert not any(line[0] in "”…，。" for line in lines)
    assert not any(line[-1] == "“" for line in lines)


def test_fixing_tag_spelling_needs_an_export(lib, capsys):
    assert main(["cluster", str(lib), "--fix-tag-spelling", "--device", "cpu"]) == 1
    assert "--fix-tag-spelling" in capsys.readouterr().err


def test_cluster_by_timeline_needs_a_time_and_reports_its_test(lib, tmp_path, capsys):
    out = tmp_path / "t"
    base = ["cluster", str(lib), "--granularity", "timeline", "--no-map", "-o", str(out)]
    assert main([*base, "--device", "cpu"]) == 1
    assert "--time" in capsys.readouterr().err
    assert main([*base, "--time", "name", "--device", "cpu"]) == 0
    err = capsys.readouterr().err
    verdicts = ("too few distinct", "no clear link", "no clear turning", "more abruptly")
    assert "periods along the timeline" in err and any(v in err for v in verdicts)


def test_demo_makes_the_images_once_and_opens_them(tmp_path, monkeypatch):
    import styleatlas.webserver as ws

    opened = {}
    monkeypatch.setattr(
        ws, "serve_when_ready", lambda build, title, **kw: opened.update(title=title) or True
    )
    folder = tmp_path / "demo"
    assert main(["demo", str(folder), "--no-browser", "--device", "cpu"]) == 0
    assert len(list(folder.rglob("*.png"))) == 72 and opened["title"] == "demo"
    first = sorted(p.stat().st_mtime_ns for p in folder.rglob("*.png"))
    assert main(["demo", str(folder), "--no-browser", "--device", "cpu"]) == 0
    assert sorted(p.stat().st_mtime_ns for p in folder.rglob("*.png")) == first  # kept


def test_help_says_where_to_start(capsys):
    import pytest

    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "where to start:\ntry it: demo\n" in out and "setup problems: doctor" in out


def test_cluster_accounts_for_every_image_and_says_how_to_get_one_folder(capsys):
    import argparse
    from types import SimpleNamespace

    from styleatlas.cli_lora import _log_where_they_went, _one_lora_hint

    _log_where_they_went(["2_a_style01"] * 44 + ["_duplicates"] * 11 + ["_outliers"] * 5)
    err = capsys.readouterr().err
    assert "60 images: 44 in 1 style folders; set aside: _duplicates 11, _outliers 5" in err
    timeline = SimpleNamespace(method="timeline", params={"p_time": 0.2, "p_turns": 0.5})
    _one_lora_hint(
        argparse.Namespace(granularity="timeline", k=None, threshold=None), timeline, None
    )
    assert "--k 1 instead of --granularity timeline" in capsys.readouterr().err
    auto = SimpleNamespace(method="agglomerative", n_clusters=6, params={})
    args = argparse.Namespace(granularity="auto", k=None, threshold=None)
    _one_lora_hint(args, auto, SimpleNamespace(verdict="like one artist"))
    assert "the 6 groups are most likely small differences" in capsys.readouterr().err
    _one_lora_hint(args, auto, SimpleNamespace(verdict="mixed"))  # a mix: no such hint
    assert capsys.readouterr().err == ""


def test_audit_says_what_to_do_about_missing_captions_and_small_images(capsys):
    from styleatlas.cli_inspect import _audit_advice

    _audit_advice({"images": 60, "no_caption": 60, "smaller_than_min_side": 60}, 768)
    err = capsys.readouterr().err
    assert "trained without them" in err and "'sample' size" in err
    _audit_advice({"images": 60, "no_caption": 3, "smaller_than_min_side": 2}, 768)
    assert capsys.readouterr().err == ""


def test_sort_merged_is_the_dataset_plus_the_new_images_ready_to_train(
    lib, tmp_path, monkeypatch, capsys
):
    from styleatlas import cli_sort
    from styleatlas.cluster import Fit

    data = tmp_path / "data"
    for colour in ("red", "blue"):
        folder = data / f"17_x_{colour}"  # 6 images at the automatic 17 repeats
        folder.mkdir(parents=True)
        for p in (lib / colour).iterdir():
            (folder / p.name).write_bytes(p.read_bytes())
    (data / "top.png").write_bytes(next((lib / "green").glob("*.png")).read_bytes())
    web = tmp_path / "data_style_atlas"  # one red image excluded in the web app
    web.mkdir()
    (web / "excluded.json").write_text(json.dumps({"17_x_red/red__100003.png": True}), "utf-8")
    new = _new_images(lib, tmp_path)

    def fits_red(style, clustering, query, skip=frozenset()):  # group 1: 17_x_red (sorted)
        return [Fit(1, 0.1, True, 0.5) for _ in query]

    monkeypatch.setattr(cli_sort, "fit_to_groups", fits_red)
    out = tmp_path / "o"
    args = ["sort", str(new), "--into", str(data), "-o", str(out), "--export", "copy"]
    assert main([*args, "--merged", "--device", "cpu"]) == 1  # needs --by-folder
    assert "--merged needs" in capsys.readouterr().err
    assert main([*args, "--by-folder", "--merged", "--trigger-captions", "--device", "cpu"]) == 0
    merged = out / "merged"
    pngs = {f.name: len(list((merged / f).glob("*.png"))) for f in merged.iterdir() if f.is_dir()}
    assert pngs == {"11_x_red": 5 + 4, "17_x_blue": 6, "_excluded": 1}  # 5 + 4 new: 11 repeats
    assert (merged / "top.png").is_file() and not list(merged.rglob("again.png"))  # a copy
    assert "num_repeats = 11" in (merged / "dataset_config.toml").read_text(encoding="utf-8")
    caption = (merged / "11_x_red" / "red__100013.txt").read_text(encoding="utf-8")
    assert caption == "x_red, 1girl, red_tag"
    assert len(list((data / "17_x_red").glob("*.png"))) == 6  # the dataset is untouched
    assert (data / "17_x_red" / "red__100013.txt").read_text(encoding="utf-8") == "1girl, red_tag"
    err = capsys.readouterr().err
    assert "renamed 17_x_red -> 11_x_red: 9 images there now (6 in the dataset's folder)" in err
    assert "merged dataset, ready to train" in err and "1 images excluded in the web app" in err
    assert not (out / "sorted" / "dataset_config.toml").exists()  # it would list new images only
    assert "rename it" not in err  # the note for the dataset itself is left out
    assert "4 of the images placed in style folders have a short side" in err  # new ones only
    assert f'style-atlas audit "{merged}"' in err
    linked = ["sort", str(new), "--into", str(data), "-o", str(tmp_path / "l"), "--by-folder"]
    assert main([*linked, "--export", "link", "--merged", "--device", "cpu"]) == 0
    assert "are hard links" in capsys.readouterr().err


def test_sort_never_writes_into_the_dataset_holding_the_new_images(lib, tmp_path, capsys):
    inside = lib / "new_batch"
    inside.mkdir()
    for p in _new_images(lib, tmp_path).iterdir():
        (inside / p.name).write_bytes(p.read_bytes())
    args = ["sort", str(inside), "--into", str(lib), "--by-folder", "--device", "cpu"]
    assert main(args) == 0
    assert not (lib / "new_batch_style_atlas").exists()  # next to the dataset instead
    assert (tmp_path / "lib_style_atlas" / "sorted.csv").is_file()
    assert main([*args, "-o", str(lib / "results")]) == 1
    assert "must not be inside the new images or the dataset" in capsys.readouterr().err


def test_merged_renames_never_take_a_folder_that_is_there():
    from collections import Counter

    from styleatlas.cli_sort import _merged_renames
    from styleatlas.cluster import from_labels

    x = np.eye(15, 8, dtype=np.float32) + 0.01
    groups = from_labels(x, np.array([0] * 6 + [1] * 9), "folders")
    names = {c.id: ("17_x_red" if c.size == 6 else "11_x_red") for c in groups.clusters}
    renames, blocked = _merged_renames(groups, names, Counter({"17_x_red": 9, "11_x_red": 9}))
    assert renames == {} and blocked == [("17_x_red", "11_x_red")]  # 9 images: 11 repeats
    renames, _ = _merged_renames(groups, names, Counter({"17_x_red": 4, "11_x_red": 9}))
    assert renames == {"17_x_red": "25_x_red"}  # fewer images (some excluded): more repeats


def test_cluster_points_a_library_of_many_artists_at_by_artist(tmp_path, capsys):
    from types import SimpleNamespace

    from styleatlas.atlas import Atlas
    from styleatlas.cli_common import _library_hint

    paths = [tmp_path / f"artist{k}" / f"{i}.png" for k in range(25) for i in range(2)]
    x = np.zeros((len(paths), 4), np.float32)
    atlas = Atlas(tmp_path, paths, x, x, "sig")
    _library_hint(atlas, SimpleNamespace(n_clusters=20))  # 25 sub-folders, 20 groups of 50
    assert "--granularity artists" in capsys.readouterr().err
    _library_hint(atlas, SimpleNamespace(n_clusters=6))  # few groups: no hint
    flat = Atlas(tmp_path, [tmp_path / f"{i}.png" for i in range(50)], x, x, "sig")
    _library_hint(flat, SimpleNamespace(n_clusters=20))  # no sub-folders: one artist, maybe
    assert "--granularity artists" not in capsys.readouterr().err
