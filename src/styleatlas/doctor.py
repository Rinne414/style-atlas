"""`style-atlas doctor`: check the setup before a long first run."""

from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path

from styleatlas import __version__
from styleatlas.cachedir import cache_dir
from styleatlas.lang import pad, tr

OK, WARN, FAIL = "ok", "warn", "FAIL"
CUDA_INDEX = "https://download.pytorch.org/whl/cu128"  # as scripts/setup.bat installs it


def _torch_lines() -> list[tuple[str, str, str]]:
    try:
        import torch
    except ImportError:
        return [
            (
                FAIL,
                "torch",
                tr(
                    "not installed: run scripts\\setup.bat or `pip install torch`",
                    "沒有安裝：請執行 scripts\\setup.bat，或 `pip install torch`",
                ),
            )
        ]
    rows = [(OK, "torch", str(torch.__version__))]
    if torch.cuda.is_available():
        rows.append((OK, "GPU", torch.cuda.get_device_name(0)))
    elif torch.version.cuda is None and shutil.which("nvidia-smi"):  # a GPU, but CPU torch
        rows.append(
            (
                WARN,
                "GPU",
                tr(
                    "an NVIDIA GPU is here, but torch is the CPU build (about 4 images/s). For "
                    "the GPU build (2.5 GB): python -m pip install --force-reinstall torch "
                    f"torchvision --index-url {CUDA_INDEX}",
                    "這台電腦有 NVIDIA 顯卡，但裝的是 CPU 版 torch（每秒約 4 張）。要換成 GPU 版"
                    "（2.5 GB）：python -m pip install --force-reinstall torch torchvision "
                    f"--index-url {CUDA_INDEX}",
                ),
            )
        )
    else:
        cuda_build = torch.version.cuda is not None
        hint = (
            tr("CUDA build but no GPU found", "CUDA 版，但沒有找到顯卡")
            if cuda_build
            else tr("CPU-only torch build", "CPU 版 torch")
        )
        rows.append(
            (
                WARN,
                "GPU",
                tr(
                    f"none ({hint}); embedding runs on CPU, about 4 images/s",
                    f"沒有（{hint}）；用 CPU 計算，每秒約 4 張",
                ),
            )
        )
    return rows


def _model_lines() -> list[tuple[str, str, str]]:
    from styleatlas.encoder import CSD_REVISION, MODEL_GB, NEED_GB

    root = cache_dir()
    slim = root / f"csd_vit_l_{CSD_REVISION[:8]}.safetensors"
    rows = [(OK, tr("cache", "快取資料夾"), str(root))]
    if slim.exists():
        size = f"{slim.stat().st_size / 1e9:.1f} GB"
        rows.append((OK, tr("CSD model", "CSD 模型"), tr(f"ready ({size})", f"已就緒（{size}）")))
    else:
        rows.append(
            (
                WARN,
                tr("CSD model", "CSD 模型"),
                tr(
                    f"not downloaded yet: the first run downloads {MODEL_GB} GB",
                    f"還沒下載：第一次使用時會下載 {MODEL_GB} GB",
                ),
            )
        )
    rows += _cache_lines(root)
    free_gb = shutil.disk_usage(root).free / 1e9
    need = 0.5 if slim.exists() else NEED_GB
    rows.append(
        (
            OK if free_gb > need else FAIL,
            tr("free disk", "磁碟空間"),
            tr(
                f"{free_gb:.1f} GB (need ~{need:.1f} GB)",
                f"{free_gb:.1f} GB（需要約 {need:.1f} GB）",
            ),
        )
    )
    old = _old_checkpoint()
    if slim.exists() and old is not None:
        size = f"{_size(old.rglob('*')) / 1e9:.1f} GB"
        rows.append(
            (
                WARN,
                tr("old download", "舊的下載"),
                tr(
                    f"{old} ({size}): style-atlas only uses its 1.2 GB copy now; delete this "
                    "folder to free the space if nothing else uses it",
                    f"{old}（{size}）：style-atlas 現在只用 1.2 GB 的精簡檔；沒有其他程式用到的話，"
                    "可以刪掉這個資料夾釋出空間",
                ),
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
        where = f"{vectors / 1e6:.0f} MB ({root / 'vectors.sqlite'})"
        rows.append((OK, tr("vector cache", "向量快取"), where))
    thumbs = root / "thumbs"
    if thumbs.is_dir():
        size = f"{_size(thumbs.rglob('*')) / 1e6:.0f} MB"
        rows.append(
            (
                OK,
                tr("thumbnails", "縮圖快取"),
                tr(f"{size}; {thumbs} can be deleted any time", f"{size}；{thumbs} 隨時可以刪掉"),
            )
        )
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
            rows.append(
                (
                    FAIL,
                    name,
                    tr(
                        "missing: reinstall with `pip install -e .`",
                        "缺少：請用 `pip install -e .` 重新安裝",
                    ),
                )
            )
    try:
        import umap  # noqa: F401

        rows.append((OK, "umap", tr("installed (UMAP map layouts)", "已安裝（地圖用 UMAP 版面）")))
    except ImportError:
        rows.append(
            (
                OK,
                "umap",
                tr(
                    "not installed (t-SNE layouts are used; optional)",
                    "沒有安裝（地圖改用 t-SNE 版面；可不裝）",
                ),
            )
        )
    return rows + [_whitening_line()] + _model_lines()


def _whitening_line() -> tuple[str, str, str]:
    """The search whitening ships inside the package; a broken install loses it."""
    try:
        from styleatlas.whiten import _params

        _params()
        return (OK, tr("search data", "搜尋資料"), tr("whitening map loaded", "已載入"))
    except (OSError, KeyError, ValueError) as e:
        return (
            FAIL,
            tr("search data", "搜尋資料"),
            tr(f"cannot load the whitening map ({e}): reinstall", f"讀不到（{e}）：請重新安裝"),
        )


def run() -> int:
    rows = checks()
    for status, name, detail in rows:
        print(f"[{status:4s}] {pad(name, 16)} {detail}")
    failed = [r for r in rows if r[0] == FAIL]
    if failed:
        print(tr(f"{len(failed)} problem(s) above", f"上面有 {len(failed)} 個問題（標示 FAIL）"))
    else:
        print(tr("all good", "一切正常，可以開始用了"))
    return 1 if failed else 0
