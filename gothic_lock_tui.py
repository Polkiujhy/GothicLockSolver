#!/usr/bin/env python3
"""Three-action TUI for the Gothic 1 Remake lock solver."""

from __future__ import annotations

import curses
import json
import os
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path

from gothic_lock.config import (
    BREAK_RECOVERY_PAUSE,
    CAPTURE_DELAY,
    HOLES,
    KEY_DELAY,
    LEARN_PAUSE,
    MAX_RULE_ATTEMPTS_FACTOR,
    MAX_STAGE_STEPS,
    NAV_PAUSE,
    PERF_LOG_PATH,
    PERF_SLOW_PATH,
    PERF_SUMMARY_EVENTS,
    PERF_SUMMARY_LIMIT,
    PIN_DOWN_KEY,
    PIN_UP_KEY,
    RESET_KEY,
    RESET_PAUSE,
    SELECT_FIRST_KEY,
    SELECT_NEXT_KEY,
    SELECT_PREV_KEY,
    STABLE_CAPTURE_PAUSE,
    STABLE_CAPTURE_TRIES,
    TARGET,
    VENV_PYTHON,
)
from gothic_lock.desktop import selected_backend as detect_desktop_backend
from gothic_lock.scanner import RuleScanLogic

if (
    __name__ == "__main__"
    and os.environ.get("GOTHIC_LOCK_NO_VENV") != "1"
    and VENV_PYTHON.exists()
    and Path(sys.executable).resolve() != VENV_PYTHON.resolve()
):
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), *sys.argv])

from gothic_lock import desktop, solver, vision
from PIL import Image


@dataclass(frozen=True)
class Button:
    label: str
    help: str
    action: str


class LockTui(RuleScanLogic):
    def __init__(self, stdscr: curses.window):
        self.stdscr = stdscr
        self.selected = 0
        self.status = "Choose an action. The game must show the lock minigame when capture starts."
        self.result_lines: list[str] = []
        self.detected_pins: list[int] | None = None
        self.learned_rules: dict[int, dict[int, int]] | None = None
        self.learned_rules_text: str | None = None
        self.plate_count: int | None = None
        self.last_image: Path | None = None
        self.rule_start_pins: list[int] | None = None
        self.rule_start_pick_signature: tuple[int, ...] | None = None
        self.last_pick_signature: tuple[int, ...] | None = None
        self.last_selected_plate: int | None = None
        self.blocked_edge_moves: set[tuple[int, str, frozenset[tuple[int, int]]]] = set()
        self.run_id = f"{int(time.time())}"
        self.buttons = [
            Button("Auto Pin Identify", "Capture the lock and display detected pin holes.", "pins"),
            Button("Auto Rule Detection", "Find safe pins, test each plate, then display same/opposite rules.", "rules"),
            Button("Auto Solve", "Reset, detect pins, send the solution keys, and display the move/key set.", "solve"),
            Button("Auto Detect + Solve", "Learn this lock's rules, reset, solve, and send the solution keys.", "rules_solve"),
        ]
        self.result_lines = self.wrap_result(self.timing_summary_lines(limit=5))

    def run(self) -> None:
        curses.curs_set(0)
        self.stdscr.keypad(True)
        while True:
            self.draw()
            key = self.stdscr.getch()
            if key in (ord("q"), ord("Q"), 27):
                return
            if key in (curses.KEY_UP, ord("k")):
                self.selected = max(0, self.selected - 1)
            elif key in (curses.KEY_DOWN, ord("j"), 9):
                self.selected = min(len(self.buttons) - 1, self.selected + 1)
            elif key in (10, 13, ord(" ")):
                self.run_selected()
            elif ord("1") <= key <= ord(str(min(len(self.buttons), 9))):
                self.selected = key - ord("1")
                self.run_selected()

    def draw(self) -> None:
        self.stdscr.erase()
        height, width = self.stdscr.getmaxyx()
        self.addstr(0, 0, "Gothic 1 Remake Lock Solver", curses.A_BOLD)
        self.addstr(1, 0, f"Up/Down select  Enter run  1-{len(self.buttons)} run action  Q quit")
        self.addstr(2, 0, "Actions always auto-detect pins from screenshots. Rules are learned after staging pins away from edges.")

        for index, button in enumerate(self.buttons):
            y = 4 + index * 2
            attr = curses.A_REVERSE if index == self.selected else curses.A_NORMAL
            self.addstr(y, 2, f"[ {index + 1}. {button.label} ]"[: width - 4], attr)
            self.addstr(y + 1, 6, button.help[: width - 8], curses.A_DIM)

        state_y = 4 + len(self.buttons) * 2 + 1
        self.addstr(state_y, 0, self.status[: width - 1], curses.A_BOLD)
        state_y += 2
        if self.plate_count:
            self.addstr(state_y, 0, f"plates: {self.plate_count}"[: width - 1])
            state_y += 1
        if self.detected_pins:
            self.addstr(state_y, 0, f"last pins: {','.join(str(pin) for pin in self.detected_pins)}"[: width - 1])
            state_y += 1
        if self.learned_rules_text:
            self.addstr(state_y, 0, f"rules: {self.learned_rules_text}"[: width - 1])
            state_y += 1
        self.addstr(state_y, 0, f"timing log: {PERF_LOG_PATH}"[: width - 1], curses.A_DIM)
        state_y += 1

        result_top = state_y + 1
        for offset, line in enumerate(self.result_lines):
            y = result_top + offset
            if y >= height:
                break
            self.addstr(y, 0, line[: width - 1])
        self.stdscr.refresh()

    def addstr(self, y: int, x: int, text: str, attr: int = curses.A_NORMAL) -> None:
        try:
            self.stdscr.addstr(y, x, text, attr)
        except curses.error:
            pass

    def timed_call(self, event: str, func, **fields):
        start = time.perf_counter()
        try:
            result = func()
        except BaseException as exc:
            self.log_timing(event, time.perf_counter() - start, ok=False, error=type(exc).__name__, **fields)
            raise
        self.log_timing(event, time.perf_counter() - start, ok=True, **fields)
        return result

    def timed_sleep(self, event: str, seconds: float, **fields) -> None:
        start = time.perf_counter()
        time.sleep(seconds)
        self.log_timing(event, time.perf_counter() - start, ok=True, requested=seconds, **fields)

    def log_timing(self, event: str, duration: float, ok: bool = True, **fields) -> None:
        payload = {
            "ts": round(time.time(), 3),
            "run_id": self.run_id,
            "event": event,
            "seconds": round(duration, 4),
            "ok": ok,
        }
        for key, value in fields.items():
            if isinstance(value, Path):
                payload[key] = str(value)
            elif isinstance(value, (str, int, float, bool)) or value is None:
                payload[key] = value
            elif isinstance(value, (list, tuple)):
                payload[key] = list(value)
            else:
                payload[key] = repr(value)
        try:
            PERF_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with PERF_LOG_PATH.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, sort_keys=True) + "\n")
        except OSError:
            pass

    def timing_summary_lines(self, limit: int = PERF_SUMMARY_LIMIT) -> list[str]:
        if not PERF_LOG_PATH.exists():
            return [
                f"Timing log will be saved to: {PERF_LOG_PATH}",
                "Run a few locks, then this area will show recent slow points.",
            ]
        try:
            raw_lines = PERF_LOG_PATH.read_text(encoding="utf-8").splitlines()[-PERF_SUMMARY_EVENTS:]
        except OSError:
            return [f"Could not read timing log: {PERF_LOG_PATH}"]

        groups: dict[str, dict[str, float | int]] = {}
        event_count = 0
        for raw in raw_lines:
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            event = str(entry.get("event", "unknown"))
            seconds = float(entry.get("seconds", 0.0))
            ok = bool(entry.get("ok", True))
            stats = groups.setdefault(event, {"count": 0, "total": 0.0, "max": 0.0, "fail": 0})
            stats["count"] = int(stats["count"]) + 1
            stats["total"] = float(stats["total"]) + seconds
            stats["max"] = max(float(stats["max"]), seconds)
            if not ok:
                stats["fail"] = int(stats["fail"]) + 1
            event_count += 1

        if not groups:
            return [f"Timing log has no readable events yet: {PERF_LOG_PATH}"]

        ranked = sorted(groups.items(), key=lambda item: (float(item[1]["total"]), float(item[1]["max"])), reverse=True)
        lines = [
            f"Recent slow points from {event_count} timing events:",
            f"summary file: {PERF_SLOW_PATH}",
        ]
        for event, stats in ranked[:limit]:
            count = int(stats["count"])
            total = float(stats["total"])
            avg = total / max(1, count)
            fail = int(stats["fail"])
            suffix = f" fail={fail}" if fail else ""
            lines.append(
                f"{event}: total {total:.2f}s avg {avg:.2f}s max {float(stats['max']):.2f}s n={count}{suffix}"
            )
        return lines

    def save_slow_points(self) -> None:
        lines = self.timing_summary_lines()
        try:
            PERF_SLOW_PATH.parent.mkdir(parents=True, exist_ok=True)
            PERF_SLOW_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            pass

    def run_selected(self) -> None:
        action = self.buttons[self.selected].action
        if action == "pins":
            self.auto_identify_pins()
        elif action == "rules":
            self.auto_detect_rules()
        elif action == "solve":
            self.auto_solve()
        elif action == "rules_solve":
            self.auto_detect_rules_and_solve()

    def auto_identify_pins(self) -> None:
        action_start = time.perf_counter()
        try:
            image_path = self.capture_live("identify")
            count = self.timed_call(
                "infer_plate_count",
                lambda: vision.infer_plate_count(image_path, vision.parse_roi(None)),
                action="identify",
                image=image_path,
            )
            pins = self.timed_call(
                "detect_pins",
                lambda: vision.detect_pins(image_path, count, HOLES, vision.parse_roi(None), None),
                action="identify",
                image=image_path,
                count=count,
            )
            self.plate_count = count
            self.detected_pins = pins
            self.last_image = image_path
            self.result_lines = self.wrap_result(
                [
                    "Auto Pin Identify",
                    f"plates: {count}",
                    f"pins: {','.join(str(pin) for pin in pins)}",
                    f"image: {image_path}",
                ]
            )
            self.status = "Detected pins."
            self.log_timing("auto_identify_pins", time.perf_counter() - action_start, ok=True, plates=count)
            self.save_slow_points()
        except (Exception, SystemExit) as exc:
            self.log_timing(
                "auto_identify_pins",
                time.perf_counter() - action_start,
                ok=False,
                error=type(exc).__name__,
            )
            self.save_slow_points()
            self.status = f"Pin identify failed: {exc}"
            self.result_lines = []

    def auto_detect_rules(self) -> None:
        action_start = time.perf_counter()
        try:
            backend = self.selected_backend()
            if backend == "print":
                raise ValueError("No key backend found. Need a supported desktop backend for rule detection.")

            curses.def_prog_mode()
            curses.endwin()
            learned_same: dict[int, list[int]]
            learned_opp: dict[int, list[int]]
            scan_keys: list[str]
            bad_moves: list[str]
            final_pins: list[int]
            baseline_path = Path(tempfile.gettempdir()) / "gothic_lock_rules_baseline.png"
            try:
                print("Auto Rule Detection", flush=True)
                print(f"Focus the lock. Starting in {CAPTURE_DELAY:g}s.", flush=True)
                self.timed_sleep("focus_delay", CAPTURE_DELAY, action="rules")
                self.timed_call(
                    "capture_screenshot",
                    lambda: desktop.capture_screenshot(baseline_path, None),
                    action="rules",
                    name="baseline",
                    image=baseline_path,
                )
                count = self.timed_call(
                    "infer_plate_count",
                    lambda: vision.infer_plate_count(baseline_path, vision.parse_roi(None)),
                    action="rules",
                    image=baseline_path,
                )
                learned_same = {plate: [] for plate in range(1, count + 1)}
                learned_opp = {plate: [] for plate in range(1, count + 1)}

                self.last_selected_plate = 1
                pins = self.capture_pins_stable("stage_start", count)
                self.rule_start_pins = pins[:]
                self.rule_start_pick_signature = self.last_pick_signature
                self.blocked_edge_moves.clear()
                print(f"Start pins: {pins}", flush=True)
                learned_same, learned_opp, scan_keys, final_pins, bad_moves = self.learn_rules_by_scan(
                    pins, count, backend, 1
                )
                print(f"Final scan pins: {final_pins}", flush=True)
                print(f"Scan keys: {' '.join(scan_keys) or '-'}", flush=True)
                self.reset_and_home(count, backend)
            finally:
                curses.reset_prog_mode()
                curses.curs_set(0)
                self.stdscr.clear()

            rules_text = self.rules_text_from_learned(learned_same, learned_opp)
            self.plate_count = count
            self.learned_rules_text = rules_text
            self.learned_rules = solver.parse_rules(rules_text)
            lines = [
                "Auto Rule Detection",
                f"plates: {count}",
                f"final scan pins: {','.join(str(pin) for pin in final_pins)}",
                f"scan keys: {' '.join(scan_keys) or '-'}",
                "rules:",
            ]
            for plate in range(1, count + 1):
                same = ",".join(str(item) for item in learned_same[plate]) or "-"
                opposite = ",".join(str(item) for item in learned_opp[plate]) or "-"
                lines.append(f"plate {plate}: same {same}; opposite {opposite}")
            lines.append(f"compact: {rules_text}")
            if bad_moves:
                lines.append("bad/unsafe moves remembered:")
                lines.extend(bad_moves[-8:])
            lines.extend(["", *self.timing_summary_lines(limit=5)])
            self.result_lines = self.wrap_result(lines)
            self.status = "Learned rules."
            self.log_timing(
                "auto_detect_rules",
                time.perf_counter() - action_start,
                ok=True,
                plates=count,
                scan_key_count=len(scan_keys),
            )
            self.save_slow_points()
        except (Exception, SystemExit) as exc:
            self.log_timing(
                "auto_detect_rules",
                time.perf_counter() - action_start,
                ok=False,
                error=type(exc).__name__,
            )
            self.save_slow_points()
            self.status = f"Rule detection failed: {exc}"
            self.result_lines = self.wrap_result(["Auto Rule Detection failed", str(exc)])

    def auto_solve(self) -> None:
        action_start = time.perf_counter()
        try:
            if self.learned_rules is None:
                raise ValueError("Run Auto Rule Detection first.")
            backend = self.selected_backend()
            if backend == "print":
                raise ValueError("No key backend found. Need a supported desktop backend to reset/home before solving.")
            count = self.plate_count or max(self.learned_rules)

            curses.def_prog_mode()
            curses.endwin()
            image_path = Path(tempfile.gettempdir()) / "gothic_lock_solve.png"
            try:
                print("Auto Solve", flush=True)
                print(f"Focus the lock. Reset/capture starts in {CAPTURE_DELAY:g}s.", flush=True)
                self.timed_sleep("focus_delay", CAPTURE_DELAY, action="solve")
                self.reset_and_home(count, backend)
                self.timed_call(
                    "capture_screenshot",
                    lambda: desktop.capture_screenshot(image_path, None),
                    action="solve",
                    image=image_path,
                )

                pins = self.timed_call(
                    "detect_pins",
                    lambda: vision.detect_pins(image_path, count, HOLES, vision.parse_roi(None), None),
                    action="solve",
                    image=image_path,
                    count=count,
                )
                keys, moves = self.timed_call(
                    "solve_key_path",
                    lambda: solver.solve_key_path(
                        pins,
                        self.learned_rules,
                        HOLES,
                        TARGET,
                        1,
                        SELECT_NEXT_KEY,
                        SELECT_PREV_KEY,
                        PIN_UP_KEY,
                        PIN_DOWN_KEY,
                    ),
                    action="solve",
                    count=count,
                )
                final_pins = self.timed_call(
                    "simulate_moves",
                    lambda: self.simulate_moves(pins, moves, self.learned_rules),
                    action="solve",
                    move_count=len(moves),
                )
                if final_pins != [TARGET] * count:
                    raise ValueError(f"Solver verification failed: {pins} -> {final_pins}")

                print(f"pins: {','.join(str(pin) for pin in pins)}", flush=True)
                print(f"moves: {self.condensed_plate_key_moves(moves)}", flush=True)
                print(f"keys: {' '.join(keys)}", flush=True)
                print(f"verified final pins: {','.join(str(pin) for pin in final_pins)}", flush=True)
                print(f"Sending {len(keys)} keys at {KEY_DELAY:.2f}s/key. Keep the lock focused.", flush=True)
                self.timed_call(
                    "send_solution_keys",
                    lambda: desktop.send_keys(keys, backend, KEY_DELAY),
                    action="solve",
                    key_count=len(keys),
                    key_delay=KEY_DELAY,
                    backend=backend,
                )
            finally:
                curses.reset_prog_mode()
                curses.curs_set(0)
                self.stdscr.clear()

            self.detected_pins = pins
            self.last_image = image_path
            self.result_lines = self.wrap_result(
                [
                    "Auto Solve",
                    f"pins: {','.join(str(pin) for pin in pins)}",
                    f"moves: {self.condensed_plate_key_moves(moves)}",
                    f"keys: {' '.join(keys)}",
                    f"verified final pins: {','.join(str(pin) for pin in final_pins)}",
                    f"sent keys: {len(keys)}",
                    f"image: {image_path}",
                    "",
                    *self.timing_summary_lines(limit=5),
                ]
            )
            self.status = "Solved and sent solution keys."
            self.log_timing(
                "auto_solve",
                time.perf_counter() - action_start,
                ok=True,
                plates=count,
                key_count=len(keys),
            )
            self.save_slow_points()
        except (Exception, SystemExit) as exc:
            self.log_timing(
                "auto_solve",
                time.perf_counter() - action_start,
                ok=False,
                error=type(exc).__name__,
            )
            self.save_slow_points()
            self.status = f"Solve failed: {exc}"
            self.result_lines = []

    def auto_detect_rules_and_solve(self) -> None:
        action_start = time.perf_counter()
        try:
            backend = self.selected_backend()
            if backend == "print":
                raise ValueError("No key backend found. Need a supported desktop backend for rule detection and solving.")

            curses.def_prog_mode()
            curses.endwin()
            try:
                print("Auto Detect + Solve", flush=True)
                print(f"Focus the lock. Starting in {CAPTURE_DELAY:g}s.", flush=True)
                self.timed_sleep("focus_delay", CAPTURE_DELAY, action="rules_solve")
                (
                    count,
                    learned_same,
                    learned_opp,
                    scan_keys,
                    final_scan_pins,
                    bad_moves,
                    rules_text,
                    rules,
                ) = self.detect_rules_once(backend, "rules_solve")
                pins, keys, moves, final_pins, image_path = self.solve_once(
                    backend,
                    count,
                    rules,
                    "rules_solve",
                    reset_first=False,
                )
            finally:
                curses.reset_prog_mode()
                curses.curs_set(0)
                self.stdscr.clear()

            self.plate_count = count
            self.learned_rules_text = rules_text
            self.learned_rules = rules
            self.detected_pins = pins
            self.last_image = image_path
            lines = [
                "Auto Detect + Solve",
                f"plates: {count}",
                f"final scan pins: {','.join(str(pin) for pin in final_scan_pins)}",
                f"solve pins: {','.join(str(pin) for pin in pins)}",
                f"moves: {self.condensed_plate_key_moves(moves)}",
                f"keys: {' '.join(keys)}",
                f"verified final pins: {','.join(str(pin) for pin in final_pins)}",
                f"sent keys: {len(keys)}",
                "rules:",
            ]
            for plate in range(1, count + 1):
                same = ",".join(str(item) for item in learned_same[plate]) or "-"
                opposite = ",".join(str(item) for item in learned_opp[plate]) or "-"
                lines.append(f"plate {plate}: same {same}; opposite {opposite}")
            lines.append(f"compact: {rules_text}")
            lines.append(f"scan keys: {' '.join(scan_keys) or '-'}")
            if bad_moves:
                lines.append("bad/unsafe moves remembered:")
                lines.extend(bad_moves[-8:])
            lines.extend(["", *self.timing_summary_lines(limit=5)])
            self.result_lines = self.wrap_result(lines)
            self.status = "Learned rules, solved, and sent solution keys."
            self.log_timing(
                "auto_detect_rules_and_solve",
                time.perf_counter() - action_start,
                ok=True,
                plates=count,
                scan_key_count=len(scan_keys),
                solve_key_count=len(keys),
            )
            self.save_slow_points()
        except (Exception, SystemExit) as exc:
            self.log_timing(
                "auto_detect_rules_and_solve",
                time.perf_counter() - action_start,
                ok=False,
                error=type(exc).__name__,
            )
            self.save_slow_points()
            self.status = f"Detect + solve failed: {exc}"
            self.result_lines = self.wrap_result(["Auto Detect + Solve failed", str(exc)])

    def detect_rules_once(
        self,
        backend: str,
        action: str,
    ) -> tuple[
        int,
        dict[int, list[int]],
        dict[int, list[int]],
        list[str],
        list[int],
        list[str],
        str,
        dict[int, dict[int, int]],
    ]:
        baseline_path = Path(tempfile.gettempdir()) / "gothic_lock_rules_baseline.png"
        print("Rule detection", flush=True)
        self.timed_call(
            "capture_screenshot",
            lambda: desktop.capture_screenshot(baseline_path, None),
            action=action,
            name="baseline",
            image=baseline_path,
        )
        count = self.timed_call(
            "infer_plate_count",
            lambda: vision.infer_plate_count(baseline_path, vision.parse_roi(None)),
            action=action,
            image=baseline_path,
        )
        self.last_selected_plate = 1
        pins = self.capture_pins_stable("stage_start", count)
        self.rule_start_pins = pins[:]
        self.rule_start_pick_signature = self.last_pick_signature
        self.blocked_edge_moves.clear()
        print(f"Start pins: {pins}", flush=True)
        learned_same, learned_opp, scan_keys, final_pins, bad_moves = self.learn_rules_by_scan(
            pins, count, backend, 1
        )
        print(f"Final scan pins: {final_pins}", flush=True)
        print(f"Scan keys: {' '.join(scan_keys) or '-'}", flush=True)
        self.reset_and_home(count, backend)
        rules_text = self.rules_text_from_learned(learned_same, learned_opp)
        rules = solver.parse_rules(rules_text)
        return count, learned_same, learned_opp, scan_keys, final_pins, bad_moves, rules_text, rules

    def solve_once(
        self,
        backend: str,
        count: int,
        rules: dict[int, dict[int, int]],
        action: str,
        reset_first: bool,
    ) -> tuple[list[int], list[str], list[tuple[int, str]], list[int], Path]:
        image_path = Path(tempfile.gettempdir()) / f"gothic_lock_{action}_solve.png"
        print("Solving", flush=True)
        if reset_first:
            self.reset_and_home(count, backend)
        self.timed_call(
            "capture_screenshot",
            lambda: desktop.capture_screenshot(image_path, None),
            action=action,
            image=image_path,
        )
        pins = self.timed_call(
            "detect_pins",
            lambda: vision.detect_pins(image_path, count, HOLES, vision.parse_roi(None), None),
            action=action,
            image=image_path,
            count=count,
        )
        keys, moves = self.timed_call(
            "solve_key_path",
            lambda: solver.solve_key_path(
                pins,
                rules,
                HOLES,
                TARGET,
                1,
                SELECT_NEXT_KEY,
                SELECT_PREV_KEY,
                PIN_UP_KEY,
                PIN_DOWN_KEY,
            ),
            action=action,
            count=count,
        )
        final_pins = self.timed_call(
            "simulate_moves",
            lambda: self.simulate_moves(pins, moves, rules),
            action=action,
            move_count=len(moves),
        )
        if final_pins != [TARGET] * count:
            raise ValueError(f"Solver verification failed: {pins} -> {final_pins}")

        print(f"pins: {','.join(str(pin) for pin in pins)}", flush=True)
        print(f"moves: {self.condensed_plate_key_moves(moves)}", flush=True)
        print(f"keys: {' '.join(keys)}", flush=True)
        print(f"verified final pins: {','.join(str(pin) for pin in final_pins)}", flush=True)
        print(f"Sending {len(keys)} keys at {KEY_DELAY:.2f}s/key. Keep the lock focused.", flush=True)
        self.timed_call(
            "send_solution_keys",
            lambda: desktop.send_keys(keys, backend, KEY_DELAY),
            action=action,
            key_count=len(keys),
            key_delay=KEY_DELAY,
            backend=backend,
        )
        return pins, keys, moves, final_pins, image_path

    def learn_rules_by_scan(
        self,
        pins: list[int],
        count: int,
        backend: str,
        selected: int,
    ) -> tuple[dict[int, list[int]], dict[int, list[int]], list[str], list[int], list[str]]:
        learned_same: dict[int, list[int]] = {}
        learned_opp: dict[int, list[int]] = {}
        scan_keys: list[str] = []
        bad_moves: list[str] = []
        current = pins[:]
        current_selected = selected
        attempted: set[tuple[tuple[int, ...], int, str]] = set()
        current_needs_sync = False

        for step in range(1, MAX_STAGE_STEPS + 1):
            if len(learned_same) == count:
                return learned_same, learned_opp, scan_keys, current, bad_moves

            if current_needs_sync:
                if self.edge_signature(current):
                    print(f"scan {step}: trusting predicted edge pins {current}", flush=True)
                else:
                    try:
                        synced = self.capture_pins_sync(f"scan_{step}_predicted_sync", count, current)
                    except (Exception, SystemExit) as exc:
                        event = f"scan {step}: predicted sync failed: {exc}"
                        bad_moves.append(event)
                        print(event, flush=True)
                        current, current_selected = self.recover_current_state(
                            count, backend, f"scan_recover_sync_{step}"
                        )
                        current_needs_sync = False
                        continue
                    if synced != current:
                        print(f"scan {step}: synced pins {current} -> {synced}", flush=True)
                        current = synced
                current_needs_sync = False

            moved = False

            for plate, move_key in self.scan_action_candidates(current, count, learned_same, learned_opp):
                if self.is_blocked_edge_move(plate, move_key, current):
                    event = (
                        f"scan {step}: skipped known unsafe plate {plate} {move_key.upper()} "
                        f"from edges {sorted(self.edge_signature(current))}"
                    )
                    bad_moves.append(event)
                    print(event, flush=True)
                    continue

                action_id = (tuple(current), plate, move_key)
                if action_id in attempted:
                    continue
                attempted.add(action_id)

                nav_keys = self.go_to_plate(plate, count, backend, current_selected)
                scan_keys.extend(nav_keys)
                current_selected = plate

                before = current[:]
                predicted_after: list[int] | None = None

                if plate not in learned_same:
                    if self.is_blocked_edge_move(plate, move_key, before):
                        event = (
                            f"scan {step}: skipped known unsafe plate {plate} {move_key.upper()} "
                            f"after sync from edges {sorted(self.edge_signature(before))}"
                        )
                        bad_moves.append(event)
                        print(event, flush=True)
                        continue

                if plate in learned_same:
                    blockers = self.known_move_blockers(plate, move_key, before, learned_same, learned_opp)
                    if blockers:
                        event = (
                            f"scan {step}: skipped rule-unsafe plate {plate} {move_key.upper()} "
                            f"from {before}; would push {blockers}"
                        )
                        bad_moves.append(event)
                        print(event, flush=True)
                        continue
                    predicted = self.predict_known_move(plate, move_key, before, learned_same, learned_opp)
                    if predicted is None or self.known_helper_score(before, predicted) <= 0:
                        continue
                    predicted_after = predicted

                if not self.move_key_in_bounds(move_key, before[plate - 1]):
                    continue

                before_pick_signature = self.last_pick_signature
                self.send_keys_and_wait([move_key], backend)
                scan_keys.append(move_key)

                if predicted_after is not None:
                    print(
                        f"scan {step}: helper plate {plate} {move_key.upper()} {before} -> {predicted_after}",
                        flush=True,
                    )
                    current = predicted_after
                    current_needs_sync = True
                    moved = True
                    break

                try:
                    after = self.capture_after_move_quick(
                        f"scan_{step}_{plate}_{move_key}_after",
                        count,
                        plate,
                        move_key,
                        before,
                        before_pick_signature,
                    )
                except (Exception, SystemExit) as exc:
                    self.remember_blocked_edge_move(plate, move_key, before)
                    event = (
                        f"scan {step}: plate {plate} {move_key.upper()} probably broke/reset "
                        f"from {before}; capture failed: {exc}"
                    )
                    bad_moves.append(event)
                    print(event, flush=True)
                    current, current_selected = self.recover_current_state(
                        count, backend, f"scan_recover_{step}", after_break=True
                    )
                    current_needs_sync = False
                    moved = True
                    break

                if self.pick_signature_changed(before_pick_signature, self.last_pick_signature):
                    self.remember_blocked_edge_move(plate, move_key, before)
                    event = f"scan {step}: plate {plate} {move_key.upper()} broke a pick {before} -> {after}"
                    bad_moves.append(event)
                    print(event, flush=True)
                    current, current_selected = self.recover_current_state(
                        count, backend, f"scan_recover_{step}", after_break=True
                    )
                    current_needs_sync = False
                    moved = True
                    break

                if after == before:
                    if self.edge_signature(before):
                        self.remember_blocked_edge_move(plate, move_key, before)
                    event = f"scan {step}: plate {plate} {move_key.upper()} no visible change from {before}"
                    bad_moves.append(event)
                    print(event, flush=True)
                    continue

                try:
                    self.validate_observed_move(plate, move_key, before, after)
                except ValueError as exc:
                    if self.edge_signature(before):
                        self.remember_blocked_edge_move(plate, move_key, before)
                    event = f"scan {step}: bad plate {plate} {move_key.upper()} {before} -> {after}: {exc}"
                    bad_moves.append(event)
                    print(event, flush=True)
                    current, current_selected = self.recover_current_state(count, backend, f"scan_recover_{step}")
                    current_needs_sync = False
                    moved = True
                    break

                same, opposite = self.rule_from_transition(plate, before, after)
                learned_new_rule = plate not in learned_same
                if plate not in learned_same:
                    learned_same[plate] = same
                    learned_opp[plate] = opposite
                    print(
                        f"Plate {plate}: {move_key.upper()} {before} -> {after}; "
                        f"same={same or '-'} opposite={opposite or '-'}",
                        flush=True,
                    )
                elif learned_same[plate] != same or learned_opp[plate] != opposite:
                    event = (
                        f"scan {step}: plate {plate} rule changed; kept "
                        f"same={learned_same[plate] or '-'} opposite={learned_opp[plate] or '-'}, "
                        f"saw same={same or '-'} opposite={opposite or '-'}"
                    )
                    bad_moves.append(event)
                    print(event, flush=True)

                if learned_new_rule and self.should_rollback_scan_move(before, after):
                    undo_key = self.inverse_move_key(move_key)
                    self.send_keys_and_wait([undo_key], backend)
                    scan_keys.append(undo_key)
                    print(
                        f"scan {step}: rolled back risky plate {plate} {undo_key.upper()} "
                        f"{after} -> {before} (predicted)",
                        flush=True,
                    )
                    current = before
                    current_needs_sync = True
                    moved = True
                    break

                current = after
                current_needs_sync = False
                moved = True
                break

            if not moved:
                missing = [plate for plate in range(1, count + 1) if plate not in learned_same]
                raise ValueError(
                    f"Rule scan got stuck at pins {current}; missing plates {missing}; "
                    f"bad moves: {bad_moves[-8:]}"
                )

        missing = [plate for plate in range(1, count + 1) if plate not in learned_same]
        raise ValueError(
            f"Rule scan reached {MAX_STAGE_STEPS} steps at pins {current}; missing plates {missing}; "
            f"bad moves: {bad_moves[-8:]}"
        )

    def stage_safe_state(
        self,
        pins: list[int],
        count: int,
        backend: str,
        selected: int,
    ) -> tuple[list[str], list[int], int, list[str]]:
        staging_keys: list[str] = []
        bad_moves: list[str] = []
        current = pins[:]
        current_selected = selected
        attempted: set[tuple[tuple[int, ...], int, str]] = set()

        for step in range(1, MAX_STAGE_STEPS + 1):
            if self.all_pins_safe(current):
                return staging_keys, current, current_selected, bad_moves

            moved = False
            for target_plate, move_key in self.stage_candidates(current, current_selected):
                action_id = (tuple(current), target_plate, move_key)
                if action_id in attempted:
                    continue
                if self.is_blocked_edge_move(target_plate, move_key, current):
                    event = (
                        f"stage {step}: skipped known unsafe plate {target_plate} {move_key.upper()} from edges "
                        f"{sorted(self.edge_signature(current))}"
                    )
                    bad_moves.append(event)
                    print(event, flush=True)
                    continue
                attempted.add(action_id)

                nav_keys = self.go_to_plate(target_plate, count, backend, current_selected)
                staging_keys.extend(nav_keys)
                current_selected = target_plate

                before = current[:]
                before_pick_signature = self.last_pick_signature
                before_score = self.safety_score(before)
                self.send_keys_and_wait([move_key], backend)
                staging_keys.append(move_key)
                try:
                    after = self.capture_pins_stable(f"stage_{step}_{target_plate}_{move_key}", count)
                except (Exception, SystemExit) as exc:
                    self.remember_blocked_edge_move(target_plate, move_key, before)
                    event = (
                        f"stage {step}: plate {target_plate} {move_key.upper()} probably broke/reset "
                        f"from {before}; capture failed: {exc}"
                    )
                    bad_moves.append(event)
                    print(event, flush=True)
                    current, current_selected = self.recover_current_state(
                        count, backend, f"stage_recover_{step}", after_break=True
                    )
                    moved = True
                    break
                after_pick_signature = self.last_pick_signature
                if self.pick_signature_changed(before_pick_signature, after_pick_signature):
                    self.remember_blocked_edge_move(target_plate, move_key, before)
                    event = (
                        f"stage {step}: plate {target_plate} {move_key.upper()} broke a pick "
                        f"{before} -> {after}"
                    )
                    bad_moves.append(event)
                    print(event, flush=True)
                    current, current_selected = self.recover_current_state(
                        count, backend, f"stage_recover_{step}", after_break=True
                    )
                    moved = True
                    break
                if after == before:
                    if self.edge_signature(before):
                        self.remember_blocked_edge_move(target_plate, move_key, before)
                    bad_moves.append(
                        f"stage {step}: plate {target_plate} {move_key.upper()} no visible change from {before}"
                    )
                    if self.edge_signature(before):
                        moved = True
                        break
                    continue

                try:
                    self.validate_observed_move(target_plate, move_key, before, after)
                except ValueError as exc:
                    if self.edge_signature(before):
                        self.remember_blocked_edge_move(target_plate, move_key, before)
                    if self.looks_like_break_reset(before, after):
                        event = f"stage {step}: plate {target_plate} {move_key.upper()} broke/reset {before} -> {after}"
                    else:
                        event = f"stage {step}: bad plate {target_plate} {move_key.upper()} {before} -> {after}: {exc}"
                    bad_moves.append(event)
                    print(event, flush=True)
                    current, current_selected = self.recover_current_state(
                        count,
                        backend,
                        f"stage_recover_{step}",
                        after_break=self.looks_like_break_reset(before, after),
                    )
                    moved = True
                    break

                after_score = self.safety_score(after)
                print(
                    f"Stage {step}: plate {target_plate} {move_key.upper()} {before} -> {after} "
                    f"score {before_score}->{after_score}",
                    flush=True,
                )
                if self.all_pins_safe(after):
                    current = after
                    moved = True
                    break

                if after_score <= before_score:
                    undo_key = self.inverse_move_key(move_key)
                    rollback_before_pick_signature = after_pick_signature
                    self.send_keys_and_wait([undo_key], backend)
                    staging_keys.append(undo_key)
                    try:
                        undo_after = self.capture_pins_stable(f"stage_{step}_{target_plate}_undo", count)
                        if self.pick_signature_changed(rollback_before_pick_signature, self.last_pick_signature):
                            raise ValueError(f"rollback broke a pick: {after} -> {undo_after}")
                        self.validate_observed_move(target_plate, undo_key, after, undo_after)
                    except (Exception, SystemExit) as exc:
                        event = (
                            f"stage {step}: rollback failed after plate {target_plate} {move_key.upper()} "
                            f"{after}: {exc}"
                        )
                        bad_moves.append(event)
                        print(event, flush=True)
                        current, current_selected = self.recover_current_state(count, backend, f"stage_recover_{step}")
                        moved = True
                        break
                    current = undo_after
                    moved = True
                    print(
                        f"Stage {step}: rolled back plate {target_plate} {undo_key.upper()} {after} -> {undo_after}",
                        flush=True,
                    )
                    break

                current = after
                moved = True
                break

            if not moved:
                raise ValueError(
                    f"Could not move boundary pins to a safe state from {current}. "
                    f"Remembered bad moves: {bad_moves[-5:]}"
                )

        raise ValueError(
            f"Could not reach a safe staging state after {len(staging_keys)} keys; "
            f"last pins {current}; remembered bad moves: {bad_moves[-5:]}"
        )

    def stage_candidates(self, pins: list[int], selected: int) -> list[tuple[int, str]]:
        boundary: list[tuple[int, str]] = []
        fallback: list[tuple[int, str]] = []
        for plate, pin in enumerate(pins, start=1):
            if pin == 1:
                boundary.append((plate, PIN_UP_KEY))
            elif pin == HOLES:
                boundary.append((plate, PIN_DOWN_KEY))
            else:
                if pin < TARGET:
                    fallback.append((plate, PIN_UP_KEY))
                    fallback.append((plate, PIN_DOWN_KEY))
                elif pin > TARGET:
                    fallback.append((plate, PIN_DOWN_KEY))
                    fallback.append((plate, PIN_UP_KEY))
                else:
                    fallback.append((plate, PIN_UP_KEY))
                    fallback.append((plate, PIN_DOWN_KEY))
        boundary.sort(key=lambda item: (abs(item[0] - selected), item[0]))
        fallback.sort(key=lambda item: (abs(item[0] - selected), item[0]))
        return boundary + fallback

    def learn_rules_with_recovery(
        self,
        pins: list[int],
        count: int,
        backend: str,
        selected: int,
    ) -> tuple[dict[int, list[int]], dict[int, list[int]], list[str]]:
        learned_same: dict[int, list[int]] = {}
        learned_opp: dict[int, list[int]] = {}
        bad_moves: list[str] = []
        current = pins[:]
        current_selected = selected
        attempts = 0

        while len(learned_same) < count:
            attempts += 1
            if attempts > count * MAX_RULE_ATTEMPTS_FACTOR:
                missing = [plate for plate in range(1, count + 1) if plate not in learned_same]
                raise ValueError(f"Could not learn all rules; missing plates {missing}; bad moves: {bad_moves[-8:]}")

            if not self.all_pins_safe(current):
                staging_keys, current, current_selected, stage_bad = self.stage_safe_state(
                    current, count, backend, current_selected
                )
                bad_moves.extend(stage_bad)
                print(f"Re-staged for learning with keys: {' '.join(staging_keys) or '-'}", flush=True)

            progress = False
            for plate in range(1, count + 1):
                if plate in learned_same:
                    continue

                self.go_to_plate(plate, count, backend, current_selected)
                current_selected = plate
                try:
                    before = self.capture_pins_stable(f"learn_base_{plate}_{attempts}", count)
                except (Exception, SystemExit) as exc:
                    event = f"Plate {plate}: base capture failed: {exc}"
                    bad_moves.append(event)
                    print(event, flush=True)
                    current, current_selected = self.recover_current_state(count, backend, f"learn_recover_{plate}")
                    break

                if not self.all_pins_safe(before):
                    current = before
                    break

                directions = [PIN_UP_KEY, PIN_DOWN_KEY] if before[plate - 1] < HOLES else [PIN_DOWN_KEY]
                learned = False
                for move_key in directions:
                    if move_key == PIN_UP_KEY and before[plate - 1] >= HOLES:
                        continue
                    if move_key == PIN_DOWN_KEY and before[plate - 1] <= 1:
                        continue
                    self.go_to_plate(plate, count, backend, current_selected)
                    current_selected = plate
                    try:
                        same, opposite, rule_before, after = self.attempt_rule_move(
                            plate, count, backend, move_key, attempts
                        )
                    except (Exception, SystemExit) as exc:
                        event = f"Plate {plate}: bad {move_key.upper()} from {before}: {exc}"
                        bad_moves.append(event)
                        print(event, flush=True)
                        current, current_selected = self.recover_current_state(
                            count, backend, f"learn_recover_{plate}_{move_key}"
                        )
                        if not self.all_pins_safe(current):
                            break
                        continue

                    learned_same[plate] = same
                    learned_opp[plate] = opposite
                    progress = True
                    learned = True
                    print(
                        f"Plate {plate}: {move_key.upper()} {rule_before} -> {after}; "
                        f"same={same or '-'} opposite={opposite or '-'}",
                        flush=True,
                    )

                    undo_key = self.inverse_move_key(move_key)
                    undo_before_pick_signature = self.last_pick_signature
                    self.send_keys_and_wait([undo_key], backend)
                    try:
                        current = self.capture_pins_stable(f"learn_undo_{plate}_{attempts}", count)
                        if self.pick_signature_changed(undo_before_pick_signature, self.last_pick_signature):
                            raise ValueError(f"undo broke a pick: {after} -> {current}")
                        self.validate_observed_move(plate, undo_key, after, current)
                    except (Exception, SystemExit) as exc:
                        event = f"Plate {plate}: undo {undo_key.upper()} failed after learning: {exc}"
                        bad_moves.append(event)
                        print(event, flush=True)
                        current, current_selected = self.recover_current_state(
                            count, backend, f"learn_recover_undo_{plate}"
                        )
                    if current != rule_before:
                        event = f"Plate {plate}: undo did not restore base: expected {rule_before}, got {current}"
                        bad_moves.append(event)
                        print(event, flush=True)
                    break

                if not learned and not self.all_pins_safe(current):
                    break

            if not progress and self.all_pins_safe(current):
                missing = [plate for plate in range(1, count + 1) if plate not in learned_same]
                raise ValueError(f"No rule-learning progress from safe state {current}; missing {missing}")

        return learned_same, learned_opp, bad_moves

    def attempt_rule_move(
        self,
        plate: int,
        count: int,
        backend: str,
        move_key: str,
        attempt: int,
    ) -> tuple[list[int], list[int], list[int], list[int]]:
        before = self.capture_pins_stable(f"learn_base_{plate}_{move_key}_{attempt}", count)
        if not self.all_pins_safe(before):
            raise ValueError(f"Unsafe rule-learning base for plate {plate}: {before}")

        before_pick_signature = self.last_pick_signature
        self.send_keys_and_wait([move_key], backend)
        after = self.capture_pins_stable(f"learn_after_{plate}_{move_key}_{attempt}", count)
        if self.pick_signature_changed(before_pick_signature, self.last_pick_signature):
            self.remember_blocked_edge_move(plate, move_key, before)
            raise ValueError(f"move broke a pick: {before} -> {after}")
        self.validate_observed_move(plate, move_key, before, after)

        same, opposite = self.rule_from_transition(plate, before, after)
        return same, opposite, before, after

    def send_keys_and_wait(
        self,
        keys: list[str],
        backend: str,
        pause: float = LEARN_PAUSE,
    ) -> None:
        if not keys:
            return
        start = time.perf_counter()

        try:
            desktop.send_keys(keys, backend, KEY_DELAY)
            time.sleep(pause)
        except BaseException as exc:
            self.log_timing(
                "send_keys_and_wait",
                time.perf_counter() - start,
                ok=False,
                error=type(exc).__name__,
                key_count=len(keys),
                keys=" ".join(keys[:20]),
                pause=pause,
                key_delay=KEY_DELAY,
                backend=backend,
            )
            raise
        self.log_timing(
            "send_keys_and_wait",
            time.perf_counter() - start,
            ok=True,
            key_count=len(keys),
            keys=" ".join(keys[:20]),
            pause=pause,
            key_delay=KEY_DELAY,
            backend=backend,
        )

    def validate_observed_move(self, plate: int, move_key: str, before: list[int], after: list[int]) -> None:
        if len(before) != len(after):
            raise ValueError(f"Pin count changed after plate {plate} {move_key.upper()}: {before} -> {after}")
        deltas = [new - old for old, new in zip(before, after)]
        if any(pin < 1 or pin > HOLES for pin in after):
            raise ValueError(f"Detected out-of-range pin after plate {plate} {move_key.upper()}: {before} -> {after}")

        expected_delta = 1 if move_key == PIN_UP_KEY else -1
        selected_delta = deltas[plate - 1]
        if selected_delta != expected_delta:
            raise ValueError(
                f"Selection/capture drift after plate {plate} {move_key.upper()}: expected plate {plate} "
                f"to move by {expected_delta}, got {selected_delta}; {before} -> {after}"
            )
        for other, delta in enumerate(deltas, start=1):
            if other != plate and abs(delta) > 2:
                raise ValueError(
                    f"Plate {plate} {move_key.upper()} made plate {other} jump by {delta}; {before} -> {after}"
                )

    def home_selection(self, count: int, backend: str) -> None:
        self.send_keys_and_wait([SELECT_FIRST_KEY] * (count + 1), backend, NAV_PAUSE)
        self.last_selected_plate = 1

    def go_to_plate(self, target: int, count: int, backend: str, current_selected: int | None = None) -> list[str]:
        source = self.last_selected_plate or current_selected
        if source is not None and 1 <= source <= count:
            keys = self.navigation_keys(source, target)
            self.send_keys_and_wait(keys, backend, NAV_PAUSE)
            self.last_selected_plate = target
            if keys:
                print(f"select {source}->{target}: {' '.join(keys)}", flush=True)
            return keys
        return self.go_to_plate_absolute(target, count, backend)

    def go_to_plate_absolute(self, target: int, count: int, backend: str) -> list[str]:
        keys = [SELECT_FIRST_KEY] * (count + 1) + [SELECT_NEXT_KEY] * (target - 1)
        self.send_keys_and_wait(keys, backend, NAV_PAUSE)
        self.last_selected_plate = target
        return keys

    def recover_current_state(
        self,
        count: int,
        backend: str,
        name: str,
        after_break: bool = False,
    ) -> tuple[list[int], int]:
        if after_break:
            self.timed_sleep("break_recovery_sleep", BREAK_RECOVERY_PAUSE)
            self.last_selected_plate = 1
            try:
                return self.capture_pins_stable(name, count), 1
            except (Exception, SystemExit) as exc:
                print(f"Recovery capture failed after break: {exc}; resetting.", flush=True)
                self.reset_and_home(count, backend)
                return self.capture_pins_stable(f"{name}_reset", count), 1

        self.home_selection(count, backend)
        try:
            return self.capture_pins_stable(name, count), 1
        except (Exception, SystemExit) as exc:
            print(f"Recovery capture failed after home: {exc}; resetting.", flush=True)
            self.reset_and_home(count, backend)
            return self.capture_pins_stable(f"{name}_reset", count), 1

    def navigation_keys(self, selected: int, target: int) -> list[str]:
        if selected < target:
            return [SELECT_NEXT_KEY] * (target - selected)
        if selected > target:
            return [SELECT_PREV_KEY] * (selected - target)
        return []

    def inverse_move_key(self, key: str) -> str:
        if key == PIN_UP_KEY:
            return PIN_DOWN_KEY
        if key == PIN_DOWN_KEY:
            return PIN_UP_KEY
        raise ValueError(f"No inverse for key {key!r}")

    def capture_pins(self, name: str, count: int) -> list[int]:
        path = Path(tempfile.gettempdir()) / f"gothic_lock_{name}.png"
        try:
            self.timed_call(
                "capture_screenshot",
                lambda: desktop.capture_screenshot(path, None),
                action="capture_pins",
                name=name,
                image=path,
            )
            self.last_pick_signature = self.timed_call(
                "detect_pick_signature",
                lambda: self.detect_pick_signature(path),
                action="capture_pins",
                name=name,
                image=path,
            )
            return self.timed_call(
                "detect_pins",
                lambda: vision.detect_pins(path, count, HOLES, vision.parse_roi(None), None),
                action="capture_pins",
                name=name,
                image=path,
                count=count,
            )
        except SystemExit as exc:
            raise ValueError(str(exc)) from exc

    def capture_pins_sync(self, name: str, count: int, expected: list[int]) -> list[int]:
        pins = self.capture_pins(name, count)
        if pins == expected:
            return pins
        return self.capture_pins_stable(f"{name}_stable", count)

    def capture_after_move_quick(
        self,
        name: str,
        count: int,
        plate: int,
        move_key: str,
        before: list[int],
        before_pick_signature: tuple[int, ...] | None,
    ) -> list[int]:
        try:
            after = self.capture_pins(f"{name}_quick", count)
        except (Exception, SystemExit) as exc:
            print(f"{name}: quick capture failed; retrying stable: {exc}", flush=True)
            return self.capture_pins_stable(name, count)

        if self.pick_signature_changed(before_pick_signature, self.last_pick_signature):
            return after

        reason = self.quick_capture_suspicion(plate, move_key, before, after)
        if reason is None:
            return after

        print(f"{name}: quick capture suspicious ({reason}); retrying stable", flush=True)
        return self.capture_pins_stable(name, count)

    def quick_capture_suspicion(
        self,
        plate: int,
        move_key: str,
        before: list[int],
        after: list[int],
    ) -> str | None:
        if after == before:
            return "no visible change"
        try:
            self.validate_observed_move(plate, move_key, before, after)
        except ValueError as exc:
            return str(exc)
        return None

    def detect_pick_signature(self, path: Path) -> tuple[int, ...] | None:
        image = Image.open(path).convert("RGB")
        width, height = image.size
        crop = image.crop(
            (
                int(width * 0.805),
                int(height * 0.735),
                int(width * 0.835),
                int(height * 0.785),
            )
        )
        pixels = crop.load()
        badge_pixels: list[tuple[int, int]] = []
        for y in range(crop.height):
            for x in range(crop.width):
                r, g, b = pixels[x, y]
                if r > 150 and g > 115 and b > 90 and r > b * 1.05 and g > b * 0.9:
                    badge_pixels.append((x, y))
        if not badge_pixels:
            return None

        left = min(x for x, _ in badge_pixels)
        top = min(y for _, y in badge_pixels)
        right = max(x for x, _ in badge_pixels)
        bottom = max(y for _, y in badge_pixels)
        inset_x = max(1, (right - left) // 8)
        inset_y = max(1, (bottom - top) // 8)
        left += inset_x
        right -= inset_x
        top += inset_y
        bottom -= inset_y

        columns = 10
        rows = 14
        signature: list[int] = []
        for grid_y in range(rows):
            for grid_x in range(columns):
                x_start = left + (right - left + 1) * grid_x // columns
                x_end = left + (right - left + 1) * (grid_x + 1) // columns
                y_start = top + (bottom - top + 1) * grid_y // rows
                y_end = top + (bottom - top + 1) * (grid_y + 1) // rows
                total = 0
                dark = 0
                for y in range(y_start, y_end):
                    for x in range(x_start, x_end):
                        r, g, b = pixels[x, y]
                        total += 1
                        if max(r, g, b) < 80:
                            dark += 1
                signature.append(1 if total and dark / total > 0.12 else 0)
        return tuple(signature)

    def capture_pins_stable(self, name: str, count: int) -> list[int]:
        stable_start = time.perf_counter()
        seen: list[tuple[list[int], tuple[int, ...] | None]] = []
        errors: list[str] = []
        previous: tuple[list[int], tuple[int, ...] | None] | None = None
        for attempt in range(1, STABLE_CAPTURE_TRIES + 1):
            try:
                pins = self.capture_pins(f"{name}_{attempt}", count)
            except (Exception, SystemExit) as exc:
                errors.append(str(exc))
                self.timed_sleep("stable_capture_pause", STABLE_CAPTURE_PAUSE, name=name, attempt=attempt)
                continue
            current = (pins, self.last_pick_signature)
            seen.append(current)
            if current == previous:
                self.log_timing(
                    "capture_pins_stable",
                    time.perf_counter() - stable_start,
                    ok=True,
                    name=name,
                    count=count,
                    attempts=attempt,
                    captures=len(seen),
                    errors=len(errors),
                )
                return pins
            previous = current
            self.timed_sleep("stable_capture_pause", STABLE_CAPTURE_PAUSE, name=name, attempt=attempt)
        detail = f"captures={[pins for pins, _ in seen]}"
        signatures = [signature for _, signature in seen]
        if any(signature is not None for signature in signatures):
            detail += f"; pick_sigs={[sum(signature) if signature else None for signature in signatures]}"
        if errors:
            detail += f"; errors={errors[-3:]}"
        self.log_timing(
            "capture_pins_stable",
            time.perf_counter() - stable_start,
            ok=False,
            name=name,
            count=count,
            attempts=STABLE_CAPTURE_TRIES,
            captures=len(seen),
            errors=len(errors),
        )
        raise ValueError(f"Pin capture did not settle after {STABLE_CAPTURE_TRIES} tries: {detail}")

    def reset_and_home(self, count: int, backend: str) -> None:
        start = time.perf_counter()
        try:
            self.send_keys_and_wait([RESET_KEY], backend, RESET_PAUSE)
            self.last_selected_plate = 1
        except BaseException as exc:
            self.log_timing(
                "reset_and_home",
                time.perf_counter() - start,
                ok=False,
                error=type(exc).__name__,
                count=count,
                backend=backend,
            )
            raise
        self.log_timing("reset_and_home", time.perf_counter() - start, ok=True, count=count, backend=backend)

    def capture_live(self, name: str) -> Path:
        image_path = Path(tempfile.gettempdir()) / f"gothic_lock_{name}.png"
        curses.def_prog_mode()
        curses.endwin()
        try:
            print(f"Capturing lock screen in {CAPTURE_DELAY:g}s. Focus the game window now.", flush=True)
            self.timed_sleep("focus_delay", CAPTURE_DELAY, action=name)
            self.timed_call(
                "capture_screenshot",
                lambda: desktop.capture_screenshot(image_path, None),
                action=name,
                image=image_path,
            )
        finally:
            curses.reset_prog_mode()
            curses.curs_set(0)
            self.stdscr.clear()
        return image_path

    def selected_backend(self) -> str:
        return detect_desktop_backend()

    def rules_text_from_learned(self, same: dict[int, list[int]], opposite: dict[int, list[int]]) -> str:
        groups: list[str] = []
        for plate in sorted(same):
            links = [f"{item}s" for item in same[plate]] + [f"{item}o" for item in opposite[plate]]
            groups.append(f"{plate}:{','.join(links)}")
        return ";".join(groups)

    def condensed_plate_key_moves(self, moves: list[tuple[int, str]]) -> str:
        keyed_moves = [
            (plate, PIN_DOWN_KEY.upper() if direction == "R" else PIN_UP_KEY.upper())
            for plate, direction in moves
        ]
        groups: list[str] = []
        index = 0
        while index < len(keyed_moves):
            run_len = 1
            while index + run_len < len(keyed_moves) and keyed_moves[index + run_len] == keyed_moves[index]:
                run_len += 1
            plate, key = keyed_moves[index]
            token = f"{plate}{key}"
            groups.append(f"{token}x{run_len}" if run_len > 1 else token)
            index += run_len
        return " ".join(groups)

    def simulate_moves(
        self,
        pins: list[int],
        moves: list[tuple[int, str]],
        rules: dict[int, dict[int, int]],
    ) -> list[int]:
        state = pins[:]
        for plate, direction in moves:
            delta = -1 if direction == "R" else 1
            state[plate - 1] += delta
            for linked_plate, relation in rules.get(plate, {}).items():
                state[linked_plate - 1] += delta * relation
            if any(pin < 1 or pin > HOLES for pin in state):
                raise ValueError(f"Solution would move out of bounds after plate {plate}{direction}: {state}")
        return state

    def wrap_result(self, lines: list[str]) -> list[str]:
        _, width = self.stdscr.getmaxyx()
        wrapped: list[str] = []
        for line in lines:
            wrapped.extend(textwrap.wrap(line, width=max(20, width - 1)) or [""])
        return wrapped


def main() -> int:
    curses.wrapper(lambda stdscr: LockTui(stdscr).run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
