"""Screenshot image analysis for the Gothic lock minigame."""

from __future__ import annotations

import itertools
import math
import statistics
from dataclasses import dataclass
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError as exc:
    raise SystemExit("Pillow/PIL is required. It is already available on this machine in normal Python.") from exc

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None


@dataclass(frozen=True)
class Blob:
    kind: str
    area: int
    bbox: tuple[int, int, int, int]
    x: float
    y: float
    p: float = 0.0
    t: float = 0.0


def parse_roi(text: str | None) -> tuple[float, float, float, float]:
    if not text:
        return (0.50, 0.12, 0.98, 0.62)
    parts = [float(part.strip()) for part in text.split(",")]
    if len(parts) != 4:
        raise SystemExit("--roi must be four comma-separated values: left,top,right,bottom")
    if not all(0 <= value <= 1 for value in parts) or not (parts[0] < parts[2] and parts[1] < parts[3]):
        raise SystemExit("--roi values must be fractions in increasing left,top,right,bottom order")
    return tuple(parts)  # type: ignore[return-value]


def connected_components(
    image: Image.Image,
    roi: tuple[float, float, float, float],
    kind: str,
) -> list[Blob]:
    if cv2 is not None and np is not None:
        return connected_components_cv(image, roi, kind)

    width, height = image.size
    left = int(roi[0] * width)
    top = int(roi[1] * height)
    right = int(roi[2] * width)
    bottom = int(roi[3] * height)
    pixels = image.load()
    mask: set[tuple[int, int]] = set()

    for y in range(top, bottom):
        for x in range(left, right):
            r, g, b = pixels[x, y][:3]
            luminance = (r + g + b) / 3
            if kind == "dark":
                keep = luminance < 45 and max(r, g, b) < 70
            else:
                keep = r > 45 and g > 35 and b < g * 0.88 and r >= g * 0.85 and (r + g) > 115 and (r - b) > 25
            if keep:
                mask.add((x, y))

    seen: set[tuple[int, int]] = set()
    blobs: list[Blob] = []
    neighbors = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1))

    for start in list(mask):
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        xs: list[int] = []
        ys: list[int] = []
        while stack:
            x, y = stack.pop()
            xs.append(x)
            ys.append(y)
            for dx, dy in neighbors:
                point = (x + dx, y + dy)
                if point in mask and point not in seen:
                    seen.add(point)
                    stack.append(point)

        area = len(xs)
        bbox = (min(xs), min(ys), max(xs), max(ys))
        blob_width = bbox[2] - bbox[0] + 1
        blob_height = bbox[3] - bbox[1] + 1
        if kind == "dark":
            valid = 25 <= area <= 220 and 5 <= blob_width <= 24 and 5 <= blob_height <= 18
        else:
            valid = 15 <= area <= 400 and 5 <= blob_width <= 30 and 5 <= blob_height <= 30
        if valid:
            blobs.append(Blob(kind, area, bbox, sum(xs) / area, sum(ys) / area))

    return blobs


def connected_components_cv(
    image: Image.Image,
    roi: tuple[float, float, float, float],
    kind: str,
) -> list[Blob]:
    width, height = image.size
    left = int(roi[0] * width)
    top = int(roi[1] * height)
    right = int(roi[2] * width)
    bottom = int(roi[3] * height)
    if right <= left or bottom <= top:
        return []

    crop = np.asarray(image)[top:bottom, left:right, :3].astype(np.int16)
    r = crop[:, :, 0]
    g = crop[:, :, 1]
    b = crop[:, :, 2]
    if kind == "dark":
        mask = ((r + g + b) < 135) & (np.maximum(np.maximum(r, g), b) < 70)
    else:
        mask = (r > 45) & (g > 35) & (b < g * 0.88) & (r >= g * 0.85) & ((r + g) > 115) & ((r - b) > 25)

    count, _, stats, centroids = cv2.connectedComponentsWithStats(mask.astype("uint8"), 8)
    blobs: list[Blob] = []
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        blob_left = int(stats[label, cv2.CC_STAT_LEFT])
        blob_top = int(stats[label, cv2.CC_STAT_TOP])
        blob_width = int(stats[label, cv2.CC_STAT_WIDTH])
        blob_height = int(stats[label, cv2.CC_STAT_HEIGHT])
        if kind == "dark":
            valid = 25 <= area <= 220 and 5 <= blob_width <= 24 and 5 <= blob_height <= 18
        else:
            valid = 15 <= area <= 400 and 5 <= blob_width <= 30 and 5 <= blob_height <= 30
        if not valid:
            continue
        x = float(centroids[label][0] + left)
        y = float(centroids[label][1] + top)
        bbox = (
            left + blob_left,
            top + blob_top,
            left + blob_left + blob_width - 1,
            top + blob_top + blob_height - 1,
        )
        blobs.append(Blob(kind, area, bbox, x, y))
    return blobs


def median_row_slope(dark_blobs: list[Blob]) -> float:
    slopes: list[float] = []
    for index, first in enumerate(dark_blobs):
        for second in dark_blobs[index + 1 :]:
            dx = second.x - first.x
            dy = second.y - first.y
            if dx < 0:
                dx = -dx
                dy = -dy
            if 12 <= dx <= 50:
                slope = dy / dx
                if 0.20 <= slope <= 0.90:
                    slopes.append(slope)
    if not slopes:
        raise SystemExit("Could not infer plate-row angle from the screenshot")
    return statistics.median(slopes)


def with_projection(blob: Blob, slope: float) -> Blob:
    return Blob(blob.kind, blob.area, blob.bbox, blob.x, blob.y, blob.y - slope * blob.x, blob.x + slope * blob.y)


def raw_row_clusters(dark_blobs: list[Blob]) -> list[list[Blob]]:
    clusters: list[list[Blob]] = []
    means: list[float] = []
    for blob in sorted(dark_blobs, key=lambda item: item.p):
        best_index = -1
        best_distance = math.inf
        for index, mean in enumerate(means):
            distance = abs(blob.p - mean)
            if distance < best_distance:
                best_index = index
                best_distance = distance
        if best_index >= 0 and best_distance < 11:
            clusters[best_index].append(blob)
            means[best_index] = statistics.mean(item.p for item in clusters[best_index])
        else:
            clusters.append([blob])
            means.append(blob.p)

    return clusters


def cluster_rows(dark_blobs: list[Blob], plate_count: int, gold_blobs: list[Blob] | None = None) -> list[list[Blob]]:
    clusters = raw_row_clusters(dark_blobs)
    usable = [cluster for cluster in clusters if len(cluster) >= 4]
    if gold_blobs is not None:
        gold_candidates = sorted(gold_blobs, key=lambda blob: blob.area, reverse=True)[: max(plate_count * 4, plate_count)]
        with_pins = [
            cluster
            for cluster in usable
            if any(abs(gold.p - statistics.mean(blob.p for blob in cluster)) < 13 for gold in gold_candidates)
        ]
        if len(with_pins) >= plate_count:
            usable = with_pins

    if len(usable) < plate_count:
        raise SystemExit(f"Detected only {len(usable)} plate rows, expected {plate_count}. Try --debug-image and adjust --roi.")

    chosen = sorted(usable, key=lambda cluster: (len(cluster), statistics.mean(item.p for item in cluster)), reverse=True)[:plate_count]
    return sorted(chosen, key=lambda cluster: statistics.mean(item.p for item in cluster), reverse=True)


def infer_plate_count(
    image_path: Path,
    roi: tuple[float, float, float, float],
    max_plates: int = 8,
) -> int:
    """Infer visible plate count from the dark hole rows in a screenshot."""
    image = Image.open(image_path).convert("RGB")
    dark = connected_components(image, roi, "dark")
    if len(dark) < 4:
        raise SystemExit("Found too few hole blobs to infer plate count")

    slope = median_row_slope(dark)
    dark = [with_projection(blob, slope) for blob in dark]
    gold = [with_projection(blob, slope) for blob in connected_components(image, roi, "gold")]
    clusters = raw_row_clusters(dark)
    usable = [cluster for cluster in clusters if len(cluster) >= 4]
    if gold:
        gold_candidates = sorted(gold, key=lambda blob: blob.area, reverse=True)[: max(max_plates * 4, max_plates)]
        pinned = [
            cluster
            for cluster in usable
            if any(abs(gold_blob.p - statistics.mean(blob.p for blob in cluster)) < 13 for gold_blob in gold_candidates)
        ]
        if pinned:
            usable = pinned
    if not usable:
        raise SystemExit("Could not infer plate rows from the screenshot")
    return min(max_plates, len(usable))


def best_even_subset(candidates: list[Blob], pin: Blob, holes: int) -> list[Blob]:
    hole_candidates = [candidate for candidate in candidates if candidate != pin]
    if len(hole_candidates) >= 4:
        median_area = statistics.median(candidate.area for candidate in hole_candidates)
        min_area = median_area * 0.40
        candidates = [
            candidate
            for candidate in candidates
            if candidate == pin or candidate.area >= min_area
        ]

    ordered = sorted(candidates, key=lambda item: item.t)
    if len(ordered) <= holes:
        return ordered

    best_score = math.inf
    best_subset = ordered[:holes]
    for subset_indexes in itertools.combinations(range(len(ordered)), holes):
        subset = [ordered[index] for index in subset_indexes]
        if pin not in subset:
            continue
        values = [item.t for item in subset]
        gaps = [values[index + 1] - values[index] for index in range(len(values) - 1)]
        median_gap = statistics.median(gaps)
        if median_gap <= 0:
            continue
        score = sum((gap - median_gap) ** 2 for gap in gaps) / len(gaps)
        score += sum(1000 for gap in gaps if gap < 0.55 * median_gap or gap > 1.65 * median_gap)
        if score < best_score:
            best_score = score
            best_subset = subset
    return sorted(best_subset, key=lambda item: item.t)


def detect_pins(
    image_path: Path,
    plate_count: int,
    holes: int,
    roi: tuple[float, float, float, float],
    debug_image: Path | None,
) -> list[int]:
    image = Image.open(image_path).convert("RGB")
    dark = connected_components(image, roi, "dark")
    gold = connected_components(image, roi, "gold")
    if len(dark) < plate_count * 4:
        raise SystemExit(f"Found too few hole blobs ({len(dark)}). The lock may not be visible or --roi is off.")
    if len(gold) < plate_count:
        raise SystemExit(f"Found too few brass pin blobs ({len(gold)}). The lock may not be visible or --roi is off.")

    slope = median_row_slope(dark)
    dark = [with_projection(blob, slope) for blob in dark]
    gold = [with_projection(blob, slope) for blob in gold]
    rows = cluster_rows(dark, plate_count, gold)
    gold_candidates = sorted(gold, key=lambda blob: blob.area, reverse=True)[: max(plate_count * 3, plate_count)]

    pins: list[int] = []
    debug_rows: list[tuple[list[Blob], Blob, int]] = []
    used_pins: set[Blob] = set()

    for row in rows:
        row_mean = statistics.mean(blob.p for blob in row)
        row_by_t = sorted(row, key=lambda blob: blob.t)
        row_gaps = [
            row_by_t[index + 1].t - row_by_t[index].t
            for index in range(len(row_by_t) - 1)
            if row_by_t[index + 1].t > row_by_t[index].t
        ]
        row_gap = statistics.median(row_gaps) if row_gaps else 28
        t_margin = max(35, row_gap * 1.6)
        min_t = row_by_t[0].t - t_margin
        max_t = row_by_t[-1].t + t_margin
        assigned = [
            blob
            for blob in gold_candidates
            if abs(blob.p - row_mean) < 13 and min_t <= blob.t <= max_t and blob not in used_pins
        ]
        if not assigned:
            assigned = [
                blob
                for blob in gold_candidates
                if abs(blob.p - row_mean) < 18 and min_t <= blob.t <= max_t and blob not in used_pins
            ]
        if not assigned:
            raise SystemExit("Could not assign a brass pin to one detected plate row. Try --debug-image and adjust --roi.")
        pin = max(assigned, key=lambda blob: blob.area)
        used_pins.add(pin)
        subset = best_even_subset(row + [pin], pin, holes)
        pin_index = subset.index(pin) + 1
        pins.append(pin_index)
        debug_rows.append((subset, pin, pin_index))

    if debug_image:
        annotated = image.copy()
        draw = ImageDraw.Draw(annotated)
        for plate_index, (subset, pin, pin_index) in enumerate(debug_rows, start=1):
            for hole_index, blob in enumerate(subset, start=1):
                color = (0, 255, 0) if blob == pin else (255, 0, 0)
                draw.rectangle(blob.bbox, outline=color, width=2)
                draw.text((blob.x + 4, blob.y - 10), str(hole_index), fill=color)
            draw.text((pin.x + 8, pin.y + 2), f"P{plate_index}={pin_index}", fill=(0, 255, 0))
        annotated.save(debug_image)

    return pins
