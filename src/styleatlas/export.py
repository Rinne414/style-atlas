"""Write cluster results: a CSV/JSON table and, optionally, one folder per style.

Folder export copies (or hard-links) each image with its caption sidecars (.txt, .caption, .json
with the same stem), so a LoRA dataset can be split by style without losing captions. Source files
are never moved or deleted, and an export never writes into a folder that already has files: a
fresh `folders_2`, `folders_3`, ... is used instead, so groups from different runs never mix.

Hard links share the file with the original: editing a linked caption edits the source caption.
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from styleatlas.atlas import Atlas
from styleatlas.cluster import Clustering
from styleatlas.dataset import plan_folders
from styleatlas.look import LOOK_NAMES, describe, profile
from styleatlas.report import cluster_table

SIDECARS = (".txt", ".caption", ".json")
EXPORT_MODES = ("copy", "link")
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


@dataclass
class ExportResult:
    folder: Path
    placed: int = 0
    failed: list[tuple[Path, str]] = field(default_factory=list)


def output_dir(source: Path) -> Path:
    """Default place for results: a sibling of the scanned folder, so the dataset folder itself
    is never written to (kohya and other trainers will not pick up stray copies)."""
    source = Path(source).resolve()
    return source.parent / f"{source.name}_style_atlas"


def _safe_cell(value: object) -> object:
    """Spreadsheet apps run cells starting with = + - @ as formulas; neutralise file names."""
    if isinstance(value, str) and value.startswith(FORMULA_START):
        return "'" + value
    return value


def _write_atomic(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Bytes are written as given: no newline translation (csv already ends rows with CRLF)."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(text.encode(encoding))
    os.replace(tmp, path)


def write_table(
    atlas: Atlas,
    clustering: Clustering,
    out_dir: Path,
    folders: list[str] | None = None,
    tags: dict[int, list[dict]] | None = None,
) -> tuple[Path, Path]:
    """clusters.csv (one row per image) and clusters.json (one entry per style group)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = cluster_table(atlas, clustering)
    folders = folders or plan_folders(atlas.paths, clustering)
    for r, f in zip(rows, folders, strict=True):
        r["folder"] = f
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else ["path"])
    w.writeheader()
    w.writerows({k: _safe_cell(v) for k, v in r.items()} for r in rows)
    csv_path = out_dir / "clusters.csv"
    _write_atomic(csv_path, buf.getvalue(), encoding="utf-8-sig")
    summary = {
        "images": len(atlas),
        "method": clustering.method,
        "params": clustering.params,
        "signature": atlas.signature,
        "unassigned": clustering.n_unassigned,
        "clusters": [
            {
                "folder": next(
                    (folders[m] for m in c.members if not folders[m].startswith("_")),
                    folders[c.medoid],
                ),
                "size": c.size,
                "cohesion": round(c.cohesion, 4),
                "representative": atlas.rel(c.medoid),
                "top_tags": (tags or {}).get(c.id, []),
                **_look_summary(atlas, c.members),
            }
            for c in clustering.clusters
        ],
    }
    json_path = out_dir / "clusters.json"
    _write_atomic(json_path, json.dumps(summary, ensure_ascii=False, indent=1))
    return csv_path, json_path


def _look_summary(atlas: Atlas, members: list[int]) -> dict:
    """The group's look against the whole folder (look.py), when it was measured."""
    if atlas.looks is None:
        return {}
    z = profile(atlas.looks, members)
    return {
        "look": dict(zip(LOOK_NAMES, (round(float(v), 2) for v in z), strict=True)),
        "look_words": describe(z) or "average",
    }


def fresh_dir(base: Path) -> Path:
    """`base` if it is missing or empty, else the first free base_2, base_3, ..."""
    candidate, n = base, 2
    while candidate.exists() and any(candidate.iterdir()):
        candidate = base.with_name(f"{base.name}_{n}")
        n += 1
    return candidate


def _place(src: Path, dst: Path, mode: str) -> None:
    if dst.exists():
        raise FileExistsError(f"{dst} already exists")
    if mode == "link":
        try:
            os.link(src, dst)
            return
        except OSError:
            pass  # other drive or no hard-link support: fall back to a copy
    shutil.copy2(src, dst)


def trigger_of(folder: str, layout: str = "plain") -> str | None:
    """Trigger word for a group folder: the folder name, without the repeat count in the kohya
    layout ("11_artistX_style01" -> "artistX_style01"); None for set-aside folders."""
    if folder.startswith("_") or folder == "unassigned":
        return None
    if layout == "kohya":
        return folder.partition("_")[2] or folder
    return folder


def norm_tag(tag: str) -> str:
    """Tags compare without case, and with spaces and underscores alike."""
    return " ".join(tag.lower().replace("_", " ").split())


def parse_tags(text: str) -> frozenset[str]:
    """A comma-separated tag list ("sketch, monochrome") as normalised tags."""
    return frozenset(t for t in (norm_tag(part) for part in text.split(",")) if t)


def _write_caption(
    side: Path | None, dst: Path, trigger: str | None, strip: frozenset[str] = frozenset()
) -> None:
    """New caption in the export (never a link, so the source caption is never touched): the
    tags in `strip` removed, then the trigger first. Images without a caption get the trigger
    alone."""
    if dst.exists():
        raise FileExistsError(f"{dst} already exists")
    text = ""
    if side is not None:
        try:
            text = side.read_text(encoding="utf-8-sig").strip()
        except UnicodeDecodeError:  # not UTF-8 (e.g. Big5 / GBK): keep it byte-for-byte
            shutil.copy2(side, dst)
            return
    if strip:
        kept = (part.strip() for part in text.split(","))
        text = ", ".join(part for part in kept if part and norm_tag(part) not in strip)
    if not trigger or text == trigger or text.startswith(trigger + ","):
        new = text  # no trigger, or already tagged (re-export)
    else:
        new = f"{trigger}, {text}" if text else trigger
    dst.write_text(new, encoding="utf-8")


def _place_sidecars(
    src: Path,
    folder: Path,
    stem: str,
    mode: str,
    trigger: str | None,
    strip: frozenset[str] = frozenset(),
) -> list[Path]:
    """Place the sidecars of one image; returns the files written. Captions are written anew
    when a trigger is added or tags are removed."""
    written = []
    captions = [e for e in (".txt", ".caption") if src.with_suffix(e).exists()]
    rewrite = bool(trigger or strip)
    for ext in SIDECARS:
        side = src.with_suffix(ext)
        if not side.exists() or (rewrite and ext in captions):
            continue
        _place(side, folder / f"{stem}{ext}", mode)
        written.append(folder / f"{stem}{ext}")
    if rewrite:
        targets = captions or ([".txt"] if trigger else [])  # a new caption only for a trigger
        for ext in targets:
            side = src.with_suffix(ext) if ext in captions else None
            _write_caption(side, folder / f"{stem}{ext}", trigger, strip)
            written.append(folder / f"{stem}{ext}")
    return written


def export_folders(
    atlas: Atlas,
    folders: list[str],
    out_dir: Path,
    mode: str = "copy",
    trigger_captions: bool = False,
    layout: str = "plain",
    strip_tags: frozenset[str] = frozenset(),
) -> ExportResult:
    """Copy or hard-link each image (and its sidecars) into its planned folder (see
    dataset.plan_folders) inside a fresh output folder. With trigger_captions, every exported
    caption in a group folder starts with that group's trigger word."""
    if mode not in EXPORT_MODES:
        raise ValueError(f"mode must be one of {EXPORT_MODES}")
    if len(folders) != len(atlas):
        raise ValueError("one destination folder per image is required")
    result = ExportResult(fresh_dir(Path(out_dir)))
    used: dict[Path, set[str]] = {}
    root = result.folder.resolve()
    inside: dict[str, bool] = {}
    for i, src in enumerate(atlas.paths):
        folder = result.folder / folders[i]
        if folders[i] not in inside:  # a folder name must not lead out of the export
            inside[folders[i]] = folder.resolve().is_relative_to(root) and folder != result.folder
        if not inside[folders[i]]:
            result.failed.append((src, f"folder name {folders[i]!r} points outside the export"))
            continue
        stem = _unique_stem(src.stem, used.setdefault(folder, set()))
        try:
            folder.mkdir(parents=True, exist_ok=True)
            trigger = trigger_of(folders[i], layout) if trigger_captions else None
            _place_sidecars(src, folder, stem, mode, trigger, strip_tags)
            _place(src, folder / f"{stem}{src.suffix}", mode)
        except OSError as e:  # long path, permissions, full disk: report and keep going
            result.failed.append((src, str(e)))
            for ext in (*SIDECARS, src.suffix):  # fresh folder + unique stem: only our files
                with contextlib.suppress(OSError):
                    (folder / f"{stem}{ext}").unlink(missing_ok=True)
            continue
        result.placed += 1
    if layout == "kohya":
        write_trainer_configs(result.folder, folders, trigger_captions)
    return result


KOHYA_CONFIG = "dataset_config.toml"
DIFFUSION_PIPE_CONFIG = "diffusion_pipe_dataset.toml"
ONETRAINER_CONCEPTS = "onetrainer_concepts.json"


def _style_folders(root: Path, folders: list[str]) -> list[tuple[str, Path, int]]:
    """(name, absolute path, repeats) of every `N_name` style folder; set-aside folders
    (`_duplicates` and the like) are left out."""
    out = []
    for name in sorted(set(folders)):
        head, _, rest = name.partition("_")
        if name.startswith("_") or not head.isdigit() or not rest:
            continue
        out.append((name, (root / name).resolve(), int(head)))
    return out


def _toml_string(path: Path) -> str:
    return json.dumps(str(path), ensure_ascii=False)  # a valid TOML basic string


def write_trainer_configs(root: Path, folders: list[str], trigger: bool = False) -> list[Path]:
    """Dataset configs for kohya sd-scripts, diffusion-pipe and OneTrainer, each listing every
    style folder with its repeats. Resolution and batch size are starting points."""
    styles = _style_folders(root, folders)
    if not styles:
        return []
    return [
        _write_kohya(root, styles, trigger),
        _write_diffusion_pipe(root, styles),
        _write_onetrainer(root, styles, trigger),
    ]


def _write_kohya(root: Path, styles: list[tuple[str, Path, int]], trigger: bool) -> Path:
    lines = [
        "# Written by style-atlas. Use it with --dataset_config. Set resolution and batch_size",
        "# for your model (1024 for SDXL / Illustrious / Anima, 512 for SD 1.5).",
        "[general]",
        "shuffle_caption = true",
        'caption_extension = ".txt"',
        f"keep_tokens = {1 if trigger else 0}  # 1 keeps the trigger word first when shuffling",
        "",
        "[[datasets]]",
        "resolution = 1024",
        "batch_size = 1",
        "enable_bucket = true",
        "",
    ]
    lines += [
        f"  [[datasets.subsets]]\n  image_dir = {_toml_string(path)}\n  num_repeats = {repeats}\n"
        for _, path, repeats in styles
    ]
    path = root / KOHYA_CONFIG
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_diffusion_pipe(root: Path, styles: list[tuple[str, Path, int]]) -> Path:
    """diffusion-pipe's dataset file (the `dataset = ...` entry of its training config)."""
    lines = [
        "# Written by style-atlas for diffusion-pipe: the training config's `dataset` file.",
        "# Paths are as this computer sees them; under WSL, D:\\ becomes /mnt/d/.",
        "# Set resolutions for your model (1024 for Anima / SDXL-class models).",
        "resolutions = [1024]",
        "enable_ar_bucket = true",
        "min_ar = 0.5",
        "max_ar = 2.0",
        "num_ar_buckets = 7",
        "",
    ]
    lines += [
        f"[[directory]]\npath = {_toml_string(path)}\nnum_repeats = {repeats}\n"
        for _, path, repeats in styles
    ]
    path = root / DIFFUSION_PIPE_CONFIG
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_onetrainer(root: Path, styles: list[tuple[str, Path, int]], trigger: bool) -> Path:
    """OneTrainer concepts (copy into its training_concepts folder). Keys left out keep its
    defaults; captions come from the .txt next to each image."""
    concepts = [
        {
            "__version": 2,
            "name": name,
            "path": str(path),
            "enabled": True,
            "balancing": float(repeats),
            "balancing_strategy": "REPEATS",
            "text": {
                "prompt_source": "sample",
                "enable_tag_shuffling": True,
                "tag_delimiter": ",",
                "keep_tags_count": 1 if trigger else 0,
            },
        }
        for name, path, repeats in styles
    ]
    path = root / ONETRAINER_CONCEPTS
    path.write_text(json.dumps(concepts, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _unique_stem(stem: str, taken: set[str]) -> str:
    """Same file name from two sub-folders must not collide inside one style folder."""
    name, n = stem, 2
    while name.lower() in taken:
        name = f"{stem}_{n}"
        n += 1
    taken.add(name.lower())
    return name
