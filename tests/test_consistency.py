import numpy as np

from styleatlas.consistency import MIXED, SAMPLE, Consistency, consistency

from .conftest import make_blobs


def test_a_mix_is_more_spread_than_one_style():
    one, _ = make_blobs([40], spread=0.6, seed=1)
    five, _ = make_blobs([8] * 5, spread=0.6, seed=1)
    a, b = consistency(one), consistency(five)
    assert a.spread < b.spread and a.percentile <= b.percentile
    assert consistency(one) == a  # same images, same answer (fixed draws)


def test_too_few_images_are_not_judged():
    x, _ = make_blobs([SAMPLE - 1])
    assert consistency(x) is None


def test_verdict_bands():
    assert Consistency(0.5, 30.0).verdict == "tight"
    assert Consistency(0.7, 70.0).verdict == "like one artist"
    assert Consistency(0.9, MIXED + 1).verdict == "mixed"
    assert 0 <= consistency(make_blobs([12])[0]).percentile <= 100
    assert np.isfinite(consistency(make_blobs([12])[0]).spread)
