"""The cluster command: group a folder, plan the LoRA folders (duplicates, outliers, web
exclusions, per-style cap), write the tables and export."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from styleatlas.atlas import Atlas
from styleatlas.cli_common import _atlas, _cluster, _opts, _positive_int, _reference, log
from styleatlas.cluster import outlier_scores
from styleatlas.look import describe, profile

FEW_FOR_LORA = 8  # style-LoRA guides suggest starting at 8-15 images (docs/LORA_GUIDE.md)


def _lora_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("training dataset")
    g.add_argument(
        "--export", choices=["copy", "link"], help="also place images into style folders"
    )
    g.add_argument(
        "--layout",
        choices=["plain", "kohya"],
        default="plain",
        help="kohya: <repeats>_<name>_styleNN folders; set-aside folders are skipped",
    )
    g.add_argument("--name", help="concept name for kohya folders (default: the folder name)")
    g.add_argument(
        "--repeats", default="auto", help="kohya repeats per style folder, or auto (~100 per epoch)"
    )
    g.add_argument(
        "--trigger-captions",
        action="store_true",
        help="start every exported caption with its group's trigger word (artistX_style01)",
    )
    g.add_argument(
        "--dedupe",
        action="store_true",
        help="keep the best copy of each near-duplicate group; others go to _duplicates",
    )
    g.add_argument(
        "--drop-outliers",
        type=int,
        default=0,
        metavar="N",
        help="move N least typical to _outliers",
    )
    g.add_argument(
        "--strip-tags",
        metavar="TAGS",
        help='remove these caption tags in the exported copies, e.g. "sketch, monochrome"',
    )
    g.add_argument(
        "--max-per-group",
        type=_positive_int,
        metavar="N",
        help="keep at most N images per style, chosen to cover it; the rest go to _trimmed",
    )


def cmd_cluster(a: argparse.Namespace) -> int:
    from styleatlas.dataset import parse_repeats

    parse_repeats(a.repeats)
    if a.trigger_captions and not a.export:
        raise ValueError("--trigger-captions only applies with --export copy|link")
    from styleatlas.export import output_dir, write_table
    from styleatlas.report import write_map

    out = Path(a.out) if a.out else output_dir(Path(a.folder))
    atlas = _atlas(a, a.folder, exclude=[out]).with_looks(_opts(a), log)
    dups = None
    if a.dedupe:  # cluster only the kept copies, so a stack of duplicates cannot pose as a style
        from styleatlas.cluster import expand_clustering
        from styleatlas.dataset import duplicate_keepers
        from styleatlas.duplicates import near_duplicate_groups

        dups = near_duplicate_groups(atlas.style, atlas.content)
        kept = duplicate_keepers(atlas.paths, dups)
        log(f"{len(atlas) - len(kept)} near-duplicates set aside before grouping")
        result = expand_clustering(_cluster(a, atlas.subset(kept)), kept, len(atlas))
    else:
        result = _cluster(a, atlas)
    folders, tags = _plan(a, atlas, result, dups)
    csv_path, json_path = write_table(atlas, result, out, folders, tags)
    log(f"wrote {csv_path} and {json_path}")
    _log_consistency(atlas)
    _print_groups(atlas, result, folders, tags, a.time)
    if a.export:
        _export(a, atlas, folders, out)
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
        log(f"map: {path}")
    return 0


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
    log(f"{a.export}: {done.placed} images into {done.folder}")
    for p, why in done.failed:
        log(f"not exported {p}: {why}")


def _plan(
    a: argparse.Namespace, atlas: Atlas, result, dups: list[list[int]] | None
) -> tuple[list[str], dict]:
    from styleatlas.dataset import plan_folders, tag_summary

    excluded = _web_exclusions(atlas, Path(a.folder))
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
        log(f"{trimmed} image(s) beyond {a.max_per_group} per group go to _trimmed")
    return folders, tag_summary(atlas.paths, result)


def _web_exclusions(atlas: Atlas, folder: Path) -> list[int]:
    """Images excluded by hand (X) in the web app: they go to _excluded here too."""
    from styleatlas.export import output_dir
    from styleatlas.persist import RelPathMap

    marks = RelPathMap(output_dir(folder) / "excluded.json", atlas, read_only=True)
    if marks.unreadable:
        log(f"warning: could not read {marks.path}; the web app's exclusions are NOT applied")
    excluded = sorted(i for i, v in marks.values.items() if v is True)
    if excluded:
        log(f"{len(excluded)} image(s) you excluded in the web app go to _excluded")
    return excluded


def _timeline(atlas: Atlas, source: str) -> np.ndarray | None:
    """Each image's position in the folder's timeline (0 oldest, 1 newest; NaN when unknown)."""
    from styleatlas.images import file_time

    times = np.array([file_time(p, source) or np.nan for p in atlas.paths], dtype=float)
    known = ~np.isnan(times)
    if source == "none" or known.sum() < 2:
        return None
    pos = np.full(len(times), np.nan)
    order = np.argsort(times[known], kind="stable")
    pos[np.flatnonzero(known)[order]] = np.arange(known.sum()) / (known.sum() - 1)
    return pos


def _when(pos: np.ndarray | None, members: list[int]) -> str:
    if pos is None:
        return ""
    v = pos[members]
    v = v[~np.isnan(v)]
    if not len(v):
        return ""
    q1, med, q3 = np.percentile(v, [25, 50, 75])
    return f"  when {med:4.0%} [{q1:.0%}-{q3:.0%}]"


CONSISTENCY_WORDS = {
    "tight": "tighter than most single artists",
    "like one artist": "in the range of a single artist",
    "mixed": "more spread than 90% of single artists: probably a mix of styles or periods",
}


def _log_consistency(atlas: Atlas) -> None:
    from styleatlas.consistency import consistency

    c = consistency(atlas.style)
    if c is not None:
        log(
            f"style consistency: spread {c.spread:.3f}, more spread than {c.percentile:.0f}% of "
            f"single artists ({CONSISTENCY_WORDS[c.verdict]})"
        )


def _print_groups(
    atlas: Atlas, result, folders: list[str], tags: dict, time_source: str = "none"
) -> None:
    from collections import Counter

    pos = _timeline(atlas, time_source)
    if pos is not None:
        log("when = position in the folder's timeline (0% oldest): median [middle half]")
    for folder, n in sorted(Counter(folders).items()):
        members = [i for i, f in enumerate(folders) if f == folder]
        if folder.startswith("_"):
            log(f"  {folder:28s} {n:5d}")
            continue
        cid = int(result.labels[members[0]])
        top = ", ".join(r["tag"] for r in tags.get(cid, [])[:5]) if cid >= 0 else ""
        few = "  (few images)" if n < FEW_FOR_LORA else ""
        look = ""
        if atlas.looks is not None:
            look = f"  [{describe(profile(atlas.looks, members)) or 'average look'}]"
        log(f"  {folder:28s} {n:5d}{few}{_when(pos, members)}{look}  {top}")
    small = [f for f, n in Counter(folders).items() if not f.startswith("_") and n < FEW_FOR_LORA]
    if small:
        log(
            f"note: {len(small)} group(s) have fewer than {FEW_FOR_LORA} images; common advice is "
            "8-15+ per style LoRA, so consider merging them (web app) or a coarser --granularity"
        )
