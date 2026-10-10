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
from styleatlas.cli_common import _atlas, log, saved_groups, web_exclusions
from styleatlas.cluster import UNASSIGNED, Clustering, Fit, fit_to_groups, from_labels
from styleatlas.dataset import auto_repeats, group_labels, is_unassigned
from styleatlas.duplicates import copies_of
from styleatlas.export import export_folders, output_dir, write_csv
from styleatlas.images import labels_from_folders
from styleatlas.whiten import whiten

UNSURE = "_unsure"  # closest group, but farther from it than 70% of its own images
ALREADY = "_already_in_dataset"  # a near-copy of an image the dataset already holds
RESERVED = {UNSURE.casefold(), ALREADY.casefold()}
MOSTLY_IN, MOSTLY_OUT = 0.5, 0.25  # share of a batch that fits (docs/BENCHMARKS.md)
MIN_BATCH = 8  # below this many new images the share says little: no verdict on the batch
KOHYA_FOLDER = re.compile(r"^(\d+)_(.+)$")  # <repeats>_<name>, as `cluster --layout kohya` writes


def cmd_sort(a: argparse.Namespace) -> int:
    new_root, data_root = Path(a.folder).resolve(), Path(a.into).resolve()
    if new_root == data_root:
        raise ValueError("the new images and the dataset are the same folder")
    out = Path(a.out) if a.out else output_dir(Path(a.folder))
    if any(root.is_relative_to(out.resolve()) for root in (new_root, data_root)):
        raise ValueError("the output folder must not hold the new images or the dataset")
    # neither side reads the other when one folder holds the other, nor earlier results
    dataset = _atlas(a, a.into, exclude=[out, *_nested(new_root, data_root)])
    new = _atlas(a, a.folder, exclude=[out, *_nested(data_root, new_root)])
    if len(new) == 0:
        log(f"no readable images in {a.folder}")
        return 1
    clustering, labels = _dataset_groups(a, dataset)
    skip = set(web_exclusions(dataset, Path(a.into)))
    _note_small_groups(clustering, labels, skip)
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
    if a.by_folder:
        _repeats_notes(clustering, labels, folders)
    if a.export:
        done = export_folders(new, folders, out / "sorted", mode=a.export)
        log(f"{done.placed} images placed in {done.folder}")
        for p, why in done.failed:
            log(f"not placed {p}: {why}")
    print(table)
    return 0


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
        raise ValueError(f"{a.into} has no sub-folders to sort into")
    index = {n: k for k, n in enumerate(kept)}
    clustering = from_labels(
        dataset.style, np.array([index.get(n, UNASSIGNED) for n in names]), "folders"
    )
    return clustering, {c.id: names[c.members[0]] for c in clustering.clusters}


def _unreserved(labels: dict[int, str]) -> dict[int, str]:
    """A group named like a set-aside folder must not end up in it."""
    return {g: f"{n}_group" if n.casefold() in RESERVED else n for g, n in labels.items()}


def _note_small_groups(clustering: Clustering, labels: dict[int, str], skip: set[int]) -> None:
    small = [labels[c.id] for c in clustering.clusters if sum(m not in skip for m in c.members) < 2]
    if small:
        log(f"too few images (under 2) to sort into: {', '.join(small)}")


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
        log(
            f"{len(fits) - len(rest)} of {len(fits)} new images are near-copies of images the "
            f"dataset already holds ({ALREADY})"
        )
    if not rest:
        return
    placed = Counter(labels[f.group] for f, _ in rest)
    fitting = Counter(labels[f.group] for f, d in rest if d != UNSURE)
    log(f"{len(rest)} new images, closest group of each:")
    for name, n in sorted(placed.items(), key=lambda t: -t[1]):
        log(f"  {name:30s} {n:5d}  ({fitting[name]} fit)")
    share = sum(fitting.values()) / len(rest)
    if len(rest) < MIN_BATCH:
        verdict = f"too few images to judge the batch (under {MIN_BATCH})"
    elif share > MOSTLY_IN:
        verdict = "mostly the dataset's styles"
    elif share <= MOSTLY_OUT:
        verdict = "mostly unlike the dataset's styles"
    else:
        verdict = "partly the dataset's styles"
    log(f"{share:.0%} fit their group: {verdict}; the rest go to {UNSURE} for a look")


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
                f"{name}: {c.size} + {added[name]} images; rename it {new}_{match[2]} to keep "
                "images x repeats near 100 (the trainer config files list the old repeats)"
            )


def sort_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("folder", help="the new images")
    p.add_argument("--into", required=True, metavar="DATASET", help="the dataset already sorted")
    p.add_argument("-o", "--out", help="output folder (default: <folder>_style_atlas)")
    p.add_argument(
        "--fresh",
        action="store_true",
        help="group afresh instead of using the groups the web app saved",
    )
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
