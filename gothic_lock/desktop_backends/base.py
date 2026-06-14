"""Shared desktop backend interface and helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class DesktopBackend(Protocol):
    name: str

    def available(self) -> bool: ...

    def send_key(self, key: str) -> None: ...

    def active_window_region(self) -> str | None: ...

    def capture_screenshot(self, path: Path, region: str | None) -> None: ...


def parse_region(region: str) -> tuple[int, int, int, int]:
    """Parse 'x,y WxH' or 'x,y,w,h' into a Pillow bbox."""
    text = region.strip()
    try:
        if " " in text and "x" in text:
            origin, size = text.split(None, 1)
            left_text, top_text = origin.split(",", 1)
            width_text, height_text = size.lower().split("x", 1)
            left = int(left_text)
            top = int(top_text)
            width = int(width_text)
            height = int(height_text)
        else:
            left, top, width, height = (int(part.strip()) for part in text.split(",", 3))
    except ValueError as exc:
        raise SystemExit(f"Bad capture region {region!r}; expected 'x,y WxH' or 'x,y,w,h'") from exc

    if width <= 0 or height <= 0:
        raise SystemExit(f"Bad capture region {region!r}; width and height must be positive")
    return left, top, left + width, top + height
