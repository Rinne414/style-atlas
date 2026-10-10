"""Helpers every command shares: logging, encoder options, embedding a folder in the chosen
vector space, the reference folder, and the grouping options."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from styleatlas.atlas import Atlas, EncodeOptions, build_atlas
from styleatlas.cluster import (
    ARTISTS,
    ARTISTS_CUT,
    GRANULARITY,
    PERIODS,
    Clustering,
    cluster_by_artist,
    cluster_styles,
    edit_groups,
)
from styleatlas.metrics import (
    CHARACTERS,
    MAX_NEUTRALIZE,
    PLAIN,
    SubjectCentring,
)

SOFT_PERIODS = 100  # below this, k-means periods changed with the seed (agreement ARI 0.3-0.7)
NEUTRALIZE_HELP = (
    "ignore the N strongest directions of variation (try 1) when the same characters appear in "
    "many styles (--ignore-characters usually does better); not for a mix of different artists"
)
CHARACTERS_HELP = (
    "when the same characters appear in many styles: find the characters from the picture "
    "content and compare styles as if all were drawn on the same character; not for a mix of "
    "different artists"
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
    space = _space(a)
    if space != PLAIN:
        atlas, a.fitted_space = atlas.in_space(space)  # reused for --reference
        _log_space(a.fitted_space.transform)
    return atlas


def _space(a: argparse.Namespace) -> str:
    """The vector space chosen on the command line (see metrics.StyleSpace)."""
    if getattr(a, "ignore_characters", False):
        return CHARACTERS
    n = getattr(a, "neutralize", 0)
    return f"neutralize-{n}" if n else PLAIN


def _positive_int(text: str) -> int:
    n = int(text)
    if n < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return n


def _neutralize_count(text: str) -> int:
    n = int(text)
    if not 0 <= n <= MAX_NEUTRALIZE:
        raise argparse.ArgumentTypeError(f"takes 0 to {MAX_NEUTRALIZE}")
    return n


def _log_space(transform: object) -> None:
    if isinstance(transform, SubjectCentring):
        n = len(transform.centres)
        if not n:
            log("too few images to find characters: styles are compared as they are")
        else:
            log(f"comparing styles per character: {n} subjects found in the picture content")
    else:
        k = len(getattr(transform, "axes", []))
        log(f"ignoring the {k} strongest direction(s) of variation (subject axis)")


def _reference(a: argparse.Namespace) -> Atlas | None:
    """The --reference folder (styles you already know), embedded the same way."""
    if not getattr(a, "reference", None):
        return None
    ref = build_atlas(Path(a.reference), _opts(a), log, recursive=True)
    for p, why in ref.failed:
        log(f"reference skipped {p}: {why}")
    space = getattr(a, "fitted_space", None)  # same space as the folder
    if space is not None:
        ref = replace(ref, style=space.apply(ref.style, ref.content))
    log(f"reference: {len(ref)} images from {a.reference}")
    return ref


def _cluster(a: argparse.Namespace, atlas: Atlas):
    if a.granularity == ARTISTS:
        return _cluster_by_artist(a, atlas)
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


def saved_groups(
    a: argparse.Namespace, atlas: Atlas, folder: Path
) -> tuple[Clustering, dict[int, str]]:
    """The groups as left in the web app for `folder` (hand edits and names), else a fresh
    grouping."""
    from styleatlas.export import output_dir
    from styleatlas.groupfile import GROUPS_FILE, carry_names, load_groups

    clustering = _cluster(a, atlas)
    saved = load_groups(output_dir(folder) / GROUPS_FILE, atlas)
    if saved is None:
        return clustering, {}
    log("using the groups and names saved by the web app")
    edited = edit_groups(atlas.style, clustering, dict(enumerate(saved.labels.tolist())))
    return edited, carry_names(saved.labels, edited.labels, saved.names)


def _cluster_by_artist(a: argparse.Namespace, atlas: Atlas) -> Clustering:
    if _space(a) != PLAIN or a.threshold is not None or a.k:
        raise ValueError(
            "--granularity artists takes plain style vectors and its own cut: leave out "
            "--neutralize, --ignore-characters, --threshold and --k"
        )
    result = cluster_by_artist(atlas.style, min_size=a.min_size)
    how = f"by artist: whitened, cut {ARTISTS_CUT}"
    log(f"{result.n_clusters} styles, {result.n_unassigned} unassigned ({how})")
    return result


def web_exclusions(atlas: Atlas, folder: Path) -> list[int]:
    """Images excluded by hand (X) in the web app, as indices into `atlas`."""
    from styleatlas.export import output_dir
    from styleatlas.persist import RelPathMap

    marks = RelPathMap(output_dir(folder) / "excluded.json", atlas, read_only=True)
    if marks.unreadable:
        log(f"warning: could not read {marks.path}; the web app's exclusions are NOT applied")
    return sorted(i for i, v in marks.values.items() if v is True)
