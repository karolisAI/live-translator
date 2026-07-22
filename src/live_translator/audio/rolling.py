from __future__ import annotations

from collections import deque
from math import ceil
from queue import Empty, Full, Queue
from threading import Event, Lock
from time import monotonic
from typing import Any

from live_translator.audio.devices import resolve_device_index
from live_translator.audio.io import _apply_input_gain, _audio_packages, _resample_audio, _select_sample_rate
from live_translator.config import AudioSettings, ChunkingSettings


class RollingSpeechChunker:
    def __init__(
        self,
        settings: AudioSettings,
        chunking: ChunkingSettings,
        *,
        emit_while_speaking: bool = True,
        verbose: bool = False,
    ) -> None:
        self._settings = settings
        self._chunking = chunking
        self._verbose = verbose
        self._emit_while_speaking = emit_while_speaking
        self._sd, self._np = _audio_packages()
        self._device_index = resolve_device_index(
            settings.input_device,
            "input",
            role="physical_input",
        )
        self._capture_rate = _select_sample_rate(self._sd, self._device_index, "input", settings.sample_rate)
        self._frame_samples = max(1, int(self._capture_rate * chunking.frame_ms / 1000.0))
        emit_seconds = (
            chunking.rolling_window_seconds if emit_while_speaking else chunking.min_segment_seconds
        )
        self._emit_frames = max(1, ceil(emit_seconds * 1000.0 / chunking.frame_ms))
        self._min_segment_frames = max(
            1,
            ceil(chunking.min_segment_seconds * 1000.0 / chunking.frame_ms),
        )
        self._min_speech_frames = max(1, ceil(chunking.min_speech_ms / chunking.frame_ms))
        self._silence_frames = max(1, ceil(chunking.silence_ms / chunking.frame_ms))
        self._pre_roll_frames = max(0, ceil(chunking.pre_roll_ms / chunking.frame_ms))
        self._max_frames = max(1, ceil(chunking.max_seconds * 1000.0 / chunking.frame_ms))
        self._overlap_frames = self._pre_roll_frames
        # Bound callback buffering to one emission window. The capture consumer
        # runs continuously and hands complete phrases to separate workers.
        self._queue: Queue[Any] = Queue(maxsize=self._emit_frames)
        self._dropped_blocks = 0
        self._drop_lock = Lock()
        self._pre_roll: deque[Any] = deque(maxlen=self._pre_roll_frames)
        self._frames: list[Any] = []
        self._speech_started = False
        self._new_speech_frames = 0
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

    def next_chunk(self, *, stop_event: Event | None = None) -> Any | None:
        while stop_event is None or not stop_event.is_set():
            try:
                block = self._queue.get(timeout=0.1)
            except Empty:
                continue
            dropped = self._consume_dropped_blocks()
            if dropped:
                self._reset_segment()
                self._log(f"Warning: dropped {dropped} stale audio block(s).")
            chunk = self._process_block(block)
            if chunk is not None:
                return chunk
        return None

    def _callback(self, indata, _frames, time_info, status) -> None:  # noqa: ANN001
        if status:
            self._log(f"Warning: audio input status: {status}")
        block = self._np.asarray(indata, dtype=self._np.float32).reshape(-1).copy()
        try:
            self._queue.put_nowait(block)
            return
        except Full:
            pass

        try:
            self._queue.get_nowait()
            self._record_dropped_block()
        except Empty:
            pass

        try:
            self._queue.put_nowait(block)
        except Full:
            # A consumer raced us and a newer callback filled the slot. The
            # current block is stale by definition, so dropping it is safe.
            self._record_dropped_block()

    def _process_block(self, block: Any) -> Any | None:
        for start in range(0, len(block), self._frame_samples):
            frame = block[start : start + self._frame_samples]
            if len(frame) < self._frame_samples:
                continue

            detection_frame = _apply_input_gain(self._np, frame, self._settings.input_gain)
            rms = (
                float(self._np.sqrt(self._np.mean(self._np.square(detection_frame))))
                if len(frame)
                else 0.0
            )
            peak = float(self._np.max(self._np.abs(detection_frame))) if len(frame) else 0.0
            threshold = max(
                self._chunking.rms_threshold,
                min(self._noise_floor * self._chunking.noise_multiplier, self._chunking.rms_threshold * 2.0)
                if self._noise_floor > 0.0
                else 0.0,
            )
            is_speech = rms >= threshold or peak >= self._chunking.peak_threshold

            now = monotonic()
            if not self._speech_started and now - self._last_level_log >= 1.0:
                self._log(
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
                self._new_speech_frames = 1
                self._silence_after_speech = 0
                self._log(f"Speech detected rms={rms:.4f} threshold={threshold:.4f}.")
                continue

            self._frames.append(frame)
            if is_speech:
                self._new_speech_frames += 1
                self._silence_after_speech = 0
            else:
                self._silence_after_speech += 1

            if self._silence_after_speech >= self._silence_frames:
                if self._new_speech_frames < self._min_speech_frames:
                    self._log("Ignoring false speech trigger: not enough sustained speech.")
                    self._reset_segment()
                    continue
                if len(self._frames) >= self._min_segment_frames:
                    self._log("Committing speech segment: trailing silence detected.")
                    return self._emit_current_segment(keep_overlap=False)
                continue

            if (
                self._emit_while_speaking
                and self._new_speech_frames >= self._min_speech_frames
                and len(self._frames) >= self._emit_frames
            ):
                self._log("Committing speech segment: rolling window reached.")
                return self._emit_current_segment(keep_overlap=True)

            if len(self._frames) >= self._max_frames:
                if self._new_speech_frames >= self._min_speech_frames:
                    self._log("Committing speech segment: max window reached.")
                    return self._emit_current_segment(keep_overlap=self._emit_while_speaking)
                self._reset_segment()

        return None

    def _emit_current_segment(self, *, keep_overlap: bool) -> Any:
        if not self._frames:
            return self._np.zeros(0, dtype=self._np.float32)

        emitted = self._np.concatenate(self._frames).astype(self._np.float32)
        if keep_overlap and self._overlap_frames > 0:
            tail = self._frames[-self._overlap_frames :]
            self._frames = [item.copy() for item in tail]
            self._new_speech_frames = 0
            self._silence_after_speech = 0
        else:
            self._reset_segment()

        if int(self._capture_rate) != int(self._settings.sample_rate):
            emitted = _resample_audio(self._np, emitted, int(self._capture_rate), self._settings.sample_rate)
        emitted = _apply_input_gain(self._np, emitted, self._settings.input_gain)
        return emitted

    def _consume_dropped_blocks(self) -> int:
        with self._drop_lock:
            dropped = self._dropped_blocks
            self._dropped_blocks = 0
        return dropped

    def _record_dropped_block(self) -> None:
        with self._drop_lock:
            self._dropped_blocks += 1

    def _reset_segment(self) -> None:
        self._frames = []
        self._pre_roll.clear()
        self._speech_started = False
        self._new_speech_frames = 0
        self._silence_after_speech = 0

    def _log(self, message: str) -> None:
        if self._verbose:
            print(message)
