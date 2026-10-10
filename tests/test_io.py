from __future__ import annotations

import csv
import io
import json
import os

import numpy as np
from PIL import Image

from styleatlas.atlas import Atlas
from styleatlas.cluster import cluster_styles
from styleatlas.dataset import plan_folders
from styleatlas.encoder import square_crops
from styleatlas.export import export_folders, write_table
from styleatlas.images import find_images, labels_from_folders, load_rgb
from styleatlas.report import render_html
from styleatlas.store import VectorStore

from .conftest import make_blobs


def _img(path, size=(40, 60), color=(200, 50, 50), mode="RGB"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new(mode, size, color if mode == "RGB" else (*color, 0)).save(path)
    return path


def test_find_images_skips_tool_folders_and_other_files(tmp_path):
    _img(tmp_path / "a" / "x.png")
    _img(tmp_path / ".styleatlas" / "y.png")
    (tmp_path / "notes.txt").write_text("hi")
    found = find_images(tmp_path)
    assert [p.name for p in found] == ["x.png"]
    assert labels_from_folders(found, tmp_path) == ["a"]


def test_load_rgb_flattens_transparency_onto_white(tmp_path):
    p = _img(tmp_path / "t.png", mode="RGBA")
    im = load_rgb(p)
    assert im.mode == "RGB"
    assert im.getpixel((0, 0)) == (255, 255, 255)


def test_square_crops_sizes():
    tall = Image.new("RGB", (400, 1200))
    assert [c.size for c in square_crops(tall, "center")] == [(224, 224)]
    tiles = square_crops(tall, "tiles")
    assert len(tiles) == 3 and all(c.size == (224, 224) for c in tiles)
    assert len(square_crops(Image.new("RGB", (300, 300)), "tiles")) == 1


def test_store_roundtrip_and_hash_reuse(tmp_path):
    img = _img(tmp_path / "a.png")
    copy = _img(tmp_path / "b.png")  # identical bytes -> same key
    with VectorStore(tmp_path / "db.sqlite") as store:
        k1, k2 = store.key(img), store.key(copy)
        assert k1 == k2
        s, c = np.arange(768, dtype=np.float32), np.ones(768, np.float32)
        store.put({k1: (s, c)}, "sig")
        got = store.get([k1], "sig")
        assert np.array_equal(got[k1][0], s)
        assert store.get([k1], "other-sig") == {}


def _atlas(tmp_path, sizes):
    x, _ = make_blobs(sizes)
    paths = [_img(tmp_path / "src" / f"sub{i % 2}" / "same.png", color=(i, i, i)) for i in range(2)]
    paths += [_img(tmp_path / "src" / f"img{i}.png", color=(i, 0, 0)) for i in range(len(x) - 2)]
    (tmp_path / "src" / "img0.txt").write_text("a caption")
    return Atlas(tmp_path / "src", paths, x, x, "sig")


def test_export_copies_captions_and_avoids_name_collisions(tmp_path):
    atlas = _atlas(tmp_path, [6, 5])
    result = cluster_styles(atlas.style)
    placed = export_folders(atlas, plan_folders(atlas.paths, result), tmp_path / "out")
    assert placed.placed == len(atlas) and not placed.failed
    files = [p for p in (tmp_path / "out").rglob("*") if p.is_file()]
    names = sorted(p.name for p in files)
    assert "same.png" in names and "same_2.png" in names
    assert "img0.txt" in names
    assert (tmp_path / "src" / "img0.png").exists()  # sources untouched


def test_export_link_mode(tmp_path):
    atlas = _atlas(tmp_path, [6, 5])
    folders = plan_folders(atlas.paths, cluster_styles(atlas.style))
    export_folders(atlas, folders, tmp_path / "out", mode="link")
    linked = next((tmp_path / "out").rglob("img1.png"))
    assert os.stat(linked).st_nlink >= 1


def test_write_table(tmp_path):
    atlas = _atlas(tmp_path, [6, 5])
    csv_path, json_path = write_table(atlas, cluster_styles(atlas.style), tmp_path / "out")
    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == len(atlas)
    assert b"\r\r\n" not in csv_path.read_bytes()  # no blank lines in Excel
    summary = json.loads(json_path.read_text(encoding="utf-8"))
    assert sum(c["size"] for c in summary["clusters"]) + summary["unassigned"] == len(atlas)


def test_render_html_cannot_be_broken_by_file_names():
    payload = {"title": "x", "points": [{"n": "</script><script>alert(1)</script>.png"}]}
    html = render_html(payload)
    data = html.split('id="atlas-data" type="application/json">')[1].split("</script>")[0]
    assert "<" not in data and "alert(1)" in data
    assert html.count("</script>") == html.count("<script")


def test_resize_pos_embed_keeps_224_and_grows_to_336():
    import torch

    from styleatlas.encoder import resize_pos_embed

    pos = torch.randn(1 + 16 * 16, 8)
    assert resize_pos_embed(pos, 224) is pos
    big = resize_pos_embed(pos, 336)
    assert big.shape == (1 + 24 * 24, 8)
    assert torch.equal(big[0], pos[0])  # class token untouched


def test_file_time_sources(tmp_path):
    from styleatlas.images import file_time

    p = _img(tmp_path / "artist__12345678_p0.png")
    assert file_time(p, "name") == 12345678.0
    assert file_time(_img(tmp_path / "no_id.png"), "name") is None
    assert file_time(p, "mtime") > 0
    assert file_time(p, "none") is None


def test_trigger_captions_are_written_in_the_export_only(tmp_path):
    from styleatlas.export import trigger_of

    atlas = _atlas(tmp_path, [6, 5])
    result = cluster_styles(atlas.style)
    folders = plan_folders(atlas.paths, result, "kohya", "artistX", "auto")
    src_caption = tmp_path / "src" / "img0.txt"
    before = src_caption.read_text()
    done = export_folders(
        atlas, folders, tmp_path / "out", mode="link", trigger_captions=True, layout="kohya"
    )
    assert src_caption.read_text() == before  # never edited through a hard link
    i0 = next(i for i, p in enumerate(atlas.paths) if p.name == "img0.png")
    exported = done.folder / folders[i0] / "img0.txt"
    trigger0 = trigger_of(folders[i0], "kohya")
    assert trigger0.startswith("artistX_") and exported.read_text().startswith(
        trigger0 + ", a caption"
    )
    i1 = next(i for i, p in enumerate(atlas.paths) if p.name == "img1.png")
    assert (done.folder / folders[i1] / "img1.txt").read_text() == trigger_of(folders[i1], "kohya")
    assert trigger_of("11_artist X_style02", "kohya") == "artist X_style02"
    assert trigger_of("_duplicates") is None and trigger_of("style_01") == "style_01"
    assert trigger_of("2024_summer") == "2024_summer"  # a plain folder is its own trigger


def test_trigger_captions_keep_non_utf8_and_do_not_double_prefix(tmp_path):
    atlas = _atlas(tmp_path, [6, 5])
    src = tmp_path / "src"
    (src / "img2.txt").write_bytes("中文標註".encode("big5"))
    (src / "img3.txt").write_text("trig, 1girl", encoding="utf-8")
    folders = ["trig"] * len(atlas)  # one plain folder, trigger = folder name
    done = export_folders(atlas, folders, tmp_path / "out", trigger_captions=True)
    assert (done.folder / "trig" / "img2.txt").read_bytes() == "中文標註".encode("big5")
    assert (done.folder / "trig" / "img3.txt").read_text(encoding="utf-8") == "trig, 1girl"


def test_cached_thumbnails_are_reused_and_refreshed(tmp_path, monkeypatch):
    import os

    from styleatlas.images import cached_thumbnail

    monkeypatch.setenv("STYLE_ATLAS_CACHE", str(tmp_path / "cache"))
    big = tmp_path / "big.jpg"
    Image.new("RGB", (2400, 1600), (10, 120, 200)).save(big, quality=90)
    first = cached_thumbnail(big, 128)
    assert Image.open(io.BytesIO(first)).size == (128, 85)
    assert len(list((tmp_path / "cache" / "thumbs").rglob("*.webp"))) == 1
    assert cached_thumbnail(big, 128) == first  # served from disk
    Image.new("RGB", (800, 800), (200, 10, 10)).save(big)
    os.utime(big, ns=(1, 1))  # a changed file must not reuse the old thumbnail
    assert Image.open(io.BytesIO(cached_thumbnail(big, 128))).size == (128, 128)


def test_cluster_output_places_each_group_on_the_timeline(tmp_path):
    from styleatlas.cli_lora import _timeline, _when

    atlas = _atlas(tmp_path, [3, 3])
    for i, p in enumerate(atlas.paths):  # ids in the names give the order
        p.rename(p.with_name(f"art__{100000 + i}.png"))
    atlas = type(atlas)(
        atlas.root,
        [p.with_name(f"art__{100000 + i}.png") for i, p in enumerate(atlas.paths)],
        atlas.style,
        atlas.content,
        atlas.signature,
    )
    pos = _timeline(atlas, "name")
    assert pos[0] == 0.0 and pos[-1] == 1.0
    assert _when(pos, [0, 1, 2]).strip().startswith("when  20%")
    assert _timeline(atlas, "none") is None and _when(None, [0]) == ""


def test_tags_are_removed_in_the_exported_captions_only(tmp_path):
    from styleatlas.export import parse_tags

    atlas = _atlas(tmp_path, [6, 5])
    src = tmp_path / "src" / "img0.txt"
    src.write_text("1girl, Monochrome, rough_sketch, smile, monochrome background", "utf-8")
    result = cluster_styles(atlas.style)
    strip = parse_tags("monochrome, rough sketch")
    i0 = next(i for i, p in enumerate(atlas.paths) if p.name == "img0.png")
    i1 = next(i for i, p in enumerate(atlas.paths) if p.name == "img1.png")

    folders = plan_folders(atlas.paths, result)
    done = export_folders(atlas, folders, tmp_path / "plain", strip_tags=strip)
    assert (done.folder / folders[i0] / "img0.txt").read_text() == (
        "1girl, smile, monochrome background"  # whole tags only
    )
    assert not (done.folder / folders[i1] / "img1.txt").exists()  # no caption made without one

    folders = plan_folders(atlas.paths, result, "kohya", "a")
    done = export_folders(
        atlas, folders, tmp_path / "kohya", trigger_captions=True, layout="kohya", strip_tags=strip
    )
    text = (done.folder / folders[i0] / "img0.txt").read_text()
    assert text.endswith(", 1girl, smile, monochrome background") and text.startswith("a_style")
    assert src.read_text(encoding="utf-8").startswith("1girl, Monochrome")  # source untouched
