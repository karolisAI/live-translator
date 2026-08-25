import unittest
from dataclasses import dataclass
from unittest.mock import patch

import numpy as np

from live_translator.asr.recognizer import ParakeetRecognizer, compression_ratio
from live_translator.errors import UnsupportedModel


@dataclass
class FakeTimestampedResult:
    text: str
    logprobs: object = None
    timestamps: object = None


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


class ScriptedModel:
    """Returns each result in turn, then nothing.

    Distinct from FlakyModel, which repeats its last result forever: a tail test
    needs the model to run out the way a real decoder stops finding new words.
    """

    def __init__(self, results: list[FakeTimestampedResult]) -> None:
        self._results = list(results)
        self.calls: list[dict] = []
        self.audio: list[object] = []

    def recognize(self, audio, **kwargs):
        self.calls.append(kwargs)
        self.audio.append(audio)
        index = len(self.calls) - 1
        if index < len(self._results):
            return self._results[index]
        return FakeTimestampedResult("", [], None)


def build(result: FakeTimestampedResult, model=None, **overrides) -> ParakeetRecognizer:
    """Build a recognizer around a fake model.

    `__init__` exists to load a real ONNX model, so it is bypassed rather than
    given a test-only injection hook on the public API.
    """
    recognizer = ParakeetRecognizer.__new__(ParakeetRecognizer)
    recognizer.language = overrides.get("language")
    recognizer.min_chars = overrides.get("min_chars", 2)
    recognizer.log_prob_threshold = overrides.get("log_prob_threshold", -1.3)
    recognizer.flag_log_prob_threshold = overrides.get("flag_log_prob_threshold", None)
    recognizer.compression_ratio_threshold = overrides.get("compression_ratio_threshold", 2.4)
    # Off unless a test asks for it, so the retry passes cannot quietly change
    # what the other tests are asserting about a single recognize() call.
    recognizer.recover_empty = overrides.get("recover_empty", False)
    # 0.0 so recovery tests exercise the retry itself rather than the length
    # gate; the gate has its own tests below.
    recognizer.min_recovery_seconds = overrides.get("min_recovery_seconds", 0.0)
    # Off for the same reason as recover_empty: a test asserting on one
    # recognize() call should not have tail passes appended underneath it.
    recognizer.recover_gaps = overrides.get("recover_gaps", False)
    recognizer.min_gap_seconds = overrides.get("min_gap_seconds", 1.0)
    recognizer.max_gap_passes = overrides.get("max_gap_passes", 3)
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


class LowConfidenceFlagTests(unittest.TestCase):
    """flag_log_prob_threshold marks an accepted transcript rather than
    rejecting it -- an opt-in signal for a caller that wants to warn on
    uncertain output instead of discarding it before translation."""

    def test_disabled_by_default(self) -> None:
        # No flag_log_prob_threshold passed to build() -> None, the default.
        recognizer = build(FakeTimestampedResult("unsicherer Satz", [-0.5]))

        transcript = recognizer.transcribe(np.zeros(16000, dtype=np.float32), 16000)

        self.assertFalse(transcript.rejected)
        self.assertFalse(transcript.low_confidence)
        self.assertEqual(transcript.avg_logprob, -0.5)

    def test_flags_accepted_text_below_the_flag_threshold(self) -> None:
        recognizer = build(
            FakeTimestampedResult("unsicherer Satz", [-0.5]),
            log_prob_threshold=-1.3,
            flag_log_prob_threshold=-0.3,
        )

        transcript = recognizer.transcribe(np.zeros(16000, dtype=np.float32), 16000)

        self.assertFalse(transcript.rejected)
        self.assertEqual(transcript.text, "unsicherer Satz")
        self.assertTrue(transcript.low_confidence)
        self.assertEqual(transcript.avg_logprob, -0.5)

    def test_does_not_flag_confident_text(self) -> None:
        recognizer = build(
            FakeTimestampedResult("klarer Satz", [-0.01]),
            flag_log_prob_threshold=-0.3,
        )

        transcript = recognizer.transcribe(np.zeros(16000, dtype=np.float32), 16000)

        self.assertFalse(transcript.low_confidence)

    def test_rejected_text_is_never_also_flagged(self) -> None:
        # Below both thresholds: log_prob_threshold rejects first, so
        # low_confidence should never fire on top of an already-rejected
        # (empty-text) result.
        recognizer = build(
            FakeTimestampedResult("murmeln", [-2.0]),
            log_prob_threshold=-1.3,
            flag_log_prob_threshold=-0.3,
        )

        transcript = recognizer.transcribe(np.zeros(16000, dtype=np.float32), 16000)

        self.assertTrue(transcript.rejected)
        self.assertFalse(transcript.low_confidence)


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
        self.assertEqual(len(model.calls), 4)  # the first try, then all three passes

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


def speech(seconds: float, sample_rate: int = 16000, level: float = 0.2) -> np.ndarray:
    """Audio loud enough to clear the recogniser's energy gates."""
    return np.full(int(seconds * sample_rate), level, dtype=np.float32)


class TailRecoveryTests(unittest.TestCase):
    """The decoder can stop part way through a segment and never resume.

    The measured shape of that failure is a first pass whose last token sits
    seconds before the end of the audio. These tests script exactly that, so
    what is under test is the recogniser's response to the defect rather than
    the model that causes it.
    """

    def _scripted(self, results, **overrides):
        model = ScriptedModel(results)
        overrides.setdefault("recover_gaps", True)
        return build(results[0], model=model, **overrides), model

    def test_decodes_the_tail_the_first_pass_skipped(self) -> None:
        recognizer, model = self._scripted([
            FakeTimestampedResult("circus and things.", [-0.01], [0.4, 1.28]),
            FakeTimestampedResult("They don't look happy to me.", [-0.02], [0.2, 2.96]),
        ])

        transcript = recognizer.transcribe(speech(5.01), 16000)

        self.assertEqual(
            transcript.text, "circus and things. They don't look happy to me."
        )
        self.assertEqual(transcript.recovered_by, "tail")
        self.assertEqual(len(model.calls), 2)

    def test_reports_how_far_the_decode_reached(self) -> None:
        recognizer, _ = self._scripted([
            FakeTimestampedResult("opening", [-0.01], [0.2, 1.2]),
            FakeTimestampedResult("and the rest", [-0.01], [3.5]),
        ])

        transcript = recognizer.transcribe(speech(5.01), 16000)

        # 1.2 - 0.16 backoff, then 3.5 further into the re-decoded piece.
        self.assertAlmostEqual(transcript.covered_seconds, 4.54, places=2)

    def test_keeps_going_until_the_audio_is_covered(self) -> None:
        recognizer, model = self._scripted([
            FakeTimestampedResult("first", [-0.01], [0.5]),
            FakeTimestampedResult("second", [-0.01], [1.5]),
            FakeTimestampedResult("third", [-0.01], [1.5]),
        ])

        transcript = recognizer.transcribe(speech(6.0), 16000)

        self.assertEqual(transcript.text, "first second third")
        self.assertEqual(transcript.recovered_by, "tail+tail")

    def test_stops_at_max_gap_passes(self) -> None:
        recognizer, model = self._scripted(
            [FakeTimestampedResult(f"word {i}", [-0.01], [0.2, 1.5]) for i in range(6)],
            max_gap_passes=2,
        )

        recognizer.transcribe(speech(30.0), 16000)

        self.assertEqual(len(model.calls), 3)  # first pass plus two tails

    def test_leaves_trailing_silence_alone(self) -> None:
        # Every segment ends on a little silence; chasing it would spend an
        # inference per utterance to recover nothing.
        recognizer, model = self._scripted([
            FakeTimestampedResult("a complete sentence.", [-0.01], [0.4, 4.6])
        ])

        transcript = recognizer.transcribe(speech(5.01), 16000)

        self.assertEqual(transcript.text, "a complete sentence.")
        self.assertIsNone(transcript.recovered_by)
        self.assertEqual(len(model.calls), 1)

    def test_does_not_interrogate_a_quiet_tail(self) -> None:
        recognizer, model = self._scripted([
            FakeTimestampedResult("spoken then silence", [-0.01], [0.2, 1.0])
        ])
        audio = np.concatenate([speech(1.0), np.zeros(16000 * 4, dtype=np.float32)])

        recognizer.transcribe(audio, 16000)

        self.assertEqual(len(model.calls), 1)

    def test_stops_when_a_pass_reaches_no_further(self) -> None:
        # A tail decode can stall in turn. Without this guard the same samples
        # would be resubmitted until the pass limit ran out.
        recognizer, model = self._scripted([
            FakeTimestampedResult("opening", [-0.01], [0.2, 1.0]),
            FakeTimestampedResult("nothing new", [-0.01], [0.0]),
        ])

        transcript = recognizer.transcribe(speech(5.01), 16000)

        self.assertEqual(transcript.text, "opening")
        self.assertEqual(len(model.calls), 2)

    def test_does_not_repeat_a_word_across_the_seam(self) -> None:
        # The tail decode starts before the last token, so it can transcribe
        # that word twice. Appending it would trade a deletion for an insertion.
        recognizer, _ = self._scripted([
            FakeTimestampedResult("I can take the stairs", [-0.01], [0.2, 1.0]),
            FakeTimestampedResult("the stairs if I can.", [-0.01], [3.0]),
        ])

        transcript = recognizer.transcribe(speech(5.01), 16000)

        self.assertEqual(transcript.text, "I can take the stairs if I can.")

    def test_seam_repetition_check_ignores_case_and_punctuation(self) -> None:
        recognizer, _ = self._scripted([
            FakeTimestampedResult("we went to the circus", [-0.01], [0.2, 1.0]),
            FakeTimestampedResult("Circus, and things.", [-0.01], [3.0]),
        ])

        transcript = recognizer.transcribe(speech(5.01), 16000)

        self.assertEqual(transcript.text, "we went to the circus and things.")

    def test_a_mumbled_tail_is_refused_rather_than_averaged_away(self) -> None:
        # A weak fragment spliced into a confident result would hide inside the
        # combined average, so it is judged on its own before being joined.
        recognizer, _ = self._scripted([
            FakeTimestampedResult("clear opening", [-0.01], [0.2, 1.0]),
            FakeTimestampedResult("mumbled tail", [-4.0], [0.2, 3.0]),
        ])

        transcript = recognizer.transcribe(speech(5.01), 16000)

        self.assertEqual(transcript.text, "clear opening")
        self.assertFalse(transcript.rejected)

    def test_an_accepted_tail_contributes_its_logprobs(self) -> None:
        recognizer, _ = self._scripted([
            FakeTimestampedResult("clear opening", [-0.01, -0.01], [0.2, 1.0]),
            FakeTimestampedResult("and the rest", [-0.5, -0.5], [0.2, 3.0]),
        ])

        transcript = recognizer.transcribe(speech(5.01), 16000)

        self.assertEqual(transcript.text, "clear opening and the rest")
        self.assertFalse(transcript.rejected)

    def test_disabled_leaves_the_truncation_in_place(self) -> None:
        recognizer, model = self._scripted(
            [
                FakeTimestampedResult("only the opening", [-0.01], [0.2, 1.0]),
                FakeTimestampedResult("unreached", [-0.01], [3.0]),
            ],
            recover_gaps=False,
        )

        transcript = recognizer.transcribe(speech(5.01), 16000)

        self.assertEqual(transcript.text, "only the opening")
        self.assertEqual(len(model.calls), 1)

    def test_a_model_without_timestamps_still_works(self) -> None:
        # onnx-asr only reports timestamps through its timestamped adapter.
        # Without them there is no coverage to check, and the call must still
        # return its text rather than fail.
        recognizer, model = self._scripted([FakeTimestampedResult("plain text", [-0.01])])

        transcript = recognizer.transcribe(speech(5.01), 16000)

        self.assertEqual(transcript.text, "plain text")
        self.assertEqual(len(model.calls), 1)


class LeadRecoveryTests(unittest.TestCase):
    """The same stall can leave a gap in front of the first token."""

    def _scripted(self, results, **overrides):
        model = ScriptedModel(results)
        overrides.setdefault("recover_gaps", True)
        return build(results[0], model=model, **overrides), model

    def test_decodes_a_lead_in_the_first_pass_skipped(self) -> None:
        recognizer, model = self._scripted([
            FakeTimestampedResult("I'll always take the stairs.", [-0.01], [1.52, 4.6]),
            FakeTimestampedResult("Hate getting inside lifts.", [-0.01], [0.2, 1.4]),
        ])

        transcript = recognizer.transcribe(speech(5.01), 16000)

        self.assertEqual(
            transcript.text, "Hate getting inside lifts. I'll always take the stairs."
        )
        self.assertEqual(transcript.recovered_by, "lead")

    def test_ignores_the_pre_roll_every_segment_starts_with(self) -> None:
        # Segments arrive with a fraction of a second of lead-in silence. That
        # is normal, and decoding it would cost an inference per utterance.
        recognizer, model = self._scripted([
            FakeTimestampedResult("a normal segment", [-0.01], [0.16, 4.6])
        ])

        recognizer.transcribe(speech(5.01), 16000)

        self.assertEqual(len(model.calls), 1)

    def test_does_not_interrogate_a_quiet_lead(self) -> None:
        recognizer, model = self._scripted([
            FakeTimestampedResult("late speech", [-0.01], [2.0, 4.6])
        ])
        audio = np.concatenate([np.zeros(16000 * 2, dtype=np.float32), speech(3.01)])

        recognizer.transcribe(audio, 16000)

        self.assertEqual(len(model.calls), 1)

    def test_a_lead_that_decodes_to_nothing_is_left_lost(self) -> None:
        # The perturbation passes were measured inventing sentences when applied
        # to a lead-in, so a silent lead gets one plain try and nothing more.
        recognizer, model = self._scripted([
            FakeTimestampedResult("the part it did get", [-0.01], [2.48, 4.6]),
            FakeTimestampedResult("", [-0.01], []),
        ], recover_empty=True)

        transcript = recognizer.transcribe(speech(5.01), 16000)

        self.assertEqual(transcript.text, "the part it did get")
        self.assertEqual(len(model.calls), 2)

    def test_does_not_repeat_a_word_across_the_seam(self) -> None:
        recognizer, _ = self._scripted([
            FakeTimestampedResult("lifts I'll always take the stairs", [-0.01], [1.52, 4.6]),
            FakeTimestampedResult("Hate getting inside lifts", [-0.01], [0.2, 1.4]),
        ])

        transcript = recognizer.transcribe(speech(5.01), 16000)

        self.assertEqual(
            transcript.text, "Hate getting inside lifts I'll always take the stairs"
        )

    def test_rejects_a_lead_the_model_is_not_confident_about(self) -> None:
        # Decoding the German intro music produced a fluent English sentence at
        # -1.07 mean logprob. Nothing else measured came close to that, so the
        # floor is what stops music being transcribed as speech.
        recognizer, _ = self._scripted([
            FakeTimestampedResult("Die wie Deutschlernen mit dem Fall.", [-0.01], [2.24, 4.6]),
            FakeTimestampedResult("They're going to be able to do it", [-1.07], [0.2, 2.0]),
        ])

        transcript = recognizer.transcribe(speech(5.01), 16000)

        self.assertEqual(transcript.text, "Die wie Deutschlernen mit dem Fall.")
        self.assertIsNone(transcript.recovered_by)

    def test_rejects_a_tail_the_model_is_not_confident_about(self) -> None:
        recognizer, _ = self._scripted([
            FakeTimestampedResult("a real clause", [-0.01], [0.2, 1.0]),
            FakeTimestampedResult("invented words", [-1.5], [0.2, 3.0]),
        ])

        transcript = recognizer.transcribe(speech(5.01), 16000)

        self.assertEqual(transcript.text, "a real clause")

    def test_a_model_without_logprobs_can_still_recover(self) -> None:
        recognizer, _ = self._scripted([
            FakeTimestampedResult("opening", None, [0.2, 1.0]),
            FakeTimestampedResult("and the rest", None, [0.2, 3.0]),
        ])

        transcript = recognizer.transcribe(speech(5.01), 16000)

        self.assertEqual(transcript.text, "opening and the rest")

    def test_recovered_lead_and_tail_are_both_reported(self) -> None:
        recognizer, _ = self._scripted([
            FakeTimestampedResult("middle", [-0.01], [1.5, 2.0]),
            FakeTimestampedResult("start", [-0.01], [0.2, 1.6]),
            FakeTimestampedResult("end", [-0.01], [0.2, 2.5]),
        ])

        transcript = recognizer.transcribe(speech(5.01), 16000)

        self.assertEqual(transcript.text, "start middle end")
        self.assertEqual(transcript.recovered_by, "lead+tail")


class TruncatedSegmentRegressionTests(unittest.TestCase):
    """The five segments this defect was found on, as scripted fixtures.

    Each case carries the measured head text and last-token time from the
    English clip, and the text a fresh decode of the leftover returned. Audio
    fixtures would be megabytes in a package that ships no data; these preserve
    what actually has to hold -- that a decode reaching only part way through a
    5.01 s segment ends up with the rest of the words appended.
    """

    CASES = {
        "051": (0.0, "", "Thought and reacts with automatic responses which enable us to either put up a fight or run."),
        "062": (3.76, "So have you got any phobias, Liz?", "I'm not sure."),
        "064": (3.52, "and injections. Even the thought of them makes me feel queasy.", "When I have to have a blood test."),
        "067": (3.76, "when I was little when I went to the doctor with my mum and my big sister.", "The doctor gave me a"),
        "072": (1.28, "circus and things.", "They don't look at all happy to me, even with a big painted smile."),
        "077": (3.52, "I'll always take the stairs if I can.", "I don't know."),
    }

    def test_every_truncated_segment_regains_its_tail(self) -> None:
        for name, (last, head, tail) in self.CASES.items():
            with self.subTest(segment=name):
                results = [
                    FakeTimestampedResult(head, [-0.01], [0.2, last] if head else None),
                    FakeTimestampedResult(tail, [-0.01], [4.6 - last]),
                ]
                recognizer = build(
                    results[0],
                    model=ScriptedModel(results),
                    recover_empty=True,
                    recover_gaps=True,
                )

                transcript = recognizer.transcribe(speech(5.01), 16000)

                self.assertIn(tail.split()[0], transcript.text)
                self.assertGreaterEqual(len(transcript.text.split()), len(tail.split()))
                self.assertFalse(transcript.rejected)

    def test_segment_051_is_recovered_by_a_pass_that_moves_the_window(self) -> None:
        # 051 decoded to nothing from the very first frame, and padding and gain
        # both failed on it. Only trimming the front moved it.
        results = [
            FakeTimestampedResult("", [-0.01]),
            FakeTimestampedResult("", [-0.01]),
            FakeTimestampedResult("", [-0.01]),
            FakeTimestampedResult("Thought and reacts with automatic responses.", [-0.01], [0.2, 4.5]),
        ]
        recognizer = build(
            results[0], model=ScriptedModel(results), recover_empty=True, recover_gaps=True
        )

        transcript = recognizer.transcribe(speech(5.01), 16000)

        self.assertTrue(transcript.text.startswith("Thought and reacts"))
        self.assertEqual(transcript.recovered_by, "trim")


class EmptyReasonTests(unittest.TestCase):
    """An empty result has to say which kind of empty it is."""

    def test_quiet_audio_is_reported_as_no_speech(self) -> None:
        recognizer = build(FakeTimestampedResult("", []))

        transcript = recognizer.transcribe(np.zeros(16000, dtype=np.float32), 16000)

        self.assertEqual(transcript.rejection_reason, "no_speech")

    def test_active_audio_that_decodes_to_nothing_is_a_failed_decode(self) -> None:
        recognizer = build(FakeTimestampedResult("", []))

        transcript = recognizer.transcribe(speech(5.01), 16000)

        self.assertTrue(transcript.rejected)
        self.assertEqual(transcript.rejection_reason, "decode_failed")


class QuantizationTests(unittest.TestCase):
    def test_full_precision_aliases_become_none(self) -> None:
        from live_translator.asr.recognizer import _normalize_quantization

        for value in ("auto", "default", "float32", "fp32", "float", "none", " AUTO ", "", None):
            with self.subTest(value=value):
                self.assertIsNone(_normalize_quantization(value))

    def test_quantization_suffix_is_passed_through(self) -> None:
        from live_translator.asr.recognizer import _normalize_quantization

        self.assertEqual(_normalize_quantization("int8"), "int8")
        self.assertEqual(_normalize_quantization(" INT8 "), "int8")


class ConcatLogprobsTests(unittest.TestCase):
    """A fragment appended without scores still contributes text, so the
    combined confidence must not claim data it doesn't have (PR #2 review:
    the old asymmetric version silently kept `first`'s scores when only
    `second` was missing, understating how much of the text was scored)."""

    def test_both_present_concatenates(self) -> None:
        from live_translator.asr.recognizer import _concat_logprobs

        self.assertEqual(_concat_logprobs([-0.1, -0.2], [-0.3]), [-0.1, -0.2, -0.3])

    def test_first_missing_returns_none(self) -> None:
        from live_translator.asr.recognizer import _concat_logprobs

        self.assertIsNone(_concat_logprobs(None, [-0.1, -0.2]))

    def test_second_missing_returns_none(self) -> None:
        from live_translator.asr.recognizer import _concat_logprobs

        self.assertIsNone(_concat_logprobs([-0.1, -0.2], None))


class SessionOptionsTests(unittest.TestCase):
    """cpu_threads -> onnxruntime SessionOptions is the only piece of __init__
    that runs without touching onnx_asr, so it's tested directly rather than
    through a full (mocked) recognizer construction."""

    def test_zero_or_negative_threads_leaves_options_unset(self) -> None:
        from live_translator.asr.recognizer import _session_options

        self.assertIsNone(_session_options(0))
        self.assertIsNone(_session_options(-1))

    def test_positive_threads_configures_intra_and_inter_op(self) -> None:
        from live_translator.asr.recognizer import _session_options

        options = _session_options(4)

        self.assertEqual(options.intra_op_num_threads, 4)
        self.assertEqual(options.inter_op_num_threads, 1)


class ModelValidationTests(unittest.TestCase):
    """__init__ translates onnx_asr's generic ValueError into UnsupportedModel
    only when the message says so, and must not swallow any other failure
    onnx_asr.load_model raises for an unrelated reason."""

    def test_unsupported_model_name_raises_domain_error(self) -> None:
        with patch(
            "onnx_asr.load_model",
            side_effect=ValueError("model 'whisper-base' is not supported"),
        ):
            with self.assertRaises(UnsupportedModel):
                ParakeetRecognizer("whisper-base")

    def test_unrelated_value_error_is_not_converted(self) -> None:
        with patch(
            "onnx_asr.load_model",
            side_effect=ValueError("could not reach the model cache"),
        ):
            with self.assertRaisesRegex(ValueError, "could not reach the model cache"):
                ParakeetRecognizer("nemo-parakeet-tdt-0.6b-v3")


class DeviceValidationTests(unittest.TestCase):
    """A typo like device='cdua' used to fall through _PROVIDERS.get(...) to
    None, silently handing onnxruntime its own default provider instead of
    surfacing a config error (PR #2 review)."""

    def test_unknown_device_raises_before_touching_onnx_asr(self) -> None:
        with patch("onnx_asr.load_model") as fake_load_model:
            with self.assertRaisesRegex(ValueError, "asr.device 'cdua' is not supported"):
                ParakeetRecognizer("nemo-parakeet-tdt-0.6b-v3", device="cdua")
            fake_load_model.assert_not_called()

    def test_known_devices_still_pass_through(self) -> None:
        for device in ("cpu", "CUDA", " cpu "):
            with self.subTest(device=device):
                with patch("onnx_asr.load_model") as fake_load_model:
                    fake_load_model.return_value.with_timestamps.return_value = object()
                    ParakeetRecognizer("nemo-parakeet-tdt-0.6b-v3", device=device)
                    fake_load_model.assert_called_once()


class AsSamplesTests(unittest.TestCase):
    """Multi-channel audio must not silently flatten into a 1-D array whose
    sample count no longer matches sample_rate (PR #2 review, line 190)."""

    def test_mono_1d_flattens_unchanged(self) -> None:
        from live_translator.asr.recognizer import _as_samples

        result = _as_samples(np.zeros(1600, dtype=np.float32))

        self.assertEqual(result.shape, (1600,))

    def test_mono_with_trailing_singleton_axis_still_flattens(self) -> None:
        from live_translator.asr.recognizer import _as_samples

        result = _as_samples(np.zeros((1600, 1), dtype=np.float32))

        self.assertEqual(result.shape, (1600,))

    def test_stereo_is_rejected_rather_than_flattened(self) -> None:
        from live_translator.asr.recognizer import _as_samples

        result = _as_samples(np.zeros((1600, 2), dtype=np.float32))

        self.assertIsNone(result)

    def test_stereo_input_skips_gap_recovery_instead_of_corrupting_it(self) -> None:
        """End-to-end: a real, sizeable gap (2s left uncovered of a 3s clip,
        well past min_gap_seconds) would normally trigger a tail-covering
        decode. On stereo input that decode must not fire at all -- not run
        against a flattened, wrongly-timed array."""
        model = FlakyModel(
            [FakeTimestampedResult("opening only", [-0.01], [0.2, 1.0])]
        )
        recognizer = build(model._results[0], model=model, recover_gaps=True, min_gap_seconds=0.5)

        # (48000, 2) stereo at 16000 Hz -> duration_seconds = 3.0s, but decoded
        # only reaches 1.0s: a 2.0s gap that mono input of the same duration
        # would trigger _cover_tail on.
        transcript = recognizer.transcribe(np.zeros((48000, 2), dtype=np.float32), 16000)

        self.assertEqual(transcript.text, "opening only")
        self.assertEqual(len(model.calls), 1)  # no extra gap-covering decode


class RecoveryTransformFailureTests(unittest.TestCase):
    """_recover must skip a pass whose transform can't process the audio,
    not crash -- and give up cleanly if every pass fails that way."""

    def test_recover_skips_passes_the_transforms_cannot_handle(self) -> None:
        model = FlakyModel([FakeTimestampedResult("should not be reached", [-0.01])])
        recognizer = build(FakeTimestampedResult("", [], None), model=model, recover_empty=True)

        name, decoded = recognizer._recover(["not", "numeric", "data"], 16000, {})

        self.assertIsNone(name)
        self.assertEqual(decoded.text, "")
        # Every pass's transform raised before the model could be called.
        self.assertEqual(len(model.calls), 0)


if __name__ == "__main__":
    unittest.main()
