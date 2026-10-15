"""End to end with the real CSD model (run with `pytest -m model`; needs the weights, CPU is fine).
Uses the generated demo styles, so no artwork is needed."""

from __future__ import annotations

import pytest
from sklearn.metrics import adjusted_rand_score

from styleatlas.atlas import EncodeOptions, build_atlas
from styleatlas.cluster import cluster_styles
from styleatlas.demo import make_all
from styleatlas.search import search

pytestmark = pytest.mark.model


@pytest.fixture(scope="module")
def demo_atlas(tmp_path_factory):
    root = tmp_path_factory.mktemp("demo_styles")
    make_all(root, n=6)
    return build_atlas(root, EncodeOptions(device="cpu"))


def test_the_four_demo_styles_come_out_as_four_groups(demo_atlas):
    truth = [p.parent.name for p in demo_atlas.paths]
    result = cluster_styles(demo_atlas.style)
    assert result.n_clusters == 4
    assert adjusted_rand_score(truth, result.labels) == pytest.approx(1.0)


def test_search_finds_the_same_style(demo_atlas):
    truth = [p.parent.name for p in demo_atlas.paths]
    for q in range(0, len(truth), 6):
        hits = search(demo_atlas.style[q : q + 1], demo_atlas.style, top=5, exclude={q})[0]
        assert all(truth[h.index] == truth[q] for h in hits)
