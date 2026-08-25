# 当前地图直接启用完整项目

本文适用于官方地图和本次开机定位已经完成、现在只缺真实运动桥的 G1。可以先在当前地图标记全部需求点位并测试，后续换图时再重新标点。

启动脚本本身不会发布运动动作。真正的前进、返回和导览命令只在操作员随后明确执行时发布。

## 1. 安装本次更新

```bash
cd /home/unitree/unitree-g1-ramp-stack
git pull --ff-only

sudo /usr/bin/bash \
./deploy/install.sh \
--allow-existing \
--install-python-deps
```

安装程序会先完整备份现有 `/home/unitree/智能中控`，不启动服务。

立即验证 systemd 实际使用的系统 Python、ROS 与项目 `vendor` 环境：

```bash
./deploy/verify_python_runtime.sh
```

必须输出 `PYTHON_RUNTIME_OK`。不要只执行裸的 `/usr/bin/python3 -c 'import httpx'`；它不能证明 systemd 启动脚本已经加载项目 `vendor`。

## 2. 启动真实运动链路

先检查 `/etc/default/g1-ramp-stack`。每台机器必须使用不同的 `G1_ROBOT_ID`，`G1_UNITREE_INTERFACE` 必须是本机内部控制网口。首次启动先保持：

```text
G1_ALLOW_REAL_MOTION=0
G1_ALLOW_RAMP_RETURN=0
G1_ALLOW_MODE_COMMANDS=0
G1_ENABLE_TOUR=0
```

完成本机隔离、保护架和急停验收后，只在当前目标 G1 把 `G1_ALLOW_REAL_MOTION=1`。`enable_motion.sh` 会在总开关不是 `1` 时拒绝启动真实运动链路。

仅本次开机启动：

```bash
cd /home/unitree/unitree-g1-ramp-stack

sudo /usr/bin/bash \
./deploy/enable_motion.sh
```

同时设置以后开机自启：

```bash
sudo /usr/bin/bash \
./deploy/enable_motion.sh \
--enable-boot
```

正常输出必须包含：

```text
全局停止路由：active
本地智能中控：active
运动桥实例数：1
```

单独查看：

```bash
systemctl is-active g1-global-stop-router.service
systemctl is-active g1-local-assistant.service
pgrep -af '/ros2/g1_motion_bridge.py'
```

`pgrep` 必须只有一个运动桥。不要使用 `nohup` 手工启动第二份。

脚本使用非阻塞方式提交本地助手启动，不会再被持续重试的 `g1-ramp-v3-bootstrap.service` 卡住。定位尚未成功时，停止命令可用，但前进和路线命令仍会被定位许可门拒绝。

## 3. 急停命令

在另一个终端保持以下命令随时可执行：

```bash
g1-ramp stop
```

## 4. 在当前地图标记全部需求点位

让 G1 到达对应位置，站直、静止并保持路线需要的朝向，然后依次执行：

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

两条坡道路线共用 `straight_begin` 和 `straight_end`。转弯路线为：

```text
straight_begin → turn_1 → turn_2 → turn_3 → straight_end
```

返回时按相反顺序执行。自定义导览点可以通过网页控制端增加、删除、自命名和重新排序。

运动桥会在每次路线命令开始时直接读取这些 JSON 点位；重新标点后不需要修改 Python 源码，也不需要再手工填写旧版 `route.json`。转弯路线的中间朝向根据相邻新点位自动计算，终点朝向使用标点时保存的朝向。

## 5. 启用网页和语音

```bash
sudo systemctl enable --now \
g1-voice-bridge.service \
g1-web-control.service
```

导览包含示教手臂动作，默认保持 `G1_ENABLE_TOUR=0`。完成单机安全验证后再单独启用导览执行器。

网页令牌：

```bash
cat \
/home/unitree/智能中控/data/web_control/access_token
```

若令牌文件还不存在：

```bash
sudo journalctl \
-u g1-web-control.service \
-n 80 --no-pager -o cat
```

## 6. 完整项目操作命令

```bash
g1-ramp status
g1-ramp odom

g1-ramp prepare
g1-ramp straight-forward
g1-ramp turning-forward

g1-ramp stop
g1-ramp result
g1-ramp logs
```

对应语音指令保持不变：

- “小智小智，直线前进”
- “小智小智，转弯前进”
- “小智小智，停止”

直线返回和转弯返回仍须在对应安全锁解除后测试。发生过返回卸力或跌倒事故时，保持 `G1_ALLOW_RAMP_RETURN=0`，不得用语音、网页或 CLI 绕过。

## 7. 后续更换全景地图

更换地图后旧坐标不能继续使用。必须修改 `/etc/default/g1-ramp-stack` 中的地图路径，清除旧地图的开机定位状态，在新地图重新设置固定开机点，并重新标记上述所有路线点和导览点。

完整换图流程见 [TEST_MAP_TO_PANORAMA.md](TEST_MAP_TO_PANORAMA.md)。
