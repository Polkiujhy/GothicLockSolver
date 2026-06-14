"""Stable facade for desktop-specific capture and keyboard backends."""

from __future__ import annotations

import time
from pathlib import Path

from gothic_lock.desktop_backends import (
    DesktopBackend,
    HyprlandBackend,
    PrintBackend,
    WindowsBackend,
    XDoToolBackend,
    parse_region,
    windows_virtual_key,
)


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
    backend = get_backend(selected_backend())
    if backend.name == "print":
        raise SystemExit("No screenshot backend found. Use --image PATH instead.")
    backend.capture_screenshot(path, region)


def send_keys(keys: list[str], backend: str, delay: float) -> None:
    sender = get_backend(backend)
    if sender.name == "print":
        return

    for index, key in enumerate(keys):
        sender.send_key(key)
        if index < len(keys) - 1:
            time.sleep(delay)
