import time
import unittest
from threading import Event

from live_translator.errors import UntrustedRuntimePath
from live_translator.realtime import CapturedSegment, RealtimeMeetingWorkers


def wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for background work")


class RealtimeMeetingWorkersTests(unittest.TestCase):
    def test_capture_submission_continues_while_recognition_is_busy(self) -> None:
        recognition_started = Event()
        release_recognition = Event()
        processed: list[int] = []
        spoken: list[str] = []

        def process(segment: CapturedSegment) -> str:
            recognition_started.set()
            release_recognition.wait(timeout=2.0)
            processed.append(segment.number)
            return f"translation-{segment.number}"

        workers = RealtimeMeetingWorkers(process, spoken.append, segment_queue_size=4)
        workers.start()
        try:
            self.assertEqual(workers.submit("first"), 1)
            self.assertTrue(recognition_started.wait(timeout=1.0))
            self.assertEqual(workers.submit("second"), 2)
            self.assertEqual(workers.submit("third"), 3)
            release_recognition.set()
            wait_until(lambda: spoken == ["translation-1", "translation-2", "translation-3"])
        finally:
            release_recognition.set()
            workers.stop()

        self.assertEqual(processed, [1, 2, 3])

    def test_overload_drops_oldest_queued_phrase_deterministically(self) -> None:
        recognition_started = Event()
        release_recognition = Event()
        processed: list[int] = []
        warnings: list[str] = []

        def process(segment: CapturedSegment) -> None:
            recognition_started.set()
            release_recognition.wait(timeout=2.0)
            processed.append(segment.number)
            return None

        workers = RealtimeMeetingWorkers(
            process,
            lambda _text: None,
            segment_queue_size=2,
            on_warning=warnings.append,
        )
        workers.start()
        try:
            workers.submit("first")
            self.assertTrue(recognition_started.wait(timeout=1.0))
            workers.submit("second")
            workers.submit("third")
            workers.submit("fourth")
            release_recognition.set()
            wait_until(lambda: processed == [1, 3, 4])
        finally:
            release_recognition.set()
            workers.stop()

        self.assertEqual(len(warnings), 1)
        self.assertIn("skipped the oldest queued phrase", warnings[0])

    def test_slow_playback_does_not_block_recognition(self) -> None:
        playback_started = Event()
        release_playback = Event()
        processed: list[int] = []
        spoken: list[str] = []

        def process(segment: CapturedSegment) -> str:
            processed.append(segment.number)
            return f"translation-{segment.number}"

        def speak(text: str) -> None:
            playback_started.set()
            release_playback.wait(timeout=2.0)
            spoken.append(text)

        workers = RealtimeMeetingWorkers(process, speak)
        workers.start()
        try:
            workers.submit("first")
            self.assertTrue(playback_started.wait(timeout=1.0))
            workers.submit("second")
            workers.submit("third")
            wait_until(lambda: processed == [1, 2, 3])
            self.assertEqual(spoken, [])
            release_playback.set()
            wait_until(lambda: spoken == ["translation-1", "translation-2", "translation-3"])
        finally:
            release_playback.set()
            workers.stop()

    def test_single_pending_playback_keeps_latest_translation(self) -> None:
        playback_started = Event()
        release_playback = Event()
        processed: list[int] = []
        spoken: list[str] = []
        warnings: list[str] = []

        def process(segment: CapturedSegment) -> str:
            processed.append(segment.number)
            return f"translation-{segment.number}"

        def speak(text: str) -> None:
            if text == "translation-1":
                playback_started.set()
                release_playback.wait(timeout=2.0)
            spoken.append(text)

        workers = RealtimeMeetingWorkers(
            process,
            speak,
            playback_queue_size=1,
            on_warning=warnings.append,
        )
        workers.start()
        try:
            workers.submit("first")
            self.assertTrue(playback_started.wait(timeout=1.0))
            workers.submit("second")
            workers.submit("third")
            wait_until(lambda: processed == [1, 2, 3])
            release_playback.set()
            wait_until(lambda: spoken == ["translation-1", "translation-3"])
        finally:
            release_playback.set()
            workers.stop()

        self.assertEqual(len(warnings), 1)
        self.assertIn("skipped the oldest queued translation", warnings[0])

    def test_worker_failure_stops_capture_and_is_propagated(self) -> None:
        def process(_segment: CapturedSegment) -> str:
            raise ValueError("model failed")

        workers = RealtimeMeetingWorkers(process, lambda _text: None)
        workers.start()
        try:
            workers.submit("audio")
            self.assertTrue(workers.stop_event.wait(timeout=1.0))
            with self.assertRaisesRegex(RuntimeError, "recognition/translation.*model failed"):
                workers.raise_if_failed()
        finally:
            workers.stop()

    def test_playback_failure_warns_without_stopping_capture(self) -> None:
        spoken: list[str] = []
        warnings: list[str] = []

        def process(segment: CapturedSegment) -> str:
            return f"translation-{segment.number}"

        def speak(text: str) -> None:
            if text == "translation-1":
                raise RuntimeError("temporary output error")
            spoken.append(text)

        workers = RealtimeMeetingWorkers(process, speak, on_warning=warnings.append)
        workers.start()
        try:
            workers.submit("first")
            wait_until(lambda: len(warnings) == 1)
            self.assertFalse(workers.stop_event.is_set())
            workers.submit("second")
            wait_until(lambda: spoken == ["translation-2"])
            workers.raise_if_failed()
        finally:
            workers.stop()

        self.assertIn("Continuous listening remains active", warnings[0])

    def test_untrusted_executable_disables_playback_for_the_rest_of_the_meeting(self) -> None:
        """An UntrustedRuntimePath is a security-relevant condition, not a
        routine hiccup: it must be called out distinctly, and -- unlike an
        ordinary playback failure -- must not be retried every phrase, since
        a mistrusted path resolves the same way again on the next attempt."""
        spoken: list[str] = []
        warnings: list[str] = []

        def process(segment: CapturedSegment) -> str:
            return f"translation-{segment.number}"

        def speak(text: str) -> None:
            if text == "translation-1":
                raise UntrustedRuntimePath("piper.exe resolved outside every approved root")
            spoken.append(text)

        workers = RealtimeMeetingWorkers(process, speak, on_warning=warnings.append)
        workers.start()
        try:
            workers.submit("first")
            wait_until(lambda: len(warnings) == 1)
            self.assertFalse(workers.stop_event.is_set())

            workers.submit("second")
            workers.submit("third")
            # stop() would discard whatever is still queued rather than wait
            # for it to be processed, so wait for the playback queue to
            # actually drain first -- otherwise "second"/"third" might never
            # reach the skip branch at all, and the assertions below would
            # pass for the wrong reason.
            workers._playback.join()
            workers.raise_if_failed()
        finally:
            workers.stop()

        # Only the first phrase ever reached speak() with the untrusted path;
        # the rest were skipped rather than retried or spoken.
        self.assertEqual(spoken, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("SECURITY WARNING", warnings[0])
        self.assertIn("disabled for the rest of this meeting", warnings[0])


if __name__ == "__main__":
    unittest.main()
