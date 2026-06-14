from gothic_lock.config import PIN_DOWN_KEY, PIN_UP_KEY
from gothic_lock.scanner import RuleScanLogic


class DummyScanner(RuleScanLogic):
    def __init__(self, selected=1, blocked=()):
        self.last_selected_plate = selected
        self.blocked_edge_moves = set(blocked)
        self.rule_start_pins = None


def first_unblocked(scanner, pins, count, learned_same, learned_opp):
    skipped = []
    for plate, key in scanner.scan_action_candidates(pins, count, learned_same, learned_opp):
        if scanner.is_blocked_edge_move(plate, key, pins):
            skipped.append((plate, key))
            continue
        return (plate, key), skipped
    return None, skipped


def test_unknown_plate_tries_legal_opposite_direction_before_helper_rollback():
    scanner = DummyScanner(
        selected=2,
        blocked=[
            (5, PIN_UP_KEY, frozenset({(6, 1)})),
            (5, PIN_UP_KEY, frozenset({(2, 7)})),
        ],
    )
    learned_same = {1: [], 2: [4, 5], 3: [4], 4: [], 6: [2]}
    learned_opp = {1: [], 2: [3], 3: [], 4: [], 6: [1]}

    first, skipped = first_unblocked(scanner, [4, 7, 2, 5, 2, 1], 6, learned_same, learned_opp)

    assert skipped == [(5, PIN_UP_KEY)]
    assert first == (5, PIN_DOWN_KEY)


def test_blocked_edge_plate_still_uses_helper_before_normal_unknown_tests():
    scanner = DummyScanner(
        selected=6,
        blocked=[
            (5, PIN_UP_KEY, frozenset({(2, 7), (5, 1)})),
            (2, PIN_DOWN_KEY, frozenset({(2, 7), (5, 1)})),
        ],
    )
    learned_same = {1: [], 4: [], 6: [2]}
    learned_opp = {1: [], 4: [], 6: [1]}

    first, skipped = first_unblocked(scanner, [3, 7, 2, 3, 1, 2], 6, learned_same, learned_opp)

    assert skipped == [(5, PIN_UP_KEY), (2, PIN_DOWN_KEY)]
    assert first == (6, PIN_DOWN_KEY)

