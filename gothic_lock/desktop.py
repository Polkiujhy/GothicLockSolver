"""Desktop-specific capture and keyboard backends.

The scanner and solver should not know whether input is sent through Hyprland,
X11, KDE Plasma, or Windows. Add future desktop providers here behind the same
small backend interface.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Protocol

from PIL import ImageGrab


class DesktopBackend(Protocol):
    name: str

    def available(self) -> bool: ...

    def send_key(self, key: str) -> None: ...

    def active_window_region(self) -> str | None: ...


class PrintBackend:
    name = "print"

    def available(self) -> bool:
        return True

    def send_key(self, key: str) -> None:
        return None

    def active_window_region(self) -> str | None:
        return None


class HyprlandBackend:
    name = "hyprctl"

    def available(self) -> bool:
        return shutil.which("hyprctl") is not None

    def send_key(self, key: str) -> None:
        subprocess.run(
            ["hyprctl", "dispatch", "sendshortcut", f",{key},activewindow"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def active_window_region(self) -> str | None:
        if not self.available():
            return None
        try:
            result = subprocess.run(
                ["hyprctl", "-j", "activewindow"],
                check=True,
                capture_output=True,
                text=True,
                timeout=1.5,
            )
            data = json.loads(result.stdout)
            at = data.get("at")
            size = data.get("size")
            if (
                isinstance(at, list)
                and isinstance(size, list)
                and len(at) == 2
                and len(size) == 2
                and int(size[0]) > 100
                and int(size[1]) > 100
            ):
                return f"{int(at[0])},{int(at[1])} {int(size[0])}x{int(size[1])}"
        except Exception:
            return None
        return None


class XDoToolBackend:
    name = "xdotool"

    def available(self) -> bool:
        return shutil.which("xdotool") is not None

    def send_key(self, key: str) -> None:
        subprocess.run(["xdotool", "key", key], check=True)

    def active_window_region(self) -> str | None:
        return None


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


BACKENDS: dict[str, DesktopBackend] = {
    "print": PrintBackend(),
    "hyprctl": HyprlandBackend(),
    "xdotool": XDoToolBackend(),
    "windows": WindowsBackend(),
}


def backend_names() -> tuple[str, ...]:
    return tuple(BACKENDS)


def get_backend(name: str) -> DesktopBackend:
    try:
        backend = BACKENDS[name]
    except KeyError as exc:
        raise SystemExit(f"Unsupported backend {name!r}") from exc
    if not backend.available():
        raise SystemExit(f"{name} is not installed")
    return backend


def selected_backend() -> str:
    if BACKENDS["windows"].available():
        return "windows"
    if BACKENDS["hyprctl"].available():
        return "hyprctl"
    if BACKENDS["xdotool"].available():
        return "xdotool"
    return "print"


def active_window_region() -> str | None:
    for backend in BACKENDS.values():
        if backend.available():
            region = backend.active_window_region()
            if region:
                return region
    return None


def capture_screenshot(path: Path, region: str | None) -> None:
    if sys.platform == "win32":
        capture_screenshot_windows(path, region)
        return

    if not shutil.which("grim"):
        raise SystemExit("grim is required for live screenshots. Use --image PATH instead.")
    if region is None:
        region = active_window_region()
    cmd = ["grim"]
    if region:
        cmd += ["-g", region]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)


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


def capture_screenshot_windows(path: Path, region: str | None) -> None:
    set_windows_dpi_aware()
    if region is None:
        region = BACKENDS["windows"].active_window_region()
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


def send_keys(keys: list[str], backend: str, delay: float) -> None:
    sender = get_backend(backend)
    if sender.name == "print":
        return

    for index, key in enumerate(keys):
        sender.send_key(key)
        if index < len(keys) - 1:
            time.sleep(delay)
