# 现场基线只读审计结论

发布包整理自一套已经现场运行的 G1 项目。审计期间没有修改服务、没有发布 ROS 运动请求、没有调用机器人运动 API。设备 IP、机器身份和网络凭据不属于通用项目，也不在仓库中公开。

## 纳入通用项目

- `app/` 中的确定性中文动作解析和 ROS 2 处理；
- 语音、运动、停止和导览 ROS 2 节点；
- 官方 SLAM CLI、导航服务启停、定位验证、里程计和标点脚本；
- Token 网页控制器及其静态页面；
- 当前两条坡道路线和三个导览点配置；
- 必需的纯 Python CycloneDDS 兼容模块；
- 经整理的 systemd 单元、CLI、安装和验收脚本。

## 未纳入

- `data/smart_center.db`、上传文件、音频、模型缓存、日志和临时采集；
- 网页访问 Token、Wi-Fi 密码、SSH 密钥、开机定位许可；
- 大体积且与爬坡无关的 ASR、RAG、Torch/Transformers vendor 依赖；
- 大量 `.before_*`、备份目录和失效实验脚本；
- 基线机器 systemd 的禁用/备份 drop-in。

## 地图结论

NX 参考 PCD 的 SHA-256：

```text
ca085ee9796feb252521228b1e3fb375985cee87c1a2a2fc46116cecfa8c05c3
```

现场配置使用 `/home/unitree/g1_internal_panorama_v2.pcd`，但该文件在 NX 文件系统不可见，官方 `initialize` 却可以接受它。这说明该地址由官方 SLAM 服务解释，可能对应内部控制单元。普通 NX PCD 曾返回 `errorCode 507 Load pcd failed`，因此发布包不会把参考 PCD冒充为可直接导航的官方地图。

## 固件行为

项目代码没有自动请求“越障模式”的显式入口；实际测试显示官方 `goto` 会使某些 G1 固件进入 FSM 501，且切回 802 会被官方导航覆盖。这属于官方导航服务行为，需要在目标机验收中记录。
