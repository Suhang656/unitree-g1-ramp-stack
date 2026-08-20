import asyncio
import importlib.util

import httpx
import shutil
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from app.config import Settings
from app.schemas import SpeechToTextResponse, VoiceStatus


class VoiceUnavailableError(RuntimeError):
    pass


class VoiceService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.audio_dir.mkdir(parents=True, exist_ok=True)
        self._whisper_model = None

    def status(self) -> VoiceStatus:
        stt_available = (
            self.settings.stt_provider == "faster_whisper"
            and importlib.util.find_spec("faster_whisper") is not None
            and importlib.util.find_spec("requests") is not None
        )
        if self.settings.tts_provider == "piper":
            tts_available = self._piper_configured()
        elif self.settings.tts_provider == "cosyvoice":
            tts_available = self._cosyvoice_available()
        elif self.settings.tts_provider == "pyttsx3":
            tts_available = importlib.util.find_spec("pyttsx3") is not None
        else:
            tts_available = False
        details = []
        if not stt_available:
            details.append(
                "STT unavailable; enable faster_whisper and install requirements-voice.txt"
            )
        if not tts_available:
            details.append(
                "TTS unavailable; start CosyVoice, configure Piper, or install pyttsx3"
            )
        return VoiceStatus(
            stt_provider=self.settings.stt_provider,
            stt_available=stt_available,
            tts_provider=self.settings.tts_provider,
            tts_available=tts_available,
            detail="; ".join(details) or None,
        )

    async def transcribe(self, content: bytes, suffix: str = ".webm") -> SpeechToTextResponse:
        if self.settings.stt_provider != "faster_whisper":
            raise VoiceUnavailableError("STT is disabled or unsupported")
        try:
            return await asyncio.to_thread(self._transcribe_sync, content, suffix)
        except VoiceUnavailableError:
            raise
        except Exception as exc:
            raise VoiceUnavailableError(f"STT failed: {exc}") from exc

    def _transcribe_sync(self, content: bytes, suffix: str) -> SpeechToTextResponse:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise VoiceUnavailableError(
                "faster-whisper is not installed; install requirements-voice.txt"
            ) from exc
        if self._whisper_model is None:
            device = self.settings.whisper_device
            if device == "auto":
                try:
                    import ctranslate2

                    device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
                except Exception:
                    device = "cpu"
            compute_type = "float16" if device == "cuda" else "int8"
            self._whisper_model = WhisperModel(
                self.settings.whisper_model,
                device=device,
                compute_type=compute_type,
            )
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
            temporary.write(content)
            path = Path(temporary.name)
        try:
            segments, info = self._whisper_model.transcribe(
                str(path),
                language="zh",
                vad_filter=True,
                beam_size=5,
                temperature=0,
                condition_on_previous_text=False,
                no_speech_threshold=self.settings.whisper_no_speech_threshold,
                initial_prompt=self.settings.whisper_initial_prompt or None,
                vad_parameters={
                    "threshold": self.settings.whisper_vad_threshold,
                    "min_silence_duration_ms": self.settings.whisper_vad_min_silence_ms,
                    "speech_pad_ms": self.settings.whisper_vad_speech_pad_ms,
                },
            )
            text = "".join(segment.text for segment in segments).strip()
            return SpeechToTextResponse(
                text=text,
                language=getattr(info, "language", None),
                duration_seconds=getattr(info, "duration", None),
            )
        finally:
            path.unlink(missing_ok=True)

    async def synthesize(self, text: str) -> Path:
        if self.settings.tts_provider == "cosyvoice":
            try:
                return await asyncio.to_thread(self._cosyvoice_sync, text)
            except VoiceUnavailableError:
                if self.settings.cosyvoice_fallback_to_piper and self._piper_configured():
                    return await asyncio.to_thread(self._piper_sync, text)
                raise
        if self.settings.tts_provider == "piper":
            return await asyncio.to_thread(self._piper_sync, text)
        if self.settings.tts_provider == "pyttsx3":
            return await asyncio.to_thread(self._pyttsx3_sync, text)
        raise VoiceUnavailableError("TTS is disabled or unsupported")

    def _piper_configured(self) -> bool:
        return bool(
            shutil.which(self.settings.piper_executable)
            and self.settings.piper_model_path
            and self.settings.piper_model_path.exists()
        )

    def _cosyvoice_available(self) -> bool:
        if not self.settings.cosyvoice_base_url:
            return False
        try:
            with httpx.Client(timeout=2, trust_env=False) as client:
                response = client.get(f"{self.settings.cosyvoice_base_url.rstrip('/')}/health")
                return response.is_success
        except httpx.HTTPError:
            return False

    def _cosyvoice_sync(self, text: str) -> Path:
        if not self.settings.cosyvoice_base_url:
            raise VoiceUnavailableError("COSYVOICE_BASE_URL is not configured")
        output = self.settings.audio_dir / f"{uuid4()}.wav"
        try:
            with httpx.Client(
                timeout=self.settings.cosyvoice_timeout_seconds,
                trust_env=False,
            ) as client:
                response = client.post(
                    f"{self.settings.cosyvoice_base_url.rstrip('/')}/tts",
                    json={"text": text},
                )
                response.raise_for_status()
                if not response.content:
                    raise VoiceUnavailableError("CosyVoice returned an empty audio response")
                output.write_bytes(response.content)
        except VoiceUnavailableError:
            output.unlink(missing_ok=True)
            raise
        except (OSError, httpx.HTTPError) as exc:
            output.unlink(missing_ok=True)
            raise VoiceUnavailableError(f"CosyVoice synthesis failed: {exc}") from exc
        return output

    def _piper_sync(self, text: str) -> Path:
        if not self.settings.piper_model_path:
            raise VoiceUnavailableError("PIPER_MODEL_PATH is not configured")
        output = self.settings.audio_dir / f"{uuid4()}.wav"
        try:
            subprocess.run(
                [
                    self.settings.piper_executable,
                    "--model",
                    str(self.settings.piper_model_path),
                    "--output_file",
                    str(output),
                ],
                input=text,
                text=True,
                capture_output=True,
                check=True,
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            output.unlink(missing_ok=True)
            raise VoiceUnavailableError(f"Piper synthesis failed: {exc}") from exc
        return output

    def _pyttsx3_sync(self, text: str) -> Path:
        try:
            import pyttsx3
        except ImportError as exc:
            raise VoiceUnavailableError(
                "pyttsx3 is not installed; install requirements-voice.txt"
            ) from exc
        output = self.settings.audio_dir / f"{uuid4()}.wav"
        engine = pyttsx3.init()
        engine.save_to_file(text, str(output))
        engine.runAndWait()
        if not output.exists():
            raise VoiceUnavailableError("pyttsx3 did not create an audio file")
        return output
