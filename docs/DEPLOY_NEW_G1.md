# 全新 G1 部署手册

本文适用于第二台或任意全新 G1。部署目标是复现语音控制、网页控制、官方 SLAM 定位、直线/转弯坡道路线和导览功能。

## 0. 安全与前提

- G1 固件、SDK2 Python、ROS 2 Humble、Unitree ROS 2 消息包和 Mid360 已由官方配置；
- 内部网卡能访问 `192.168.123.161`；
- 首次部署时机器人断开路线执行权限，放在平地并站直；
- 操作员持遥控器并可立即急停；
- 不把源 G1 和目标 G1 同时接入同一 DDS 网段进行运动测试。

记录目标机：

```bash
hostname
cat /etc/machine-id
ip -br -4 address
ip route get 192.168.123.161
```

两台 G1 出厂镜像可能有相同 hostname，必须用 `machine-id` 和无线 MAC 区分。

## 1. 获取私有仓库与只读检查

推荐在已经登录 GitHub 的管理电脑上克隆，再复制到 G1。这样不需要在机器人上保存 GitHub 账户凭据：

```bash
git clone git@github.com:Suhang656/unitree-g1-ramp-stack.git
scp -r unitree-g1-ramp-stack \
  unitree@<G1无线IP>:/home/unitree/
```

也可以为目标 G1 创建本仓库专用的只读 Deploy Key：

```bash
ssh-keygen -t ed25519 \
  -f ~/.ssh/unitree_g1_ramp_deploy \
  -N ''
cat ~/.ssh/unitree_g1_ramp_deploy.pub
```

把公钥添加到 GitHub 仓库的 `Settings → Deploy keys`，不要勾选写权限。随后配置只使用该密钥：

```bash
cat >>~/.ssh/config <<'EOF'
Host github-g1-ramp
  HostName ssh.github.com
  Port 443
  User git
  IdentityFile ~/.ssh/unitree_g1_ramp_deploy
  IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config

git clone \
  git@github-g1-ramp:Suhang656/unitree-g1-ramp-stack.git \
  /home/unitree/unitree-g1-ramp-stack
```

不要把私钥、GitHub Token 或 `~/.ssh` 复制进项目目录。

复制完成后，在目标 G1 执行只读检查：

```bash
cd /home/unitree/unitree-g1-ramp-stack

G1_NETWORK_INTERFACE=enP8p1s0 \
G1_CONTROL_IP=192.168.123.161 \
./deploy/check_prerequisites.sh
```

缺少 `rmw_cyclonedds_cpp` 时：

```bash
sudo apt-get update
sudo apt-get install -y ros-humble-rmw-cyclonedds-cpp python3-pip
```

## 2. 安装（不会启动服务）

全新机器：

```bash
sudo ./deploy/install.sh --install-python-deps
```

若 `/home/unitree/智能中控` 已存在，先人工审计，再执行：

```bash
sudo ./deploy/install.sh --allow-existing --install-python-deps
```

该模式会先复制完整备份到 `/home/unitree/智能中控.before_portable_install_时间戳`。安装不会 enable/start 服务，也不会发布运动请求。

## 3. 配置目标机

```bash
sudoedit /etc/default/g1-ramp-stack
sudoedit /home/unitree/智能中控/.env
```

重点核对：

```text
G1_NETWORK_INTERFACE=enP8p1s0
G1_CONTROL_IP=192.168.123.161
UNITREE_SDK2_PYTHON_PATH=/home/unitree/unitree_sdk2_python
CYCLONEDDS_COMPAT_PREFIX=/home/unitree/cyclonedds-prefix
UNITREE_ROS2_SETUP=/home/unitree/unitree_ros2/cyclonedds_ws/install/setup.bash
G1_INTERNAL_MAP_PATH=/home/unitree/g1_internal_panorama_v2.pcd
G1_INTERNAL_MAP_VERIFIED=0
```

此时保持 `G1_INTERNAL_MAP_VERIFIED=0`。

## 4. 准备目标 G1 的官方地图

严格按 [MAP_MIGRATION.md](MAP_MIGRATION.md) 操作。最可靠方式是在目标 G1 用官方 `start-map` / `stop-map` 建图，并通过官方 `initialize` 验证内部地图。

验证成功后：

```bash
sudo sed -i 's/^G1_INTERNAL_MAP_VERIFIED=.*/G1_INTERNAL_MAP_VERIFIED=1/' /etc/default/g1-ramp-stack
```

## 5. 采集目标机固定起点

先手动启动导航服务和初始化定位，不启动运动桥。G1 在坡道起点站直、朝向终点：

```bash
sudo systemctl start g1-navigation-services.service
g1-map-point mark straight_begin
```

将输出 JSON 的 `x/y/yaw` 写入 `/etc/default/g1-ramp-stack` 的 `G1_FIXED_START_X/Y/YAW`。注意：`g1-map-point` 要求已经有本次开机定位许可；首次建站可直接用 `capture_turning_waypoint.py` 采样，或在官方 initialize 成功后生成临时许可，详见地图文档。

## 6. 重新标定两条路线

必须在目标地图坐标系重新采集：

```bash
g1-map-point mark straight_begin
g1-map-point mark straight_end
g1-map-point mark turn_1
g1-map-point mark turn_2
g1-map-point mark turn_3
```

然后更新：

- `data/embodied_lab_panorama_v2/routes_v1.json`
- `data/turning_route_v1/route.json`
- 各点位 JSON 的 `map_path`

两条路线应共用 `straight_begin` 和 `straight_end`。转弯路线顺序为：

```text
straight_begin → turn_1 → turn_2 → turn_3 → straight_end
```

返回顺序严格反向。先用官方 `goto` 逐点低风险验证，再串联路线。

## 7. 启用开机服务

```bash
cd /home/unitree/unitree-g1-ramp-stack
sudo ./deploy/activate.sh
./deploy/verify.sh
```

检查运动桥必须只有一个：

```bash
pgrep -af g1_motion_bridge.py
```

检查定位成功、地图路径正确、`boot_id匹配: True` 后，才可进入运动验收。

## 8. 分级现场验收

1. 只读：`g1-ramp status`、`g1-ramp odom`、网页状态；
2. 停止链路：在机器人静止时测试网页停止、`g1-ramp stop`、语音停止；
3. 单点官方 goto：0.5–1 m 平地短距离；
4. 直线路线平地段；
5. 转弯路线各段；
6. 最后才在有保护措施的坡道测试。

验收项见 [SAFETY_ACCEPTANCE.md](SAFETY_ACCEPTANCE.md)。

## 9. 网页与语音

```bash
cat /home/unitree/智能中控/data/web_control/access_token
ip -br -4 address
```

浏览器打开 `http://G1无线IP:8088/` 并填写 Token。验证五条命令：直线前进、直线返回、转弯前进、转弯返回、停止。

## 10. 停用与回滚

```bash
cd /home/unitree/unitree-g1-ramp-stack
sudo ./deploy/uninstall.sh
```

停用脚本不删除项目、地图和数据。若安装前已有旧项目，可在所有服务停止后从时间戳备份恢复。
