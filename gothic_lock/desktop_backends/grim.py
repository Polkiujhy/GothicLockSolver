"""Screenshot capture through grim."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def capture_with_grim(path: Path, region: str | None) -> None:
    if not shutil.which("grim"):
        raise SystemExit("grim is required for live screenshots. Use --image PATH instead.")
    cmd = ["grim"]
    if region:
        cmd += ["-g", region]
    cmd.append(str(path))
    subprocess.run(cmd, check=True)
