"""Near-duplicate groups: the same picture, crops, recolours, or frames of one scene.

Two images are near-duplicates when both their style and their content vectors agree:
min(cos_style, cos_content) >= threshold. On 3,253 Danbooru works, pairs at 0.93-0.97 were
consecutive frames of one scene and pairs at 0.90-0.93 were redraws of one pose; at 0.85-0.90
the same figure appeared over a new background. The default 0.92 flags the first two kinds.
Duplicates matter for LoRA training (they over-weight one picture) and inflate retrieval scores.
"""

from __future__ import annotations

import numpy as np

from styleatlas.metrics import CHUNK

DEFAULT_THRESHOLD = 0.92
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
