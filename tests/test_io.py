from __future__ import annotations

import csv
import json
import os

import numpy as np
from PIL import Image

from styleatlas.atlas import Atlas
from styleatlas.cluster import cluster_styles
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
    placed = export_folders(atlas, result, tmp_path / "out")
    assert placed.placed == len(atlas) and not placed.failed
    files = [p for p in (tmp_path / "out").rglob("*") if p.is_file()]
    names = sorted(p.name for p in files)
    assert "same.png" in names and "same_2.png" in names
    assert "img0.txt" in names
    assert (tmp_path / "src" / "img0.png").exists()  # sources untouched


def test_export_link_mode(tmp_path):
    atlas = _atlas(tmp_path, [6, 5])
    export_folders(atlas, cluster_styles(atlas.style), tmp_path / "out", mode="link")
    linked = next((tmp_path / "out").rglob("img1.png"))
    assert os.stat(linked).st_nlink >= 1


def test_write_table(tmp_path):
    atlas = _atlas(tmp_path, [6, 5])
    csv_path, json_path = write_table(atlas, cluster_styles(atlas.style), tmp_path / "out")
    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == len(atlas)
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
