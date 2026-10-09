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
    x, y = make_blobs([5, 30])
    with pytest.raises(ValueError):
        train_taste(x[y == 0], x[y == 1], "sig")


def test_bench_on_clean_labels_is_near_perfect():
    x, y = make_blobs([12, 12, 12, 12, 12, 12])
    report = run_bench(x, [f"artist{v}" for v in y], trials=5)
    assert report["hub"]["top1"] > 0.95
    assert report["hub"]["pair_auc"] > 0.95
    assert report["mixtures_medium"]["mix3_ari"] > 0.9
