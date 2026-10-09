"""Keep heavy work polite: cap CPU threads and lower process priority.

Long embedding runs on a desktop can starve the machine (and some machines hard-reset under full
load). Every command that loads a model calls `limit_resources` first, so the cap cannot be skipped.
"""

from __future__ import annotations

import contextlib
import os
import sys

import psutil

DEFAULT_THREADS = 8


def limit_resources(threads: int | None = DEFAULT_THREADS, low_priority: bool = True) -> int:
    """Pin to `threads` logical CPUs at lower priority. Returns the thread count in effect."""
    total = os.cpu_count() or 1
    n = total if not threads or threads <= 0 else min(threads, total)
    proc = psutil.Process()
    if hasattr(proc, "cpu_affinity"):  # not available on macOS
        with contextlib.suppress(psutil.Error, OSError, ValueError):
            proc.cpu_affinity(list(range(n)))
    if low_priority:
        with contextlib.suppress(psutil.Error, OSError):
            proc.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if sys.platform == "win32" else 10)
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ.setdefault(var, str(n))
    try:
        import torch

        torch.set_num_threads(n)
    except ImportError:
        pass
    return n
