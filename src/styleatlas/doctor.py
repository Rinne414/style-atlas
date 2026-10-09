"""`style-atlas doctor`: check the setup before a long first run."""

from __future__ import annotations

import platform
import shutil
import sys

from styleatlas import __version__
from styleatlas.cachedir import cache_dir

MODEL_GB = 2.4  # first download; a 1.2 GB slim copy is kept afterwards
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
    from styleatlas.encoder import CSD_REVISION

    root = cache_dir()
    slim = root / f"csd_vit_l_{CSD_REVISION[:8]}.safetensors"
    rows = [(OK, "cache", str(root))]
    if slim.exists():
        rows.append((OK, "CSD model", f"ready ({slim.stat().st_size / 1e9:.1f} GB)"))
    else:
        rows.append(
            (WARN, "CSD model", f"not downloaded yet: the first run downloads {MODEL_GB} GB")
        )
    free_gb = shutil.disk_usage(root).free / 1e9
    need = 0.5 if slim.exists() else MODEL_GB + 1.5
    rows.append(
        (OK if free_gb > need else FAIL, "free disk", f"{free_gb:.1f} GB (need ~{need:.1f} GB)")
    )
    return rows


def checks() -> list[tuple[str, str, str]]:
    py_ok = sys.version_info >= (3, 10)
    rows = [
        (OK, "style-atlas", __version__),
        (OK if py_ok else FAIL, "python", f"{platform.python_version()} ({sys.executable})"),
    ]
    rows += _torch_lines()
    for name in ("open_clip", "sklearn", "huggingface_hub", "safetensors", "PIL"):
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
    return rows + _model_lines()


def run() -> int:
    rows = checks()
    for status, name, detail in rows:
        print(f"[{status:4s}] {name:16s} {detail}")
    failed = [r for r in rows if r[0] == FAIL]
    print("all good" if not failed else f"{len(failed)} problem(s) above")
    return 1 if failed else 0
