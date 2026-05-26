from __future__ import annotations

from dataclasses import dataclass
from math import pi
from typing import Any

from live_translator.audio.devices import resolve_device_index
from live_translator.errors import MissingDependency


@dataclass(frozen=True)
class RouteTestResult:
    sample_rate: int
    rms: float
    peak: float
    passed: bool


def test_output_to_input_route(
    *,
    output_device: str,
    input_device: str,
    sample_rate: int = 48000,
    duration_seconds: float = 1.0,
    frequency_hz: float = 880.0,
    threshold: float = 0.01,
) -> RouteTestResult:
    sd, np = _audio_packages()
    output_index = resolve_device_index(output_device, "output")
    input_index = resolve_device_index(input_device, "input")

    for rate in _candidate_rates(sd, input_index, output_index, sample_rate):
        try:
            frames = max(1, int(rate * duration_seconds))
            time = np.arange(frames, dtype=np.float32) / float(rate)
            tone = (0.2 * np.sin(2.0 * pi * frequency_hz * time)).astype(np.float32)
            recording = sd.playrec(
                tone.reshape(-1, 1),
                samplerate=rate,
                channels=1,
                dtype="float32",
                device=(input_index, output_index),
            )
            sd.wait()
            samples = np.asarray(recording, dtype=np.float32).reshape(-1)
            rms = float(np.sqrt(np.mean(np.square(samples)))) if len(samples) else 0.0
            peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
            return RouteTestResult(sample_rate=rate, rms=rms, peak=peak, passed=rms >= threshold)
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"Could not test output-to-input route: {type(last_error).__name__}: {last_error}")


def _candidate_rates(sd: Any, input_index: int | None, output_index: int | None, preferred: int) -> list[int]:
    rates: list[int] = [preferred]
    for index in (input_index, output_index):
        if index is not None:
            try:
                rates.append(int(sd.query_devices(index)["default_samplerate"]))
            except Exception:
                pass
    rates.extend([48000, 44100, 22050, 16000])
    return list(dict.fromkeys(rates))


def _audio_packages():
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError as exc:
        raise MissingDependency(
            "Missing dependency 'numpy' or 'sounddevice'. Install dependencies with: python -m pip install -e ."
        ) from exc
    return sd, np
