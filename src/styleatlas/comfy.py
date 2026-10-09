"""ComfyUI nodes: style distance to a reference set, and a gate that keeps original (or matching)
generations. ComfyUI itself is not imported here, so the logic is testable on its own; the thin
loader lives in the repository's `comfyui/` folder.

ComfyUI IMAGE tensors are float [batch, height, width, channels] in 0-1.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from styleatlas.atlas import EncodeOptions, build_atlas, get_encoder
from styleatlas.search import nearest_reference

CATEGORY = "style-atlas"
GATE_MODES = ("keep original", "keep matching")


@dataclass(frozen=True)
class StyleReferences:
    """Style vectors of a reference folder (the custom STYLE_REFS type)."""

    style: np.ndarray
    names: list[str]
    signature: str


def tensor_to_pil(images) -> list[Image.Image]:
    arr = images.detach().cpu().numpy() if hasattr(images, "detach") else np.asarray(images)
    arr = np.clip(arr * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return [Image.fromarray(a[..., :3]) for a in arr]


def embed_tensor(images, opts: EncodeOptions) -> np.ndarray:
    return get_encoder(opts).encode(tensor_to_pil(images)).style


class LoadStyleReferences:
    """Folder of styles you already know (artists, earlier generations, forum recipes)."""

    CATEGORY = CATEGORY
    RETURN_TYPES = ("STYLE_REFS",)
    FUNCTION = "load"

    @classmethod
    def INPUT_TYPES(cls):  # noqa: N802 (ComfyUI API name)
        return {
            "required": {
                "folder": ("STRING", {"default": ""}),
                "device": (["auto", "cpu", "cuda"],),
            }
        }

    def load(self, folder: str, device: str = "auto"):
        atlas = build_atlas(Path(folder), EncodeOptions(device=device))
        names = [atlas.rel(i) for i in range(len(atlas))]
        return (StyleReferences(atlas.style, names, atlas.signature),)


class StyleDistance:
    """Distance from each image to its closest reference (0 = same style; ~0.5+ = far)."""

    CATEGORY = CATEGORY
    RETURN_TYPES = ("FLOAT", "STRING")
    RETURN_NAMES = ("min_distance", "report")
    FUNCTION = "measure"

    @classmethod
    def INPUT_TYPES(cls):  # noqa: N802
        return {"required": {"images": ("IMAGE",), "references": ("STYLE_REFS",)}}

    def measure(self, images, references: StyleReferences, device: str = "auto"):
        dist, which = nearest_reference(
            embed_tensor(images, EncodeOptions(device=device)), references.style
        )
        lines = [
            f"#{k}: {d:.3f} closest {references.names[int(j)]}"
            for k, (d, j) in enumerate(zip(dist, which, strict=True))
        ]
        return (float(dist.min()), "\n".join(lines))


class StyleGate:
    """Keep only the images that are far enough from every reference (original), or close
    enough to one (matching). Returns the kept images and how many passed."""

    CATEGORY = CATEGORY
    RETURN_TYPES = ("IMAGE", "INT", "STRING")
    RETURN_NAMES = ("images", "kept", "report")
    FUNCTION = "gate"

    @classmethod
    def INPUT_TYPES(cls):  # noqa: N802
        return {
            "required": {
                "images": ("IMAGE",),
                "references": ("STYLE_REFS",),
                "mode": (list(GATE_MODES),),
                "threshold": ("FLOAT", {"default": 0.35, "min": 0.0, "max": 1.5, "step": 0.01}),
            }
        }

    def gate(self, images, references: StyleReferences, mode: str, threshold: float):
        if mode not in GATE_MODES:
            raise ValueError(f"mode must be one of {GATE_MODES}")
        dist, which = nearest_reference(embed_tensor(images, EncodeOptions()), references.style)
        keep = dist >= threshold if mode == "keep original" else dist < threshold
        report = [
            f"#{k}: {d:.3f} {'kept' if ok else 'dropped'} (closest {references.names[int(j)]})"
            for k, (d, j, ok) in enumerate(zip(dist, which, keep, strict=True))
        ]
        if not keep.any():  # ComfyUI needs at least one image downstream
            return (
                images[:1],
                0,
                "\n".join(report + ["nothing passed; first image passed through"]),
            )
        idx = [int(i) for i in np.flatnonzero(keep)]  # list indexing works for torch tensors
        return (images[idx], int(keep.sum()), "\n".join(report))


NODE_CLASS_MAPPINGS = {
    "StyleAtlasLoadReferences": LoadStyleReferences,
    "StyleAtlasDistance": StyleDistance,
    "StyleAtlasGate": StyleGate,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "StyleAtlasLoadReferences": "Load Style References (style-atlas)",
    "StyleAtlasDistance": "Style Distance (style-atlas)",
    "StyleAtlasGate": "Style Gate (style-atlas)",
}
