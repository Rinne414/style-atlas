"""The parts of the local server that load nothing heavy, so the desktop program can start, or
hand over to a copy already open, before torch is imported (webserver.py imports it)."""

from __future__ import annotations

POST_HEADER = "X-Style-Atlas"  # every POST needs it: a cross-site page cannot send it
CONTROL_PATH = "/desktop/window"  # a later start of the desktop program asks for a window here


class StandIn:
    """Answers in place of a StyleAtlasApp: a page, no images, no requests (503)."""

    atlas = ()  # no images

    def page(self) -> str:
        raise NotImplementedError
