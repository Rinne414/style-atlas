"""`style-atlas doctor`: check the setup before a long first run."""

from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path

from styleatlas import __version__
from styleatlas.cachedir import cache_dir
from styleatlas.lang import tr

OK, WARN, FAIL = "ok", "warn", "FAIL"


def _torch_lines() -> list[tuple[str, str, str]]:
    try:
        import torch
    except ImportError:
        return [(FAIL, "torch", "not installed: run scripts\\setup.bat or `pip install torch`")]
    rows = [(OK, "torch", str(torch.__version__))]
    if torch.cuda.is_available():
        rows.append((OK, "GPU", torch.cuda.get_device_name(0)))
    else:
        cuda_build = torch.version.cuda is not None
        hint = "CUDA build but no GPU found" if cuda_build else "CPU-only torch build"
        rows.append((WARN, "GPU", f"none ({hint}); embedding runs on CPU, about 4 images/s"))
    return rows


def _model_lines() -> list[tuple[str, str, str]]:
    from styleatlas.encoder import CSD_REVISION, MODEL_GB, NEED_GB

    root = cache_dir()
    slim = root / f"csd_vit_l_{CSD_REVISION[:8]}.safetensors"
    rows = [(OK, "cache", str(root))]
    if slim.exists():
        rows.append((OK, "CSD model", f"ready ({slim.stat().st_size / 1e9:.1f} GB)"))
    else:
        rows.append(
            (WARN, "CSD model", f"not downloaded yet: the first run downloads {MODEL_GB} GB")
        )
    rows += _cache_lines(root)
    free_gb = shutil.disk_usage(root).free / 1e9
    need = 0.5 if slim.exists() else NEED_GB
    rows.append(
        (OK if free_gb > need else FAIL, "free disk", f"{free_gb:.1f} GB (need ~{need:.1f} GB)")
    )
    old = _old_checkpoint()
    if slim.exists() and old is not None:
        rows.append(
            (
                WARN,
                "old download",
                f"{old} ({_size(old.rglob('*')) / 1e9:.1f} GB): style-atlas only uses its 1.2 GB "
                "copy now; delete this folder to free the space if nothing else uses it",
            )
        )
    return rows


def _old_checkpoint() -> Path | None:
    """The CSD checkpoint left in the default Hugging Face cache by versions before 0.44."""
    try:
        from huggingface_hub import constants
    except ImportError:
        return None
    folder = Path(constants.HF_HUB_CACHE) / "models--tomg-group-umd--CSD-ViT-L"
    return folder if folder.exists() else None


def _cache_lines(root: Path) -> list[tuple[str, str, str]]:
    """How big the caches have grown: vectors are kept (they take minutes to recompute), the
    thumbnails can be deleted at any time (they are remade when a page asks for them)."""
    rows = []
    vectors = _size(root.glob("vectors.sqlite*"))
    if vectors:
        rows.append((OK, "vector cache", f"{vectors / 1e6:.0f} MB ({root / 'vectors.sqlite'})"))
    thumbs = root / "thumbs"
    if thumbs.is_dir():
        size = _size(thumbs.rglob("*"))
        rows.append((OK, "thumbnails", f"{size / 1e6:.0f} MB; {thumbs} can be deleted any time"))
    return rows


def _size(files) -> int:
    """Total bytes; a file removed meanwhile (e.g. by a running web app) is skipped."""
    total = 0
    for f in files:
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            continue
    return total


def checks() -> list[tuple[str, str, str]]:
    py_ok = sys.version_info >= (3, 10)
    rows = [
        (OK, "style-atlas", __version__),
        (OK if py_ok else FAIL, "python", f"{platform.python_version()} ({sys.executable})"),
    ]
    rows += _torch_lines()
    for name in ("open_clip", "sklearn", "scipy", "huggingface_hub", "safetensors", "PIL"):
        try:
            module = __import__(name)
            rows.append((OK, name, getattr(module, "__version__", "installed")))
        except ImportError:
            rows.append((FAIL, name, "missing: reinstall with `pip install -e .`"))
    try:
        import umap  # noqa: F401

        rows.append((OK, "umap", "installed (UMAP map layouts)"))
    except ImportError:
        rows.append((OK, "umap", "not installed (t-SNE layouts are used; optional)"))
    return rows + [_whitening_line()] + _model_lines()


def _whitening_line() -> tuple[str, str, str]:
    """The search whitening ships inside the package; a broken install loses it."""
    try:
        from styleatlas.whiten import _params

        _params()
        return (OK, "search data", "whitening map loaded")
    except (OSError, KeyError, ValueError) as e:
        return (FAIL, "search data", f"cannot load the whitening map ({e}): reinstall")


def run() -> int:
    rows = checks()
    for status, name, detail in rows:
        print(f"[{status:4s}] {name:16s} {detail}")
    failed = [r for r in rows if r[0] == FAIL]
    if failed:
        print(tr(f"{len(failed)} problem(s) above", f"上面有 {len(failed)} 個問題（標示 FAIL）"))
    else:
        print(tr("all good", "一切正常，可以開始用了"))
    return 1 if failed else 0
