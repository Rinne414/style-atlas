"""CSD style encoder (Somepalli et al. 2024, "Measuring Style Similarity in Diffusion Models").

Weights: Hugging Face `tomg-group-umd/CSD-ViT-L` (CC-BY-4.0), downloaded on first use. The backbone
is OpenAI CLIP ViT-L/14 (QuickGELU) without its projection; CSD adds two 1024x768 heads, one for
style and one for content. Outputs are L2-normalised 768-d vectors.

The training checkpoint holds optimiser state (2.4 GB). On first load the needed tensors are copied
to a small safetensors file in the cache folder so later loads are fast and pickle-free, and the
checkpoint is removed again. It is downloaded into the cache folder from the faster of
huggingface.co and hf-mirror.com (fetch.py; checked against its SHA256), unless the user's own
Hugging Face cache has it already: then that copy is read and left where it is.
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import shutil
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torchvision import transforms as T

from styleatlas import fetch
from styleatlas.cachedir import cache_dir
from styleatlas.lang import tr
from styleatlas.prepare import INPUT_PX, square_crops

CSD_REPO = "tomg-group-umd/CSD-ViT-L"
CSD_REVISION = "5bc26a6fb0487f3f00a2a7313135103a005b1b67"
CSD_FILE = "pytorch_model.bin"
CSD_SHA256 = "40e92fad63a361b8136100cd234c42d401ef9b34ff1748234318929ebcc7e7a1"  # at CSD_REVISION
CSD_BYTES = 2_438_228_893
HF_HOSTS = ("https://huggingface.co", "https://hf-mirror.com")  # the original, then its mirror
PROGRESS_EVERY = 1.0  # seconds between download progress lines
# images per model batch when none is given; on an RTX 3090 a batch of 16 embedded 46 images/s
# where 8 did 41 (2026-10-20, same vectors to 1e-6); the CPU was not measured, so it keeps 8
GPU_BATCH = 16
CPU_BATCH = 8
RESOLUTIONS = (224, 336)  # 336 interpolates the position embeddings (arXiv 2605.09030)
PATCH = 14
CLIP_MEAN = (0.48145466, 0.4578275, 0.40821073)
CLIP_STD = (0.26862954, 0.26130258, 0.27577711)
CROP_MODES = ("center", "tiles")
DOWNLOAD_DIR = "hf-download"  # the checkpoint while the slim copy is made; removed after
MODEL_GB = 2.4  # the checkpoint
SLIM_GB = 1.2  # the copy kept in the cache folder
ROOM_GB = 0.3  # spare room per drive
NEED_GB = MODEL_GB + SLIM_GB + ROOM_GB  # one drive holds both while the copy is made (3.9 GB)


def resolve_device(device: str) -> str:
    if device == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    return device


def _numpy_pickle_globals() -> list:
    """Types the CSD training checkpoint pickles besides tensors (argparse args, numpy scalars)."""
    try:
        from numpy._core.multiarray import scalar
    except ImportError:  # numpy < 2
        from numpy.core.multiarray import scalar
    # the checkpoint was saved under numpy 1, where scalar lived in numpy.core; under numpy 2 the
    # name differs from the one in the file, which torch then refuses (every first download did)
    allowed = [argparse.Namespace, scalar, (scalar, "numpy.core.multiarray.scalar"), np.dtype]
    for name in ("Float64DType", "Int64DType", "Float32DType"):
        if hasattr(np, "dtypes") and hasattr(np.dtypes, name):
            allowed.append(getattr(np.dtypes, name))
    return allowed


class ModelDownloadError(RuntimeError):
    """The CSD weights could not be fetched (no network, blocked site, full disk)."""


NETWORK_HINT = (
    "Check the network or proxy and try again; the environment variable HF_ENDPOINT can name "
    "another mirror (Windows: set HF_ENDPOINT=https://...)."
)
NETWORK_HINT_ZH = (
    "请检查网络或代理后再试；也可以用环境变量 HF_ENDPOINT 指定别的镜像站"
    "（Windows：set HF_ENDPOINT=https://...）。"
)


def download_dir() -> Path:
    """Where the checkpoint is downloaded while the slim copy is made (removed after)."""
    return cache_dir() / DOWNLOAD_DIR


def model_urls() -> list[str]:
    """The checkpoint on each host to try: HF_ENDPOINT alone when the user set it."""
    chosen = os.environ.get("HF_ENDPOINT", "").strip()
    hosts = [chosen] if chosen else list(HF_HOSTS)
    return [f"{h.rstrip('/')}/{CSD_REPO}/resolve/{CSD_REVISION}/{CSD_FILE}" for h in hosts]


def hf_cached() -> Path | None:
    """The checkpoint in the user's own Hugging Face cache, when another tool downloaded it."""
    try:
        from huggingface_hub import try_to_load_from_cache

        found = try_to_load_from_cache(CSD_REPO, CSD_FILE, revision=CSD_REVISION)
    except (ImportError, OSError, ValueError):
        return None
    if not isinstance(found, str) or not Path(found).is_file():
        return None
    return Path(found) if Path(found).stat().st_size == CSD_BYTES else None  # not a broken copy


def finished_download() -> Path | None:
    """The checkpoint a stopped run downloaded but did not turn into the slim copy (checked
    against its SHA256 first), so it is not downloaded again."""
    path = download_dir() / CSD_FILE
    if path.is_file() and path.stat().st_size == CSD_BYTES and fetch.sha256_of(path) == CSD_SHA256:
        return path
    return None


def check_space(downloading: bool = True) -> None:
    """Fail before a download that cannot fit, saying how to put the cache elsewhere."""
    root = cache_dir()
    need = round(SLIM_GB + ROOM_GB + (MODEL_GB if downloading else 0), 1)
    free = shutil.disk_usage(root).free / 1e9
    if free < need:
        raise ModelDownloadError(
            tr(
                f"the first run needs about {need} GB free for the style model, but "
                f"{root.anchor or root} has {free:.1f} GB. Free some space, or move the cache to "
                "another drive (start page: Move…; or the environment variable STYLE_ATLAS_CACHE)",
                f"第一次使用需要约 {need} GB 的空间放画风模型，"
                f"但 {root.anchor or root} 只剩 {free:.1f} GB。请清出空间，"
                "或把缓存搬到别的磁盘（开始页面的“更改位置…”，或环境变量 STYLE_ATLAS_CACHE）",
            )
        )


def fetch_checkpoint(progress: Callable[[str], None]) -> Path:
    """Download the checkpoint into download_dir() from the fastest host and return it."""
    urls = model_urls()
    ranking = fetch.ranked(urls, fetch.file_speed) if len(urls) > 1 else [(urls[0], 0.0)]
    if len(urls) > 1:
        progress(
            tr(
                f"download sources: {fetch.describe(ranking)}",
                f"下载来源测速：{fetch.describe(ranking, '无回应')}",
            )
        )
    last = [0.0, 0]  # time and bytes of the last progress line

    def tick(done: int, total: int, host: str) -> None:
        now = time.monotonic()
        if now - last[0] < PROGRESS_EVERY and done < total:
            return
        rate = (done - last[1]) / max(now - last[0], 1e-3) / 1e6 if last[0] else 0.0
        last[:] = [now, done]
        pct = 100 * done // total
        progress(
            "\r"  # replaces the line before on the waiting page
            + tr(
                f"downloading the style model: {pct}% of {total / 1e9:.1f} GB, {rate:.1f} MB/s "
                f"from {host}",
                f"正在下载画风模型：{pct}%（共 {total / 1e9:.1f} GB），{rate:.1f} MB/s，"
                f"来源 {host}",
            )
        )

    dest = download_dir() / CSD_FILE
    try:
        fetch.download(ranking, dest, CSD_SHA256, CSD_BYTES, tick)
    except fetch.FetchError as e:
        raise ModelDownloadError(
            tr(
                f"could not download the style model: {e}. {NETWORK_HINT}",
                f"无法下载画风模型：{e}。{NETWORK_HINT_ZH}",
            )
        ) from e
    return dest


def _extract_weights(path: Path) -> dict[str, torch.Tensor]:
    with torch.serialization.safe_globals(_numpy_pickle_globals()):
        state = torch.load(path, map_location="cpu", weights_only=True)["model_state_dict"]
    state = {k.removeprefix("module."): v for k, v in state.items()}
    keep = {k: v.float().contiguous() for k, v in state.items() if k.startswith("backbone.")}
    keep["last_layer_style"] = state["last_layer_style"].float().contiguous()
    keep["last_layer_content"] = state["last_layer_content"].float().contiguous()
    return keep


def slim_path() -> Path:
    """The 1.2 GB copy of the model kept after the first download."""
    return cache_dir() / f"csd_vit_l_{CSD_REVISION[:8]}.safetensors"


def _say(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def load_weights(progress: Callable[[str], None] | None = None) -> dict[str, torch.Tensor]:
    """The slim weights, made on the first run from the checkpoint (downloaded unless the
    user's Hugging Face cache has it). `progress` gets the lines the waiting page shows."""
    from safetensors.torch import load_file, save_file

    progress = progress or _say
    slim = slim_path()
    ours = download_dir()
    if slim.exists():
        if ours.exists():  # left by a run stopped before it removed it
            shutil.rmtree(ours, ignore_errors=True)
        return load_file(str(slim))
    checkpoint = hf_cached() or finished_download()
    check_space(downloading=checkpoint is None)
    if checkpoint is None:
        progress(
            tr(
                "first run: downloading the style model once (about 2.4 GB; a 1.2 GB copy is kept)",
                "第一次使用：下载画风模型（约 2.4 GB，只会下载一次；之后保留 1.2 GB 的精简版）",
            )
        )
        _clear_other_downloads(ours)
        checkpoint = fetch_checkpoint(progress)
    progress(tr("preparing the style model (once)", "正在整理画风模型（只需一次）"))
    weights = _extract_weights(checkpoint)
    tmp = slim.with_suffix(".tmp")
    save_file(weights, str(tmp))
    os.replace(tmp, slim)
    shutil.rmtree(ours, ignore_errors=True)  # the 2.4 GB checkpoint is not needed again
    return weights


def _clear_other_downloads(folder: Path) -> None:
    """Everything in the download folder but our own unfinished download (older versions left
    Hugging Face's layout there, which this download does not continue)."""
    keep = f"{CSD_FILE}.part"
    if folder.is_dir():
        for path in folder.iterdir():
            if path.name != keep:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)


def encoder_signature(crop: str, px: int = INPUT_PX) -> str:
    """Identifies the vector space; cached vectors with another signature are recomputed."""
    return f"csd-vit-l@{CSD_REVISION[:8]}/{crop}{px}"


def resize_pos_embed(pos: torch.Tensor, px: int) -> torch.Tensor:
    """(1 + g*g, d) CLIP position embeddings -> grid for `px` inputs (bicubic, class token kept)."""
    old = int(math.isqrt(pos.shape[0] - 1))
    new = px // PATCH
    if new == old:
        return pos
    grid = pos[1:].reshape(1, old, old, -1).permute(0, 3, 1, 2)
    grid = torch.nn.functional.interpolate(
        grid, size=(new, new), mode="bicubic", align_corners=False, antialias=True
    )
    return torch.cat([pos[:1], grid.permute(0, 2, 3, 1).reshape(new * new, -1)])


@dataclass(frozen=True)
class Embeddings:
    style: np.ndarray  # (n, 768) float32, unit rows
    content: np.ndarray  # (n, 768) float32, unit rows


class _NoRandomInitWarning(logging.Filter):
    """Drops only open_clip's "No pretrained weights loaded ... initialized randomly" line."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "No pretrained weights loaded" not in record.getMessage()


class CSDEncoder:
    """Image -> (style, content) unit vectors."""

    def __init__(
        self,
        device: str = "auto",
        crop: str = "center",
        batch_size: int | None = None,
        resolution: int = INPUT_PX,
        progress: Callable[[str], None] | None = None,
    ):
        if crop not in CROP_MODES:
            raise ValueError(f"crop must be one of {CROP_MODES}, got {crop!r}")
        if resolution not in RESOLUTIONS:
            raise ValueError(f"resolution must be one of {RESOLUTIONS}, got {resolution!r}")
        import open_clip

        self.device = resolve_device(device)
        self.crop = crop
        self.px = resolution
        default = GPU_BATCH if self.device == "cuda" else CPU_BATCH
        self.batch_size = max(1, batch_size or default)
        weights = load_weights(progress)
        quiet = _NoRandomInitWarning()  # open_clip says "initialized randomly"; CSD loads next
        logging.getLogger().addFilter(quiet)
        try:
            visual = open_clip.create_model(
                "ViT-L-14-quickgelu", pretrained=None, force_image_size=resolution
            ).visual
        finally:
            logging.getLogger().removeFilter(quiet)
        visual.proj = None
        backbone = {
            k.removeprefix("backbone."): v for k, v in weights.items() if k.startswith("backbone.")
        }
        backbone["positional_embedding"] = resize_pos_embed(
            backbone["positional_embedding"], resolution
        )
        visual.load_state_dict(backbone, strict=True)
        self.visual = visual.float().to(self.device).eval()
        self.style_head = weights["last_layer_style"].to(self.device)
        self.content_head = weights["last_layer_content"].to(self.device)
        self.to_tensor = T.Compose([T.ToTensor(), T.Normalize(CLIP_MEAN, CLIP_STD)])

    @property
    def signature(self) -> str:
        return encoder_signature(self.crop, self.px)

    @torch.inference_mode()
    def _run(self, batch: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        feats = self.visual(batch.to(self.device))
        return feats @ self.style_head, feats @ self.content_head

    def prepare(self, image: Image.Image) -> list[torch.Tensor]:
        """The model inputs for one image (one per crop). Safe to call from several threads,
        so the next images can be prepared while the model runs."""
        return [self.to_tensor(c) for c in square_crops(image, self.crop, self.px)]

    def tensors(self, squares: list[np.ndarray]) -> list[torch.Tensor]:
        """The model inputs from prepare.prepare_file's uint8 squares: the same numbers prepare
        gives for the image (ToTensor reads an array as it reads a picture)."""
        return [self.to_tensor(square) for square in squares]

    def encode(self, images: list[Image.Image]) -> Embeddings:
        return self.encode_prepared([self.prepare(im) for im in images])

    def encode_prepared(self, prepared: list[list[torch.Tensor]]) -> Embeddings:
        crops = [c for inputs in prepared for c in inputs]
        owner = [i for i, inputs in enumerate(prepared) for _ in inputs]
        style_rows, content_rows = [], []
        for s in range(0, len(crops), self.batch_size):
            st, ct = self._run(torch.stack(crops[s : s + self.batch_size]))
            style_rows.append(torch.nn.functional.normalize(st, dim=1).cpu())
            content_rows.append(torch.nn.functional.normalize(ct, dim=1).cpu())
        owner_t = torch.tensor(owner)
        return Embeddings(
            style=_pool(torch.cat(style_rows), owner_t, len(prepared)),
            content=_pool(torch.cat(content_rows), owner_t, len(prepared)),
        )


def _pool(rows: torch.Tensor, owner: torch.Tensor, n: int) -> np.ndarray:
    """Average each image's crop vectors, then re-normalise."""
    out = torch.zeros(n, rows.shape[1])
    out.index_add_(0, owner, rows)
    return torch.nn.functional.normalize(out, dim=1).numpy().astype(np.float32)
