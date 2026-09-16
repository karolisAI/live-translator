from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from live_translator.audio.devices import (
    AudioDevice,
    DeviceKind,
    DeviceRole,
    list_devices,
    resolve_device_index,
)
from live_translator.config import AppConfig, validate_config
from live_translator.defaults import DEFAULT_ASR_ENGINE, DEFAULT_ASR_MODEL
from live_translator.errors import MissingDependency
from live_translator.runtime import default_profile_path, resolve_trusted_path


SUPPORTED_DIRECTIONS = ("en-de", "de-en")

DIRECTION_SETTINGS: dict[str, dict[str, Any]] = {
    "en-de": {
        "asr_language": "en",
        "source_language": "en",
        "target_language": "de",
        "tts_model": "models/tts/de_DE-thorsten-medium.onnx",
    },
    "de-en": {
        "asr_language": "de",
        "source_language": "de",
        "target_language": "en",
        "tts_model": "models/tts/en_US-hfc_male-medium.onnx",
    },
}

INBOUND_TARGET_LANGUAGE = "en"


def inbound_config(outbound: AppConfig, their_language: str | None = None, target_language: str = INBOUND_TARGET_LANGUAGE) -> AppConfig:
    """The inbound direction's config: the outbound direction with languages reversed.

    The remote party speaks `their_language` (by default, the language the
    outbound direction translates into) and target_language selects what the user hears (English by default).
    Recognition and translation share the source language; Piper uses the
    bundled voice for the selected target language.

    Engines, model, thread count, chunking and queue settings are copied from the
    outbound config, so both directions run the same stack. The audio section is
    copied unchanged: the inbound capture and headset devices are wired
    separately and must be set before this config is run.
    """
    language = (their_language or outbound.translation.target_language).lower()
    direction = f"{language}-{target_language.lower()}"
    if direction not in DIRECTION_SETTINGS:
        raise ValueError(
            f"Unsupported remote language direction '{direction}'. "
            f"Use one of: {', '.join(SUPPORTED_DIRECTIONS)}"
        )

    settings = DIRECTION_SETTINGS[direction]
    inbound = replace(
        outbound,
        asr=replace(outbound.asr, source_language=settings["asr_language"]),
        translation=replace(
            outbound.translation,
            source_language=settings["source_language"],
            target_language=settings["target_language"],
        ),
        tts=replace(outbound.tts, model_path=settings["tts_model"]),
    )
    validate_config(inbound)
    return inbound


def validate_inbound_config(outbound: AppConfig, inbound: AppConfig) -> None:
    """Validate explicit overrides against the conversation's inbound contract."""
    source = inbound.translation.source_language.lower()
    target = inbound.translation.target_language.lower()
    if f"{source}-{target}" not in DIRECTION_SETTINGS:
        raise ValueError(f"Unsupported inbound direction '{source}-{target}'.")
    if (inbound.asr.source_language or "").lower() != source:
        raise ValueError(f"Inbound recognition must use {source}, matching translation.source_language.")
    voice_name = {"en": "English", "de": "German"}[target]
    if inbound.tts.engine.lower() not in {"piper", "piper-cli"}:
        raise ValueError(f"Inbound speech requires a {voice_name} Piper voice.")
    if not inbound.tts.model_path:
        raise ValueError("tts.model_path is required for the inbound Piper voice.")
    model = resolve_trusted_path(inbound.tts.model_path)
    metadata_path = resolve_trusted_path(model.with_suffix(".onnx.json"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    language = metadata.get("language", {}) if isinstance(metadata, dict) else {}
    code = language.get("code", "") if isinstance(language, dict) else ""
    if not isinstance(code, str) or code.lower().replace("-", "_").split("_")[0] != target:
        raise ValueError(f"Inbound speech requires a {voice_name} Piper voice (language.code in its metadata).")


def wire_inbound_devices(inbound: AppConfig) -> AppConfig:
    """Point the inbound direction at the second cable and the user's headset.

    Capture is the recording end of CABLE-B, where the meeting app's speaker is
    routed; playback is Windows' default headset or speakers. Both are resolved
    to concrete device names here because the pipeline reads audio.input_device
    and audio.output_device with the outbound roles, where "auto" would mean the
    physical microphone and the outbound cable.
    """
    capture = _auto_device_name("input", "remote_input")
    headset = _auto_device_name("output", "headset_output")
    return replace(
        inbound,
        audio=replace(
            inbound.audio,
            input_device=capture,
            output_device=headset,
            peer_input_device=None,
        ),
    )


def _auto_device_name(kind: DeviceKind, role: DeviceRole) -> str:
    index = resolve_device_index("auto", kind, role=role)
    return next(device.name for device in list_devices(kind) if device.index == index)


def write_meeting_profile(
    *,
    path: str | Path | None,
    direction: str,
    microphone_device: str,
    translated_output_device: str,
    meeting_microphone_device: str,
    chunk_seconds: float = 4.0,
) -> Path:
    settings = _direction_settings(direction)
    profile_path = Path(path) if path else default_profile_path()
    profile_path.parent.mkdir(parents=True, exist_ok=True)

    raw = {
        "audio": {
            "sample_rate": 16000,
            "chunk_seconds": chunk_seconds,
            "input_device": microphone_device,
            "output_device": translated_output_device,
            "peer_input_device": meeting_microphone_device,
            "input_gain": 1.0,
            "playback_gain": 0.7,
        },
        "asr": {
            "engine": DEFAULT_ASR_ENGINE,
            "model": DEFAULT_ASR_MODEL,
            "device": "cpu",
            "compute_type": "int8",
            "cpu_threads": 8,
            "source_language": settings["asr_language"],
            "log_prob_threshold": -1.3,
            "compression_ratio_threshold": 2.4,
            "min_segment_chars": 2,
        },
        "translation": {
            "engine": "argos",
            "source_language": settings["source_language"],
            "target_language": settings["target_language"],
        },
        "tts": {
            "engine": "piper",
            "model_path": settings["tts_model"],
            "piper_exe": "tools/piper/piper.exe",
            "speaker": None,
            "length_scale": 1.0,
        },
        "chunking": {
            "mode": "vad",
            "frame_ms": 30,
            "min_speech_ms": 180,
            "min_segment_seconds": 0.8,
            "rolling_window_seconds": 2.4,
            "silence_ms": 450,
            "max_seconds": 5.0,
            "pre_roll_ms": 200,
            "rms_threshold": 0.008,
            "peak_threshold": 0.025,
            "min_active_ratio": 0.06,
            "noise_multiplier": 3.0,
        },
        "realtime": {
            "recognition_queue_size": 2,
            "playback_queue_size": 1,
        },
    }

    try:
        import yaml
    except ImportError as exc:
        raise MissingDependency("Missing dependency 'PyYAML'. Install dependencies with: python -m pip install -e .") from exc

    profile_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return profile_path


def prompt_for_device(kind: str, prompt: str) -> str:
    devices = list_devices(kind)  # type: ignore[arg-type]
    if not devices:
        raise RuntimeError(f"No {kind} devices found.")

    _print_numbered_devices(devices, kind)
    while True:
        value = input(f"{prompt}: ").strip()
        if not value:
            print("Enter a device number or exact device name.")
            continue
        selected = _select_device(value, devices)
        if selected:
            return selected
        print("No matching device. Try the number from the list or paste the exact name.")


def _select_device(value: str, devices: list[AudioDevice]) -> str | None:
    if value.isdigit():
        requested = int(value)
        for device in devices:
            if device.index == requested:
                same_name = [item for item in devices if item.name == device.name]
                return str(device.index) if len(same_name) > 1 else device.name
        return None

    exact = [device for device in devices if device.name.lower() == value.lower()]
    if len(exact) == 1:
        return exact[0].name
    partial = [device for device in devices if value.lower() in device.name.lower()]
    if len(partial) == 1:
        return partial[0].name
    return None


def _print_numbered_devices(devices: list[AudioDevice], kind: str) -> None:
    print()
    print(f"Available {kind} devices:")
    for device in devices:
        channels = device.max_input_channels if kind == "input" else device.max_output_channels
        print(
            f"  [{device.index}] {device.name} [{device.host_api}] "
            f"channels={channels} rate={device.default_sample_rate:.0f}"
        )


def _direction_settings(direction: str) -> dict[str, Any]:
    normalized = direction.lower()
    if normalized not in DIRECTION_SETTINGS:
        raise ValueError(f"Unsupported direction '{direction}'. Use one of: {', '.join(SUPPORTED_DIRECTIONS)}")
    return DIRECTION_SETTINGS[normalized]
