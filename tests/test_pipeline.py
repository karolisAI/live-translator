import io
import unittest
from contextlib import redirect_stdout

from live_translator.config import AppConfig, RealtimeSettings
from live_translator.pipeline import LocalTranslatorPipeline


class FakeSpeaker:
    def speak(self, _text: str) -> None:
        return None


class PipelineTests(unittest.TestCase):
    def test_realtime_queue_sizes_come_from_config(self) -> None:
        pipeline = LocalTranslatorPipeline(
            AppConfig(realtime=RealtimeSettings(recognition_queue_size=3, playback_queue_size=2))
        )

        workers = pipeline._create_realtime_workers(object(), FakeSpeaker(), None)

        self.assertEqual(workers._segments.maxsize, 3)
        self.assertEqual(workers._playback.maxsize, 2)


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


if __name__ == "__main__":
    unittest.main()
