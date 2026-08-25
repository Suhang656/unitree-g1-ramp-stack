# 已验证目标 G1 配置

本文记录 2026-08-25 在第二台 G1 上完成的脱敏只读审计结果，用于说明一套实际同时支持语音、网页和终端控制的配置。无线 IP、网页 Token、SSH 凭据、地图文件和站点点位不进入仓库。

## 验证结果

- Unitree 内部控制网口：`enP8p1s0`，通过它访问 `192.168.123.161`；
- 机器人命令身份：`target_g1`；
- 命令话题前缀：`/target_g1/smart_center`；
- 命令 ROS Domain：`0`，同时由启动脚本强制 `ROS_LOCALHOST_ONLY=1`；
- 语音、官方导航、里程计缓存、开机定位、本地助手、全局停止和网页服务均为 `enabled`、`active`；
- 导览未验收，保持 `disabled`、`inactive`；
- 运动桥只有一个实例；
- 语音桥、运动桥、网页端、CLI 和标点工具与本仓库 1.1.2 基线文件 SHA-256 完全一致；
- 语音桥实际监听 `rt/audio_msg`，并向本机 `/target_g1/smart_center/*` 话题发布；
- 唤醒主词为“小智小智”，同时接受“小志小志”和“小知小知”，未启用 `--strict-wake`；
- 现场已验证终端、网页和语音三种入口均能控制同一目标 G1。

## 站点配置结构

以下是现场配置的脱敏结构。`CHANGE_ME` 项必须在每台 G1 本机重新填写，不能照抄另一台机器的地图和坐标。

```text
G1_PROJECT_DIR=/home/unitree/智能中控
G1_CONTROL_IP=192.168.123.161
G1_UNITREE_INTERFACE=enP8p1s0
G1_ROBOT_ID=CHANGE_ME
G1_COMMAND_ROS_DOMAIN_ID=0
UNITREE_SDK2_PYTHON_PATH=/home/unitree/unitree_sdk2_python
CYCLONEDDS_COMPAT_PREFIX=/home/unitree/cyclonedds-prefix
UNITREE_ROS2_SETUP=/home/unitree/unitree_ros2/cyclonedds_ws/install/setup.bash
G1_INTERNAL_MAP_PATH=CHANGE_ME
G1_INTERNAL_MAP_VERIFIED=1
G1_FIXED_START_X=CHANGE_ME
G1_FIXED_START_Y=CHANGE_ME
G1_FIXED_START_YAW=CHANGE_ME
G1_LOCALIZATION_RETRY_SECONDS=2
G1_SLAM_RESET_WAIT_SECONDS=3
G1_WEB_PORT=8088
G1_VOICE_VOLUME=90
G1_ALLOW_REAL_MOTION=1
G1_ALLOW_RAMP_RETURN=1
G1_ALLOW_MODE_COMMANDS=1
G1_ENABLE_TOUR=0
```

地图路径和固定起点必须来自当前 G1 自己的官方地图与标点结果。`G1_ROBOT_ID` 必须与现场其他机器人不同。

## 一键持久开启完整路线权限

仅在当前 G1 已完成定位、单机命令隔离、五条路线、返回稳定性和急停验收后执行：

```bash
cd /home/unitree/unitree-g1-ramp-stack

sudo ./deploy/enable_motion.sh \
  --unlock-all \
  --enable-boot
```

该操作会备份 `/etc/default/g1-ramp-stack`，把三个可选授权持久改为 `1`，启用并启动全局停止路由和本地助手。它不会发布任何运动命令。

重启后先检查：

```bash
g1-ramp status
pgrep -af '/ros2/g1_motion_bridge.py'
```

要求定位许可为当前 `boot_id`、地图路径正确且运动桥恰好一个。随后可逐条使用：

```bash
g1-ramp prepare
g1-ramp straight-forward
g1-ramp straight-return
g1-ramp turning-forward
g1-ramp turning-return
g1-ramp stop
```

“持久开启”只表示无需每次开机修改三个授权；仍必须等上一条路线完成再发下一条。基础的定位许可、机器身份、本机话题隔离和全局停止不可删除。
