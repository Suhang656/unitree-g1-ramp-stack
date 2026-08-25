#!/usr/bin/env python3
"""Token-protected G1 web control panel backed by the existing ROS 2 bridge."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import math
import re
import secrets
import signal
import threading
import time
from collections import OrderedDict, deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from uuid import uuid4


PROJECT = Path(os.environ.get("G1_PROJECT_DIR", "/home/unitree/智能中控"))
STATIC_ROOT = PROJECT / "static" / "g1-control"
TOKEN_PATH = PROJECT / "data" / "web_control" / "access_token"
ROTATE_TOKEN_PATH = PROJECT / "data" / "web_control" / "rotate_on_restart"
READY_PATH = PROJECT / "data" / "ramp_platform_v3" / "localization_ready.json"
ODOM_PATH = Path("/run/g1-ramp/odom.json")
BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")
WAYPOINT_ROOT = PROJECT / "data" / "embodied_lab_panorama_v2"
EXPECTED_MAP_PATH = os.environ.get(
    "G1_INTERNAL_MAP_PATH",
    "/home/unitree/g1_internal_panorama_v2.pcd",
)
WAYPOINT_NAME_PATTERN = re.compile(r"[A-Za-z0-9_\-\u4e00-\u9fff]{1,40}")
WAYPOINT_TOPIC = "/unitree/slam_relocation/odom"
WAYPOINT_SAMPLE_COUNT = 50
WAYPOINT_TIMEOUT_SECONDS = 40.0
WAYPOINT_MAX_SPREAD_METERS = 0.05
TOUR_CONFIG_PATH = WAYPOINT_ROOT / "tour_config.json"
TOUR_POINT_NAMES = ("guide_1", "guide_2", "guide_3")
MAX_TOUR_POINTS = 20
GUIDE_1_TRIGGER = "下面我将展示爬坡行走"

DEFAULT_TOUR_STATIONS: dict[str, dict[str, str]] = {
    "guide_1": {
        "display_name": "坡道行走展示",
        "speech": (
            "这里是坡道行走展示区。"
            "下面我将展示爬坡行走"
        ),
    },
    "guide_2": {
        "display_name": "灵巧手展示",
        "speech": "这里是灵巧手展示区，请观看灵巧手的操作展示。",
    },
    "guide_3": {
        "display_name": "机器人与机器狗展示",
        "speech": "这里展示的是机器人与机器狗，请观看它们的协同展示。",
    },
}

RAMP_COMMAND_IDS = {
    "ramp_prepare",
    "straight_forward",
    "straight_return",
    "turning_forward",
    "turning_return",
}

COMMANDS: OrderedDict[str, dict[str, Any]] = OrderedDict(
    [
        (
            "ramp_prepare",
            {
                "label": "准备到起点",
                "category": "ramp",
                "description": "使用官方导航前往坡道起点",
                "payload": {"action": "move", "target": "ramp_prepare", "speed": 0.22},
            },
        ),
        (
            "straight_forward",
            {
                "label": "直线前进",
                "category": "ramp",
                "description": "从起点沿直线路线到固定终点",
                "payload": {"action": "move", "target": "continuous_forward", "speed": 0.22},
            },
        ),
        (
            "straight_return",
            {
                "label": "直线返回",
                "category": "ramp",
                "description": "从终点沿直线路线返回起点",
                "payload": {"action": "move", "target": "ramp_return", "speed": 0.22},
            },
        ),
        (
            "turning_forward",
            {
                "label": "转弯前进",
                "category": "ramp",
                "description": "依次经过三个转弯路线点前往终点",
                "payload": {"action": "move", "target": "turning_forward", "speed": 0.22},
            },
        ),
        (
            "turning_return",
            {
                "label": "转弯返回",
                "category": "ramp",
                "description": "沿转弯路线反向返回起点",
                "payload": {"action": "move", "target": "turning_return", "speed": 0.22},
            },
        ),
        (
            "mode_ready",
            {
                "label": "预备模式",
                "category": "mode",
                "description": "进入锁定站立预备状态",
                "payload": {"action": "mode", "target": "ready"},
            },
        ),
        (
            "mode_stand",
            {
                "label": "站立模式",
                "category": "mode",
                "description": "恢复常规平衡站立",
                "payload": {"action": "mode", "target": "stand"},
            },
        ),
        (
            "mode_sport",
            {
                "label": "走跑模式",
                "category": "mode",
                "description": "进入走跑运动模式",
                "payload": {"action": "mode", "target": "sport"},
            },
        ),
        (
            "mode_squat",
            {
                "label": "下蹲模式",
                "category": "mode",
                "description": "机器人将降低身体，请确认周围安全",
                "payload": {"action": "mode", "target": "squat"},
                "warning": True,
            },
        ),
        (
            "mode_sit",
            {
                "label": "落座模式",
                "category": "mode",
                "description": "机器人将进入落座姿态",
                "payload": {"action": "mode", "target": "sit"},
                "warning": True,
            },
        ),
        (
            "mode_damp",
            {
                "label": "阻尼模式",
                "category": "mode",
                "description": "停止主动运动并进入阻尼状态",
                "payload": {"action": "mode", "target": "damp"},
                "warning": True,
            },
        ),
    ]
)

GESTURES = OrderedDict(
    [
        ("turn_back_wave", "转身挥手"),
        ("two_hand_kiss", "双手飞吻"),
        ("left_kiss", "左手飞吻"),
        ("right_kiss", "右手飞吻"),
        ("both_hands_up", "举双手"),
        ("clap", "鼓掌"),
        ("high_five", "击掌"),
        ("hug", "拥抱"),
        ("heart", "双手比心"),
        ("right_heart", "右手比心"),
        ("refuse", "拒绝动作"),
        ("right_hand_up", "举右手"),
        ("ultraman_ray", "双手打叉"),
        ("face_wave", "胸前挥手"),
        ("high_wave", "高举挥手"),
        ("handshake_start", "开始握手"),
        ("handshake_end", "结束握手"),
        ("release_arm", "释放手臂"),
    ]
)

for target, label in GESTURES.items():
    COMMANDS[f"gesture_{target}"] = {
        "label": label,
        "category": "gesture",
        "description": "G1 官方 ArmAction",
        "payload": {"action": "gesture", "target": target},
    }


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def ensure_token() -> str:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    rotate = ROTATE_TOKEN_PATH.exists()
    try:
        token = TOKEN_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        token = ""
    if rotate:
        token = ""
    if len(token) < 24:
        token = secrets.token_urlsafe(32)
        temporary = TOKEN_PATH.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(token + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(TOKEN_PATH)
    os.chmod(TOKEN_PATH, 0o600)
    ROTATE_TOKEN_PATH.unlink(missing_ok=True)
    return token


class ControlState:
    def __init__(self, token: str) -> None:
        self.token = token
        self.lock = threading.Lock()
        self.results: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.latest_result: dict[str, Any] | None = None
        self.publisher: Any = None
        self.tour_publisher: Any = None
        self.last_action_time = 0.0
        self.odom_condition = threading.Condition()
        self.odom_samples: deque[dict[str, float]] = deque(maxlen=400)
        self.waypoint_capture_lock = threading.Lock()
        self.tour_config_lock = threading.RLock()

    def set_publisher(self, publisher: Any) -> None:
        self.publisher = publisher

    def set_tour_publisher(self, publisher: Any) -> None:
        self.tour_publisher = publisher

    @staticmethod
    def _default_tour_config() -> dict[str, Any]:
        return {
            "version": 1,
            "map_path": EXPECTED_MAP_PATH,
            "order": list(TOUR_POINT_NAMES),
            "stations": {
                name: dict(value)
                for name, value in DEFAULT_TOUR_STATIONS.items()
            },
            "updated_at_unix": time.time(),
        }

    def _validated_tour_config(
        self,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        order = value.get("order")
        if (
            not isinstance(order, list)
            or not 1 <= len(order) <= MAX_TOUR_POINTS
        ):
            raise ValueError("导览路线须包含1至20个点位")
        clean_order = [str(name).strip() for name in order]
        if len(set(clean_order)) != len(clean_order):
            raise ValueError("导览路线中存在重复点位")
        for name in clean_order:
            self._validate_waypoint_name(name)
        if "guide_1" not in clean_order:
            raise ValueError("guide_1是坡道待命安全点，不能从路线中删除")

        stations = value.get("stations")
        if not isinstance(stations, dict):
            raise ValueError("导览讲解配置无效")

        cleaned_stations: dict[str, dict[str, str]] = {}
        for name in clean_order:
            station = stations.get(name)
            if not isinstance(station, dict):
                raise ValueError(f"缺少{name}的讲解配置")
            display_name = str(station.get("display_name", "")).strip()
            speech = str(station.get("speech", "")).strip()
            if not display_name or len(display_name) > 40:
                raise ValueError(f"{name}的显示名称须为1至40个字符")
            if not speech or len(speech) > 1000:
                raise ValueError(f"{name}的播报内容须为1至1000个字符")
            cleaned_stations[name] = {
                "display_name": display_name,
                "speech": speech,
            }

        for name in clean_order:
            point = read_json(WAYPOINT_ROOT / f"{name}.json")
            if not point or not all(key in point for key in ("x", "y", "yaw")):
                raise ValueError(f"尚未采集导览点{name}")
            if point.get("map_path") not in (None, EXPECTED_MAP_PATH):
                raise ValueError(f"{name}不属于当前全景地图")

        return {
            "version": 1,
            "map_path": EXPECTED_MAP_PATH,
            "order": clean_order,
            "stations": cleaned_stations,
            "updated_at_unix": time.time(),
        }

    def read_tour_config(self) -> dict[str, Any]:
        value = read_json(TOUR_CONFIG_PATH)
        if value is None:
            value = self._default_tour_config()
            TOUR_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            temporary = TOUR_CONFIG_PATH.with_suffix(
                f".{os.getpid()}.tmp"
            )
            temporary.write_text(
                json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(TOUR_CONFIG_PATH)
        validated = self._validated_tour_config(value)
        points: dict[str, dict[str, Any]] = {}
        for name in validated["order"]:
            point = read_json(WAYPOINT_ROOT / f"{name}.json") or {}
            points[name] = {
                "x": point.get("x"),
                "y": point.get("y"),
                "yaw": point.get("yaw"),
                "yaw_degrees": point.get("yaw_degrees"),
                "please_first": True,
                "ramp_demo": name == "guide_1",
            }
        validated["points"] = points
        validated["guide_1_fixed_trigger"] = GUIDE_1_TRIGGER
        return validated

    def save_tour_config(self, value: dict[str, Any]) -> dict[str, Any]:
        with self.tour_config_lock:
            validated = self._validated_tour_config(value)
            TOUR_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            if TOUR_CONFIG_PATH.exists():
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                backup = TOUR_CONFIG_PATH.with_name(
                    f"{TOUR_CONFIG_PATH.name}.before_{timestamp}"
                )
                backup.write_bytes(TOUR_CONFIG_PATH.read_bytes())
            temporary = TOUR_CONFIG_PATH.with_suffix(f".{os.getpid()}.tmp")
            temporary.write_text(
                json.dumps(validated, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(TOUR_CONFIG_PATH)
            return self.read_tour_config()

    def add_tour_station(
        self,
        requested_name: str,
        display_name: str,
        speech: str,
    ) -> dict[str, Any]:
        name = self._validate_waypoint_name(requested_name)
        display_name = display_name.strip()
        speech = speech.strip()
        if not display_name or len(display_name) > 40:
            raise ValueError("显示名称须为1至40个字符")
        if not speech or len(speech) > 1000:
            raise ValueError("播报内容须为1至1000个字符")
        with self.tour_config_lock:
            config = self.read_tour_config()
            if name in config["order"]:
                raise ValueError("同名导览点已存在，请直接编辑后保存")
            if len(config["order"]) >= MAX_TOUR_POINTS:
                raise ValueError("导览点已达到20个上限")
            point = self.capture_waypoint(name)
            config["order"].append(name)
            config["stations"][name] = {
                "display_name": display_name,
                "speech": speech,
            }
            saved = self.save_tour_config(config)
            return {"success": True, "point": point, "config": saved}

    def delete_tour_station(self, requested_name: str) -> dict[str, Any]:
        name = self._validate_waypoint_name(requested_name)
        if name == "guide_1":
            raise ValueError("guide_1是坡道待命安全点，不能删除")
        with self.tour_config_lock:
            config = self.read_tour_config()
            if name not in config["order"]:
                raise ValueError("导览点不在当前路线中")
            config["order"] = [
                value for value in config["order"] if value != name
            ]
            config["stations"].pop(name, None)
            saved = self.save_tour_config(config)
            point_path = WAYPOINT_ROOT / f"{name}.json"
            archived = None
            if point_path.exists():
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                archived_path = point_path.with_name(
                    f"{point_path.name}.deleted_{timestamp}"
                )
                point_path.replace(archived_path)
                archived = str(archived_path)
            return {
                "success": True,
                "deleted": name,
                "archived_point": archived,
                "config": saved,
            }

    def reserve_action(self, is_stop: bool) -> bool:
        """Reject accidental double-submits while always allowing emergency stop."""
        if is_stop:
            return True
        now = time.monotonic()
        with self.lock:
            if now - self.last_action_time < 1.0:
                return False
            self.last_action_time = now
        return True

    def update_result(self, result: dict[str, Any]) -> None:
        task_id = str(result.get("task_id", ""))
        with self.lock:
            self.latest_result = result
            if task_id:
                self.results[task_id] = result
                self.results.move_to_end(task_id)
                while len(self.results) > 100:
                    self.results.popitem(last=False)

    def update_odom(self, message: Any) -> None:
        orientation = message.pose.pose.orientation
        sin_yaw = 2.0 * (
            orientation.w * orientation.z
            + orientation.x * orientation.y
        )
        cos_yaw = 1.0 - 2.0 * (
            orientation.y * orientation.y
            + orientation.z * orientation.z
        )
        position = message.pose.pose.position
        sample = {
            "x": float(position.x),
            "y": float(position.y),
            "yaw": math.atan2(sin_yaw, cos_yaw),
            "received_monotonic": time.monotonic(),
        }
        with self.odom_condition:
            self.odom_samples.append(sample)
            self.odom_condition.notify_all()

    @staticmethod
    def _validate_waypoint_name(name: str) -> str:
        name = name.strip()
        if not WAYPOINT_NAME_PATTERN.fullmatch(name):
            raise ValueError(
                "名称须为1至40位中文、英文、数字、下划线或短横线"
            )
        return name

    @staticmethod
    def _localization_ready() -> dict[str, Any]:
        ready = read_json(READY_PATH)
        try:
            boot_id = BOOT_ID_PATH.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError("无法读取本次开机标识") from exc
        if not ready or ready.get("success") is not True:
            raise RuntimeError("本次开机全局定位尚未成功")
        if ready.get("boot_id") != boot_id:
            raise RuntimeError("定位许可不属于本次开机")
        if ready.get("map_path") != EXPECTED_MAP_PATH:
            raise RuntimeError("当前定位地图不是具身智能实验场地全景图")
        return ready

    def list_waypoints(self) -> list[dict[str, Any]]:
        WAYPOINT_ROOT.mkdir(parents=True, exist_ok=True)
        values: list[dict[str, Any]] = []
        for path in sorted(WAYPOINT_ROOT.glob("*.json")):
            value = read_json(path)
            if not value or not all(key in value for key in ("x", "y", "yaw")):
                continue
            values.append(
                {
                    "name": str(value.get("name") or path.stem),
                    "x": value["x"],
                    "y": value["y"],
                    "yaw": value["yaw"],
                    "yaw_degrees": value.get("yaw_degrees"),
                    "position_spread_meters": value.get(
                        "position_spread_meters"
                    ),
                    "created_at_unix": value.get("created_at_unix"),
                    "file": str(path),
                }
            )
        values.sort(
            key=lambda value: float(value.get("created_at_unix") or 0.0),
            reverse=True,
        )
        return values

    def capture_waypoint(self, requested_name: str) -> dict[str, Any]:
        name = self._validate_waypoint_name(requested_name)
        ready = self._localization_ready()
        if not self.waypoint_capture_lock.acquire(blocking=False):
            raise RuntimeError("已有点位正在采集，请等待完成")
        try:
            deadline = time.monotonic() + WAYPOINT_TIMEOUT_SECONDS
            samples: deque[dict[str, float]] = deque(
                maxlen=WAYPOINT_SAMPLE_COUNT
            )
            last_cache_timestamp = -1.0
            last_spread: float | None = None
            boot_id = BOOT_ID_PATH.read_text(encoding="utf-8").strip()

            # The motion web bridge deliberately uses Fast DDS, while the
            # official relocation odometry is received by the dedicated
            # CycloneDDS cache service. Sampling that boot-scoped cache keeps
            # action publishing unchanged and uses the already proven odom
            # path instead of creating a second incompatible subscription.
            while True:
                cache = read_json(ODOM_PATH)
                if cache and cache.get("boot_id") == boot_id:
                    try:
                        cache_timestamp = float(cache["updated_at_unix"])
                        cache_age = time.time() - cache_timestamp
                        x_value = float(cache["x"])
                        y_value = float(cache["y"])
                        yaw_value = float(cache["yaw"])
                    except (KeyError, TypeError, ValueError):
                        cache_timestamp = -1.0
                        cache_age = float("inf")
                    if (
                        cache_timestamp > last_cache_timestamp
                        and -0.25 <= cache_age <= 1.0
                    ):
                        samples.append(
                            {
                                "x": x_value,
                                "y": y_value,
                                "yaw": yaw_value,
                                "received_monotonic": time.monotonic(),
                            }
                        )
                        last_cache_timestamp = cache_timestamp

                if len(samples) == WAYPOINT_SAMPLE_COUNT:
                    window_xs = sorted(sample["x"] for sample in samples)
                    window_ys = sorted(sample["y"] for sample in samples)
                    middle = WAYPOINT_SAMPLE_COUNT // 2
                    window_x = (
                        window_xs[middle - 1] + window_xs[middle]
                    ) / 2.0
                    window_y = (
                        window_ys[middle - 1] + window_ys[middle]
                    ) / 2.0
                    last_spread = max(
                        math.hypot(
                            sample["x"] - window_x,
                            sample["y"] - window_y,
                        )
                        for sample in samples
                    )
                    if last_spread <= WAYPOINT_MAX_SPREAD_METERS:
                        break
                if time.monotonic() >= deadline:
                    detail = (
                        f"，最近窗口波动{last_spread:.3f}米"
                        if last_spread is not None
                        else ""
                    )
                    raise RuntimeError(
                        "等待稳定定位超时："
                        f"已有{len(samples)}/{WAYPOINT_SAMPLE_COUNT}帧"
                        f"{detail}；请保持G1静止并等待定位收敛后重试"
                    )
                time.sleep(0.02)

            samples = list(samples)
            xs = sorted(sample["x"] for sample in samples)
            ys = sorted(sample["y"] for sample in samples)
            count = len(samples)
            middle = count // 2
            x = (xs[middle - 1] + xs[middle]) / 2.0
            y = (ys[middle - 1] + ys[middle]) / 2.0
            yaw = math.atan2(
                sum(math.sin(sample["yaw"]) for sample in samples),
                sum(math.cos(sample["yaw"]) for sample in samples),
            )
            spread = max(
                math.hypot(sample["x"] - x, sample["y"] - y)
                for sample in samples
            )
            # The sliding window above guarantees this final sample set is
            # stable. Keep the value in the result for later quality audits.

            WAYPOINT_ROOT.mkdir(parents=True, exist_ok=True)
            output = WAYPOINT_ROOT / f"{name}.json"
            if output.exists():
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                output.replace(output.with_name(f"{output.name}.before_{timestamp}"))
            result = {
                "success": True,
                "name": name,
                "samples": count,
                "x": x,
                "y": y,
                "yaw": yaw,
                "yaw_degrees": math.degrees(yaw),
                "position_spread_meters": spread,
                "created_at_unix": time.time(),
                "boot_id": boot_id,
                "map_path": EXPECTED_MAP_PATH,
                "localization_pose": ready.get("pose"),
                "localization_created_at_unix": ready.get("created_at_unix"),
                "source": "g1_web_control",
            }
            temporary = output.with_suffix(f".{os.getpid()}.tmp")
            temporary.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(output)
            result["file"] = str(output)
            return result
        finally:
            self.waypoint_capture_lock.release()

    def get_result(self, task_id: str) -> dict[str, Any] | None:
        with self.lock:
            value = self.results.get(task_id)
            return dict(value) if value else None

    def status(self) -> dict[str, Any]:
        boot_id = BOOT_ID_PATH.read_text(encoding="utf-8").strip()
        ready = read_json(READY_PATH)
        localized = bool(
            ready
            and ready.get("success") is True
            and ready.get("boot_id") == boot_id
        )
        odom = read_json(ODOM_PATH)
        odom_age = None
        if odom and odom.get("updated_at_unix") is not None:
            odom_age = max(0.0, time.time() - float(odom["updated_at_unix"]))
        publisher = self.publisher
        subscribers = int(publisher.get_subscription_count()) if publisher else 0
        tour_publisher = self.tour_publisher
        tour_subscribers = (
            int(tour_publisher.get_subscription_count())
            if tour_publisher
            else 0
        )
        with self.lock:
            latest = dict(self.latest_result) if self.latest_result else None
        return {
            "online": subscribers > 0,
            "request_subscribers": subscribers,
            "tour_online": tour_subscribers > 0,
            "tour_request_subscribers": tour_subscribers,
            "localized": localized,
            "pose": ready.get("pose") if localized and ready else None,
            "odom": odom,
            "odom_age_seconds": round(odom_age, 3) if odom_age is not None else None,
            "latest_result": latest,
            "server_time_unix": time.time(),
        }


class Handler(BaseHTTPRequestHandler):
    server_version = "G1WebControl/1.0"

    @property
    def control(self) -> ControlState:
        return self.server.control  # type: ignore[attr-defined]

    def log_message(self, format_string: str, *args: Any) -> None:
        if self.command == "GET" and self.path.startswith(
            ("/api/status", "/api/results/")
        ):
            return
        print(
            f"WEB {self.client_address[0]} " + format_string % args,
            flush=True,
        )

    def _authorized(self) -> bool:
        supplied = self.headers.get("X-G1-Control-Token", "")
        if not supplied:
            authorization = self.headers.get("Authorization", "")
            if authorization.startswith("Bearer "):
                supplied = authorization[7:]
        return hmac.compare_digest(supplied, self.control.token)

    def _headers(self, status: int, content_type: str, length: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'",
        )
        self.end_headers()

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(content))
        self.wfile.write(content)

    def _serve(self, relative: str, content_type: str) -> None:
        path = (STATIC_ROOT / relative).resolve()
        if STATIC_ROOT.resolve() not in path.parents:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._headers(HTTPStatus.OK, content_type, len(content))
        self.wfile.write(content)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path in {"/", "/index.html"}:
            self._serve("index.html", "text/html; charset=utf-8")
            return
        if path == "/control.css":
            self._serve("control.css", "text/css; charset=utf-8")
            return
        if path == "/control.js":
            self._serve("control.js", "text/javascript; charset=utf-8")
            return
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "访问令牌无效"})
            return
        if path == "/api/commands":
            commands = []
            for command_id, command in COMMANDS.items():
                commands.append(
                    {
                        "id": command_id,
                        "label": command["label"],
                        "category": command["category"],
                        "description": command["description"],
                        "warning": bool(command.get("warning")),
                    }
                )
            self._json(HTTPStatus.OK, {"commands": commands})
            return
        if path == "/api/status":
            self._json(HTTPStatus.OK, self.control.status())
            return
        if path == "/api/waypoints":
            self._json(
                HTTPStatus.OK,
                {"waypoints": self.control.list_waypoints()},
            )
            return
        if path == "/api/tour/config":
            try:
                config = self.control.read_tour_config()
            except ValueError as exc:
                self._json(HTTPStatus.CONFLICT, {"error": str(exc)})
                return
            self._json(HTTPStatus.OK, config)
            return
        prefix = "/api/results/"
        if path.startswith(prefix):
            task_id = path[len(prefix) :]
            result = self.control.get_result(task_id)
            if result is None:
                self._json(HTTPStatus.OK, {"task_id": task_id, "state": "queued"})
            else:
                self._json(HTTPStatus.OK, result)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in {
            "/api/actions",
            "/api/waypoints/mark",
            "/api/tour/config",
            "/api/tour/visit",
            "/api/tour/stations/add",
            "/api/tour/stations/delete",
        }:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "访问令牌无效"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length < 1 or length > 16384:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "请求大小无效"})
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "请求不是有效JSON"})
            return
        if path == "/api/waypoints/mark":
            try:
                result = self.control.capture_waypoint(str(body.get("name", "")))
            except ValueError as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            except RuntimeError as exc:
                self._json(HTTPStatus.CONFLICT, {"error": str(exc)})
                return
            except OSError as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": f"保存点位失败：{exc}"},
                )
                return
            self._json(HTTPStatus.CREATED, result)
            return
        if path == "/api/tour/config":
            try:
                result = self.control.save_tour_config(body)
            except ValueError as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            except OSError as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": f"保存导览配置失败：{exc}"},
                )
                return
            self._json(HTTPStatus.OK, result)
            return
        if path == "/api/tour/stations/add":
            try:
                result = self.control.add_tour_station(
                    str(body.get("name", "")),
                    str(body.get("display_name", "")),
                    str(body.get("speech", "")),
                )
            except ValueError as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            except RuntimeError as exc:
                self._json(HTTPStatus.CONFLICT, {"error": str(exc)})
                return
            except OSError as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": f"新增导览点失败：{exc}"},
                )
                return
            self._json(HTTPStatus.CREATED, result)
            return
        if path == "/api/tour/stations/delete":
            if body.get("confirmed") is not True:
                self._json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "删除导览点尚未确认"},
                )
                return
            try:
                result = self.control.delete_tour_station(
                    str(body.get("point_name", ""))
                )
            except ValueError as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            except OSError as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": f"删除导览点失败：{exc}"},
                )
                return
            self._json(HTTPStatus.OK, result)
            return
        if path == "/api/tour/visit":
            point_name = str(body.get("point_name", ""))
            if body.get("confirmed") is not True:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "前往下一站尚未确认"})
                return
            try:
                config = self.control.read_tour_config()
            except ValueError as exc:
                self._json(HTTPStatus.CONFLICT, {"error": str(exc)})
                return
            if point_name not in config["order"]:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "导览点不在当前路线中"})
                return
            status = self.control.status()
            if not status["localized"]:
                self._json(HTTPStatus.CONFLICT, {"error": "本次开机全局定位尚未成功"})
                return
            if status["request_subscribers"] < 1:
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "运动桥当前不在线"})
                return
            if status["tour_request_subscribers"] < 1:
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "导览执行器当前不在线"})
                return
            if not self.control.reserve_action(False):
                self._json(HTTPStatus.TOO_MANY_REQUESTS, {"error": "操作过快，请等待1秒后重试"})
                return
            task_id = f"tour-{int(time.time())}-{uuid4().hex[:10]}"
            request_payload = {
                "task_id": task_id,
                "robot_id": os.environ.get("G1_ROBOT_ID", ""),
                "source": "g1_web_control",
                "action": "visit",
                "point_name": point_name,
                "confirmed": True,
            }
            from std_msgs.msg import String

            message = String()
            message.data = json.dumps(request_payload, ensure_ascii=False)
            self.control.tour_publisher.publish(message)
            station = config["stations"][point_name]
            self._json(
                HTTPStatus.ACCEPTED,
                {
                    "accepted": True,
                    "task_id": task_id,
                    "state": "queued",
                    "point_name": point_name,
                    "label": station["display_name"],
                },
            )
            return
        command_id = str(body.get("command_id", ""))
        command = COMMANDS.get(command_id)
        is_stop = command_id == "stop"
        if command is None and not is_stop:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "动作不在服务器白名单中"})
            return
        if not is_stop and body.get("confirmed") is not True:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "动作尚未二次确认"})
            return
        status = self.control.status()
        if status["request_subscribers"] < 1:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "运动桥当前不在线"})
            return
        if command_id in RAMP_COMMAND_IDS and not status["localized"]:
            self._json(HTTPStatus.CONFLICT, {"error": "本次开机全局定位尚未成功"})
            return
        if not self.control.reserve_action(is_stop):
            self._json(
                HTTPStatus.TOO_MANY_REQUESTS,
                {"error": "操作过快，请等待1秒后重试"},
            )
            return
        task_id = f"web-{int(time.time())}-{uuid4().hex[:10]}"
        if is_stop:
            payload = {"action": "stop", "confirmed": True}
        else:
            payload = dict(command["payload"])
            payload["confirmed"] = True
        request_payload = {
            "task_id": task_id,
            "robot_id": os.environ.get("G1_ROBOT_ID", ""),
            "source": "g1_web_control",
            **payload,
        }
        from std_msgs.msg import String

        message = String()
        message.data = json.dumps(request_payload, ensure_ascii=False)
        self.control.publisher.publish(message)
        self._json(
            HTTPStatus.ACCEPTED,
            {
                "accepted": True,
                "task_id": task_id,
                "state": "queued",
                "command_id": command_id,
                "label": "立即停止" if is_stop else command["label"],
            },
        )


class ControlServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], control: ControlState) -> None:
        super().__init__(address, Handler)
        self.control = control


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--request-topic", required=True)
    parser.add_argument("--result-topic", required=True)
    parser.add_argument("--tour-request-topic", required=True)
    parser.add_argument("--tour-result-topic", required=True)
    args = parser.parse_args()

    import rclpy
    from std_msgs.msg import String
    from nav_msgs.msg import Odometry
    from rclpy.qos import qos_profile_sensor_data

    token = ensure_token()
    control = ControlState(token)
    rclpy.init()
    node = rclpy.create_node("g1_web_control")
    publisher = node.create_publisher(String, args.request_topic, 10)
    control.set_publisher(publisher)
    tour_publisher = node.create_publisher(String, args.tour_request_topic, 10)
    control.set_tour_publisher(tour_publisher)

    def result_callback(message: Any) -> None:
        try:
            result = json.loads(message.data)
        except (json.JSONDecodeError, TypeError):
            return
        if isinstance(result, dict):
            control.update_result(result)

    subscription = node.create_subscription(String, args.result_topic, result_callback, 10)
    tour_subscription = node.create_subscription(
        String,
        args.tour_result_topic,
        result_callback,
        10,
    )
    odom_subscription = node.create_subscription(
        Odometry,
        WAYPOINT_TOPIC,
        control.update_odom,
        qos_profile_sensor_data,
    )
    def spin_ros() -> None:
        try:
            rclpy.spin(node)
        except Exception as exc:
            if rclpy.ok():
                print(f"ROS spin stopped unexpectedly: {exc}", flush=True)

    spin_thread = threading.Thread(target=spin_ros, daemon=False)
    spin_thread.start()
    server = ControlServer((args.host, args.port), control)

    def shutdown(_signum: int, _frame: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print(f"G1 web control listening on http://{args.host}:{args.port}", flush=True)
    print(f"Access token file: {TOKEN_PATH}", flush=True)
    try:
        server.serve_forever(poll_interval=0.3)
    finally:
        server.server_close()
        if rclpy.ok():
            rclpy.shutdown()
        spin_thread.join(timeout=5.0)
        node.destroy_subscription(odom_subscription)
        node.destroy_subscription(tour_subscription)
        node.destroy_subscription(subscription)
        node.destroy_node()


if __name__ == "__main__":
    main()
