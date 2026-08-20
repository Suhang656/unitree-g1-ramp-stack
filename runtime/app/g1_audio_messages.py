"""Unitree G1 ``rt/audio_msg`` message parsing helpers."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class G1AsrMessage:
    text: str
    index: int | None = None
    is_final: bool | None = None
    confidence: float | None = None
    language: str | None = None


@dataclass(frozen=True)
class G1PlaybackMessage:
    playing: bool


def parse_g1_audio_message(raw: str) -> G1AsrMessage | G1PlaybackMessage | None:
    """Parse the JSON string published by G1 on ``rt/audio_msg``.

    Firmware versions do not always expose exactly the same optional fields, so
    only ``text`` and ``play_state`` are treated as discriminators.
    """

    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None

    if "play_state" in payload:
        return G1PlaybackMessage(playing=bool(payload["play_state"]))

    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        return None

    index = payload.get("index")
    confidence = payload.get("confidence")
    language = payload.get("language")
    final_value = payload.get("is_final")
    return G1AsrMessage(
        text=text.strip(),
        index=index if isinstance(index, int) and not isinstance(index, bool) else None,
        is_final=bool(final_value) if final_value is not None else None,
        confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
        language=language if isinstance(language, str) else None,
    )


class G1AsrFilter:
    """Suppress partial, duplicate, low-confidence, and self-playback ASR."""

    def __init__(self, *, final_only: bool = True, min_confidence: float = 0.0) -> None:
        self.final_only = final_only
        self.min_confidence = min_confidence
        self.playing = False
        self._suppress_until = 0.0
        self._last_index: int | None = None
        self._last_text: str | None = None

    def suppress_for(self, seconds: float, *, now: float | None = None) -> None:
        current_time = time.monotonic() if now is None else now
        self._suppress_until = max(self._suppress_until, current_time + max(0.0, seconds))

    def accept(self, message: G1AsrMessage | G1PlaybackMessage | None) -> str | None:
        if isinstance(message, G1PlaybackMessage):
            self.playing = message.playing
            return None
        if (
            not isinstance(message, G1AsrMessage)
            or self.playing
            or time.monotonic() < self._suppress_until
        ):
            return None
        if self.final_only and message.is_final is False:
            return None
        if message.confidence is not None and message.confidence < self.min_confidence:
            return None
        if message.index is not None and message.index == self._last_index:
            return None
        if message.index is None and message.text == self._last_text:
            return None
        self._last_index = message.index
        self._last_text = message.text
        return message.text


@dataclass(frozen=True)
class G1WakeDecision:
    command: str | None = None
    acknowledge: bool = False


class G1WakeGate:
    """Turn G1 ASR text into one local-Qwen command per wake-up."""

    _TRIM_CHARACTERS = " \t\r\n，。！？、,.!?:：；;"

    def __init__(
        self,
        wake_word: str = "小智小智",
        timeout_seconds: float = 10.0,
        min_command_chars: int = 1,
        aliases: tuple[str, ...] = (),
    ) -> None:
        self.wake_word = wake_word.strip()
        self.wake_phrases = tuple(
            phrase for phrase in (self.wake_word, *(item.strip() for item in aliases)) if phrase
        )
        self.timeout_seconds = timeout_seconds
        self.min_command_chars = max(1, min_command_chars)
        self._awake_until = 0.0

    def process(self, text: str, *, now: float | None = None) -> G1WakeDecision:
        current_time = time.monotonic() if now is None else now
        content = text.strip()
        if not self.wake_phrases:
            return G1WakeDecision(command=content or None)

        matched_phrase = next((phrase for phrase in self.wake_phrases if phrase in content), None)
        if matched_phrase is not None:
            position = content.find(matched_phrase)
            remainder = content[position + len(matched_phrase):].lstrip(self._TRIM_CHARACTERS)
            if len(remainder) >= self.min_command_chars:
                self._awake_until = 0.0
                return G1WakeDecision(command=remainder)
            self._awake_until = current_time + self.timeout_seconds
            return G1WakeDecision(acknowledge=True)

        if current_time <= self._awake_until:
            if len(content) < self.min_command_chars:
                return G1WakeDecision()
            self._awake_until = 0.0
            return G1WakeDecision(command=content or None)
        return G1WakeDecision()
