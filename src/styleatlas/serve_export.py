"""The web app's dataset export: which groups go out, as one training set or one per group, and
where to; the plan the page shows before anything is written, and opening what was written."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from styleatlas.atlas import Atlas
from styleatlas.cluster import UNASSIGNED, Clustering
from styleatlas.dataset import (
    LAYOUTS,
    MAX_NAME,
    MAX_PER_GROUP_RANGE,
    SET_ASIDE,
    clean_group_name,
    group_labels,
    is_unassigned,
    plan_folders,
    spelling_fixes,
)
from styleatlas.export import (
    KOHYA_CONFIG,
    export_paths,
    fresh_dir,
    parse_tags,
    steps_per_epoch,
    trigger_of,
    write_table,
)
from styleatlas.lang import tr

if TYPE_CHECKING:
    from styleatlas.report import Layout

EXPORT_MIN_GROUP = 3  # without a choice of groups: smaller ones go to _unassigned (as in the CLI)
MAX_DEST_TEXT = 1000  # longest destination path accepted from the page
MAX_STRIP_TEXT = 2000
MAX_REPEATS = 100  # kohya repeats set by hand in the export dialog
MAX_WORD_TEXT = 200


@dataclass
class ExportJob:
    """One training set to write: its folder's name, its images and the folder inside it for
    each ("" = the top, with `top` as the trigger word)."""

    name: str
    images: list[int]
    folders: list[str]
    top: str | None = None


def set_aside(folder: str) -> bool:
    return folder.startswith("_") or is_unassigned(folder)


def show_folder(folder: Path) -> None:
    """Open `folder` in the file manager. Callers pass folders of their own, never the page's."""
    if hasattr(os, "startfile"):
        os.startfile(folder)  # noqa: S606 - a folder this program wrote
    else:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([opener, str(folder)])  # noqa: S603


class DatasetExport:
    """Mixed into StyleAtlasApp, which sets these attributes."""

    atlas: Atlas
    clustering: Clustering
    excluded: set[int]
    kept_copies: set[int]
    layout: Layout
    _lock: threading.Lock
    out_dir: Path
    names_by_group: Callable[[], dict[int, str]]
    _last_export: Path | None = None

    def _export_options(self, body: dict) -> tuple[str, bool, str, str, int | None, str]:
        """(layout, trigger, name, strip_tags, max_per_group, repeats) from the page, checked."""
        layout = body.get("layout", "plain")
        trigger = body.get("trigger", False)
        if layout not in LAYOUTS or not isinstance(trigger, bool):
            raise ValueError(f"layout must be one of {LAYOUTS}; trigger must be true or false")
        name = clean_group_name(body.get("name") or self.atlas.root.name or "style")
        strip = body.get("strip_tags") or ""
        if not isinstance(strip, str) or len(strip) > MAX_STRIP_TEXT:
            raise ValueError("strip_tags must be a comma-separated list of tags")
        cap = body.get("max_per_group")
        low, high = MAX_PER_GROUP_RANGE
        if cap is not None and (type(cap) is not int or not low <= cap <= high):
            raise ValueError(f"max_per_group must be empty or a whole number from {low} to {high}")
        repeats = body.get("repeats")
        if repeats is not None and (type(repeats) is not int or not 1 <= repeats <= MAX_REPEATS):
            raise ValueError(f"repeats must be empty (automatic) or a whole number 1-{MAX_REPEATS}")
        return layout, trigger, name, strip, cap, "auto" if repeats is None else str(repeats)

    def _export_groups(self, body: dict) -> tuple[list[int] | None, bool]:
        """(the groups ticked, one training set each). Without `groups`: every image, set-asides
        and unassigned too, as one set (the API before the page could choose)."""
        groups, separate = body.get("groups"), body.get("separate", False)
        if not isinstance(separate, bool):
            raise ValueError("separate must be true or false")
        if groups is None:
            if separate:
                raise ValueError("separate needs the list of groups to export")
            return None, False
        ids = {c.id for c in self.clustering.clusters}
        if not isinstance(groups, list) or any(type(g) is not int or g not in ids for g in groups):
            raise ValueError("groups must be a list of this map's group numbers")
        return sorted(set(groups)), separate

    def _export_words(self, body: dict, groups: list[int] | None) -> dict[int, str]:
        """Trigger words typed for ticked groups ({"3": "artistx_early"}), as folder names."""
        words = body.get("words") or {}
        if not isinstance(words, dict) or (words and groups is None):
            raise ValueError("words must map ticked group numbers to trigger words")
        out = {}
        for key, text in words.items():
            if not (isinstance(key, str) and key.lstrip("-").isdigit() and int(key) in groups):
                raise ValueError("words must map ticked group numbers to trigger words")
            if not isinstance(text, str) or len(text) > MAX_WORD_TEXT:
                raise ValueError("a trigger word must be text")
            if not text.strip():
                continue
            word = clean_group_name(text)
            if is_unassigned(
                word.casefold()
            ):  # the folder of pictures in no group (Windows: any case)
                raise ValueError(
                    tr(
                        f"{word} names the folder of pictures in no group.",
                        f"{word} 是未歸類資料夾的名字，請換一個。",
                    )
                )
            out[int(key)] = word
        return out

    def _export_dest(self, body: dict) -> Path:
        """Where the training sets go: the page's folder, else next to the folder shown."""
        raw = body.get("dest")
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return self.out_dir
        if not isinstance(raw, str) or len(raw) > MAX_DEST_TEXT:
            raise ValueError("dest must be a folder path")
        path = Path(raw.strip().strip('"')).expanduser()
        if not path.is_absolute():
            raise ValueError(
                tr(
                    "Give the whole folder path (for example D:\\LoRA).",
                    "請填完整的資料夾路徑（例如 D:\\LoRA）。",
                )
            )
        path, root = path.resolve(), self.atlas.root.resolve()
        if path.is_relative_to(root):
            raise ValueError(
                tr(
                    "Choose a folder outside the one shown: trainers reading it would also "
                    "pick up the copies.",
                    "請選這個資料夾以外的地方：放在裡面的話，訓練程式讀這個資料夾時會連複本一起讀。",
                )
            )
        if path.exists() and not path.is_dir():
            raise ValueError(tr("That is a file, not a folder.", "這是檔案，不是資料夾。"))
        return path

    def _plan(
        self,
        layout: str,
        name: str,
        cap: int | None,
        repeats: str = "auto",
        groups: list[int] | None = None,
    ) -> list[str]:
        """Each image's export folder (call under the lock). With `groups`, those groups train
        whatever their size and every other image counts as unassigned; near-duplicates keep a
        copy among the ticked groups."""
        clustering, duplicates, min_size = self.clustering, self.layout.duplicates, EXPORT_MIN_GROUP
        if groups is not None:
            ticked = np.isin(clustering.labels, groups)
            clustering = replace(clustering, labels=np.where(ticked, clustering.labels, UNASSIGNED))
            kept = ([i for i in group if ticked[i]] for group in duplicates)
            duplicates, min_size = [g for g in kept if len(g) > 1], 1
        return plan_folders(
            self.atlas.paths,
            clustering,
            layout=layout,
            name=name,
            repeats=repeats,
            duplicate_groups=duplicates,
            excluded=sorted(self.excluded),
            group_names=self.names_by_group(),
            min_size=min_size,
            max_per_group=cap,
            style=self.atlas.style,
            prefer=self.kept_copies,
        )

    def _jobs(
        self,
        layout: str,
        name: str,
        cap: int | None,
        repeats: str,
        groups: list[int] | None,
        separate: bool,
        words: dict[int, str] | None = None,
    ) -> list[ExportJob]:
        """The training sets an export writes (call under the lock). `words`: trigger words typed
        for some groups, used as they are (two the same is refused: it would merge them)."""
        folders = self._plan(layout, name, cap, repeats, groups)
        if groups is None:
            return [ExportJob(name, list(range(len(folders))), folders)]
        labels, words = self.clustering.labels, words or {}
        if not separate:
            chosen = [i for i in range(len(folders)) if int(labels[i]) in groups]
            mine = [_with_word(folders[i], words.get(int(labels[i])), layout) for i in chosen]
            _refuse_repeats(chosen, mine, labels, layout)
            return [ExportJob(name, chosen, mine)]
        own = group_labels(self.clustering, "plain", self.names_by_group())
        taken: set[str] = set()
        for w in words.values():  # typed words first: the automatic ones make way for them
            if w.casefold() in taken:
                raise ValueError(_same_word(w))
            taken.add(w.casefold())
        jobs = []
        for g in groups:  # one LoRA each, named <name>_<group>: its folder and trigger word
            word = words.get(g) or _unique(
                clean_group_name(f"{name[: MAX_NAME // 2]}_{own[g]}"), taken
            )
            chosen = [i for i in range(len(folders)) if labels[i] == g]
            inner = [
                f
                if set_aside(f)
                else f"{f.partition('_')[0]}_{word}"  # kohya: the plan's repeats, own trigger
                if layout == "kohya"
                else ""
                for f in (folders[i] for i in chosen)
            ]
            jobs.append(ExportJob(word, chosen, inner, word if layout == "plain" else None))
        return jobs

    def _plan_summary(self, job: ExportJob, layout: str, trigger: bool) -> dict:
        """What writing `job` gives: groups too small to keep, how many images train, the
        trigger words and the steps per epoch."""
        labels = self.clustering.labels
        pairs = list(zip(job.images, job.folders, strict=True))
        small = {int(labels[i]) for i, f in pairs if labels[i] >= 0 and is_unassigned(f)}
        words = (trigger_of(f, layout) if f else job.top for f in job.folders) if trigger else ()
        return {
            "small_groups": len(small),  # left with < EXPORT_MIN_GROUP images: in unassigned
            "small_ids": sorted(small),
            # the rest go to the set-aside folders (_duplicates, _excluded, unassigned ...)
            "training": sum(not set_aside(f) for f in job.folders),
            "triggers": sorted({w for w in words if w}),
            "trimmed": sum(f == SET_ASIDE["trimmed"] for f in job.folders),
            "steps": steps_per_epoch(job.folders) if layout == "kohya" else None,
        }

    def _group_rows(self, jobs: list[ExportJob], named: dict[str, str], layout: str) -> list[dict]:
        """Per ticked group: the training set and folder it goes to, its trigger word, how many
        images train and how many are set aside (duplicates, excluded, trimmed)."""
        labels, rows = self.clustering.labels, {}
        for job in jobs:
            for i, f in zip(job.images, job.folders, strict=True):
                g = int(labels[i])
                if g < 0:
                    continue
                row = rows.setdefault(
                    g,
                    {
                        "id": g,
                        "dataset": named[job.name],
                        "folder": "",
                        "word": "",
                        "training": 0,
                        "aside": 0,
                    },
                )
                if set_aside(f):
                    row["aside"] += 1
                else:
                    row["training"] += 1
                    row["folder"] = f
                    row["word"] = (trigger_of(f, layout) if f else job.top) or ""
        return [rows[g] for g in sorted(rows)]

    def export_plan(self, body: dict) -> dict:
        """The export's plan without writing anything: one row per folder (images, and the
        repeats of a kohya folder), one per ticked group, and the same summary as an export."""
        layout, trigger, name, _, cap, repeats = self._export_options(body)
        groups, separate = self._export_groups(body)
        words = self._export_words(body, groups)
        dest = self._export_dest(body)
        with self._lock:
            jobs = self._jobs(layout, name, cap, repeats, groups, separate, words)
            summaries = [self._plan_summary(job, layout, trigger) for job in jobs]
            named = {job.name: fresh_dir(dest / job.name).name for job in jobs}  # name_2 when taken
            group_rows = self._group_rows(jobs, named, layout)
        rows, datasets = [], []
        for job, summary in zip(jobs, summaries, strict=True):
            datasets.append(
                {
                    "name": named[job.name],
                    "training": summary["training"],
                    "steps": summary["steps"],
                }
            )
            for folder, n in sorted(Counter(job.folders).items()):
                head, _, rest = folder.partition("_")
                kohya = layout == "kohya" and head.isdigit() and bool(rest)
                rows.append(
                    {
                        "dataset": named[job.name],
                        "folder": folder,
                        "images": n,
                        "repeats": int(head) if kohya else None,
                        "training": not set_aside(folder),
                    }
                )
        return {
            "rows": rows,
            "datasets": datasets,
            "groups": group_rows,
            "dest": str(dest),
            **_merged(summaries),
        }

    def export(self, body: dict) -> dict:
        mode = body.get("mode", "copy")
        layout, trigger, name, strip, cap, repeats = self._export_options(body)
        groups, separate = self._export_groups(body)
        if groups == []:
            raise ValueError(tr("Tick at least one group to export.", "請至少勾一群再匯出。"))
        words = self._export_words(body, groups)
        dest = self._export_dest(body)
        fix = body.get("fix_spelling", False)
        if not isinstance(fix, bool):
            raise ValueError("fix_spelling must be true or false")
        respell = spelling_fixes(self.atlas.paths) if fix else None  # reads captions: no lock
        with self._lock:
            jobs = self._jobs(layout, name, cap, repeats, groups, separate, words)
            table = [""] * len(self.atlas)  # the folder table: where each image went, if anywhere
            for job in jobs:
                for i, f in zip(job.images, job.folders, strict=True):
                    table[i] = f if len(jobs) == 1 else f"{job.name}/{f}".rstrip("/")
            write_table(self.atlas, self.clustering, self.out_dir, table)
            results = [
                export_paths(
                    [self.atlas.paths[i] for i in job.images],
                    job.folders,
                    dest / job.name,
                    mode=mode,
                    trigger_captions=trigger,
                    layout=layout,
                    strip_tags=parse_tags(strip),
                    respell=respell,
                    allow_top=job.top is not None,
                    top_trigger=job.top,
                )
                for job in jobs
            ]
            summaries = [self._plan_summary(job, layout, trigger) for job in jobs]
        self._last_export = results[0].folder if len(results) == 1 else dest
        return {
            "placed": sum(r.placed for r in results),
            "failed": sum(len(r.failed) for r in results),
            "folder": str(self._last_export),
            "datasets": [
                {"name": r.folder.name, "folder": str(r.folder), **_short(s)}
                for r, s in zip(results, summaries, strict=True)
            ],
            "upright": sum(r.upright for r in results),
            "respelt": sorted(respell.values()) if respell else [],
            "small_training": sum(r.small_training for r in results),
            "config": any((r.folder / KOHYA_CONFIG).exists() for r in results),
            **_merged(summaries),
        }

    def open_export(self, body: dict) -> dict:
        """Show the last export in the file manager: only that folder, nothing from the page."""
        folder = self._last_export
        if folder is None or not folder.is_dir():
            raise ValueError(tr("Nothing was exported yet.", "還沒有匯出過。"))
        show_folder(folder)
        return {"folder": str(folder)}


def _with_word(folder: str, word: str | None, layout: str) -> str:
    """A group's training folder under the trigger word typed for it (kohya keeps the repeats)."""
    if word is None or set_aside(folder):
        return folder
    return f"{folder.partition('_')[0]}_{word}" if layout == "kohya" else word


def _same_word(word: str) -> str:
    return tr(
        f"Two groups have the trigger word {word}: give each its own, or they train as one.",
        f"有兩群的觸發詞都是 {word}：請各取不同的名字，不然會被當成同一群訓練。",
    )


def _refuse_repeats(chosen: list[int], folders: list[str], labels: np.ndarray, layout: str) -> None:
    """One training set: two groups whose folders would share a trigger word are refused."""
    owner: dict[str, int] = {}
    for i, f in zip(chosen, folders, strict=True):
        if set_aside(f):
            continue
        word = (trigger_of(f, layout) or f).casefold()
        if owner.setdefault(word, int(labels[i])) != int(labels[i]):
            raise ValueError(_same_word(trigger_of(f, layout) or f))


def _unique(word: str, taken: set[str]) -> str:
    """`word`, else word_2, word_3 ... (folders differ in more than case on Windows)."""
    out, n = word, 2
    while out.casefold() in taken:
        out, n = f"{word}_{n}", n + 1
    taken.add(out.casefold())
    return out


def _short(summary: dict) -> dict:
    return {"training": summary["training"], "steps": summary["steps"]}


def _merged(summaries: list[dict]) -> dict:
    """One summary for several training sets (steps only for one: each set trains on its own)."""
    small = sorted({g for s in summaries for g in s["small_ids"]})
    return {
        "small_groups": len(small),
        "small_ids": small,
        "training": sum(s["training"] for s in summaries),
        "triggers": sorted({w for s in summaries for w in s["triggers"]}),
        "trimmed": sum(s["trimmed"] for s in summaries),
        "steps": summaries[0]["steps"] if len(summaries) == 1 else None,
    }
