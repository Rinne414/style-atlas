"""Measure how well style vectors recover known labels (sub-folder = label, e.g. one artist each).

Reports, for raw cosine and hub-corrected scores:
  retrieval  share of images whose nearest neighbour(s) carry the same label
  pair_auc   same-label vs different-label pairs separated by similarity (0.5 = chance)
  mixtures   random mixtures of 2, 3 and 5 labels clustered blind; mean adjusted Rand index
             (the LoRA case: split a folder into its styles without knowing how many there are)
"""

from __future__ import annotations

from collections import Counter

import numpy as np
from sklearn.metrics import adjusted_rand_score, roc_auc_score

from styleatlas.cluster import GRANULARITY, cluster_styles
from styleatlas.metrics import neighbor_density

MIX_SIZES = (2, 3, 5)
MIN_PER_LABEL = 5


def retrieval(sim: np.ndarray, labels: np.ndarray, ks: tuple[int, ...] = (1, 5, 10)) -> dict:
    s = sim.copy()
    np.fill_diagonal(s, -np.inf)
    order = np.argsort(-s, axis=1)[:, : max(ks)]
    hit = labels[order] == labels[:, None]
    return {f"top{k}": round(float(hit[:, :k].any(axis=1).mean()), 4) for k in ks}


def pair_auc(sim: np.ndarray, labels: np.ndarray) -> float:
    iu = np.triu_indices(len(labels), 1)
    same = (labels[:, None] == labels[None, :])[iu]
    if same.all() or not same.any():
        return float("nan")
    return round(float(roc_auc_score(same, sim[iu])), 4)


def hub_similarity(x: np.ndarray, k: int = 10) -> np.ndarray:
    r = neighbor_density(x, x, k=k, same_set=True)
    return x @ x.T - (r[:, None] + r[None, :]) / 2.0


def mixtures(
    x: np.ndarray,
    labels: np.ndarray,
    trials: int = 30,
    seed: int = 0,
    threshold: float | None = None,
) -> dict:
    counts = Counter(labels.tolist())
    pool = sorted(lbl for lbl, c in counts.items() if c >= MIN_PER_LABEL)
    rng = np.random.default_rng(seed)
    out: dict[str, float] = {}
    for m in MIX_SIZES:
        if len(pool) < m:
            continue
        scores = []
        for _ in range(trials):
            chosen = rng.choice(pool, m, replace=False)
            idx = np.flatnonzero(np.isin(labels, chosen))
            result = cluster_styles(x[idx], threshold=threshold, min_size=1)
            scores.append(adjusted_rand_score(labels[idx], result.labels))
        out[f"mix{m}_ari"] = round(float(np.mean(scores)), 4)
    return out


def run_bench(x: np.ndarray, labels: list[str] | np.ndarray, trials: int = 30) -> dict:
    labels = np.asarray(labels)
    keep = np.isin(labels, [lbl for lbl, c in Counter(labels.tolist()).items() if c >= 2])
    x, labels = x[keep], labels[keep]
    raw = x @ x.T
    hub = hub_similarity(x)
    report = {
        "images": int(len(x)),
        "labels": int(len(set(labels.tolist()))),
        "raw": {**retrieval(raw, labels), "pair_auc": pair_auc(raw, labels)},
        "hub": {**retrieval(hub, labels), "pair_auc": pair_auc(hub, labels)},
    }
    for name, thr in GRANULARITY.items():
        report[f"mixtures_{name}"] = mixtures(x, labels, trials=trials, threshold=thr)
    return report
