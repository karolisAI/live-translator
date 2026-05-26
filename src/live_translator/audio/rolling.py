from __future__ import annotations

from collections import deque
from math import ceil
from queue import Queue
from time import monotonic
from typing import Any

from live_translator.audio.devices import resolve_device_index
from live_translator.audio.io import _apply_input_gain, _audio_packages, _resample_linear, _select_sample_rate
from live_translator.config import AudioSettings, ChunkingSettings


class RollingSpeechChunker:
    def __init__(self, settings: AudioSettings, chunking: ChunkingSettings) -> None:
        self._settings = settings
        self._chunking = chunking
        self._sd, self._np = _audio_packages()
        self._device_index = resolve_device_index(settings.input_device, "input")
        self._capture_rate = _select_sample_rate(self._sd, self._device_index, "input", settings.sample_rate)
        self._frame_samples = max(1, int(self._capture_rate * chunking.frame_ms / 1000.0))
        self._emit_frames = max(1, ceil(chunking.min_segment_seconds * 1000.0 / chunking.frame_ms))
        self._silence_frames = max(1, ceil(chunking.silence_ms / chunking.frame_ms))
        self._pre_roll_frames = max(0, ceil(chunking.pre_roll_ms / chunking.frame_ms))
        self._max_frames = max(1, ceil(chunking.max_seconds * 1000.0 / chunking.frame_ms))
        self._overlap_frames = self._pre_roll_frames
        self._queue: Queue[Any] = Queue()
        self._pre_roll: deque[Any] = deque(maxlen=self._pre_roll_frames)
        self._frames: list[Any] = []
        self._speech_started = False
        self._silence_after_speech = 0
        self._noise_floor = 0.0
        self._last_level_log = monotonic()
        self._stream = None

    def __enter__(self) -> "RollingSpeechChunker":
        self._stream = self._sd.InputStream(
            samplerate=self._capture_rate,
            channels=1,
            dtype="float32",
            device=self._device_index,
            blocksize=self._frame_samples,
            callback=self._callback,
        )
        self._stream.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._stream is not None:
            self._stream.__exit__(exc_type, exc, tb)
        return False

    def next_chunk(self) -> Any:
        while True:
            block = self._queue.get()
            chunk = self._process_block(block)
            if chunk is not None:
                return chunk

    def _callback(self, indata, _frames, time_info, status) -> None:  # noqa: ANN001
        if status:
            print(f"Warning: audio input status: {status}")
        self._queue.put(self._np.asarray(indata, dtype=self._np.float32).reshape(-1).copy())

    def _process_block(self, block: Any) -> Any | None:
        for start in range(0, len(block), self._frame_samples):
            frame = block[start : start + self._frame_samples]
            if len(frame) < self._frame_samples:
                continue

            rms = float(self._np.sqrt(self._np.mean(self._np.square(frame)))) if len(frame) else 0.0
            peak = float(self._np.max(self._np.abs(frame))) if len(frame) else 0.0
            threshold = max(
                self._chunking.rms_threshold,
                min(self._noise_floor * self._chunking.noise_multiplier, self._chunking.rms_threshold * 2.0)
                if self._noise_floor > 0.0
                else 0.0,
            )
            is_speech = rms >= threshold or peak >= self._chunking.peak_threshold

            now = monotonic()
            if not self._speech_started and now - self._last_level_log >= 1.0:
                print(
                    "Listening levels: "
                    f"rms={rms:.4f} peak={peak:.4f} threshold={threshold:.4f}"
                )
                self._last_level_log = now

            if not self._speech_started:
                if not is_speech:
                    self._pre_roll.append(frame)
                    self._noise_floor = (
                        rms if self._noise_floor <= 0.0 else (0.98 * self._noise_floor + 0.02 * rms)
                    )
                    continue

                self._speech_started = True
                self._frames.extend(item.copy() for item in self._pre_roll)
                self._frames.append(frame.copy())
                self._silence_after_speech = 0
                print(f"Speech detected rms={rms:.4f} threshold={threshold:.4f}.")
                continue

            self._frames.append(frame)
            if is_speech:
                self._silence_after_speech = 0
            else:
                self._silence_after_speech += 1

            if len(self._frames) >= self._emit_frames:
                print("Committing speech segment: rolling window reached.")
                return self._emit_current_segment(keep_overlap=True)

            if len(self._frames) >= self._max_frames:
                print("Committing speech segment: max window reached.")
                return self._emit_current_segment(keep_overlap=True)

            if (
                self._silence_after_speech >= self._silence_frames
                and len(self._frames) >= self._emit_frames
            ):
                print("Committing speech segment: trailing silence detected.")
                return self._emit_current_segment(keep_overlap=False)

        return None

    def _emit_current_segment(self, *, keep_overlap: bool) -> Any:
        if not self._frames:
            return self._np.zeros(0, dtype=self._np.float32)

        emitted = self._np.concatenate(self._frames).astype(self._np.float32)
        if keep_overlap and self._overlap_frames > 0:
            tail = self._frames[-self._overlap_frames :]
            self._frames = [item.copy() for item in tail]
            self._silence_after_speech = 0
        else:
            self._frames = []
            self._pre_roll.clear()
            self._speech_started = False
            self._silence_after_speech = 0

        if int(self._capture_rate) != int(self._settings.sample_rate):
            emitted = _resample_linear(self._np, emitted, int(self._capture_rate), self._settings.sample_rate)
        emitted = _apply_input_gain(self._np, emitted, self._settings.input_gain)
        return emitted
