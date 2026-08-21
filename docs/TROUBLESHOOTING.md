# 故障排查

所有排查先让 G1 静止并由操作员持有急停。除明确写出的测试外，以下命令不发布运动。

## `g1-map-point` 提示没有许可或不允许

`g1-map-point mark` 只允许在当前开机定位已经通过后使用：

```bash
g1-map-point check
g1-ramp status
```

首次建站存在先后关系：先让官方 `initialize` 成功并确认 `/unitree/slam_relocation/odom` 稳定，再直接运行 `capture_turning_waypoint.py` 采集第一个起点；此时不要伪造正式许可。完整命令见 [DEPLOY_NEW_G1.md](DEPLOY_NEW_G1.md)。

## 官方 SLAM 返回码

- `0`：请求成功；
- `505 Pcd buffer less than 1`：当前建图会话没有可保存的地图缓存，通常是已经停止过、点云中断或建图未真正开始；
- `507 Load pcd failed`：给出的地址不是该官方 SLAM 能加载的内部地图；NX 本地参考 PCD 不能替代内部地图；
- `509 matching degree is low`：地图可访问，但初始 x/y/yaw、机器人姿态或现场点云不匹配；
- `3202`：RPC 服务/接口链路未就绪，检查导航服务、SDK 环境和内部网卡。

## `stop-map` 成功但 NX 上找不到文件

官方 `address` 可能属于内部控制单元文件系统。`Save pcd successfully` 表示官方服务保存成功，NX 上 `ls` 不到不等于失败。必须随后用相同地址执行 `initialize` 验证。

## 开机定位不断失败

```bash
systemctl is-active g1-navigation-services.service
sudo journalctl -u g1-navigation-services.service -b --no-pager
sudo journalctl -u g1-ramp-v3-bootstrap.service -b --no-pager
```

确认机器人在人工固定起点、站直、朝向正确，地图路径与已验收地址完全一致。不要复制另一台 G1 的：

```text
localization_ready.json
boot_start_adjustment.json
last_localization_pose.json
```

## 定位成功但运动服务未启动

```bash
systemctl status g1-local-assistant.service --no-pager
pgrep -af 'g1_motion_bridge.py|smart_center_node.py'
```

运动桥必须只有一个。若服务失败，先看日志，不要手工 `nohup` 再启动第二份运动桥。

## Wi-Fi 短时中断

G1 的官方 SLAM、定位和路线执行走内部网卡，不应依赖手机到网页的 Wi-Fi。手机断线期间不要重复点击；恢复连接后先刷新状态。网页请求使用任务 ID，服务端应拒绝重复提交，但现场仍应由急停操作员监护。
