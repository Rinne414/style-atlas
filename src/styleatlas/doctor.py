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
                    "没有安装：请运行 scripts\\setup.bat，或 `pip install torch`",
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
                    "这台电脑有 NVIDIA 显卡，但装的是 CPU 版 torch（每秒约 4 张）。要换成 GPU 版"
                    "（2.5 GB）：python -m pip install --force-reinstall torch torchvision "
                    f"--index-url {CUDA_INDEX}",
                ),
            )
        )
    else:
        cuda_build = torch.version.cuda is not None
        hint = (
            tr("CUDA build but no GPU found", "CUDA 版，但没有找到显卡")
            if cuda_build
            else tr("CPU-only torch build", "CPU 版 torch")
        )
        rows.append(
            (
                WARN,
                "GPU",
                tr(
                    f"none ({hint}); embedding runs on CPU, about 4 images/s",
                    f"没有（{hint}）；用 CPU 计算，每秒约 4 张",
                ),
            )
        )
    return rows


def _model_lines() -> list[tuple[str, str, str]]:
    from styleatlas.encoder import MODEL_GB, NEED_GB, slim_path

    root = cache_dir()
    slim = slim_path()
    rows = [(OK, tr("cache", "缓存文件夹"), str(root))]
    if slim.exists():
        size = f"{slim.stat().st_size / 1e9:.1f} GB"
        rows.append((OK, tr("CSD model", "CSD 模型"), tr(f"ready ({size})", f"已就绪（{size}）")))
    else:
        rows.append(
            (
                WARN,
                tr("CSD model", "CSD 模型"),
                tr(
                    f"not downloaded yet: the first run downloads {MODEL_GB} GB",
                    f"还没下载：第一次使用时会下载 {MODEL_GB} GB",
                ),
            )
        )
    rows += _cache_lines(root)
    free_gb = shutil.disk_usage(root).free / 1e9
    need = 0.5 if slim.exists() else NEED_GB
    rows.append(
        (
            OK if free_gb > need else FAIL,
            tr("free disk", "磁盘空间"),
            tr(
                f"{free_gb:.1f} GB (need ~{need:.1f} GB)",
                f"{free_gb:.1f} GB（需要约 {need:.1f} GB）",
            ),
        )
    )
    old = _old_checkpoint()
    if slim.exists() and old is not None:
        size = f"{_size(old.rglob('*')) / 1e9:.1f} GB"
        rows.append(
            (
                WARN,
                tr("old download", "旧的下载"),
                tr(
                    f"{old} ({size}): style-atlas only uses its 1.2 GB copy now; delete this "
                    "folder to free the space if nothing else uses it",
                    f"{old}（{size}）：style-atlas 现在只用 1.2 GB 的精简文件；"
                    "没有其他程序用到的话，可以删掉这个文件夹释放空间",
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
        rows.append((OK, tr("vector cache", "向量缓存"), where))
    thumbs = root / "thumbs"
    if thumbs.is_dir():
        size = f"{_size(thumbs.rglob('*')) / 1e6:.0f} MB"
        rows.append(
            (
                OK,
                tr("thumbnails", "缩略图缓存"),
                tr(f"{size}; {thumbs} can be deleted any time", f"{size}；{thumbs} 随时可以删掉"),
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
                        "缺少：请用 `pip install -e .` 重新安装",
                    ),
                )
            )
    try:
        import umap  # noqa: F401

        rows.append((OK, "umap", tr("installed (UMAP map layouts)", "已安装（地图用 UMAP 版面）")))
    except ImportError:
        rows.append(
            (
                OK,
                "umap",
                tr(
                    "not installed (t-SNE layouts are used; optional)",
                    "没有安装（地图改用 t-SNE 版面；可不装）",
                ),
            )
        )
    return rows + [_whitening_line()] + _model_lines()


def _whitening_line() -> tuple[str, str, str]:
    """The search whitening ships inside the package; a broken install loses it."""
    try:
        from styleatlas.whiten import _params

        _params()
        return (OK, tr("search data", "搜索数据"), tr("whitening map loaded", "已加载"))
    except (OSError, KeyError, ValueError) as e:
        return (
            FAIL,
            tr("search data", "搜索数据"),
            tr(f"cannot load the whitening map ({e}): reinstall", f"读不到（{e}）：请重新安装"),
        )


def run() -> int:
    rows = checks()
    for status, name, detail in rows:
        print(f"[{status:4s}] {pad(name, 16)} {detail}")
    failed = [r for r in rows if r[0] == FAIL]
    if failed:
        print(tr(f"{len(failed)} problem(s) above", f"上面有 {len(failed)} 个问题（标示 FAIL）"))
    else:
        print(tr("all good", "一切正常，可以开始用了"))
    return 1 if failed else 0
