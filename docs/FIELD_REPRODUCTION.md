# 现场最佳复现流程

本文汇总第二台全新 G1 现场部署中实际暴露的问题，并给出从零复现语音、网页、官方定位、坡道路线和导览功能的最短可靠流程。

## 一、最终有效的设计原则

1. **安装、定位、运动分三阶段**：安装不启服务；定位不启运动；只有地图、起点、路线和急停验收后才启真实运动。
2. **系统 Python 与应用依赖分层**：ROS 2 Humble 使用 `/usr/bin/python3`，应用依赖固定安装到 `/home/unitree/智能中控/vendor`，所有启动脚本显式加载该目录。
3. **定位不能阻塞急停与助手**：开机定位允许短周期持续重试，但本地助手和全局停止路由不再 `Requires/After` 定位服务。
4. **定位许可仍是运动硬门**：运动桥在线不等于允许路线运动。许可必须绑定当前 `boot_id` 与当前地图。
5. **运动桥严格单实例**：只能由 `g1-local-assistant.service` 管理，不手工 `python3`、不 `nohup` 启动第二份。
6. **地图坐标不可迁移**：换地图后重新采集固定起点、共享终点、三个转弯点和全部导览点。
7. **命令总线不能跨机器**：ROS 动作话题强制本机回环，并按每台 G1 独立的 `G1_ROBOT_ID` 命名。
8. **内部网口不能写死**：`G1_UNITREE_INTERFACE` 由本机到 `192.168.123.161` 的路由确定，启动前必须核验。

## 二、全新机器安装

```bash
git clone https://github.com/Suhang656/unitree-g1-ramp-stack.git \
  /home/unitree/unitree-g1-ramp-stack
cd /home/unitree/unitree-g1-ramp-stack

G1_UNITREE_INTERFACE="$(ip route get 192.168.123.161 | awk '{for(i=1;i<=NF;i++) if($i==\"dev\") {print $(i+1); exit}}')" \
G1_CONTROL_IP=192.168.123.161 \
./deploy/check_prerequisites.sh

sudo ./deploy/install.sh --install-python-deps
./deploy/verify_python_runtime.sh
```

已有 `/home/unitree/智能中控` 时使用：

```bash
sudo ./deploy/install.sh --allow-existing --install-python-deps
./deploy/verify_python_runtime.sh
```

安装程序会先备份旧项目。依赖验证必须输出 `PYTHON_RUNTIME_OK`，否则不要启动任何项目服务。

## 三、地图、起点和许可

1. 编辑 `/etc/default/g1-ramp-stack`，保持 `G1_INTERNAL_MAP_VERIFIED=0`。
2. 仅启动 `g1-navigation-services.service`，按 `MAP_MIGRATION.md` 建图或加载官方内部地图。
3. 官方 `initialize` 返回成功且重定位里程计稳定后，直接使用 `capture_turning_waypoint.py` 采集首次人工起点。
4. 将本机采集的 `x/y/yaw` 写入 `G1_FIXED_START_X/Y/YAW`，确认地图地址后设置 `G1_INTERNAL_MAP_VERIFIED=1`。
5. G1 留在固定起点、站直、朝向终点，启动 `g1-ramp-v3-bootstrap.service`；成功后必须看到当前开机许可。

```bash
sudo systemctl start --no-block g1-ramp-v3-bootstrap.service
sudo journalctl -u g1-ramp-v3-bootstrap.service -f -n 0 -o cat
g1-ramp status
```

只有 `success: True`、`boot_id匹配: True`、地图路径正确才进入下一阶段。

## 四、重新标点

```bash
g1-map-point mark straight_begin
g1-map-point mark straight_end
g1-map-point mark turn_1
g1-map-point mark turn_2
g1-map-point mark turn_3
g1-map-point mark guide_1
g1-map-point mark guide_2
g1-map-point mark guide_3
```

每次采样时 G1 必须站直、静止并保持到点后的目标朝向。两条坡道路线共用 `straight_begin` 和 `straight_end`；运动桥会在命令开始时读取最新 JSON。

## 五、启用服务并保持真实运动锁定

```bash
cd /home/unitree/unitree-g1-ramp-stack
sudo ./deploy/activate.sh
./deploy/verify.sh

systemctl is-active g1-global-stop-router.service
systemctl is-active g1-local-assistant.service
pgrep -af '/ros2/g1_motion_bridge.py|/ros2/smart_center_node.py'
```

助手和运动桥各只能有一个进程。`activate.sh` 不会发布动作；定位仍可在后台重试。

配置中必须先保持：

```text
G1_ALLOW_REAL_MOTION=0
G1_ALLOW_RAMP_RETURN=0
G1_ALLOW_MODE_COMMANDS=0
G1_ENABLE_TOUR=0
```

只有完成本机话题、robot ID、保护架和急停验收后，才在当前目标 G1 临时设置 `G1_ALLOW_REAL_MOTION=1`。源 G1 继续保持为 `0`。

## 六、分级运动验收

机器人佩戴保护、操作员握持遥控急停，命令逐条执行，不串联复制。发生过返回跌倒事故时不要执行任何返回命令：

```bash
g1-ramp stop
g1-ramp status
g1-ramp odom
g1-ramp prepare
g1-ramp straight-forward
g1-ramp turning-forward
```

先验证停止，再验证平地短距离，最后才测试坡道。若 `localization_ready.json` 不存在或不匹配当前开机，保持机器人静止并修复定位，不绕过许可。

## 七、现场问题与最终修复对应关系

| 现场现象 | 根因 | 当前解决方法 |
|---|---|---|
| `ModuleNotFoundError: httpx/pydantic` | systemd 节点未加载项目 `vendor` | 安装完整 requirements，`start_ros2_node.sh` 显式加入 vendor，运行依赖验证 |
| `g1-local-assistant` 长期 `activating` | 强依赖无限重试的定位服务 | systemd 解耦，定位和助手使用非阻塞启动 |
| `AMENT_TRACE_SETUP_FILES: unbound variable` | ROS setup 前启用 `set -u` | ROS setup 完成后再启用 nounset |
| `target: unbound variable` | 同一行 local 声明提前引用变量 | target/action/task 分行赋值 |
| 两个运动桥 | 手工启动与 systemd 重复 | `enable_motion.sh` 单实例拒绝策略 |
| 服务在线但路线不能动 | 本次开机许可不存在 | 这是安全门；先完成定位，不复制或伪造许可 |
| 新 G1 测试时源 G1 也运动 | 公共 Domain/话题经无线网络被另一运动桥发现 | 命令总线本机化、每机独立 `G1_ROBOT_ID`、动作消息校验 robot ID |
| 返回时关节卸力或跌倒 | 原因尚需结合官方导航 FSM 和事故日志确认 | `G1_ALLOW_RAMP_RETURN=0` 硬锁返回，模式命令和导览也默认锁定 |

## 八、换正式全景地图

测试小地图验证软件后，按 `TEST_MAP_TO_PANORAMA.md` 切换全景地图。保留语音命令、网页界面和导览编排，但清理旧地图许可与微调状态，并重新采集所有地图相关点位。
