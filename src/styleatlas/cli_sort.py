"""The sort command: place new images into the style groups of a dataset that is already sorted,
e.g. a LoRA training set that grows (see cluster.fit_to_groups).

Images are placed in the search whitening's space. On artists it never saw, with 10 artists'
sub-folders as the groups, it picked the right folder for 91.5% of their new works (plain CSD
85.7%) and let 6% of other artists' works fit (plain 47%); docs/BENCHMARKS.md, "Sorting new
images into a dataset"."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import numpy as np

from styleatlas.atlas import Atlas
from styleatlas.cli_common import _atlas, log, saved_groups, web_exclusions
from styleatlas.cluster import UNASSIGNED, Clustering, Fit, fit_to_groups, from_labels
from styleatlas.dataset import group_labels
from styleatlas.duplicates import copies_of
from styleatlas.export import export_folders, output_dir, write_csv
from styleatlas.images import labels_from_folders
from styleatlas.whiten import whiten

UNSURE = "_unsure"  # closest group, but less alike than 90% of that group's own images
ALREADY = "_already_in_dataset"  # a near-copy of an image the dataset already holds
MOSTLY_IN, MOSTLY_OUT = 0.5, 0.25  # share of a batch that fits (docs/BENCHMARKS.md)


def cmd_sort(a: argparse.Namespace) -> int:
    out = Path(a.out) if a.out else output_dir(Path(a.folder))
    dataset = _atlas(a, a.into)
    new = _atlas(a, a.folder, exclude=[out])
    if len(new) == 0:
        log(f"no readable images in {a.folder}")
        return 1
    clustering, labels = _dataset_groups(a, dataset)
    skip = set(web_exclusions(dataset, Path(a.into)))
    fits = fit_to_groups(
        whiten(dataset.style, keep=False), clustering, whiten(new.style, keep=False), skip
    )
    if not fits:
        log(f"{a.into} has no style group of 2 or more images to sort into")
        return 1
    copies = {
        row: base
        for row, base, _ in copies_of(new.style, new.content, dataset.style, dataset.content)
    }
    folders = [_destination(i, f, labels, copies) for i, f in enumerate(fits)]
    table = write_csv(out / "sorted.csv", _rows(new, dataset, fits, labels, copies, folders))
    _summary(fits, labels, folders)
    if a.export:
        done = export_folders(new, folders, out / "sorted", mode=a.export)
        log(f"{done.placed} images placed in {done.folder}")
        for p, why in done.failed:
            log(f"not placed {p}: {why}")
    print(table)
    return 0


def _dataset_groups(a: argparse.Namespace, dataset: Atlas) -> tuple[Clustering, dict[int, str]]:
    """The groups to sort into with their folder labels: the dataset's sub-folders (--by-folder,
    leaving out set-aside ones such as _excluded), else its style groups as `cluster` and the web
    app make them."""
    if not a.by_folder:
        clustering, names = saved_groups(a, dataset, Path(a.into))
        return clustering, group_labels(clustering, "plain", names)
    names = labels_from_folders(dataset.paths, dataset.root)
    kept = sorted({n for n in names if n and not n.startswith("_")})
    if not kept:
        raise ValueError(f"{a.into} has no sub-folders to sort into")
    index = {n: k for k, n in enumerate(kept)}
    clustering = from_labels(
        dataset.style, np.array([index.get(n, UNASSIGNED) for n in names]), "folders"
    )
    return clustering, {c.id: names[c.members[0]] for c in clustering.clusters}


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
            "fits": "yes" if f.fits else "no",
            "copy_of": dataset.rel(copies[i]) if i in copies else "",
        }
        for i, f in enumerate(fits)
    ]


def _summary(fits: list[Fit], labels: dict[int, str], folders: list[str]) -> None:
    placed = Counter(labels[f.group] for f in fits)
    fitting = Counter(
        labels[f.group] for f, d in zip(fits, folders, strict=True) if d not in (UNSURE, ALREADY)
    )
    log(f"{len(fits)} new images, closest group of each:")
    for name, n in sorted(placed.items(), key=lambda t: -t[1]):
        log(f"  {name:30s} {n:5d}  ({fitting[name]} fit)")
    already = folders.count(ALREADY)
    if already:
        log(f"{already} are near-copies of images the dataset already holds ({ALREADY})")
    if already == len(fits):
        return
    share = sum(fitting.values()) / (len(fits) - already)
    if share > MOSTLY_IN:
        verdict = "mostly the dataset's styles"
    elif share <= MOSTLY_OUT:
        verdict = "mostly unlike the dataset's styles"
    else:
        verdict = "partly the dataset's styles"
    log(f"{share:.0%} fit their group: {verdict}; the rest go to {UNSURE} for a look")


def sort_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("folder", help="the new images")
    p.add_argument("--into", required=True, metavar="DATASET", help="the dataset already sorted")
    p.add_argument("-o", "--out", help="output folder (default: <folder>_style_atlas)")
    p.add_argument(
        "--by-folder",
        action="store_true",
        help="the dataset's sub-folders are the groups (e.g. an exported kohya dataset)",
    )
    p.add_argument(
        "--export",
        choices=["copy", "link"],
        help="also place the new images (with captions) into <out>/sorted/<group>",
    )
