import io
import unittest
from contextlib import redirect_stderr
from dataclasses import dataclass, replace
from importlib import import_module
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np

from live_translator.asr import SUPPORTED_ASR_ENGINES, create_asr
from live_translator.asr.parakeet_engine import ParakeetAsr
from live_translator.cli import build_parser
from live_translator.config import (
    AppConfig,
    AsrSettings,
    apply_cli_overrides,
    load_config,
    validate_config,
)
from live_translator.defaults import ASR_ENGINES, DEFAULT_ASR_ENGINE
from live_translator.errors import UnsupportedModel


@dataclass
class FakeTranscript:
    """Duck-types `live_translator.asr.recognizer.Transcript`.

    Declared locally rather than imported so these tests do not need onnx-asr.
    """

    text: str
    language: str | None = None
    duration_seconds: float = 1.0
    inference_seconds: float = 0.1
    rejected: bool = False
    rejection_reason: str | None = None
    low_confidence: bool = False


class FakeRecognizer:
    def __init__(self, transcript: FakeTranscript) -> None:
        self._transcript = transcript
        self.calls: list[tuple] = []

    def transcribe(self, audio, sample_rate):
        self.calls.append((len(audio), sample_rate))
        return self._transcript


def build_adapter(transcript: FakeTranscript) -> ParakeetAsr:
    engine = ParakeetAsr.__new__(ParakeetAsr)
    engine._settings = AsrSettings(engine="parakeet", model="nemo-parakeet-tdt-0.6b-v3")
    engine._recognizer = FakeRecognizer(transcript)
    return engine


class ParakeetAdapterTests(unittest.TestCase):
    """The recognizer's own behaviour is covered in test_recognizer.py.
    What matters here is the mapping onto this project's TranscriptResult."""

    def test_maps_accepted_transcript(self) -> None:
        engine = build_adapter(
            FakeTranscript("Guten Morgen", language="de", duration_seconds=2.0)
        )

        result = engine.transcribe(np.zeros(32000, dtype=np.float32), 16000)

        self.assertEqual(result.text, "Guten Morgen")
        self.assertEqual(result.language, "de")
        self.assertEqual(result.duration_seconds, 2.0)
        self.assertEqual(result.rejected_segments, 0)
        self.assertEqual(result.rejection_reasons, ())
        self.assertEqual(engine._recognizer.calls, [(32000, 16000)])

    def test_maps_rejection_to_segment_count_and_reasons(self) -> None:
        engine = build_adapter(
            FakeTranscript("", rejected=True, rejection_reason="no_speech")
        )

        result = engine.transcribe(np.zeros(16000, dtype=np.float32), 16000)

        self.assertEqual(result.text, "")
        self.assertEqual(result.rejected_segments, 1)
        self.assertEqual(result.rejection_reasons, ("no_speech",))

    def test_maps_low_confidence_flag(self) -> None:
        engine = build_adapter(FakeTranscript("unsicherer Satz", low_confidence=True))

        result = engine.transcribe(np.zeros(16000, dtype=np.float32), 16000)

        self.assertEqual(result.text, "unsicherer Satz")
        self.assertEqual(result.rejected_segments, 0)
        self.assertTrue(result.low_confidence)

    def test_rejects_wrong_engine_before_loading_the_model(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported ASR engine"):
            ParakeetAsr(AsrSettings(engine="whisper.cpp"))

    def test_constructs_recognizer_from_settings(self) -> None:
        """The other tests here bypass __init__ via build_adapter(), so nothing
        else verifies that AsrSettings actually reaches ParakeetRecognizer."""
        settings = AsrSettings(
            engine="parakeet",
            model="nemo-parakeet-tdt-0.6b-v3",
            compute_type="int8",
            device="cpu",
            cpu_threads=8,
            source_language="de",
            min_segment_chars=2,
            log_prob_threshold=-1.3,
            flag_log_prob_threshold=-0.05,
            compression_ratio_threshold=2.4,
        )

        with patch("live_translator.asr.parakeet_engine.ParakeetRecognizer") as fake_cls:
            ParakeetAsr(settings)

        fake_cls.assert_called_once_with(
            "nemo-parakeet-tdt-0.6b-v3",
            quantization="int8",
            device="cpu",
            cpu_threads=8,
            language="de",
            min_chars=2,
            log_prob_threshold=-1.3,
            flag_log_prob_threshold=-0.05,
            compression_ratio_threshold=2.4,
        )

    def test_translates_unsupported_model_into_a_config_facing_error(self) -> None:
        with patch(
            "live_translator.asr.parakeet_engine.ParakeetRecognizer",
            side_effect=UnsupportedModel("'base' is not a Parakeet model"),
        ):
            with self.assertRaisesRegex(ValueError, r"asr\.model 'base' is not a Parakeet model"):
                ParakeetAsr(AsrSettings(engine="parakeet", model="base"))


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
        self.assertEqual(SUPPORTED_ASR_ENGINES, ("parakeet",))


class AsrRegistryTests(unittest.TestCase):
    """`defaults.ASR_ENGINES` is the one place an engine is declared. These pin
    the three consumers -- the factory, config validation and the CLI choices --
    to it, so a new entry cannot reach some of them and not the others."""

    def test_supported_engines_are_exactly_the_registry_keys(self) -> None:
        self.assertEqual(SUPPORTED_ASR_ENGINES, tuple(ASR_ENGINES))

    def test_every_registered_engine_resolves_and_is_an_asr_engine(self) -> None:
        for name, target in ASR_ENGINES.items():
            with self.subTest(engine=name):
                module_name, separator, attribute = target.partition(":")
                self.assertTrue(separator, f"{name} must be 'module:attribute'")
                engine_class = getattr(import_module(module_name), attribute)
                self.assertTrue(callable(getattr(engine_class, "transcribe", None)))
                self.assertEqual(engine_class.ENGINE_NAME, name)

    def test_factory_builds_every_registered_engine(self) -> None:
        for name in ASR_ENGINES:
            with self.subTest(engine=name):
                with patch("live_translator.asr.parakeet_engine.ParakeetRecognizer"):
                    engine = create_asr(AsrSettings(engine=name))

                self.assertEqual(type(engine).ENGINE_NAME, name)

    def test_config_validation_accepts_every_registered_engine(self) -> None:
        for name in ASR_ENGINES:
            with self.subTest(engine=name):
                validate_config(replace(AppConfig(), asr=AsrSettings(engine=name)))

    def test_config_validation_rejects_what_the_registry_omits(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported ASR engine"):
            validate_config(replace(AppConfig(), asr=AsrSettings(engine="whisper.cpp")))

    def test_cli_offers_exactly_the_registered_engines(self) -> None:
        parser = build_parser()

        for command in ("meeting", "transcribe-once"):
            for name in ASR_ENGINES:
                with self.subTest(command=command, engine=name):
                    args = parser.parse_args([command, "--asr-engine", name])
                    self.assertEqual(args.asr_engine, name)

            with self.subTest(command=command, engine="unregistered"):
                with redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        parser.parse_args([command, "--asr-engine", "whisper.cpp"])

    def test_default_engine_is_registered(self) -> None:
        self.assertIn(DEFAULT_ASR_ENGINE, ASR_ENGINES)
        self.assertEqual(AppConfig().asr.engine, DEFAULT_ASR_ENGINE)

    def test_an_unregistered_engine_is_rejected_everywhere(self) -> None:
        """The failure mode this centralization exists to prevent: a name that
        one consumer accepts and another does not."""
        with patch.dict(ASR_ENGINES, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "Unsupported ASR engine"):
                create_asr(AsrSettings(engine="parakeet"))


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

    def test_log_prob_threshold_is_independent_per_profile(self) -> None:
        """log_prob_threshold is meant to be tuned per direction profile
        (en-de.yaml vs de-en.yaml), not shared globally -- confidence/WER
        correlation measured differently by source_language. Two separate
        config files must not leak a value into each other."""
        with TemporaryDirectory() as temp_dir:
            en_de_path = Path(temp_dir) / "en-de.yaml"
            en_de_path.write_text(
                "asr:\n  engine: parakeet\n  source_language: en\n  log_prob_threshold: -0.07\n",
                encoding="utf-8",
            )
            de_en_path = Path(temp_dir) / "de-en.yaml"
            de_en_path.write_text(
                "asr:\n  engine: parakeet\n  source_language: de\n  log_prob_threshold: -0.03\n",
                encoding="utf-8",
            )

            en_de = load_config(en_de_path)
            de_en = load_config(de_en_path)

            self.assertEqual(en_de.asr.log_prob_threshold, -0.07)
            self.assertEqual(de_en.asr.log_prob_threshold, -0.03)

    def test_config_still_rejects_unknown_engine(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "app.yaml"
            config_path.write_text("asr:\n  engine: bogus\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Unsupported ASR engine"):
                load_config(config_path)

    def test_cli_model_override_wins(self) -> None:
        from live_translator.config import AppConfig

        config = AppConfig(asr=AsrSettings(engine="parakeet"))

        updated = apply_cli_overrides(config, model="custom/model")

        self.assertEqual(updated.asr.engine, "parakeet")
        self.assertEqual(updated.asr.model, "custom/model")

    def test_cli_engine_override_keeps_configured_model(self) -> None:
        from live_translator.config import AppConfig

        config = AppConfig(asr=AsrSettings(engine="parakeet", model="custom/model"))

        updated = apply_cli_overrides(config, asr_engine="parakeet")

        self.assertEqual(updated.asr.model, "custom/model")


if __name__ == "__main__":
    unittest.main()
