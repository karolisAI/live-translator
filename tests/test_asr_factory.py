import unittest
from unittest.mock import patch

from live_translator.asr import create_asr
from live_translator.config import AsrSettings


class CreateAsrTests(unittest.TestCase):
    def test_dispatches_to_faster_whisper(self) -> None:
        settings = AsrSettings(engine="faster-whisper")
        with patch("live_translator.asr.FasterWhisperAsr") as fake_cls:
            asr = create_asr(settings)

        fake_cls.assert_called_once_with(settings)
        self.assertIs(asr, fake_cls.return_value)

    def test_dispatches_to_parakeet(self) -> None:
        settings = AsrSettings(engine="parakeet")
        with patch("live_translator.asr.ParakeetAsr") as fake_cls:
            asr = create_asr(settings)

        fake_cls.assert_called_once_with(settings)
        self.assertIs(asr, fake_cls.return_value)

    def test_dispatches_to_parakeet_live(self) -> None:
        settings = AsrSettings(engine="parakeet-live")
        with patch("live_translator.asr.ParakeetLiveAsr") as fake_cls:
            asr = create_asr(settings)

        fake_cls.assert_called_once_with(settings)
        self.assertIs(asr, fake_cls.return_value)

    def test_dispatch_is_case_insensitive(self) -> None:
        settings = AsrSettings(engine="Parakeet-Live")
        with patch("live_translator.asr.ParakeetLiveAsr") as fake_cls:
            create_asr(settings)

        fake_cls.assert_called_once_with(settings)

    def test_rejects_unknown_engine(self) -> None:
        settings = AsrSettings(engine="bogus")
        with self.assertRaisesRegex(ValueError, "Unsupported ASR engine"):
            create_asr(settings)


if __name__ == "__main__":
    unittest.main()
