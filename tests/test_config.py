import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from live_translator.config import AppConfig, apply_cli_overrides, load_config
from live_translator.profiles import write_meeting_profile


class ConfigTests(unittest.TestCase):
    def test_cli_overrides_chunk_and_languages(self) -> None:
        config = apply_cli_overrides(
            AppConfig(),
            seconds=1.5,
            input_gain=1.8,
            source_language="en",
            target_language="de",
            translation_engine="identity",
            tts_engine="none",
        )

        self.assertEqual(config.audio.chunk_seconds, 1.5)
        self.assertEqual(config.audio.input_gain, 1.8)
        self.assertEqual(config.asr.source_language, "en")
        self.assertEqual(config.translation.source_language, "en")
        self.assertEqual(config.translation.target_language, "de")
        self.assertEqual(config.translation.engine, "identity")
        self.assertEqual(config.tts.engine, "none")

    def test_cli_overrides_piper_settings(self) -> None:
        config = apply_cli_overrides(
            AppConfig(),
            tts_engine="piper",
            tts_voice="de_DE-thorsten-medium",
            tts_model_path="models/tts/de_DE-thorsten-medium.onnx",
            piper_exe="tools/piper/piper.exe",
        )

        self.assertEqual(config.tts.engine, "piper")
        self.assertEqual(config.tts.voice, "de_DE-thorsten-medium")
        self.assertEqual(config.tts.model_path, "models/tts/de_DE-thorsten-medium.onnx")
        self.assertEqual(config.tts.piper_exe, "tools/piper/piper.exe")

    def test_loads_tts_speaker_field(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "app.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "tts:",
                        "  engine: piper",
                        "  model_path: models/tts/de_DE-thorsten-medium.onnx",
                        "  piper_exe: tools/piper/piper.exe",
                        "  speaker: '0'",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_config(config_path)

        self.assertEqual(config.tts.engine, "piper")
        self.assertEqual(config.tts.speaker, "0")

    def test_loads_chunking_settings(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "app.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "chunking:",
                        "  mode: vad",
                        "  silence_ms: 500",
                        "  min_segment_seconds: 1.4",
                        "  max_seconds: 4.5",
                        "  rms_threshold: 0.02",
                        "  peak_threshold: 0.04",
                        "  min_active_ratio: 0.12",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_config(config_path)

        self.assertEqual(config.chunking.mode, "vad")
        self.assertEqual(config.chunking.silence_ms, 500)
        self.assertEqual(config.chunking.min_segment_seconds, 1.4)
        self.assertEqual(config.chunking.max_seconds, 4.5)
        self.assertEqual(config.chunking.rms_threshold, 0.02)
        self.assertEqual(config.chunking.peak_threshold, 0.04)
        self.assertEqual(config.chunking.min_active_ratio, 0.12)

    def test_loads_asr_safety_settings(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "app.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "asr:",
                        "  condition_on_previous_text: false",
                        "  no_speech_threshold: 0.5",
                        "  log_prob_threshold: -0.8",
                        "  compression_ratio_threshold: 2.2",
                        "  min_segment_chars: 3",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_config(config_path)

        self.assertFalse(config.asr.condition_on_previous_text)
        self.assertEqual(config.asr.no_speech_threshold, 0.5)
        self.assertEqual(config.asr.log_prob_threshold, -0.8)
        self.assertEqual(config.asr.compression_ratio_threshold, 2.2)
        self.assertEqual(config.asr.min_segment_chars, 3)

    def test_cli_overrides_chunking_settings(self) -> None:
        config = apply_cli_overrides(
            AppConfig(),
            no_speech_threshold=0.88,
            log_prob_threshold=-1.7,
            chunker_mode="vad",
            vad_threshold=0.02,
            peak_threshold=0.04,
            min_active_ratio=0.12,
            min_segment_seconds=1.4,
            silence_ms=450,
            max_seconds=5.0,
        )

        self.assertEqual(config.asr.no_speech_threshold, 0.88)
        self.assertEqual(config.asr.log_prob_threshold, -1.7)
        self.assertEqual(config.chunking.mode, "vad")
        self.assertEqual(config.chunking.rms_threshold, 0.02)
        self.assertEqual(config.chunking.peak_threshold, 0.04)
        self.assertEqual(config.chunking.min_active_ratio, 0.12)
        self.assertEqual(config.chunking.min_segment_seconds, 1.4)
        self.assertEqual(config.chunking.silence_ms, 450)
        self.assertEqual(config.chunking.max_seconds, 5.0)

    def test_write_de_en_profile(self) -> None:
        with TemporaryDirectory() as temp_dir:
            profile_path = write_meeting_profile(
                path=Path(temp_dir) / "default.yaml",
                direction="de-en",
                microphone_device="Microphone",
                translated_output_device="CABLE Input",
                meeting_microphone_device="CABLE Output",
            )

            config = load_config(profile_path)

        self.assertEqual(config.asr.source_language, "de")
        self.assertEqual(config.translation.source_language, "de")
        self.assertEqual(config.translation.target_language, "en")
        self.assertEqual(config.audio.input_device, "Microphone")
        self.assertEqual(config.audio.output_device, "CABLE Input")
        self.assertEqual(config.audio.peer_input_device, "CABLE Output")
        self.assertEqual(config.audio.input_gain, 1.0)
        self.assertEqual(config.asr.model, "base")
        self.assertEqual(config.tts.model_path, "models/tts/en_US-hfc_male-medium.onnx")
        self.assertEqual(config.chunking.mode, "vad")
        self.assertEqual(config.chunking.min_segment_seconds, 1.2)
        self.assertFalse(config.asr.condition_on_previous_text)
        self.assertEqual(config.asr.no_speech_threshold, 0.90)
        self.assertEqual(config.asr.log_prob_threshold, -1.8)


if __name__ == "__main__":
    unittest.main()
