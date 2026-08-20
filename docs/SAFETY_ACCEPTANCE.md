# 安全部署与验收清单

## 静态检查

- [ ] 目标机 `machine-id` 已记录，不会与源机混淆；
- [ ] SDK2、ROS 2、Unitree 消息包、CycloneDDS 兼容库存在；
- [ ] 内部网卡和 `192.168.123.161` 连通；
- [ ] `/etc/default/g1-ramp-stack` 的网卡、地图和起点正确；
- [ ] 官方 `initialize` 已成功，`G1_INTERNAL_MAP_VERIFIED=1` 由操作员设置；
- [ ] 路线点全部属于当前地图；
- [ ] 网页 Token 未提交到 Git、未在公开聊天中泄露。

## 开机检查

- [ ] `g1-ramp status` 显示定位成功、地图正确、boot_id 匹配；
- [ ] `/unitree/slam_relocation/odom` 持续发布且静止波动可接受；
- [ ] `g1_motion_bridge.py` 只有一个进程；
- [ ] 语音桥、全局停止、网页控制器在线；
- [ ] 网页断网/重连不会重复提交旧动作；
- [ ] 机器人不在起点时，固定起点定位不会被错误接受。

## 运动前条件

- [ ] 急停操作员在场；
- [ ] 坡道两侧和终点有防跌落保护；
- [ ] 路线净空，无人员和移动障碍；
- [ ] 电量、关节温度和机身状态正常；
- [ ] 先验证停止链路，再验证任何前进动作；
- [ ] 首次仅执行短距离平地动作。

## 路线验收

- [ ] 直线前进逐段通过；
- [ ] 直线返回逐段通过；
- [ ] 转弯前进每个拐点朝向通过；
- [ ] 转弯返回反序通过；
- [ ] 到达判定不会导致大幅停顿或越点；
- [ ] 导览每次“继续下一站”均要求网页确认；
- [ ] guide_1 演示结束后能回到 guide_1 待命；
- [ ] 记录官方 goto 前后 FSM，若出现 501，按目标固件风险评估处理。

## 失败时

先执行遥控急停或 `g1-ramp stop`，再停服务：

```bash
sudo systemctl stop g1-local-assistant.service g1-tour-executor.service g1-web-control.service
```

保存日志但不要在定位不可信时继续重试运动：

```bash
sudo journalctl -u g1-ramp-v3-bootstrap.service -b --no-pager
sudo journalctl -u g1-local-assistant.service -b --no-pager
```
