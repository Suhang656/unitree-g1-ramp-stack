#!/usr/bin/env python3

import argparse
import time

from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.g1.audio.g1_audio_client import AudioClient


def read_volume(data):
    if isinstance(data, dict):
        for key in ("volume", "data"):
            value = data.get(key)
            if isinstance(value, (int, float)):
                return int(value)
            if isinstance(value, dict):
                nested = value.get("volume")
                if isinstance(nested, (int, float)):
                    return int(nested)
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("network_interface")
    parser.add_argument("volume", type=int)
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()

    target = max(0, min(100, args.volume))

    ChannelFactoryInitialize(0, args.network_interface)

    client = AudioClient()
    client.SetTimeout(5.0)
    client.Init()

    print(
        f"G1音量锁定服务启动，目标音量={target}",
        flush=True,
    )

    while True:
        try:
            code, data = client.GetVolume()
            current = read_volume(data)

            if code != 0 or current != target:
                set_code = client.SetVolume(target)
                print(
                    f"恢复音量：原音量={current}，"
                    f"读取返回码={code}，"
                    f"设置返回码={set_code}",
                    flush=True,
                )
            else:
                print(
                    f"音量正常：{current}",
                    flush=True,
                )

        except Exception as exc:
            print(
                f"音量检查异常：{exc}",
                flush=True,
            )

        time.sleep(args.interval)


if __name__ == "__main__":
    main()
