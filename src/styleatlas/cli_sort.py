"""The sort command: place new images into the style groups of a dataset that is already sorted,
e.g. a LoRA training set that grows (see cluster.fit_to_groups).

Images are placed in the search whitening's space. On artists it never saw, with 10 artists'
sub-folders as the groups, it picked the right folder for 91.5% of their new works (plain CSD
85.7%); 69% fitted and 9% of other artists' works were let in (docs/BENCHMARKS.md, "Sorting new
images into a dataset")."""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

import numpy as np

from styleatlas.atlas import Atlas
from styleatlas.cli_common import _atlas, export_notes, log, saved_groups, web_exclusions
from styleatlas.cluster import (
    BATCH_MIN,
    FIT_MIN,
    UNASSIGNED,
    Clustering,
    Fit,
    batch_verdict,
    fit_to_groups,
    from_labels,
)
from styleatlas.dataset import auto_repeats, group_labels, is_unassigned
from styleatlas.duplicates import copies_of
from styleatlas.export import export_folders, output_dir, parse_tags, write_csv
from styleatlas.images import labels_from_folders
from styleatlas.lang import pad, tr

UNSURE = "_unsure"  # closest group, but farther from it than 70% of its own images
ALREADY = "_already_in_dataset"  # a near-copy of an image the dataset already holds
RESERVED = {UNSURE.casefold(), ALREADY.casefold()}
VERDICTS_ZH = {
    "few": f"張數太少，不判斷整批（不到 {BATCH_MIN} 張）",
    "in": "大多是資料集的畫風",
    "some": "部分像資料集的畫風",
    "out": "大多不像資料集的畫風",
}
VERDICTS = {
    "few": f"too few images to judge the batch (under {BATCH_MIN})",
    "in": "mostly the dataset's styles",
    "some": "partly the dataset's styles",
    "out": "mostly unlike the dataset's styles",
}
KOHYA_FOLDER = re.compile(r"^(\d+)_(.+)$")  # <repeats>_<name>, as `cluster --layout kohya` writes


def cmd_sort(a: argparse.Namespace) -> int:
    out = Path(a.out) if a.out else output_dir(Path(a.folder))
    dataset, new = _both_sides(a, out)
    if len(new) == 0:
        log(tr(f"no readable images in {a.folder}", f"{a.folder} 裡沒有讀得到的圖"))
        return 1
    clustering, labels = _dataset_groups(a, dataset)
    skip = set(web_exclusions(dataset, Path(a.into)))
    _note_small_groups(clustering, labels, skip)
    fits = fit_to_groups(dataset.style, clustering, new.style, skip)
    if not fits:
        log(
            tr(
                f"{a.into} has no style group of {FIT_MIN} or more images to sort into",
                f"{a.into} 沒有 {FIT_MIN} 張以上的畫風群可以放新圖",
            )
        )
        return 1
    copies = {
        row: base
        for row, base, _ in copies_of(new.style, new.content, dataset.style, dataset.content)
    }
    folders = [_destination(i, f, labels, copies) for i, f in enumerate(fits)]
    table = write_csv(out / "sorted.csv", _rows(new, dataset, fits, labels, copies, folders))
    _summary(fits, labels, folders)
    if a.by_folder:
        _repeats_notes(clustering, labels, folders)
    if a.export:
        _place(a, new, folders, labels, out)
    log(tr("table of every new image:", "每張新圖的結果表："))
    print(table)
    return 0


def _both_sides(a: argparse.Namespace, out: Path) -> tuple[Atlas, Atlas]:
    """The dataset and the new images, checked: neither side reads the other when one folder
    holds the other, nor earlier results in `out`."""
    new_root, data_root = Path(a.folder).resolve(), Path(a.into).resolve()
    if new_root == data_root:
        raise ValueError(
            tr(
                "the new images and the dataset are the same folder",
                "新圖和資料集是同一個資料夾",
            )
        )
    if (a.trigger_captions or a.strip_tags) and not a.export:
        raise ValueError(
            tr(
                "--trigger-captions and --strip-tags only apply with --export copy|link",
                "--trigger-captions 和 --strip-tags 只在 --export copy|link 時有用",
            )
        )
    if any(root.is_relative_to(out.resolve()) for root in (new_root, data_root)):
        raise ValueError(
            tr(
                "the output folder must not hold the new images or the dataset",
                "輸出資料夾不能包含新圖或資料集",
            )
        )
    log(tr(f"dataset: {a.into}", f"資料集：{a.into}"))
    dataset = _atlas(a, a.into, exclude=[out, *_nested(new_root, data_root)])
    log(tr(f"new images: {a.folder}", f"新圖：{a.folder}"))
    return dataset, _atlas(a, a.folder, exclude=[out, *_nested(data_root, new_root)])


def _place(a: argparse.Namespace, new: Atlas, folders: list, labels: dict, out: Path) -> None:
    """--export: the new images (and captions) into <out>/sorted/<group>."""
    matches = [bool(KOHYA_FOLDER.match(name)) for name in labels.values()]
    kohya = all(matches)
    if a.trigger_captions and any(matches) and not kohya:
        log(
            tr(
                "note: only some folders are named <repeats>_<name>; the triggers keep each "
                "folder's "
                "full name",
                "注意：只有部分資料夾是 <repeats>_<名稱> 的格式；觸發詞會用各資料夾的完整名稱",
            )
        )
    done = export_folders(
        new,
        folders,
        out / "sorted",
        mode=a.export,
        trigger_captions=a.trigger_captions,
        layout="kohya" if kohya else "plain",
        strip_tags=parse_tags(a.strip_tags or ""),
    )
    log(
        tr(
            f"{done.placed} images placed in {done.folder}",
            f"已放 {done.placed} 張到 {done.folder}",
        )
    )
    export_notes(done, folders, "kohya" if kohya else "plain", a.trigger_captions)
    for p, why in done.failed:
        log(tr(f"not placed {p}: {why}", f"沒有放入 {p}：{why}"))


def _nested(inner: Path, outer: Path) -> list[Path]:
    return [inner] if inner.is_relative_to(outer) else []


def _dataset_groups(a: argparse.Namespace, dataset: Atlas) -> tuple[Clustering, dict[int, str]]:
    """The groups to sort into with their folder labels: the dataset's sub-folders (--by-folder,
    leaving out set-aside ones such as _excluded or unassigned), else its style groups as
    `cluster` and the web app make them."""
    if not a.by_folder:
        clustering, names = saved_groups(a, dataset, Path(a.into))
        return clustering, _unreserved(group_labels(clustering, "plain", names))
    names = labels_from_folders(dataset.paths, dataset.root)
    kept = sorted({n for n in names if n and not n.startswith("_") and not is_unassigned(n)})
    if not kept:
        raise ValueError(
            tr(
                f"{a.into} has no sub-folders to sort into",
                f"{a.into} 沒有可以分進去的子資料夾",
            )
        )
    index = {n: k for k, n in enumerate(kept)}
    clustering = from_labels(
        dataset.style, np.array([index.get(n, UNASSIGNED) for n in names]), "folders"
    )
    return clustering, {c.id: names[c.members[0]] for c in clustering.clusters}


def _unreserved(labels: dict[int, str]) -> dict[int, str]:
    """A group named like a set-aside folder must not end up in it."""
    return {g: f"{n}_group" if n.casefold() in RESERVED else n for g, n in labels.items()}


def _note_small_groups(clustering: Clustering, labels: dict[int, str], skip: set[int]) -> None:
    usable = {c.id: sum(m not in skip for m in c.members) for c in clustering.clusters}
    small = [labels[g] for g, n in usable.items() if n < FIT_MIN]
    if small:
        names = ", ".join(small)
        log(
            tr(
                f"too few images (under {FIT_MIN}) to sort into: {names}",
                f"這些群的圖太少（不到 {FIT_MIN} 張），不會放新圖進去：{names}",
            )
        )


def _destination(i: int, fit: Fit, labels: dict[int, str], copies: dict[int, int]) -> str:
    if i in copies:
        return ALREADY
    return labels[fit.group] if fit.fits else UNSURE


def _rows(
    new: Atlas,
    dataset: Atlas,
    fits: list[Fit],
    labels: dict[int, str],
    copies: dict[int, int],
    folders: list[str],
) -> list[dict]:
    return [
        {
            "path": new.rel(i),
            "folder": folders[i],
            "closest_group": labels[f.group],
            "distance": round(f.dist, 4),
            "limit": round(f.limit, 4),  # fits when distance <= limit
            "fits": "yes" if f.fits else "no",
            "copy_of": dataset.rel(copies[i]) if i in copies else "",
        }
        for i, f in enumerate(fits)
    ]


def _summary(fits: list[Fit], labels: dict[int, str], folders: list[str]) -> None:
    rest = [(f, d) for f, d in zip(fits, folders, strict=True) if d != ALREADY]
    if len(rest) < len(fits):
        k = len(fits) - len(rest)
        log(
            tr(
                f"{k} of {len(fits)} new images are near-copies of images the dataset already holds"
                f" ({ALREADY})",
                f"{len(fits)} 張新圖裡有 {k} 張和資料集裡的圖幾乎一樣（{ALREADY}）",
            )
        )
    if not rest:
        return
    placed = Counter(labels[f.group] for f, _ in rest)
    fitting = Counter(labels[f.group] for f, d in rest if d != UNSURE)
    log(
        tr(f"{len(rest)} new images, closest group of each:", f"{len(rest)} 張新圖，各自最像的群：")
    )
    for name, n in sorted(placed.items(), key=lambda t: -t[1]):
        k = fitting[name]
        log(f"  {pad(name, 30)}{n:5d}  " + tr(f"({k} fit)", f"（{k} 張符合）"))
    k, n = sum(fitting.values()), len(rest)
    reading = batch_verdict(k / n, n)
    log(
        tr(
            f"{k} of {n} ({k / n:.0%}) fit their group: {VERDICTS[reading]}; the rest go to "
            f"{UNSURE} for a look",
            f"{n} 張裡有 {k} 張（{k / n:.0%}）符合所屬的群：{VERDICTS_ZH[reading]}；"
            f"其餘放進 {UNSURE}，請看一下",
        )
    )


def _repeats_notes(clustering: Clustering, labels: dict[int, str], folders: list[str]) -> None:
    """kohya folders whose automatic repeats (images x repeats near 100) change once the new
    images that fit are added: the new folder name to keep each style's weight per epoch."""
    added = Counter(folders)
    for c in clustering.clusters:
        name = labels[c.id]
        match = KOHYA_FOLDER.match(name)
        if not match or not added[name] or int(match[1]) != auto_repeats(c.size):
            continue  # not a kohya folder, nothing added, or repeats set by hand
        new = auto_repeats(c.size + added[name])
        if new != int(match[1]):
            log(
                tr(
                    f"{name}: {c.size} + {added[name]} images; rename it {new}_{match[2]} to keep "
                    "images x repeats near 100 (the trainer config files list the old repeats)",
                    f"{name}：{c.size} + {added[name]} 張；建議改名成 {new}_{match[2]}，"
                    "讓張數 × repeats "
                    "維持在約 100（訓練設定檔裡的 repeats 也要跟著改）",
                )
            )


def sort_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("folder", help=tr("the new images", "新圖"))
    p.add_argument(
        "--into",
        required=True,
        metavar="DATASET",
        help=tr("the dataset already sorted", "已經分好的資料集"),
    )
    p.add_argument(
        "-o",
        "--out",
        help=tr(
            "output folder (default: <folder>_style_atlas)",
            "輸出資料夾（預設：<資料夾>_style_atlas）",
        ),
    )
    p.add_argument(
        "--fresh",
        action="store_true",
        help=tr(
            "group afresh instead of using the groups the web app saved",
            "重新分群，不沿用網頁介面存的分群",
        ),
    )
    p.add_argument(
        "--by-folder",
        action="store_true",
        help=tr(
            "the dataset's sub-folders are the groups (e.g. an exported kohya dataset)",
            "資料集的子資料夾就是各群（例如匯出的 kohya 資料集）",
        ),
    )
    p.add_argument(
        "--export",
        choices=["copy", "link"],
        help=tr(
            "also place the new images (with captions) into <out>/sorted/<group>",
            "也把新圖（連同標註檔）放進 <out>/sorted/<群>",
        ),
    )
    p.add_argument(
        "--trigger-captions",
        action="store_true",
        help=tr(
            "start each placed caption with its group's trigger, as `cluster --trigger-captions` "
            "does (kohya folders: the name without the repeats)",
            "每個放進去的標註開頭加上該群的觸發詞，做法同 `cluster --trigger-captions`"
            "（kohya 資料夾：去掉重複次數的名稱）",
        ),
    )
    p.add_argument(
        "--strip-tags",
        metavar="TAGS",
        help=tr(
            "remove these comma-separated tags from the placed captions, as `cluster` does",
            "從放進去的標註中移除這些以逗號分隔的標籤，做法同 `cluster`",
        ),
    )
