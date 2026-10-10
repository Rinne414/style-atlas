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
    log,
    web_exclusions,
)
from styleatlas.cluster import outlier_scores
from styleatlas.images import timeline, timeline_span
from styleatlas.lang import chinese, pad, tr
from styleatlas.look import describe, profile

FEW_FOR_LORA = 8  # style-LoRA guides suggest starting at 8-15 images (docs/LORA_GUIDE.md)


def _lora_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("training dataset")
    g.add_argument(
        "--export",
        choices=["copy", "link"],
        help=tr("also place images into style folders", "也把圖放進各畫風群的資料夾"),
    )
    g.add_argument(
        "--layout",
        choices=["plain", "kohya"],
        default="plain",
        help=tr(
            "kohya: <repeats>_<name>_styleNN folders; set-aside folders are skipped",
            "kohya：<重複次數>_<名稱>_styleNN 資料夾；另外放的資料夾會被略過",
        ),
    )
    g.add_argument(
        "--name",
        help=tr(
            "concept name for kohya folders (default: the folder name)",
            "kohya 資料夾用的概念名稱（預設：資料夾名稱）",
        ),
    )
    g.add_argument(
        "--repeats",
        default="auto",
        help=tr(
            "kohya repeats per style folder, or auto (images x repeats about 100 per epoch)",
            "kohya 每個畫風資料夾的重複次數，或 auto（每個 epoch 張數 × 重複次數約 100）",
        ),
    )
    g.add_argument(
        "--trigger-captions",
        action="store_true",
        help=tr(
            "start every exported caption with its group's trigger word (artistX_style01)",
            "每個匯出的標註開頭加上該群的觸發詞（artistX_style01）",
        ),
    )
    g.add_argument(
        "--dedupe",
        action="store_true",
        help=tr(
            "keep the best copy of each near-duplicate group; others go to _duplicates",
            "每組近重複圖只留最好的一張，其餘放進 _duplicates",
        ),
    )
    g.add_argument(
        "--drop-outliers",
        type=int,
        default=0,
        metavar="N",
        help=tr("move the N least typical images to _outliers", "把最不典型的 N 張移到 _outliers"),
    )
    g.add_argument(
        "--strip-tags",
        metavar="TAGS",
        help=tr(
            'remove these caption tags in the exported copies, e.g. "sketch, monochrome"',
            '從匯出的複本標註中移除這些標籤，例如 "sketch, monochrome"',
        ),
    )
    g.add_argument(
        "--max-per-group",
        type=_positive_int,
        metavar="N",
        help=tr(
            "keep at most N images per style, chosen to cover it; the rest go to _trimmed",
            "每個畫風群最多留 N 張（挑能涵蓋整群的），其餘放進 _trimmed",
        ),
    )


def cmd_cluster(a: argparse.Namespace) -> int:
    from styleatlas.dataset import parse_repeats

    parse_repeats(a.repeats)
    if a.trigger_captions and not a.export:
        raise ValueError(
            tr(
                "--trigger-captions only applies with --export copy|link",
                "--trigger-captions 只在 --export copy|link 時有用",
            )
        )
    from styleatlas.export import output_dir, write_table
    from styleatlas.report import write_map

    out = Path(a.out) if a.out else output_dir(Path(a.folder))
    atlas = _atlas(a, a.folder, exclude=[out]).with_looks(_opts(a), log)
    result, dups = _group(a, atlas)
    folders, tags = _plan(a, atlas, result, dups)
    csv_path, json_path = write_table(atlas, result, out, folders, tags)
    log(tr(f"wrote {csv_path} and {json_path}", f"已寫出 {csv_path} 和 {json_path}"))
    if getattr(a, "fitted_space", None) is None:  # the reference was measured on plain CSD
        _log_consistency(atlas)
    _print_groups(atlas, result, folders, tags, a.time)
    if a.export:
        _export(a, atlas, folders, out)
    else:
        log(
            tr(
                "the folder names above are the plan; add --export copy (or link) to write the "
                "folders",
                "上面的資料夾名稱只是規劃；加 --export copy（或 link）才會真的建立資料夾",
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
        log(tr(f"map: {path}", f"地圖：{path}"))
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
                f"{aside} 張近重複圖先放到一邊，不參與分群",
            )
        )
        result = expand_clustering(_cluster(a, atlas.subset(kept)), kept, len(atlas))
    else:
        result = _cluster(a, atlas)
    return result, dups


def _export(a: argparse.Namespace, atlas: Atlas, folders: list[str], out: Path) -> None:
    from styleatlas.export import export_folders, parse_tags

    done = export_folders(
        atlas,
        folders,
        out / "folders",
        mode=a.export,
        trigger_captions=a.trigger_captions,
        layout=a.layout,
        strip_tags=parse_tags(a.strip_tags or ""),
    )
    verb = "已複製" if a.export == "copy" else "已連結"
    log(
        tr(
            f"{a.export}: {done.placed} images into {done.folder}",
            f"{verb} {done.placed} 張到 {done.folder}",
        )
    )
    if a.layout == "kohya":
        from styleatlas.export import steps_per_epoch

        steps = steps_per_epoch(folders)
        log(
            tr(
                f"one epoch = {steps} steps at batch size 1 (images x repeats)",
                f"batch size 1 時，每個 epoch 約 {steps} 步（張數 × repeats）",
            )
        )
    for p, why in done.failed:
        log(tr(f"not exported {p}: {why}", f"沒有匯出 {p}：{why}"))


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
                f"注意：第 {names} 群拿掉重複、離群和排除的圖之後太少，沒有資料夾（編號跳過）",
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
                f"{len(excluded)} 張你在網頁介面排除的圖會放到 _excluded",
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
                f"每群超過 {a.max_per_group} 張的 {trimmed} 張放到 _trimmed",
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
        f"  when {med:4.0%} [{q1:.0%}-{q3:.0%}]", f"  時間位置 {med:4.0%} [{q1:.0%}-{q3:.0%}]"
    )


CONSISTENCY_WORDS_ZH = {
    "tight": "很一致",
    "like one artist": "在一位畫師的正常範圍內；兩三位畫師混在一起也常落在這裡",
    "mixed": "多半混了不同畫風或時期；下面的分群把它分開",
}
CONSISTENCY_WORDS = {
    "tight": "very consistent",
    "like one artist": (
        "in the range of a single artist; a mix of two or three artists often reads this way too"
    ),
    "mixed": "probably a mix of styles or periods; the groups below split it",
}


def _log_consistency(atlas: Atlas) -> None:
    from styleatlas.consistency import consistency

    c = consistency(atlas.style)
    if c is not None:
        log(
            tr(
                f"style consistency: spread {c.spread:.3f}, more spread than {c.percentile:.0f}% "
                "of "
                f"single artists ({CONSISTENCY_WORDS[c.verdict]})",
                f"畫風一致性：{CONSISTENCY_WORDS_ZH[c.verdict]}"
                f"（比 {c.percentile:.0f}% 的單一畫師分散；分散度 {c.spread:.3f}，越大越雜）",
            )
        )


def _print_groups(
    atlas: Atlas, result, folders: list[str], tags: dict, time_source: str = "none"
) -> None:
    from collections import Counter

    pos = timeline(atlas.paths, time_source)
    if pos is not None:
        log(
            tr(
                "when = position in the folder's timeline (0% oldest): median [middle half]",
                "時間位置 = 在作品時間軸上的位置（0% 最早）：中位數 [中間一半]",
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
        few = tr("  (few images)", "  （張數少）") if n < FEW_FOR_LORA else ""
        look = ""
        if atlas.looks is not None:
            words = describe(profile(atlas.looks, members), "zh" if chinese() else "en")
            look = f"  [{words or tr('average look', '外觀平均')}]"
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
                f"注意：{len(small)} 群少於 {FEW_FOR_LORA} 張（{names}）；一般建議每個畫風 LoRA "
                "至少 8～15 張，而且自動 repeats 會讓小群重複很多次，容易過擬合："
                "可以在網頁介面合併、"
                "用較粗的 --granularity，或用 --repeats 指定",
            )
        )
