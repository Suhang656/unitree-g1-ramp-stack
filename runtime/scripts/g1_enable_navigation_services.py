#!/usr/bin/env python3

import sys
import time

from unitree_sdk2py.core.channel import (
    ChannelFactoryInitialize,
)
from unitree_sdk2py.go2.robot_state.robot_state_client import (
    RobotStateClient,
)

NETWORK_INTERFACE = (
    sys.argv[1]
    if len(sys.argv) > 1
    else ""
)
if not NETWORK_INTERFACE:
    raise SystemExit("必须显式传入本机 Unitree 内部网口")

SERVICES = (
    "lidar_driver",
    "unitree_slam",
)

print(
    "初始化G1导航服务客户端：",
    NETWORK_INTERFACE,
    flush=True,
)

ChannelFactoryInitialize(
    0,
    NETWORK_INTERFACE,
)

client = RobotStateClient()
client.SetTimeout(8.0)
client.Init()

for attempt in range(1, 13):
    print(
        f"导航服务启动尝试：{attempt}/12",
        flush=True,
    )

    results = {}

    for service_name in SERVICES:
        try:
            result = client.ServiceSwitch(
                service_name,
                True,
            )
        except Exception as exc:
            print(
                f"{service_name}调用异常：{exc}",
                flush=True,
            )
            result = -1

        results[service_name] = result

        print(
            f"{service_name}返回码：{result}",
            flush=True,
        )

        time.sleep(2)

    if all(
        result == 0
        for result in results.values()
    ):
        print(
            "lidar_driver和unitree_slam启动成功",
            flush=True,
        )

        # 给Mid360和SLAM留出初始化时间。
        time.sleep(12)
        raise SystemExit(0)

    time.sleep(5)

print(
    "连续尝试后仍未能启动导航服务",
    flush=True,
)
raise SystemExit(1)
