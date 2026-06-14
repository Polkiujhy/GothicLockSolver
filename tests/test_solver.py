from gothic_lock.solver import parse_rules, solve_key_path


def simulate_moves(pins, moves, rules, holes=7):
    state = pins[:]
    for plate, direction in moves:
        delta = -1 if direction == "R" else 1
        state[plate - 1] += delta
        for linked_plate, relation in rules.get(plate, {}).items():
            state[linked_plate - 1] += delta * relation
        assert all(1 <= pin <= holes for pin in state)
    return state


def test_four_plate_lock_solves_to_center():
    rules = parse_rules("1:2s;2:3s;3:2s,1o,4o;4:")
    keys, moves = solve_key_path(
        [2, 1, 7, 7],
        rules,
        holes=7,
        target=4,
        start_plate=1,
        next_key="w",
        prev_key="s",
        left_key="a",
        right_key="d",
    )

    assert keys
    assert moves
    assert simulate_moves([2, 1, 7, 7], moves, rules) == [4, 4, 4, 4]


def test_historical_six_plate_lock_solves_to_center():
    rules = parse_rules("1:4o;2:6s,1o,3o;3:6o;4:3o,6o;5:1o;6:1o")
    keys, moves = solve_key_path(
        [7, 6, 6, 1, 2, 1],
        rules,
        holes=7,
        target=4,
        start_plate=1,
        next_key="w",
        prev_key="s",
        left_key="a",
        right_key="d",
    )

    assert keys
    assert moves
    assert simulate_moves([7, 6, 6, 1, 2, 1], moves, rules) == [4, 4, 4, 4, 4, 4]

