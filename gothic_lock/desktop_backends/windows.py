"""Windows desktop backend."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from PIL import ImageGrab

from gothic_lock.desktop_backends.base import parse_region


class WindowsBackend:
    name = "windows"

    def available(self) -> bool:
        return sys.platform == "win32"

    def send_key(self, key: str) -> None:
        if not self.available():
            raise SystemExit("windows backend is only available on Windows")

        import ctypes

        vk = windows_virtual_key(key)
        scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0)
        ctypes.windll.user32.keybd_event(vk, scan, 0, 0)
        time.sleep(0.02)
        ctypes.windll.user32.keybd_event(vk, scan, 0x0002, 0)

    def active_window_region(self) -> str | None:
        if not self.available():
            return None

        import ctypes
        from ctypes import wintypes

        set_windows_dpi_aware()
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None

        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        width = int(rect.right - rect.left)
        height = int(rect.bottom - rect.top)
        if width <= 100 or height <= 100:
            return None
        return f"{int(rect.left)},{int(rect.top)} {width}x{height}"

    def capture_screenshot(self, path: Path, region: str | None) -> None:
        set_windows_dpi_aware()
        if region is None:
            region = self.active_window_region()
        bbox = parse_region(region) if region else None
        image = ImageGrab.grab(bbox=bbox)
        image.save(path)


def set_windows_dpi_aware() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def windows_virtual_key(key: str) -> int:
    normalized = key.strip().lower()
    if len(normalized) == 1 and normalized.isalnum():
        return ord(normalized.upper())
    named = {
        "esc": 0x1B,
        "escape": 0x1B,
        "enter": 0x0D,
        "return": 0x0D,
        "space": 0x20,
        "tab": 0x09,
        "left": 0x25,
        "up": 0x26,
        "right": 0x27,
        "down": 0x28,
    }
    try:
        return named[normalized]
    except KeyError as exc:
        raise SystemExit(f"Unsupported Windows key {key!r}") from exc
