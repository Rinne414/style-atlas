"""Command line: style-atlas <command> ...  (run `style-atlas <command> -h` for options)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import numpy as np

from styleatlas import __version__
from styleatlas.atlas import Atlas, EncodeOptions, build_atlas, embed_paths
from styleatlas.cluster import GRANULARITY, METHODS, PERIODS, cluster_styles, outlier_scores
from styleatlas.encoder import CROP_MODES, RESOLUTIONS
from styleatlas.images import TIME_SOURCES, find_images, labels_from_folders
from styleatlas.metrics import StyleScale, group_difference, split_half_noise, unit
from styleatlas.project import PROJECTIONS

SOFT_PERIODS = 100  # below this, k-means periods changed with the seed (agreement ARI 0.3-0.7)
NEUTRALIZE_HELP = (
    "ignore the N strongest directions of variation (try 1) when the same characters appear in "
    "many styles; do not use it on a mix of different artists"
)


REFERENCE_HELP = (
    "folder of styles you already know (artists, forum recipes); adds an originality axis: "
    "distance from each image to its closest reference"
)


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _opts(a: argparse.Namespace) -> EncodeOptions:
    from styleatlas.safety import limit_resources

    limit_resources(a.threads)
    return EncodeOptions(
        device=a.device,
        crop=a.crop,
        batch_size=a.batch,
        resolution=a.resolution,
        db_path=Path(a.cache_db) if a.cache_db else None,
    )


def _atlas(a: argparse.Namespace, folder: str, exclude: list[Path] | None = None) -> Atlas:
    atlas = build_atlas(Path(folder), _opts(a), log, recursive=not a.no_recursive, exclude=exclude)
    for p, why in atlas.failed:
        log(f"skipped {p}: {why}")
    if getattr(a, "neutralize", 0):
        atlas, a.neutralizer = atlas.neutralized(a.neutralize)  # reused for --reference
        log(f"ignoring the {a.neutralize} strongest direction(s) of variation (subject axis)")
    return atlas


def _reference(a: argparse.Namespace, neutral=None) -> Atlas | None:
    """The --reference folder (styles you already know), embedded the same way."""
    if not getattr(a, "reference", None):
        return None
    ref = build_atlas(Path(a.reference), _opts(a), log, recursive=True)
    for p, why in ref.failed:
        log(f"reference skipped {p}: {why}")
    neutral = neutral or getattr(a, "neutralizer", None)  # same space as the folder
    if neutral is not None:
        ref = replace(ref, style=neutral.apply(ref.style))
    log(f"reference: {len(ref)} images from {a.reference}")
    return ref


def _cluster(a: argparse.Namespace, atlas: Atlas):
    method, k, threshold = a.method, a.k, a.threshold
    if a.granularity == "period" and threshold is None:
        if method != "agglomerative":
            raise ValueError("--granularity period uses k-means; leave out --method")
        method, k = "kmeans", a.k or PERIODS
        if len(atlas) < SOFT_PERIODS:
            log(
                f"note: with fewer than {SOFT_PERIODS} images the period boundaries are soft; "
                "check them in the web app (serve)"
            )
    elif threshold is None:
        threshold = GRANULARITY.get(a.granularity)  # None for auto
    result = cluster_styles(
        atlas.style, method=method, threshold=threshold, n_clusters=k, min_size=a.min_size
    )
    cut = result.params.get("threshold")
    how = f", cut {cut} ({'auto' if result.params.get('auto') else 'set'})" if cut else ""
    log(f"{result.n_clusters} styles, {result.n_unassigned} unassigned ({result.method}{how})")
    if "note" in result.params:
        log("note: " + result.params["note"])
    return result


def cmd_embed(a: argparse.Namespace) -> int:
    atlas = _atlas(a, a.folder)
    log(f"{len(atlas)} images embedded, {len(atlas.failed)} skipped")
    return 0


def cmd_cluster(a: argparse.Namespace) -> int:
    from styleatlas.dataset import parse_repeats

    parse_repeats(a.repeats)
    if a.trigger_captions and not a.export:
        raise ValueError("--trigger-captions only applies with --export copy|link")
    from styleatlas.export import output_dir, write_table
    from styleatlas.report import write_map

    out = Path(a.out) if a.out else output_dir(Path(a.folder))
    atlas = _atlas(a, a.folder, exclude=[out])
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
    from styleatlas.export import export_folders

    done = export_folders(
        atlas,
        folders,
        out / "folders",
        mode=a.export,
        trigger_captions=a.trigger_captions,
        layout=a.layout,
    )
    log(f"{a.export}: {done.placed} images into {done.folder}")
    for p, why in done.failed:
        log(f"not exported {p}: {why}")


def _plan(
    a: argparse.Namespace, atlas: Atlas, result, dups: list[list[int]] | None
) -> tuple[list[str], dict]:
    from styleatlas.dataset import plan_folders, tag_summary

    outliers = None
    if a.drop_outliers:
        outliers = [int(i) for i in np.argsort(-outlier_scores(atlas.style))[: a.drop_outliers]]
    name = a.name or Path(a.folder).resolve().name
    safe = "".join(ch if ch.isalnum() or ch in " -_." else "_" for ch in name).strip() or "style"
    folders = plan_folders(
        atlas.paths, result, a.layout, safe, a.repeats, dups, outliers, min_size=a.min_size
    )
    return folders, tag_summary(atlas.paths, result)


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
        log(f"  {folder:28s} {n:5d}{few}{_when(pos, members)}  {top}")
    small = [f for f, n in Counter(folders).items() if not f.startswith("_") and n < FEW_FOR_LORA]
    if small:
        log(
            f"note: {len(small)} group(s) have fewer than {FEW_FOR_LORA} images; common advice is "
            "8-15+ per style LoRA, so consider merging them (web app) or a coarser --granularity"
        )


def cmd_audit(a: argparse.Namespace) -> int:
    from styleatlas.dataset import audit

    report = audit(find_images(Path(a.folder)), min_side=a.min_side, max_ratio=a.max_ratio)
    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        return 0
    for key, value in report["summary"].items():
        print(f"{key:24s} {value}")
    for key, files in report["files"].items():
        for f in files[: a.show]:
            print(f"  [{key}] {f}")
    return 0


LARGE_MAP = 8000  # thumbnails make the single-file map ~2 KB per image


def cmd_map(a: argparse.Namespace) -> int:
    from styleatlas.report import write_map

    atlas = _atlas(a, a.folder)
    if len(atlas) > LARGE_MAP:
        log(f"{len(atlas)} images: the HTML file will be large; `style-atlas serve` loads faster")
    result = _cluster(a, atlas)
    out = Path(a.out or Path(a.folder) / "style_atlas_map.html")
    path = write_map(
        atlas,
        result,
        out,
        a.projection,
        a.thumb,
        a.title,
        progress=log,
        time_source=a.time,
        reference=_reference(a),
    )
    print(path)
    return 0


def cmd_search(a: argparse.Namespace) -> int:
    from styleatlas.search import search

    opts = _opts(a)
    qpaths = [p for q in a.query for p in find_images(Path(q))]
    qkept, qstyle, _, failed = embed_paths(qpaths, opts, log)
    if not qkept:
        log("no readable query images")
        return 1
    atlas = build_atlas(Path(a.within), opts, log, recursive=not a.no_recursive)
    if a.neutralize:
        atlas, neutral = atlas.neutralized(a.neutralize)
        qstyle = neutral.apply(qstyle)
    query_files = {q.resolve() for q in qkept}
    same = {i for i, p in enumerate(atlas.paths) if p.resolve() in query_files}
    results = search(qstyle, atlas.style, top=a.top, combine=a.combine, exclude=same)
    names = ["(all queries)"] if a.combine else [str(p) for p in qkept]
    rows = [
        {
            "query": names[qi],
            "rank": r + 1,
            "path": atlas.rel(h.index),
            "score": round(h.score, 4),
            "cosine": round(h.cosine, 4),
        }
        for qi, hits in enumerate(results)
        for r, h in enumerate(hits)
    ]
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    else:
        for row in rows:
            print(f"{row['rank']:3d}  {row['cosine']:.3f}  {row['path']}    <- {row['query']}")
    if a.copy_to:
        _copy_matches(atlas, [h.index for hits in results for h in hits], Path(a.copy_to))
    return 0


def _copy_matches(atlas, indices: list[int], dest: Path) -> None:
    from styleatlas.export import export_folders

    unique = list(dict.fromkeys(indices))  # several queries may find the same image
    done = export_folders(atlas.subset(unique), ["matches"] * len(unique), dest)
    log(f"copied {done.placed} matches to {done.folder / 'matches'}")
    for p, why in done.failed:
        log(f"not copied {p}: {why}")


def cmd_outliers(a: argparse.Namespace) -> int:
    atlas = _atlas(a, a.folder)
    scores = outlier_scores(atlas.style)
    for i in np.argsort(-scores)[: a.top]:
        print(f"{scores[i]:.3f}  {atlas.rel(int(i))}")
    return 0


def cmd_duplicates(a: argparse.Namespace) -> int:
    from styleatlas.duplicates import near_duplicate_groups

    atlas = _atlas(a, a.folder)
    groups = near_duplicate_groups(atlas.style, atlas.content, a.threshold)
    if a.json:
        print(json.dumps([[atlas.rel(i) for i in g] for g in groups], ensure_ascii=False, indent=1))
        return 0
    extra = sum(len(g) - 1 for g in groups)
    log(f"{len(groups)} near-duplicate groups ({extra} images beyond the first of each group)")
    for n, g in enumerate(groups, 1):
        print(f"group {n}: " + "  |  ".join(atlas.rel(i) for i in g))
    return 0


def cmd_compare(a: argparse.Namespace) -> int:
    opts = _opts(a)
    groups = []
    for folder in (a.a, a.b):
        kept, style, _, _ = embed_paths(find_images(Path(folder)), opts, log)
        if len(kept) < 2:
            log(f"{folder}: need at least 2 readable images, found {len(kept)}")
            return 1
        groups.append(style)
    dist, p = group_difference(groups[0], groups[1], rounds=a.rounds)
    scale = StyleScale(noise_floor=a.noise_floor) if a.noise_floor else StyleScale()
    print(
        json.dumps(
            {
                "images": [len(groups[0]), len(groups[1])],
                "centroid_distance": round(dist, 4),
                "z": round(scale.z(dist), 2),
                "verdict": scale.verdict(dist),
                "permutation_p": round(p, 4),
            },
            indent=1,
        )
    )
    return 0


def cmd_calibrate(a: argparse.Namespace) -> int:
    root = Path(a.folder)
    paths = find_images(root)
    kept, style, _, _ = embed_paths(paths, _opts(a), log)
    labels = np.array(labels_from_folders(kept, root))
    floors = {}
    for lbl in sorted(set(labels.tolist()) - {""}):
        idx = np.flatnonzero(labels == lbl)
        if len(idx) >= 4:
            floors[lbl] = round(split_half_noise(style[idx]), 4)
    if not floors:
        log("need sub-folders with >= 4 images of one style each")
        return 1
    print(
        json.dumps(
            {"per_group": floors, "noise_floor": round(float(np.median(list(floors.values()))), 4)},
            indent=1,
        )
    )
    return 0


def cmd_bench(a: argparse.Namespace) -> int:
    from styleatlas.bench import run_bench

    if not a.npz and not a.folder:
        log("give a folder whose sub-folders are the labels, or --npz")
        return 1
    content = None
    if a.npz:
        with np.load(a.npz) as z:
            keys = list(z.files)
            style = np.stack([z[k] for k in keys]).astype(np.float32)
        style = unit(style)
        labels = [k.rsplit(a.sep, 1)[0] for k in keys]
    else:
        root = Path(a.folder)
        kept, style, content, _ = embed_paths(find_images(root), _opts(a), log)
        if a.labels == "prefix":
            labels = [p.stem.rsplit(a.sep, 1)[0] for p in kept]
        else:
            labels = labels_from_folders(kept, root)
    dedupe = None if a.keep_duplicates else a.dup_threshold
    report = run_bench(style, labels, trials=a.trials, content=content, dedupe=dedupe)
    print(json.dumps(report, indent=1))
    return 0


def cmd_taste(a: argparse.Namespace) -> int:
    from styleatlas.taste import TasteModel, train_taste

    opts = _opts(a)
    if a.taste_cmd == "train":
        like = embed_paths(find_images(Path(a.like)), opts, log)[1]
        dislike = embed_paths(find_images(Path(a.dislike)), opts, log)[1]
        from styleatlas.encoder import encoder_signature

        model = train_taste(like, dislike, encoder_signature(opts.crop, opts.resolution))
        saved = model.save(Path(a.model))
        log(
            f"saved {saved}: {model.n_like} liked / {model.n_dislike} disliked, "
            f"CV AUC {model.cv_auc:.3f}"
        )
        return 0
    model = TasteModel.load(Path(a.model))
    atlas = build_atlas(Path(a.folder), opts, log)
    if model.signature != atlas.signature:
        log(f"model was trained on {model.signature}, images embedded as {atlas.signature}")
        return 1
    scores = model.score(atlas.style)
    for i in np.argsort(-scores):
        print(f"{scores[i]:.3f}  {atlas.rel(int(i))}")
    return 0


def cmd_serve(a: argparse.Namespace) -> int:
    from styleatlas.serve import StyleAtlasApp, serve

    k, a.neutralize = a.neutralize, 0  # the app keeps raw vectors and applies k itself
    app = StyleAtlasApp(
        _atlas(a, a.folder),
        _opts(a),
        a.projection,
        a.title,
        progress=log,
        time_source=a.time,
        neutralize=k,
        reference=_reference(a),
    )
    serve(app, port=a.port, open_browser=not a.no_browser)
    return 0


def _common(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("embedding")
    g.add_argument("--device", default="auto", help="auto, cpu or cuda (default auto)")
    g.add_argument("--crop", default="center", choices=CROP_MODES)
    g.add_argument("--resolution", type=int, default=224, choices=RESOLUTIONS)
    g.add_argument("--batch", type=int, default=8)
    g.add_argument("--threads", type=int, default=8, help="CPU threads cap (0 = all)")
    g.add_argument(
        "--cache-db", help="vector cache file (default ~/.cache/style-atlas/vectors.sqlite)"
    )
    g.add_argument("--no-recursive", action="store_true", help="do not look into sub-folders")


def _cluster_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("clustering")
    g.add_argument(
        "--granularity",
        default="auto",
        choices=["auto", "period", *GRANULARITY],
        help="auto picks the cut from the data; period splits one artist into --k periods "
        f"(default {PERIODS}, k-means, every image assigned)",
    )
    g.add_argument(
        "--threshold", type=float, help="hub-corrected distance cut (overrides granularity)"
    )
    g.add_argument("--k", type=int, help="force this many styles (with period: periods)")
    g.add_argument("--method", default="agglomerative", choices=METHODS)
    g.add_argument("--min-size", type=int, default=3, help="smaller groups become 'unassigned'")
    g.add_argument("--projection", default="auto", choices=PROJECTIONS)
    g.add_argument(
        "--time",
        default="none",
        choices=TIME_SOURCES,
        help="show when each style was made: file-name id (Pixiv/Danbooru) or mtime",
    )
    g.add_argument("--neutralize", type=int, default=0, metavar="N", help=NEUTRALIZE_HELP)
    g.add_argument("--reference", metavar="DIR", help=REFERENCE_HELP)
    g.add_argument("--thumb", type=int, help="thumbnail px in the map (default 128, 72 above 2k)")


Adder = Callable[..., argparse.ArgumentParser]
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


def _add_folder_commands(add: Adder) -> None:
    add("embed", cmd_embed, "embed and cache a folder").add_argument("folder")
    p = add(
        "cluster", cmd_cluster, "group a folder by style; write CSV/JSON, map, optional folders"
    )
    p.add_argument("folder")
    p.add_argument("-o", "--out")
    p.add_argument("--no-map", action="store_true")
    _lora_args(p)
    _cluster_args(p)
    p = add("map", cmd_map, "write the interactive 3D style map (one HTML file)")
    p.add_argument("folder")
    p.add_argument("-o", "--out")
    p.add_argument("--title")
    _cluster_args(p)
    p = add("serve", cmd_serve, "open the interactive map in the browser with live search")
    p.add_argument("folder")
    p.add_argument("--port", type=int, default=8770)
    p.add_argument("--title")
    p.add_argument("--projection", default="auto", choices=PROJECTIONS)
    p.add_argument("--time", default="none", choices=TIME_SOURCES)
    p.add_argument("--neutralize", type=int, default=0, metavar="N", help=NEUTRALIZE_HELP)
    p.add_argument("--reference", metavar="DIR", help=REFERENCE_HELP)
    p.add_argument("--no-browser", action="store_true")


def _add_inspect_commands(add: Adder) -> None:
    p = add("search", cmd_search, "find images in a folder whose style is closest to the query")
    p.add_argument("query", nargs="+", help="query image(s) or folder(s)")
    p.add_argument("--in", dest="within", required=True, help="folder to search")
    p.add_argument("--top", type=int, default=20)
    p.add_argument(
        "--combine",
        action="store_true",
        help="treat all queries as one style (from 3 images up, a model learned from them)",
    )
    p.add_argument(
        "--copy-to", metavar="DIR", help="copy the matches (with captions) into a new folder here"
    )
    p.add_argument("--neutralize", type=int, default=0, metavar="N", help=NEUTRALIZE_HELP)
    p.add_argument("--json", action="store_true")
    p = add("outliers", cmd_outliers, "images least like the rest of a folder")
    p.add_argument("folder")
    p.add_argument("--top", type=int, default=30)
    p = add("audit", cmd_audit, "check a training folder: sizes, aspect ratios, captions")
    p.add_argument("folder")
    p.add_argument("--min-side", type=int, default=512, help="training resolution to check against")
    p.add_argument("--max-ratio", type=float, default=2.5)
    p.add_argument("--show", type=int, default=10, help="files to list per problem")
    p.add_argument("--json", action="store_true")
    p = add("duplicates", cmd_duplicates, "near-duplicate groups (same picture, crops, frames)")
    p.add_argument("folder")
    p.add_argument(
        "--threshold", type=float, default=0.95, help="min(style, content) cosine; 0.92 is looser"
    )
    p.add_argument("--json", action="store_true")


def _add_measure_commands(add: Adder) -> None:
    p = add("compare", cmd_compare, "do two folders differ in style? distance, z units, p-value")
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--rounds", type=int, default=999)
    p.add_argument("--noise-floor", type=float, help="from `calibrate` (default 0.071)")
    p = add("calibrate", cmd_calibrate, "estimate the noise floor from one-style sub-folders")
    p.add_argument("folder")
    p = add("bench", cmd_bench, "score retrieval and clustering against sub-folder labels")
    p.add_argument("folder", nargs="?")
    p.add_argument("--npz", help="precomputed vectors; label = key prefix before --sep")
    p.add_argument("--labels", choices=["folder", "prefix"], default="folder")
    p.add_argument("--sep", default="__")
    p.add_argument("--keep-duplicates", action="store_true", help="score duplicates too")
    p.add_argument("--dup-threshold", type=float, default=0.92)
    p.add_argument("--trials", type=int, default=30)
    p = add("taste", cmd_taste, "train or apply a personal like/dislike model", common=False)
    tsub = p.add_subparsers(dest="taste_cmd", required=True)
    t1 = tsub.add_parser("train", help="learn from a liked and a disliked folder")
    t1.add_argument("--like", required=True)
    t1.add_argument("--dislike", required=True)
    t1.add_argument("--model", default="taste_model.npz")
    t2 = tsub.add_parser("score", help="rank a folder with a trained model")
    t2.add_argument("folder")
    t2.add_argument("--model", default="taste_model.npz")
    for t in (t1, t2):
        _common(t)


def cmd_doctor(a: argparse.Namespace) -> int:
    from styleatlas.doctor import run

    return run()


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="style-atlas", description=__doc__)
    ap.add_argument("--version", action="version", version=f"style-atlas {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name: str, fn, help_: str, common: bool = True) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_, description=help_)
        p.set_defaults(fn=fn)
        if common:
            _common(p)
        return p

    add(
        "doctor",
        cmd_doctor,
        "check Python, torch, GPU, model download and disk space",
        common=False,
    )
    _add_folder_commands(add)
    _add_inspect_commands(add)
    _add_measure_commands(add)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except (FileNotFoundError, ValueError) as e:
        log(f"error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
