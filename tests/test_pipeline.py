import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from live_translator.config import AppConfig, RealtimeSettings
from live_translator.asr.base import TranscriptResult
from live_translator.pipeline import LocalTranslatorPipeline
from live_translator.tts.speaker import RenderedSpeech


class FakeSpeaker:
    def __init__(self) -> None:
        self.rendered: list[str] = []
        self.played: list[RenderedSpeech | None] = []
        self.spoken: list[str] = []

    def render(self, text: str) -> RenderedSpeech:
        self.rendered.append(text)
        return RenderedSpeech(text, samples=[0.0], sample_rate=16000)

    def play(self, rendered: RenderedSpeech | None) -> None:
        self.played.append(rendered)

    def speak(self, text: str) -> None:
        self.spoken.append(text)


class PipelineTests(unittest.TestCase):
    def test_realtime_queue_sizes_come_from_config(self) -> None:
        pipeline = LocalTranslatorPipeline(
            AppConfig(realtime=RealtimeSettings(recognition_queue_size=3, playback_queue_size=2))
        )

        workers = pipeline._create_realtime_workers(object(), FakeSpeaker(), None)

        self.assertEqual(workers._segments.maxsize, 3)
        self.assertEqual(workers._playback.maxsize, 2)

    def test_recognition_worker_synthesizes_so_playback_only_plays(self) -> None:
        """Synthesis must happen in the recognition worker. If it drifts back into
        the playback worker, that worker again costs synthesis plus playback per
        phrase, which is more than phrases take to arrive, and speech gets dropped."""
        pipeline = LocalTranslatorPipeline(AppConfig())
        speaker = FakeSpeaker()

        class FakeTranslator:
            def translate(self, text: str) -> str:
                return f"target: {text}"

        class FakeSegment:
            number = 1
            audio = [0.0] * 16000
            captured_at = 0.0

        transcript = TranscriptResult(
            text="source", language="en", duration_seconds=1.0, inference_seconds=0.1
        )
        with patch.object(pipeline, "_transcribe_audio_if_safe", return_value=transcript):
            result = pipeline._process_live_segment(
                FakeSegment(), FakeTranslator(), speaker, None
            )

        self.assertEqual(speaker.rendered, ["target: source"])
        self.assertIsInstance(result, RenderedSpeech)
        self.assertEqual(result.text, "target: source")
        self.assertEqual(speaker.played, [])  # playback is the other worker's job

    def test_skipped_segment_renders_nothing(self) -> None:
        pipeline = LocalTranslatorPipeline(AppConfig())
        speaker = FakeSpeaker()

        class FakeSegment:
            number = 2
            audio = [0.0] * 16000
            captured_at = 0.0

        with patch.object(pipeline, "_transcribe_audio_if_safe", return_value=None):
            result = pipeline._process_live_segment(FakeSegment(), object(), speaker, None)

        self.assertIsNone(result)
        self.assertEqual(speaker.rendered, [])

    def test_low_confidence_segment_is_translated_but_not_rendered(self) -> None:
        """A flagged segment is still shown in full (see PrintTranslationTests)
        and still translated -- only voicing it is skipped, since the
        recognizer itself is telling us this one might be wrong and a wrong
        sentence heard aloud costs more than one merely read."""
        pipeline = LocalTranslatorPipeline(AppConfig())
        speaker = FakeSpeaker()

        class FakeTranslator:
            def translate(self, text: str) -> str:
                return f"target: {text}"

        class FakeSegment:
            number = 3
            audio = [0.0] * 16000
            captured_at = 0.0

        transcript = TranscriptResult(
            text="unsicher",
            language="de",
            duration_seconds=1.0,
            inference_seconds=0.1,
            low_confidence=True,
        )
        with patch.object(pipeline, "_transcribe_audio_if_safe", return_value=transcript):
            result = pipeline._process_live_segment(
                FakeSegment(), FakeTranslator(), speaker, None
            )

        self.assertIsNone(result)
        self.assertEqual(speaker.rendered, [])


class TranslateOnceTests(unittest.TestCase):
    """translate_once (the one-shot debug/testing command) follows the same
    policy as the live path: a flagged transcript is still translated and
    printed, just not spoken."""

    def _run(self, *, low_confidence: bool) -> FakeSpeaker:
        pipeline = LocalTranslatorPipeline(AppConfig())
        speaker = FakeSpeaker()

        class FakeTranslator:
            def translate(self, text: str) -> str:
                return f"target: {text}"

        transcript = TranscriptResult(
            text="source",
            language="en",
            duration_seconds=1.0,
            inference_seconds=0.1,
            low_confidence=low_confidence,
        )
        with (
            patch.object(pipeline, "prepare"),
            patch.object(pipeline, "_get_translator", return_value=FakeTranslator()),
            patch.object(pipeline, "_get_speaker", return_value=speaker),
            patch("live_translator.pipeline.record_mono", return_value=[0.0] * 16000),
            patch.object(pipeline, "_transcribe_audio_if_safe", return_value=transcript),
        ):
            pipeline.translate_once()
        return speaker

    def test_speaks_a_confident_translation(self) -> None:
        speaker = self._run(low_confidence=False)
        self.assertEqual(speaker.spoken, ["target: source"])

    def test_does_not_speak_a_low_confidence_translation(self) -> None:
        speaker = self._run(low_confidence=True)
        self.assertEqual(speaker.spoken, [])


class PrintTranslationTests(unittest.TestCase):
    """low_confidence is a marker on an otherwise fully shown segment, not a
    second rejection -- both source and target text always print in full."""

    def test_marks_both_lines_when_flagged(self) -> None:
        """The marker used to appear on the source line only -- someone
        reading just the target-language line, or only hearing it spoken (see
        PipelineTests.test_low_confidence_segment_is_translated_but_not_rendered
        for why it isn't spoken), would never see any warning at all."""
        pipeline = LocalTranslatorPipeline(AppConfig())
        buffer = io.StringIO()

        with redirect_stdout(buffer):
            pipeline._print_translation("unsicherer Satz", "uncertain sentence", low_confidence=True)

        lines = buffer.getvalue().splitlines()
        source_line = next(line for line in lines if "unsicherer Satz" in line)
        target_line = next(line for line in lines if "uncertain sentence" in line)
        self.assertIn("[low confidence, not spoken]", source_line)
        self.assertIn("[low confidence, not spoken]", target_line)

    def test_no_marker_when_not_flagged(self) -> None:
        pipeline = LocalTranslatorPipeline(AppConfig())
        buffer = io.StringIO()

        with redirect_stdout(buffer):
            pipeline._print_translation("klarer Satz", "clear sentence", low_confidence=False)

        self.assertNotIn("[low confidence", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
