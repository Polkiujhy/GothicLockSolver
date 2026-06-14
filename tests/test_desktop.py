import sys

import pytest

from gothic_lock import desktop
from gothic_lock.desktop_backends import windows as windows_backend


def test_parse_region_accepts_grim_style_region():
    assert desktop.parse_region("100,200 640x480") == (100, 200, 740, 680)


def test_parse_region_accepts_comma_region():
    assert desktop.parse_region("100,200,640,480") == (100, 200, 740, 680)


def test_parse_region_rejects_bad_size():
    with pytest.raises(SystemExit):
        desktop.parse_region("100,200 0x480")


def test_windows_backend_is_registered():
    assert "windows" in desktop.backend_names()
    assert desktop.windows_virtual_key("w") == ord("W")
    assert desktop.windows_virtual_key("escape") == 0x1B


def test_selected_backend_prefers_windows_on_windows(monkeypatch):
    monkeypatch.setattr(windows_backend.sys, "platform", "win32")
    assert desktop.selected_backend() == "windows"


def test_windows_backend_availability_matches_platform():
    assert desktop.BACKENDS["windows"].available() is (sys.platform == "win32")


def test_capture_screenshot_uses_selected_backend(monkeypatch, tmp_path):
    calls = []

    class DummyBackend:
        name = "dummy"

        def available(self):
            return True

        def send_key(self, key):
            raise AssertionError("send_key should not be called")

        def active_window_region(self):
            return None

        def capture_screenshot(self, path, region):
            calls.append((path, region))

    monkeypatch.setitem(desktop.BACKENDS, "dummy", DummyBackend())
    monkeypatch.setattr(desktop, "selected_backend", lambda: "dummy")

    path = tmp_path / "shot.png"
    desktop.capture_screenshot(path, "1,2 3x4")

    assert calls == [(path, "1,2 3x4")]
