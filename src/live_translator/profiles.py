from __future__ import annotations

from pathlib import Path
from typing import Any

from live_translator.audio.devices import AudioDevice, list_devices
from live_translator.errors import MissingDependency
from live_translator.runtime import default_profile_path


SUPPORTED_DIRECTIONS = ("en-de", "de-en")

DIRECTION_SETTINGS: dict[str, dict[str, Any]] = {
    "en-de": {
        "asr_language": "en",
        "source_language": "en",
        "target_language": "de",
        "tts_voice": "de_DE-thorsten-medium",
        "tts_model": "models/tts/de_DE-thorsten-medium.onnx",
    },
    "de-en": {
        "asr_language": "de",
        "source_language": "de",
        "target_language": "en",
        "tts_voice": "en_US-hfc_male-medium",
        "tts_model": "models/tts/en_US-hfc_male-medium.onnx",
    },
}


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
            "playback_gain": 1.0,
        },
        "asr": {
            "engine": "faster-whisper",
            "model": "base",
            "device": "auto",
            "compute_type": "auto",
            "source_language": settings["asr_language"],
            "beam_size": 1,
            "condition_on_previous_text": False,
            "no_speech_threshold": 0.90,
            "log_prob_threshold": -1.8,
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
            "voice": settings["tts_voice"],
            "model_path": settings["tts_model"],
            "piper_exe": "tools/piper/piper.exe",
            "speaker": None,
        },
        "chunking": {
            "mode": "vad",
            "frame_ms": 30,
            "min_speech_ms": 250,
            "min_segment_seconds": 1.2,
            "silence_ms": 650,
            "max_seconds": 6.0,
            "pre_roll_ms": 180,
            "rms_threshold": 0.012,
            "peak_threshold": 0.035,
            "min_active_ratio": 0.08,
            "noise_multiplier": 3.0,
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
        print(f"  [{device.index}] {device.name}  channels={channels} rate={device.default_sample_rate:.0f}")


def _direction_settings(direction: str) -> dict[str, Any]:
    normalized = direction.lower()
    if normalized not in DIRECTION_SETTINGS:
        raise ValueError(f"Unsupported direction '{direction}'. Use one of: {', '.join(SUPPORTED_DIRECTIONS)}")
    return DIRECTION_SETTINGS[normalized]
