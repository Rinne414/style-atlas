from __future__ import annotations

import numpy as np
import pytest
import torch

from styleatlas import comfy
from styleatlas.encoder import Embeddings

from .conftest import make_blobs


class FakeEncoder:
    """Maps each image to a known vector by its red value (pixel [0, 0, 0])."""

    def __init__(self, table: np.ndarray):
        self.table = table

    def encode(self, images):
        rows = [self.table[int(np.asarray(im)[0, 0, 0])] for im in images]
        x = np.stack(rows)
        return Embeddings(style=x, content=x)


@pytest.fixture
def refs_and_images(monkeypatch):
    x, _ = make_blobs([4, 4])  # rows 0-3 style A, rows 4-7 style B
    monkeypatch.setattr(comfy, "get_encoder", lambda opts: FakeEncoder(x))
    refs = comfy.StyleReferences(x[:4], [f"ref{i}.png" for i in range(4)], "sig")
    images = torch.zeros((3, 8, 8, 3))
    for k, row in enumerate((1, 5, 6)):  # one image in the reference style, two in style B
        images[k, 0, 0, 0] = row / 255.0
    return refs, images


def test_distance_reports_the_closest_reference(refs_and_images):
    refs, images = refs_and_images
    min_dist, report = comfy.StyleDistance().measure(images, refs)
    assert min_dist < 0.05 and report.splitlines()[0].endswith("ref1.png")
    assert len(report.splitlines()) == 3


def test_gate_keeps_original_or_matching_images(refs_and_images):
    refs, images = refs_and_images
    kept, n, _ = comfy.StyleGate().gate(images, refs, "keep original", 0.3)
    assert n == 2 and kept.shape[0] == 2
    kept, n, _ = comfy.StyleGate().gate(images, refs, "keep matching", 0.3)
    assert n == 1 and kept.shape[0] == 1
    kept, n, report = comfy.StyleGate().gate(images, refs, "keep original", 1.4)
    assert n == 0 and kept.shape[0] == 1 and "nothing passed" in report


def test_tensor_to_pil_round_trip():
    t = torch.rand((2, 5, 7, 3))
    ims = comfy.tensor_to_pil(t)
    assert [im.size for im in ims] == [(7, 5), (7, 5)]
    assert np.allclose(np.asarray(ims[0]) / 255.0, t[0].numpy(), atol=1 / 255)


def test_nodes_are_registered_for_comfyui():
    assert set(comfy.NODE_CLASS_MAPPINGS) == set(comfy.NODE_DISPLAY_NAME_MAPPINGS)
    for cls in comfy.NODE_CLASS_MAPPINGS.values():
        assert "required" in cls.INPUT_TYPES() and hasattr(cls, cls.FUNCTION)
