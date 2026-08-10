import unittest
from dataclasses import dataclass

import numpy as np

from parakeet_live import ParakeetRecognizer, compression_ratio


@dataclass
class FakeTimestampedResult:
    text: str
    logprobs: object = None


class FakeModel:
    """Stands in for onnx_asr's timestamped adapter."""

    def __init__(self, result: FakeTimestampedResult) -> None:
        self._result = result
        self.calls: list[dict] = []

    def recognize(self, audio, **kwargs):
        self.calls.append(kwargs)
        return self._result


def build(result: FakeTimestampedResult, **overrides) -> ParakeetRecognizer:
    """Build a recognizer around a fake model.

    `__init__` exists to load a real ONNX model, so it is bypassed rather than
    given a test-only injection hook on the public API.
    """
    recognizer = ParakeetRecognizer.__new__(ParakeetRecognizer)
    recognizer.language = overrides.get("language")
    recognizer.min_chars = overrides.get("min_chars", 2)
    recognizer.log_prob_threshold = overrides.get("log_prob_threshold", -1.3)
    recognizer.compression_ratio_threshold = overrides.get("compression_ratio_threshold", 2.4)
    recognizer._model = FakeModel(result)
    return recognizer


class TranscribeTests(unittest.TestCase):
    def test_transcribes_and_reports_timings(self) -> None:
        recognizer = build(FakeTimestampedResult("Guten Morgen", [-0.01, -0.02]))

        transcript = recognizer.transcribe(np.zeros(16000, dtype=np.float32), 16000)

        self.assertEqual(transcript.text, "Guten Morgen")
        self.assertEqual(transcript.duration_seconds, 1.0)
        self.assertFalse(transcript.rejected)
        self.assertIsNone(transcript.rejection_reason)
        self.assertGreaterEqual(transcript.inference_seconds, 0.0)

    def test_passes_language_through(self) -> None:
        recognizer = build(FakeTimestampedResult("hallo", [-0.1]), language="de")

        transcript = recognizer.transcribe(np.zeros(1600, dtype=np.float32), 16000)

        self.assertEqual(recognizer._model.calls[0]["language"], "de")
        self.assertEqual(transcript.language, "de")

    def test_omits_language_when_unset(self) -> None:
        recognizer = build(FakeTimestampedResult("hallo", [-0.1]), language=None)

        recognizer.transcribe(np.zeros(1600, dtype=np.float32), 16000)

        self.assertNotIn("language", recognizer._model.calls[0])

    def test_per_call_language_overrides_the_instance_default(self) -> None:
        recognizer = build(FakeTimestampedResult("hello", [-0.1]), language="de")

        transcript = recognizer.transcribe(np.zeros(1600, dtype=np.float32), 16000, language="en")

        self.assertEqual(recognizer._model.calls[0]["language"], "en")
        self.assertEqual(transcript.language, "en")

    def test_one_recognizer_serves_both_directions(self) -> None:
        # The point of the per-call override: no second model load for the
        # reverse direction.
        recognizer = build(FakeTimestampedResult("text", [-0.1]))
        audio = np.zeros(1600, dtype=np.float32)

        recognizer.transcribe(audio, 16000, language="de")
        recognizer.transcribe(audio, 16000, language="en")

        self.assertEqual(
            [call["language"] for call in recognizer._model.calls], ["de", "en"]
        )

    def test_omitted_language_falls_back_to_the_instance_default(self) -> None:
        recognizer = build(FakeTimestampedResult("hallo", [-0.1]), language="de")

        transcript = recognizer.transcribe(np.zeros(1600, dtype=np.float32), 16000)

        self.assertEqual(recognizer._model.calls[0]["language"], "de")
        self.assertEqual(transcript.language, "de")

    def test_missing_logprobs_do_not_crash(self) -> None:
        recognizer = build(FakeTimestampedResult("hallo", None))

        self.assertEqual(
            recognizer.transcribe(np.zeros(1600, dtype=np.float32), 16000).text, "hallo"
        )


class RejectionTests(unittest.TestCase):
    def test_empty_output_is_rejected_as_no_speech(self) -> None:
        # Silence and noise make this model emit zero tokens.
        recognizer = build(FakeTimestampedResult("", []))

        transcript = recognizer.transcribe(np.zeros(16000, dtype=np.float32), 16000)

        self.assertEqual(transcript.text, "")
        self.assertTrue(transcript.rejected)
        self.assertEqual(transcript.rejection_reason, "no_speech")

    def test_rejects_low_average_logprob(self) -> None:
        recognizer = build(
            FakeTimestampedResult("murmeln", [-2.0, -3.0]), log_prob_threshold=-1.3
        )

        transcript = recognizer.transcribe(np.zeros(16000, dtype=np.float32), 16000)

        self.assertEqual(transcript.text, "")
        self.assertTrue(transcript.rejected)
        self.assertTrue(transcript.rejection_reason.startswith("avg_logprob="))

    def test_keeps_confident_output_at_same_threshold(self) -> None:
        recognizer = build(
            FakeTimestampedResult("klarer Satz", [-0.01, -0.02]), log_prob_threshold=-1.3
        )

        transcript = recognizer.transcribe(np.zeros(16000, dtype=np.float32), 16000)

        self.assertEqual(transcript.text, "klarer Satz")

    def test_rejects_short_output(self) -> None:
        recognizer = build(FakeTimestampedResult("a", [-0.01]), min_chars=2)

        transcript = recognizer.transcribe(np.zeros(16000, dtype=np.float32), 16000)

        self.assertEqual(transcript.rejection_reason, "short")

    def test_rejects_degenerate_repetition(self) -> None:
        recognizer = build(
            FakeTimestampedResult("ja " * 400, [-0.01]), compression_ratio_threshold=2.4
        )

        transcript = recognizer.transcribe(np.zeros(16000, dtype=np.float32), 16000)

        self.assertEqual(transcript.text, "")
        self.assertTrue(transcript.rejection_reason.startswith("compression_ratio="))

    def test_compression_ratio_flags_repetition(self) -> None:
        self.assertGreater(compression_ratio("ja " * 400), compression_ratio("ein normaler Satz"))


class QuantizationTests(unittest.TestCase):
    def test_full_precision_aliases_become_none(self) -> None:
        from parakeet_live.engine import _normalize_quantization

        for value in ("auto", "default", "float32", "fp32", "float", "none", " AUTO ", "", None):
            with self.subTest(value=value):
                self.assertIsNone(_normalize_quantization(value))

    def test_quantization_suffix_is_passed_through(self) -> None:
        from parakeet_live.engine import _normalize_quantization

        self.assertEqual(_normalize_quantization("int8"), "int8")
        self.assertEqual(_normalize_quantization(" INT8 "), "int8")


if __name__ == "__main__":
    unittest.main()
