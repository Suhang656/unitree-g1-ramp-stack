#!/usr/bin/env bash
set -Eeuo pipefail

echo "===== 服务 ====="
for s in g1-voice-bridge g1-navigation-services g1-ramp-odom-cache g1-ramp-v3-bootstrap g1-local-assistant g1-global-stop-router g1-web-control g1-tour-executor g1-ramp-last-pose; do
  printf '%-34s ' "$s"
  systemctl is-active "$s.service" 2>/dev/null || true
done

echo "===== 进程唯一性 ====="
pgrep -af 'g1_motion_bridge.py|g1_voice_bridge.py|g1_web_control.py|g1_tour_executor.py' || true

echo "===== 当前开机定位许可 ====="
g1-ramp status

echo "===== Web Token ====="
if [[ -r /home/unitree/智能中控/data/web_control/access_token ]]; then
  echo "已生成（不在此脚本中回显，请在 G1 本机读取）。"
else
  echo "尚未生成。"
fi

echo "此验证是只读的，不发送运动命令。"
