"""G1参数化高层运动指令与安全约束。"""

from __future__ import annotations

import math
import re
from typing import Any


FORWARD_THREE_STEPS_TARGET = "forward_three_steps"
CONTINUOUS_FORWARD_TARGET = "continuous_forward"
RAMP_RETURN_TARGET = "ramp_return"
RAMP_PREPARE_TARGET = "ramp_prepare"
TURNING_FORWARD_TARGET = "turning_forward"
TURNING_RETURN_TARGET = "turning_return"
TOUR_GOTO_TARGET = "tour_goto"
TOUR_POINT_NAME_PATTERN = re.compile(
    r"[A-Za-z0-9_\-\u4e00-\u9fff]{1,40}"
)
CONTINUOUS_FORWARD_SPEED_MPS = 0.22

MODE_TARGET_LABELS = {
    "damp": "阻尼模式",
    "zero_torque": "零力矩模式",
    "ready": "预备模式",
    "squat": "下蹲模式",
    "sit": "落座模式",
    "stand": "站立模式",
    "sport": "运动模式",
    "debug": "调试模式",
    "main_control": "主运控模式",
}

FORWARD_SPEED_MPS = 0.30
MIN_FORWARD_DURATION_SECONDS = 1.0
MAX_FORWARD_DURATION_SECONDS = 20.0
DEFAULT_FORWARD_DURATION_SECONDS = 1.0

MIN_FORWARD_DISTANCE_METERS = 0.30
MAX_FORWARD_DISTANCE_METERS = 0.90
DEFAULT_FORWARD_DISTANCE_METERS = 0.30

TURN_SPEED_RAD_S = 0.30
TURN_STARTUP_COMPENSATION_SECONDS = 1.50
MIN_TURN_ANGLE_DEGREES = 15.0
MAX_TURN_ANGLE_DEGREES = 90.0
DEFAULT_TURN_ANGLE_DEGREES = 30.0

FORWARD_THREE_STEPS_SPEED_MPS = FORWARD_SPEED_MPS
FORWARD_THREE_STEPS_DURATION_SECONDS = 3.0
FORWARD_THREE_STEPS_ESTIMATED_DISTANCE_METERS = 0.90


def normalize_voice_command(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?]+", "", text)


def is_forward_three_steps_command(text: str) -> bool:
    return normalize_voice_command(text) == "前进三步"


def is_continuous_forward_command(text: str) -> bool:
    return normalize_voice_command(text) in {
        "前进",
        "直线前进",
        "一直前进",
        "持续前进",
        "一直往前走",
        "一直向前走",
    }


def is_turning_forward_command(text: str) -> bool:
    return normalize_voice_command(text) in {
        "转弯前进",
        "转弯路线前进",
        "沿转弯路线前进",
    }


def is_turning_return_command(text: str) -> bool:
    return normalize_voice_command(text) in {
        "转弯返回",
        "转弯路线返回",
        "沿转弯路线返回",
    }


def is_ramp_return_command(text: str) -> bool:
    return normalize_voice_command(text) in {
        "返回",
        "直线返回",
        "返回起点",
        "回到起点",
        "原路返回",
        "返回原点",
    }


def is_ramp_prepare_command(text: str) -> bool:
    return normalize_voice_command(text) in {
        "准备爬坡行走",
        "准备爬坡",
        "前往爬坡起点",
        "去爬坡起点",
        "回到爬坡起点",
    }


def is_stop_command(text: str) -> bool:
    return normalize_voice_command(text) in {
        "停止",
        "立即停止",
        "紧急停止",
        "停下",
        "停下来",
    }


def is_emergency_damp_command(text: str) -> bool:
    return normalize_voice_command(text) in {
        "紧急阻尼",
        "立即阻尼",
        "紧急停止并阻尼",
    }


def is_mode_confirmation_command(text: str) -> bool:
    return normalize_voice_command(text) in {
        "确认",
        "确认执行",
        "我确认",
        "执行",
    }


def is_mode_cancel_command(text: str) -> bool:
    return normalize_voice_command(text) in {
        "取消",
        "取消执行",
        "不要执行",
        "不执行",
    }


def parse_mode_command(text: str) -> str | None:
    value = normalize_voice_command(text)

    if any(marker in value for marker in (
        "什么是", "为什么", "怎么", "如何",
        "能不能", "可不可以", "是否", "吗", "呢",
    )):
        return None

    aliases = {
        "damp": {
            "进入阻尼模式", "切换阻尼模式",
            "切换到阻尼模式", "阻尼模式",
        },
        "zero_torque": {
            "进入零力矩模式", "切换零力矩模式",
            "切换到零力矩模式", "零力矩模式",
        },
        "ready": {
            "进入预备模式", "切换预备模式",
            "切换到预备模式", "预备模式",
        },
        "squat": {
            "进入下蹲模式", "切换下蹲模式",
            "切换到下蹲模式", "下蹲模式",
        },
        "sit": {
            "进入落座模式", "切换落座模式",
            "切换到落座模式", "落座模式",
        },
        "stand": {
            "进入站立模式", "切换站立模式",
            "切换到站立模式", "站立模式",
        },
        "sport": {
            "进入运动模式", "切换运动模式",
            "切换到运动模式", "运动模式",
        },
        "debug": {
            "进入调试模式", "切换调试模式",
            "切换到调试模式", "调试模式",
        },
        "main_control": {
            "恢复主运控", "进入主运控模式",
            "切换到主运控模式", "主运控模式",
        },
    }

    for target, commands in aliases.items():
        if value in commands:
            return target

    return None


def get_mode_confirmation_prompt(target: str) -> str:
    label = MODE_TARGET_LABELS[target]

    if target == "zero_torque":
        return (
            "零力矩模式会让机器人失去主动支撑，"
            "可能发生倒落。请确认保护架已经固定，"
            "然后说确认执行，或者说取消执行。"
        )

    if target == "debug":
        return (
            "即将先进入阻尼状态，再释放主运控并进入调试模式。"
            "请确认机器人已经稳定，然后说确认执行，"
            "或者说取消执行。"
        )

    if target in {"sit", "squat"}:
        return (
            f"机器人即将进入{label}，请确认周围没有障碍物，"
            "然后说确认执行，或者说取消执行。"
        )

    return (
        f"即将切换到{label}。"
        "请说确认执行，或者说取消执行。"
    )


def is_authorized_motion_command(text: str, action: str) -> bool:
    normalized = normalize_voice_command(text)

    question_words = (
        "能不能",
        "可不可以",
        "可以吗",
        "会不会",
        "是否",
        "怎么",
        "如何",
        "为什么",
        "吗",
        "呢",
    )
    if any(word in normalized for word in question_words):
        return False

    if action == "stop":
        return is_stop_command(text)

    if action == "move":
        if is_ramp_return_command(text):
            return True

        return normalized.startswith((
            "前进",
            "向前走",
            "往前走",
            "向前移动",
            "往前移动",
            "向前直行",
            "往前直行",
            "直走",
            "走直线",
        ))

    if action == "turn":
        return normalized.startswith((
            "左转",
            "向左转",
            "往左转",
            "右转",
            "向右转",
            "往右转",
        ))

    return False


def clamp_number(
    value: Any,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default

    if not math.isfinite(number):
        number = default

    return round(max(minimum, min(maximum, number)), 3)


def normalize_motion_payload(payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action", "")).strip()

    if action == "stop":
        return {
            "action": "stop",
            "confirmed": True,
        }

    if action == "mode":
        target = str(payload.get("target", "")).strip()
        return {
            "action": "mode",
            "target": target,
            "confirmed": payload.get("confirmed") is True,
        }

    if action == "gesture":
        target = str(payload.get("target", "")).strip()

        return {
            "action": "gesture",
            "target": target,
            "confirmed": payload.get("confirmed") is True,
        }

    if action == "move":
        target = str(payload.get("target", "")).strip()

        if target == TOUR_GOTO_TARGET:
            point_name = str(payload.get("point_name", "")).strip()
            return {
                "action": "move",
                "target": TOUR_GOTO_TARGET,
                "point_name": point_name,
                "direction": "forward",
                "duration_seconds": 2.25,
                "distance_m": 0.90,
                "speed": CONTINUOUS_FORWARD_SPEED_MPS,
                "confirmed": payload.get("confirmed") is True,
            }

        if target == RAMP_PREPARE_TARGET:
            return {
                "action": "move",
                "target": RAMP_PREPARE_TARGET,
                "direction": "forward",
                "duration_seconds": 2.25,
                "distance_m": 0.90,
                "speed": CONTINUOUS_FORWARD_SPEED_MPS,
                "confirmed": payload.get("confirmed") is True,
            }

        if target in {
            TURNING_FORWARD_TARGET,
            TURNING_RETURN_TARGET,
        }:
            return {
                "action": "move",
                "target": target,
                "direction": "forward",
                "duration_seconds": 2.25,
                "distance_m": 0.90,
                "speed": CONTINUOUS_FORWARD_SPEED_MPS,
                "confirmed": payload.get("confirmed") is True,
            }

        if target == RAMP_RETURN_TARGET:
            return {
                "action": "move",
                "target": RAMP_RETURN_TARGET,
                "direction": "forward",
                "duration_seconds": 2.25,
                "distance_m": 0.90,
                "speed": CONTINUOUS_FORWARD_SPEED_MPS,
                "confirmed": payload.get("confirmed") is True,
            }

        if target == CONTINUOUS_FORWARD_TARGET:
            return {
                "action": "move",
                "target": CONTINUOUS_FORWARD_TARGET,
                "direction": "forward",
                "duration_seconds": 2.25,
                "distance_m": 0.90,
                "speed": CONTINUOUS_FORWARD_SPEED_MPS,
                "confirmed": payload.get("confirmed") is True,
            }

        if target == FORWARD_THREE_STEPS_TARGET:
            duration = FORWARD_THREE_STEPS_DURATION_SECONDS
        elif payload.get("duration_seconds") is not None:
            duration = clamp_number(
                payload.get("duration_seconds"),
                DEFAULT_FORWARD_DURATION_SECONDS,
                MIN_FORWARD_DURATION_SECONDS,
                MAX_FORWARD_DURATION_SECONDS,
            )
        else:
            distance = clamp_number(
                payload.get("distance_m"),
                DEFAULT_FORWARD_DISTANCE_METERS,
                MIN_FORWARD_DISTANCE_METERS,
                MAX_FORWARD_DISTANCE_METERS,
            )
            duration = round(distance / FORWARD_SPEED_MPS, 3)

        duration = clamp_number(
            duration,
            DEFAULT_FORWARD_DURATION_SECONDS,
            MIN_FORWARD_DURATION_SECONDS,
            MAX_FORWARD_DURATION_SECONDS,
        )
        distance = round(FORWARD_SPEED_MPS * duration, 3)

        return {
            "action": "move",
            "direction": "forward",
            "duration_seconds": duration,
            "distance_m": distance,
            "speed": FORWARD_SPEED_MPS,
            "confirmed": payload.get("confirmed") is True,
        }

    if action == "turn":
        direction = str(payload.get("direction", "")).strip().lower()
        if direction not in {"left", "right"}:
            direction = ""

        angle = clamp_number(
            payload.get("angle_deg"),
            DEFAULT_TURN_ANGLE_DEGREES,
            MIN_TURN_ANGLE_DEGREES,
            MAX_TURN_ANGLE_DEGREES,
        )

        return {
            "action": "turn",
            "direction": direction,
            "angle_deg": angle,
            "angular_speed": TURN_SPEED_RAD_S,
            "confirmed": payload.get("confirmed") is True,
        }

    return {"action": action}


def validate_motion_payload(
    payload: dict[str, Any],
) -> tuple[bool, str]:
    normalized = normalize_motion_payload(payload)
    action = normalized.get("action")

    if action == "stop":
        return True, ""

    if normalized.get("confirmed") is not True:
        return False, "动作没有通过语音指令确认门"

    if action == "mode":
        if normalized.get("target") not in MODE_TARGET_LABELS:
            return False, "模式不在安全白名单中"
        return True, ""

    if action == "gesture":
        if normalized.get("target") not in INTERACTION_TARGETS:
            return False, "交互动作不在安全白名单中"
        return True, ""

    if action == "move":
        if normalized.get("direction") != "forward":
            return False, "当前只允许向前直线运动"
        if normalized.get("target") == TOUR_GOTO_TARGET:
            point_name = str(normalized.get("point_name", ""))
            if not TOUR_POINT_NAME_PATTERN.fullmatch(point_name):
                return False, "导览点名称不符合安全规则"
        return True, ""

    if action == "turn":
        if normalized.get("direction") not in {"left", "right"}:
            return False, "没有识别出左转或右转"
        return True, ""

    return False, "当前只允许受控运动、交互动作、模式切换和停止"


_CN_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _parse_chinese_integer(value: str) -> float | None:
    if not value:
        return 0.0

    if "十" in value:
        left, right = value.split("十", 1)
        tens = 1 if not left else _CN_DIGITS.get(left)
        ones = 0 if not right else _CN_DIGITS.get(right)

        if tens is None or ones is None:
            return None

        return float(tens * 10 + ones)

    digits = []

    for character in value:
        digit = _CN_DIGITS.get(character)
        if digit is None:
            return None
        digits.append(str(digit))

    if not digits:
        return None

    return float("".join(digits))


def _parse_spoken_number(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        pass

    if "点" in value:
        integer_text, decimal_text = value.split("点", 1)
        integer = _parse_chinese_integer(integer_text)

        if integer is None or not decimal_text:
            return None

        decimal_digits = []

        for character in decimal_text:
            digit = _CN_DIGITS.get(character)
            if digit is None:
                return None
            decimal_digits.append(str(digit))

        return float(f"{int(integer)}.{''.join(decimal_digits)}")

    return _parse_chinese_integer(value)


def parse_forward_duration_command(text: str) -> float | None:
    """解析明确的向前直行时间，返回秒数。"""

    value = re.sub(r"[\s，。！？、,!?：:；;]+", "", text)

    question_markers = (
        "能不能",
        "可不可以",
        "可以吗",
        "是否",
        "为什么",
        "怎么",
        "如何",
        "吗",
        "呢",
    )

    if any(marker in value for marker in question_markers):
        return None

    prefixes = (
        "前进",
        "向前走",
        "往前走",
        "向前移动",
        "往前移动",
        "向前直行",
        "往前直行",
        "直走",
        "走直线",
    )

    if not value.startswith(prefixes):
        return None

    match = re.search(
        r"([0-9]+(?:\.[0-9]+)?|[零〇一二两三四五六七八九十点]+)秒(半)?",
        value,
    )

    if match is None:
        return None

    seconds = _parse_spoken_number(match.group(1))

    if seconds is None:
        return None

    if match.group(2):
        seconds += 0.5

    return seconds



_WAKE_WORD_VARIANTS = (
    "小智小智",
    "小志小志",
    "小知小知",
    "小志小智",
    "小智小志",
    "小知小智",
    "小智小知",
)


def strip_leading_wake_words(text: str) -> str:
    """清除ASR残留在运动指令开头的唤醒词。"""

    value = text.strip()

    changed = True
    while changed:
        changed = False

        for wake_word in _WAKE_WORD_VARIANTS:
            if value.startswith(wake_word):
                value = value[len(wake_word):].lstrip(
                    "，。！？、,.!? "
                )
                changed = True
                break

    return value


def parse_turn_command(
    text: str,
) -> tuple[str, float] | None:
    """解析左右转指令，返回方向和角度。"""

    value = strip_leading_wake_words(text)
    value = re.sub(r"[\s，。！？、,!?：:；;]+", "", value)

    question_markers = (
        "能不能",
        "可不可以",
        "可以吗",
        "是否",
        "为什么",
        "怎么",
        "如何",
        "吗",
        "呢",
    )

    if any(marker in value for marker in question_markers):
        return None

    left_prefixes = (
        "左转",
        "向左转",
        "往左转",
        "向左旋转",
        "往左旋转",
    )
    right_prefixes = (
        "右转",
        "向右转",
        "往右转",
        "向右旋转",
        "往右旋转",
    )

    if value.startswith(left_prefixes):
        direction = "left"
    elif value.startswith(right_prefixes):
        direction = "right"
    else:
        return None

    match = re.search(
        r"([0-9]+(?:\.[0-9]+)?|[零〇一二两三四五六七八九十点]+)度",
        value,
    )

    if match is None:
        angle = DEFAULT_TURN_ANGLE_DEGREES
    else:
        angle = _parse_spoken_number(match.group(1))
        if angle is None:
            return None

    return direction, float(angle)



INTERACTION_TARGETS = {
    "wave",
    "wave_turn",
    "handshake_start",
    "handshake_end",
}


def parse_interaction_command(text: str) -> str | None:
    """解析G1官方高层交互动作。"""

    value = strip_leading_wake_words(text)
    value = normalize_voice_command(value)

    question_markers = (
        "能不能",
        "可不可以",
        "可以吗",
        "是否",
        "为什么",
        "怎么",
        "如何",
        "吗",
        "呢",
    )

    if any(marker in value for marker in question_markers):
        return None

    commands = {
        "挥手": "wave",
        "挥挥手": "wave",
        "招手": "wave",
        "打个招呼": "wave",
        "向我挥手": "wave",
        "原地挥手": "wave",
        "转身挥手": "wave_turn",
        "转过身挥手": "wave_turn",
        "边转身边挥手": "wave_turn",
        "握手": "handshake_start",
        "和我握手": "handshake_start",
        "跟我握手": "handshake_start",
        "伸手握手": "handshake_start",
        "结束握手": "handshake_end",
        "停止握手": "handshake_end",
        "握手结束": "handshake_end",
        "松开手": "handshake_end",
    }

    return commands.get(value)


# PC1 ArmAction服务实际返回的安全交互动作。
ARM_ACTIONS = {
    "release_arm": {
        "id": 99,
        "label": "释放手臂",
        "wait_seconds": 1.0,
        "hold": False,
    },
    "turn_back_wave": {
        "id": 1,
        "label": "转身挥手",
        "wait_seconds": 6.0,
        "hold": False,
    },
    "two_hand_kiss": {
        "id": 11,
        "label": "双手飞吻",
        "wait_seconds": 5.0,
        "hold": False,
    },
    "left_kiss": {
        "id": 12,
        "label": "左手飞吻",
        "wait_seconds": 5.0,
        "hold": False,
    },
    "right_kiss": {
        "id": 13,
        "label": "右手飞吻",
        "wait_seconds": 5.0,
        "hold": False,
    },
    "both_hands_up": {
        "id": 15,
        "label": "举双手",
        "wait_seconds": 3.0,
        "hold": False,
    },
    "clap": {
        "id": 17,
        "label": "鼓掌",
        "wait_seconds": 5.0,
        "hold": False,
    },
    "high_five": {
        "id": 18,
        "label": "击掌",
        "wait_seconds": 3.0,
        "hold": False,
    },
    "hug": {
        "id": 19,
        "label": "拥抱",
        "wait_seconds": 3.0,
        "hold": False,
    },
    "heart": {
        "id": 20,
        "label": "双手比心",
        "wait_seconds": 3.0,
        "hold": False,
    },
    "right_heart": {
        "id": 21,
        "label": "右手比心",
        "wait_seconds": 3.0,
        "hold": False,
    },
    "refuse": {
        "id": 22,
        "label": "拒绝动作",
        "wait_seconds": 3.0,
        "hold": False,
    },
    "right_hand_up": {
        "id": 23,
        "label": "举右手",
        "wait_seconds": 3.0,
        "hold": False,
    },
    "ultraman_ray": {
        "id": 24,
        "label": "双手打叉",
        "wait_seconds": 3.0,
        "hold": False,
    },
    "face_wave": {
        "id": 25,
        "label": "胸前挥手",
        "wait_seconds": 5.0,
        "hold": False,
    },
    "high_wave": {
        "id": 26,
        "label": "高举挥手",
        "wait_seconds": 5.0,
        "hold": False,
    },
    "handshake_start": {
        "id": 27,
        "label": "握手",
        "wait_seconds": 2.0,
        "hold": True,
    },
    "handshake_end": {
        "id": 99,
        "label": "结束握手",
        "wait_seconds": 1.0,
        "hold": False,
    },
}

INTERACTION_TARGETS = set(ARM_ACTIONS)


def parse_interaction_command(text: str) -> str | None:
    """使用PC1 ArmAction服务解析交互动作。"""

    value = strip_leading_wake_words(text)
    value = normalize_voice_command(value)

    question_markers = (
        "能不能",
        "可不可以",
        "可以吗",
        "是否",
        "为什么",
        "怎么",
        "如何",
        "吗",
        "呢",
    )

    if any(marker in value for marker in question_markers):
        return None

    commands = {
        "挥手": "face_wave",
        "挥挥手": "face_wave",
        "招手": "face_wave",
        "打个招呼": "face_wave",
        "胸前挥手": "face_wave",
        "向我挥手": "face_wave",
        "高举挥手": "high_wave",
        "举手挥舞": "high_wave",
        "转身挥手": "turn_back_wave",
        "转过身挥手": "turn_back_wave",

        "握手": "handshake_start",
        "和我握手": "handshake_start",
        "跟我握手": "handshake_start",
        "伸手握手": "handshake_start",
        "结束握手": "handshake_end",
        "停止握手": "handshake_end",
        "握手结束": "handshake_end",
        "松开手": "handshake_end",

        "鼓掌": "clap",
        "拍拍手": "clap",
        "击掌": "high_five",
        "和我击掌": "high_five",
        "拥抱": "hug",
        "抱一下": "hug",

        "飞吻": "two_hand_kiss",
        "双手飞吻": "two_hand_kiss",
        "左手飞吻": "left_kiss",
        "右手飞吻": "right_kiss",

        "举双手": "both_hands_up",
        "双手举起": "both_hands_up",
        "举右手": "right_hand_up",
        "右手举起": "right_hand_up",

        "比心": "heart",
        "双手比心": "heart",
        "右手比心": "right_heart",

        "拒绝": "refuse",
        "表示拒绝": "refuse",
        "双手打叉": "ultraman_ray",
        "打叉": "ultraman_ray",
        "奥特曼光线": "ultraman_ray",

        "释放手臂": "release_arm",
        "放下手臂": "release_arm",
        "恢复手臂": "release_arm",
    }

    return commands.get(value)
