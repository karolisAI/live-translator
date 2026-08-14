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
        self.audio: list[object] = []

    def recognize(self, audio, **kwargs):
        self.calls.append(kwargs)
        self.audio.append(audio)
        return self._result


class FlakyModel:
    """Emits nothing until the Nth call, like a clip that needs a retry."""

    def __init__(self, results: list[FakeTimestampedResult]) -> None:
        self._results = results
        self.calls: list[dict] = []
        self.audio: list[object] = []

    def recognize(self, audio, **kwargs):
        self.calls.append(kwargs)
        self.audio.append(audio)
        index = min(len(self.calls) - 1, len(self._results) - 1)
        return self._results[index]


def build(result: FakeTimestampedResult, model=None, **overrides) -> ParakeetRecognizer:
    """Build a recognizer around a fake model.

    `__init__` exists to load a real ONNX model, so it is bypassed rather than
    given a test-only injection hook on the public API.
    """
    recognizer = ParakeetRecognizer.__new__(ParakeetRecognizer)
    recognizer.language = overrides.get("language")
    recognizer.min_chars = overrides.get("min_chars", 2)
    recognizer.log_prob_threshold = overrides.get("log_prob_threshold", -1.3)
    recognizer.compression_ratio_threshold = overrides.get("compression_ratio_threshold", 2.4)
    # Off unless a test asks for it, so the retry passes cannot quietly change
    # what the other tests are asserting about a single recognize() call.
    recognizer.recover_empty = overrides.get("recover_empty", False)
    # 0.0 so recovery tests exercise the retry itself rather than the length
    # gate; the gate has its own tests below.
    recognizer.min_recovery_seconds = overrides.get("min_recovery_seconds", 0.0)
    recognizer._model = FakeModel(result) if model is None else model
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


class RecoveryTests(unittest.TestCase):
    """The decoder sometimes emits nothing for audio that does contain speech."""

    def _flaky(self, texts, **overrides):
        results = [FakeTimestampedResult(t, [-0.01]) for t in texts]
        model = FlakyModel(results)
        return build(results[0], model=model, recover_empty=True, **overrides), model

    def test_retries_when_the_first_pass_returns_nothing(self) -> None:
        recognizer, model = self._flaky(["", "recovered text"])

        transcript = recognizer.transcribe(np.zeros(16000, dtype=np.float32), 16000)

        self.assertEqual(transcript.text, "recovered text")
        self.assertFalse(transcript.rejected)
        self.assertEqual(transcript.recovered_by, "pad")
        self.assertEqual(len(model.calls), 2)

    def test_falls_through_to_the_second_pass(self) -> None:
        recognizer, model = self._flaky(["", "", "found on gain"])

        transcript = recognizer.transcribe(np.zeros(16000, dtype=np.float32), 16000)

        self.assertEqual(transcript.text, "found on gain")
        self.assertEqual(transcript.recovered_by, "gain")
        self.assertEqual(len(model.calls), 3)

    def test_gives_up_and_still_reports_no_speech(self) -> None:
        # Genuine silence stays silent: every pass returns nothing, so the
        # recogniser must not invent an answer.
        recognizer, model = self._flaky(["", "", ""])

        transcript = recognizer.transcribe(np.zeros(16000, dtype=np.float32), 16000)

        self.assertEqual(transcript.text, "")
        self.assertTrue(transcript.rejected)
        self.assertEqual(transcript.rejection_reason, "no_speech")
        self.assertIsNone(transcript.recovered_by)
        self.assertEqual(len(model.calls), 3)

    def test_no_retry_when_the_first_pass_already_has_text(self) -> None:
        recognizer, model = self._flaky(["straight away", "should not be reached"])

        transcript = recognizer.transcribe(np.zeros(16000, dtype=np.float32), 16000)

        self.assertEqual(transcript.text, "straight away")
        self.assertIsNone(transcript.recovered_by)
        self.assertEqual(len(model.calls), 1)

    def test_disabled_by_default_construction_flag(self) -> None:
        recognizer, model = self._flaky(["", "recovered"], )
        recognizer.recover_empty = False

        transcript = recognizer.transcribe(np.zeros(16000, dtype=np.float32), 16000)

        self.assertEqual(transcript.text, "")
        self.assertEqual(transcript.rejection_reason, "no_speech")
        self.assertEqual(len(model.calls), 1)

    def test_retries_keep_the_language_option(self) -> None:
        recognizer, model = self._flaky(["", "wieder da"], language="de")

        recognizer.transcribe(np.zeros(16000, dtype=np.float32), 16000)

        self.assertEqual([c["language"] for c in model.calls], ["de", "de"])

    def test_passes_alter_the_audio_they_resubmit(self) -> None:
        recognizer, model = self._flaky(["", "", "text"])
        audio = np.full(1600, 0.4, dtype=np.float32)

        recognizer.transcribe(audio, 16000)

        first, padded, amplified = model.audio
        self.assertEqual(len(first), 1600)
        self.assertGreater(len(padded), len(first))          # silence margins added
        self.assertAlmostEqual(float(np.max(amplified)), 0.8, places=5)  # gain applied

    def test_amplified_audio_stays_in_range(self) -> None:
        recognizer, model = self._flaky(["", "", "text"])

        recognizer.transcribe(np.full(1600, 0.9, dtype=np.float32), 16000)

        self.assertLessEqual(float(np.max(np.abs(model.audio[-1]))), 1.0)


class RecoveryLengthGateTests(unittest.TestCase):
    """Short clips are left alone: retrying them produced noise, not words."""

    def _flaky(self, **overrides):
        results = [FakeTimestampedResult("", [-0.01]), FakeTimestampedResult("late text", [-0.01])]
        model = FlakyModel(results)
        recognizer = build(results[0], model=model, recover_empty=True, **overrides)
        return recognizer, model

    def test_skips_recovery_below_the_threshold(self) -> None:
        recognizer, model = self._flaky(min_recovery_seconds=3.0)

        transcript = recognizer.transcribe(np.zeros(16000, dtype=np.float32), 16000)  # 1.0s

        self.assertEqual(transcript.text, "")
        self.assertEqual(transcript.rejection_reason, "no_speech")
        self.assertEqual(len(model.calls), 1)

    def test_recovers_at_or_above_the_threshold(self) -> None:
        recognizer, model = self._flaky(min_recovery_seconds=3.0)

        transcript = recognizer.transcribe(np.zeros(48000, dtype=np.float32), 16000)  # 3.0s

        self.assertEqual(transcript.text, "late text")
        self.assertEqual(transcript.recovered_by, "pad")

    def test_zero_threshold_recovers_everything(self) -> None:
        recognizer, model = self._flaky(min_recovery_seconds=0.0)

        transcript = recognizer.transcribe(np.zeros(1600, dtype=np.float32), 16000)  # 0.1s

        self.assertEqual(transcript.text, "late text")


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
