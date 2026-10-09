"""Fit the search whitening shipped in src/styleatlas/data/whiten_csd.npz.

Input: an .npz of CSD style vectors (default encoder settings) keyed "<artist>__<id>", e.g. the
Danbooru benchmark corpus. Near-duplicates are dropped, then the within-artist covariance is
whitened (WCCN) with shrinkage LAMBDA toward the average variance. See docs/BENCHMARKS.md,
"Search whitening".

    python scripts/fit_whitening.py corpus_csd.npz
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from styleatlas.duplicates import keep_one_per_group, near_duplicate_groups  # noqa: E402

LAMBDA = 0.3
OUT = Path(__file__).resolve().parents[1] / "src" / "styleatlas" / "data" / "whiten_csd.npz"


def fit(x: np.ndarray, labels: np.ndarray, lam: float = LAMBDA) -> tuple[np.ndarray, np.ndarray]:
    """(mean, matrix) such that unit((v - mean) @ matrix) is the whitened vector."""
    sw = np.zeros((x.shape[1], x.shape[1]))
    for lbl in np.unique(labels):
        xi = x[labels == lbl]
        if len(xi) >= 2:
            d = xi - xi.mean(0)
            sw += d.T @ d
    sw /= len(x)
    sw += lam * np.trace(sw) / len(sw) * np.eye(len(sw))
    w, v = np.linalg.eigh(sw)
    return x.mean(0), v @ np.diag(w**-0.5) @ v.T


def main() -> int:
    z = np.load(sys.argv[1])
    x = np.stack([z[k] for k in z.files]).astype(np.float64)
    x /= np.linalg.norm(x, axis=1, keepdims=True)
    labels = np.array([k.rsplit("__", 1)[0] for k in z.files])
    x32 = x.astype(np.float32)
    keep = keep_one_per_group(len(x), near_duplicate_groups(x32, x32, 0.95))
    mean, matrix = fit(x[keep], labels[keep])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        OUT,
        mean=mean.astype(np.float32),
        matrix=matrix.astype(np.float32),
        images=len(keep),
        labels=len(np.unique(labels[keep])),
        shrinkage=LAMBDA,
    )
    print(f"{OUT}: {len(keep)} images, {len(np.unique(labels[keep]))} artists")
    return 0


if __name__ == "__main__":
    sys.exit(main())
