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

## How It Works

The lock is treated as a set of numbered plates. Each plate has one visible pin
position from `1` to `7`; position `4` is the center target.

### 1. Pin Detection

The vision code captures the active game window and looks for two kinds of
blobs inside the lock area:

- dark hole blobs, used to infer plate rows and the seven hole positions,
- brass pin blobs, used to determine the current pin position on each row.

Rows are projected along the slanted lock angle, grouped into plates, and each
brass pin is assigned to the closest detected row. OpenCV is used when
available, with a pure-Python fallback kept for portability.

### 2. Rule Detection

The scanner learns rules by moving one selected plate at a time and comparing
pin positions before and after the move.

For every plate:

- the selected plate always moves by one hole,
- linked plates may move in the same direction,
- linked plates may move in the opposite direction,
- unlinked plates do not move.

The scanner remembers unsafe edge moves that break lockpicks or produce no
movement. If a pin is on hole `1` or `7`, it prefers moves that pull pins away
from the edge. When known rules can safely create a better test position, the
scanner uses them as helper moves, but it avoids undoing a useful setup before
testing an unknown plate.

### 3. Solving

After rules are known, the solver runs a breadth-first search over pin states.
It only accepts moves where every pin stays inside holes `1..7`. The goal state
is all pins at `4`.

The solver searches actual key cost, including plate selection keys, not only
plate moves. That produces a key sequence ready to send to the game.

### 4. Input And Capture

Desktop-specific work is isolated behind `gothic_lock/desktop.py`.

The rest of the scanner asks for simple operations:

- capture the active lock screen,
- move selection to another plate,
- press a plate movement key,
- reset/home the lock.

That is why Hyprland, X11, Windows, and future KDE Plasma support can live
behind the same backend interface.

## Desktop Backends

`gothic_lock/desktop.py` is the stable wrapper used by the TUI, CLI, scanner,
and solver. Desktop-specific input/capture code lives in
`gothic_lock/desktop_backends/`, with one module per backend.

Current backends:

- Hyprland via `hyprctl`
- X11 via `xdotool`
- Windows via native Win32 APIs and Pillow `ImageGrab`
- print/no-op backend for dry runs

Future KDE Plasma support should be added as another backend module behind the
same facade.

On Windows, install `requirements.txt` in a normal Python environment. The TUI
uses `windows-curses`; the CLI path does not need a separate terminal UI package.

## Tests

```bash
python -m pytest -q
```

The tests cover pure solver behavior and scanner candidate ordering. They do not require the game window.
