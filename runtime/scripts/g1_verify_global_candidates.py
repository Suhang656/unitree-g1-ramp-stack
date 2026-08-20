#!/usr/bin/env python3

import argparse
import json
import math
import os
import subprocess
import time
from pathlib import Path

import numpy as np
import rclpy

from nav_msgs.msg import Odometry
from rclpy.qos import qos_profile_sensor_data


PROJECT = Path(os.environ.get("G1_PROJECT_DIR", "/home/unitree/智能中控"))

parser = argparse.ArgumentParser()
parser.add_argument(
    "--result",
    default=str(
        PROJECT
        / "data/global_localization/"
        "boot_stationary_result.json"
    ),
)
parser.add_argument(
    "--map",
    default="/home/unitree/test1.pcd",
)
parser.add_argument(
    "--interface",
    default=os.environ.get("G1_NETWORK_INTERFACE", "enP8p1s0"),
)
parser.add_argument(
    "--ready",
    default=str(
        PROJECT
        / "data/global_localization/"
        "localization_ready.json"
    ),
)
args = parser.parse_args()

CANDIDATE_REJECT_DELAY_SECONDS = max(
    0.0,
    float(
        os.environ.get(
            "G1_LOCALIZATION_CANDIDATE_DELAY_SECONDS",
            "0.15",
        )
    ),
)

result_path = Path(args.result)
ready_path = Path(args.ready)

ready_path.unlink(missing_ok=True)

result = json.loads(
    result_path.read_text(encoding="utf-8")
)


def angle_difference(first, second):
    return math.atan2(
        math.sin(first - second),
        math.cos(first - second),
    )


candidates = []

# GLOBAL_ROUTE_ANCHORS_V1
# 官方SLAM优先验证可信历史姿态和已知路线锚点，
# 离线点云匹配候选仅作为最后兜底。
last_pose_path = (
    PROJECT
    / "data/ramp_platform_v3"
    / "last_localization_pose.json"
)


def append_priority_candidate(
    name,
    x,
    y,
    yaw,
    offsets,
):
    candidates.append(
        {
            "name": name,
            "x": float(x),
            "y": float(y),
            "yaw": float(yaw),
            "source_score": 1.0,
            "yaw_offsets_degrees": tuple(offsets),
        }
    )


if last_pose_path.exists():
    try:
        last_pose_data = json.loads(
            last_pose_path.read_text(
                encoding="utf-8"
            )
        )

        last_pose = last_pose_data.get(
            "pose",
            last_pose_data,
        )

        append_priority_candidate(
            "last_pose",
            last_pose["x"],
            last_pose["y"],
            last_pose["yaw"],
            (0, -15, 15, -30, 30, 180),
        )

        print(
            "已载入上次可信姿态：",
            round(float(last_pose["x"]), 3),
            round(float(last_pose["y"]), 3),
            round(float(last_pose["yaw"]), 3),
        )
    except Exception as exc:
        print("上次姿态文件不可用：", exc)


route_points = {
    "start": (
        0.024735889031391838,
        -0.08662520735348705,
        -0.3986063585212273,
    ),
    "end": (
        14.963454714172158,
        -6.78900872898837,
        -0.37799739368461505,
    ),
    "turn_1": (
        1.18586348379448,
        1.1515916561978627,
        -0.3651415685027259,
    ),
    "turn_2": (
        4.900046498890634,
        -0.5406526657681765,
        -1.846993124065595,
    ),
    "turn_3": (
        4.275112442278064,
        -1.9522534788074815,
        -0.421499968000555,
    ),
}

full_yaw_offsets = (
    0,
    180,
    -30,
    30,
    -60,
    60,
    -90,
    90,
    -120,
    120,
    -150,
    150,
)

for name, pose in route_points.items():
    append_priority_candidate(
        f"route_key_{name}",
        pose[0],
        pose[1],
        pose[2],
        full_yaw_offsets,
    )


def append_segment_anchors(
    segment_name,
    start_name,
    end_name,
    spacing=1.0,
):
    start = route_points[start_name]
    end = route_points[end_name]

    delta_x = end[0] - start[0]
    delta_y = end[1] - start[1]
    length = math.hypot(delta_x, delta_y)

    divisions = max(
        1,
        int(math.ceil(length / spacing)),
    )

    travel_yaw = math.atan2(
        delta_y,
        delta_x,
    )

    # 两端已经作为关键点加入，只添加中间位置。
    for index in range(1, divisions):
        ratio = index / divisions

        append_priority_candidate(
            (
                f"route_dense_{segment_name}_"
                f"{index:02d}"
            ),
            start[0] + ratio * delta_x,
            start[1] + ratio * delta_y,
            travel_yaw,
            (
                0,
                180,
                -60,
                60,
                -120,
                120,
            ),
        )


# 原直线坡道。
append_segment_anchors(
    "straight",
    "start",
    "end",
)

# 新转弯路线。
append_segment_anchors(
    "start_turn1",
    "start",
    "turn_1",
)
append_segment_anchors(
    "turn1_turn2",
    "turn_1",
    "turn_2",
)
append_segment_anchors(
    "turn2_turn3",
    "turn_2",
    "turn_3",
)
append_segment_anchors(
    "turn3_end",
    "turn_3",
    "end",
)


for index, candidate in enumerate(
    result.get("coarse_candidates", []),
    1,
):
    candidates.append(
        {
            "name": f"coarse_{index:02d}",
            "x": float(candidate["x"]),
            "y": float(candidate["y"]),
            "yaw": float(candidate["yaw"]),
            "source_score": float(
                candidate["correlation"]
            ),
        }
    )

for index, candidate in enumerate(
    result.get("refined_candidates", []),
    1,
):
    candidates.append(
        {
            "name": f"refined_{index:02d}",
            "x": float(candidate["x"]),
            "y": float(candidate["y"]),
            "yaw": float(candidate["yaw"]),
            "source_score": float(
                candidate["inlier_30"]
            ),
        }
    )

# 去掉几乎相同的候选，但保留粗候选优先级。
unique = []

for candidate in candidates:
    duplicate = False

    for previous in unique:
        distance = math.hypot(
            candidate["x"] - previous["x"],
            candidate["y"] - previous["y"],
        )

        yaw_difference = abs(
            angle_difference(
                candidate["yaw"],
                previous["yaw"],
            )
        )

        if (
            distance < 0.30
            and yaw_difference < math.radians(8)
        ):
            duplicate = True
            break

    if not duplicate:
        unique.append(candidate)

# 官方SLAM对初始朝向较敏感。先从粗搜索和精搜索中
# 交替选择位置种子，再为每个位置尝试完整的多朝向初值。
coarse_seeds = [
    candidate
    for candidate in unique
    if candidate["name"].startswith("coarse_")
]

refined_seeds = [
    candidate
    for candidate in unique
    if candidate["name"].startswith("refined_")
]

priority_seeds = [
    candidate
    for candidate in unique
    if (
        candidate["name"] == "last_pose"
        or candidate["name"].startswith(
            "route_key_"
        )
        or candidate["name"].startswith(
            "route_dense_"
        )
    )
]

ordered_seeds = list(priority_seeds)

for index in range(
    max(len(coarse_seeds), len(refined_seeds))
):
    if index < len(coarse_seeds):
        ordered_seeds.append(coarse_seeds[index])

    if index < len(refined_seeds):
        ordered_seeds.append(refined_seeds[index])

position_seeds = []

for candidate in ordered_seeds:
    duplicate_position = any(
        math.hypot(
            candidate["x"] - previous["x"],
            candidate["y"] - previous["y"],
        ) < 0.35
        for previous in position_seeds
    )

    if duplicate_position:
        continue

    position_seeds.append(candidate)

    if len(position_seeds) >= 64:
        break

# GLOBAL_ROUTE_YAW_EXPANSION_V1
# 按位置优先展开：
# 先完整验证上次姿态，再验证起点、终点和路线锚点，
# 最后才轮到离线点云匹配候选。
default_yaw_offsets = (
    -30,
    0,
    30,
    -60,
    60,
    -90,
    90,
    -120,
    120,
    -150,
    150,
    180,
)

expanded_candidates = []

for candidate in position_seeds:
    offsets = candidate.get(
        "yaw_offsets_degrees",
        default_yaw_offsets,
    )

    for offset_degrees in offsets:
        offset_radians = math.radians(
            offset_degrees
        )

        expanded = dict(candidate)

        expanded["yaw"] = math.atan2(
            math.sin(
                candidate["yaw"]
                + offset_radians
            ),
            math.cos(
                candidate["yaw"]
                + offset_radians
            ),
        )

        expanded["base_yaw"] = (
            candidate["yaw"]
        )
        expanded["yaw_offset_degrees"] = (
            offset_degrees
        )

        if offset_degrees == 0:
            suffix = "base"
        else:
            suffix = (
                f"{offset_degrees:+d}deg"
            )

        expanded["name"] = (
            f"{candidate['name']}_{suffix}"
        )

        expanded_candidates.append(
            expanded
        )

unique = expanded_candidates


# GLOBAL_BOOT_SEARCH_PRIORITY_V1
# 开机全局定位候选优先级：
# 1 起点，2 终点，3 全部路线点，4 最近成功许可，5 其它地图候选。
def _boot_candidate_priority(candidate):
    name = str(candidate.get("name", ""))

    if (
        "route_key_start" in name
        or name.startswith("start")
        or "straight_00" in name
    ):
        return (0, name)

    if (
        "route_key_end" in name
        or name.startswith("end")
        or "straight_17" in name
    ):
        return (1, name)

    if name.startswith("route_key_"):
        return (2, name)

    if name.startswith("route_dense_"):
        return (3, name)

    if (
        name == "last_pose"
        or name.startswith("last_pose")
        or name.startswith("last_ready")
        or "last_localization" in name
    ):
        return (4, name)

    return (9, name)


try:
    candidates.sort(key=_boot_candidate_priority)
except NameError:
    pass


print("位置种子数量：", len(position_seeds))
print(
    "候选朝向：按历史姿态、关键点、"
    "稠密锚点和离线候选分别配置"
)





# GLOBAL_START_ONLY_LIST_V2
# 最终搜索列表只保留坡道起点3米范围内候选。
# 终点、转弯点、路线中点、全图其它点全部不参与本次开机验证。
import math as _g1_start_only_math

_start_x = 0.024735889031391838
_start_y = -0.08662520735348705
_start_radius_m = 3.0

def _g1_candidate_xy(candidate):
    for key_x, key_y in (
        ("x", "y"),
        ("initial_x", "initial_y"),
        ("pose_x", "pose_y"),
    ):
        if key_x in candidate and key_y in candidate:
            return (
                float(candidate[key_x]),
                float(candidate[key_y]),
            )

    pose = candidate.get("pose")
    if isinstance(pose, dict):
        if "x" in pose and "y" in pose:
            return (
                float(pose["x"]),
                float(pose["y"]),
            )

    return None

_start_only_unique = []

    # STRICT_START_NAME_FILTER_V1
for candidate in unique:
    name = str(candidate.get("name", ""))

    # 只保留固定起点以及离线生成的起点附近候选。
    # 明确排除终点、转弯点、路线中间点和历史位置。
    if (
        name.startswith("route_key_end")
        or name.startswith("route_key_turn")
        or name.startswith("route_dense_")
        or name.startswith("last_pose")
        or name.startswith("last_ready")
        or "last_localization" in name
    ):
        continue

    # 其它固定路线关键点也全部排除，
    # 唯一允许的固定关键点是route_key_start。
    if (
        name.startswith("route_key_")
        and not name.startswith("route_key_start")
    ):
        continue

    xy = _g1_candidate_xy(candidate)

    if xy is None:
        continue

    x, y = xy

    distance = _g1_start_only_math.hypot(
        x - _start_x,
        y - _start_y,
    )

    if distance <= _start_radius_m:
        candidate["_start_distance_m"] = distance
        _start_only_unique.append(candidate)

_start_only_unique.sort(
    key=lambda item: (
        float(item.get("_start_distance_m", 999.0)),
        str(item.get("name", "")),
    )
)

print(
    "起点3米搜索列表：",
    len(unique),
    "->",
    len(_start_only_unique),
)

if (
    not _start_only_unique
    and os.environ.get(
        "G1_FIXED_START_FAST_BOOT",
        "0",
    ) != "1"
):
    raise SystemExit(
        "起点3米范围内没有候选，停止本次开机定位"
    )

_start_base_candidates = [
    candidate
    for candidate in _start_only_unique
    if str(candidate.get("name", ""))
    == "route_key_start_base"
]

_start_other_candidates = [
    candidate
    for candidate in _start_only_unique
    if str(candidate.get("name", "")).startswith(
        "route_key_start_"
    )
    and str(candidate.get("name", ""))
    != "route_key_start_base"
]

_start_nearby_candidates = [
    candidate
    for candidate in _start_only_unique
    if not str(
        candidate.get("name", "")
    ).startswith("route_key_start_")
]

unique = (
    _start_base_candidates
    + _start_other_candidates
    + _start_nearby_candidates
)[:24]

print(
    "起点最终验证顺序：",
    [
        candidate.get("name", "")
        for candidate in unique
    ],
)


# FIXED_START_FAST_BOOT_V5
# FIXED_START_36_CANDIDATES_V2
# 仅搜索固定起点0.5米以内。
# 6个位置 × 6个面向终点附近朝向 = 36个候选。
if os.environ.get(
    "G1_FIXED_START_FAST_BOOT",
    "0",
) == "1":
    start_x = float(
        os.environ.get(
            "G1_FIXED_START_X",
            "0.024735889031391838",
        )
    )
    start_y = float(
        os.environ.get(
            "G1_FIXED_START_Y",
            "-0.08662520735348705",
        )
    )
    base_yaw = float(
        os.environ.get(
            "G1_FIXED_START_YAW",
            "-0.3986063585212273",
        )
    )

    # 新地图固定坡道起点。
    # 第一项是人工采集姿态，第二项是官方SLAM
    # 优化后的历史姿态，其余为12厘米小范围候选。
    fixed_positions = (
        (start_x, start_y),
        (start_x + 0.08, start_y + 0.08),
        (start_x + 0.12, start_y),
        (start_x - 0.12, start_y),
        (start_x, start_y + 0.12),
        (start_x, start_y - 0.12),
    )

    # 所有候选均保持在新共同起点附近，
    # 不再使用旧地图优化姿态。
    yaw_candidates = (
        ("base", base_yaw),
        ("m05", base_yaw + math.radians(-5.0)),
        ("p05", base_yaw + math.radians(5.0)),
        ("m10", base_yaw + math.radians(-10.0)),
        ("p10", base_yaw + math.radians(10.0)),
        ("m15", base_yaw + math.radians(-15.0)),
    )

    unique = []

    for position_index, position in enumerate(
        fixed_positions,
        1,
    ):
        distance = math.hypot(
            position[0] - start_x,
            position[1] - start_y,
        )

        if distance > 0.5:
            continue

        for yaw_name, candidate_yaw in yaw_candidates:
            unique.append(
                {
                    "name": (
                        f"fixed_start_"
                        f"p{position_index:02d}_"
                        f"yaw_{yaw_name}"
                    ),
                    "x": float(position[0]),
                    "y": float(position[1]),
                    "yaw": float(candidate_yaw),
                    "distance_to_start": distance,
                }
            )

    print(
        "固定起点36候选验证顺序：",
        [
            (
                item["name"],
                round(item["x"], 4),
                round(item["y"], 4),
                round(item["yaw"], 4),
            )
            for item in unique
        ],
    )


print("待官方验证候选数量：", len(unique))


def cli_environment():
    environment = os.environ.copy()

    environment["PYTHONPATH"] = (
        str(PROJECT / "vendor")
        + ":"
        + os.environ.get(
            "UNITREE_SDK2_PYTHON_PATH",
            "/home/unitree/unitree_sdk2_python",
        )
    )
    environment["CYCLONEDDS_HOME"] = (
        os.environ.get(
            "CYCLONEDDS_COMPAT_PREFIX",
            "/home/unitree/cyclonedds-prefix",
        )
    )
    environment["LD_LIBRARY_PATH"] = (
        environment["CYCLONEDDS_HOME"] + "/lib"
    )
    environment.pop("CYCLONEDDS_URI", None)

    return environment


def initialize(x, y, yaw):
    # argparse不能可靠处理“-0.0”位置参数。
    x = 0.0 if abs(float(x)) < 1e-8 else float(x)
    y = 0.0 if abs(float(y)) < 1e-8 else float(y)
    yaw = 0.0 if abs(float(yaw)) < 1e-8 else float(yaw)

    command = [
        "/usr/bin/python3",
        str(PROJECT / "scripts/g1_slam_cli.py"),
        args.interface,
        "initialize",
        "--",
        args.map,
        str(x),
        str(y),
        str(yaw),
    ]

    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT,
            env=cli_environment(),
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print(
            "候选初始化超过30秒，"
            "跳过当前候选"
        )
        return False

    if completed.stdout.strip():
        print(completed.stdout.strip())

    if completed.stderr.strip():
        print(completed.stderr.strip())

    return completed.returncode == 0


samples = []


def odom_callback(message):
    position = message.pose.pose.position
    quaternion = message.pose.pose.orientation

    yaw = math.atan2(
        2.0 * (
            quaternion.w * quaternion.z
            + quaternion.x * quaternion.y
        ),
        1.0 - 2.0 * (
            quaternion.y * quaternion.y
            + quaternion.z * quaternion.z
        ),
    )

    samples.append(
        [position.x, position.y, yaw]
    )


def collect_pose(node, seconds=6.0):
    samples.clear()
    deadline = time.monotonic() + seconds

    while (
        time.monotonic() < deadline
        and len(samples) < 60
    ):
        rclpy.spin_once(
            node,
            timeout_sec=0.2,
        )

    if len(samples) < 15:
        print("重定位里程计样本不足：", len(samples))
        return None

    array = np.asarray(
        samples,
        dtype=np.float64,
    )

    x = float(np.median(array[:, 0]))
    y = float(np.median(array[:, 1]))

    yaw = math.atan2(
        float(np.mean(np.sin(array[:, 2]))),
        float(np.mean(np.cos(array[:, 2]))),
    )

    position_spread = float(
        np.max(
            np.hypot(
                array[:, 0] - x,
                array[:, 1] - y,
            )
        )
    )

    yaw_spread = float(
        np.max(
            np.abs(
                np.arctan2(
                    np.sin(array[:, 2] - yaw),
                    np.cos(array[:, 2] - yaw),
                )
            )
        )
    )

    return {
        "x": x,
        "y": y,
        "yaw": yaw,
        "samples": len(samples),
        "position_spread": position_spread,
        "yaw_spread": yaw_spread,
    }


rclpy.init()
node = rclpy.create_node(
    "g1_global_candidate_verifier"
)

subscription = node.create_subscription(
    Odometry,
    "/unitree/slam_relocation/odom",
    odom_callback,
    qos_profile_sensor_data,
)

accepted = None

try:
    for index, candidate in enumerate(unique, 1):
        print()
        print(
            f"===== 官方验证 {index}/{len(unique)} "
            f"{candidate['name']} ====="
        )
        print(
            "初值：",
            round(candidate["x"], 4),
            round(candidate["y"], 4),
            round(candidate["yaw"], 4),
        )

        # argparse会把字符串“-0.0”误当作命令选项，
        # 导致最后的yaw位置参数被判定为缺失。
        for coordinate in ("x", "y", "yaw"):
            value = float(candidate[coordinate])

            if abs(value) < 1e-9:
                value = 0.0

            candidate[coordinate] = value

        if not initialize(
            candidate["x"],
            candidate["y"],
            candidate["yaw"],
        ):
            print("官方服务拒绝候选")
            time.sleep(
                CANDIDATE_REJECT_DELAY_SECONDS
            )
            continue

        print("官方服务接受初值，等待优化")
        time.sleep(4)

        first = collect_pose(node)

        if first is None:
            continue

        print(
            "第一次优化：",
            round(first["x"], 4),
            round(first["y"], 4),
            round(first["yaw"], 4),
            "波动=",
            round(first["position_spread"], 4),
            "米",
        )

        # SINGLE_STABLE_LOCALIZATION_V1
        # 官方SLAM已经接受初值并持续发布稳定里程计后，
        # 直接认定本次开机定位成功。
        # 不再把优化结果二次提交给官方SLAM，
        # 避免正在重定位时再次initialize返回509。
        first_stable = (
            first["position_spread"] <= 0.08
            and math.degrees(
                first["yaw_spread"]
            ) <= 5.0
            and first["samples"] >= 20
        )

        if not first_stable:
            print(
                "第一次优化姿态不稳定，"
                "继续验证下一个候选"
            )
            continue

        accepted = {
            "success": True,
            "boot_id": Path(
                "/proc/sys/kernel/random/boot_id"
            ).read_text(
                encoding="utf-8"
            ).strip(),
            "created_at_unix": time.time(),
            "map_path": args.map,
            "candidate": candidate,
            "pose": {
                "x": first["x"],
                "y": first["y"],
                "yaw": first["yaw"],
            },
            "verification": {
                "method": (
                    "official_initialization_"
                    "single_stable_pose"
                ),
                "position_spread_meters": (
                    first["position_spread"]
                ),
                "yaw_spread_degrees": math.degrees(
                    first["yaw_spread"]
                ),
                "repeat_distance_meters": 0.0,
                "repeat_yaw_degrees": 0.0,
                "samples": first["samples"],
            },
        }

        print(
            "官方首次定位稳定，"
            "本次开机定位验证成功"
        )
        break
finally:
    node.destroy_node()

    if rclpy.ok():
        rclpy.shutdown()

if accepted is None:
    print()
    print("所有候选均未通过官方重复定位验证")
    raise SystemExit(1)

temporary = ready_path.with_suffix(".tmp")

temporary.write_text(
    json.dumps(
        accepted,
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)

temporary.replace(ready_path)

print()
print("===== 无人定位验证成功 =====")
print(
    "全局姿态：",
    round(accepted["pose"]["x"], 4),
    round(accepted["pose"]["y"], 4),
    round(accepted["pose"]["yaw"], 4),
)
print("许可文件：", ready_path)
