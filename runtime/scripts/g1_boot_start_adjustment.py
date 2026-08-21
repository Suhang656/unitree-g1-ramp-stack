#!/usr/bin/env python3

"""Pure helpers for safe fixed-start localization candidate generation."""

import json
import math
import time
from pathlib import Path


def normalize_angle(value):
    return math.atan2(math.sin(value), math.cos(value))


def angle_distance(first, second):
    return abs(normalize_angle(first - second))


def load_adjustment(
    path,
    map_path,
    canonical_pose,
    maximum_position_delta,
    maximum_yaw_delta,
):
    """Return a previously learned boot-start pose only when it is safe."""
    path = Path(path)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        pose = data["pose"]
        candidate = (
            float(pose["x"]),
            float(pose["y"]),
            normalize_angle(float(pose["yaw"])),
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None

    if data.get("success") is not True:
        return None

    if str(data.get("map_path", "")) != str(map_path):
        return None

    position_delta = math.hypot(
        candidate[0] - canonical_pose[0],
        candidate[1] - canonical_pose[1],
    )
    yaw_delta = angle_distance(candidate[2], canonical_pose[2])

    if position_delta > maximum_position_delta:
        return None

    if yaw_delta > maximum_yaw_delta:
        return None

    return candidate


def _yaw_offsets(window_degrees, step_degrees):
    offsets = [0.0]
    level = step_degrees

    while level <= window_degrees + 1e-9:
        offsets.extend((-level, level))
        level += step_degrees

    return offsets


def _local_position_offsets(radius, step):
    offsets = [(0.0, 0.0)]
    ring = step

    while ring <= radius + 1e-9:
        diagon = ring / math.sqrt(2.0)
        offsets.extend(
            (
                (ring, 0.0),
                (-ring, 0.0),
                (0.0, ring),
                (0.0, -ring),
                (diagon, diagon),
                (diagon, -diagon),
                (-diagon, diagon),
                (-diagon, -diagon),
            )
        )
        ring += step

    return offsets


def build_candidates(
    canonical_pose,
    adjusted_pose=None,
    search_radius=0.5,
    position_step=0.12,
    yaw_window_degrees=15.0,
    yaw_step_degrees=5.0,
    maximum_candidates=36,
):
    """Build deterministic candidates around the local G1's fixed start.

    The learned pose is tried first. The configured canonical pose remains an
    immutable fallback and the search never leaves ``search_radius`` around it.
    Position offsets are expressed in the robot's heading-aligned frame.
    """
    if search_radius <= 0.0:
        raise ValueError("search_radius must be positive")
    if position_step <= 0.0:
        raise ValueError("position_step must be positive")
    if yaw_step_degrees <= 0.0:
        raise ValueError("yaw_step_degrees must be positive")
    if yaw_window_degrees < 0.0:
        raise ValueError("yaw_window_degrees cannot be negative")
    if maximum_candidates < 1:
        raise ValueError("maximum_candidates must be at least one")

    canonical = (
        float(canonical_pose[0]),
        float(canonical_pose[1]),
        normalize_angle(float(canonical_pose[2])),
    )

    centers = []
    if adjusted_pose is not None:
        adjusted = (
            float(adjusted_pose[0]),
            float(adjusted_pose[1]),
            normalize_angle(float(adjusted_pose[2])),
        )
        if math.hypot(
            adjusted[0] - canonical[0],
            adjusted[1] - canonical[1],
        ) <= search_radius:
            centers.append(("learned", adjusted))

    centers.append(("canonical", canonical))

    positions = []
    for center_name, center in centers:
        positions.append((center_name, center))

    search_center = centers[0][1]
    heading = search_center[2]
    cosine = math.cos(heading)
    sine = math.sin(heading)

    for local_x, local_y in _local_position_offsets(
        search_radius,
        position_step,
    ):
        if local_x == 0.0 and local_y == 0.0:
            continue

        x = search_center[0] + cosine * local_x - sine * local_y
        y = search_center[1] + sine * local_x + cosine * local_y

        if math.hypot(x - canonical[0], y - canonical[1]) > search_radius:
            continue

        positions.append(
            (
                f"search_{len(positions) + 1:02d}",
                (x, y, search_center[2]),
            )
        )

    yaw_offsets = _yaw_offsets(
        yaw_window_degrees,
        yaw_step_degrees,
    )
    candidates = []

    # Round-robin by yaw offset: exact headings at all nearby positions are
    # attempted before increasingly large heading corrections.
    for yaw_offset in yaw_offsets:
        for position_name, pose in positions:
            candidate_yaw = normalize_angle(
                pose[2] + math.radians(yaw_offset)
            )
            name_offset = (
                "base"
                if yaw_offset == 0.0
                else f"{yaw_offset:+g}deg"
            )
            candidate = {
                "name": f"boot_start_{position_name}_{name_offset}",
                "x": pose[0],
                "y": pose[1],
                "yaw": candidate_yaw,
                "distance_to_canonical_m": math.hypot(
                    pose[0] - canonical[0],
                    pose[1] - canonical[1],
                ),
                "yaw_offset_degrees": yaw_offset,
                "auto_adjusted": position_name == "learned",
            }

            duplicate = any(
                math.hypot(
                    candidate["x"] - previous["x"],
                    candidate["y"] - previous["y"],
                ) < 1e-6
                and angle_distance(
                    candidate["yaw"], previous["yaw"]
                ) < 1e-6
                for previous in candidates
            )
            if duplicate:
                continue

            candidates.append(candidate)
            if len(candidates) >= maximum_candidates:
                return candidates

    return candidates


def pose_is_plausible(
    pose,
    canonical_pose,
    maximum_position_delta,
    maximum_yaw_delta,
):
    return (
        math.hypot(
            float(pose["x"]) - float(canonical_pose[0]),
            float(pose["y"]) - float(canonical_pose[1]),
        )
        <= maximum_position_delta
        and angle_distance(
            float(pose["yaw"]), float(canonical_pose[2])
        )
        <= maximum_yaw_delta
    )


def save_adjustment(path, map_path, canonical_pose, accepted):
    """Atomically persist only the boot-start localization correction."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pose = accepted["pose"]
    output = {
        "success": True,
        "updated_at_unix": time.time(),
        "map_path": str(map_path),
        "canonical_pose": {
            "x": float(canonical_pose[0]),
            "y": float(canonical_pose[1]),
            "yaw": normalize_angle(float(canonical_pose[2])),
        },
        "pose": {
            "x": float(pose["x"]),
            "y": float(pose["y"]),
            "yaw": normalize_angle(float(pose["yaw"])),
        },
        "correction": {
            "dx": float(pose["x"]) - float(canonical_pose[0]),
            "dy": float(pose["y"]) - float(canonical_pose[1]),
            "dyaw": normalize_angle(
                float(pose["yaw"]) - float(canonical_pose[2])
            ),
        },
        "accepted_candidate": accepted.get("candidate", {}).get("name"),
    }

    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
