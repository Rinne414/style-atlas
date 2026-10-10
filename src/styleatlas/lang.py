"""The language of command-line messages: Traditional Chinese on a Chinese Windows (or locale),
else English; the environment variable STYLE_ATLAS_LANG ("zh" or "en") overrides it. The summary
lines a person reads are translated; paths, option names and library errors stay as they are."""

from __future__ import annotations

import locale
import os
import sys
import unicodedata
from functools import lru_cache

LANG_CHINESE = 0x04  # Windows primary language id


def chinese() -> bool:
    choice = os.environ.get("STYLE_ATLAS_LANG", "").strip().lower()
    if choice.startswith(("zh", "en")):
        return choice.startswith("zh")
    return _system_is_chinese()  # unset, "auto" or anything else


@lru_cache(maxsize=1)
def _system_is_chinese() -> bool:
    try:
        if sys.platform == "win32":
            import ctypes

            ui = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return (ui & 0x3FF) == LANG_CHINESE
        name = locale.getlocale()[0] or os.environ.get("LANG", "")
        return name.lower().startswith("zh")
    except (OSError, ValueError, AttributeError):
        return False


def columns(text: str) -> int:
    """Terminal columns `text` takes: a Chinese character takes two."""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def pad(text: str, width: int) -> str:
    """`text` padded to `width` terminal columns (at least one space), so Chinese group names
    line up where plain format widths would not."""
    return text + " " * max(1, width - columns(text))


def tr(en: str, zh: str) -> str:
    """`zh` when messages are in Chinese, else `en`."""
    return zh if chinese() else en
