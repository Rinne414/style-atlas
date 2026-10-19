"""The CSD checkpoint loads under torch's safe loading (weights_only=True) with numpy 2.

The checkpoint was saved under numpy 1, so its pickle names numpy's scalar type as
numpy.core.multiarray.scalar; numpy 2 moved it to numpy._core, and an allowlist holding only the
new name made every first download fail (UnpicklingError), seen on a clean install."""

from __future__ import annotations

import io
import zipfile

import numpy as np
import pytest
import torch

from styleatlas.encoder import _numpy_pickle_globals

NEW = b"cnumpy._core.multiarray\nscalar\n"  # a pickle GLOBAL (torch.save writes protocol 2)
OLD = b"cnumpy.core.multiarray\nscalar\n"


def _saved_like_numpy_1() -> bytes:
    """A small checkpoint whose pickle names the scalar type the numpy 1 way."""
    buf = io.BytesIO()
    torch.save({"model_state_dict": {"w": torch.ones(2)}, "best": np.float64(0.5)}, buf)
    old_zip, new_zip = zipfile.ZipFile(io.BytesIO(buf.getvalue())), io.BytesIO()
    with zipfile.ZipFile(new_zip, "w", zipfile.ZIP_STORED) as out:
        for item in old_zip.infolist():
            data = old_zip.read(item)
            if item.filename.endswith("data.pkl"):
                assert NEW in data or OLD in data  # numpy 1 writes the old name itself
                data = data.replace(NEW, OLD)
            out.writestr(item.filename, data)
    return new_zip.getvalue()


def test_a_numpy_1_checkpoint_loads_safely():
    data = _saved_like_numpy_1()
    with pytest.raises(Exception, match="numpy.core.multiarray.scalar"):
        torch.load(io.BytesIO(data), weights_only=True)  # refused without the allowlist
    with torch.serialization.safe_globals(_numpy_pickle_globals()):
        state = torch.load(io.BytesIO(data), weights_only=True)
    assert torch.equal(state["model_state_dict"]["w"], torch.ones(2)) and state["best"] == 0.5
