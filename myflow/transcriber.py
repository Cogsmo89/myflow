from __future__ import annotations

import io
import wave
import numpy as np

from .config import Config


class TranscribeError(RuntimeError):
    pass


_local_model = None
_local_model_name = None


def _to_wav_bytes(audio: np.ndarray, sr: int) -> bytes:
    pcm16 = np.clip(audio, -1.0, 1.0)
    pcm16 = (pcm16 * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm16.tobytes())
    return buf.getvalue()


def _transcribe_openai(audio: np.ndarray, sr: int, cfg: Config) -> str:
    if not cfg.openai_api_key:
        raise TranscribeError("openai_api_key not set in config")
    try:
        from openai import OpenAI
    except ImportError as e:
        raise TranscribeError("openai package not installed") from e

    client = OpenAI(api_key=cfg.openai_api_key, max_retries=3, timeout=30.0)
    wav = _to_wav_bytes(audio, sr)
    file_tuple = ("audio.wav", wav, "audio/wav")
    try:
        resp = client.audio.transcriptions.create(
            model="whisper-1",
            file=file_tuple,
        )
    except Exception as e:
        raise TranscribeError(f"OpenAI transcription failed: {e}") from e
    return (resp.text or "").strip()


def _transcribe_local(audio: np.ndarray, sr: int, cfg: Config) -> str:
    global _local_model, _local_model_name
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise TranscribeError("faster-whisper not installed") from e

    if _local_model is None or _local_model_name != cfg.local_whisper_model:
        # CPU is the safe default; CUDA needs cuBLAS DLLs that aren't bundled.
        _local_model = WhisperModel(
            cfg.local_whisper_model, device="cpu", compute_type="int8"
        )
        _local_model_name = cfg.local_whisper_model

    if sr != 16000:
        raise TranscribeError(f"local engine expects 16k audio, got {sr}")

    try:
        lang = (cfg.language or "").strip() or None
        segments, _info = _local_model.transcribe(
            audio,
            language=lang,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
            condition_on_previous_text=False,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()
    except Exception as e:
        raise TranscribeError(f"Local transcription failed: {e}") from e


def transcribe(audio: np.ndarray, sr: int, cfg: Config) -> str:
    engine = (cfg.stt_engine or "openai").lower()
    if engine == "openai":
        return _transcribe_openai(audio, sr, cfg)
    if engine == "local":
        return _transcribe_local(audio, sr, cfg)
    raise TranscribeError(f"Unknown stt_engine: {cfg.stt_engine}")
