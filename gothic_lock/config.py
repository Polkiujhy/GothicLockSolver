"""Shared configuration for the Gothic lock solver."""

from __future__ import annotations

from pathlib import Path


VENV_PYTHON = Path.home() / ".local/share/gothic_lock_solver/venv/bin/python"

CAPTURE_DELAY = 2.0
LEARN_PAUSE = 0.45
NAV_PAUSE = 0.12
RESET_PAUSE = 1.0
KEY_DELAY = 0.25
STABLE_CAPTURE_PAUSE = 0.05
STABLE_CAPTURE_TRIES = 5
MAX_STAGE_STEPS = 60
MAX_RULE_ATTEMPTS_FACTOR = 10
BREAK_RECOVERY_PAUSE = 1.2

RESET_KEY = "r"
SELECT_FIRST_KEY = "s"
SELECT_NEXT_KEY = "w"
SELECT_PREV_KEY = "s"
PIN_UP_KEY = "a"
PIN_DOWN_KEY = "d"

HOLES = 7
TARGET = 4

PERF_LOG_PATH = Path.home() / ".local/state/gothic_lock_solver/timings.jsonl"
PERF_SLOW_PATH = PERF_LOG_PATH.with_name("slow_points.txt")
PERF_SUMMARY_EVENTS = 800
PERF_SUMMARY_LIMIT = 8
