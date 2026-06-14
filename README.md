# GothicLockSolver

Small Python solver for the Gothic 1 Remake lock minigame.

It can:

- detect pin positions from screenshots,
- learn plate-link rules by interacting with the lock,
- solve the lock while keeping all pins inside the visible holes,
- send keys through a desktop backend.

## Run

```bash
python gothic_lock_tui.py
```

The TUI has four actions:

1. Auto Pin Identify
2. Auto Rule Detection
3. Auto Solve
4. Auto Detect + Solve

## Desktop Backends

Desktop-specific input/capture code lives in `gothic_lock/desktop.py`.

Current backends:

- Hyprland via `hyprctl`
- X11 via `xdotool`
- Windows via native Win32 APIs and Pillow `ImageGrab`
- print/no-op backend for dry runs

Future KDE Plasma support should be added there behind the same backend interface.

On Windows, install `requirements.txt` in a normal Python environment. The TUI
uses `windows-curses`; the CLI path does not need a separate terminal UI package.

## Tests

```bash
python -m pytest -q
```

The tests cover pure solver behavior and scanner candidate ordering. They do not require the game window.
