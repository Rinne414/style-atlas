"""The command line end to end, with a stand-in encoder: each image's style vector comes from its
average colour, so folders of red, green and blue pictures are three clean styles."""

from __future__ import annotations

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
    copied = sorted(p.name for p in (out / "matches").glob("*.png"))
    assert len(copied) == 3 and all(name.startswith("red__") for name in copied)
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
    verdict = json.loads(capsys.readouterr().out)
    assert verdict["images"] == [7, 6] and verdict["centroid_distance"] > 0.5
    assert verdict["look_b_minus_a"]["warmth"] < 0 and "cooler" in verdict["look_words"]


def test_map_and_bench(lib, tmp_path, capsys):
    html = tmp_path / "map.html"
    folders = tmp_path / "folders.html"
    assert main(["map", str(lib), "--by-folder", "-o", str(folders), "--projection", "pca",
                 "--device", "cpu"]) == 0  # fmt: skip
    assert folders.exists()
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
    assert main(["calibrate", str(lib), "--device", "cpu"]) == 0
    floors = json.loads(capsys.readouterr().out)
    assert set(floors["per_group"]) == {"red", "green", "blue"} and floors["noise_floor"] >= 0
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
    assert main(["taste", "score", str(lib), "--model", str(model), "--device", "cpu"]) == 0
    ranked = [line.split()[1] for line in capsys.readouterr().out.strip().splitlines()]
    assert ranked[0].startswith("red/") and ranked[-1].startswith("blue/")

    assert main(["embed", str(lib), "--device", "cpu"]) == 0
    assert main(["audit", str(lib), "--device", "cpu"]) == 0
    out = capsys.readouterr().out
    assert "smaller_than_min_side" in out and "[smaller_than_min_side]" in out


def test_report_sums_up_a_folder(lib, tmp_path, capsys):
    out = tmp_path / "report.html"
    assert main(["report", str(lib), "-o", str(out), "--artists", str(lib), "--device", "cpu"]) == 0
    page = out.read_text(encoding="utf-8")
    assert "畫風一致性" in page and "最像的畫師" in page and page.count('<div class="card">') >= 3
    assert "data:image/webp;base64," in page  # thumbnails inside, so the file can be sent alone
    assert main(["report", str(lib), "-o", str(out), "--lang", "en", "--device", "cpu"]) == 0
    assert "Style consistency" in out.read_text(encoding="utf-8")


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
