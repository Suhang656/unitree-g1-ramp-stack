# 从测试小地图切换到全景地图

本文适用于：当前 G1 只有覆盖一小部分场景的测试地图，先验证软件功能；现场验收通过后重新构建全景地图，并在新坐标系重新标记全部需求点。

## 1. 换地图后哪些数据必须重做

以下内容与地图坐标系绑定，不能从测试小地图沿用：

- `G1_FIXED_START_X/Y/YAW`；
- 直线路线起点、终点；
- 转弯路线全部拐点；
- 全部导览点；
- `localization_ready.json`；
- `boot_start_adjustment.json`；
- `last_localization_pose.json`。

语音命令、网页按钮、路线名称、导览讲解文字和动作编排可以保留，只替换地图地址和点位坐标。

## 2. 测试小地图阶段

小地图只用于停止链路、网页、语音、短距离平地、点位编辑等软件验收。保存当前配置：

```bash
sudo cp -a /etc/default/g1-ramp-stack \
  /etc/default/g1-ramp-stack.before_panorama_$(date +%Y%m%d_%H%M%S)
cp -a /home/unitree/智能中控/data/embodied_lab_panorama_v2 \
  /home/unitree/智能中控/data/embodied_lab_panorama_v2.before_panorama_$(date +%Y%m%d_%H%M%S)
```

## 3. 停止项目运动服务

G1 站在平地，操作员持急停。停止上层运动服务，只保留导航服务：

```bash
sudo systemctl stop \
  g1-local-assistant.service \
  g1-web-control.service \
  g1-tour-executor.service \
  g1-ramp-v3-bootstrap.service

pgrep -af 'g1_motion_bridge.py|g1_tour_executor.py' \
  || echo "运动桥和导览执行器均未运行"

sudo systemctl start g1-navigation-services.service
```

建图期间使用遥控器人工缓慢移动，不运行项目路线命令。

## 4. 开始全景建图

```bash
export PROJECT=/home/unitree/智能中控
export G1_IF=enP8p1s0
export PYTHONPATH="$PROJECT/vendor:/home/unitree/unitree_sdk2_python"
export CYCLONEDDS_HOME=/home/unitree/cyclonedds-prefix
export LD_LIBRARY_PATH=/home/unitree/cyclonedds-prefix/lib

timeout 20s /usr/bin/python3 -u \
  "$PROJECT/scripts/g1_slam_cli.py" "$G1_IF" close || true
sleep 5
timeout 40s /usr/bin/python3 -u \
  "$PROJECT/scripts/g1_slam_cli.py" "$G1_IF" start-map
```

看到 `Successfully started mapping` 后再移动。另开终端运行：

```bash
/usr/bin/bash "$PROJECT/scripts/start_g1_mapping_monitor.sh"
```

建图原则：

- 从未来固定开机起点开始；
- 缓慢行走，避免快速旋转和剧烈俯仰；
- 相邻路线保持重叠；
- 门口、走廊、坡道上下和房间连接处从多个方向重复经过；
- 完整遍历后回到起点形成闭环；
- 点云中断时立即停止移动，不在断流状态继续走。

## 5. 保存官方全景地图

使用一个新的官方内部地图地址：

```bash
export PANORAMA_MAP=/home/unitree/g1_internal_panorama_v3.pcd

timeout 240s /usr/bin/python3 -u \
  "$PROJECT/scripts/g1_slam_cli.py" "$G1_IF" stop-map "$PANORAMA_MAP"
```

必须看到 `Save pcd successfully`。`stop-map` 只能消费一次当前建图缓存；再次执行返回 `505 Pcd buffer less than 1` 通常表示第一次已经完成。

官方地图可能位于内部控制单元，NX 上 `ls "$PANORAMA_MAP"` 找不到不能判定保存失败。NX 参考点云只用于查看和备份，不替代官方地图。

## 6. 加载验证

G1 回到建图起点，站直并保持开始建图时的朝向：

```bash
timeout 20s /usr/bin/python3 -u \
  "$PROJECT/scripts/g1_slam_cli.py" "$G1_IF" close || true
sleep 5
timeout 60s /usr/bin/python3 -u \
  "$PROJECT/scripts/g1_slam_cli.py" "$G1_IF" initialize -- \
  "$PANORAMA_MAP" 0.0 0.0 0.0
```

若返回 `509`，保持 G1 站直，围绕实际建图原点小幅调整 x/y/yaw 初值。不要使用测试地图坐标。只有 `errorCode 0` 且 `/unitree/slam_relocation/odom` 稳定，才进入下一步。

## 7. 首次采集全景地图固定起点

此时尚无本次开机许可，不能调用 `g1-map-point mark`。直接采样官方重定位里程计：

```bash
unset PYTHONPATH PYTHONHOME AMENT_PREFIX_PATH CMAKE_PREFIX_PATH COLCON_PREFIX_PATH CYCLONEDDS_HOME CYCLONEDDS_URI
source /opt/ros/humble/setup.bash
source /home/unitree/unitree_ros2/cyclonedds_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DOMAIN_ID=0 ROS_LOCALHOST_ONLY=0 ROS2CLI_DISABLE_DAEMON=1
export CYCLONEDDS_URI='<CycloneDDS><Domain Id="any"><General><Interfaces><NetworkInterface name="enP8p1s0"/></Interfaces></General></Domain></CycloneDDS>'

cd /home/unitree/智能中控
/usr/bin/python3 -u scripts/capture_turning_waypoint.py \
  data/embodied_lab_panorama_v2/straight_begin.json
```

编辑配置：

```bash
sudoedit /etc/default/g1-ramp-stack
```

写入：

```text
G1_INTERNAL_MAP_PATH=/home/unitree/g1_internal_panorama_v3.pcd
G1_INTERNAL_MAP_VERIFIED=1
G1_FIXED_START_X=<新x>
G1_FIXED_START_Y=<新y>
G1_FIXED_START_YAW=<新yaw>
```

清除全部测试地图运行状态：

```bash
rm -f \
  /home/unitree/智能中控/data/ramp_platform_v3/localization_ready.json \
  /home/unitree/智能中控/data/ramp_platform_v3/boot_start_adjustment.json \
  /home/unitree/智能中控/data/ramp_platform_v3/last_localization_pose.json
```

## 8. 验证全景地图开机定位

G1 保持在新固定起点：

```bash
sudo systemctl restart g1-ramp-v3-bootstrap.service
sudo journalctl -u g1-ramp-v3-bootstrap.service -f -n 0 -o cat
```

定位成功后：

```bash
g1-map-point check
g1-ramp status
```

确认地图路径、定位许可和当前 `boot_id` 一致后，才采集其它点。

## 9. 重新标记全部需求点

逐点把 G1 移到目标位置，站直、静止并保持所需朝向：

```bash
g1-map-point mark straight_begin
g1-map-point mark straight_end
g1-map-point mark turn_1
g1-map-point mark turn_2
g1-map-point mark turn_3
g1-map-point mark guide_1
g1-map-point mark guide_2
g1-map-point mark guide_3
g1-map-point list
```

网页可新增自命名导览点；路线固定点建议保留上述受控名称。更新并核查：

```text
data/embodied_lab_panorama_v2/routes_v1.json
data/turning_route_v1/route.json
data/embodied_lab_panorama_v2/tour_config.json
```

两条坡道路线共用新的 `straight_begin` 和 `straight_end`。导览顺序和讲解文字可保留，但坐标必须来自全景地图。

## 10. 分级重新验收

换地图等同重新部署：

1. 只读检查定位、里程计、地图路径；
2. 验证全局停止链路；
3. 官方 `goto` 逐个验证 0.5–1 m 平地目标；
4. 验证所有拐点位置和朝向；
5. 验证直线前进/返回；
6. 验证转弯前进/返回；
7. 验证导览逐站确认、讲解和 Please 动作；
8. 最后在保护措施下测试坡道。

全部通过后再启用完整服务：

```bash
cd /home/unitree/unitree-g1-ramp-stack
sudo ./deploy/activate.sh
./deploy/verify.sh
```
