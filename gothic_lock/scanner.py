"""Rule-scan decision helpers.

This mixin is intentionally free of curses and screenshot/key-sending code.
It owns candidate ordering, known-rule prediction, and edge-risk memory.
"""

from __future__ import annotations

from .config import HOLES, PIN_DOWN_KEY, PIN_UP_KEY, TARGET


class RuleScanLogic:
    blocked_edge_moves: set[tuple[int, str, frozenset[tuple[int, int]]]]
    rule_start_pins: list[int] | None

    def all_pins_safe(self, pins: list[int]) -> bool:
        return all(1 < pin < HOLES for pin in pins)

    def scan_action_candidates(
        self,
        pins: list[int],
        count: int,
        learned_same: dict[int, list[int]],
        learned_opp: dict[int, list[int]],
    ) -> list[tuple[int, str]]:
        missing = [plate for plate in range(1, count + 1) if plate not in learned_same]
        missing_edges_to_free: set[int] = set()
        selected = getattr(self, "last_selected_plate", None) or 1
        direct_edge: list[tuple[int, int, int, str]] = []
        direct_normal: list[tuple[int, int, int, str]] = []

        for plate in missing:
            direct_moves = self.scan_directions(pins[plate - 1])
            direct_move_available = False
            for order, move_key in enumerate(direct_moves):
                item = (abs(plate - selected), plate, order, move_key)
                if pins[plate - 1] in (1, HOLES) and self.move_key_in_bounds(move_key, pins[plate - 1]):
                    direct_edge.append(item)
                else:
                    direct_normal.append(item)
                if self.move_key_in_bounds(move_key, pins[plate - 1]) and not self.is_blocked_edge_move(
                    plate, move_key, pins
                ):
                    direct_move_available = True
            if pins[plate - 1] in (1, HOLES) and not direct_move_available:
                missing_edges_to_free.add(plate)

        helper_candidates: list[tuple[int, int, int, str]] = []
        targeted_helpers: list[tuple[int, int, int, str]] = []
        for plate in range(1, count + 1):
            if plate not in learned_same:
                continue
            for move_key in self.scan_directions(pins[plate - 1]):
                predicted = self.predict_known_move(plate, move_key, pins, learned_same, learned_opp)
                if predicted is None:
                    continue
                score = self.known_helper_score(pins, predicted)
                targeted_score = self.missing_edge_helper_score(pins, predicted, missing_edges_to_free)
                if targeted_score > 0:
                    targeted_helpers.append((-targeted_score, abs(plate - selected), plate, move_key))
                if score > 0:
                    helper_candidates.append((-score, abs(plate - selected), plate, move_key))

        direct_edge.sort()
        targeted_helpers.sort()
        direct_normal.sort()
        helper_candidates.sort()
        candidates: list[tuple[int, str]] = []
        candidates.extend((plate, move_key) for _, plate, _, move_key in direct_edge)
        candidates.extend((plate, move_key) for _, _, plate, move_key in targeted_helpers)
        if missing_edges_to_free:
            candidates.extend((plate, move_key) for _, _, plate, move_key in helper_candidates)
            candidates.extend((plate, move_key) for _, plate, _, move_key in direct_normal)
        else:
            candidates.extend((plate, move_key) for _, plate, _, move_key in direct_normal)
            candidates.extend((plate, move_key) for _, _, plate, move_key in helper_candidates)
        return candidates

    def scan_directions(self, pin: int) -> list[str]:
        if pin <= 1:
            return [PIN_UP_KEY]
        if pin >= HOLES:
            return [PIN_DOWN_KEY]
        if pin < TARGET:
            return [PIN_UP_KEY, PIN_DOWN_KEY]
        if pin > TARGET:
            return [PIN_DOWN_KEY, PIN_UP_KEY]
        return [PIN_UP_KEY, PIN_DOWN_KEY]

    def known_move_deltas(
        self,
        plate: int,
        move_key: str,
        count: int,
        learned_same: dict[int, list[int]],
        learned_opp: dict[int, list[int]],
    ) -> list[int] | None:
        if plate not in learned_same:
            return None
        selected_delta = 1 if move_key == PIN_UP_KEY else -1
        deltas = [0] * count
        deltas[plate - 1] = selected_delta
        for linked in learned_same[plate]:
            deltas[linked - 1] = selected_delta
        for linked in learned_opp[plate]:
            deltas[linked - 1] = -selected_delta
        return deltas

    def known_move_blockers(
        self,
        plate: int,
        move_key: str,
        pins: list[int],
        learned_same: dict[int, list[int]],
        learned_opp: dict[int, list[int]],
    ) -> list[tuple[int, int]]:
        deltas = self.known_move_deltas(plate, move_key, len(pins), learned_same, learned_opp)
        if deltas is None:
            return []
        blockers: list[tuple[int, int]] = []
        for index, (pin, delta) in enumerate(zip(pins, deltas), start=1):
            if delta == 0:
                continue
            next_pin = pin + delta
            if next_pin < 1 or next_pin > HOLES:
                blockers.append((index, next_pin))
        return blockers

    def predict_known_move(
        self,
        plate: int,
        move_key: str,
        pins: list[int],
        learned_same: dict[int, list[int]],
        learned_opp: dict[int, list[int]],
    ) -> list[int] | None:
        deltas = self.known_move_deltas(plate, move_key, len(pins), learned_same, learned_opp)
        if deltas is None:
            return None
        predicted = [pin + delta for pin, delta in zip(pins, deltas)]
        if any(pin < 1 or pin > HOLES for pin in predicted):
            return None
        return predicted

    def known_helper_score(self, before: list[int], after: list[int]) -> int:
        edge_gain = 0
        created_edges = 0
        for old, new in zip(before, after):
            if old == 1 and new > 1:
                edge_gain += 1
            elif old == HOLES and new < HOLES:
                edge_gain += 1
            elif old not in (1, HOLES) and new in (1, HOLES):
                created_edges += 1
        if edge_gain == 0:
            return 0
        return edge_gain * 20 + self.safety_score(after) - self.safety_score(before) - created_edges * 2

    def missing_edge_helper_score(self, before: list[int], after: list[int], missing_edges: set[int]) -> int:
        if not missing_edges:
            return 0
        target_gain = 0
        created_edges = 0
        for plate in missing_edges:
            old = before[plate - 1]
            new = after[plate - 1]
            if old == 1 and new > 1:
                target_gain += 1
            elif old == HOLES and new < HOLES:
                target_gain += 1
        if target_gain == 0:
            return 0
        for old, new in zip(before, after):
            if old not in (1, HOLES) and new in (1, HOLES):
                created_edges += 1
        return target_gain * 100 + self.safety_score(after) - self.safety_score(before) - created_edges * 2

    def move_key_in_bounds(self, move_key: str, pin: int) -> bool:
        if move_key == PIN_UP_KEY:
            return pin < HOLES
        if move_key == PIN_DOWN_KEY:
            return pin > 1
        return False

    def rule_from_transition(self, plate: int, before: list[int], after: list[int]) -> tuple[list[int], list[int]]:
        selected_delta = after[plate - 1] - before[plate - 1]
        same: list[int] = []
        opposite: list[int] = []
        for other in range(1, len(before) + 1):
            if other == plate:
                continue
            delta = after[other - 1] - before[other - 1]
            if delta == 0:
                continue
            if abs(delta) > 1:
                print(
                    f"Plate {plate}: treating plate {other} jump {delta} as detection wobble; using direction only",
                    flush=True,
                )
            if delta * selected_delta > 0:
                same.append(other)
            elif delta * selected_delta < 0:
                opposite.append(other)
        return same, opposite

    def safety_score(self, pins: list[int]) -> int:
        return sum(min(pin - 1, HOLES - pin) for pin in pins)

    def edge_count(self, pins: list[int]) -> int:
        return sum(1 for pin in pins if pin in (1, HOLES))

    def should_rollback_scan_move(self, before: list[int], after: list[int]) -> bool:
        return self.edge_count(after) > self.edge_count(before)

    def edge_signature(self, pins: list[int]) -> frozenset[tuple[int, int]]:
        return frozenset((plate, pin) for plate, pin in enumerate(pins, start=1) if pin in (1, HOLES))

    def remember_blocked_edge_move(self, plate: int, move_key: str, pins: list[int]) -> None:
        edges = set(self.edge_signature(pins))
        if self.move_key_in_bounds(move_key, pins[plate - 1]):
            edges.discard((plate, pins[plate - 1]))
        if edges:
            self.blocked_edge_moves.add((plate, move_key, frozenset(edges)))

    def is_blocked_edge_move(self, plate: int, move_key: str, pins: list[int]) -> bool:
        current_edges = self.edge_signature(pins)
        if not current_edges:
            return False
        for blocked_plate, blocked_key, blocked_edges in self.blocked_edge_moves:
            if blocked_plate == plate and blocked_key == move_key and blocked_edges & current_edges:
                return True
        return False

    def looks_like_break_reset(self, before: list[int], after: list[int]) -> bool:
        return (
            self.rule_start_pins is not None
            and before != after
            and after == self.rule_start_pins
            and bool(self.edge_signature(before))
        )

    def pick_signature_changed(
        self,
        before: tuple[int, ...] | None,
        after: tuple[int, ...] | None,
    ) -> bool:
        return before is not None and after is not None and before != after
