#!/usr/bin/env bash
set -Eeuo pipefail

ENABLE_BOOT=0
UNLOCK_ALL=0

usage() {
  cat <<'EOF'
用法：sudo /usr/bin/bash ./deploy/enable_motion.sh [--unlock-all] [--enable-boot]

在地图与本次开机定位已经完成后，启动真实运动链路：
1. 全局停止路由；
2. 本地智能中控与唯一运动桥。

--enable-boot  同时将两个服务设为开机自启
--unlock-all   持久开启真实运动、返回路线和模式命令三个可选授权

本脚本只启动服务，不发布前进、转弯、路线或姿态动作。
--unlock-all 不会移除定位许可、robot_id、本机话题隔离或全局停止保护。
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --enable-boot) ENABLE_BOOT=1 ;;
    --unlock-all) UNLOCK_ALL=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数：$1" >&2; usage; exit 2 ;;
  esac
  shift
done

if [[ "$EUID" -ne 0 ]]; then
  echo "请使用 sudo 执行。" >&2
  exit 1
fi

CONFIG=/etc/default/g1-ramp-stack
[[ -f "$CONFIG" ]] || {
  echo "缺少 $CONFIG，拒绝启动真实运动。" >&2
  exit 1
}

if [[ "$UNLOCK_ALL" == 1 ]]; then
  for key in \
    G1_ALLOW_REAL_MOTION \
    G1_ALLOW_RAMP_RETURN \
    G1_ALLOW_MODE_COMMANDS
  do
    if ! grep -q "^${key}=" "$CONFIG"; then
      echo "配置缺少 ${key}，未修改任何运动授权。" >&2
      exit 1
    fi
  done

  backup="${CONFIG}.before_unlock_all_$(date +%Y%m%d_%H%M%S)"
  cp -a "$CONFIG" "$backup"
  sed -i \
    -e 's/^G1_ALLOW_REAL_MOTION=.*/G1_ALLOW_REAL_MOTION=1/' \
    -e 's/^G1_ALLOW_RAMP_RETURN=.*/G1_ALLOW_RAMP_RETURN=1/' \
    -e 's/^G1_ALLOW_MODE_COMMANDS=.*/G1_ALLOW_MODE_COMMANDS=1/' \
    "$CONFIG"
  echo "三个可选运动授权已持久开启。"
  echo "配置备份：$backup"
fi

source "$CONFIG"

[[ "${G1_ALLOW_REAL_MOTION:-0}" == 1 ]] || {
  echo "G1_ALLOW_REAL_MOTION 不是 1；真实运动总开关保持锁定。" >&2
  echo "请先完成单机隔离、保护架和急停验证，再人工授权。" >&2
  exit 1
}

PROJECT="${G1_PROJECT_DIR:-/home/unitree/智能中控}"
source "$PROJECT/scripts/require_g1_unitree_interface.sh"
source "$PROJECT/scripts/load_g1_command_plane.sh"

for unit in \
  g1-global-stop-router.service \
  g1-local-assistant.service
do
  if ! systemctl cat "$unit" >/dev/null 2>&1; then
    echo "缺少 systemd 服务：$unit" >&2
    echo "请先运行 deploy/install.sh 安装完整发布包。" >&2
    exit 1
  fi
done

mapfile -t existing_bridges < <(
  pgrep -af '/ros2/g1_motion_bridge.py' || true
)

if (( ${#existing_bridges[@]} > 1 )); then
  echo "检测到多个运动桥，拒绝继续：" >&2
  printf '%s\n' "${existing_bridges[@]}" >&2
  echo "先执行 g1-ramp stop，再排查手工 nohup 或重复服务。" >&2
  exit 1
fi

if (( ${#existing_bridges[@]} == 1 )) \
  && ! systemctl is-active --quiet g1-local-assistant.service
then
  echo "检测到服务外手工启动的运动桥，拒绝再启动第二份：" >&2
  printf '%s\n' "${existing_bridges[@]}" >&2
  exit 1
fi

if [[ "$ENABLE_BOOT" == 1 ]]; then
  systemctl enable \
    g1-global-stop-router.service \
    g1-local-assistant.service
fi

systemctl start g1-global-stop-router.service
# The assistant must not synchronously wait for the potentially long-running
# boot localization job. Route commands remain guarded by localization_ready.
systemctl start --no-block g1-local-assistant.service

deadline=$((SECONDS + 20))
while (( SECONDS < deadline )); do
  mapfile -t bridges < <(
    pgrep -af '/ros2/g1_motion_bridge.py' || true
  )

  if systemctl is-active --quiet g1-global-stop-router.service \
    && systemctl is-active --quiet g1-local-assistant.service \
    && (( ${#bridges[@]} == 1 ))
  then
    echo "真实运动链路已启动。"
    echo "全局停止路由：active"
    echo "本地智能中控：active"
    echo "运动桥实例数：1"
    printf '%s\n' "${bridges[0]}"
    echo
    echo "本脚本没有发布任何运动动作。"
    echo "运动总授权：${G1_ALLOW_REAL_MOTION:-0}"
    echo "返回路线授权：${G1_ALLOW_RAMP_RETURN:-0}"
    echo "模式命令授权：${G1_ALLOW_MODE_COMMANDS:-0}"
    echo "停止命令：g1-ramp stop"
    exit 0
  fi

  sleep 1
done

echo "运动链路未在20秒内达到单实例在线状态。" >&2
systemctl --no-pager --full status \
  g1-global-stop-router.service \
  g1-local-assistant.service >&2 || true
pgrep -af '/ros2/g1_motion_bridge.py' >&2 || true
exit 1
