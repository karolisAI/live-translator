import io
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from live_translator.config import AppConfig, AsrSettings, RealtimeSettings
from live_translator.asr.base import TranscriptResult
from live_translator.errors import ModelNotPrepared
from live_translator.pipeline import LocalTranslatorPipeline
from live_translator.tts.speaker import RenderedSpeech


class FakeSpeaker:
    def __init__(self) -> None:
        self.rendered: list[str] = []
        self.played: list[RenderedSpeech | None] = []

    def render(self, text: str) -> RenderedSpeech:
        self.rendered.append(text)
        return RenderedSpeech(text, samples=[0.0], sample_rate=16000)

    def play(self, rendered: RenderedSpeech | None) -> None:
        self.played.append(rendered)


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


class PrintTranslationTests(unittest.TestCase):
    """low_confidence is a marker on an otherwise fully shown segment, not a
    second rejection -- both source and target text always print in full."""

    def test_marks_low_confidence_source_line(self) -> None:
        pipeline = LocalTranslatorPipeline(AppConfig())
        buffer = io.StringIO()

        with redirect_stdout(buffer):
            pipeline._print_translation("unsicherer Satz", "uncertain sentence", low_confidence=True)

        output = buffer.getvalue()
        self.assertIn("[low confidence]", output)
        self.assertIn("unsicherer Satz", output)
        self.assertIn("uncertain sentence", output)

    def test_no_marker_when_not_flagged(self) -> None:
        pipeline = LocalTranslatorPipeline(AppConfig())
        buffer = io.StringIO()

        with redirect_stdout(buffer):
            pipeline._print_translation("klarer Satz", "clear sentence", low_confidence=False)

        self.assertNotIn("[low confidence]", buffer.getvalue())


class OfflineStartupOrderTests(unittest.TestCase):
    """`loopback` opens the microphone only after `prepare()` returns, so an
    unprepared machine has to fail while there is still no meeting audio in the
    process at all. Asserting the ordering is the only way to keep it: both
    calls succeed independently, and only their sequence carries the property.
    """

    def test_missing_model_fails_before_any_audio_is_captured(self) -> None:
        with TemporaryDirectory() as tmp:
            config = replace(
                AppConfig(), asr=AsrSettings(model_dir=str(Path(tmp) / "never-prepared"))
            )
            pipeline = LocalTranslatorPipeline(config)

            with patch("live_translator.pipeline.record_mono") as fake_record:
                with redirect_stdout(io.StringIO()):
                    with self.assertRaises(ModelNotPrepared):
                        pipeline.prepare()

            fake_record.assert_not_called()


if __name__ == "__main__":
    unittest.main()
