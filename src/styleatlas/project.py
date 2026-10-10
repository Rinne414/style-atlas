"""Project style vectors to 3D for the map. Visual only: never cluster on these coordinates."""

from __future__ import annotations

import numpy as np
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE

PROJECTIONS = ("auto", "umap", "tsne", "pca")
PRE_DIMS = 50
TSNE_MAX = 15000  # 3D t-SNE took 28 s at 8k on 8 CPU threads; above this "auto" falls back to PCA


def has_umap() -> bool:
    try:
        import umap  # noqa: F401
    except ImportError:
        return False
    return True


def project_3d(x: np.ndarray, method: str = "auto", seed: int = 0) -> tuple[np.ndarray, str]:
    """(n, 3) coordinates scaled into [-1, 1], plus the method actually used."""
    n = len(x)
    if n < 2:  # nothing to spread out (PCA of one point divides by zero)
        return np.zeros((n, 3), np.float32), "none"
    if n < 5:
        method = "pca"
    elif method == "auto":
        method = "umap" if has_umap() else ("tsne" if n <= TSNE_MAX else "pca")
    if method == "pca":
        coords = _pca(x, 3)
    elif method == "umap":
        coords = _umap(x, seed)
    elif method == "tsne":
        coords = _tsne(x, seed)
    else:
        raise ValueError(f"projection must be one of {PROJECTIONS}")
    return _scale(coords), method


def _pca(x: np.ndarray, dims: int) -> np.ndarray:
    dims = min(dims, x.shape[0], x.shape[1])
    out = PCA(n_components=dims, random_state=0).fit_transform(x)
    if out.shape[1] < 3:
        out = np.pad(out, ((0, 0), (0, 3 - out.shape[1])))
    return out


def _tsne(x: np.ndarray, seed: int) -> np.ndarray:
    pre = _pca(x, PRE_DIMS) if x.shape[0] > PRE_DIMS else x
    perplexity = float(min(30, max(2, (len(x) - 1) // 3)))
    return TSNE(
        n_components=3, perplexity=perplexity, init="pca", random_state=seed, metric="cosine"
    ).fit_transform(pre)


def _umap(x: np.ndarray, seed: int) -> np.ndarray:
    import umap

    neighbors = int(min(15, max(2, len(x) - 1)))
    return umap.UMAP(
        n_components=3, n_neighbors=neighbors, metric="cosine", random_state=seed
    ).fit_transform(x)


def _scale(c: np.ndarray) -> np.ndarray:
    c = c - c.mean(axis=0)
    span = np.abs(c).max()
    return (c / span if span > 0 else c).astype(np.float32)
