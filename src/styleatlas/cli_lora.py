"""The cluster command: group a folder, plan the LoRA folders (duplicates, outliers, web
exclusions, per-style cap), write the tables and export."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from styleatlas.atlas import Atlas
from styleatlas.cli_common import (
    _atlas,
    _cluster,
    _opts,
    _positive_int,
    _reference,
    export_notes,
    log,
    web_exclusions,
)
from styleatlas.cluster import outlier_scores
from styleatlas.images import timeline, timeline_span
from styleatlas.lang import chinese, pad, tr
from styleatlas.look import describe, profile

FEW_FOR_LORA = 8  # style-LoRA guides suggest starting at 8-15 images (docs/LORA_GUIDE.md)


def _lora_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group(tr("training dataset", "训练数据集"))
    g.add_argument(
        "--export",
        choices=["copy", "link"],
        help=tr("also place images into style folders", "也把图放进各画风组的文件夹"),
    )
    g.add_argument(
        "--layout",
        choices=["plain", "kohya"],
        default="plain",
        help=tr(
            "kohya: <repeats>_<name>_styleNN folders; set-aside folders are skipped",
            "kohya：<重复次数>_<名称>_styleNN 文件夹；另外放的文件夹会被略过",
        ),
    )
    g.add_argument(
        "--name",
        help=tr(
            "concept name for kohya folders (default: the folder name)",
            "kohya 文件夹用的概念名称（默认：文件夹名称）",
        ),
    )
    g.add_argument(
        "--repeats",
        default="auto",
        help=tr(
            "kohya repeats per style folder, or auto (images x repeats about 100 per epoch)",
            "kohya 每个画风文件夹的重复次数，或 auto（每个 epoch 张数 × 重复次数约 100）",
        ),
    )
    g.add_argument(
        "--trigger-captions",
        action="store_true",
        help=tr(
            "start every exported caption with its group's trigger word (artistX_style01)",
            "每个导出的标注开头加上该组的触发词（artistX_style01）",
        ),
    )
    g.add_argument(
        "--dedupe",
        action="store_true",
        help=tr(
            "keep the best copy of each near-duplicate group; others go to _duplicates",
            "每组近重复图只留最好的一张，其余放进 _duplicates",
        ),
    )
    g.add_argument(
        "--drop-outliers",
        type=int,
        default=0,
        metavar="N",
        help=tr("move the N least typical images to _outliers", "把最不典型的 N 张移到 _outliers"),
    )
    g.add_argument(
        "--strip-tags",
        metavar="TAGS",
        help=tr(
            'remove these caption tags in the exported copies, e.g. "sketch, monochrome"',
            '从导出的副本标注中移除这些标签，例如 "sketch, monochrome"',
        ),
    )
    g.add_argument(
        "--fix-tag-spelling",
        action="store_true",
        help=tr(
            "in the exported copies, write each tag the dataset spells two ways "
            "(long_hair / long hair) "
            "the way most captions do",
            "导出的副本中，数据集有两种写法的标签（long_hair/long hair）统一成多数标注的写法",
        ),
    )
    g.add_argument(
        "--max-per-group",
        type=_positive_int,
        metavar="N",
        help=tr(
            "keep at most N images per style, chosen to cover it; the rest go to _trimmed",
            "每个画风组最多留 N 张（挑能涵盖整组的），其余放进 _trimmed",
        ),
    )


def cmd_cluster(a: argparse.Namespace) -> int:
    from styleatlas.dataset import parse_repeats

    parse_repeats(a.repeats)
    if (a.trigger_captions or a.fix_tag_spelling) and not a.export:
        raise ValueError(
            tr(
                "--trigger-captions and --fix-tag-spelling only apply with --export copy|link",
                "--trigger-captions 和 --fix-tag-spelling 只在 --export copy|link 时有用",
            )
        )
    from styleatlas.export import output_dir, write_table
    from styleatlas.report import write_map

    out = Path(a.out) if a.out else output_dir(Path(a.folder))
    atlas = _atlas(a, a.folder, exclude=[out]).with_looks(_opts(a), log)
    result, dups = _group(a, atlas)
    folders, tags = _plan(a, atlas, result, dups)
    csv_path, json_path = write_table(atlas, result, out, folders, tags)
    log(tr(f"wrote {csv_path} and {json_path}", f"已写出 {csv_path} 和 {json_path}"))
    spread = None
    if getattr(a, "fitted_space", None) is None:  # the reference was measured on plain CSD
        spread = _log_consistency(atlas)
    _print_groups(atlas, result, folders, tags, a.time)
    _log_where_they_went(folders)
    _one_lora_hint(a, result, spread)
    if a.export:
        _export(a, atlas, folders, out)
    else:
        log(
            tr(
                "the folder names above are the plan; add --export copy (or link) to write the "
                "folders",
                "上面的文件夹名称只是规划；加 --export copy（或 link）才会真的创建文件夹",
            )
        )
    if not a.no_map:
        path = write_map(
            atlas,
            result,
            out / "map.html",
            a.projection,
            a.thumb,
            progress=log,
            time_source=a.time,
            reference=_reference(a),
        )
        log(tr(f"map: {path}", f"地图：{path}"))
    return 0


def _group(a: argparse.Namespace, atlas: Atlas):
    """The style groups, and with --dedupe the near-duplicate groups (grouping only the kept
    copies, so a stack of duplicates cannot pose as a style)."""
    dups = None
    if a.dedupe:
        from styleatlas.cluster import expand_clustering
        from styleatlas.dataset import duplicate_keepers
        from styleatlas.duplicates import near_duplicate_groups

        dups = near_duplicate_groups(atlas.style, atlas.content)
        kept = duplicate_keepers(atlas.paths, dups)
        aside = len(atlas) - len(kept)
        log(
            tr(
                f"{aside} near-duplicates set aside before grouping",
                f"{aside} 张近重复图先放到一边，不参与分组",
            )
        )
        result = expand_clustering(_cluster(a, atlas.subset(kept)), kept, len(atlas))
    else:
        result = _cluster(a, atlas)
    return result, dups


def _export(a: argparse.Namespace, atlas: Atlas, folders: list[str], out: Path) -> None:
    from styleatlas.dataset import spelling_fixes
    from styleatlas.export import export_folders, parse_tags

    respell = spelling_fixes(atlas.paths) if a.fix_tag_spelling else None
    done = export_folders(
        atlas,
        folders,
        out / "folders",
        mode=a.export,
        trigger_captions=a.trigger_captions,
        layout=a.layout,
        strip_tags=parse_tags(a.strip_tags or ""),
        respell=respell,
    )
    verb = "已复制" if a.export == "copy" else "已链接"
    log(
        tr(
            f"{a.export}: {done.placed} images into {done.folder}",
            f"{verb} {done.placed} 张到 {done.folder}",
        )
    )
    export_notes(done, folders, a.layout, a.trigger_captions, respell)
    if a.layout == "kohya":
        from styleatlas.export import steps_per_epoch

        steps = steps_per_epoch(folders)
        log(
            tr(
                f"one epoch = {steps} steps at batch size 1 (images x repeats)",
                f"batch size 1 时，每个 epoch 约 {steps} 步（张数 × repeats）",
            )
        )
        if a.repeats == "auto":
            log(
                tr(
                    "repeats (the number before each folder name) were set so that each folder "
                    "gives about 100 images per epoch: small folders repeat more, so every style "
                    "weighs about the same",
                    "repeats（文件夹名称前面的数字）是自动算的：让每个文件夹每个 epoch 约 100 张，"
                    "张数少的文件夹重复较多次，各画风的份量就差不多",
                )
            )
    for p, why in done.failed:
        log(tr(f"not exported {p}: {why}", f"没有导出 {p}：{why}"))


def _note_lost_groups(result, folders: list[str]) -> None:
    """Groups none of whose images reach a style folder (all set aside as duplicates, outliers,
    exclusions, or too few left): said here, as their folder numbers are skipped."""
    from styleatlas.dataset import is_unassigned

    lost = [
        c.id + 1
        for c in result.clusters
        if all(folders[i].startswith("_") or is_unassigned(folders[i]) for i in c.members)
    ]
    if lost:
        names = ", ".join(f"{n:02d}" for n in lost)
        log(
            tr(
                f"note: style {names} kept too few images after duplicates, outliers and "
                "exclusions;"
                " it has no folder (its number is skipped)",
                f"注意：第 {names} 组拿掉重复、离群和排除的图之后太少，没有文件夹（编号跳过）",
            )
        )


def _plan(
    a: argparse.Namespace, atlas: Atlas, result, dups: list[list[int]] | None
) -> tuple[list[str], dict]:
    from styleatlas.dataset import plan_folders, tag_summary

    excluded = web_exclusions(atlas, Path(a.folder))
    if excluded:
        log(
            tr(
                f"{len(excluded)} image(s) you excluded in the web app go to _excluded",
                f"{len(excluded)} 张你在网页界面排除的图会放到 _excluded",
            )
        )
    outliers = None
    if a.drop_outliers:  # the N most atypical among the images not already excluded
        skip = set(excluded)
        order = [int(i) for i in np.argsort(-outlier_scores(atlas.style))]
        outliers = [i for i in order if i not in skip][: a.drop_outliers]
    name = a.name or Path(a.folder).resolve().name
    safe = "".join(ch if ch.isalnum() or ch in " -_." else "_" for ch in name).strip() or "style"
    folders = plan_folders(
        atlas.paths,
        result,
        a.layout,
        safe,
        a.repeats,
        dups,
        outliers,
        min_size=a.min_size,
        excluded=excluded,
        max_per_group=a.max_per_group,
        style=atlas.style,
    )
    trimmed = sum(f == "_trimmed" for f in folders)
    if trimmed:
        log(
            tr(
                f"{trimmed} image(s) beyond {a.max_per_group} per group go to _trimmed",
                f"每组超过 {a.max_per_group} 张的 {trimmed} 张放到 _trimmed",
            )
        )
    _note_lost_groups(result, folders)
    return folders, tag_summary(atlas.paths, result)


def _when(pos: np.ndarray | None, members: list[int]) -> str:
    span = timeline_span(pos, members)
    if span is None:
        return ""
    q1, med, q3 = span
    return tr(
        f"  when {med:4.0%} [{q1:.0%}-{q3:.0%}]", f"  时间位置 {med:4.0%} [{q1:.0%}-{q3:.0%}]"
    )


CONSISTENCY_WORDS_ZH = {
    "tight": "很一致",
    "like one artist": "在一位画师的正常范围内；两三位画师混在一起也常落在这里",
    "mixed": "可能混了不同画风或时期（约 1 成的单一画师也会落在这里）；下面的分组把它分开",
}
CONSISTENCY_WORDS = {
    "tight": "very consistent",
    "like one artist": (
        "in the range of a single artist; a mix of two or three artists often reads this way too"
    ),
    "mixed": (
        "may be a mix of styles or periods (about 1 in 10 single artists also lands here); "
        "the groups below split it"
    ),
}


def _log_where_they_went(folders: list[str]) -> None:
    """One line that accounts for every image: how many went into style folders and how many
    were set aside, and why (duplicates, outliers, unassigned...)."""
    from collections import Counter

    from styleatlas.dataset import is_unassigned

    aside = Counter(f for f in folders if f.startswith("_") or is_unassigned(f))
    kept = len(folders) - sum(aside.values())
    groups = len({f for f in folders if not (f.startswith("_") or is_unassigned(f))})
    rest = ", ".join(f"{name} {n}" for name, n in sorted(aside.items()))
    log(
        tr(
            f"{len(folders)} images: {kept} in {groups} style folders"
            + (f"; set aside: {rest}" if rest else ""),
            f"共 {len(folders)} 张：{kept} 张在 {groups} 个画风文件夹"
            + (f"；另外放：{rest}" if rest else ""),
        )
    )


def _one_lora_hint(a: argparse.Namespace, result, spread) -> None:
    """How to get one folder when the output suggests one LoRA: a timeline verdict of no link or
    only drift, or several automatic groups in a folder as consistent as one artist."""
    from styleatlas.timeline import TIMELINE, verdict

    if result.method == TIMELINE and verdict(result.params) in ("none", "drift"):
        log(
            tr(
                "to train one LoRA on all of it: run the same command with --k 1 instead of "
                "--granularity timeline (one folder)",
                "要用全部作品训练一个 LoRA：把 --granularity timeline 换成 --k 1 再运行一次"
                "（全部放进同一个文件夹）",
            )
        )
        return
    automatic = a.granularity == "auto" and a.k is None and a.threshold is None
    if automatic and result.n_clusters > 1 and spread is not None and spread.verdict != "mixed":
        log(
            tr(
                f"if these are all one artist's works, the {result.n_clusters} groups are most "
                "likely small differences within one style; for one LoRA add --k 1 (one folder)",
                f"如果这些都是同一位画师的作品，分出的 {result.n_clusters} 组多半只是同一画风里的"
                "细部差异；要训练一个 LoRA，加 --k 1（全部放进同一个文件夹）",
            )
        )


def _log_consistency(atlas: Atlas):
    """Print how consistent the folder's style is; the Consistency, or None if too few images."""
    from styleatlas.consistency import consistency

    c = consistency(atlas.style)
    if c is not None:
        log(
            tr(
                f"style consistency: spread {c.spread:.3f}, more spread than {c.percentile:.0f}% "
                "of "
                f"single artists ({CONSISTENCY_WORDS[c.verdict]})",
                f"画风一致性：{CONSISTENCY_WORDS_ZH[c.verdict]}"
                f"（比 {c.percentile:.0f}% 的单一画师分散；分散度 {c.spread:.3f}，越大越杂）",
            )
        )
    return c


def _print_groups(
    atlas: Atlas, result, folders: list[str], tags: dict, time_source: str = "none"
) -> None:
    from collections import Counter

    pos = timeline(atlas.paths, time_source)
    if pos is not None:
        log(
            tr(
                "when = position in the folder's timeline (0% oldest): median [middle half]",
                "时间位置 = 在作品时间轴上的位置（0% 最早）：中位数 [中间一半]",
            )
        )

    def by_style(item: tuple[str, int]) -> tuple[bool, str]:  # 2_x_style01 before 25_x_style11
        head, _, rest = item[0].partition("_")
        return item[0].startswith("_"), rest if head.isdigit() else item[0]

    for folder, n in sorted(Counter(folders).items(), key=by_style):
        members = [i for i, f in enumerate(folders) if f == folder]
        if folder.startswith("_"):
            log(f"  {pad(folder, 28)}{n:5d}")
            continue
        cid = int(result.labels[members[0]])
        top = ", ".join(r["tag"] for r in tags.get(cid, [])[:5]) if cid >= 0 else ""
        few = tr("  (few images)", "  （张数少）") if n < FEW_FOR_LORA else ""
        look = ""
        if atlas.looks is not None:
            words = describe(profile(atlas.looks, members), "zh" if chinese() else "en")
            look = f"  [{words or tr('average look', '外观平均')}]"
        log(f"  {pad(folder, 28)}{n:5d}{few}{_when(pos, members)}{look}  {top}")
    small = [f for f, n in Counter(folders).items() if not f.startswith("_") and n < FEW_FOR_LORA]
    if small:
        names = ", ".join(sorted(small)[:6]) + (" ..." if len(small) > 6 else "")
        log(
            tr(
                f"note: {len(small)} group(s) have fewer than {FEW_FOR_LORA} images ({names}); "
                "common "
                "advice is 8-15+ per style LoRA, and automatic repeats repeat a small group more, "
                "which can overfit it: merge them (web app), use a coarser --granularity, or set "
                "--repeats",
                f"注意：{len(small)} 组少于 {FEW_FOR_LORA} 张（{names}）；一般建议每个画风 LoRA "
                "至少 8~15 张，而且自动 repeats 会让小组重复很多次，容易过拟合："
                "可以在网页界面合并、"
                "用较粗的 --granularity，或用 --repeats 指定",
            )
        )
