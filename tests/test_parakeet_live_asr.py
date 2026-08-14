import unittest
from unittest.mock import patch

from live_translator.asr.parakeet_live_engine import ParakeetLiveAsr
from live_translator.config import AsrSettings
from parakeet_live import Transcript


class ParakeetLiveAsrTests(unittest.TestCase):
    def _make(self, **overrides):
        settings = AsrSettings(engine="parakeet-live", **overrides)
        with patch("parakeet_live.ParakeetRecognizer") as fake_recognizer_cls:
            asr = ParakeetLiveAsr(settings)
        return asr, fake_recognizer_cls

    def test_rejects_non_parakeet_live_engine(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported ASR engine"):
            ParakeetLiveAsr(AsrSettings(engine="parakeet"))

    def test_constructs_recognizer_from_settings(self) -> None:
        _asr, fake_recognizer_cls = self._make(
            model="nemo-parakeet-tdt-0.6b-v3",
            compute_type="int8",
            device="cpu",
            cpu_threads=8,
            source_language="de",
            min_segment_chars=2,
            log_prob_threshold=-1.3,
            compression_ratio_threshold=2.4,
        )

        fake_recognizer_cls.assert_called_once_with(
            model="nemo-parakeet-tdt-0.6b-v3",
            quantization="int8",
            device="cpu",
            cpu_threads=8,
            language="de",
            min_chars=2,
            log_prob_threshold=-1.3,
            compression_ratio_threshold=2.4,
        )

    def test_transcribe_maps_accepted_transcript(self) -> None:
        asr, _ = self._make()
        asr._recognizer.transcribe.return_value = Transcript(
            text="hallo welt",
            language="de",
            duration_seconds=3.0,
            inference_seconds=0.5,
        )

        result = asr.transcribe([0.0] * 48000, 16000)

        self.assertEqual(result.text, "hallo welt")
        self.assertEqual(result.language, "de")
        self.assertEqual(result.duration_seconds, 3.0)
        self.assertEqual(result.inference_seconds, 0.5)
        self.assertEqual(result.rejected_segments, 0)
        self.assertEqual(result.rejection_reasons, ())

    def test_transcribe_maps_rejected_transcript(self) -> None:
        asr, _ = self._make()
        asr._recognizer.transcribe.return_value = Transcript(
            text="",
            language="en",
            duration_seconds=1.0,
            inference_seconds=0.1,
            rejected=True,
            rejection_reason="no_speech",
        )

        result = asr.transcribe([0.0] * 16000, 16000)

        self.assertEqual(result.text, "")
        self.assertEqual(result.rejected_segments, 1)
        self.assertEqual(result.rejection_reasons, ("no_speech",))


if __name__ == "__main__":
    unittest.main()
