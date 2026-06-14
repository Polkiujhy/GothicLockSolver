"""XDoTool keyboard backend."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from gothic_lock.desktop_backends.grim import capture_with_grim


class XDoToolBackend:
    name = "xdotool"

    def available(self) -> bool:
        return shutil.which("xdotool") is not None

    def send_key(self, key: str) -> None:
        subprocess.run(["xdotool", "key", key], check=True)

    def active_window_region(self) -> str | None:
        return None

    def capture_screenshot(self, path: Path, region: str | None) -> None:
        capture_with_grim(path, region)
