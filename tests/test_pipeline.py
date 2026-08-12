import unittest
from unittest.mock import patch

from live_translator.config import AppConfig, AsrSettings, RealtimeSettings
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

    def test_get_asr_dispatches_to_parakeet_when_configured(self) -> None:
        pipeline = LocalTranslatorPipeline(AppConfig(asr=AsrSettings(engine="parakeet")))

        with patch("live_translator.pipeline.ParakeetAsr") as fake_parakeet_cls:
            asr = pipeline._get_asr()

        fake_parakeet_cls.assert_called_once_with(pipeline._config.asr)
        self.assertIs(asr, fake_parakeet_cls.return_value)

    def test_get_asr_dispatches_to_faster_whisper_by_default(self) -> None:
        pipeline = LocalTranslatorPipeline(AppConfig())

        with patch("live_translator.pipeline.FasterWhisperAsr") as fake_whisper_cls:
            asr = pipeline._get_asr()

        fake_whisper_cls.assert_called_once_with(pipeline._config.asr)
        self.assertIs(asr, fake_whisper_cls.return_value)


if __name__ == "__main__":
    unittest.main()
