"""The export dialog's choices: only the ticked groups, one training set per group or one for all,
a destination of the user's choosing, and opening what was written."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from styleatlas.atlas import Atlas, EncodeOptions
from styleatlas.serve import StyleAtlasApp

from .conftest import make_blobs


def _app(tmp_path, sizes=(8, 7, 6)):
    x, _ = make_blobs(list(sizes))
    folder = tmp_path / "pics"
    folder.mkdir()
    paths = []
    for i in range(len(x)):
        p = folder / f"img{i}.png"
        Image.new("RGB", (16, 16), (i, 0, 0)).save(p)
        paths.append(p)
    app = StyleAtlasApp(Atlas(folder, paths, x, x, "sig"), EncodeOptions(device="cpu"), "pca")
    app.regroup({"threshold": 0.5})
    assert app.clustering.n_clusters == len(sizes)
    return app


def _images(folder: Path) -> set[str]:
    return {p.name for p in folder.rglob("*.png")}


def test_only_the_ticked_group_is_written(tmp_path):
    app = _app(tmp_path)
    g = app.clustering.clusters[1]
    done = app.export({"groups": [g.id], "name": "art"})
    root = Path(done["folder"])
    assert root == app.out_dir / "art"
    assert _images(root) == {f"img{i}.png" for i in g.members}
    assert done["training"] == g.size and done["placed"] == g.size


def test_one_training_set_per_group_with_its_own_trigger(tmp_path):
    app = _app(tmp_path)
    a, b = app.clustering.clusters[0], app.clustering.clusters[2]
    body = {
        "groups": [a.id, b.id],
        "separate": True,
        "name": "art",
        "layout": "kohya",
        "trigger": True,
    }
    plan = app.export_plan(body)
    done = app.export(body)
    names = [d["name"] for d in done["datasets"]]
    assert names == [d["name"] for d in plan["datasets"]] == ["art_style_01", "art_style_03"]
    assert Path(done["folder"]) == app.out_dir  # several sets: their parent folder
    for d, g in zip(done["datasets"], (a, b), strict=True):
        root = Path(d["folder"])
        (inner,) = [p for p in root.iterdir() if p.is_dir()]
        assert inner.name.endswith(f"_{d['name']}") and inner.name.split("_")[0].isdigit()
        assert _images(root) == {f"img{i}.png" for i in g.members}
        assert (root / "dataset_config.toml").exists()  # each set trains on its own
        caption = next(inner.glob("*.txt")).read_text(encoding="utf-8")
        assert caption.startswith(d["name"])
    assert plan["triggers"] == done["triggers"] == names
    assert done["steps"] is None and all(d["steps"] for d in done["datasets"])


def test_plain_sets_keep_the_pictures_at_the_top_with_the_set_as_trigger(tmp_path):
    app = _app(tmp_path)
    g = app.clustering.clusters[0]
    done = app.export({"groups": [g.id], "separate": True, "name": "art", "trigger": True})
    root = Path(done["datasets"][0]["folder"])
    assert {p.name for p in root.glob("*.png")} == {f"img{i}.png" for i in g.members}
    assert (root / f"img{g.members[0]}.txt").read_text(encoding="utf-8").startswith("art_style_01")


def test_a_ticked_group_trains_however_small_and_unticked_ones_are_left_alone(tmp_path):
    app = _app(tmp_path)
    small = app.clustering.clusters[2]
    for i in small.members[2:]:  # two images left: too few without a choice, ticked: trained
        app.move({"i": i, "to": -1, "rev": app.revision})
    plan = app.export_plan({"groups": [small.id]})
    assert plan["training"] == 2 and plan["small_groups"] == 0
    assert [r["id"] for r in plan["groups"]] == [small.id]
    assert app.export_plan({"groups": []})["training"] == 0
    with pytest.raises(ValueError):
        app.export({"groups": []})


def test_a_copy_is_kept_among_the_ticked_groups(tmp_path):
    app = _app(tmp_path)
    a, b = app.clustering.clusters[0], app.clustering.clusters[1]
    pair = [[a.members[0], b.members[0]]]  # the same picture in two groups
    app.layout = replace(app.layout, duplicates=pair)
    app.kept_copies = {a.members[0]}  # kept in the group that is not exported
    plan = app.export_plan({"groups": [b.id]})
    assert plan["training"] == b.size  # b's copy is not set aside for one that stays home
    both = app.export_plan({"groups": [a.id, b.id]})
    assert both["training"] == a.size + b.size - 1


def test_the_destination_is_checked(tmp_path):
    app = _app(tmp_path)
    g = app.clustering.clusters[0].id
    out = tmp_path / "datasets"
    done = app.export({"groups": [g], "dest": str(out), "name": "art"})
    assert Path(done["folder"]) == out / "art"
    again = app.export_plan({"groups": [g], "dest": str(out), "name": "art"})
    assert again["datasets"][0]["name"] == "art_2"  # taken: the next free name
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    for bad in ("relative/path", str(app.atlas.root / "inside"), str(tmp_path / "file.txt"), 5):
        with pytest.raises(ValueError):
            app.export_plan({"groups": [g], "dest": bad})
    for bad in ([99], ["0"], [True], "0"):
        with pytest.raises(ValueError):
            app.export_plan({"groups": bad})
    with pytest.raises(ValueError):
        app.export_plan({"separate": True})  # one set per group needs the groups


def test_open_export_opens_only_the_last_export(tmp_path, monkeypatch):
    import os

    app = _app(tmp_path)
    opened = []
    monkeypatch.setattr(os, "startfile", opened.append, raising=False)
    monkeypatch.setattr("styleatlas.serve_export.subprocess.Popen", lambda a: opened.append(a[-1]))
    with pytest.raises(ValueError):
        app.open_export({})
    done = app.export({"groups": [app.clustering.clusters[0].id]})
    assert app.open_export({"folder": "C:/Windows"})["folder"] == done["folder"]
    assert [str(f) for f in opened] == [done["folder"]]


def test_one_set_per_group_keeps_names_apart_however_long_the_name(tmp_path):
    app = _app(tmp_path)
    groups = [c.id for c in app.clustering.clusters]
    plan = app.export_plan({"groups": groups, "separate": True, "name": "n" * 70, "trigger": True})
    names = [d["name"] for d in plan["datasets"]]
    assert len(set(names)) == len(names) == len(groups)
    assert len(plan["triggers"]) == len(groups)


def test_a_file_where_a_set_would_go_takes_the_next_name(tmp_path):
    app = _app(tmp_path)
    out = tmp_path / "datasets"
    out.mkdir()
    (out / "art").write_text("not a folder", encoding="utf-8")
    plan = app.export_plan(
        {"groups": [app.clustering.clusters[0].id], "dest": str(out), "name": "art"}
    )
    assert plan["datasets"][0]["name"] == "art_2"


def test_typed_trigger_words_name_the_sets_and_the_folders(tmp_path):
    app = _app(tmp_path)
    a, b = app.clustering.clusters[0].id, app.clustering.clusters[1].id
    body = {
        "groups": [a, b],
        "separate": True,
        "layout": "kohya",
        "trigger": True,
        "words": {str(a): "artistx early", str(b): ""},
    }
    plan = app.export_plan(body)
    assert [d["name"] for d in plan["datasets"]] == ["artistx early", "pics_style_02"]
    assert [r["word"] for r in plan["groups"]] == ["artistx early", "pics_style_02"]
    done = app.export(body)
    inner = next(p for p in Path(done["datasets"][0]["folder"]).iterdir() if p.is_dir())
    assert inner.name.endswith("_artistx early")
    one = app.export_plan({**body, "separate": False})
    folders = {r["word"] for r in one["groups"]}
    assert "artistx early" in folders and len(folders) == 2


def test_two_groups_cannot_share_a_typed_trigger_word(tmp_path):
    app = _app(tmp_path)
    a, b, c = (g.id for g in app.clustering.clusters)
    for separate in (True, False):
        with pytest.raises(ValueError):
            app.export_plan(
                {"groups": [a, b], "separate": separate, "words": {str(a): "x", str(b): "X"}}
            )
    clash = app.export_plan(
        {"groups": [a, b], "separate": True, "words": {str(a): "pics_style_02"}}
    )
    assert [d["name"] for d in clash["datasets"]] == ["pics_style_02", "pics_style_02_2"]
    with pytest.raises(ValueError):
        app.export_plan({"groups": [a], "words": {str(c): "y"}})  # not a ticked group
    with pytest.raises(ValueError):
        app.export_plan({"words": {str(a): "y"}})  # words need the ticked groups


def test_the_unassigned_folder_name_is_not_a_trigger_word(tmp_path):
    app = _app(tmp_path)
    g = app.clustering.clusters[0].id
    with pytest.raises(ValueError):
        app.export_plan({"groups": [g], "words": {str(g): "Unassigned"}})
