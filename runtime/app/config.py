from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ollama_base_url: str = Field(default="http://127.0.0.1:11434")
    rag_ollama_base_url: str | None = None
    ollama_model: str = Field(default="qwen3:4b")
    ollama_complex_model: str = "qwen3:4b-q4_K_M"
    ollama_timeout_seconds: float = Field(default=120, gt=0)
    ollama_keep_alive: str = "30m"
    # Qwen3 默认可输出长思考过程；中控对话默认关闭以减少首字延迟。
    ollama_think: bool = False
    database_path: Path = Field(default=Path("data/smart_center.db"))
    max_history_messages: int = Field(default=40, ge=2, le=200)
    upload_dir: Path = Field(default=Path("data/uploads"))
    rag_enabled: bool = True
    rag_embedding_model: str = "qwen3-embedding:0.6b"
    rag_top_k: int = Field(default=5, ge=1, le=20)
    rag_chunk_size: int = Field(default=800, ge=200, le=4000)
    rag_chunk_overlap: int = Field(default=120, ge=0, le=1000)
    rag_candidate_k: int = Field(default=30, ge=5, le=100)
    rag_rrf_k: int = Field(default=60, ge=1, le=200)
    rag_bm25_k1: float = Field(default=1.5, gt=0, le=3)
    rag_bm25_b: float = Field(default=0.75, ge=0, le=1)
    rag_reranker_enabled: bool = True
    rag_reranker_model: str = "Qwen/Qwen3-Reranker-0.6B"
    rag_reranker_device: str = "auto"
    rag_reranker_max_length: int = Field(default=1024, ge=256, le=8192)
    rag_reranker_batch_size: int = Field(default=4, ge=1, le=32)
    agent_max_steps: int = Field(default=4, ge=1, le=10)
    device_bridge_url: str | None = None
    device_bridge_token: str | None = None
    device_simulation: bool = True
    # 真实设备还需显式开启；仅把 DEVICE_SIMULATION 设为 false 不足以运动。
    device_real_actions_enabled: bool = False
    # G1 只读状态桥接器写出的 JSON 文件。配置后仍保持动作仿真安全策略。
    g1_status_file: Path | None = None
    ros2_enabled: bool = False
    ros2_node_name: str = 'smart_center'
    ros2_session_title: str = 'ROS2 智能中控会话'
    # 正常启动脚本会用每台机器的 robot_id 覆盖这些占位值。
    ros2_input_topic: str = '/unconfigured/smart_center/input_text'
    ros2_response_topic: str = '/unconfigured/smart_center/response_text'
    ros2_action_request_topic: str = '/unconfigured/smart_center/robot_action_request'
    ros2_action_result_topic: str = '/unconfigured/smart_center/robot_action_result'
    ros2_robot_status_topic: str = '/unconfigured/smart_center/robot_status'
    ros2_status_topic: str = '/unconfigured/smart_center/status'
    ros2_emergency_stop_topic: str = '/unconfigured/smart_center/emergency_stop'
    stt_provider: str = "disabled"
    whisper_model: str = "small"
    whisper_device: str = "auto"
    whisper_vad_threshold: float = Field(default=0.30, ge=0.05, le=0.95)
    whisper_vad_min_silence_ms: int = Field(default=350, ge=100, le=5000)
    whisper_vad_speech_pad_ms: int = Field(default=500, ge=0, le=2000)
    whisper_no_speech_threshold: float = Field(default=0.80, ge=0.05, le=1.0)
    whisper_initial_prompt: str = "智能中控，机器人，机械臂，摄像头，设备控制，知识库。"
    tts_provider: str = "disabled"
    piper_executable: str = "piper"
    piper_model_path: Path | None = None
    # CosyVoice 运行在独立 Python 3.10 环境，通过本机 HTTP 服务调用。
    cosyvoice_base_url: str | None = None
    cosyvoice_timeout_seconds: float = Field(default=180, gt=0, le=600)
    cosyvoice_fallback_to_piper: bool = True
    audio_dir: Path = Field(default=Path("data/audio"))
    system_prompt: str = Field(
        default=(
            "你是智能中控系统的中枢助手。请使用清晰、准确、自然的中文回答。"
            "你的回答会被直接交给中文语音合成系统朗读，因此只能输出适合口语朗读的纯文本。"
            "禁止输出 Markdown、项目符号、编号、标题符号、反引号、代码块、英文引号、中文引号、"
            "括号、方括号、花括号、星号、井号、下划线、斜杠、反斜杠、网址、表情符号、颜文字、"
            "HTML、JSON、XML 或任何特殊格式标记。"
            "只使用汉字、阿拉伯数字，以及中文句号、逗号、问号、感叹号和顿号。"
            "需要列举时改用完整的自然语言分句，不要使用列表。"
            "不得声称已经执行未实际调用的设备操作；涉及机器人动作时，"
            "必须等待受控工具返回真实结果。知识库来源由系统单独保存，不要在回答中添加引用标记。"
        )
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
