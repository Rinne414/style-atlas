"""Small JSON files that remember per-image choices (votes, exclusions) by relative path.

Entries whose file is not in the current scan (renamed, moved, or a sub-folder was scanned) are
kept untouched and written back, so a later run on the full folder still sees them. A file that
cannot be parsed is renamed to `*.bad` instead of being overwritten.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path

from styleatlas.atlas import Atlas


class RelPathMap:
    def __init__(self, path: Path, atlas: Atlas, read_only: bool = False):
        """read_only: never rename an unreadable file (a reader such as the CLI must not touch
        the web app's file); `unreadable` then tells the caller."""
        self.path = Path(path)
        self.atlas = atlas
        self.read_only = read_only
        self.unreadable = False
        self.values: dict[int, object] = {}
        self.orphans: dict[str, object] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            raw = None
        if isinstance(raw, list):  # older format: a plain list of excluded paths
            raw = {str(name): True for name in raw}
        if not isinstance(raw, dict):
            self.unreadable = True
            if not self.read_only:
                self._set_aside()
            return
        index = {self.atlas.rel(i): i for i in range(len(self.atlas))}
        for rel, value in raw.items():
            if rel in index:
                self.values[index[rel]] = value
            else:
                self.orphans[rel] = value

    def _set_aside(self) -> None:
        """Keep an unreadable file as <name>.<time>.bad so the next save cannot overwrite it."""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        # locked or read-only: start empty, the original stays where it is
        with contextlib.suppress(OSError):
            os.replace(self.path, self.path.with_name(f"{self.path.name}.{stamp}.bad"))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = dict(self.orphans)
        data.update({self.atlas.rel(i): v for i, v in sorted(self.values.items())})
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)
