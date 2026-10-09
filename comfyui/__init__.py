"""ComfyUI entry point for style-atlas nodes.

Install: put (or link) this folder into ComfyUI/custom_nodes/style-atlas, and install style-atlas
into the Python that ComfyUI runs (e.g. `python_embeded/python.exe -m pip install -e <repo>`).
"""

from styleatlas.comfy import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
