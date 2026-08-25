# Unitree G1 语音爬坡与导览控制栈

这是从一台已运行的 Unitree G1 项目中整理出的可迁移版本，覆盖：

- G1 内置麦克风唤醒、ASR 文本接入和机身扬声器 TTS；
- “直线前进 / 直线返回 / 转弯前进 / 转弯返回 / 停止”确定性语音路由；
- Unitree 官方雷达、SLAM 定位和 `goto` 导航链路；
- 固定起点短周期重复定位、本机起点微调学习，成功后播报“全局定位成功”；
- Token 保护的网页控制、路线按钮、点位采集和导览编辑；
- 三点导览、Please 示教动作、讲解文本与坡道演示编排；
- 全局停止路由、实时里程计缓存、可信姿态保存和命令行工具。

## 重要边界

1. 本仓库面向已完成 Unitree 官方 SDK2、ROS 2 Humble、雷达和内部网络配置的 G1。
2. `maps/g1_embodied_lab_panorama_v2_nx_reference.pcd.part-*` 是 NX 侧采集参考点云的分片；运行 `bash maps/assemble_reference_map.sh` 可无损重组。它不保证能被官方 SLAM 直接加载。
3. 官方导航地图的 `address` 可能指向 G1 内部控制单元文件系统，NX 上 `ls` 不到并不表示不存在。必须用 `g1_slam_cli.py initialize` 验证。
4. 路线坐标只对生成它的地图坐标系有效。换地图、地图原点或场地后必须重新标点。
5. 官方 `goto` 在部分固件上会把 FSM 切到 501。项目自身不主动请求“越障模式”，但不能承诺官方导航不改变底层 FSM。
6. 首次现场验收必须有保护架/防跌倒措施、遥控急停人员和净空区域。
7. 每台 G1 独立建图、标点和学习开机修正；部署和运行都不需要连接源 G1。

## 仓库结构

```text
runtime/       实际部署到 /home/unitree/智能中控 的代码和配置
systemd/units/ 开机服务模板
bin/           g1-ramp 与 g1-map-point
deploy/        前置检查、安装、激活、只读验证和停用脚本
config/        站点配置模板及源场地路线数据
maps/          NX 参考点云分片、重组脚本与元数据
docs/          架构、地图迁移、安全验收和完整部署手册
```

## 新 G1 快速部署

仓库公开地址：<https://github.com/Suhang656/unitree-g1-ramp-stack>。

先完整阅读 [新 G1 部署手册](docs/DEPLOY_NEW_G1.md)、[当前地图直接启用完整项目](docs/RUN_COMPLETE_PROJECT.md)、[已验证目标 G1 配置](docs/VERIFIED_TARGET_G1.md)、[地图迁移说明](docs/MAP_MIGRATION.md)、[测试小地图切换全景地图](docs/TEST_MAP_TO_PANORAMA.md)、[开机定位说明](docs/BOOT_LOCALIZATION.md) 和 [安全验收](docs/SAFETY_ACCEPTANCE.md)。摘要如下：

```bash
git clone https://github.com/Suhang656/unitree-g1-ramp-stack.git \
  /home/unitree/unitree-g1-ramp-stack
cd /home/unitree/unitree-g1-ramp-stack

G1_UNITREE_INTERFACE="$(ip route get 192.168.123.161 | awk '{for(i=1;i<=NF;i++) if($i==\"dev\") {print $(i+1); exit}}')" \
./deploy/check_prerequisites.sh

sudo ./deploy/install.sh --install-python-deps
./deploy/verify_python_runtime.sh
sudoedit /etc/default/g1-ramp-stack
```

每台 G1 必须分别设置不同的 `G1_ROBOT_ID`，例如 `source_g1`、`target_g1`。项目动作总线强制只在本机回环通信，不能依靠相同 hostname 或可能被镜像复制的 `machine-id` 区分机器人。新安装默认保持 `G1_ALLOW_REAL_MOTION=0`、`G1_ALLOW_RAMP_RETURN=0` 和 `G1_ALLOW_MODE_COMMANDS=0`。

随后在目标 G1 上创建或验证官方 SLAM 地图，采集新的起点和路线点。只有官方 `initialize` 成功后，才把：

```text
G1_INTERNAL_MAP_VERIFIED=1
```

写入 `/etc/default/g1-ramp-stack`，再执行：

```bash
sudo ./deploy/activate.sh
./deploy/verify.sh
```

`activate.sh` 不再同步等待可能长期重试的全局定位；急停、本地助手和网页会独立启动，定位在后台继续。没有当前 `boot_id` 的有效定位许可时，路线命令仍会被运动桥拒绝。

在单机隔离、定位、保护措施和急停全部验收后，可显式持久开启三个可选运动授权并设置运动链路开机自启：

```bash
sudo ./deploy/enable_motion.sh --unlock-all --enable-boot
```

该命令不会发布任何动作，也不会删除定位许可、`robot_id`、本机话题隔离和全局停止保护。授权生效后仍须先用 `g1-ramp status` 确认本次开机定位有效，再逐条执行路线命令。

现场从零复现和本次部署问题的统一修复方法见 [现场最佳复现流程](docs/FIELD_REPRODUCTION.md)。

## 用户命令

```bash
g1-ramp status
g1-ramp odom
g1-ramp straight-forward
g1-ramp straight-return
g1-ramp turning-forward
g1-ramp turning-return
g1-ramp stop

g1-map-point check
g1-map-point mark straight_begin
g1-map-point mark straight_end
g1-map-point mark turn_1
g1-map-point list
```

确定性语音指令：

- 小智小智，直线前进
- 小智小智，直线返回
- 小智小智，转弯前进
- 小智小智，转弯返回
- 小智小智，停止

网页地址为 `http://<G1无线IP>:8088/`。首次启动后在 G1 本机读取 Token：

```bash
cat /home/unitree/智能中控/data/web_control/access_token
```

## 安全设计

- 安装脚本不启用服务、不启动机器人、不发布动作命令；
- 地图未人工确认时，激活脚本拒绝继续；
- 定位许可绑定当前 `boot_id` 和地图路径；
- 开机点位自调整记录绑定本机地图，并受人工起点位置/朝向双重阈值约束；
- 点位采集要求本次开机定位有效，并检查静止采样波动；
- 网页写操作要求随机 Token；
- 动作 ROS 话题按 `G1_ROBOT_ID` 命名，并强制 `ROS_LOCALHOST_ONLY=1`；
- Unitree 内部网口必须由 `G1_UNITREE_INTERFACE` 显式配置并通过路由检查；
- 新部署的真实运动、返回路线、模式切换和导览默认锁定；
- 全局停止路由独立运行；
- `verify.sh` 仅做只读检查。

## 来源与验证状态

整理基线来自一套已经现场运行的 G1 项目。代码、路线、服务关系和地图行为已经做过只读审计；仓库不会包含设备 IP、Token、数据库、日志、开机许可、开机微调记录或 Wi-Fi 密码。新 G1 不需要连接原设备。详见 [现场基线审计](docs/SOURCE_AUDIT.md) 和 [故障排查](docs/TROUBLESHOOTING.md)。
