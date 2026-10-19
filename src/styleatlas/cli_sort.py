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
from styleatlas.dataset import (
    SET_ASIDE,
    auto_repeats,
    group_labels,
    is_unassigned,
    spelling_fixes,
)
from styleatlas.duplicates import copies_of
from styleatlas.export import (
    ExportResult,
    export_folders,
    export_paths,
    output_dir,
    parse_tags,
    write_csv,
)
from styleatlas.images import labels_from_folders
from styleatlas.lang import pad, tr

UNSURE = "_unsure"  # closest group, but farther from it than 70% of its own images
ALREADY = "_already_in_dataset"  # a near-copy of an image the dataset already holds
RESERVED = {UNSURE.casefold(), ALREADY.casefold()}
SHOWN = 10  # near-copies and _unsure images named in the summary (the rest: sorted.csv)
VERDICTS_ZH = {
    "few": f"张数太少，不判断整批（不到 {BATCH_MIN} 张）",
    "in": "大多是数据集的画风",
    "some": "部分像数据集的画风",
    "out": "大多不像数据集的画风",
}
VERDICTS = {
    "few": f"too few images to judge the batch (under {BATCH_MIN})",
    "in": "mostly the dataset's styles",
    "some": "partly the dataset's styles",
    "out": "mostly unlike the dataset's styles",
}
KOHYA_FOLDER = re.compile(r"^(\d+)_(.+)$")  # <repeats>_<name>, as `cluster --layout kohya` writes


def cmd_sort(a: argparse.Namespace) -> int:
    out = Path(a.out) if a.out else _default_out(Path(a.folder), Path(a.into))
    dataset, new = _both_sides(a, out)
    if len(new) == 0:
        log(tr(f"no readable images in {a.folder}", f"{a.folder} 里没有读得到的图"))
        return 1
    clustering, labels = _dataset_groups(a, dataset)
    skip = set(web_exclusions(dataset, Path(a.into)))
    _note_small_groups(clustering, labels, skip)
    fits = fit_to_groups(dataset.style, clustering, new.style, skip)
    if not fits:
        log(
            tr(
                f"{a.into} has no style group of {FIT_MIN} or more images to sort into",
                f"{a.into} 没有 {FIT_MIN} 张以上的画风组可以放新图",
            )
        )
        return 1
    copies = {
        row: base
        for row, base, _ in copies_of(new.style, new.content, dataset.style, dataset.content)
    }
    folders = [_destination(i, f, labels, copies) for i, f in enumerate(fits)]
    table = write_csv(out / "sorted.csv", _rows(new, dataset, fits, labels, copies, folders))
    names = [new.rel(i) for i in range(len(new))]
    _summary(fits, labels, folders, names, {i: dataset.rel(b) for i, b in copies.items()})
    if a.by_folder and not a.merged:
        _repeats_notes(clustering, labels, folders)
    placed = merged = None
    if a.export:
        placed, options = _place(a, new, folders, labels, out, dataset)
        if a.merged:
            merged = _merge(dataset, new, folders, clustering, labels, skip, out, options)
    log(tr("table of every new image:", "每张新图的结果表："))
    print(table, flush=True)  # before the next step, also when the output is piped
    _next_step(a, placed, merged, UNSURE in folders)
    return 0


def _default_out(new: Path, dataset: Path) -> Path:
    """Next to the new images, unless that is inside the dataset (new images kept in a
    sub-folder of it): then next to the dataset, so nothing is written into it."""
    out, data_root = output_dir(new), dataset.resolve()
    return output_dir(data_root) if out.resolve().is_relative_to(data_root) else out


def _both_sides(a: argparse.Namespace, out: Path) -> tuple[Atlas, Atlas]:
    """The dataset and the new images, checked: neither side reads the other when one folder
    holds the other, nor earlier results in `out`."""
    new_root, data_root = Path(a.folder).resolve(), Path(a.into).resolve()
    if new_root == data_root:
        raise ValueError(
            tr(
                "the new images and the dataset are the same folder",
                "新图和数据集是同一个文件夹",
            )
        )
    if a.merged and not (a.export and a.by_folder):
        raise ValueError(
            tr(
                "--merged needs --export copy|link and --by-folder (the dataset's sub-folders are "
                "the groups)",
                "--merged 需要搭配 --export copy|link 和 --by-folder（数据集的子文件夹就是各组）",
            )
        )
    if (a.trigger_captions or a.strip_tags or a.fix_tag_spelling) and not a.export:
        raise ValueError(
            tr(
                "--trigger-captions, --strip-tags and --fix-tag-spelling only apply with "
                "--export copy|link",
                "--trigger-captions、--strip-tags 和 --fix-tag-spelling 只在 --export copy|link "
                "时有用",
            )
        )
    if any(root.is_relative_to(out.resolve()) for root in (new_root, data_root)):
        raise ValueError(
            tr(
                "the output folder must not hold the new images or the dataset",
                "输出文件夹不能包含新图或数据集",
            )
        )
    if any(out.resolve().is_relative_to(root) for root in (new_root, data_root)):
        raise ValueError(
            tr(
                "the output folder must not be inside the new images or the dataset (a trainer "
                "would read the copies in it)",
                "输出文件夹不能放在新图或数据集里面（训练程序会把里面的副本也读进去）",
            )
        )
    log(tr(f"dataset: {a.into}", f"数据集：{a.into}"))
    dataset = _atlas(a, a.into, exclude=[out, *_nested(new_root, data_root)])
    log(tr(f"new images: {a.folder}", f"新图：{a.folder}"))
    return dataset, _atlas(a, a.folder, exclude=[out, *_nested(data_root, new_root)])


def _place(
    a: argparse.Namespace, new: Atlas, folders: list, labels: dict, out: Path, dataset: Atlas
) -> tuple[Path, dict]:
    """--export: the new images (and captions) into <out>/sorted/<group>; that folder and the
    export options (--merged uses them too)."""
    matches = [bool(KOHYA_FOLDER.match(name)) for name in labels.values()]
    kohya = all(matches)
    if a.trigger_captions and any(matches) and not kohya:
        log(
            tr(
                "note: only some folders are named <repeats>_<name>; the triggers keep each "
                "folder's "
                "full name",
                "注意：只有部分文件夹是 <repeats>_<名称> 的格式；触发词会用各文件夹的完整名称",
            )
        )
    # the new captions follow the spelling the dataset and the new images use more
    respell = spelling_fixes([*dataset.paths, *new.paths]) if a.fix_tag_spelling else None
    options = {
        "mode": a.export,
        "trigger_captions": a.trigger_captions,
        "layout": "kohya" if kohya else "plain",
        "strip_tags": parse_tags(a.strip_tags or ""),
        "respell": respell,
    }
    # no trainer configs here: they would list only the new images
    done = export_folders(new, folders, out / "sorted", trainer_configs=False, **options)
    log(_placed_line(done, new.paths, folders))
    export_notes(done, folders, options["layout"], a.trigger_captions, respell)
    for p, why in done.failed:
        log(tr(f"not placed {p}: {why}", f"没有放入 {p}：{why}"))
    return done.folder, options


def _placed_line(done: ExportResult, paths: list[Path], folders: list[str]) -> str:
    failed = {p for p, _ in done.failed}
    kinds = Counter(
        d if d in (UNSURE, ALREADY) else ""
        for p, d in zip(paths, folders, strict=True)
        if p not in failed
    )
    return tr(
        f"{done.placed} images placed in {done.folder}: {kinds['']} in style folders, "
        f"{kinds[UNSURE]} in {UNSURE}, {kinds[ALREADY]} in {ALREADY}",
        f"已放 {done.placed} 张到 {done.folder}：{kinds['']} 张进画风文件夹、"
        f"{kinds[UNSURE]} 张进 {UNSURE}、{kinds[ALREADY]} 张进 {ALREADY}",
    )


def _merge(
    dataset: Atlas,
    new: Atlas,
    folders: list[str],
    clustering: Clustering,
    labels: dict[int, str],
    skip: set[int],
    out: Path,
    options: dict,
) -> Path:
    """--merged: the dataset (its sub-folders as they are; images excluded in the web app in
    _excluded) plus the new images that fit, in <out>/merged, ready to train. kohya folders
    whose automatic repeats change with the new count are renamed. The dataset is not touched.
    The caption options apply to the dataset's copies too (a trigger is never added twice)."""
    excluded = SET_ASIDE["excluded"]
    paths = list(dataset.paths)
    places = [
        excluded if i in skip else dataset.rel(i).rpartition("/")[0] for i in range(len(dataset))
    ]
    added = [(p, d) for p, d in zip(new.paths, folders, strict=True) if d not in (UNSURE, ALREADY)]
    paths += [p for p, _ in added]
    places += [d for _, d in added]
    count = Counter(place.partition("/")[0] for place in places)
    renames, blocked = _merged_renames(clustering, labels, count)
    places = [_renamed(place, renames) for place in places]
    done = export_paths(paths, places, out / "merged", allow_top=True, **options)
    log(
        tr(
            f"merged dataset, ready to train: {done.folder} ({len(dataset)} dataset images + "
            f"{len(added)} new ones that fit; the dataset itself is unchanged)",
            f"合并好的数据集，可以直接训练：{done.folder}（数据集 {len(dataset)} 张 + 符合的新图 "
            f"{len(added)} 张；原本的数据集没有改动）",
        )
    )
    _merge_notes(dataset, skip, options["mode"])
    sizes = {labels[c.id]: c.size for c in clustering.clusters}
    for old, name in sorted(renames.items()):
        log(
            tr(
                f"renamed {old} -> {name}: {count[old]} images there now ({sizes[old]} in the "
                "dataset's folder), so images x repeats stays near 100; the trainer configs in it "
                "list the new repeats",
                f"已改名 {old} -> {name}：现在有 {count[old]} 张"
                f"（数据集的文件夹是 {sizes[old]} 张），让张数 × repeats 维持在约 100；"
                "里面的训练配置文件用的是新的 repeats",
            )
        )
    for old, name in blocked:
        log(
            tr(
                f"kept the name {old}: {name} is already a folder; set its repeats by hand "
                f"({count[old]} images there now)",
                f"保留 {old} 的名称：已经有 {name} 这个文件夹；请自己调整它的 repeats"
                f"（现在有 {count[old]} 张）",
            )
        )
    for p, why in done.failed:
        log(tr(f"not placed {p}: {why}", f"没有放入 {p}：{why}"))
    return done.folder


def _merge_notes(dataset: Atlas, skip: set[int], mode: str) -> None:
    excluded = SET_ASIDE["excluded"]
    if skip:
        log(
            tr(
                f"{len(skip)} images excluded in the web app are in {excluded}",
                f"网页界面排除的 {len(skip)} 张放在 {excluded}",
            )
        )
    if dataset.failed:
        log(
            tr(
                f"{len(dataset.failed)} files in the dataset could not be read and are not in it",
                f"数据集里有 {len(dataset.failed)} 个文件读不到，没有放进去",
            )
        )
    if mode == "link":
        log(
            tr(
                "the dataset's images there are hard links: editing one of them in place edits "
                "the dataset's file too (rewritten captions are separate files)",
                "里面数据集的图是硬链接：直接修改其中一张，数据集里的原文件也会一起改"
                "（重写过的标注文件是另外的文件）",
            )
        )


def _merged_renames(
    clustering: Clustering, labels: dict[int, str], count: Counter
) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """kohya folder -> its name for the merged image `count`, where the repeats change; and the
    renames left out because a folder of that name is already there."""
    taken, renames, blocked = set(count), {}, []
    for c in clustering.clusters:
        name = labels[c.id]
        new = _repeats_for(name, c.size, count[name]) if count[name] else None
        if not new:
            continue
        if new in taken:  # never into a folder that is already there
            blocked.append((name, new))
            continue
        renames[name] = new
        taken.add(new)
    return renames, blocked


def _renamed(place: str, renames: dict[str, str]) -> str:
    top, sep, rest = place.partition("/")
    return renames.get(top, top) + sep + rest


def _next_step(
    a: argparse.Namespace, placed: Path | None, merged: Path | None, has_unsure: bool
) -> None:
    if placed is None:
        log(
            tr(
                "next: add --export copy to place the new images in folders"
                + (
                    " (and --merged for the dataset plus them, ready to train)"
                    if a.by_folder
                    else ""
                ),
                "下一步：加上 --export copy 把新图放进文件夹"
                + ("（再加 --merged 会连同数据集合并好，可以直接训练）" if a.by_folder else ""),
            )
        )
        return
    look = (
        tr(f"look through {placed / UNSURE}; ", f"看一下 {placed / UNSURE}；") if has_unsure else ""
    )
    if merged is not None:
        log(
            tr(
                f"next: {look}"
                + (
                    f"move any that belong into their group's folder in {merged}; "
                    if has_unsure
                    else ""
                )
                + f'then check it: style-atlas audit "{merged}"',
                f"下一步：{look}"
                + (f"属于数据集的就移到 {merged} 里对应的文件夹；" if has_unsure else "")
                + f'然后检查一遍：style-atlas audit "{merged}"',
            )
        )
        return
    log(
        tr(
            f"next: {look}move the images that belong into the dataset's folders"
            + (" (or rerun with --merged for a copy ready to train)" if a.by_folder else "")
            + f'; then check it: style-atlas audit "{a.into}"',
            f"下一步：{look}把属于数据集的图移进数据集对应的文件夹"
            + ("（或加 --merged 重跑，直接得到可以训练的合并版）" if a.by_folder else "")
            + f'；然后检查一遍：style-atlas audit "{a.into}"',
        )
    )


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
                f"{a.into} 没有可以分进去的子文件夹",
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
                f"这些组的图太少（不到 {FIT_MIN} 张），不会放新图进去：{names}",
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


def _summary(
    fits: list[Fit],
    labels: dict[int, str],
    folders: list[str],
    names: list[str],
    copy_of: dict[int, str],
) -> None:
    """The batch in a few lines. `names` are the new images', `copy_of` maps a near-copy to the
    dataset image it repeats."""
    rest = [(f, d) for f, d in zip(fits, folders, strict=True) if d != ALREADY]
    if len(rest) < len(fits):
        k = len(fits) - len(rest)
        log(
            tr(
                f"{k} of {len(fits)} new images are near-copies of images the dataset already holds"
                f" ({ALREADY}):",
                f"{len(fits)} 张新图里有 {k} 张和数据集里的图几乎一样（{ALREADY}）：",
            )
        )
        pairs = sorted(copy_of.items())
        for i, base in pairs[:SHOWN]:
            log(f"  {names[i]}  =  {base}")
        _more(len(pairs), "copy_of")
    if not rest:
        return
    placed = Counter(labels[f.group] for f, _ in rest)
    fitting = Counter(labels[f.group] for f, d in rest if d != UNSURE)
    log(
        tr(f"{len(rest)} new images, closest group of each:", f"{len(rest)} 张新图，各自最像的组：")
    )
    for name, n in sorted(placed.items(), key=lambda t: -t[1]):
        k = fitting[name]
        log(f"  {pad(name, 30)}{n:5d}  " + tr(f"({k} fit)", f"（{k} 张符合）"))
    k, n = sum(fitting.values()), len(rest)
    reading = batch_verdict(k / n, n)
    log(
        tr(
            f"{k} of {n} ({k / n:.0%}) fit their group: {VERDICTS[reading]}; the rest go to "
            f"{UNSURE} for a look",
            f"{n} 张里有 {k} 张（{k / n:.0%}）符合所属的组：{VERDICTS_ZH[reading]}；"
            f"其余放进 {UNSURE}，请看一下",
        )
    )
    _list_unsure(fits, labels, folders, names)


def _list_unsure(
    fits: list[Fit], labels: dict[int, str], folders: list[str], names: list[str]
) -> None:
    """The _unsure images, the closest to a group (by how far past its limit) first."""
    pairs = enumerate(zip(fits, folders, strict=True))
    unsure = sorted((f.dist - f.limit, i) for i, (f, d) in pairs if d == UNSURE)
    if not unsure:
        return
    log(
        tr(
            f"{UNSURE}, the closest to a group first (that group in brackets):",
            f"{UNSURE} 里越前面的越接近某一组（括号里是那一组）：",
        )
    )
    for _, i in unsure[:SHOWN]:
        log(f"  {names[i]}  ({labels[fits[i].group]})")
    _more(len(unsure), "distance - limit")
    log(
        tr(
            "  the order is a hint, not a test: in benchmarks an image by a dataset artist came "
            "before another artist's about 2 times in 3, and for 1 in 3 of them the group in "
            "brackets was not their own",
            "  顺序只是参考：实测数据集画师的图排在其他画师前面的概率约 2/3，"
            "而且其中约 1/3 括号里的组不是它真正的组",
        )
    )


def _more(total: int, column: str) -> None:
    if total > SHOWN:
        log(
            tr(
                f"  ... and {total - SHOWN} more (sorted.csv: {column})",
                f"  ……还有 {total - SHOWN} 张（见 sorted.csv：{column}）",
            )
        )


def _repeats_notes(clustering: Clustering, labels: dict[int, str], folders: list[str]) -> None:
    """kohya folders whose automatic repeats (images x repeats near 100) change once the new
    images that fit are added: the new folder name to keep each style's weight per epoch."""
    added = Counter(folders)
    for c in clustering.clusters:
        name = labels[c.id]
        new = _repeats_for(name, c.size, c.size + added[name]) if added[name] else None
        if new:
            log(
                tr(
                    f"{name}: {c.size} + {added[name]} images; rename it {new} to keep "
                    "images x repeats near 100 (the trainer config files list the old repeats)",
                    f"{name}：{c.size} + {added[name]} 张；建议改名成 {new}，"
                    "让张数 × repeats "
                    "维持在约 100（训练配置文件里的 repeats 也要跟着改）",
                )
            )


def _repeats_for(name: str, size: int, total: int) -> str | None:
    """The kohya folder name for `total` images when `name` has the automatic repeats for `size`
    (images x repeats near 100) and they change; None for other folders, repeats set by hand,
    or no change."""
    match = KOHYA_FOLDER.match(name)
    if not match or int(match[1]) != auto_repeats(size):
        return None
    new = f"{auto_repeats(total)}_{match[2]}"
    return None if new == name else new


def sort_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("folder", help=tr("the new images", "新图"))
    p.add_argument(
        "--into",
        required=True,
        metavar="DATASET",
        help=tr("the dataset already sorted", "已经分好的数据集"),
    )
    p.add_argument(
        "-o",
        "--out",
        help=tr(
            "output folder (default: <folder>_style_atlas)",
            "输出文件夹（默认：<文件夹>_style_atlas）",
        ),
    )
    p.add_argument(
        "--fresh",
        action="store_true",
        help=tr(
            "group afresh instead of using the groups the web app saved",
            "重新分组，不沿用网页界面存的分组",
        ),
    )
    p.add_argument(
        "--by-folder",
        action="store_true",
        help=tr(
            "the dataset's sub-folders are the groups (e.g. an exported kohya dataset)",
            "数据集的子文件夹就是各组（例如导出的 kohya 数据集）",
        ),
    )
    p.add_argument(
        "--export",
        choices=["copy", "link"],
        help=tr(
            "also place the new images (with captions) into <out>/sorted/<group>",
            "也把新图（连同标注文件）放进 <out>/sorted/<组>",
        ),
    )
    p.add_argument(
        "--merged",
        action="store_true",
        help=tr(
            "with --export and --by-folder: also write <out>/merged, the dataset plus the new "
            "images that fit, ready to train (kohya repeats and trainer configs updated; the "
            "caption options apply to the dataset's copies too; the dataset itself is not "
            "changed)",
            "搭配 --export 和 --by-folder：另外写出 <out>/merged，即数据集加上符合的新图，"
            "可以直接训练（kohya 的 repeats 和训练配置文件会跟着更新；标注的选项也会套用到数据集的"
            "副本；原本的数据集不会改动）",
        ),
    )
    p.add_argument(
        "--trigger-captions",
        action="store_true",
        help=tr(
            "start each placed caption with its group's trigger, as `cluster --trigger-captions` "
            "does (kohya folders: the name without the repeats)",
            "每个放进去的标注开头加上该组的触发词，做法同 `cluster --trigger-captions`"
            "（kohya 文件夹：去掉重复次数的名称）",
        ),
    )
    p.add_argument(
        "--strip-tags",
        metavar="TAGS",
        help=tr(
            "remove these comma-separated tags from the placed captions, as `cluster` does",
            "从放进去的标注中移除这些以逗号分隔的标签，做法同 `cluster`",
        ),
    )
    p.add_argument(
        "--fix-tag-spelling",
        action="store_true",
        help=tr(
            "in the exported copies, write each tag the dataset spells two ways "
            "(long_hair / long hair) "
            "the way most captions do",
            "导出的副本中，数据集有两种写法的标签（long_hair/long hair）统一成多数标注的写法",
        ),
    )
