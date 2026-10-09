"""Small JSON files that remember per-image choices (votes, exclusions) by relative path.

Entries whose file is not in the current scan (renamed, moved, or a sub-folder was scanned) are
kept untouched and written back, so a later run on the full folder still sees them. A file that
cannot be parsed is renamed to `*.bad` instead of being overwritten.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from styleatlas.atlas import Atlas


class RelPathMap:
    def __init__(self, path: Path, atlas: Atlas):
        self.path = Path(path)
        self.atlas = atlas
        self.values: dict[int, object] = {}
        self.orphans: dict[str, object] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            os.replace(self.path, self.path.with_name(self.path.name + ".bad"))
            return
        if isinstance(raw, list):  # older format: a plain list of excluded paths
            raw = {str(name): True for name in raw}
        if not isinstance(raw, dict):
            return
        index = {self.atlas.rel(i): i for i in range(len(self.atlas))}
        for rel, value in raw.items():
            if rel in index:
                self.values[index[rel]] = value
            else:
                self.orphans[rel] = value

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = dict(self.orphans)
        data.update({self.atlas.rel(i): v for i, v in sorted(self.values.items())})
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)
