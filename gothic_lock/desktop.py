"""Desktop-specific capture and keyboard backends.

The scanner and solver should not know whether input is sent through Hyprland,
X11, KDE Plasma, or Windows. Add future desktop providers here behind the same
small backend interface.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Protocol


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


BACKENDS: dict[str, DesktopBackend] = {
    "print": PrintBackend(),
    "hyprctl": HyprlandBackend(),
    "xdotool": XDoToolBackend(),
}


def get_backend(name: str) -> DesktopBackend:
    try:
        backend = BACKENDS[name]
    except KeyError as exc:
        raise SystemExit(f"Unsupported backend {name!r}") from exc
    if not backend.available():
        raise SystemExit(f"{name} is not installed")
    return backend


def selected_backend() -> str:
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
    if not shutil.which("grim"):
        raise SystemExit("grim is required for live screenshots. Use --image PATH instead.")
    if region is None:
        region = active_window_region()
    cmd = ["grim"]
    if region:
        cmd += ["-g", region]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)


def send_keys(keys: list[str], backend: str, delay: float) -> None:
    sender = get_backend(backend)
    if sender.name == "print":
        return

    for index, key in enumerate(keys):
        sender.send_key(key)
        if index < len(keys) - 1:
            time.sleep(delay)
