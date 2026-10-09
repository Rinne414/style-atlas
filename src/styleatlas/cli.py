"""Command line: style-atlas <command> ...  (run `style-atlas <command> -h` for options)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from styleatlas import __version__
from styleatlas.atlas import Atlas, EncodeOptions, build_atlas, embed_paths
from styleatlas.cluster import GRANULARITY, METHODS, cluster_styles, outlier_scores
from styleatlas.encoder import CROP_MODES
from styleatlas.images import find_images, labels_from_folders
from styleatlas.metrics import StyleScale, group_difference, split_half_noise
from styleatlas.project import PROJECTIONS


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _opts(a: argparse.Namespace) -> EncodeOptions:
    from styleatlas.safety import limit_resources

    limit_resources(a.threads)
    return EncodeOptions(
        device=a.device,
        crop=a.crop,
        batch_size=a.batch,
        db_path=Path(a.cache_db) if a.cache_db else None,
    )


def _atlas(a: argparse.Namespace, folder: str) -> Atlas:
    atlas = build_atlas(Path(folder), _opts(a), log, recursive=not a.no_recursive)
    for p, why in atlas.failed:
        log(f"skipped {p}: {why}")
    return atlas


def _cluster(a: argparse.Namespace, atlas: Atlas):
    threshold = a.threshold if a.threshold is not None else GRANULARITY[a.granularity]
    result = cluster_styles(
        atlas.style, method=a.method, threshold=threshold, n_clusters=a.k, min_size=a.min_size
    )
    log(
        f"{result.n_clusters} styles, {result.n_unassigned} unassigned "
        f"({result.method}, {result.params})"
    )
    return result


def cmd_embed(a: argparse.Namespace) -> int:
    atlas = _atlas(a, a.folder)
    log(f"{len(atlas)} images embedded, {len(atlas.failed)} skipped")
    return 0


def cmd_cluster(a: argparse.Namespace) -> int:
    from styleatlas.export import export_folders, write_table
    from styleatlas.report import write_map

    atlas = _atlas(a, a.folder)
    result = _cluster(a, atlas)
    out = Path(a.out or Path(a.folder) / "style_atlas_out")
    csv_path, json_path = write_table(atlas, result, out)
    log(f"wrote {csv_path} and {json_path}")
    if a.export:
        placed = export_folders(atlas, result, out / "folders", mode=a.export)
        log(f"{a.export}: {placed} images into {out / 'folders'}")
    if not a.no_map:
        path = write_map(atlas, result, out / "map.html", a.projection, a.thumb, progress=log)
        log(f"map: {path}")
    return 0


def cmd_map(a: argparse.Namespace) -> int:
    from styleatlas.report import write_map

    atlas = _atlas(a, a.folder)
    result = _cluster(a, atlas)
    out = Path(a.out or Path(a.folder) / "style_atlas_map.html")
    path = write_map(atlas, result, out, a.projection, a.thumb, a.title, progress=log)
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
    same = {i for i, p in enumerate(atlas.paths) if p.resolve() in {q.resolve() for q in qkept}}
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
    return 0


def cmd_outliers(a: argparse.Namespace) -> int:
    atlas = _atlas(a, a.folder)
    scores = outlier_scores(atlas.style)
    for i in np.argsort(-scores)[: a.top]:
        print(f"{scores[i]:.3f}  {atlas.rel(int(i))}")
    return 0


def cmd_compare(a: argparse.Namespace) -> int:
    opts = _opts(a)
    groups = []
    for folder in (a.a, a.b):
        kept, style, _, _ = embed_paths(find_images(Path(folder)), opts, log)
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

    if a.npz:
        with np.load(a.npz) as z:
            keys = list(z.files)
            style = np.stack([z[k] for k in keys]).astype(np.float32)
        style /= np.linalg.norm(style, axis=1, keepdims=True)
        labels = [k.rsplit(a.sep, 1)[0] for k in keys]
    else:
        root = Path(a.folder)
        kept, style, _, _ = embed_paths(find_images(root), _opts(a), log)
        labels = labels_from_folders(kept, root)
    print(json.dumps(run_bench(style, labels, trials=a.trials), indent=1))
    return 0


def cmd_taste(a: argparse.Namespace) -> int:
    from styleatlas.taste import TasteModel, train_taste

    opts = _opts(a)
    if a.taste_cmd == "train":
        like = embed_paths(find_images(Path(a.like)), opts, log)[1]
        dislike = embed_paths(find_images(Path(a.dislike)), opts, log)[1]
        from styleatlas.encoder import encoder_signature

        model = train_taste(like, dislike, encoder_signature(opts.crop))
        model.save(Path(a.model))
        log(
            f"saved {a.model}: {model.n_like} liked / {model.n_dislike} disliked, "
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


def _common(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("embedding")
    g.add_argument("--device", default="auto", help="auto, cpu or cuda (default auto)")
    g.add_argument("--crop", default="center", choices=CROP_MODES)
    g.add_argument("--batch", type=int, default=8)
    g.add_argument("--threads", type=int, default=8, help="CPU threads cap (0 = all)")
    g.add_argument(
        "--cache-db", help="vector cache file (default ~/.cache/style-atlas/vectors.sqlite)"
    )
    g.add_argument("--no-recursive", action="store_true", help="do not look into sub-folders")


def _cluster_args(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("clustering")
    g.add_argument("--granularity", default="medium", choices=list(GRANULARITY))
    g.add_argument(
        "--threshold", type=float, help="hub-corrected distance cut (overrides granularity)"
    )
    g.add_argument("--k", type=int, help="force this many styles")
    g.add_argument("--method", default="agglomerative", choices=METHODS)
    g.add_argument("--min-size", type=int, default=3, help="smaller groups become 'unassigned'")
    g.add_argument("--projection", default="auto", choices=PROJECTIONS)
    g.add_argument("--thumb", type=int, help="thumbnail px in the map (default 128, 72 above 2k)")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="style-atlas", description=__doc__)
    ap.add_argument("--version", action="version", version=f"style-atlas {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name: str, fn, help_: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_, description=help_)
        p.set_defaults(fn=fn)
        _common(p)
        return p

    add("embed", cmd_embed, "embed and cache a folder").add_argument("folder")
    p = add(
        "cluster", cmd_cluster, "group a folder by style; write CSV/JSON, map, optional folders"
    )
    p.add_argument("folder")
    p.add_argument("-o", "--out")
    p.add_argument(
        "--export", choices=["copy", "link"], help="also place images into style folders"
    )
    p.add_argument("--no-map", action="store_true")
    _cluster_args(p)
    p = add("map", cmd_map, "write the interactive 3D style map (one HTML file)")
    p.add_argument("folder")
    p.add_argument("-o", "--out")
    p.add_argument("--title")
    _cluster_args(p)
    p = add("search", cmd_search, "find images in a folder whose style is closest to the query")
    p.add_argument("query", nargs="+", help="query image(s) or folder(s)")
    p.add_argument("--in", dest="within", required=True, help="folder to search")
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--combine", action="store_true", help="treat all queries as one style")
    p.add_argument("--json", action="store_true")
    p = add("outliers", cmd_outliers, "images least like the rest of a folder")
    p.add_argument("folder")
    p.add_argument("--top", type=int, default=30)
    p = add("compare", cmd_compare, "do two folders differ in style? distance, z units, p-value")
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--rounds", type=int, default=999)
    p.add_argument("--noise-floor", type=float, help="from `calibrate` (default 0.071)")
    p = add(
        "calibrate", cmd_calibrate, "estimate the noise floor from sub-folders of one style each"
    )
    p.add_argument("folder")
    p = add("bench", cmd_bench, "score retrieval and clustering against sub-folder labels")
    p.add_argument("folder", nargs="?")
    p.add_argument("--npz", help="precomputed vectors; label = key prefix before --sep")
    p.add_argument("--sep", default="__")
    p.add_argument("--trials", type=int, default=30)
    p = add("taste", cmd_taste, "train or apply a personal like/dislike model")
    tsub = p.add_subparsers(dest="taste_cmd", required=True)
    t1 = tsub.add_parser("train")
    t1.add_argument("--like", required=True)
    t1.add_argument("--dislike", required=True)
    t1.add_argument("--model", default="taste_model.npz")
    t2 = tsub.add_parser("score")
    t2.add_argument("folder")
    t2.add_argument("--model", default="taste_model.npz")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
