from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from styleatlas.atlas import Atlas
from styleatlas.cluster import cluster_styles
from styleatlas.dataset import plan_folders
from styleatlas.encoder import square_crops
from styleatlas.export import export_folders, export_paths, write_table
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
    folders = plan_folders(atlas.paths, result)
    placed = export_folders(atlas, folders, tmp_path / "out")
    assert placed.placed == len(atlas) and not placed.failed
    training = sum(not (f.startswith("_") or f == "unassigned") for f in folders)
    assert placed.small_training == training  # the test images are tiny
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


@pytest.mark.parametrize("mode", ["copy", "link"])
def test_export_writes_photos_turned_only_by_exif_upright(tmp_path, mode):
    src = tmp_path / "src"
    src.mkdir()
    photo = src / "phone.jpg"
    stored = Image.new("RGB", (60, 40), (200, 30, 30))  # stored sideways: wide
    stored.paste((30, 30, 200), (0, 0, 10, 40))  # a blue band on the stored left edge
    exif = Image.Exif()
    exif[0x0112] = 6  # viewers turn it 90 degrees clockwise: tall
    stored.save(photo, exif=exif, quality=95)
    before = photo.read_bytes()
    x = np.eye(1, 4, dtype=np.float32)
    atlas = Atlas(src, [photo], x, x, "sig")
    done = export_folders(atlas, ["style_01"], tmp_path / "out", mode=mode)
    assert done.placed == 1 and done.upright == 1
    with Image.open(tmp_path / "out" / "style_01" / "phone.jpg") as out:
        assert out.size == (40, 60)  # upright in its pixels
        assert out.getexif().get(0x0112, 1) == 1
        top = out.convert("RGB").getpixel((20, 2))
    assert top[2] > 150 and top[0] < 100  # the blue band is now on top, as a viewer shows it
    assert photo.read_bytes() == before  # the source is untouched


def test_writing_upright_keeps_the_encoding_and_leaves_animations_alone(tmp_path):
    from PIL import JpegImagePlugin, PngImagePlugin

    from styleatlas.export import _write_upright

    exif = Image.Exif()
    exif[0x0112] = 6
    jpeg = tmp_path / "fine.jpg"
    Image.new("RGB", (40, 30), (200, 40, 40)).save(jpeg, quality=100, subsampling=0, exif=exif)
    assert _write_upright(jpeg, tmp_path / "fine_out.jpg")
    with Image.open(tmp_path / "fine_out.jpg") as out:
        assert out.size == (30, 40) and JpegImagePlugin.get_sampling(out) == 0  # still 4:4:4

    png = tmp_path / "prompt.png"
    text = PngImagePlugin.PngInfo()
    text.add_text("parameters", "1girl, masterpiece")
    Image.new("RGB", (40, 30)).save(png, pnginfo=text, exif=exif)
    assert _write_upright(png, tmp_path / "prompt_out.png")
    with Image.open(tmp_path / "prompt_out.png") as out:
        assert out.text.get("parameters") == "1girl, masterpiece"

    anim = tmp_path / "moving.webp"
    frames = [Image.new("RGB", (40, 30), c) for c in ((255, 0, 0), (0, 0, 255))]
    frames[0].save(anim, save_all=True, append_images=frames[1:], exif=exif)
    assert not _write_upright(anim, tmp_path / "moving_out.webp")  # copied as it is instead
    assert not (tmp_path / "moving_out.webp").exists()


def test_the_upright_copy_wins_a_tie_between_duplicates(tmp_path):
    from styleatlas.dataset import best_in_group

    same = Image.new("RGB", (60, 40), (90, 90, 90))
    exif = Image.Exif()
    exif[0x0112] = 6
    same.save(tmp_path / "a_turned.jpg", exif=exif, quality=95)
    same.save(tmp_path / "b_plain.jpg", quality=95)
    paths = [tmp_path / "a_turned.jpg", tmp_path / "b_plain.jpg"]
    assert best_in_group(paths) == 1


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
    from styleatlas.cli_lora import _when
    from styleatlas.images import timeline

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
    pos = timeline(atlas.paths, "name")
    assert pos[0] == 0.0 and pos[-1] == 1.0
    assert _when(pos, [0, 1, 2]).strip().startswith("when  20%")
    assert timeline(atlas.paths, "none") is None and _when(None, [0]) == ""


def test_a_time_of_zero_is_a_time():
    from styleatlas.images import file_times

    times = file_times([Path("a_00000.png"), Path("b_00007.png"), Path("c.png")], "name")
    assert times[0] == 0.0 and times[1] == 7.0 and np.isnan(times[2])


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


def test_results_go_next_to_the_folder_never_inside_it(tmp_path):
    from styleatlas.export import output_dir

    assert output_dir(tmp_path / "artistX") == (tmp_path / "artistX_style_atlas").resolve()
    drive = output_dir(tmp_path.parents[len(tmp_path.parents) - 1])  # a whole drive has no name
    assert drive.name.endswith("_style_atlas") and drive.name != "_style_atlas"


@pytest.mark.parametrize(
    "name", ["畫師 #1: x", "a\x7fb", "a\x85b", "a\u2028b", "emoji 😀", 'q"t', "t\tx"]
)
def test_folder_names_survive_toml_and_yaml(name):
    from styleatlas.export import _quoted

    tomllib = pytest.importorskip("tomllib")
    yaml = pytest.importorskip("yaml")
    text = str(Path("D:/lora") / name)
    assert tomllib.loads("k = " + _quoted(Path(text)))["k"] == text
    assert yaml.safe_load("k: " + _quoted(Path(text)))["k"] == text


def test_folder_atlas_has_one_point_per_sub_folder(tmp_path):
    from styleatlas.atlas import folder_atlas

    x, labels = make_blobs([5, 4, 6])
    paths = []
    for i, k in enumerate(labels):
        folder = tmp_path / f"artist{k}" if i != 0 else tmp_path  # image 0 is loose at the top
        folder.mkdir(exist_ok=True)
        paths.append(folder / f"img{i}.png")
    atlas = Atlas(tmp_path, paths, x, x, "sig", looks=np.ones((len(x), 6), np.float32))
    folders = folder_atlas(atlas)
    assert [p.parent.name for p in folders.paths] == ["artist0", "artist1", "artist2"]
    assert folders.style.shape == (3, x.shape[1]) and folders.looks.shape == (3, 6)
    assert np.allclose(np.linalg.norm(folders.style, axis=1), 1.0)


def test_docs_have_no_stray_control_characters():
    """A mangled backslash (\a, \b ...) in an edit leaves a control character behind."""
    root = Path(__file__).resolve().parents[1]
    for doc in [root / "README.md", root / "CHANGELOG.md", *sorted((root / "docs").glob("*.md"))]:
        text = doc.read_text(encoding="utf-8")
        bad = [i for i, ch in enumerate(text) if ord(ch) < 32 and ch not in "\n\t"]
        assert not bad, f"{doc.name}: control character near {text[max(0, bad[0] - 30) : bad[0]]!r}"


def test_images_are_loaded_ahead_in_batches_and_in_order():
    from styleatlas.atlas import _ahead

    out = list(_ahead(list(range(10)), 4, lambda x: x * x, 3))
    assert [batch for batch, _ in out] == [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9]]
    assert [loaded for _, loaded in out] == [[0, 1, 4, 9], [16, 25, 36, 49], [64, 81]]
    assert list(_ahead([], 4, abs, 2)) == []


def test_a_failed_load_stops_the_loop_ahead(tmp_path):
    from styleatlas.atlas import _ahead

    def load(x):
        if x == 5:
            raise MemoryError("too big")
        return x

    with pytest.raises(MemoryError):
        list(_ahead(list(range(10)), 4, load, 2))


def test_sixteen_bit_grey_images_are_scaled_not_clipped(tmp_path):
    from styleatlas.quality import softness_of_file

    ramp = np.linspace(0, 65535, 512 * 512).reshape(512, 512).astype(np.uint16)
    wide, narrow = tmp_path / "wide.png", tmp_path / "narrow.png"
    Image.fromarray(ramp).save(wide)  # opens as I;16
    Image.fromarray((ramp // 257).astype(np.uint8)).save(narrow)
    assert Image.open(wide).mode.startswith("I")
    a, b = np.asarray(load_rgb(wide), dtype=float), np.asarray(load_rgb(narrow), dtype=float)
    assert abs(a.mean() - b.mean()) < 1.0  # was 254.5 against 127 before
    assert softness_of_file(wide) == pytest.approx(softness_of_file(narrow), abs=0.02)


def test_jfif_files_are_found_and_served_as_jpeg(tmp_path):
    from styleatlas.images import IMAGE_TYPES

    Image.new("RGB", (32, 32), (200, 10, 10)).save(tmp_path / "from_x.jfif", format="JPEG")
    assert [p.name for p in find_images(tmp_path)] == ["from_x.jfif"]
    assert load_rgb(tmp_path / "from_x.jfif").size == (32, 32)
    assert IMAGE_TYPES[".jfif"] == "image/jpeg" and IMAGE_TYPES[".webp"] == "image/webp"


def test_mac_zip_leftovers_are_not_images(tmp_path):
    Image.new("RGB", (8, 8)).save(tmp_path / "a.png")
    (tmp_path / "._a.png").write_bytes(b"\x00\x05\x16\x07 AppleDouble")
    (tmp_path / "__MACOSX").mkdir()
    (tmp_path / "__MACOSX" / "._a.png").write_bytes(b"\x00\x05\x16\x07")
    assert [p.name for p in find_images(tmp_path)] == ["a.png"]


def test_pad_counts_chinese_characters_as_two_columns():
    from styleatlas.lang import pad

    assert pad("style_01", 12) == "style_01    " and pad("早期畫風", 12) == "早期畫風    "
    assert pad("a_very_long_group_name", 4).endswith(" ")  # always one space after


def test_wrap_fits_chinese_help_by_display_width():
    from styleatlas.lang import columns, wrap

    text = "同樣的角色出現在很多畫風裡時用（--ignore-characters 通常更好）；混了不同畫師時不要用"
    for width in (12, 20, 31, 40):
        lines = wrap(text, width)
        for line in lines:  # only kept punctuation, or a word wider than the line, overhangs
            assert columns(line.rstrip("，；）")) <= width or "--ignore-characters" in line
        assert "".join(lines).replace(" ", "") == text.replace(" ", "")
        assert not any(line[0] in "，。；）" for line in lines)
        assert not any(line[-1] == "（" for line in lines)
        assert any("--ignore-characters" in line for line in lines)  # words are not split
    assert wrap("", 10) == []


def test_message_language_follows_the_system_unless_set(monkeypatch):
    from styleatlas import lang

    detect = lang._system_is_chinese.__wrapped__  # without its cache
    monkeypatch.delenv("STYLE_ATLAS_LANG")
    monkeypatch.setattr(lang, "_system_is_chinese", lambda: True)
    assert lang.chinese() and lang.tr("a", "乙") == "乙"
    monkeypatch.setenv("STYLE_ATLAS_LANG", "en")
    assert not lang.chinese()
    monkeypatch.setattr(lang.sys, "platform", "linux")  # elsewhere the locale decides
    monkeypatch.setattr(lang.locale, "getlocale", lambda: ("zh_TW", "UTF-8"))
    assert detect()
    monkeypatch.setattr(lang.locale, "getlocale", lambda: ("en_US", "UTF-8"))
    assert not detect()


def test_wide_grey_modes_are_scaled_to_eight_bits():
    from styleatlas.images import to_8bit

    ramp = np.linspace(0, 1, 64 * 64).reshape(64, 64)
    floats = Image.fromarray(ramp.astype(np.float32))  # mode F, 0-1
    ints = Image.fromarray((ramp * 65535).astype(np.int32))  # mode I, 16-bit values
    small = Image.fromarray((ramp * 255).astype(np.int32))  # mode I, 8-bit values
    for im in (floats, ints, small):
        out = np.asarray(to_8bit(im), dtype=float)
        assert abs(out.mean() - 127.5) < 1.5, im.mode
    rgb = Image.new("RGB", (4, 4))
    assert to_8bit(rgb) is rgb  # other modes untouched


def test_an_unknown_language_setting_falls_back_to_the_system(monkeypatch):
    from styleatlas import lang

    monkeypatch.setattr(lang, "_system_is_chinese", lambda: True)
    for value, chinese in (("auto", True), ("zh-TW", True), ("en", False), ("", True)):
        monkeypatch.setenv("STYLE_ATLAS_LANG", value)
        assert lang.chinese() is chinese, value


def test_export_respells_tags_only_in_the_copies(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    image = src / "a.png"
    Image.new("RGB", (16, 16)).save(image)
    image.with_suffix(".txt").write_text("1girl, long_hair, Smile", encoding="utf-8")
    x = np.eye(1, 4, dtype=np.float32)
    done = export_folders(
        Atlas(src, [image], x, x, "sig"),
        ["style_01"],
        tmp_path / "out",
        respell={"long hair": "long hair"},
    )
    assert done.placed == 1
    assert (tmp_path / "out" / "style_01" / "a.txt").read_text(
        encoding="utf-8"
    ) == "1girl, long hair, Smile"
    assert image.with_suffix(".txt").read_text(encoding="utf-8") == "1girl, long_hair, Smile"


def test_file_names_with_dates_sort_by_date():
    from styleatlas.images import file_time

    names = ["2023-05-12 art.png", "IMG_2023_05_12.jpg", "20230601_1530.jpg", "2022.12.31.png"]
    times = [file_time(Path(n), "name") for n in names]
    assert times == [20230512.0, 20230512.0, 20230601.0, 20221231.0]
    assert file_time(Path("2023-13-40.png"), "name") is None  # not a date, too few digits
    assert file_time(Path("12345678_p0.png"), "name") == 12345678.0  # ids as before


def test_export_paths_keeps_names_apart_and_stays_inside(tmp_path):
    a, b = _img(tmp_path / "a" / "img.png"), _img(tmp_path / "b" / "img.png", color=(1, 2, 3))
    done = export_paths([a, b, a], ["10_x/sub", "10_x/sub", "../escape"], tmp_path / "o")
    assert sorted(p.name for p in (tmp_path / "o" / "10_x" / "sub").iterdir()) == [
        "img.png",
        "img_2.png",
    ]
    assert done.placed == 2 and "outside the export" in done.failed[0][1]
    assert export_paths([a], [""], tmp_path / "top").failed  # the top only when allowed
    assert not export_paths([a], [""], tmp_path / "top2", allow_top=True).failed
    assert (tmp_path / "top2" / "img.png").is_file()
