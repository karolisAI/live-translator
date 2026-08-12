import unittest
from unittest.mock import patch

import numpy as np

from live_translator.asr.parakeet_engine import ParakeetAsr
from live_translator.config import AsrSettings


class FakeParakeetModel:
    def __init__(self, gguf_path) -> None:
        self.gguf_path = gguf_path
        self.calls: list[tuple[int, int, str | None]] = []
        self.next_text = ""

    def transcribe_pcm(self, samples, sample_rate, decoder=0, target_lang=None):
        self.calls.append((len(samples), sample_rate, target_lang))
        return self.next_text


class ParakeetAsrTests(unittest.TestCase):
    def test_rejects_non_parakeet_engine(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported ASR engine"):
            ParakeetAsr(AsrSettings(engine="faster-whisper"))

    def test_pins_thread_count_from_settings(self) -> None:
        with (
            patch("live_translator.asr.parakeet_engine.ParakeetModel", FakeParakeetModel),
            patch("live_translator.asr.parakeet_engine.set_num_threads") as fake_set_threads,
        ):
            ParakeetAsr(AsrSettings(engine="parakeet", model="m.gguf", cpu_threads=8))

        fake_set_threads.assert_called_once_with(8)

    def test_zero_cpu_threads_leaves_library_default(self) -> None:
        with (
            patch("live_translator.asr.parakeet_engine.ParakeetModel", FakeParakeetModel),
            patch("live_translator.asr.parakeet_engine.set_num_threads") as fake_set_threads,
        ):
            ParakeetAsr(AsrSettings(engine="parakeet", model="m.gguf", cpu_threads=0))

        fake_set_threads.assert_not_called()

    def test_transcribe_passes_source_language_as_target_lang(self) -> None:
        with (
            patch("live_translator.asr.parakeet_engine.ParakeetModel", FakeParakeetModel),
            patch("live_translator.asr.parakeet_engine.set_num_threads"),
        ):
            asr = ParakeetAsr(
                AsrSettings(engine="parakeet", model="m.gguf", source_language="de", cpu_threads=0)
            )
            asr._model.next_text = "Hallo Welt"
            audio = np.zeros(16000, dtype=np.float32)
            result = asr.transcribe(audio, 16000)

        self.assertEqual(asr._model.calls[0], (16000, 16000, "de"))
        self.assertEqual(result.text, "Hallo Welt")
        self.assertEqual(result.language, "de")
        self.assertEqual(result.duration_seconds, 1.0)
        self.assertEqual(result.rejected_segments, 0)
        self.assertEqual(result.rejection_reasons, ())

    def test_short_nonempty_hypothesis_is_rejected(self) -> None:
        with (
            patch("live_translator.asr.parakeet_engine.ParakeetModel", FakeParakeetModel),
            patch("live_translator.asr.parakeet_engine.set_num_threads"),
        ):
            asr = ParakeetAsr(
                AsrSettings(engine="parakeet", model="m.gguf", cpu_threads=0, min_segment_chars=5)
            )
            asr._model.next_text = "Hi"
            result = asr.transcribe(np.zeros(1600, dtype=np.float32), 16000)

        self.assertEqual(result.text, "")
        self.assertEqual(result.rejected_segments, 1)
        self.assertEqual(result.rejection_reasons, ("short",))

    def test_repetitive_hypothesis_is_rejected_as_compression_ratio(self) -> None:
        with (
            patch("live_translator.asr.parakeet_engine.ParakeetModel", FakeParakeetModel),
            patch("live_translator.asr.parakeet_engine.set_num_threads"),
        ):
            asr = ParakeetAsr(
                AsrSettings(engine="parakeet", model="m.gguf", cpu_threads=0, compression_ratio_threshold=2.4)
            )
            asr._model.next_text = "the the the the the the the the the the the the the the the the"
            result = asr.transcribe(np.zeros(1600, dtype=np.float32), 16000)

        self.assertEqual(result.text, "")
        self.assertEqual(result.rejected_segments, 1)
        self.assertTrue(result.rejection_reasons[0].startswith("compression_ratio="))

    def test_normal_hypothesis_is_not_rejected_as_compression_ratio(self) -> None:
        with (
            patch("live_translator.asr.parakeet_engine.ParakeetModel", FakeParakeetModel),
            patch("live_translator.asr.parakeet_engine.set_num_threads"),
        ):
            asr = ParakeetAsr(
                AsrSettings(engine="parakeet", model="m.gguf", cpu_threads=0, compression_ratio_threshold=2.4)
            )
            asr._model.next_text = "Let's start with the project timeline"
            result = asr.transcribe(np.zeros(1600, dtype=np.float32), 16000)

        self.assertEqual(result.text, "Let's start with the project timeline")
        self.assertEqual(result.rejected_segments, 0)

    def test_empty_hypothesis_is_not_counted_as_a_rejection(self) -> None:
        with (
            patch("live_translator.asr.parakeet_engine.ParakeetModel", FakeParakeetModel),
            patch("live_translator.asr.parakeet_engine.set_num_threads"),
        ):
            asr = ParakeetAsr(
                AsrSettings(engine="parakeet", model="m.gguf", cpu_threads=0, min_segment_chars=5)
            )
            asr._model.next_text = ""
            result = asr.transcribe(np.zeros(1600, dtype=np.float32), 16000)

        self.assertEqual(result.text, "")
        self.assertEqual(result.rejected_segments, 0)
        self.assertEqual(result.rejection_reasons, ())


if __name__ == "__main__":
    unittest.main()
