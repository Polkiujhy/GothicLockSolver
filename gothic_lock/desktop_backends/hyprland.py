"""Hyprland desktop backend."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from gothic_lock.desktop_backends.grim import capture_with_grim


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

    def capture_screenshot(self, path: Path, region: str | None) -> None:
        capture_with_grim(path, region or self.active_window_region())
