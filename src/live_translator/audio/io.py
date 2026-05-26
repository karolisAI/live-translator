from __future__ import annotations

import wave
from pathlib import Path
from typing import Any

from live_translator.audio.devices import resolve_device_index
from live_translator.config import AudioSettings
from live_translator.errors import MissingDependency


def record_mono(settings: AudioSettings, seconds: float | None = None) -> Any:
    sd, np = _audio_packages()
    duration = seconds if seconds is not None else settings.chunk_seconds
    device_index = resolve_device_index(settings.input_device, "input")
    capture_rate = _select_sample_rate(sd, device_index, "input", settings.sample_rate)
    frames = int(capture_rate * duration)

    print(
        f"Recording {duration:.1f}s at {capture_rate} Hz"
        f" from {settings.input_device or 'default input'}..."
    )
    audio = sd.rec(
        frames,
        samplerate=capture_rate,
        channels=1,
        dtype="float32",
        device=device_index,
    )
    sd.wait()
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    if int(capture_rate) != int(settings.sample_rate):
        samples = _resample_linear(np, samples, int(capture_rate), settings.sample_rate)
    samples = _apply_input_gain(np, samples, settings.input_gain)
    return samples


def play_mono(audio: Any, settings: AudioSettings) -> None:
    sd, np = _audio_packages()
    if audio is None:
        return

    device_index = resolve_device_index(settings.output_device, "output")
    playback_rate = _select_sample_rate(sd, device_index, "output", settings.sample_rate)
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    if settings.playback_gain != 1.0:
        samples = np.clip(samples * settings.playback_gain, -1.0, 1.0)
    if int(playback_rate) != int(settings.sample_rate):
        samples = _resample_linear(np, samples, settings.sample_rate, int(playback_rate))

    sd.play(samples, samplerate=playback_rate, device=device_index)
    sd.wait()


def write_wav(path: str | Path, audio: Any, sample_rate: int) -> None:
    _, np = _audio_packages()
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype(np.int16)

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())


def read_wav_mono(path: str | Path) -> tuple[Any, int]:
    _, np = _audio_packages()
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        sample_rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())

    if sample_width != 2:
        raise ValueError(f"Only 16-bit PCM WAV is supported for playback: {path}")

    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, sample_rate


def _audio_packages():
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError as exc:
        raise MissingDependency(
            "Missing dependency 'numpy' or 'sounddevice'. Install dependencies with: python -m pip install -e ."
        ) from exc
    return sd, np


def _select_sample_rate(sd: Any, device_index: int | None, kind: str, target_rate: int) -> int:
    check = sd.check_input_settings if kind == "input" else sd.check_output_settings
    try:
        check(device=device_index, samplerate=target_rate, channels=1, dtype="float32")
        return target_rate
    except Exception:
        pass

    fallback_rates = []
    if device_index is not None:
        device = sd.query_devices(device_index)
        fallback_rates.append(int(device["default_samplerate"]))
    fallback_rates.extend([48000, 44100, 16000])

    for rate in dict.fromkeys(fallback_rates):
        try:
            check(device=device_index, samplerate=rate, channels=1, dtype="float32")
            if rate != target_rate:
                print(f"Info: using {rate} Hz for {kind}; internal pipeline remains {target_rate} Hz.")
            return rate
        except Exception:
            continue

    device_text = f"device {device_index}" if device_index is not None else "default device"
    raise RuntimeError(f"Could not open {kind} {device_text} at any supported sample rate.")


def _resample_linear(np: Any, samples: Any, source_rate: int, target_rate: int) -> Any:
    if source_rate == target_rate or len(samples) == 0:
        return samples

    duration = len(samples) / float(source_rate)
    target_length = max(1, int(round(duration * target_rate)))
    source_positions = np.linspace(0.0, duration, num=len(samples), endpoint=False)
    target_positions = np.linspace(0.0, duration, num=target_length, endpoint=False)
    return np.interp(target_positions, source_positions, samples).astype(np.float32)


def _apply_input_gain(np: Any, samples: Any, gain: float) -> Any:
    if gain == 1.0 or len(samples) == 0:
        return samples
    return np.clip(samples * gain, -1.0, 1.0).astype(np.float32)
