from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Full, Queue
from threading import Event, Thread
from time import perf_counter
from typing import Any, Callable

from live_translator.errors import UntrustedRuntimePath


@dataclass(frozen=True)
class CapturedSegment:
    number: int
    audio: Any
    captured_at: float


@dataclass(frozen=True)
class _WorkerFailure:
    stage: str
    error: BaseException


_STOP = object()


class RealtimeMeetingWorkers:
    """Keep capture independent from ordered recognition and playback work."""

    def __init__(
        self,
        process_segment: Callable[[CapturedSegment], str | None],
        speak: Callable[[str], None],
        *,
        segment_queue_size: int = 8,
        playback_queue_size: int = 8,
        on_warning: Callable[[str], None] = print,
    ) -> None:
        if segment_queue_size <= 0 or playback_queue_size <= 0:
            raise ValueError("Realtime queue sizes must be positive")
        self.stop_event = Event()
        self._process_segment = process_segment
        self._speak = speak
        self._on_warning = on_warning
        self._segments: Queue[CapturedSegment | object] = Queue(maxsize=segment_queue_size)
        self._playback: Queue[tuple[int, str] | object] = Queue(maxsize=playback_queue_size)
        self._failures: Queue[_WorkerFailure] = Queue()
        self._next_number = 1
        self._started = False
        self._tts_disabled_reason: str | None = None
        """Set once, from the playback thread only, on UntrustedRuntimePath.

        Not a lock-protected flag: only `_playback_loop` ever writes it, and
        only `_playback_loop` reads it, so this is safe as long as playback
        stays single-threaded. It would need a lock if that ever changes.
        """
        self._recognition_thread = Thread(
            target=self._recognition_loop,
            name="live-translator-recognition",
            daemon=True,
        )
        self._playback_thread = Thread(
            target=self._playback_loop,
            name="live-translator-playback",
            daemon=True,
        )

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._playback_thread.start()
        self._recognition_thread.start()

    def submit(self, audio: Any) -> int:
        self.raise_if_failed()
        if self.stop_event.is_set():
            raise RuntimeError("Meeting workers are stopping")

        number = self._next_number
        self._next_number += 1
        segment = CapturedSegment(number=number, audio=audio, captured_at=perf_counter())
        dropped = self._offer_latest(self._segments, segment)
        if dropped:
            self._on_warning(
                "Warning: recognition fell behind; skipped the oldest queued phrase to stay live."
            )
        return number

    def raise_if_failed(self) -> None:
        try:
            failure = self._failures.get_nowait()
        except Empty:
            return
        raise RuntimeError(f"Background {failure.stage} failed: {failure.error}") from failure.error

    def stop(self, *, join_timeout: float = 10.0) -> None:
        if not self._started:
            return
        self.stop_event.set()

        self._discard_pending(self._segments)
        self._offer_stop(self._segments)
        self._recognition_thread.join(timeout=join_timeout)

        self._discard_pending(self._playback)
        self._offer_stop(self._playback)
        self._playback_thread.join(timeout=join_timeout)

        if self._recognition_thread.is_alive() or self._playback_thread.is_alive():
            self._on_warning("Warning: a background worker did not stop within the shutdown timeout.")

    def _recognition_loop(self) -> None:
        try:
            while True:
                item = self._segments.get()
                try:
                    if item is _STOP:
                        return
                    translated = self._process_segment(item)
                    if translated:
                        dropped = self._offer_latest(self._playback, (item.number, translated))
                        if dropped:
                            self._on_warning(
                                "Warning: speech playback fell behind; skipped the oldest queued translation."
                            )
                finally:
                    self._segments.task_done()
        except BaseException as exc:
            self._record_failure("recognition/translation", exc)

    def _playback_loop(self) -> None:
        try:
            while True:
                item = self._playback.get()
                try:
                    if item is _STOP:
                        return
                    _number, text = item
                    if self._tts_disabled_reason is not None:
                        # Already warned once below; a mistrusted executable
                        # will resolve the same way again, so retrying every
                        # phrase would only repeat the same failure -- and
                        # printing about it every phrase would recreate the
                        # exact per-phrase spam this is meant to avoid.
                        continue
                    try:
                        self._speak(text)
                    except UntrustedRuntimePath as exc:
                        self._tts_disabled_reason = str(exc)
                        self._on_warning(
                            f"SECURITY WARNING: phrase {_number} tried to run a speech "
                            f"executable outside every trusted location ({exc}). Spoken "
                            f"playback is disabled for the rest of this meeting; "
                            f"transcription and translation continue normally."
                        )
                    except Exception as exc:
                        self._on_warning(
                            f"Warning: translated speech playback failed for phrase {_number}: "
                            f"{exc}. Continuous listening remains active."
                        )
                finally:
                    self._playback.task_done()
        except BaseException as exc:
            self._record_failure("speech playback", exc)

    def _record_failure(self, stage: str, error: BaseException) -> None:
        self._failures.put(_WorkerFailure(stage=stage, error=error))
        self.stop_event.set()

    @staticmethod
    def _offer_latest(queue: Queue[Any], item: Any) -> bool:
        try:
            queue.put_nowait(item)
            return False
        except Full:
            pass

        dropped = False
        try:
            queue.get_nowait()
            queue.task_done()
            dropped = True
        except Empty:
            pass
        queue.put_nowait(item)
        return dropped

    @staticmethod
    def _discard_pending(queue: Queue[Any]) -> None:
        while True:
            try:
                queue.get_nowait()
                queue.task_done()
            except Empty:
                return

    @staticmethod
    def _offer_stop(queue: Queue[Any]) -> None:
        while True:
            try:
                queue.put_nowait(_STOP)
                return
            except Full:
                try:
                    queue.get_nowait()
                    queue.task_done()
                except Empty:
                    continue
