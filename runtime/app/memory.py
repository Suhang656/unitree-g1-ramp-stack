import re

from app.database import Database
from app.schemas import MemoryRecord


MEMORY_TRIGGER = "记住"
_LEADING_PUNCTUATION = " ：:，,。.!！?？；;、\t\r\n"


def memory_was_requested(text: str) -> bool:
    return MEMORY_TRIGGER in text


def extract_memory(text: str) -> tuple[str, str, str] | None:
    """Deterministically turn text containing '记住' into a local memory."""
    normalized = " ".join(text.split()).strip()
    if not memory_was_requested(normalized):
        return None
    value = normalized.split(MEMORY_TRIGGER, 1)[1].lstrip(_LEADING_PUNCTUATION)
    if not value:
        value = normalized
    value = value[:5000]

    if any(marker in value for marker in ("放在", "位于", "位置", "存放", "在哪里")):
        kind = "location"
        match = re.match(r"(.{1,80}?)(?:放在|位于|存放)", value)
        key = match.group(1).strip(_LEADING_PUNCTUATION) if match else value[:80]
    elif any(marker in value for marker in ("喜欢", "偏好", "习惯", "不喜欢", "常用")):
        kind = "preference"
        key = value[:80]
    elif any(marker in value for marker in ("我叫", "我是", "我的名字", "生日", "联系方式")):
        kind = "profile"
        if "我叫" in value or "我的名字" in value:
            key = "姓名"
        elif "生日" in value:
            key = "生日"
        elif "联系方式" in value:
            key = "联系方式"
        else:
            key = value[:80]
    else:
        kind = "instruction"
        key = value[:80]

    key = key.strip(_LEADING_PUNCTUATION) or "用户要求记住的内容"
    return kind, key[:200], value


async def remember_text_if_requested(
    database: Database,
    text: str,
    session_id: str | None = None,
    source: str = "keyword_trigger",
) -> MemoryRecord | None:
    parsed = extract_memory(text)
    if parsed is None:
        return None
    kind, key, value = parsed
    memory = await database.upsert_memory(kind, key, value, 1.0, source)
    await database.log_tool_execution(
        session_id,
        "remember_user_text",
        {"trigger": MEMORY_TRIGGER, "kind": kind, "key": key},
        {"memory": memory.model_dump(mode="json")},
        "success",
    )
    return memory
