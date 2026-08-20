#!/usr/bin/env python3

import argparse
import json
import math

from unitree_sdk2py.core.channel import (
    ChannelFactoryInitialize,
)
from unitree_sdk2py.rpc.client import Client


SERVICE_NAME = "slam_operate"
API_VERSION = "1.0.0.1"

API_START_MAPPING = 1801
API_STOP_MAPPING = 1802
API_INITIALIZE_POSE = 1804
API_NAVIGATE_POSE = 1102
API_PAUSE = 1201
API_RESUME = 1202
API_CLOSE = 1901


class SlamClient(Client):
    def __init__(self):
        super().__init__(SERVICE_NAME, False)

    def Init(self):
        self._SetApiVerson(API_VERSION)

        for api_id in (
            API_START_MAPPING,
            API_STOP_MAPPING,
            API_INITIALIZE_POSE,
            API_NAVIGATE_POSE,
            API_PAUSE,
            API_RESUME,
            API_CLOSE,
        ):
            self._RegistApi(api_id, 0)

    def request(self, api_id, payload):
        parameter = json.dumps(
            payload,
            ensure_ascii=False,
        )

        code, data = self._Call(
            api_id,
            parameter,
        )

        print("RPC返回码：", code)
        print("原始响应：", data)

        if code != 0:
            raise SystemExit(
                f"SLAM RPC失败，返回码{code}"
            )

        try:
            response = json.loads(data or "{}")
        except json.JSONDecodeError:
            response = {}

        if response:
            print(
                json.dumps(
                    response,
                    ensure_ascii=False,
                    indent=2,
                )
            )

            if response.get("succeed") is False:
                raise SystemExit(
                    "SLAM服务拒绝请求："
                    + str(response.get("info", ""))
                )


def pose(x, y, yaw_radians):
    # RViz和里程计输出的yaw均为弧度。
    yaw = float(yaw_radians)

    return {
        "x": x,
        "y": y,
        "z": 0.0,
        "q_x": 0.0,
        "q_y": 0.0,
        "q_z": math.sin(yaw / 2.0),
        "q_w": math.cos(yaw / 2.0),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "network_interface",
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    commands.add_parser("start-map")

    stop_map = commands.add_parser(
        "stop-map"
    )
    stop_map.add_argument("map_path")

    initialize = commands.add_parser(
        "initialize"
    )
    initialize.add_argument("map_path")
    initialize.add_argument("x", type=float)
    initialize.add_argument("y", type=float)
    initialize.add_argument(
        "yaw",
        type=float,
    )

    navigate = commands.add_parser("goto")
    navigate.add_argument("x", type=float)
    navigate.add_argument("y", type=float)
    navigate.add_argument(
        "yaw",
        type=float,
    )

    commands.add_parser("pause")
    commands.add_parser("resume")
    commands.add_parser("close")

    args = parser.parse_args()

    ChannelFactoryInitialize(
        0,
        args.network_interface,
    )

    client = SlamClient()
    client.SetTimeout(180.0)
    client.Init()

    if args.command == "start-map":
        client.request(
            API_START_MAPPING,
            {
                "data": {
                    "slam_type": "indoor",
                }
            },
        )

    elif args.command == "stop-map":
        client.request(
            API_STOP_MAPPING,
            {
                "data": {
                    "address": args.map_path,
                }
            },
        )

    elif args.command == "initialize":
        initial_pose = pose(
            args.x,
            args.y,
            args.yaw,
        )
        initial_pose["address"] = (
            args.map_path
        )

        client.request(
            API_INITIALIZE_POSE,
            {
                "data": initial_pose,
            },
        )

    elif args.command == "goto":
        client.request(
            API_NAVIGATE_POSE,
            {
                "data": {
                    "targetPose": pose(
                        args.x,
                        args.y,
                        args.yaw,
                    ),
                    "mode": 1,
                }
            },
        )

    elif args.command == "pause":
        client.request(
            API_PAUSE,
            {"data": {}},
        )

    elif args.command == "resume":
        client.request(
            API_RESUME,
            {"data": {}},
        )

    elif args.command == "close":
        client.request(
            API_CLOSE,
            {"data": {}},
        )


if __name__ == "__main__":
    main()
