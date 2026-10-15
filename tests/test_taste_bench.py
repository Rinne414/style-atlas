from __future__ import annotations

import numpy as np
import pytest

from styleatlas.bench import run_bench
from styleatlas.taste import TasteModel, train_taste

from .conftest import make_blobs


def test_taste_learns_separable_preferences_and_roundtrips(tmp_path):
    x, y = make_blobs([30, 30], spread=0.9)
    model = train_taste(x[y == 0], x[y == 1], "sig")
    assert model.cv_auc > 0.95
    scores = model.score(x)
    assert scores[y == 0].mean() > 0.8 and scores[y == 1].mean() < 0.2
    path = tmp_path / "m.npz"
    model.save(path)
    loaded = TasteModel.load(path)
    assert loaded.signature == "sig"
    assert np.allclose(loaded.score(x), scores)


def test_taste_needs_enough_examples():
    x, y = make_blobs([4, 30])  # MIN_PER_CLASS is 5
    with pytest.raises(ValueError):
        train_taste(x[y == 0], x[y == 1], "sig")


def test_bench_on_clean_labels_is_near_perfect():
    x, y = make_blobs([12, 12, 12, 12, 12, 12])
    report = run_bench(x, [f"artist{v}" for v in y], trials=5)
    assert report["hub"]["top1"] > 0.95
    assert report["hub"]["pair_auc"] > 0.95
    assert report["whitened"]["top1"] > 0.9  # the space search ranks in
    assert report["mixtures_medium"]["mix3_ari"] > 0.9


def test_taste_drops_duplicates_and_conflicts():
    from styleatlas.taste import _dedupe

    x, _ = make_blobs([4, 4])
    like = np.vstack([x[:4], x[:1]])  # x[0] twice
    dislike = np.vstack([x[4:], x[1:2]])  # x[1] is also liked
    a, b = _dedupe(like, dislike)
    assert len(a) == 3 and len(b) == 4


def test_taste_save_adds_npz_suffix(tmp_path):
    x, y = make_blobs([10, 10], spread=0.9)
    saved = train_taste(x[y == 0], x[y == 1], "sig").save(tmp_path / "model")
    assert saved.name == "model.npz" and saved.exists()


def test_taste_session_fits_saves_and_reloads(tmp_path):
    from pathlib import Path

    from styleatlas.atlas import Atlas
    from styleatlas.taste_session import TasteSession

    x, y = make_blobs([10, 10], spread=0.9)
    paths = [Path(tmp_path / f"img{i}.png") for i in range(len(x))]
    atlas = Atlas(tmp_path, paths, x, x, "sig")
    session = TasteSession(atlas, tmp_path / "out")
    for i in range(len(x)):
        state = session.vote(i, bool(y[i] == 0))
    assert state["auc"] is not None and state["auc"] > 0.9
    assert len(state["scores"]) == len(x)
    assert (tmp_path / "out" / "taste_model.npz").exists()
    assert state["auc_groups"] is None  # 2 looks: no grouped AUC, and None (not NaN) in JSON
    saved = TasteModel.load(tmp_path / "out" / "taste_model.npz")
    assert set(saved.example_names) == {f"img{i}.png" for i in range(len(x))}  # real names
    again = TasteSession(atlas, tmp_path / "out")
    assert again.state()["likes"] == 10 and again.state()["scores"] is not None


def test_saved_choices_survive_missing_files_and_broken_json(tmp_path):
    import json
    from pathlib import Path

    from styleatlas.atlas import Atlas
    from styleatlas.persist import RelPathMap
    from styleatlas.taste_session import TasteSession

    x, _ = make_blobs([3, 3])
    paths = [Path(tmp_path / f"img{i}.png") for i in range(6)]
    full = Atlas(tmp_path, paths, x, x, "sig")
    store = tmp_path / "out" / "taste_votes.json"
    session = TasteSession(full, tmp_path / "out")
    session.vote(0, True)
    session.vote(5, False)
    part = Atlas(tmp_path, paths[:3], x[:3], x[:3], "sig")  # img5 missing from this scan
    TasteSession(part, tmp_path / "out").vote(1, True)
    saved = json.loads(store.read_text(encoding="utf-8"))
    assert saved == {"img0.png": True, "img1.png": True, "img5.png": False}

    store.write_text("{broken", encoding="utf-8")
    assert TasteSession(full, tmp_path / "out").state()["likes"] == 0  # starts, does not crash
    assert list((tmp_path / "out").glob("taste_votes.json.*.bad"))  # kept, not overwritten
    legacy = tmp_path / "excluded.json"
    legacy.write_text(json.dumps(["img2.png"]), encoding="utf-8")
    assert RelPathMap(legacy, full).values == {2: True}


def test_taste_session_survives_duplicate_only_votes(tmp_path):
    from pathlib import Path

    import numpy as np

    from styleatlas.atlas import Atlas
    from styleatlas.taste_session import TasteSession

    x, _ = make_blobs([2, 2])
    style = np.vstack([np.repeat(x[:1], 9, axis=0), np.repeat(x[2:3], 9, axis=0)])
    paths = [Path(tmp_path / f"img{i}.png") for i in range(18)]
    session = TasteSession(Atlas(tmp_path, paths, style, style, "sig"), tmp_path / "out")
    for i in range(18):
        state = session.vote(i, i < 9)  # 9 + 9 votes but only one distinct image each
    assert state["scores"] is None and state["likes"] == 9


def test_next_to_rate_spreads_out_over_the_collection(tmp_path):
    from pathlib import Path

    from styleatlas.atlas import Atlas
    from styleatlas.taste_session import TasteSession

    x, y = make_blobs([6, 6, 6])
    paths = [Path(tmp_path / f"img{i}.png") for i in range(len(x))]
    session = TasteSession(Atlas(tmp_path, paths, x, x, "sig"), tmp_path / "out")
    seen = []
    for _ in range(3):
        i = session.next_to_rate()
        seen.append(int(y[i]))
        session.vote(i, True)
    assert sorted(seen) == [0, 1, 2]  # one from each style before any repeat
    assert session.next_to_rate(skip=set(range(len(x)))) is None


def test_taste_keeps_its_examples_and_a_grouped_auc(tmp_path):
    x, y = make_blobs([12, 12, 12, 12])
    like, dislike = x[y <= 1], x[y >= 2]  # two looks liked, two disliked
    names = ([f"l{i}" for i in range(24)], [f"d{i}" for i in range(24)])
    model = train_taste(like, dislike, "sig", names=names)
    assert np.isnan(model.cv_auc_groups)  # 2 looks a side: holding one out swaps the looks
    many, labels = make_blobs([8] * 10)
    wide = train_taste(many[labels < 5], many[labels >= 5], "sig")  # 5 looks a side
    assert 0.0 <= wide.cv_auc_groups <= 1.0
    rows, cos = model.nearest_example(x[:1])
    assert model.example_names[rows[0]] == "l0" and cos[0] > 0.99 and model.example_liked[rows[0]]
    path = model.save(tmp_path / "m")
    loaded = TasteModel.load(path)
    assert loaded.example_names == model.example_names
    assert np.isnan(loaded.cv_auc_groups)  # NaN saved and read back
    new = ("examples", "example_names", "example_liked", "cv_auc_groups")
    with np.load(path) as z:  # a model file from before 0.44
        old = {k: z[k] for k in z.files if k not in new}
    np.savez(tmp_path / "old.npz", **old)
    old_model = TasteModel.load(tmp_path / "old.npz")
    assert old_model.nearest_example(x) is None and np.isnan(old_model.cv_auc_groups)
    assert np.allclose(old_model.score(x), model.score(x))


def test_taste_names_stay_with_their_pictures_after_dedupe(tmp_path):
    x, _ = make_blobs([6, 6])
    like = np.vstack([x[:6], x[:1]])  # the first liked picture twice
    dislike = np.vstack([x[6:], x[1:2]])  # x[1] liked and disliked: dropped from both
    names = ([f"l{i}" for i in range(7)], [f"d{i}" for i in range(7)])
    model = train_taste(like, dislike, "sig", names=names)
    assert model.example_names == ("l0", "l2", "l3", "l4", "l5", *(f"d{i}" for i in range(6)))
    rows, _ = model.nearest_example(x[6:7])
    assert model.example_names[rows[0]] == "d0" and not model.example_liked[rows[0]]


def test_a_damaged_shared_model_file_is_refused(tmp_path):
    x, y = make_blobs([10, 10], spread=0.9)
    path = train_taste(x[y == 0], x[y == 1], "sig").save(tmp_path / "m")
    with np.load(path) as z:
        fields = {k: z[k] for k in z.files}
    fields["example_names"] = fields["example_names"][:3]  # fewer names than pictures
    np.savez(tmp_path / "bad.npz", **fields)
    with pytest.raises(ValueError, match="damaged"):
        TasteModel.load(tmp_path / "bad.npz")
