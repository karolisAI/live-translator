"""End-to-end coverage for US-1.3: a fatal failure in one direction's real
worker threads must stop only that direction while the other keeps processing
new phrases and the session process itself stays alive.

Unlike test_session.py (which drives BidirectionalSession with bare fake
Direction callables) and test_pipeline.py (which drives one pipeline's workers
in isolation), this wires two real LocalTranslatorPipeline instances -- each
with its own real RealtimeMeetingWorkers and recognition/playback threads --
into a real BidirectionalSession, and only fakes the boundary each pipeline
already fakes in unit tests: audio capture (`record_mono`) and ASR
(`_transcribe_audio_if_safe`). Translation uses the real identity engine.
"""

import io
import time
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from threading import Thread
from unittest.mock import patch

from live_translator.asr.base import TranscriptResult
from live_translator.config import AppConfig, TranslationSettings
from live_translator.pipeline import LocalTranslatorPipeline
from live_translator.session import BidirectionalSession, Direction
from live_translator.tts.speaker import RenderedSpeech


class FakeSpeaker:
    def __init__(self) -> None:
        self.played: list[RenderedSpeech | None] = []

    def render(self, text: str) -> RenderedSpeech:
        return RenderedSpeech(text, samples=[0.0], sample_rate=16000)

    def play(self, rendered: RenderedSpeech | None) -> None:
        self.played.append(rendered)

    def close(self) -> None:
        pass


def wait_until(predicate, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Timed out waiting for background work")


class BidirectionalFaultIsolationIntegrationTests(unittest.TestCase):
    def _build_direction(self, label: str, source: str, target: str, transcribe_side_effect):
        config = AppConfig(
            translation=TranslationSettings(engine="identity", source_language=source, target_language=target)
        )
        pipeline = LocalTranslatorPipeline(config)
        speaker = FakeSpeaker()
        patches = [
            patch.object(pipeline, "_print_audio_route"),
            patch.object(pipeline, "_get_speaker", return_value=speaker),
            patch.object(pipeline, "_transcribe_audio_if_safe", side_effect=transcribe_side_effect),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        direction = Direction(
            label=label,
            run=lambda stop, p=pipeline, l=label: p.run_prepared(
                stop_event=stop, label=l, chunker_mode="fixed"
            ),
            close=pipeline.close,
        )
        return direction, speaker

    def test_a_recognizer_crash_in_one_direction_leaves_the_other_running(self) -> None:
        healthy_calls: list[int] = []

        def healthy_transcribe(_audio):
            healthy_calls.append(1)
            return TranscriptResult(
                text=f"phrase {len(healthy_calls)}", language="en", duration_seconds=0.1, inference_seconds=0.01
            )

        broken_calls = {"count": 0}

        def broken_transcribe(_audio):
            broken_calls["count"] += 1
            if broken_calls["count"] > 2:
                # Simulate the recognizer crashing mid-session, after it had
                # already handled a couple of phrases successfully.
                raise RuntimeError("recognizer crashed")
            return TranscriptResult(
                text="ok", language="de", duration_seconds=0.1, inference_seconds=0.01
            )

        broken, _broken_speaker = self._build_direction("DE->EN", "de", "en", broken_transcribe)
        healthy, _healthy_speaker = self._build_direction("EN->DE", "en", "de", healthy_transcribe)

        warnings: list[str] = []
        session = BidirectionalSession([broken, healthy], on_warning=warnings.append, join_timeout=3.0)

        runner = Thread(target=session.run)
        with (
            patch("live_translator.pipeline.record_mono", return_value=[0.0] * 16000),
            redirect_stdout(io.StringIO()),
        ):
            runner.start()
            try:
                # The broken direction fails and is reported, by itself.
                wait_until(lambda: any("DE->EN" in w and "ended early" in w for w in warnings))
                wait_until(lambda: not session.is_running("DE->EN"))

                # The session process does not exit: it is still alive, and
                # the healthy direction is still the one running.
                self.assertTrue(runner.is_alive())
                self.assertTrue(session.is_running("EN->DE"))

                # New phrases keep arriving on the healthy direction for the
                # remainder of the test, well past the point of failure.
                calls_at_failure = len(healthy_calls)
                wait_until(lambda: len(healthy_calls) > calls_at_failure + 5)
                self.assertTrue(session.is_running("EN->DE"))
                self.assertTrue(runner.is_alive())

                # Only the broken direction was ever reported as failed.
                self.assertFalse(any("EN->DE" in w and "ended early" in w for w in warnings))
            finally:
                session.stop()
                runner.join(timeout=5.0)

        self.assertFalse(runner.is_alive())

    def test_restart_recovers_the_crashed_direction_while_the_session_keeps_running(self) -> None:
        def broken_transcribe(_audio):
            raise RuntimeError("model crashed")

        healthy_calls: list[int] = []

        def healthy_transcribe(_audio):
            healthy_calls.append(1)
            return TranscriptResult(text="ok", language="en", duration_seconds=0.1, inference_seconds=0.01)

        broken, _ = self._build_direction("DE->EN", "de", "en", broken_transcribe)
        healthy, _ = self._build_direction("EN->DE", "en", "de", healthy_transcribe)

        warnings: list[str] = []
        session = BidirectionalSession([broken, healthy], on_warning=warnings.append, join_timeout=3.0)

        recovered_calls: list[int] = []

        def recovered_transcribe(_audio):
            recovered_calls.append(1)
            return TranscriptResult(text="recovered", language="de", duration_seconds=0.1, inference_seconds=0.01)

        runner = Thread(target=session.run)
        with (
            patch("live_translator.pipeline.record_mono", return_value=[0.0] * 16000),
            redirect_stdout(io.StringIO()),
        ):
            runner.start()
            try:
                wait_until(lambda: not session.is_running("DE->EN"))

                recovered_direction, _ = self._build_direction("DE->EN", "de", "en", recovered_transcribe)
                session.restart(recovered_direction)

                wait_until(lambda: len(recovered_calls) > 3)
                self.assertTrue(session.is_running("DE->EN"))
                self.assertTrue(session.is_running("EN->DE"))
                self.assertTrue(runner.is_alive())
            finally:
                session.stop()
                runner.join(timeout=5.0)

        self.assertFalse(runner.is_alive())


if __name__ == "__main__":
    unittest.main()
