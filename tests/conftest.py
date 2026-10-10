from __future__ import annotations

import numpy as np
import pytest

from styleatlas.metrics import unit

DIM = 768


def make_blobs(
    sizes: list[int], spread: float = 0.6, seed: int = 0
) -> tuple[np.ndarray, np.ndarray]:
    """Unit vectors in len(sizes) well-separated groups (synthetic 'styles')."""
    rng = np.random.default_rng(seed)
    centers = unit(rng.normal(size=(len(sizes), DIM)))
    rows, labels = [], []
    for k, n in enumerate(sizes):
        noise = rng.normal(size=(n, DIM)) * spread / np.sqrt(DIM)
        rows.append(unit(centers[k] + noise))
        labels += [k] * n
    return np.vstack(rows).astype(np.float32), np.array(labels)


@pytest.fixture
def blobs() -> tuple[np.ndarray, np.ndarray]:
    return make_blobs([20, 15, 10])


@pytest.fixture(autouse=True)
def english_messages(monkeypatch):
    """Tests read the English messages, whatever the machine's language."""
    monkeypatch.setenv("STYLE_ATLAS_LANG", "en")
