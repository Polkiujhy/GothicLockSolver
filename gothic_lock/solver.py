"""Pure rule parsing and lock-solving algorithms."""

from __future__ import annotations

from collections import deque


DEFAULT_RULES = "1:4o;2:1o,3o,6s;3:6o;4:3o,6o;5:1o;6:1o"


def parse_rules(text: str) -> dict[int, dict[int, int]]:
    """Parse rules like '1:4o;2:1o,3o,6s'.

    Each selected plate always moves itself in the same direction. Linked plates
    use s/same => same direction, o/opposite => opposite direction.
    """
    rules: dict[int, dict[int, int]] = {}
    for raw_group in text.split(";"):
        group = raw_group.strip()
        if not group:
            continue
        if ":" not in group:
            raise SystemExit(f"Bad rule group {group!r}; expected e.g. 2:1o,3s")
        left, right = group.split(":", 1)
        try:
            plate = int(left.strip())
        except ValueError as exc:
            raise SystemExit(f"Bad plate number in rule group {group!r}") from exc
        links = rules.setdefault(plate, {})
        if right.strip():
            for raw_item in right.split(","):
                item = raw_item.strip().lower()
                if not item:
                    continue
                if item[-1] not in {"s", "o"}:
                    raise SystemExit(f"Bad link {item!r}; suffix with s for same or opposite")
                try:
                    other = int(item[:-1])
                except ValueError as exc:
                    raise SystemExit(f"Bad linked plate number in {item!r}") from exc
                links[other] = 1 if item[-1] == "s" else -1
    if not rules:
        raise SystemExit("No rules parsed")
    max_plate = max([*rules.keys(), *(plate for links in rules.values() for plate in links)])
    for plate in range(1, max_plate + 1):
        rules.setdefault(plate, {})
    return rules


def solve_moves(
    pins: list[int],
    rules: dict[int, dict[int, int]],
    holes: int,
    target: int,
) -> list[tuple[int, str]]:
    plate_count = max(max(rules), len(pins))
    if len(pins) != plate_count:
        raise SystemExit(f"Detected {len(pins)} pins, but rules describe {plate_count} plates")

    effects: dict[int, tuple[int, ...]] = {}
    for plate in range(1, plate_count + 1):
        delta = [0] * plate_count
        delta[plate - 1] = -1
        for linked_plate, relation in rules.get(plate, {}).items():
            delta[linked_plate - 1] = -1 if relation == 1 else 1
        effects[plate] = tuple(delta)

    start = tuple(pins)
    wanted = tuple([target] * plate_count)
    queue: deque[tuple[int, ...]] = deque([start])
    parent: dict[tuple[int, ...], tuple[int, ...] | None] = {start: None}
    action: dict[tuple[int, ...], tuple[int, str]] = {}

    while queue:
        state = queue.popleft()
        if state == wanted:
            break
        for plate, effect in effects.items():
            for direction, sign in (("R", 1), ("L", -1)):
                next_state = tuple(state[index] + sign * effect[index] for index in range(plate_count))
                if all(1 <= value <= holes for value in next_state) and next_state not in parent:
                    parent[next_state] = state
                    action[next_state] = (plate, direction)
                    queue.append(next_state)

    if wanted not in parent:
        raise SystemExit("No solution found while keeping all pins inside the visible holes")

    moves: list[tuple[int, str]] = []
    state = wanted
    while parent[state] is not None:
        moves.append(action[state])
        state = parent[state]  # type: ignore[assignment]
    moves.reverse()
    return moves


def build_effects(rules: dict[int, dict[int, int]], plate_count: int) -> dict[int, tuple[int, ...]]:
    """Visible pin-number deltas for moving one selected plate right."""
    effects: dict[int, tuple[int, ...]] = {}
    for plate in range(1, plate_count + 1):
        delta = [0] * plate_count
        delta[plate - 1] = -1
        for linked_plate, relation in rules.get(plate, {}).items():
            delta[linked_plate - 1] = -1 if relation == 1 else 1
        effects[plate] = tuple(delta)
    return effects


def solve_key_path(
    pins: list[int],
    rules: dict[int, dict[int, int]],
    holes: int,
    target: int,
    start_plate: int,
    next_key: str,
    prev_key: str,
    left_key: str,
    right_key: str,
) -> tuple[list[str], list[tuple[int, str]]]:
    """Shortest solution in actual key presses, including plate selection."""
    plate_count = max(max(rules), len(pins))
    if len(pins) != plate_count:
        raise SystemExit(f"Detected {len(pins)} pins, but rules describe {plate_count} plates")
    if not 1 <= start_plate <= plate_count:
        raise SystemExit(f"--start-plate must be between 1 and {plate_count}")

    effects = build_effects(rules, plate_count)
    wanted = tuple([target] * plate_count)
    start = (tuple(pins), start_plate)
    queue: deque[tuple[tuple[int, ...], int]] = deque([start])
    parent: dict[tuple[tuple[int, ...], int], tuple[tuple[int, ...], int] | None] = {start: None}
    action: dict[tuple[tuple[int, ...], int], tuple[str, tuple[int, str] | None]] = {}
    final_state: tuple[tuple[int, ...], int] | None = None

    while queue:
        pins_state, selected = queue.popleft()
        if pins_state == wanted:
            final_state = (pins_state, selected)
            break

        candidates: list[tuple[str, tuple[tuple[int, ...], int], tuple[int, str] | None]] = []
        if selected < plate_count:
            candidates.append((next_key, (pins_state, selected + 1), None))
        if selected > 1:
            candidates.append((prev_key, (pins_state, selected - 1), None))

        effect = effects[selected]
        for direction, sign, key in (("R", 1, right_key), ("L", -1, left_key)):
            next_pins = tuple(pins_state[index] + sign * effect[index] for index in range(plate_count))
            if all(1 <= value <= holes for value in next_pins):
                candidates.append((key, (next_pins, selected), (selected, direction)))

        for key, next_state, move in candidates:
            if next_state in parent:
                continue
            parent[next_state] = (pins_state, selected)
            action[next_state] = (key, move)
            queue.append(next_state)

    if final_state is None:
        raise SystemExit("No key path found while keeping all pins inside the visible holes")

    keys: list[str] = []
    moves: list[tuple[int, str]] = []
    state = final_state
    while parent[state] is not None:
        key, move = action[state]
        keys.append(key)
        if move is not None:
            moves.append(move)
        state = parent[state]  # type: ignore[assignment]
    keys.reverse()
    moves.reverse()
    return keys, moves


def condensed_moves(moves: list[tuple[int, str]]) -> str:
    groups: list[str] = []
    index = 0
    while index < len(moves):
        run_len = 1
        while index + run_len < len(moves) and moves[index + run_len] == moves[index]:
            run_len += 1
        token = f"{moves[index][0]}{moves[index][1]}"
        groups.append(f"{token}x{run_len}" if run_len > 1 else token)
        index += run_len
    return " ".join(groups)


def moves_to_keys(
    moves: list[tuple[int, str]],
    start_plate: int,
    next_key: str,
    prev_key: str,
    left_key: str,
    right_key: str,
) -> list[str]:
    keys: list[str] = []
    current = start_plate
    for plate, direction in moves:
        while current < plate:
            keys.append(next_key)
            current += 1
        while current > plate:
            keys.append(prev_key)
            current -= 1
        keys.append(right_key if direction == "R" else left_key)
    return keys
