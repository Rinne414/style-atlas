"""CSD style encoder (Somepalli et al. 2024, "Measuring Style Similarity in Diffusion Models").

Weights: Hugging Face `tomg-group-umd/CSD-ViT-L` (CC-BY-4.0), downloaded on first use. The backbone
is OpenAI CLIP ViT-L/14 (QuickGELU) without its projection; CSD adds two 1024x768 heads, one for
style and one for content. Outputs are L2-normalised 768-d vectors.

The training checkpoint holds optimiser state (2.4 GB). On first load the needed tensors are copied
to a small safetensors file in the cache folder so later loads are fast and pickle-free.
"""

from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torchvision import transforms as T

CSD_REPO = "tomg-group-umd/CSD-ViT-L"
CSD_REVISION = "5bc26a6fb0487f3f00a2a7313135103a005b1b67"
INPUT_PX = 224
CLIP_MEAN = (0.48145466, 0.4578275, 0.40821073)
CLIP_STD = (0.26862954, 0.26130258, 0.27577711)
CROP_MODES = ("center", "tiles")
MAX_TILES = 3


def cache_dir() -> Path:
    root = os.environ.get("STYLE_ATLAS_CACHE") or Path.home() / ".cache" / "style-atlas"
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return path


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


def _extract_weights() -> dict[str, torch.Tensor]:
    from huggingface_hub import hf_hub_download

    path = hf_hub_download(CSD_REPO, "pytorch_model.bin", revision=CSD_REVISION)
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


def square_crops(im: Image.Image, mode: str) -> list[Image.Image]:
    """Resize the short side to INPUT_PX; take the centre square or tiles along the long side."""
    w, h = im.size
    scale = INPUT_PX / min(w, h)
    rw, rh = max(INPUT_PX, round(w * scale)), max(INPUT_PX, round(h * scale))
    im = im.resize((rw, rh), Image.Resampling.BICUBIC)
    long_side = max(rw, rh)
    n = 1 if mode == "center" else min(MAX_TILES, math.ceil(long_side / INPUT_PX - 0.15))
    if n <= 1:
        offsets = [(long_side - INPUT_PX) // 2]
    else:
        offsets = [round(i * (long_side - INPUT_PX) / (n - 1)) for i in range(n)]
    if rw >= rh:
        return [im.crop((o, 0, o + INPUT_PX, INPUT_PX)) for o in offsets]
    return [im.crop((0, o, INPUT_PX, o + INPUT_PX)) for o in offsets]


def encoder_signature(crop: str) -> str:
    """Identifies the vector space; cached vectors with another signature are recomputed."""
    return f"csd-vit-l@{CSD_REVISION[:8]}/{crop}{INPUT_PX}"


@dataclass(frozen=True)
class Embeddings:
    style: np.ndarray  # (n, 768) float32, unit rows
    content: np.ndarray  # (n, 768) float32, unit rows


class CSDEncoder:
    """Image -> (style, content) unit vectors."""

    def __init__(self, device: str = "auto", crop: str = "center", batch_size: int = 8):
        if crop not in CROP_MODES:
            raise ValueError(f"crop must be one of {CROP_MODES}, got {crop!r}")
        import open_clip

        self.device = resolve_device(device)
        self.crop = crop
        self.batch_size = max(1, batch_size)
        weights = load_weights()
        visual = open_clip.create_model("ViT-L-14-quickgelu", pretrained=None).visual
        visual.proj = None
        backbone = {
            k.removeprefix("backbone."): v for k, v in weights.items() if k.startswith("backbone.")
        }
        visual.load_state_dict(backbone, strict=True)
        self.visual = visual.float().to(self.device).eval()
        self.style_head = weights["last_layer_style"].to(self.device)
        self.content_head = weights["last_layer_content"].to(self.device)
        self.to_tensor = T.Compose([T.ToTensor(), T.Normalize(CLIP_MEAN, CLIP_STD)])

    @property
    def signature(self) -> str:
        return encoder_signature(self.crop)

    @torch.inference_mode()
    def _run(self, batch: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        feats = self.visual(batch.to(self.device))
        return feats @ self.style_head, feats @ self.content_head

    def encode(self, images: list[Image.Image]) -> Embeddings:
        crops, owner = [], []
        for i, im in enumerate(images):
            for c in square_crops(im, self.crop):
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
