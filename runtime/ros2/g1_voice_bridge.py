#!/usr/bin/env python3
"""Bridge Unitree G1 built-in ASR/TTS to Smart Center ROS 2 text topics."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import queue
import threading
from pathlib import Path
from typing import Any

from app.g1_audio_messages import G1AsrFilter, G1WakeGate, parse_g1_audio_message


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Unitree G1 voice bridge")
    parser.add_argument("network_interface", help="G1 network interface, for example enp3s0")
    parser.add_argument("--input-topic", required=True)
    parser.add_argument("--response-topic", required=True)
    parser.add_argument(
        "--fixed-route-topic",
        required=True,
    )
    parser.add_argument("--volume", type=int, default=80)
    parser.add_argument("--speaker-id", type=int, default=0, help="0=Chinese/auto, 1=English")
    parser.add_argument("--min-confidence", type=float, default=0.0)
    parser.add_argument(
        "--wake-word",
        default="小智小智",
        help="Local wake word; pass an empty value to forward every utterance",
    )
    parser.add_argument(
        "--wake-alias",
        action="append",
        default=[],
        help="Additional STT spelling accepted as the wake word; may be repeated",
    )
    parser.add_argument("--wake-reply", default="我在")
    parser.add_argument("--wake-timeout", type=float, default=10.0)
    parser.add_argument("--min-command-chars", type=int, default=3)
    parser.add_argument(
        "--tts-guard-seconds",
        type=float,
        default=1.5,
        help="Additional ASR suppression after estimated G1 TTS playback",
    )
    parser.add_argument(
        "--accept-interim",
        action="store_true",
        help="Accept ASR messages whose is_final is false (normally disabled)",
    )
    return parser


def acquire_process_lock() -> Any:
    handle = Path("/tmp/smart-center-g1-voice-bridge.lock").open("w", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise SystemExit(
            "Another g1_voice_bridge process is already running; stop it before restarting."
        ) from exc
    handle.write(str(os.getpid()))
    handle.flush()
    return handle


def main() -> None:
    args = build_parser().parse_args()
    process_lock = acquire_process_lock()
    if not 0 <= args.volume <= 100:
        raise SystemExit("--volume must be between 0 and 100")

    try:
        import rclpy
        from rclpy.node import Node
        from std_msgs.msg import String
    except ImportError as exc:
        raise SystemExit("rclpy/std_msgs unavailable; source the matching ROS 2 environment") from exc

    try:
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
        from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient
        from unitree_sdk2py.idl.std_msgs.msg.dds_ import String_ as UnitreeString
    except ImportError as exc:
        raise SystemExit("unitree_sdk2py unavailable; install the official Unitree SDK2 Python package") from exc

    ChannelFactoryInitialize(0, args.network_interface)
    audio_client = AudioClient()
    audio_client.SetTimeout(10.0)
    audio_client.Init()
    volume_result = audio_client.SetVolume(args.volume)
    if volume_result != 0:
        raise SystemExit(f"G1 SetVolume failed: {volume_result}")

    asr_filter = G1AsrFilter(
        final_only=not args.accept_interim,
        min_confidence=args.min_confidence,
    )
    wake_gate = G1WakeGate(
        args.wake_word,
        0.0,
        args.min_command_chars,
        tuple(dict.fromkeys([
            *args.wake_alias,
            "小智小志",
            "小志小智",
            "小智小知",
            "小知小智",
            "小志小志",
            "小知小知",
        ])),
    )
    speech_queue: queue.Queue[str | None] = queue.Queue(maxsize=8)

    class G1VoiceBridge(Node):
        def __init__(self) -> None:
            super().__init__("g1_voice_bridge")
            self.input_publisher = self.create_publisher(String, args.input_topic, 10)
            self.fixed_route_publisher = self.create_publisher(
                String,
                args.fixed_route_topic,
                10,
            )
            self.create_subscription(String, args.response_topic, self._on_response, 10)
            self.get_logger().info(
                f"G1 voice bridge ready: rt/audio_msg -> {args.input_topic} -> "
                f"{args.response_topic} -> G1 TTS"
            )

        def on_unitree_audio(self, message: Any) -> None:
            text = asr_filter.accept(parse_g1_audio_message(message.data))
            if not text:
                return
            self.get_logger().info(f"G1 STT: {text}")
            decision = wake_gate.process(text)

            if decision.command:
                normalized_command = "".join(
                    character
                    for character in decision.command
                    if character not in " ，。！？、,.!?\\t\\r\\n"
                )

                fixed_routes = {
                    "准备固定路段行走": "prepare",
                    "进行导览服务": "fixed_route",
                    "回到初始点": "return_home",
                    "停止行走": "stop",
                }

                fixed_route = fixed_routes.get(
                    normalized_command
                )

                if fixed_route:
                    output = String()
                    output.data = fixed_route
                    self.fixed_route_publisher.publish(output)
                    self.get_logger().warning(
                        "SILENT_FIXED_ROUTE: "
                        f"{normalized_command} -> {fixed_route}"
                    )
                    return

            if decision.acknowledge and args.wake_reply:
                try:
                    speech_queue.put_nowait(args.wake_reply)
                except queue.Full:
                    self.get_logger().warning("G1 TTS queue is full; dropping wake reply")

            if decision.command:
                output = String()
                output.data = decision.command
                self.input_publisher.publish(output)
                self.get_logger().info(f"Local Qwen input: {decision.command}")

        def _on_response(self, message: Any) -> None:
            try:
                payload = json.loads(message.data)
                text = payload.get("text", "") if isinstance(payload, dict) else ""
            except json.JSONDecodeError:
                text = message.data
            if not isinstance(text, str) or not text.strip():
                return
            try:
                speech_queue.put_nowait(text.strip())
            except queue.Full:
                self.get_logger().warning("G1 TTS queue is full; dropping response")

    rclpy.init()
    node = G1VoiceBridge()

    def speak() -> None:
        while True:
            text = speech_queue.get()
            if text is None:
                break
            # TtsMaker returns before playback completes. Keep ASR muted for an
            # estimated Chinese speaking duration even if firmware play_state
            # events are delayed or missing.
            estimated_seconds = max(2.0, len(text) / 4.5 + args.tts_guard_seconds)
            asr_filter.suppress_for(estimated_seconds)
            node.get_logger().info(f"G1 TTS: {text}")
            result = audio_client.TtsMaker(text, args.speaker_id)
            if result != 0:
                node.get_logger().error(f"G1 TtsMaker failed: {result}")

    tts_thread = threading.Thread(target=speak, name="g1-tts", daemon=True)
    tts_thread.start()
    audio_subscriber = ChannelSubscriber("rt/audio_msg", UnitreeString)
    audio_subscriber.Init(node.on_unitree_audio, 10)

    try:
        rclpy.spin(node)
    finally:
        speech_queue.put(None)
        tts_thread.join(timeout=5)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        process_lock.close()


if __name__ == "__main__":
    main()
