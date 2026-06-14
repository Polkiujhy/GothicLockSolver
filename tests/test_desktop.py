import sys

import pytest

from gothic_lock import desktop


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
    monkeypatch.setattr(desktop.sys, "platform", "win32")
    assert desktop.selected_backend() == "windows"


def test_windows_backend_availability_matches_platform():
    assert desktop.BACKENDS["windows"].available() is (sys.platform == "win32")
