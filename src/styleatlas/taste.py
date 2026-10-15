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
from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from styleatlas.lang import tr

PCA_DIMS = 20
MIN_PER_CLASS = 5  # with diverse picks, 10 ratings already gave AUC ~0.69
# A new image whose highest cosine to every rated image is below this is unlike all of them: on
# artists300 (6 rated artists, 8 works each) 30% of other artists' works fell below it and 10% of
# the rated artists' other works; their scores were at chance (BENCHMARKS "Taste: new artists").
UNFAMILIAR = 0.6


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
    # held out by whole look-alike groups: closer to how it does on styles never rated
    cv_auc_groups: float = float("nan")
    examples: np.ndarray | None = None  # the rated images' style vectors, liked first
    example_names: tuple[str, ...] = ()
    example_liked: np.ndarray | None = None

    def nearest_example(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
        """(index of the closest rated image, its cosine) per row; None for an old model file
        that keeps no examples."""
        if self.examples is None or not len(self.examples):
            return None
        sims = x @ self.examples.T
        best = sims.argmax(axis=1)
        return best, sims[np.arange(len(x)), best]

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
            cv_auc_groups=np.array(self.cv_auc_groups),
            examples=np.zeros((0, 0), np.float32) if self.examples is None else self.examples,
            example_names=np.array(self.example_names, dtype=str),
            example_liked=np.zeros(0, bool) if self.example_liked is None else self.example_liked,
        )
        os.replace(tmp, path)
        return path

    @classmethod
    def load(cls, path: Path) -> TasteModel:
        """Model files from before 0.44 have no grouped AUC and no examples; they still load."""
        with np.load(path, allow_pickle=False) as z:
            examples = z["examples"] if "examples" in z.files and z["examples"].size else None
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
                float(z["cv_auc_groups"]) if "cv_auc_groups" in z.files else float("nan"),
                examples,
                tuple(str(n) for n in z["example_names"]) if examples is not None else (),
                z["example_liked"].astype(bool) if examples is not None else None,
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


def cross_val_auc_groups(
    x: np.ndarray, y: np.ndarray, dims: int, c: float, folds: int = 5
) -> float:
    """AUC with whole look-alike groups held out together (StratifiedGroupKFold): a rated
    artist's other works no longer sit on both sides, so this reads closer to the AUC on styles
    the ratings never covered. NaN when each class has fewer than 2 groups."""
    groups = look_alike_groups(x)
    folds = min(folds, *(len(set(groups[y == k])) for k in (0, 1)))
    if folds < 2:
        return float("nan")
    pred = np.full(len(y), np.nan)
    split = StratifiedGroupKFold(folds, shuffle=True, random_state=0).split(x, y, groups)
    for fit_rows, te in split:
        if len(set(y[fit_rows].tolist())) < 2:
            continue  # a fold whose training side lost a class: those rows stay unscored
        model = _pipeline(min(dims, len(fit_rows) - 1), c).fit(x[fit_rows], y[fit_rows])
        pred[te] = model.predict_proba(x[te])[:, 1]
    ok = ~np.isnan(pred)
    if len(set(y[ok].tolist())) < 2:
        return float("nan")
    return float(roc_auc_score(y[ok], pred[ok]))


def look_alike_groups(x: np.ndarray) -> np.ndarray:
    """The tool's own style groups of `x` (strays each a group of their own)."""
    from styleatlas.cluster import cluster_styles

    labels = cluster_styles(np.asarray(x, dtype=np.float32)).labels.copy()
    alone = labels < 0
    labels[alone] = labels.max() + 1 + np.arange(alone.sum())
    return labels


def _dedupe(like: np.ndarray, dislike: np.ndarray) -> tuple[list[int], list[int]]:
    """Rows to keep: repeated images (they would leak across CV folds) and images in both sets
    are dropped. The first of each repeat is kept."""

    def first_rows(x: np.ndarray) -> dict[bytes, int]:
        out: dict[bytes, int] = {}
        for i, r in enumerate(x):
            out.setdefault(np.round(r, 5).tobytes(), i)
        return out

    a, b = first_rows(like), first_rows(dislike)
    both = a.keys() & b.keys()
    return [i for k, i in a.items() if k not in both], [i for k, i in b.items() if k not in both]


def train_taste(
    like: np.ndarray,
    dislike: np.ndarray,
    signature: str,
    c: float = 0.5,
    names: tuple[list[str], list[str]] | None = None,
) -> TasteModel:
    """`names` (liked, disliked) are kept with the examples, to say which rated image a new one
    is closest to."""
    keep_like, keep_dislike = _dedupe(like, dislike)
    if names is None:  # numbered as given
        names = (
            [f"liked {i + 1}" for i in range(len(like))],
            [f"disliked {i + 1}" for i in range(len(dislike))],
        )
    kept_names = [names[0][i] for i in keep_like] + [names[1][i] for i in keep_dislike]
    like, dislike = like[keep_like], dislike[keep_dislike]
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
    auc_groups = cross_val_auc_groups(x, y, dims, c)
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
        auc_groups,
        x.astype(np.float32),
        tuple(kept_names),
        y.astype(bool),
    )
