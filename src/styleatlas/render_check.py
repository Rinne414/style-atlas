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
from styleatlas.metrics import ArtistReading, StyleScale, artist_reading, group_difference

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
    nearest: list[tuple[int, float]]  # per render: closest training image, style cosine
    reading: ArtistReading | None  # the distance among pairs of artists (5+ images a side)

    @property
    def fitting(self) -> int:
        return sum(f.fits for f in self.fits)

    def order(self) -> list[int]:
        """Renders as a reader goes through them: likely copies of a training image first (most
        alike first), then those outside the training set's style groups, then the rest (each
        the farthest first)."""
        copied = {i: s for i, _, s in self.copies}

        def key(i: int) -> tuple:
            fit = self.fits[i] if self.fits else None  # no fits: no training group of 3+
            outside = fit is not None and not fit.fits
            far = fit.dist if fit is not None else -self.nearest[i][1]
            return (0 if i in copied else 1 if outside else 2, -copied.get(i, 0.0), -far)

        return sorted(range(len(self.renders)), key=key)


def check_renders(train: Atlas, clustering: Clustering, renders: Atlas) -> RenderCheck:
    """`clustering` is the training set's (rows of `train`); both sets need 2 images or more."""
    if len(train) < 2 or len(renders) < 2:
        raise ValueError("the training set and the renders need at least 2 readable images each")
    distance, p = group_difference(train.style, renders.style, rounds=ROUNDS)
    scale = StyleScale()
    fits = fit_to_groups(train.style, clustering, renders.style)
    look = None
    if train.looks is not None and renders.looks is not None:
        look = difference(train.looks, renders.looks)
    copies = copies_of(renders.style, renders.content, train.style, train.content)
    sims = renders.style @ train.style.T
    best = sims.argmax(axis=1)
    nearest = [(int(j), float(sims[i, j])) for i, j in enumerate(best)]
    reading = artist_reading(distance, len(train), len(renders))
    return RenderCheck(
        renders,
        distance,
        scale.z(distance),
        scale.verdict(distance),
        p,
        fits,
        look,
        copies,
        nearest,
        reading,
    )
