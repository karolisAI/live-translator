import unittest

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


if __name__ == "__main__":
    unittest.main()
