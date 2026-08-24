#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "$EUID" -ne 0 ]]; then
  echo "请使用 sudo 执行。" >&2
  exit 1
fi

PROJECT=/home/unitree/智能中控
CONFIG=/etc/default/g1-ramp-stack
[[ -f "$CONFIG" ]] || { echo "缺少 $CONFIG" >&2; exit 1; }
source "$CONFIG"

[[ "${G1_INTERNAL_MAP_VERIFIED:-0}" == 1 ]] || {
  echo "G1_INTERNAL_MAP_VERIFIED 尚未设为 1。" >&2
  echo "请先按 docs/MAP_MIGRATION.md 通过官方 initialize 验证地图。" >&2
  echo "地图可能位于内部控制单元，不能只用 NX 的 test -f 判断。" >&2
  exit 1
}

systemctl enable \
  g1-voice-bridge.service \
  g1-navigation-services.service \
  g1-ramp-odom-cache.service \
  g1-ramp-v3-bootstrap.service \
  g1-local-assistant.service \
  g1-global-stop-router.service \
  g1-web-control.service \
  g1-tour-executor.service \
  g1-ramp-last-pose.service

systemctl start g1-global-stop-router.service
systemctl start g1-voice-bridge.service
systemctl start g1-navigation-services.service
systemctl start g1-ramp-odom-cache.service

# Localization can legitimately retry for a long time. Do not make activation
# or the emergency-stop/local-assistant services wait synchronously for it.
systemctl start --no-block g1-ramp-v3-bootstrap.service
systemctl start --no-block g1-local-assistant.service
systemctl start g1-web-control.service
systemctl start g1-tour-executor.service
systemctl start --no-block g1-ramp-last-pose.service

echo "服务启动请求已提交；开机定位可能继续在后台重试。"
echo "此脚本没有发布路线运动命令。"
echo "运行 g1-ramp status 查看状态。"
