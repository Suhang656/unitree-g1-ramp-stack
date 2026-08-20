# 官方 SLAM 地图迁移与重建

## 两类 PCD 不能混淆

- **NX 参考点云**：由 ROS 话题 `/unitree/slam_mapping/points` 本地记录，可查看、备份和比较；本仓库附带一份参考 PCD。
- **官方内部导航地图**：由 `slam_operate` 的 `stop-map <address>` 保存，并由 `initialize -- <address> x y yaw` 加载。`address` 可能位于内部控制单元，NX 的 `find/ls` 未必能看到。

普通 NX PCD 在源机曾返回 `507 Load pcd failed`，因此复制参考 PCD不能视为完成迁移。

## 推荐方案：目标 G1 重建官方地图

只启动官方雷达和 SLAM，不启动本项目运动服务：

```bash
sudo systemctl stop g1-local-assistant.service g1-ramp-v3-bootstrap.service 2>/dev/null || true
sudo systemctl start g1-navigation-services.service
```

设置 SDK 环境：

```bash
export PROJECT=/home/unitree/智能中控
export G1_IF=enP8p1s0
export PYTHONPATH="$PROJECT/vendor:/home/unitree/unitree_sdk2_python"
export CYCLONEDDS_HOME=/home/unitree/cyclonedds-prefix
export LD_LIBRARY_PATH=/home/unitree/cyclonedds-prefix/lib
```

开始建图：

```bash
timeout 40s /usr/bin/python3 -u \
  "$PROJECT/scripts/g1_slam_cli.py" \
  "$G1_IF" start-map
```

确认建图点云约 10 Hz：

```bash
source /opt/ros/humble/setup.bash
source /home/unitree/unitree_ros2/cyclonedds_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ROS_DOMAIN_ID=0 ROS_LOCALHOST_ONLY=0 ROS2CLI_DISABLE_DAEMON=1
export CYCLONEDDS_URI='<CycloneDDS><Domain Id="any"><General><Interfaces><NetworkInterface name="enP8p1s0"/></Interfaces></General></Domain></CycloneDDS>'
timeout 15s ros2 topic hz /unitree/slam_mapping/points
```

缓慢遍历场地、保持重叠、完成闭环并回到固定起点。实时监控：

```bash
/usr/bin/bash "$PROJECT/scripts/start_g1_mapping_monitor.sh"
```

结束并让官方服务保存地图：

```bash
timeout 240s /usr/bin/python3 -u \
  "$PROJECT/scripts/g1_slam_cli.py" \
  "$G1_IF" stop-map \
  /home/unitree/g1_internal_panorama_v2.pcd
```

`Save pcd successfully` 是官方服务确认；不要只依赖 NX 的 `ls`。

## 必须做的加载验证

G1 回到地图原点/固定起点并站直，先关闭旧会话：

```bash
timeout 20s /usr/bin/python3 -u "$PROJECT/scripts/g1_slam_cli.py" "$G1_IF" close || true
sleep 5
timeout 60s /usr/bin/python3 -u "$PROJECT/scripts/g1_slam_cli.py" "$G1_IF" initialize -- \
  /home/unitree/g1_internal_panorama_v2.pcd 0.0 0.0 0.0
```

- `errorCode 0`：地图可加载，再读取 `/unitree/slam_relocation/odom` 并采集精确起点；
- `507`：文件格式/存储位置不是官方可加载地图；
- `509`：地图已加载但初始姿态匹配度低，需要调整 x/y/yaw 候选或让 G1 站直；
- `3202`：RPC 服务未就绪或接口链路错误，先检查导航服务、SDK 环境和网卡。

只有完成一次成功 initialize，并确认位置稳定，才设置：

```text
G1_INTERNAL_MAP_VERIFIED=1
```

## 源地图直接复制的条件

只有在 Unitree 官方提供内部地图导出/导入方法、并在目标控制单元完成导入后，才可复用源地图。仓库中的参考点云先用 `bash maps/assemble_reference_map.sh` 重组；仅把重组得到的 `*_nx_reference.pcd` 复制到 NX，仍不满足官方内部地图导入条件。

即便同一张地图复制成功，不同机器雷达外参、固件和初始姿态也要重新验收；路线坐标可作为候选，但不能跳过逐点验证。
