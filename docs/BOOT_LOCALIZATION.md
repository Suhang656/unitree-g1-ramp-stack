# 开机固定点定位与自调整

## 功能边界

该功能适用于：G1 每次开机都放在同一人工标定区域，站直，并大致朝向同一方向。它不是任意地点全局搜索，也不会让机器人移动寻找位置。

每台 G1 只使用本机的：

- 官方内部 SLAM 地图；
- `/etc/default/g1-ramp-stack` 中的人工固定起点；
- Mid360 点云、IMU 和官方重定位里程计；
- 本机上一次成功开机定位产生的微调记录。

不需要、也不允许连接源 G1。不同 G1 的开机微调记录不能互相复制。

## 工作流程

1. 等待 Mid360 点云和 IMU；
2. 关闭残留的官方 SLAM 会话；
3. 若存在同一地图的本机微调记录，优先尝试该姿态；
4. 尝试人工固定起点；
5. 在人工起点安全半径内，按机器人朝向坐标生成位置和朝向候选；
6. 官方 `initialize` 接受候选后，采集稳定的重定位里程计；
7. 同时通过静止波动、距人工起点距离和朝向误差检查，才生成本次开机许可；
8. 把成功姿态写入本机 `boot_start_adjustment.json`，供下次优先尝试；
9. 播报“全局定位成功”，运动服务随后才允许启动。

人工基准点不会被自动改写。换地图后，旧微调记录因地图路径不匹配会被自动忽略。

## 配置

编辑 `/etc/default/g1-ramp-stack`：

```text
G1_FIXED_START_X=0.0
G1_FIXED_START_Y=0.0
G1_FIXED_START_YAW=0.0
G1_BOOT_AUTO_ADJUST=1
G1_BOOT_SEARCH_RADIUS_M=0.50
G1_BOOT_POSITION_STEP_M=0.12
G1_BOOT_YAW_WINDOW_DEG=15
G1_BOOT_YAW_STEP_DEG=5
G1_BOOT_MAX_CANDIDATES=36
G1_BOOT_ACCEPT_MAX_POSITION_ERROR_M=0.50
G1_BOOT_ACCEPT_MAX_YAW_ERROR_DEG=35
```

- `SEARCH_RADIUS` 是候选相对人工起点的最大范围；
- `POSITION_STEP` 是周边候选间距；
- `YAW_WINDOW/YAW_STEP` 控制面向固定方向的小幅搜索；
- `MAX_CANDIDATES` 限制每轮耗时；
- `ACCEPT_MAX_*` 是成功结果的最终安全门，不能大于现场允许偏差。

## 状态文件

```text
data/ramp_platform_v3/localization_ready.json
data/ramp_platform_v3/boot_start_adjustment.json
```

前者绑定当前 `boot_id`，重启后失效；后者是本机、当前地图的学习结果，可跨重启使用，但不应复制到另一台 G1。

查看：

```bash
g1-ramp status
sudo journalctl -u g1-ramp-v3-bootstrap.service -b --no-pager
/usr/bin/python3 -m json.tool \
  /home/unitree/智能中控/data/ramp_platform_v3/boot_start_adjustment.json
```

如需废弃学习结果并从人工基准重新开始（不影响地图和路线）：

```bash
sudo systemctl stop g1-ramp-v3-bootstrap.service
rm -f /home/unitree/智能中控/data/ramp_platform_v3/boot_start_adjustment.json
sudo systemctl start g1-ramp-v3-bootstrap.service
```

## 不应通过的情况

- G1 没有站直、仍在晃动；
- G1 不在固定起点安全范围；
- 朝向与人工基准相差过大；
- 地图路径改变但尚未重新验收；
- 官方重定位里程计中断或波动超限。

定位失败时服务会短周期重试，但不会启动运动桥。不要为了“快速成功”扩大阈值来接受错误地点。
