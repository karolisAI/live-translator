import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from live_translator.asr import SUPPORTED_ASR_ENGINES, create_asr
from live_translator.asr.parakeet_engine import ParakeetAsr
from live_translator.config import AsrSettings, apply_cli_overrides, load_config


@dataclass
class FakeTranscript:
    """Duck-types `parakeet_live.Transcript`.

    Declared locally rather than imported so these tests still run when the
    optional `parakeet-live` package is not installed.
    """

    text: str
    language: str | None = None
    duration_seconds: float = 1.0
    inference_seconds: float = 0.1
    rejected: bool = False
    rejection_reason: str | None = None


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
    """The recognizer's own behaviour is covered in packages/parakeet-live.
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

    def test_rejects_wrong_engine_before_importing_the_package(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported ASR engine"):
            ParakeetAsr(AsrSettings(engine="faster-whisper"))


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
