from __future__ import annotations

import wave
from pathlib import Path
from time import sleep
from typing import Any

from live_translator.audio.devices import (
    describe_device_index,
    resolve_device_index,
)
from live_translator.config import AudioSettings
from live_translator.errors import MissingDependency


def record_mono(
    settings: AudioSettings,
    seconds: float | None = None,
    *,
    announce: bool = True,
) -> Any:
    sd, np = _audio_packages()
    duration = seconds if seconds is not None else settings.chunk_seconds
    device_index = resolve_device_index(settings.input_device, "input", role="physical_input")
    capture_rate = _select_sample_rate(sd, device_index, "input", settings.sample_rate)
    frames = int(capture_rate * duration)

    if announce:
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
        samples = _resample_audio(np, samples, int(capture_rate), settings.sample_rate)
    samples = _apply_input_gain(np, samples, settings.input_gain)
    return samples


def play_mono(audio: Any, settings: AudioSettings) -> None:
    sd, np = _audio_packages()
    if audio is None:
        return

    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    if settings.playback_gain != 1.0:
        samples = np.clip(samples * settings.playback_gain, -1.0, 1.0)

    device_index = resolve_device_index(
        settings.output_device,
        "output",
        role="translated_output",
    )
    raw_device = sd.query_devices(device_index) if device_index is not None else sd.query_devices(kind="output")
    output_channels = 2 if int(raw_device["max_output_channels"]) >= 2 else 1
    playback_rate = _select_sample_rate(
        sd,
        device_index,
        "output",
        settings.sample_rate,
        channels=output_channels,
        announce=False,
    )
    output = samples
    if int(playback_rate) != int(settings.sample_rate):
        output = _resample_audio(np, samples, settings.sample_rate, int(playback_rate))
    frames = output.reshape(-1, 1)
    if output_channels == 2:
        frames = np.repeat(frames, 2, axis=1)
    frames = np.ascontiguousarray(frames, dtype=np.float32)

    last_error: Exception | None = None
    detail = describe_device_index(device_index, "output")
    for attempt in range(3):
        stream = None
        try:
            stream = sd.OutputStream(
                samplerate=playback_rate,
                channels=output_channels,
                dtype="float32",
                device=device_index,
                latency="high",
            )
            stream.start()
        except Exception as exc:
            last_error = exc
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            if attempt < 2:
                print(
                    f"Warning: translated audio output did not start on {detail}; "
                    f"retrying ({attempt + 1}/2)."
                )
                sleep(0.1 * (attempt + 1))
            continue

        try:
            stream.write(frames)
            stream.stop()
            return
        except Exception as exc:
            raise RuntimeError(
                "Translated audio playback failed after the output stream started; "
                "the phrase will not be replayed automatically."
            ) from exc
        finally:
            try:
                stream.close()
            except Exception:
                pass

    selector = settings.output_device or "Windows default"
    raise RuntimeError(f"Could not play translated speech through '{selector}': {last_error}") from last_error


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


def _numpy_package():
    """numpy alone, for code that computes on samples without touching a device.

    Importing sounddevice loads PortAudio and raises OSError where the library is
    absent, so pulling it in for pure arithmetic makes analysis code fail on a
    machine that has no audio stack at all -- including CI.
    """
    try:
        import numpy as np
    except ImportError as exc:
        raise MissingDependency(
            "Missing dependency 'numpy'. Install dependencies with: python -m pip install -e ."
        ) from exc
    return np


def _audio_packages():
    np = _numpy_package()
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise MissingDependency(
            "Missing dependency 'sounddevice'. Install dependencies with: python -m pip install -e ."
        ) from exc
    return sd, np


def _select_sample_rate(
    sd: Any,
    device_index: int | None,
    kind: str,
    target_rate: int,
    *,
    channels: int = 1,
    announce: bool = True,
) -> int:
    check = sd.check_input_settings if kind == "input" else sd.check_output_settings
    try:
        check(device=device_index, samplerate=target_rate, channels=channels, dtype="float32")
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
            check(device=device_index, samplerate=rate, channels=channels, dtype="float32")
            if rate != target_rate and announce:
                if kind == "input":
                    print(
                        f"Info: input device uses {rate} Hz; audio is converted to "
                        f"{target_rate} Hz for processing without changing speed."
                    )
                else:
                    print(
                        f"Info: output device uses {rate} Hz; {target_rate} Hz audio is "
                        "sample-rate converted without changing speed or pitch."
                    )
            return rate
        except Exception:
            continue

    device_text = f"device {device_index}" if device_index is not None else "default device"
    raise RuntimeError(f"Could not open {kind} {device_text} at any supported sample rate.")


def _resample_audio(np: Any, samples: Any, source_rate: int, target_rate: int) -> Any:
    if source_rate == target_rate or len(samples) == 0:
        return samples

    try:
        import av
    except ImportError as exc:
        raise MissingDependency("Missing dependency 'av'. Install dependencies with: python -m pip install -e .") from exc

    source = np.asarray(samples, dtype=np.float32).reshape(1, -1)
    frame = av.AudioFrame.from_ndarray(source, format="fltp", layout="mono")
    frame.sample_rate = source_rate
    resampler = av.AudioResampler(format="fltp", layout="mono", rate=target_rate)
    frames = resampler.resample(frame)
    frames.extend(resampler.resample(None))
    if not frames:
        return _resample_short_audio(np, source.reshape(-1), source_rate, target_rate)
    result = np.concatenate([item.to_ndarray().reshape(-1) for item in frames])
    if len(result) == 0:
        return _resample_short_audio(np, source.reshape(-1), source_rate, target_rate)
    source_peak = float(np.max(np.abs(source)))
    peak_limit = min(1.0, source_peak)
    return np.clip(result, -peak_limit, peak_limit).astype(np.float32)


def _resample_short_audio(np: Any, samples: Any, source_rate: int, target_rate: int) -> Any:
    duration = len(samples) / float(source_rate)
    target_length = max(1, int(round(duration * target_rate)))
    source_positions = np.linspace(0.0, duration, num=len(samples), endpoint=False)
    target_positions = np.linspace(0.0, duration, num=target_length, endpoint=False)
    return np.interp(target_positions, source_positions, samples).astype(np.float32)


def _apply_input_gain(np: Any, samples: Any, gain: float) -> Any:
    if gain == 1.0 or len(samples) == 0:
        return samples
    return np.clip(samples * gain, -1.0, 1.0).astype(np.float32)
