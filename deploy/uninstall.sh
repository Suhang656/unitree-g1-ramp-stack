#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "$EUID" -ne 0 ]]; then
  echo "请使用 sudo 执行。" >&2
  exit 1
fi

units=(g1-tour-executor g1-web-control g1-global-stop-router g1-local-assistant g1-ramp-last-pose g1-ramp-v3-bootstrap g1-ramp-odom-cache g1-navigation-services g1-voice-bridge)
for unit in "${units[@]}"; do
  systemctl disable --now "$unit.service" 2>/dev/null || true
done
echo "服务已停用。项目、地图、配置和数据均未删除，可手工恢复或审计。"
