"""LoRA renders against their training set (`style-atlas report TRAIN --renders DIR`): how far
the style moved, how many renders fall inside the training set's style groups, how the look
changed, and which renders repeat a training image (a sign of memorisation). Each part is a
measured piece used elsewhere too: the group comparison of `compare`, the fit rule of `sort`
(cluster.fit_to_groups), the look measures and the near-duplicate threshold."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from styleatlas.atlas import Atlas
from styleatlas.cluster import Clustering, Fit, fit_to_groups
from styleatlas.duplicates import copies_of
from styleatlas.look import difference
from styleatlas.metrics import StyleScale, group_difference
from styleatlas.whiten import whiten

ROUNDS = 199  # permutations for the p-value (resolution 0.005), as in the web app


@dataclass
class RenderCheck:
    renders: Atlas
    distance: float  # between the two sets' mean styles (plain CSD)
    z: float  # in noise units of the default StyleScale
    verdict: str  # "same style" / "related" / "clearly different"
    p: float  # permutation p-value
    fits: list[Fit]  # per render: closest training group and whether it fits it
    look: np.ndarray | None  # renders minus training set, per look measure, in pooled SDs
    copies: list[tuple[int, int, float]]  # (render, training image, similarity)

    @property
    def fitting(self) -> int:
        return sum(f.fits for f in self.fits)


def check_renders(train: Atlas, clustering: Clustering, renders: Atlas) -> RenderCheck:
    """`clustering` is the training set's (rows of `train`); both sets need 2 images or more."""
    if len(train) < 2 or len(renders) < 2:
        raise ValueError("the training set and the renders need at least 2 readable images each")
    distance, p = group_difference(train.style, renders.style, rounds=ROUNDS)
    scale = StyleScale()
    fits = fit_to_groups(
        whiten(train.style, keep=False), clustering, whiten(renders.style, keep=False)
    )
    look = None
    if train.looks is not None and renders.looks is not None:
        look = difference(train.looks, renders.looks)
    copies = copies_of(renders.style, renders.content, train.style, train.content)
    return RenderCheck(
        renders, distance, scale.z(distance), scale.verdict(distance), p, fits, look, copies
    )
