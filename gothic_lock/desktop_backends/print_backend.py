"""Dry-run desktop backend."""

from __future__ import annotations

from pathlib import Path


class PrintBackend:
    name = "print"

    def available(self) -> bool:
        return True

    def send_key(self, key: str) -> None:
        return None

    def active_window_region(self) -> str | None:
        return None

    def capture_screenshot(self, path: Path, region: str | None) -> None:
        raise SystemExit("No screenshot backend found. Use --image PATH instead.")
