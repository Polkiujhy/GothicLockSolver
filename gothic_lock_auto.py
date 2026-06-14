#!/usr/bin/env python3
"""Compatibility CLI for the Gothic 1 Remake plate lock solver."""

from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path

from gothic_lock.desktop import (
    backend_names,
    capture_screenshot,
    selected_backend,
    send_keys,
)
from gothic_lock.solver import (
    DEFAULT_RULES,
    build_effects,
    condensed_moves,
    moves_to_keys,
    parse_rules,
    solve_key_path,
    solve_moves,
)
from gothic_lock.vision import (
    Blob,
    best_even_subset,
    cluster_rows,
    connected_components,
    connected_components_cv,
    detect_pins,
    infer_plate_count,
    median_row_slope,
    parse_roi,
    raw_row_clusters,
    with_projection,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect and solve the Gothic 1 Remake plate lock minigame.")
    parser.add_argument("--rules", default=DEFAULT_RULES, help=f"Plate links. Default: {DEFAULT_RULES!r}")
    parser.add_argument("--pins", help="Manual pin override, e.g. 7,6,6,1,2,1. Skips screenshot detection.")
    parser.add_argument("--image", help="Use an existing screenshot instead of capturing the current screen")
    parser.add_argument("--capture-delay", type=float, default=0.0, help="Wait this many seconds before live screenshot capture")
    parser.add_argument("--capture-region", help='Capture region, e.g. "100,100 900x700" or "100,100,900,700"')
    parser.add_argument("--roi", help="Detection ROI as screen fractions: left,top,right,bottom. Default: 0.50,0.12,0.98,0.62")
    parser.add_argument("--debug-image", help="Write an annotated detection image")
    parser.add_argument("--holes", type=int, default=7)
    parser.add_argument("--target", type=int, default=4)
    parser.add_argument("--start-plate", type=int, default=1)
    parser.add_argument("--next-key", default="s", help="Key that moves selection to the next plate number")
    parser.add_argument("--prev-key", default="w", help="Key that moves selection to the previous plate number")
    parser.add_argument("--left-key", default="a")
    parser.add_argument("--right-key", default="d")
    parser.add_argument("--backend", choices=backend_names(), default="print")
    parser.add_argument("--execute", action="store_true", help="Actually send keys; without this, only prints")
    parser.add_argument("--countdown", type=float, default=3.0)
    parser.add_argument("--delay", type=float, default=0.08)
    args = parser.parse_args()

    rules = parse_rules(args.rules)
    plate_count = max(max(rules), *(plate for links in rules.values() for plate in links))
    roi = parse_roi(args.roi)

    debug_image = Path(args.debug_image).expanduser() if args.debug_image else None
    if args.pins:
        try:
            pins = [int(part.strip()) for part in args.pins.split(",") if part.strip()]
        except ValueError as exc:
            raise SystemExit("--pins must be comma-separated numbers") from exc
        if len(pins) != plate_count:
            raise SystemExit(f"--pins has {len(pins)} values, but rules describe {plate_count} plates")
        image_path = None
    else:
        if args.image:
            image_path = Path(args.image).expanduser()
        else:
            image_path = Path(tempfile.gettempdir()) / "gothic_lock_auto_capture.png"
            if args.capture_delay > 0:
                print(f"Capturing screen in {args.capture_delay:g}s. Focus the lock minigame now.")
                time.sleep(args.capture_delay)
            capture_screenshot(image_path, args.capture_region)
        pins = detect_pins(image_path, plate_count, args.holes, roi, debug_image)

    keys, moves = solve_key_path(
        pins,
        rules,
        args.holes,
        args.target,
        args.start_plate,
        args.next_key,
        args.prev_key,
        args.left_key,
        args.right_key,
    )

    print(f"image: {image_path if image_path else '(manual pins)'}")
    print(f"pins: {','.join(str(pin) for pin in pins)}")
    print(f"moves: {condensed_moves(moves)}")
    print(f"keys: {' '.join(keys)}")
    if debug_image:
        print(f"debug: {debug_image}")

    if args.execute:
        backend = args.backend if args.backend != "print" else selected_backend()
        if backend == "print":
            raise SystemExit("No key backend found. Use a supported desktop backend, or run without --execute.")
        print(f"Sending {len(keys)} keys via {backend} in {args.countdown:g}s. Focus the game window now.")
        time.sleep(args.countdown)
        send_keys(keys, backend, args.delay)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
