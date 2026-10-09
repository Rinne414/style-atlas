"""Like / dislike votes cast in the web app, and the taste model refitted from them.

Votes are saved with the other outputs (`<folder>_style_atlas/taste_votes.json`, keyed by the
image's path relative to the folder) so they survive restarts. Once there are enough examples
of both kinds, the model is refitted after every vote and saved as `taste_model.npz`, which
`style-atlas taste score` can use on other folders.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

from styleatlas.atlas import Atlas
from styleatlas.taste import MIN_PER_CLASS, TasteModel, train_taste


class TasteSession:
    def __init__(self, atlas: Atlas, store_dir: Path):
        self.atlas = atlas
        self.store_dir = Path(store_dir)
        self.votes_path = self.store_dir / "taste_votes.json"
        self.votes: dict[int, bool] = self._load()
        self.model: TasteModel | None = None
        self.scores: np.ndarray | None = None
        self._refit()

    def _load(self) -> dict[int, bool]:
        if not self.votes_path.exists():
            return {}
        saved = json.loads(self.votes_path.read_text(encoding="utf-8"))
        index = {self.atlas.rel(i): i for i in range(len(self.atlas))}
        return {index[rel]: bool(v) for rel, v in saved.items() if rel in index}

    def _save(self) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        data = {self.atlas.rel(i): v for i, v in sorted(self.votes.items())}
        tmp = self.votes_path.with_name(self.votes_path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.votes_path)

    def _refit(self) -> None:
        like = [i for i, v in self.votes.items() if v]
        dislike = [i for i, v in self.votes.items() if not v]
        if len(like) < MIN_PER_CLASS or len(dislike) < MIN_PER_CLASS:
            self.model, self.scores = None, None
            return
        style = self.atlas.style
        model = train_taste(style[like], style[dislike], self.atlas.signature)
        self.model, self.scores = model, model.score(style)
        model.save(self.store_dir / "taste_model.npz")

    def vote(self, index: int, like: bool | None) -> dict:
        if not 0 <= index < len(self.atlas):
            raise ValueError("image index out of range")
        if like is None:
            self.votes.pop(index, None)
        else:
            self.votes[index] = bool(like)
        self._save()
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
            "scores": None if self.scores is None else np.round(self.scores, 3).tolist(),
        }
