"""Like / dislike votes cast in the web app, and the taste model refitted from them.

Votes are saved with the other outputs (`<folder>_style_atlas/taste_votes.json`, keyed by the
image's path relative to the folder) so they survive restarts; votes for files missing from the
current scan are kept. Once there are enough distinct examples of both kinds, the model is
refitted after every vote and saved as `taste_model.npz`, which `style-atlas taste score` can use
on other folders.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from styleatlas.atlas import Atlas
from styleatlas.persist import RelPathMap
from styleatlas.taste import MIN_PER_CLASS, TasteModel, train_taste


class TasteSession:
    def __init__(self, atlas: Atlas, store_dir: Path):
        self.atlas = atlas
        self.store_dir = Path(store_dir)
        self._store = RelPathMap(self.store_dir / "taste_votes.json", atlas)
        self.votes: dict[int, bool] = {
            i: v for i, v in self._store.values.items() if isinstance(v, bool)
        }
        self.model: TasteModel | None = None
        self.scores: np.ndarray | None = None
        self._refit()

    def _refit(self) -> None:
        like = [i for i, v in self.votes.items() if v]
        dislike = [i for i, v in self.votes.items() if not v]
        self.model, self.scores = None, None
        if len(like) < MIN_PER_CLASS or len(dislike) < MIN_PER_CLASS:
            return
        style = self.atlas.style
        try:  # identical files count once, so enough votes may still be too few examples
            model = train_taste(style[like], style[dislike], self.atlas.signature)
        except ValueError:
            return
        self.model, self.scores = model, model.score(style)
        model.save(self.store_dir / "taste_model.npz")

    def next_to_rate(self, skip: set[int] | None = None) -> int | None:
        """The unrated image least like anything rated so far (farthest-first). In a simulation
        on 140 real votes this reached AUC 0.69 after 10 ratings, where random picks needed ~25;
        picking the most uncertain image was no better than random."""
        skip = skip or set()
        rated = list(self.votes)
        pool = np.array(
            [i for i in range(len(self.atlas)) if i not in self.votes and i not in skip]
        )
        if not len(pool):
            return None
        style = self.atlas.style
        if not rated:  # start with the most unusual image
            return int(pool[np.argmin(style[pool] @ style.mean(axis=0))])
        closest = (style[pool] @ style[rated].T).max(axis=1)
        return int(pool[np.argmin(closest)])

    def vote(self, index: int, like: bool | None) -> dict:
        if not 0 <= index < len(self.atlas):
            raise ValueError("image index out of range")
        if like is None:
            self.votes.pop(index, None)
        else:
            self.votes[index] = like
        self._store.values = dict(self.votes)
        self._store.save()
        self._refit()
        return self.state()

    def state(self) -> dict:
        likes = sum(1 for v in self.votes.values() if v)
        return {
            "votes": {str(i): v for i, v in self.votes.items()},
            "likes": likes,
            "dislikes": len(self.votes) - likes,
            "min": MIN_PER_CLASS,
            "auc": None if self.model is None else round(self.model.cv_auc, 3),
            # NaN (too few look-alike groups) is not valid JSON: None instead
            "auc_groups": None
            if self.model is None or np.isnan(self.model.cv_auc_groups)
            else round(self.model.cv_auc_groups, 3),
            "scores": None if self.scores is None else np.round(self.scores, 3).tolist(),
        }
