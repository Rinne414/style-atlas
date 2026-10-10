"""Personal taste model: learn like / dislike from examples, then score new images.

Method (validated in the research this tool comes from): PCA to 20 dims on the style vectors,
standardise, L2 logistic regression. With 140 rated renders it reached cross-validated AUC 0.76,
and its blind top-20 picks among 1,084 unseen styles were all liked. Limits measured at the same
time: it separates liked from disliked, but it did not rank *degrees* of liking among already-good
candidates (Spearman 0.17), and on a batch from a new generator it fell to chance. Treat the score
as a coarse filter and keep looking at the images.

Models are saved as plain .npz arrays (no pickle), so a shared model file cannot run code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from styleatlas.lang import tr

PCA_DIMS = 20
MIN_PER_CLASS = 5  # with diverse picks, 10 ratings already gave AUC ~0.69


@dataclass(frozen=True)
class TasteModel:
    pca_mean: np.ndarray
    pca_components: np.ndarray
    scale_mean: np.ndarray
    scale_std: np.ndarray
    coef: np.ndarray
    intercept: float
    signature: str
    cv_auc: float
    n_like: int
    n_dislike: int

    def score(self, x: np.ndarray) -> np.ndarray:
        """Probability of 'like' per row of unit style vectors."""
        z = (x - self.pca_mean) @ self.pca_components.T
        z = (z - self.scale_mean) / self.scale_std
        return 1.0 / (1.0 + np.exp(-(z @ self.coef + self.intercept)))

    def save(self, path: Path) -> Path:
        """Atomic write; the file always ends in .npz (numpy would append it anyway)."""
        path = Path(path)
        if path.suffix != ".npz":
            path = path.with_name(path.name + ".npz")
        tmp = path.with_name(path.stem + ".tmp.npz")
        np.savez(
            tmp,
            pca_mean=self.pca_mean,
            pca_components=self.pca_components,
            scale_mean=self.scale_mean,
            scale_std=self.scale_std,
            coef=self.coef,
            intercept=np.array(self.intercept),
            signature=np.array(self.signature),
            cv_auc=np.array(self.cv_auc),
            counts=np.array([self.n_like, self.n_dislike]),
        )
        os.replace(tmp, path)
        return path

    @classmethod
    def load(cls, path: Path) -> TasteModel:
        with np.load(path, allow_pickle=False) as z:
            return cls(
                z["pca_mean"],
                z["pca_components"],
                z["scale_mean"],
                z["scale_std"],
                z["coef"],
                float(z["intercept"]),
                str(z["signature"]),
                float(z["cv_auc"]),
                int(z["counts"][0]),
                int(z["counts"][1]),
            )


def _pipeline(dims: int, c: float):
    return make_pipeline(
        PCA(n_components=dims, random_state=0),
        StandardScaler(),
        LogisticRegression(C=c, max_iter=2000, class_weight="balanced"),
    )


def cross_val_auc(x: np.ndarray, y: np.ndarray, dims: int, c: float, folds: int = 5) -> float:
    folds = int(min(folds, np.bincount(y).min()))
    if folds < 2:
        return float("nan")
    pred = np.zeros(len(y))
    for fit_rows, te in StratifiedKFold(folds, shuffle=True, random_state=0).split(x, y):
        model = _pipeline(min(dims, len(fit_rows) - 1), c).fit(x[fit_rows], y[fit_rows])
        pred[te] = model.predict_proba(x[te])[:, 1]
    return float(roc_auc_score(y, pred))


def _dedupe(like: np.ndarray, dislike: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Drop repeated images (they would leak across CV folds) and images in both sets."""

    def unique_rows(x: np.ndarray) -> dict[bytes, np.ndarray]:
        return {np.round(r, 5).tobytes(): r for r in x}

    a, b = unique_rows(like), unique_rows(dislike)
    both = a.keys() & b.keys()
    dim = like.shape[1]
    keep_a = np.array([r for k, r in a.items() if k not in both]).reshape(-1, dim)
    keep_b = np.array([r for k, r in b.items() if k not in both]).reshape(-1, dim)
    return keep_a, keep_b


def train_taste(
    like: np.ndarray, dislike: np.ndarray, signature: str, c: float = 0.5
) -> TasteModel:
    like, dislike = _dedupe(like, dislike)
    if len(like) < MIN_PER_CLASS or len(dislike) < MIN_PER_CLASS:
        raise ValueError(
            tr(
                f"need at least {MIN_PER_CLASS} liked and {MIN_PER_CLASS} disliked images",
                f"至少要 {MIN_PER_CLASS} 張喜歡和 {MIN_PER_CLASS} 張不喜歡的圖",
            )
        )
    x = np.vstack([like, dislike]).astype(np.float64)
    y = np.r_[np.ones(len(like), int), np.zeros(len(dislike), int)]
    dims = min(PCA_DIMS, len(x) - 1)
    auc = cross_val_auc(x, y, dims, c)
    pipe = _pipeline(dims, c).fit(x, y)
    pca, scaler, lr = pipe.named_steps.values()
    return TasteModel(
        pca.mean_,
        pca.components_,
        scaler.mean_,
        scaler.scale_,
        lr.coef_[0],
        float(lr.intercept_[0]),
        signature,
        auc,
        len(like),
        len(dislike),
    )
