"""The web app's hand edits on groups (names, undo, saved groups, moves, placing new images),
called on the app object directly; the HTTP side is in test_serve.py."""

from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image

from styleatlas.atlas import Atlas, EncodeOptions
from styleatlas.serve import StyleAtlasApp

from .conftest import make_blobs
from .test_serve import _app


def test_undo_restores_names_and_the_space_after_a_switch(tmp_path):
    x, _ = make_blobs([8, 7])
    paths = []
    for i in range(len(x)):
        p = tmp_path / f"img{i}.png"
        Image.new("RGB", (16, 16), (i, 0, 0)).save(p)
        paths.append(p)
    app = StyleAtlasApp(Atlas(tmp_path, paths, x, x, "sig"), EncodeOptions(device="cpu"), "pca")
    app.regroup({"threshold": 0.5})
    app.rename({"group": 0, "name": "first", "rev": app.revision})
    app.rename({"group": 0, "name": "second", "rev": app.revision})
    app.undo({"rev": app.revision})
    assert app.names_by_group() == {0: "first"}
    app.merge({"from": 1, "into": 0, "rev": app.revision})
    app.set_space({"space": "characters"})
    app.undo({"rev": app.revision})  # back to the old space, hand edit and name included
    assert app.space.name == "plain" and app.clustering.n_clusters == 1
    assert app.names_by_group() == {0: "first"}


def test_a_groups_file_from_before_spaces_keeps_its_neutralize_count(tmp_path):
    app, atlas = _app(tmp_path)
    app.regroup({"threshold": 0.5})
    path = app._groups_path
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["space"]
    for k, expected in ((1, "neutralize-1"), (0, "plain"), (99, "plain")):
        path.write_text(json.dumps({**data, "neutralize": k}), encoding="utf-8")
        again = StyleAtlasApp(atlas, EncodeOptions(device="cpu"), "pca")
        assert again.restored and again.space.name == expected  # 99: invalid, the default


def test_names_follow_their_images_through_edits(tmp_path):
    app, _ = _app(tmp_path, (8, 7, 6))
    app.regroup({"threshold": 0.5})
    assert app.clustering.n_clusters == 3
    sizes = {c.id: c.size for c in app.clustering.clusters}
    app.rename({"group": 0, "name": "big", "rev": app.revision})
    app.rename({"group": 2, "name": "small", "rev": app.revision})
    app.merge({"from": 0, "into": 2, "rev": app.revision})  # the target's name wins
    assert list(app.names_by_group().values()) == ["small"]
    assert app.clustering.clusters[0].size == sizes[0] + sizes[2]
    app.undo({"rev": app.revision})
    app.split({"group": 0, "rev": app.revision})  # the larger half keeps the name
    named = next(g for g, n in app.names_by_group().items() if n == "big")
    assert app.clustering.clusters[named].size >= 4


def test_failed_or_unchanged_renames_add_no_undo_step(tmp_path):
    app, _ = _app(tmp_path)
    app.regroup({"threshold": 0.5})
    steps = len(app._history)
    with pytest.raises(ValueError):
        app.rename({"group": 0, "name": " ... ", "rev": app.revision})
    app.rename({"group": 0, "name": "a", "rev": app.revision})
    app.rename({"group": 0, "name": "a", "rev": app.revision})
    assert len(app._history) == steps + 1
    with pytest.raises(ValueError, match="already called"):
        app.rename({"group": 1, "name": "A", "rev": app.revision})
    with pytest.raises(ValueError, match="reload"):
        app.undo({"rev": app.revision + 1})
    for i in range(40):
        app.rename({"group": 0, "name": f"n{i}", "rev": app.revision})
    assert len(app._history) == 30


def test_a_damaged_groups_file_is_set_aside(tmp_path):
    app, atlas = _app(tmp_path)
    app.regroup({"threshold": 0.5})
    path = app._groups_path
    data = json.loads(path.read_text(encoding="utf-8"))
    data["labels"][next(iter(data["labels"]))] = "x"
    path.write_text(json.dumps(data), encoding="utf-8")
    again = StyleAtlasApp(atlas, EncodeOptions(device="cpu"), "pca")
    assert not again.restored
    assert len(list(path.parent.glob("groups.json.*.bad"))) == 1


def test_the_saved_space_and_names_come_back(tmp_path):
    app, atlas = _app(tmp_path)
    app.regroup({"threshold": 0.5})
    app.rename({"group": 1, "name": "second", "rev": app.revision})
    app.set_space({"space": "neutralize-1"})
    again = StyleAtlasApp(atlas, EncodeOptions(device="cpu"), "pca")
    assert again.restored and again.space.name == "neutralize-1"
    assert again.names_by_group() == app.names_by_group()
    assert (again.clustering.labels == app.clustering.labels).all()


def test_web_export_reports_groups_too_small_to_keep(tmp_path):
    app, _ = _app(tmp_path)
    app.regroup({"threshold": 0.5})
    for i in app.clustering.clusters[1].members[2:]:  # leave 2 images in the smaller group
        app.move({"i": i, "to": -1, "rev": app.revision})
    small = app.clustering.clusters[1].id
    done = app.export({"mode": "copy"})
    assert done["small_groups"] == 1 and done["small_ids"] == [small]
    kept = sum(c.size for c in app.clustering.clusters if c.size >= 3)  # no duplicates here
    assert done["training"] == kept < len(app.atlas)


def test_several_images_are_excluded_or_moved_at_once(tmp_path):
    app, _ = _app(tmp_path, (8, 7))
    app.regroup({"threshold": 0.5})
    assert app.exclude({"items": [1, 2, 2, 3]})["excluded"] == [1, 2, 3]
    assert app.exclude({"items": [2, 3], "excluded": False})["excluded"] == [1]
    for bad in ([], [99], ["1"], [True], "1,2"):
        with pytest.raises(ValueError):
            app.exclude({"items": bad})
    target = int(app.clustering.labels[-1])
    moved = [0, 1, 2]
    app.move({"items": moved, "to": target, "rev": app.revision})
    labels = app.clustering.labels  # group ids are renumbered after an edit
    assert all(labels[i] == labels[-1] for i in moved)
    app.undo({"rev": app.revision})  # the whole batch is one step
    labels = app.clustering.labels
    assert all(labels[i] != labels[-1] for i in moved)


def test_dropped_images_are_placed_in_a_group_or_called_outside(tmp_path):
    app, _ = _app(tmp_path, (12, 10))
    app.regroup({"threshold": 0.5})
    inside = app.atlas.style[:2]  # images of the first group itself
    rng = np.random.default_rng(3)
    stranger = rng.normal(size=(1, inside.shape[1]))
    stranger /= np.linalg.norm(stranger)
    got = app.fit(np.vstack([inside, stranger]))
    first = int(app.clustering.labels[0])
    assert [g["group"] for g in got[:2]] == [first, first] and got[0]["fits"] and got[1]["fits"]
    assert not got[2]["fits"]


def test_unassigned_images_are_put_back_only_where_they_fit(tmp_path):
    x, _ = make_blobs([8, 7, 1])
    x[0] = x[1:8].mean(axis=0) / np.linalg.norm(x[1:8].mean(axis=0))  # the heart of style A
    paths = []
    for i in range(len(x)):
        p = tmp_path / f"img{i}.png"
        Image.new("RGB", (16, 16), (i, 0, 0)).save(p)
        paths.append(p)
    app = StyleAtlasApp(Atlas(tmp_path, paths, x, x, "sig"), EncodeOptions(device="cpu"), "pca")
    app.move({"items": [0], "to": -1, "rev": app.revision})
    assert app.clustering.labels[0] == -1 and app.clustering.labels[15] == -1  # 15: style C alone
    result = app.place_unassigned({"rev": app.revision})
    assert result["moved"] == 1 and result["left"] == 1
    assert app.clustering.labels[0] == app.clustering.labels[1] != -1
    assert app.clustering.labels[15] == -1
    app.undo({"rev": app.revision})
    assert app.clustering.labels[0] == -1
    app.exclude({"items": [0, 15]})
    with pytest.raises(ValueError):  # excluded images are not placed
        app.place_unassigned({"rev": app.revision})


def test_the_web_app_can_group_by_artist_and_keeps_it_after_a_restart(tmp_path):
    app, atlas = _app(tmp_path, (8, 7))
    app.regroup({"method": "artists"})
    assert app.clustering.method == "artists" and app.settings["method"] == "artists"
    again = StyleAtlasApp(atlas, EncodeOptions(device="cpu"), "pca")
    assert again.settings["method"] == "artists"  # the page selects "by artist" again
    assert again.clustering.method == "artists" and again._edit_vectors is again.raw.style
    assert (again.clustering.labels == app.clustering.labels).all()
    with pytest.raises(ValueError):
        app.regroup({"method": "spectral"})


def test_the_export_preview_writes_nothing_and_matches_the_export(tmp_path):
    app, _ = _app(tmp_path)
    app.regroup({"threshold": 0.5})
    for i in app.clustering.clusters[1].members[2:]:  # leave 2 images in the smaller group
        app.move({"i": i, "to": -1, "rev": app.revision})
    body = {"layout": "kohya", "name": "artistx", "trigger": True}
    plan = app.export_plan(body)
    assert not list(app.out_dir.glob("folders*"))  # nothing exported yet
    assert sum(r["images"] for r in plan["rows"]) == len(app.atlas)
    trained = [r for r in plan["rows"] if r["training"]]
    assert trained and all(
        r["repeats"] and r["folder"].startswith(f"{r['repeats']}_") for r in trained
    )
    done = app.export({"mode": "copy", **body})
    for key in ("small_ids", "training", "triggers", "steps"):
        assert plan[key] == done[key], key


def test_a_comparison_lists_each_side_with_the_most_distinctive_first(tmp_path):
    app, _ = _app(tmp_path)
    app.regroup({"threshold": 0.5})
    a, b = app.clustering.clusters[0], app.clustering.clusters[1]
    r = app.compare({"a": a.id, "b": b.id})
    assert sorted(r["order_a"]) == sorted(a.members) and sorted(r["order_b"]) == sorted(b.members)


def test_the_web_app_cuts_periods_along_the_timeline_when_it_knows_the_time(tmp_path):
    from styleatlas.atlas import EncodeOptions
    from styleatlas.serve import StyleAtlasApp

    app, atlas = _app(tmp_path, (8, 7))
    with pytest.raises(ValueError):  # opened without --time
        app.regroup({"method": "timeline", "k": 2})
    timed = StyleAtlasApp(atlas, EncodeOptions(device="cpu"), "pca", time_source="mtime")
    done = timed.regroup({"method": "timeline", "k": 2})
    assert done["clusters"] == 2 and 0 < done["p"] <= 1 and "separation" in done
    assert timed.settings["method"] == "timeline"
