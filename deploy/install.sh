#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="/home/unitree/智能中控"
ALLOW_EXISTING=0
INSTALL_DEPS=0

usage() {
  cat <<'EOF'
用法：sudo ./deploy/install.sh [--allow-existing] [--install-python-deps]

默认仅安装文件和 systemd 单元，不启用、不启动任何服务，不触发运动。
--allow-existing       允许合并到已有 /home/unitree/智能中控（会先整体备份）
--install-python-deps  使用 pip 将固定依赖安装到项目 vendor 目录
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --allow-existing) ALLOW_EXISTING=1 ;;
    --install-python-deps) INSTALL_DEPS=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数：$1" >&2; usage; exit 2 ;;
  esac
  shift
done

if [[ "$EUID" -ne 0 ]]; then
  echo "请使用 sudo 执行安装。" >&2
  exit 1
fi
if [[ ! -d "$ROOT/runtime" || ! -d "$ROOT/systemd/units" ]]; then
  echo "发布包不完整。" >&2
  exit 1
fi

if [[ -e "$TARGET" ]]; then
  if [[ "$ALLOW_EXISTING" != 1 ]]; then
    echo "$TARGET 已存在；为防止覆盖，安装已停止。" >&2
    echo "确认是需要迁移的旧项目后，使用 --allow-existing。" >&2
    exit 1
  fi
  BACKUP="/home/unitree/智能中控.before_portable_install_$(date +%Y%m%d_%H%M%S)"
  cp -a "$TARGET" "$BACKUP"
  echo "已有项目已备份：$BACKUP"
fi

install -d -o unitree -g unitree -m 0755 "$TARGET"
cp -a "$ROOT/runtime/." "$TARGET/"
chown -R unitree:unitree "$TARGET"
find "$TARGET/scripts" -maxdepth 1 -type f -name '*.sh' -exec chmod 0755 {} +
find "$TARGET/scripts" -maxdepth 1 -type f -name '*.py' -exec chmod 0755 {} +

if [[ ! -f "$TARGET/.env" ]]; then
  install -o unitree -g unitree -m 0600 "$ROOT/.env.example" "$TARGET/.env"
fi

if [[ ! -f /etc/default/g1-ramp-stack ]]; then
  install -o root -g root -m 0644 "$ROOT/config/g1-ramp-stack.example" /etc/default/g1-ramp-stack
else
  echo "保留现有 /etc/default/g1-ramp-stack"
fi

for unit in "$ROOT"/systemd/units/*.service; do
  install -o root -g root -m 0644 "$unit" "/etc/systemd/system/$(basename "$unit")"
done
install -o root -g root -m 0755 "$ROOT/bin/g1-ramp" /usr/local/bin/g1-ramp
install -o root -g root -m 0755 "$ROOT/bin/g1-map-point" /usr/local/bin/g1-map-point

if [[ "$INSTALL_DEPS" == 1 ]]; then
  /usr/bin/python3 -m pip install --target "$TARGET/vendor" -r "$ROOT/requirements.txt"
  chown -R unitree:unitree "$TARGET/vendor"
fi

systemctl daemon-reload
echo
echo "安装完成，但尚未启用或启动服务，也没有发送运动命令。"
echo "下一步：编辑 /etc/default/g1-ramp-stack，按 docs/MAP_MIGRATION.md 准备官方地图，"
echo "然后执行 sudo ./deploy/activate.sh。"
