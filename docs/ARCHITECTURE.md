# 系统架构

## 控制链路

```text
G1 内置麦克风 rt/audio_msg
        ↓ g1_voice_bridge.py（唤醒门控/ASR文本）
/smart_center/input_text
        ↓ smart_center_node.py + Ros2CommandProcessor（确定性命令优先）
/smart_center/robot_action_request
        ↓ g1_motion_bridge.py
Unitree 官方 SLAM RPC / G1 高层 Loco、Arm API
        ↓
/smart_center/robot_action_result → TTS / 网页状态
```

网页和 `g1-ramp` 也只向同一个 action request 主题发请求，避免绕开安全校验。`g1_global_stop_router.py` 独立监听停止请求，`g1_ramp_odom_cache.py` 将当前开机的里程计写入 `/run/g1-ramp/odom.json`。

## 开机顺序

1. `g1-voice-bridge`：语音桥先启动；
2. `g1-navigation-services`：开启 `lidar_driver` 与 `unitree_slam`；
3. `g1-ramp-odom-cache`：建立可靠位置缓存；
4. `g1-ramp-v3-bootstrap`：固定起点候选循环定位，成功后生成本次开机许可；
5. `g1-local-assistant`：启动智能中控节点与唯一运动桥；
6. 全局停止、网页、导览和可信姿态服务。

## 配置与状态

- 站点级配置：`/etc/default/g1-ramp-stack`
- 应用级配置：`/home/unitree/智能中控/.env`
- 路线点：`data/embodied_lab_panorama_v2/*.json`
- 导览配置：`data/embodied_lab_panorama_v2/tour_config.json`
- 当前开机许可：`data/ramp_platform_v3/localization_ready.json`（不入 Git）
- 网页 Token：`data/web_control/access_token`（不入 Git）
- 里程计缓存：`/run/g1-ramp/odom.json`

## 不包含的内容

通用发布包不包含模型缓存、RAG 文档、聊天数据库、音频、日志、临时扫描、历史备份和 Wi-Fi/SSH 配置。爬坡确定性指令不依赖 RAG；普通开放式问答若需要 Ollama，应由部署者另行安装模型。
