"""Desktop backend implementations."""

from gothic_lock.desktop_backends.base import DesktopBackend, parse_region
from gothic_lock.desktop_backends.hyprland import HyprlandBackend
from gothic_lock.desktop_backends.print_backend import PrintBackend
from gothic_lock.desktop_backends.windows import WindowsBackend, windows_virtual_key
from gothic_lock.desktop_backends.xdotool import XDoToolBackend

__all__ = [
    "DesktopBackend",
    "HyprlandBackend",
    "PrintBackend",
    "WindowsBackend",
    "XDoToolBackend",
    "parse_region",
    "windows_virtual_key",
]
