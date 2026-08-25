#!/usr/bin/env bash
# Require an explicitly configured Unitree internal NIC. Never guess a Wi-Fi NIC.

G1_UNITREE_INTERFACE="${G1_UNITREE_INTERFACE:-}"
if [[ -z "$G1_UNITREE_INTERFACE" || "$G1_UNITREE_INTERFACE" == "CHANGE_ME" ]]; then
  echo "G1_UNITREE_INTERFACE 尚未配置；拒绝访问 Unitree DDS。" >&2
  echo "请在 /etc/default/g1-ramp-stack 中填写本机连接 192.168.123.161 的网口。" >&2
  return 1 2>/dev/null || exit 1
fi

if [[ ! "$G1_UNITREE_INTERFACE" =~ ^[A-Za-z0-9_.:-]+$ ]] \
  || [[ ! -d "/sys/class/net/$G1_UNITREE_INTERFACE" ]]; then
  echo "Unitree 网口不存在或名称无效：$G1_UNITREE_INTERFACE" >&2
  return 1 2>/dev/null || exit 1
fi

G1_CONTROL_IP="${G1_CONTROL_IP:-192.168.123.161}"
route_line="$(ip route get "$G1_CONTROL_IP" 2>/dev/null | head -n 1 || true)"
if [[ "$route_line" != *" dev $G1_UNITREE_INTERFACE "* ]]; then
  echo "到 $G1_CONTROL_IP 的路由没有使用 $G1_UNITREE_INTERFACE；拒绝启动。" >&2
  echo "实际路由：${route_line:-不可达}" >&2
  return 1 2>/dev/null || exit 1
fi

# Compatibility for older Python modules. The value still comes only from the
# explicit per-robot setting above.
export G1_NETWORK_INTERFACE="$G1_UNITREE_INTERFACE"

