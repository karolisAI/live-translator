from __future__ import annotations

from collections import deque
from queue import Queue
from math import ceil
from time import monotonic
from typing import Any

from live_translator.audio.devices import resolve_device_index
from live_translator.audio.io import _apply_input_gain, _audio_packages, _resample_linear, _select_sample_rate
from live_translator.config import AudioSettings, ChunkingSettings


def record_speech_segment(settings: AudioSettings, chunking: ChunkingSettings) -> Any:
    sd, np = _audio_packages()
    device_index = resolve_device_index(settings.input_device, "input")
    capture_rate = _select_sample_rate(sd, device_index, "input", settings.sample_rate)
    frame_samples = max(1, int(capture_rate * chunking.frame_ms / 1000.0))
    silence_frames = max(1, ceil(chunking.silence_ms / chunking.frame_ms))
    min_speech_frames = max(1, ceil(chunking.min_speech_ms / chunking.frame_ms))
    min_segment_frames = max(1, ceil(chunking.min_segment_seconds * 1000.0 / chunking.frame_ms))
    pre_roll_frames = max(0, ceil(chunking.pre_roll_ms / chunking.frame_ms))
    max_frames = max(1, ceil(chunking.max_seconds * 1000.0 / chunking.frame_ms))

    print(
        f"Listening for speech at {capture_rate} Hz from {settings.input_device or 'default input'} "
        f"(silence={chunking.silence_ms}ms min={chunking.min_segment_seconds:.1f}s "
        f"max={chunking.max_seconds:.1f}s)..."
    )

    pre_roll: deque[Any] = deque(maxlen=pre_roll_frames)
    frames: list[Any] = []
    speech_started = False
    speech_frames = 0
    silence_after_speech = 0
    noise_floor = 0.0
    committed = False
    last_level_log = monotonic()
    audio_queue: Queue[Any] = Queue()

    def callback(indata, _frames, time_info, status) -> None:  # noqa: ANN001
        if status:
            print(f"Warning: audio input status: {status}")
        audio_queue.put(np.asarray(indata, dtype=np.float32).reshape(-1).copy())

    with sd.InputStream(
        samplerate=capture_rate,
        channels=1,
        dtype="float32",
        device=device_index,
        blocksize=frame_samples,
        callback=callback,
    ):
        while not committed:
            block = audio_queue.get()
            for start in range(0, len(block), frame_samples):
                frame = block[start : start + frame_samples]
                if len(frame) < frame_samples:
                    continue
                rms = float(np.sqrt(np.mean(np.square(frame)))) if len(frame) else 0.0
                peak = float(np.max(np.abs(frame))) if len(frame) else 0.0
                adaptive_threshold = (
                    min(noise_floor * chunking.noise_multiplier, chunking.rms_threshold * 2.0)
                    if noise_floor > 0.0
                    else 0.0
                )
                threshold = max(
                    chunking.rms_threshold,
                    adaptive_threshold,
                )
                is_speech = rms >= threshold or peak >= chunking.peak_threshold

                now = monotonic()
                if not speech_started and now - last_level_log >= 1.0:
                    print(
                        "Listening levels: "
                        f"rms={rms:.4f} peak={peak:.4f} threshold={threshold:.4f}"
                    )
                    last_level_log = now

                if not speech_started:
                    if not is_speech:
                        pre_roll.append(frame)
                        noise_floor = rms if noise_floor <= 0.0 else (0.98 * noise_floor + 0.02 * rms)
                        continue

                    speech_started = True
                    frames.extend(item.copy() for item in pre_roll)
                    frames.append(frame.copy())
                    speech_frames = 1
                    silence_after_speech = 0
                    print(f"Speech detected rms={rms:.4f} threshold={threshold:.4f}.")
                    continue

                frames.append(frame)
                if is_speech:
                    speech_frames += 1
                    silence_after_speech = 0
                else:
                    silence_after_speech += 1

                if len(frames) >= max_frames:
                    print("Committing speech segment: max window reached.")
                    committed = True
                    break

                if (
                    speech_frames >= min_speech_frames
                    and silence_after_speech >= silence_frames
                    and len(frames) >= min_segment_frames
                ):
                    print("Committing speech segment: trailing silence detected.")
                    committed = True
                    break

    if not frames:
        return np.zeros(0, dtype=np.float32)

    samples = np.concatenate(frames).astype(np.float32)
    if int(capture_rate) != int(settings.sample_rate):
        samples = _resample_linear(np, samples, int(capture_rate), settings.sample_rate)
    samples = _apply_input_gain(np, samples, settings.input_gain)
    return samples
