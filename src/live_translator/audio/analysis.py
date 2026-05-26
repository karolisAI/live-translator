from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from live_translator.audio.io import _audio_packages


@dataclass(frozen=True)
class AudioStats:
    duration_seconds: float
    rms: float
    peak: float
    active_ratio: float


def analyze_audio(audio: Any, sample_rate: int, *, frame_ms: int, active_rms_threshold: float) -> AudioStats:
    _, np = _audio_packages()
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    if len(samples) == 0:
        return AudioStats(duration_seconds=0.0, rms=0.0, peak=0.0, active_ratio=0.0)

    rms = float(np.sqrt(np.mean(np.square(samples))))
    peak = float(np.max(np.abs(samples)))
    duration_seconds = len(samples) / float(sample_rate)
    frame_samples = max(1, int(sample_rate * frame_ms / 1000.0))
    active_frames = 0
    total_frames = 0
    for start in range(0, len(samples), frame_samples):
        frame = samples[start : start + frame_samples]
        if len(frame) == 0:
            continue
        total_frames += 1
        frame_rms = float(np.sqrt(np.mean(np.square(frame))))
        if frame_rms >= active_rms_threshold:
            active_frames += 1

    active_ratio = active_frames / float(total_frames) if total_frames else 0.0
    return AudioStats(duration_seconds=duration_seconds, rms=rms, peak=peak, active_ratio=active_ratio)


def has_enough_audio_energy(stats: AudioStats, *, rms_threshold: float, peak_threshold: float, min_active_ratio: float) -> bool:
    return (
        stats.rms >= rms_threshold
        and stats.peak >= peak_threshold
        and stats.active_ratio >= min_active_ratio
    )
