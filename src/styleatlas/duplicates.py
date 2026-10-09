"""Near-duplicate groups: the same picture, crops, recolours, or frames of one scene.

Two images are near-duplicates when both their style and their content vectors agree:
min(cos_style, cos_content) >= threshold. Checked by eye on Danbooru works (2026-10-09):
>= 0.95 were mostly recolours, expression variants, crops and frames of one picture (7 of 8
sampled pairs at 0.95-0.965); 0.92-0.95 were often *different* pictures of one character in a
new pose on the same plain background, which a LoRA dataset should keep. The default 0.95 is
therefore conservative: it would rather miss a variant than drop a valid training image.
Duplicates over-weight one picture in training and inflate retrieval scores; `bench` uses the
stricter BENCH_THRESHOLD so that benchmark numbers are not inflated.
"""

from __future__ import annotations

import numpy as np

from styleatlas.metrics import CHUNK

DEFAULT_THRESHOLD = 0.95
BENCH_THRESHOLD = 0.92
NEIGHBORS = 10


def _root(parent: list[int], i: int) -> int:
    while parent[i] != i:
        parent[i] = parent[parent[i]]
        i = parent[i]
    return i


def near_duplicate_groups(
    style: np.ndarray, content: np.ndarray, threshold: float = DEFAULT_THRESHOLD
) -> list[list[int]]:
    """Groups (size >= 2, largest first) of images joined by near-duplicate pairs."""
    n = len(style)
    parent = list(range(n))
    k = min(NEIGHBORS, n - 1)
    if k < 1:
        return []
    for s in range(0, n, CHUNK):
        sims = style[s : s + CHUNK] @ style.T
        rows = np.arange(s, s + len(sims))
        sims[rows - s, rows] = -np.inf
        cand = np.argpartition(-sims, k - 1, axis=1)[:, :k]
        for r, row in enumerate(cand):
            i = s + r
            for j in row:
                if sims[r, j] >= threshold and float(content[i] @ content[j]) >= threshold:
                    a, b = _root(parent, i), _root(parent, int(j))
                    if a != b:
                        parent[max(a, b)] = min(a, b)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(_root(parent, i), []).append(i)
    return sorted((g for g in groups.values() if len(g) > 1), key=lambda g: (-len(g), g[0]))


def keep_one_per_group(n: int, groups: list[list[int]]) -> np.ndarray:
    """Indices that remain when only the first image of each duplicate group is kept."""
    drop = {i for g in groups for i in g[1:]}
    return np.array([i for i in range(n) if i not in drop], dtype=int)
