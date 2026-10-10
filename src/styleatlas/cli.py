"""Command line: style-atlas <command> ...  (run `style-atlas <command> -h` for options)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

import numpy as np

from styleatlas import __version__
from styleatlas.atlas import build_atlas, embed_paths
from styleatlas.cli_common import (  # noqa: F401 (re-exported for tests and callers)
    CHARACTERS_HELP,
    NEUTRALIZE_HELP,
    REFERENCE_HELP,
    SOFT_PERIODS,
    _atlas,
    _cluster,
    _log_space,
    _neutralize_count,
    _opts,
    _positive_int,
    _reference,
    _space,
    log,
)
from styleatlas.cli_inspect import cmd_audit, cmd_compare, cmd_duplicates, cmd_outliers
from styleatlas.cli_lora import FEW_FOR_LORA, _lora_args, cmd_cluster  # noqa: F401
from styleatlas.cli_report import cmd_report, report_args
from styleatlas.cli_sort import cmd_sort, sort_args
from styleatlas.cluster import ARTISTS, GRANULARITY, METHODS, PERIODS
from styleatlas.encoder import CROP_MODES, RESOLUTIONS
from styleatlas.images import TIME_SOURCES, find_images, labels_from_folders
from styleatlas.lang import tr
from styleatlas.metrics import (
    PLAIN,
    split_half_noise,
    unit,
)
from styleatlas.project import PROJECTIONS


def cmd_embed(a: argparse.Namespace) -> int:
    atlas = _atlas(a, a.folder)
    n, skipped = len(atlas), len(atlas.failed)
    log(tr(f"{n} images embedded, {skipped} skipped", f"{n} 張已算好向量，{skipped} 張略過"))
    return 0


LARGE_MAP = 8000  # thumbnails make the single-file map ~2 KB per image
FAMILY_CUT = 0.35  # folder means: about 11 families of 269 artists, loose (BENCHMARKS.md)


def cmd_map(a: argparse.Namespace) -> int:
    from styleatlas.report import write_map

    atlas = _atlas(a, a.folder).with_looks(_opts(a), log)
    if a.by_folder:
        from styleatlas.atlas import folder_atlas

        atlas = folder_atlas(atlas)
        if len(atlas) < 3:
            log(f"{a.folder} has {len(atlas)} sub-folders; --by-folder needs at least 3")
            return 1
        log(f"{len(atlas)} sub-folders, each shown by its most typical image")
        if a.granularity == "auto" and a.threshold is None and a.k is None:
            a.threshold = FAMILY_CUT  # the automatic cut lumps folder means into 1-2 groups
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
    qkept, qstyle, qcontent, failed = embed_paths(qpaths, opts, log)
    if not qkept:
        log("no readable query images")
        return 1
    atlas = build_atlas(Path(a.within), opts, log, recursive=not a.no_recursive)
    plain = atlas.style  # near-copies are judged in plain CSD
    space = _space(a)
    if space != PLAIN:
        atlas, fitted = atlas.in_space(space)
        qstyle = fitted.apply(qstyle, qcontent)
    query_files = {q.resolve() for q in qkept}
    same = {i for i, p in enumerate(atlas.paths) if p.resolve() in query_files}
    names = ["(all queries)"] if a.combine else [str(p) for p in qkept]
    if a.by_folder:
        return _search_folders(a, atlas, qstyle, names, same)
    wide = a.top if a.keep_duplicates else 2 * a.top
    results = search(qstyle, atlas.style, top=wide, combine=a.combine, exclude=same)
    if not a.keep_duplicates:
        results = _fold(results, plain, atlas.content, a.top)
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
        _print_by_query(rows, lambda r: f"{r['rank']:3d}  {r['cosine']:.3f}  {r['path']}")
        log(tr(SEARCH_ORDER_EN, SEARCH_ORDER_ZH))
    if a.copy_to:
        _copy_matches(atlas, [h.index for hits in results for h in hits], Path(a.copy_to))
    return 0


def _search_folders(a: argparse.Namespace, atlas, qstyle, names: list[str], same: set) -> int:
    from styleatlas.search import rank_folders

    if a.copy_to:
        log("--copy-to copies single images; it is not used with --by-folder")
    folders = labels_from_folders(atlas.paths, atlas.root)
    if len(set(folders) - {""}) < 2:
        log(f"{a.within} has no sub-folders to rank; --by-folder compares its sub-folders")
        return 1
    results = rank_folders(qstyle, atlas.style, folders, top=a.top, combine=a.combine, exclude=same)
    rows = [
        {
            "query": names[qi],
            "rank": r + 1,
            "folder": h.folder,
            "score": round(h.score, 4),
            "images": h.size,
            "closest": atlas.rel(h.best),
        }
        for qi, hits in enumerate(results)
        for r, h in enumerate(hits)
    ]
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    _print_by_query(
        rows,
        lambda r: (
            f"{r['rank']:3d}  {r['score']:.3f}  {r['folder']} ({r['images']} images,"
            f" closest {r['closest']})"
        ),
    )
    log(
        tr(
            "score: cosine between the query and each folder's mean style, in the search space "
            "(1 = same direction; it reads lower than the image search's numbers)",
            "分數：查詢圖和每個資料夾平均畫風的相似度（在搜尋空間裡；1 表示完全同方向，"
            "數值會比單張搜尋的低，看排名就好）",
        )
    )
    return 0


SEARCH_ORDER_EN = (
    "ranked by style match in the search space (whitened, corrected for images that are close to "
    "everything); the number shown is the plain cosine, so it is not always in order"
)
SEARCH_ORDER_ZH = (
    "名次依畫風相似度排（在搜尋空間裡，並修正了「和什麼都像」的圖）；旁邊的數字是一般的相似度，"
    "所以不一定照大小排"
)


def _print_by_query(rows: list[dict], line: Callable[[dict], str]) -> None:
    """Each query's name once, then its results."""
    query = None
    for row in rows:
        if row["query"] != query:
            query = row["query"]
            print(f"{query}:")
        print(line(row))


def _fold(results: list, plain: np.ndarray, content: np.ndarray, top: int) -> list:
    from styleatlas.search import fold_hits

    shown, folded = [], 0
    for hits in results:
        kept, n = fold_hits(hits, plain, content, top)
        shown.append(kept)
        folded += n
    if folded:
        log(f"{folded} near-copies of a better match left out (--keep-duplicates lists them)")
    return shown


def _copy_matches(atlas, indices: list[int], dest: Path) -> None:
    from styleatlas.export import export_folders

    unique = list(dict.fromkeys(indices))  # several queries may find the same image
    done = export_folders(atlas.subset(unique), ["matches"] * len(unique), dest)
    log(f"copied {done.placed} matches to {done.folder / 'matches'}")
    for p, why in done.failed:
        log(f"not copied {p}: {why}")


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
    from styleatlas.serve import StyleAtlasApp
    from styleatlas.webserver import serve

    space = _space(a)
    a.neutralize, a.ignore_characters = 0, False  # the app applies the space itself
    app = StyleAtlasApp(
        _atlas(a, a.folder),
        _opts(a),
        a.projection,
        a.title,
        progress=log,
        time_source=a.time,
        space=space,
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
    g = _grouping_args(p)
    g.add_argument("--projection", default="auto", choices=PROJECTIONS)
    g.add_argument(
        "--time",
        default="none",
        choices=TIME_SOURCES,
        help="show when each style was made: file-name id (Pixiv/Danbooru) or mtime",
    )
    _space_args(g)
    g.add_argument("--reference", metavar="DIR", help=REFERENCE_HELP)
    g.add_argument("--thumb", type=int, help="thumbnail px in the map (default 128, 72 above 2k)")


def _grouping_args(p: argparse.ArgumentParser) -> argparse._ArgumentGroup:
    g = p.add_argument_group("clustering")
    g.add_argument(
        "--granularity",
        default="auto",
        choices=["auto", "period", ARTISTS, *GRANULARITY],
        help="auto picks the cut from the data; period splits one artist into --k periods "
        f"(default {PERIODS}, k-means, every image assigned); artists follows artists in a "
        "gallery of many (20 or more)",
    )
    g.add_argument(
        "--threshold", type=float, help="hub-corrected distance cut (overrides granularity)"
    )
    g.add_argument("--k", type=int, help="force this many styles (with period: periods)")
    g.add_argument("--method", default="agglomerative", choices=METHODS)
    g.add_argument("--min-size", type=int, default=3, help="smaller groups become 'unassigned'")
    return g


Adder = Callable[..., argparse.ArgumentParser]


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
    p = add("report", cmd_report, "one HTML page that sums up a folder's style (to keep or send)")
    report_args(p)
    _cluster_args(p)
    p = add("sort", cmd_sort, "place new images into the style groups of a sorted dataset")
    sort_args(p)
    _grouping_args(p)
    p = add("map", cmd_map, "write the interactive 3D style map (one HTML file)")
    p.add_argument("folder")
    p.add_argument("-o", "--out")
    p.add_argument("--title")
    p.add_argument(
        "--by-folder",
        action="store_true",
        help="one point per sub-folder (e.g. per artist) at its mean style, grouped into families",
    )
    _cluster_args(p)
    p = add("serve", cmd_serve, "open the interactive map in the browser with live search")
    p.add_argument("folder")
    p.add_argument("--port", type=int, default=8770)
    p.add_argument("--title")
    p.add_argument("--projection", default="auto", choices=PROJECTIONS)
    p.add_argument("--time", default="none", choices=TIME_SOURCES)
    _space_args(p)
    p.add_argument("--reference", metavar="DIR", help=REFERENCE_HELP)
    p.add_argument("--no-browser", action="store_true")


def _space_args(p) -> None:
    x = p.add_mutually_exclusive_group()
    x.add_argument("--ignore-characters", action="store_true", help=CHARACTERS_HELP)
    x.add_argument(
        "--neutralize", type=_neutralize_count, default=0, metavar="N", help=NEUTRALIZE_HELP
    )


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
    p.add_argument(
        "--by-folder",
        action="store_true",
        help="rank the sub-folders of --in (e.g. one per artist) instead of single images",
    )
    p.add_argument(
        "--keep-duplicates",
        action="store_true",
        help="also list near-copies of a better match (left out by default)",
    )
    _space_args(p)
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
    p.add_argument("--json", action="store_true", help="every number, as JSON")
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
    from styleatlas.encoder import ModelDownloadError

    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except (FileNotFoundError, ValueError, ModelDownloadError) as e:
        log(tr("error: ", "錯誤：") + str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
