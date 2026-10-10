"""CSD style encoder (Somepalli et al. 2024, "Measuring Style Similarity in Diffusion Models").

Weights: Hugging Face `tomg-group-umd/CSD-ViT-L` (CC-BY-4.0), downloaded on first use. The backbone
is OpenAI CLIP ViT-L/14 (QuickGELU) without its projection; CSD adds two 1024x768 heads, one for
style and one for content. Outputs are L2-normalised 768-d vectors.

The training checkpoint holds optimiser state (2.4 GB). On first load the needed tensors are copied
to a small safetensors file in the cache folder so later loads are fast and pickle-free.
"""

from __future__ import annotations

import argparse
import logging
import math
import os
from dataclasses import dataclass

import numpy as np
import torch
from PIL import Image
from torchvision import transforms as T

from styleatlas.cachedir import cache_dir

CSD_REPO = "tomg-group-umd/CSD-ViT-L"
CSD_REVISION = "5bc26a6fb0487f3f00a2a7313135103a005b1b67"
INPUT_PX = 224
RESOLUTIONS = (224, 336)  # 336 interpolates the position embeddings (arXiv 2605.09030)
PATCH = 14
CLIP_MEAN = (0.48145466, 0.4578275, 0.40821073)
CLIP_STD = (0.26862954, 0.26130258, 0.27577711)
CROP_MODES = ("center", "tiles")
MAX_TILES = 3
MAX_ASPECT = 4.0  # longer strips are centre-cropped first (keeps memory bounded)


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
    allowed = [argparse.Namespace, scalar, np.dtype]
    for name in ("Float64DType", "Int64DType", "Float32DType"):
        if hasattr(np, "dtypes") and hasattr(np.dtypes, name):
            allowed.append(getattr(np.dtypes, name))
    return allowed


class ModelDownloadError(RuntimeError):
    """The CSD weights could not be fetched (no network, blocked site, full disk)."""


MIRROR_HINT = (
    "If huggingface.co cannot be reached from here, set the environment variable "
    "HF_ENDPOINT=https://hf-mirror.com and try again."
)


def _extract_weights() -> dict[str, torch.Tensor]:
    from huggingface_hub import hf_hub_download

    try:
        path = hf_hub_download(CSD_REPO, "pytorch_model.bin", revision=CSD_REVISION)
    except OSError as e:  # connection, HTTP and missing-file errors of huggingface_hub
        raise ModelDownloadError(
            f"could not download the style model ({CSD_REPO}): {e}. {MIRROR_HINT}"
        ) from e
    with torch.serialization.safe_globals(_numpy_pickle_globals()):
        state = torch.load(path, map_location="cpu", weights_only=True)["model_state_dict"]
    state = {k.removeprefix("module."): v for k, v in state.items()}
    keep = {k: v.float().contiguous() for k, v in state.items() if k.startswith("backbone.")}
    keep["last_layer_style"] = state["last_layer_style"].float().contiguous()
    keep["last_layer_content"] = state["last_layer_content"].float().contiguous()
    return keep


def load_weights() -> dict[str, torch.Tensor]:
    from safetensors.torch import load_file, save_file

    slim = cache_dir() / f"csd_vit_l_{CSD_REVISION[:8]}.safetensors"
    if slim.exists():
        return load_file(str(slim))
    weights = _extract_weights()
    tmp = slim.with_suffix(".tmp")
    save_file(weights, str(tmp))
    os.replace(tmp, slim)
    return weights


def square_crops(im: Image.Image, mode: str, px: int = INPUT_PX) -> list[Image.Image]:
    """Resize the short side to `px`; take the centre square or tiles along the long side."""
    w, h = im.size
    if max(w, h) > MAX_ASPECT * min(w, h):
        long_keep = int(MAX_ASPECT * min(w, h))
        if w > h:
            im = im.crop(((w - long_keep) // 2, 0, (w - long_keep) // 2 + long_keep, h))
        else:
            im = im.crop((0, (h - long_keep) // 2, w, (h - long_keep) // 2 + long_keep))
        w, h = im.size
    scale = px / min(w, h)
    rw, rh = max(px, round(w * scale)), max(px, round(h * scale))
    im = im.resize((rw, rh), Image.Resampling.BICUBIC)
    long_side = max(rw, rh)
    n = 1 if mode == "center" else min(MAX_TILES, math.ceil(long_side / px - 0.15))
    if n <= 1:
        offsets = [(long_side - px) // 2]
    else:
        offsets = [round(i * (long_side - px) / (n - 1)) for i in range(n)]
    if rw >= rh:
        return [im.crop((o, 0, o + px, px)) for o in offsets]
    return [im.crop((0, o, px, o + px)) for o in offsets]


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
        batch_size: int = 8,
        resolution: int = INPUT_PX,
    ):
        if crop not in CROP_MODES:
            raise ValueError(f"crop must be one of {CROP_MODES}, got {crop!r}")
        if resolution not in RESOLUTIONS:
            raise ValueError(f"resolution must be one of {RESOLUTIONS}, got {resolution!r}")
        import open_clip

        self.device = resolve_device(device)
        self.crop = crop
        self.px = resolution
        self.batch_size = max(1, batch_size)
        weights = load_weights()
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

    def encode(self, images: list[Image.Image]) -> Embeddings:
        crops, owner = [], []
        for i, im in enumerate(images):
            for c in square_crops(im, self.crop, self.px):
                crops.append(self.to_tensor(c))
                owner.append(i)
        style_rows, content_rows = [], []
        for s in range(0, len(crops), self.batch_size):
            st, ct = self._run(torch.stack(crops[s : s + self.batch_size]))
            style_rows.append(torch.nn.functional.normalize(st, dim=1).cpu())
            content_rows.append(torch.nn.functional.normalize(ct, dim=1).cpu())
        owner_t = torch.tensor(owner)
        return Embeddings(
            style=_pool(torch.cat(style_rows), owner_t, len(images)),
            content=_pool(torch.cat(content_rows), owner_t, len(images)),
        )


def _pool(rows: torch.Tensor, owner: torch.Tensor, n: int) -> np.ndarray:
    """Average each image's crop vectors, then re-normalise."""
    out = torch.zeros(n, rows.shape[1])
    out.index_add_(0, owner, rows)
    return torch.nn.functional.normalize(out, dim=1).numpy().astype(np.float32)
