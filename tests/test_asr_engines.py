import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from live_translator.asr import SUPPORTED_ASR_ENGINES, create_asr
from live_translator.asr.parakeet_engine import ParakeetAsr, _compression_ratio
from live_translator.config import AsrSettings, apply_cli_overrides, load_config


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


def build_parakeet(result: FakeTimestampedResult, **overrides) -> ParakeetAsr:
    settings = AsrSettings(engine="parakeet", model="nemo-parakeet-tdt-0.6b-v3", **overrides)
    engine = ParakeetAsr.__new__(ParakeetAsr)
    engine._settings = settings
    engine._model = FakeModel(result)
    return engine


class ParakeetEngineTests(unittest.TestCase):
    def test_transcribes_and_reports_timings(self) -> None:
        engine = build_parakeet(FakeTimestampedResult("Guten Morgen", [-0.01, -0.02]))

        result = engine.transcribe(np.zeros(16000, dtype=np.float32), 16000)

        self.assertEqual(result.text, "Guten Morgen")
        self.assertEqual(result.duration_seconds, 1.0)
        self.assertEqual(result.rejected_segments, 0)
        self.assertGreaterEqual(result.inference_seconds, 0.0)

    def test_passes_source_language_through(self) -> None:
        engine = build_parakeet(FakeTimestampedResult("hallo", [-0.1]), source_language="de")

        engine.transcribe(np.zeros(1600, dtype=np.float32), 16000)

        self.assertEqual(engine._model.calls[0]["language"], "de")

    def test_omits_language_when_unset(self) -> None:
        engine = build_parakeet(FakeTimestampedResult("hallo", [-0.1]), source_language=None)

        engine.transcribe(np.zeros(1600, dtype=np.float32), 16000)

        self.assertNotIn("language", engine._model.calls[0])

    def test_empty_output_is_rejected_as_no_speech(self) -> None:
        # Silence and noise make this model emit zero tokens.
        engine = build_parakeet(FakeTimestampedResult("", []))

        result = engine.transcribe(np.zeros(16000, dtype=np.float32), 16000)

        self.assertEqual(result.text, "")
        self.assertEqual(result.rejected_segments, 1)
        self.assertEqual(result.rejection_reasons, ("no_speech",))

    def test_rejects_low_average_logprob(self) -> None:
        engine = build_parakeet(
            FakeTimestampedResult("murmeln", [-2.0, -3.0]), log_prob_threshold=-1.3
        )

        result = engine.transcribe(np.zeros(16000, dtype=np.float32), 16000)

        self.assertEqual(result.text, "")
        self.assertEqual(result.rejected_segments, 1)
        self.assertTrue(result.rejection_reasons[0].startswith("avg_logprob="))

    def test_keeps_confident_output_at_same_threshold(self) -> None:
        engine = build_parakeet(
            FakeTimestampedResult("klarer Satz", [-0.01, -0.02]), log_prob_threshold=-1.3
        )

        self.assertEqual(engine.transcribe(np.zeros(16000, dtype=np.float32), 16000).text, "klarer Satz")

    def test_rejects_short_output(self) -> None:
        engine = build_parakeet(FakeTimestampedResult("a", [-0.01]), min_segment_chars=2)

        result = engine.transcribe(np.zeros(16000, dtype=np.float32), 16000)

        self.assertEqual(result.rejection_reasons, ("short",))

    def test_rejects_degenerate_repetition(self) -> None:
        engine = build_parakeet(
            FakeTimestampedResult("ja " * 400, [-0.01]), compression_ratio_threshold=2.4
        )

        result = engine.transcribe(np.zeros(16000, dtype=np.float32), 16000)

        self.assertEqual(result.text, "")
        self.assertTrue(result.rejection_reasons[0].startswith("compression_ratio="))

    def test_missing_logprobs_do_not_crash(self) -> None:
        engine = build_parakeet(FakeTimestampedResult("hallo", None))

        self.assertEqual(engine.transcribe(np.zeros(1600, dtype=np.float32), 16000).text, "hallo")

    def test_compression_ratio_flags_repetition(self) -> None:
        self.assertGreater(_compression_ratio("ja " * 400), _compression_ratio("ein normaler Satz"))


class SilenceGateTests(unittest.TestCase):
    """Parakeet can hallucinate a short phrase on digital silence, with
    confidence overlapping genuine short speech, so no logprob threshold can
    filter it. The pre-ASR energy gate is the actual protection."""

    def test_energy_gate_blocks_silence_before_asr(self) -> None:
        from live_translator.audio.analysis import analyze_audio, has_enough_audio_energy
        from live_translator.config import ChunkingSettings

        chunking = ChunkingSettings()
        for name, audio in (
            ("silence", np.zeros(32000, dtype=np.float32)),
            ("near-silence", np.full(32000, 1e-4, dtype=np.float32)),
        ):
            with self.subTest(audio=name):
                stats = analyze_audio(
                    audio,
                    16000,
                    frame_ms=chunking.frame_ms,
                    active_rms_threshold=chunking.rms_threshold,
                    active_peak_threshold=chunking.peak_threshold,
                )
                self.assertFalse(
                    has_enough_audio_energy(
                        stats,
                        rms_threshold=chunking.rms_threshold,
                        peak_threshold=chunking.peak_threshold,
                        min_active_ratio=chunking.min_active_ratio,
                    )
                )


class AsrFactoryTests(unittest.TestCase):
    def test_rejects_unknown_engine(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported ASR engine"):
            create_asr(AsrSettings(engine="whisper.cpp"))

    def test_supported_engines_list(self) -> None:
        self.assertEqual(SUPPORTED_ASR_ENGINES, ("faster-whisper", "parakeet"))


class ParakeetConfigTests(unittest.TestCase):
    def test_config_accepts_parakeet_engine(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "app.yaml"
            config_path.write_text(
                "asr:\n"
                "  engine: parakeet\n"
                "  model: nemo-parakeet-tdt-0.6b-v3\n"
                "  compute_type: int8\n"
                "  source_language: de\n"
                "translation:\n"
                "  engine: argos\n"
                "  source_language: de\n"
                "  target_language: en\n",
                encoding="utf-8",
            )

            config = load_config(config_path)

            self.assertEqual(config.asr.engine, "parakeet")
            self.assertEqual(config.asr.compute_type, "int8")

    def test_config_still_rejects_unknown_engine(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "app.yaml"
            config_path.write_text("asr:\n  engine: bogus\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Unsupported ASR engine"):
                load_config(config_path)

    def test_cli_override_switches_engine_and_default_model(self) -> None:
        from live_translator.config import AppConfig

        # A profile carries a Whisper model name; switching engines alone must
        # not hand 'base' to Parakeet.
        config = AppConfig(asr=AsrSettings(engine="faster-whisper", model="base"))

        updated = apply_cli_overrides(config, asr_engine="parakeet")

        self.assertEqual(updated.asr.engine, "parakeet")
        self.assertEqual(updated.asr.model, "nemo-parakeet-tdt-0.6b-v3")

    def test_explicit_model_wins_over_engine_default(self) -> None:
        from live_translator.config import AppConfig

        config = AppConfig(asr=AsrSettings(engine="faster-whisper", model="base"))

        updated = apply_cli_overrides(config, asr_engine="parakeet", model="custom/model")

        self.assertEqual(updated.asr.model, "custom/model")

    def test_same_engine_keeps_configured_model(self) -> None:
        from live_translator.config import AppConfig

        config = AppConfig(asr=AsrSettings(engine="faster-whisper", model="small"))

        updated = apply_cli_overrides(config, asr_engine="faster-whisper")

        self.assertEqual(updated.asr.model, "small")


if __name__ == "__main__":
    unittest.main()
