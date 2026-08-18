from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from .errors import MissingDependency


_SUPPORTED_ASR_ENGINES = ("parakeet",)

_DEFAULT_ASR_MODEL = "nemo-parakeet-tdt-0.6b-v3"


@dataclass(frozen=True)
class AudioSettings:
    sample_rate: int = 16000
    chunk_seconds: float = 3.0
    input_device: str | None = None
    output_device: str | None = None
    peer_input_device: str | None = None
    input_gain: float = 1.0
    playback_gain: float = 1.0


@dataclass(frozen=True)
class AsrSettings:
    engine: str = "parakeet"
    model: str = _DEFAULT_ASR_MODEL
    device: str = "cpu"
    compute_type: str = "int8"
    cpu_threads: int = 0
    source_language: str | None = "en"
    log_prob_threshold: float = -1.3
    flag_log_prob_threshold: float | None = None
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
    length_scale: float | None = None


@dataclass(frozen=True)
class ChunkingSettings:
    mode: str = "fixed"
    frame_ms: int = 30
    min_speech_ms: int = 180
    min_segment_seconds: float = 0.8
    rolling_window_seconds: float = 2.4
    silence_ms: int = 450
    max_seconds: float = 5.0
    pre_roll_ms: int = 200
    rms_threshold: float = 0.008
    peak_threshold: float = 0.025
    min_active_ratio: float = 0.06
    noise_multiplier: float = 3.0


@dataclass(frozen=True)
class RealtimeSettings:
    recognition_queue_size: int = 2
    playback_queue_size: int = 1


@dataclass(frozen=True)
class AppConfig:
    audio: AudioSettings = AudioSettings()
    asr: AsrSettings = AsrSettings()
    translation: TranslationSettings = TranslationSettings()
    tts: TtsSettings = TtsSettings()
    chunking: ChunkingSettings = ChunkingSettings()
    realtime: RealtimeSettings = RealtimeSettings()


_SECTION_KEYS: dict[str, set[str]] = {
    "audio": {
        "sample_rate",
        "chunk_seconds",
        "window_seconds",
        "input_device",
        "output_device",
        "peer_input_device",
        "input_gain",
        "playback_gain",
    },
    "asr": {
        "engine",
        "model",
        "device",
        "compute_type",
        "cpu_threads",
        "source_language",
        "log_prob_threshold",
        "flag_log_prob_threshold",
        "compression_ratio_threshold",
        "min_segment_chars",
    },
    "translation": {"engine", "source_language", "target_language"},
    "tts": {"engine", "voice", "model_path", "piper_exe", "speaker", "length_scale"},
    "chunking": {
        "mode",
        "frame_ms",
        "min_speech_ms",
        "min_segment_seconds",
        "rolling_window_seconds",
        "silence_ms",
        "silence_commit_ms",
        "max_seconds",
        "pre_roll_ms",
        "rms_threshold",
        "peak_threshold",
        "min_active_ratio",
        "noise_multiplier",
    },
    "realtime": {"recognition_queue_size", "playback_queue_size"},
}


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

    _validate_raw_config(raw)
    config = AppConfig(
        audio=_load_audio(raw.get("audio") or {}),
        asr=_load_asr(raw.get("asr") or {}),
        translation=_load_translation(raw.get("translation") or {}),
        tts=_load_tts(raw.get("tts") or {}),
        chunking=_load_chunking(raw.get("chunking") or raw.get("vad") or {}),
        realtime=_load_realtime(raw.get("realtime") or {}),
    )
    validate_config(config)
    return config


def apply_cli_overrides(
    config: AppConfig,
    *,
    seconds: float | None = None,
    input_device: str | None = None,
    output_device: str | None = None,
    input_gain: float | None = None,
    asr_engine: str | None = None,
    model: str | None = None,
    source_language: str | None = None,
    target_language: str | None = None,
    translation_engine: str | None = None,
    tts_engine: str | None = None,
    tts_voice: str | None = None,
    tts_model_path: str | None = None,
    piper_exe: str | None = None,
    tts_length_scale: float | None = None,
    log_prob_threshold: float | None = None,
    flag_log_prob_threshold: float | None = None,
    chunker_mode: str | None = None,
    vad_threshold: float | None = None,
    peak_threshold: float | None = None,
    min_active_ratio: float | None = None,
    min_segment_seconds: float | None = None,
    silence_ms: int | None = None,
    max_seconds: float | None = None,
    rolling_window_seconds: float | None = None,
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
    if asr_engine is not None:
        asr = replace(asr, engine=asr_engine)
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
    if tts_length_scale is not None:
        tts = replace(tts, length_scale=tts_length_scale)
    if log_prob_threshold is not None:
        asr = replace(asr, log_prob_threshold=log_prob_threshold)
    if flag_log_prob_threshold is not None:
        asr = replace(asr, flag_log_prob_threshold=flag_log_prob_threshold)
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
    if rolling_window_seconds is not None:
        chunking = replace(chunking, rolling_window_seconds=rolling_window_seconds)

    updated = AppConfig(
        audio=audio,
        asr=asr,
        translation=translation,
        tts=tts,
        chunking=chunking,
        realtime=config.realtime,
    )
    validate_config(updated)
    return updated


def validate_config(config: AppConfig) -> None:
    if config.audio.sample_rate != 16000:
        raise ValueError("audio.sample_rate must be 16000")
    if config.audio.chunk_seconds <= 0.0:
        raise ValueError("audio.chunk_seconds must be positive")
    if config.audio.input_gain <= 0.0:
        raise ValueError("audio.input_gain must be positive")
    if config.audio.playback_gain <= 0.0:
        raise ValueError("audio.playback_gain must be positive")
    if config.asr.engine.lower() not in _SUPPORTED_ASR_ENGINES:
        raise ValueError(f"Unsupported ASR engine: {config.asr.engine}")
    if not config.asr.model:
        raise ValueError("asr.model must not be empty")
    if config.asr.cpu_threads < 0:
        raise ValueError("asr.cpu_threads must not be negative")
    if config.asr.compression_ratio_threshold <= 0.0:
        raise ValueError("asr.compression_ratio_threshold must be positive")
    if (
        config.asr.flag_log_prob_threshold is not None
        and config.asr.flag_log_prob_threshold <= config.asr.log_prob_threshold
    ):
        raise ValueError(
            "asr.flag_log_prob_threshold must be greater than asr.log_prob_threshold "
            "(otherwise everything it would flag is already rejected first)"
        )
    if config.asr.min_segment_chars <= 0:
        raise ValueError("asr.min_segment_chars must be positive")

    if not config.translation.source_language:
        raise ValueError("translation.source_language must not be empty")
    if not config.translation.target_language:
        raise ValueError("translation.target_language must not be empty")

    translation_engine = config.translation.engine.lower()
    if translation_engine not in {"none", "identity", "off", "argos"}:
        raise ValueError(f"Unsupported translation engine: {config.translation.engine}")
    if translation_engine == "argos":
        if config.translation.source_language.lower() == "auto":
            raise ValueError(
                "Argos translation requires a fixed source language. Use an EN-DE or DE-EN profile."
            )
        if config.asr.source_language is None:
            raise ValueError("Argos translation requires asr.source_language to be set")
        if config.asr.source_language.lower() != config.translation.source_language.lower():
            raise ValueError("asr.source_language must match translation.source_language")
        if config.translation.source_language.lower() == config.translation.target_language.lower():
            raise ValueError("translation source and target languages must be different")

    tts_engine = config.tts.engine.lower()
    if tts_engine not in {"none", "off", "pyttsx3", "sapi", "piper", "piper-cli"}:
        raise ValueError(f"Unsupported TTS engine: {config.tts.engine}")
    if tts_engine in {"piper", "piper-cli"} and not config.tts.model_path:
        raise ValueError("tts.model_path is required when tts.engine is 'piper'")
    if config.tts.length_scale is not None and config.tts.length_scale <= 0.0:
        raise ValueError("tts.length_scale must be positive")

    if config.chunking.mode.lower() not in {"fixed", "vad", "rolling"}:
        raise ValueError("chunking.mode must be 'fixed', 'vad', or 'rolling'")
    if config.chunking.frame_ms <= 0:
        raise ValueError("chunking.frame_ms must be positive")
    if config.chunking.min_speech_ms <= 0:
        raise ValueError("chunking.min_speech_ms must be positive")
    if config.chunking.min_segment_seconds <= 0.0:
        raise ValueError("chunking.min_segment_seconds must be positive")
    if config.chunking.rolling_window_seconds <= 0.0:
        raise ValueError("chunking.rolling_window_seconds must be positive")
    if config.chunking.silence_ms <= 0:
        raise ValueError("chunking.silence_ms must be positive")
    if config.chunking.max_seconds <= 0.0:
        raise ValueError("chunking.max_seconds must be positive")
    if config.chunking.pre_roll_ms < 0:
        raise ValueError("chunking.pre_roll_ms must not be negative")
    if config.chunking.rms_threshold <= 0.0:
        raise ValueError("chunking.rms_threshold must be positive")
    if config.chunking.peak_threshold <= 0.0:
        raise ValueError("chunking.peak_threshold must be positive")
    if not 0.0 < config.chunking.min_active_ratio <= 1.0:
        raise ValueError("chunking.min_active_ratio must be greater than 0 and at most 1")
    if config.chunking.noise_multiplier <= 0.0:
        raise ValueError("chunking.noise_multiplier must be positive")
    if config.chunking.min_segment_seconds > config.chunking.max_seconds:
        raise ValueError("chunking.min_segment_seconds must not exceed chunking.max_seconds")
    if config.chunking.rolling_window_seconds > config.chunking.max_seconds:
        raise ValueError("chunking.rolling_window_seconds must not exceed chunking.max_seconds")
    if config.realtime.recognition_queue_size <= 0:
        raise ValueError("realtime.recognition_queue_size must be positive")
    if config.realtime.playback_queue_size <= 0:
        raise ValueError("realtime.playback_queue_size must be positive")


def _validate_raw_config(raw: dict[str, Any]) -> None:
    allowed_sections = set(_SECTION_KEYS) | {"vad"}
    unknown_sections = sorted(set(raw) - allowed_sections)
    if unknown_sections:
        raise ValueError(f"Unknown config section(s): {', '.join(unknown_sections)}")
    if "chunking" in raw and "vad" in raw:
        raise ValueError("Use 'chunking', not both 'chunking' and the legacy 'vad' section")

    for section_name, section_value in raw.items():
        if not isinstance(section_value, dict):
            raise ValueError(f"Config section '{section_name}' must be a mapping")
        canonical_name = "chunking" if section_name == "vad" else section_name
        unknown_keys = sorted(set(section_value) - _SECTION_KEYS[canonical_name])
        if unknown_keys:
            formatted = ", ".join(f"{section_name}.{key}" for key in unknown_keys)
            raise ValueError(f"Unknown config setting(s): {formatted}")


def _load_audio(raw: dict[str, Any]) -> AudioSettings:
    return AudioSettings(
        sample_rate=_int(raw, "sample_rate", 16000),
        chunk_seconds=_float(raw, "chunk_seconds", _float(raw, "window_seconds", 3.0)),
        input_device=_str_or_none(raw, "input_device"),
        output_device=_str_or_none(raw, "output_device"),
        peer_input_device=_str_or_none(raw, "peer_input_device"),
        input_gain=_float(raw, "input_gain", 1.0),
        playback_gain=_float(raw, "playback_gain", 1.0),
    )


def _load_asr(raw: dict[str, Any]) -> AsrSettings:
    return AsrSettings(
        engine=_str(raw, "engine", "parakeet"),
        model=_str(raw, "model", _DEFAULT_ASR_MODEL),
        device=_str(raw, "device", "cpu"),
        compute_type=_str(raw, "compute_type", "int8"),
        cpu_threads=_nonnegative_int(raw, "cpu_threads", 0),
        source_language=_str_or_none(raw, "source_language", "en"),
        log_prob_threshold=_float_any(raw, "log_prob_threshold", -1.3),
        flag_log_prob_threshold=_float_or_none(raw, "flag_log_prob_threshold"),
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
        length_scale=_float_or_none(raw, "length_scale"),
    )


def _load_chunking(raw: dict[str, Any]) -> ChunkingSettings:
    return ChunkingSettings(
        mode=_str(raw, "mode", "fixed"),
        frame_ms=_int(raw, "frame_ms", 30),
        min_speech_ms=_int(raw, "min_speech_ms", 180),
        min_segment_seconds=_float(raw, "min_segment_seconds", 0.8),
        rolling_window_seconds=_float(raw, "rolling_window_seconds", 2.4),
        silence_ms=_int(raw, "silence_ms", _int(raw, "silence_commit_ms", 450)),
        max_seconds=_float(raw, "max_seconds", 5.0),
        pre_roll_ms=_int(raw, "pre_roll_ms", 200),
        rms_threshold=_float(raw, "rms_threshold", 0.008),
        peak_threshold=_float(raw, "peak_threshold", 0.025),
        min_active_ratio=_float(raw, "min_active_ratio", 0.06),
        noise_multiplier=_float(raw, "noise_multiplier", 3.0),
    )


def _load_realtime(raw: dict[str, Any]) -> RealtimeSettings:
    return RealtimeSettings(
        recognition_queue_size=_int(raw, "recognition_queue_size", 2),
        playback_queue_size=_int(raw, "playback_queue_size", 1),
    )


def _str(raw: dict[str, Any], key: str, default: str) -> str:
    value = raw.get(key, default)
    if value is None:
        raise ValueError(f"{key} must not be blank")
    text = str(value).strip()
    if not text:
        raise ValueError(f"{key} must not be blank")
    return text


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


def _nonnegative_int(raw: dict[str, Any], key: str, default: int) -> int:
    value = raw.get(key, default)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc
    if parsed < 0:
        raise ValueError(f"{key} must not be negative")
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


def _float_or_none(raw: dict[str, Any], key: str) -> float | None:
    value = raw.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a number") from exc
