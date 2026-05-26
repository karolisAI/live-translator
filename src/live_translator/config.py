from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .errors import MissingDependency


@dataclass(frozen=True)
class AudioSettings:
    sample_rate: int = 16000
    chunk_seconds: float = 3.0
    input_device: str | None = None
    output_device: str | None = None
    peer_input_device: str | None = None
    peer_output_device: str | None = None
    input_gain: float = 1.0
    playback_gain: float = 1.0


@dataclass(frozen=True)
class AsrSettings:
    engine: str = "faster-whisper"
    model: str = "base"
    device: str = "auto"
    compute_type: str = "auto"
    source_language: str | None = "en"
    beam_size: int = 1
    condition_on_previous_text: bool = False
    no_speech_threshold: float = 0.90
    log_prob_threshold: float = -1.8
    compression_ratio_threshold: float = 2.4
    min_segment_chars: int = 2


@dataclass(frozen=True)
class TranslationSettings:
    engine: str = "identity"
    source_language: str = "en"
    target_language: str = "de"


@dataclass(frozen=True)
class TtsSettings:
    engine: str = "none"
    voice: str | None = None
    model_path: str | None = None
    piper_exe: str = "piper"
    speaker: str | None = None


@dataclass(frozen=True)
class ChunkingSettings:
    mode: str = "fixed"
    frame_ms: int = 30
    min_speech_ms: int = 250
    min_segment_seconds: float = 1.2
    silence_ms: int = 650
    max_seconds: float = 6.0
    pre_roll_ms: int = 180
    rms_threshold: float = 0.012
    peak_threshold: float = 0.035
    min_active_ratio: float = 0.08
    noise_multiplier: float = 3.0


@dataclass(frozen=True)
class AppConfig:
    audio: AudioSettings = AudioSettings()
    asr: AsrSettings = AsrSettings()
    translation: TranslationSettings = TranslationSettings()
    tts: TtsSettings = TtsSettings()
    chunking: ChunkingSettings = ChunkingSettings()


def load_config(path: str | Path | None) -> AppConfig:
    if path is None:
        return AppConfig()

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    try:
        import yaml
    except ImportError as exc:
        raise MissingDependency("Missing dependency 'PyYAML'. Install dependencies with: python -m pip install -e .") from exc

    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    if not isinstance(raw, dict):
        raise ValueError(f"Config root must be a mapping: {config_path}")

    return AppConfig(
        audio=_load_audio(raw.get("audio") or {}),
        asr=_load_asr(raw.get("asr") or {}),
        translation=_load_translation(raw.get("translation") or {}),
        tts=_load_tts(raw.get("tts") or {}),
        chunking=_load_chunking(raw.get("chunking") or raw.get("vad") or {}),
    )


def apply_cli_overrides(
    config: AppConfig,
    *,
    seconds: float | None = None,
    input_device: str | None = None,
    output_device: str | None = None,
    input_gain: float | None = None,
    model: str | None = None,
    source_language: str | None = None,
    target_language: str | None = None,
    translation_engine: str | None = None,
    tts_engine: str | None = None,
    tts_voice: str | None = None,
    tts_model_path: str | None = None,
    piper_exe: str | None = None,
    no_speech_threshold: float | None = None,
    log_prob_threshold: float | None = None,
    chunker_mode: str | None = None,
    vad_threshold: float | None = None,
    peak_threshold: float | None = None,
    min_active_ratio: float | None = None,
    min_segment_seconds: float | None = None,
    silence_ms: int | None = None,
    max_seconds: float | None = None,
) -> AppConfig:
    audio = config.audio
    asr = config.asr
    translation = config.translation
    tts = config.tts
    chunking = config.chunking

    if seconds is not None:
        audio = replace(audio, chunk_seconds=seconds)
    if input_device is not None:
        audio = replace(audio, input_device=input_device)
    if output_device is not None:
        audio = replace(audio, output_device=output_device)
    if input_gain is not None:
        audio = replace(audio, input_gain=input_gain)
    if model is not None:
        asr = replace(asr, model=model)
    if source_language is not None:
        asr = replace(asr, source_language=None if source_language == "auto" else source_language)
        translation = replace(translation, source_language=source_language)
    if target_language is not None:
        translation = replace(translation, target_language=target_language)
    if translation_engine is not None:
        translation = replace(translation, engine=translation_engine)
    if tts_engine is not None:
        tts = replace(tts, engine=tts_engine)
    if tts_voice is not None:
        tts = replace(tts, voice=tts_voice)
    if tts_model_path is not None:
        tts = replace(tts, model_path=tts_model_path)
    if piper_exe is not None:
        tts = replace(tts, piper_exe=piper_exe)
    if no_speech_threshold is not None:
        asr = replace(asr, no_speech_threshold=no_speech_threshold)
    if log_prob_threshold is not None:
        asr = replace(asr, log_prob_threshold=log_prob_threshold)
    if chunker_mode is not None:
        chunking = replace(chunking, mode=chunker_mode)
    if vad_threshold is not None:
        chunking = replace(chunking, rms_threshold=vad_threshold)
    if peak_threshold is not None:
        chunking = replace(chunking, peak_threshold=peak_threshold)
    if min_active_ratio is not None:
        chunking = replace(chunking, min_active_ratio=min_active_ratio)
    if min_segment_seconds is not None:
        chunking = replace(chunking, min_segment_seconds=min_segment_seconds)
    if silence_ms is not None:
        chunking = replace(chunking, silence_ms=silence_ms)
    if max_seconds is not None:
        chunking = replace(chunking, max_seconds=max_seconds)

    return AppConfig(audio=audio, asr=asr, translation=translation, tts=tts, chunking=chunking)


def _load_audio(raw: dict[str, Any]) -> AudioSettings:
    return AudioSettings(
        sample_rate=_int(raw, "sample_rate", 16000),
        chunk_seconds=_float(raw, "chunk_seconds", _float(raw, "window_seconds", 3.0)),
        input_device=_str_or_none(raw, "input_device"),
        output_device=_str_or_none(raw, "output_device"),
        peer_input_device=_str_or_none(raw, "peer_input_device"),
        peer_output_device=_str_or_none(raw, "peer_output_device"),
        input_gain=_float(raw, "input_gain", 1.0),
        playback_gain=_float(raw, "playback_gain", 1.0),
    )


def _load_asr(raw: dict[str, Any]) -> AsrSettings:
    return AsrSettings(
        engine=_str(raw, "engine", "faster-whisper"),
        model=_str(raw, "model", "base"),
        device=_str(raw, "device", "auto"),
        compute_type=_str(raw, "compute_type", "auto"),
        source_language=_str_or_none(raw, "source_language", "en"),
        beam_size=_int(raw, "beam_size", 1),
        condition_on_previous_text=_bool(raw, "condition_on_previous_text", False),
        no_speech_threshold=_float(raw, "no_speech_threshold", 0.90),
        log_prob_threshold=_float_any(raw, "log_prob_threshold", -1.8),
        compression_ratio_threshold=_float(raw, "compression_ratio_threshold", 2.4),
        min_segment_chars=_int(raw, "min_segment_chars", 2),
    )


def _load_translation(raw: dict[str, Any]) -> TranslationSettings:
    return TranslationSettings(
        engine=_str(raw, "engine", "identity"),
        source_language=_str(raw, "source_language", "en"),
        target_language=_str(raw, "target_language", "de"),
    )


def _load_tts(raw: dict[str, Any]) -> TtsSettings:
    return TtsSettings(
        engine=_str(raw, "engine", "none"),
        voice=_str_or_none(raw, "voice"),
        model_path=_str_or_none(raw, "model_path"),
        piper_exe=_str(raw, "piper_exe", "piper"),
        speaker=_str_or_none(raw, "speaker"),
    )


def _load_chunking(raw: dict[str, Any]) -> ChunkingSettings:
    return ChunkingSettings(
        mode=_str(raw, "mode", "fixed"),
        frame_ms=_int(raw, "frame_ms", 30),
        min_speech_ms=_int(raw, "min_speech_ms", 250),
        min_segment_seconds=_float(raw, "min_segment_seconds", 1.2),
        silence_ms=_int(raw, "silence_ms", _int(raw, "silence_commit_ms", 650)),
        max_seconds=_float(raw, "max_seconds", 6.0),
        pre_roll_ms=_int(raw, "pre_roll_ms", 180),
        rms_threshold=_float(raw, "rms_threshold", 0.012),
        peak_threshold=_float(raw, "peak_threshold", 0.035),
        min_active_ratio=_float(raw, "min_active_ratio", 0.08),
        noise_multiplier=_float(raw, "noise_multiplier", 3.0),
    )


def _str(raw: dict[str, Any], key: str, default: str) -> str:
    value = raw.get(key, default)
    return str(value).strip()


def _str_or_none(raw: dict[str, Any], key: str, default: str | None = None) -> str | None:
    value = raw.get(key, default)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bool(raw: dict[str, Any], key: str, default: bool) -> bool:
    value = raw.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"{key} must be a boolean")


def _int(raw: dict[str, Any], key: str, default: int) -> int:
    value = raw.get(key, default)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{key} must be positive")
    return parsed


def _float(raw: dict[str, Any], key: str, default: float) -> float:
    value = raw.get(key, default)
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc
    if parsed <= 0:
        raise ValueError(f"{key} must be positive")
    return parsed


def _float_any(raw: dict[str, Any], key: str, default: float) -> float:
    value = raw.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc
