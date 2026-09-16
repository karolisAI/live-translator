from __future__ import annotations

import sys
import wave
from contextlib import contextmanager
from pathlib import Path
from threading import Lock, local
from time import sleep
from typing import Any

from live_translator.audio.devices import (
    describe_device_index,
    resolve_device_index,
)
from live_translator.config import AudioSettings
from live_translator.errors import MissingDependency


AUDIO_STREAM_LOCK = Lock()
"""Serialises PortAudio stream opens across threads.

PortAudio stream creation/start is not safe to run from two threads at the same
time. A bidirectional session opens one capture stream per direction, each on
its own thread, and each direction's playback worker opens output streams too,
so without this two opens can race. Held only while opening a stream, never
while it runs, so audio still flows concurrently once every stream is open.
Single-direction mode never contends for it.
"""

_thread_com = local()


def _ensure_thread_com() -> None:
    """Initialise COM on the current thread once (Windows only).

    PortAudio's WASAPI/MMDevice backend needs COM initialised on whichever
    thread opens a stream. The main thread gets it from PortAudio's own init,
    but a plain worker thread does not, so its first stream open fails -- on
    Windows this surfaces as a WDM-KS `DeviceIoControl` error. A bidirectional
    session opens every capture stream (and its playback streams) on worker
    threads, so each must initialise COM first. Uses the multithreaded
    apartment, which needs no message pump -- these threads only open a stream.
    Never uninitialised on purpose: the threads live for the whole session, and
    the process tears COM down on exit.
    """
    if sys.platform != "win32":
        return
    if getattr(_thread_com, "ready", False):
        return
    try:
        import ctypes

        ctypes.windll.ole32.CoInitializeEx(None, 0x0)  # COINIT_MULTITHREADED
    except Exception:
        # An already-initialised thread (S_FALSE) or a different-apartment
        # thread (RPC_E_CHANGED_MODE) is still usable; only record that we tried.
        pass
    _thread_com.ready = True


@contextmanager
def audio_open_guard():
    """Wrap a PortAudio stream open: COM-ready thread, then a serialised open.

    Every place that opens a capture or playback stream uses this, so an open
    from any thread is both COM-initialised (see `_ensure_thread_com`) and
    serialised against other opens (see `AUDIO_STREAM_LOCK`).
    """
    _ensure_thread_com()
    with AUDIO_STREAM_LOCK:
        yield


def ensure_audio_ready() -> None:
    """Initialise PortAudio on the calling thread; call once on the main thread.

    PortAudio's first-time initialisation is not safe to trigger from the worker
    threads that open each direction's stream. Single-direction mode never hit
    this because it opens its first stream on the main thread; a bidirectional
    session opens every stream on a worker thread, so it must force that first
    initialisation here, up front, before starting them. Cheap and idempotent.
    """
    sd, _ = _audio_packages()
    with AUDIO_STREAM_LOCK:
        sd.query_devices()


def record_mono(
    settings: AudioSettings,
    seconds: float | None = None,
    *,
    announce: bool = True,
) -> Any:
    sd, np = _audio_packages()
    duration = seconds if seconds is not None else settings.chunk_seconds
    # Guard the device probe and recording open like the streaming capture path,
    # so fixed-mode capture also works from a worker thread (converse runs each
    # direction off the main thread). sd.wait() blocks for the whole recording,
    # so it stays outside the guard.
    with audio_open_guard():
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
            # Only the open is guarded (COM-ready thread + serialised open); the
            # write below streams the audio and must not block another
            # direction's open for its whole duration.
            with audio_open_guard():
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
                with AUDIO_STREAM_LOCK:
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
            # stop() and close() touch PortAudio like open does, so serialise
            # them with other directions' opens. write() streams the audio and
            # stays outside the lock so it never blocks another open.
            with AUDIO_STREAM_LOCK:
                stream.stop()
            return
        except Exception as exc:
            raise RuntimeError(
                "Translated audio playback failed after the output stream started; "
                "the phrase will not be replayed automatically."
            ) from exc
        finally:
            with AUDIO_STREAM_LOCK:
                try:
                    stream.close()
                except Exception:
                    pass

    selector = settings.output_device or "Windows default"
    raise RuntimeError(f"Could not play translated speech through '{selector}': {last_error}") from last_error


def write_wav(path: str | Path, audio: Any, sample_rate: int) -> None:
    # Only numpy: writing a file must not need PortAudio, which is absent on
    # Linux CI runners and makes `import sounddevice` raise OSError.
    np = _numpy_package()
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
    np = _numpy_package()
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
