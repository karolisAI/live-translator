import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from live_translator.asr.recognizer import DEFAULT_MODEL
from live_translator.config import AppConfig, apply_cli_overrides, load_config
from live_translator.defaults import DEFAULT_ASR_ENGINE, DEFAULT_ASR_MODEL
from live_translator.profiles import write_meeting_profile


class DefaultModelTests(unittest.TestCase):
    """One source of truth: changing it must not strand a stale copy behind."""

    def test_recognizer_and_config_agree_on_the_default_model(self) -> None:
        self.assertEqual(DEFAULT_MODEL, DEFAULT_ASR_MODEL)
        self.assertEqual(AppConfig().asr.model, DEFAULT_ASR_MODEL)

    def test_omitted_model_falls_back_to_the_shared_default(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "app.yaml"
            config_path.write_text("asr:\n  device: cpu\n", encoding="utf-8")

            self.assertEqual(load_config(config_path).asr.model, DEFAULT_ASR_MODEL)

    def test_generated_profile_uses_the_shared_default(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "en-de.yaml"
            write_meeting_profile(
                path=config_path,
                direction="en-de",
                microphone_device="Mic",
                translated_output_device="Cable Input",
                meeting_microphone_device="Cable Output",
            )

            self.assertEqual(load_config(config_path).asr.model, DEFAULT_ASR_MODEL)
            self.assertIn(DEFAULT_ASR_MODEL, config_path.read_text(encoding="utf-8"))

    def test_generated_profile_uses_the_shared_engine_default(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "en-de.yaml"
            write_meeting_profile(
                path=config_path,
                direction="en-de",
                microphone_device="Mic",
                translated_output_device="Cable Input",
                meeting_microphone_device="Cable Output",
            )

            self.assertEqual(load_config(config_path).asr.engine, DEFAULT_ASR_ENGINE)

    def test_no_module_hardcodes_the_model_name(self) -> None:
        self.assertEqual(self._offenders(DEFAULT_ASR_MODEL), [])

    def test_no_module_hardcodes_the_engine_name(self) -> None:
        # parakeet_engine.py declares its own ENGINE_NAME, which
        # AsrRegistryTests pins to the matching defaults.ASR_ENGINES key.
        self.assertEqual(self._offenders(DEFAULT_ASR_ENGINE, allowed={"parakeet_engine.py"}), [])

    def _offenders(self, literal: str, *, allowed: set[str] | None = None) -> list[str]:
        source_root = Path(__file__).resolve().parents[1] / "src" / "live_translator"
        exempt = {"defaults.py"} | (allowed or set())
        return sorted(
            path.name
            for path in source_root.rglob("*.py")
            if path.name not in exempt
            and f'"{literal}"' in path.read_text(encoding="utf-8")
        )


class ConfigTests(unittest.TestCase):
    def test_checked_in_configs_are_valid(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for filename in ("app.example.yaml",):
            with self.subTest(filename=filename):
                load_config(root / filename)

    def test_rejects_unknown_config_settings(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "app.yaml"
            config_path.write_text(
                "asr:\n  model: base\n  window_ms: 1200\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "asr.window_ms"):
                load_config(config_path)

    def test_rejects_non_16khz_pipeline_rate(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "app.yaml"
            config_path.write_text(
                "audio:\n  sample_rate: 48000\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "must be 16000"):
                load_config(config_path)

    def test_rejects_argos_auto_source_language(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires a fixed source language"):
            apply_cli_overrides(
                AppConfig(),
                source_language="auto",
                target_language="de",
                translation_engine="argos",
            )

    def test_rejects_blank_engine_instead_of_silently_disabling_it(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "app.yaml"
            config_path.write_text("translation:\n  engine:\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "engine must not be blank"):
                load_config(config_path)

    def test_rejects_nonpositive_cli_timings_and_thresholds(self) -> None:
        overrides = (
            {"seconds": -1.0},
            {"vad_threshold": -1.0},
            {"peak_threshold": -1.0},
            {"min_segment_seconds": -1.0},
            {"silence_ms": -1},
            {"max_seconds": -1.0},
            {"tts_length_scale": -1.0},
        )
        for override in overrides:
            with self.subTest(override=override), self.assertRaisesRegex(ValueError, "positive"):
                apply_cli_overrides(AppConfig(), **override)

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
            tts_length_scale=1.0,
        )

        self.assertEqual(config.tts.engine, "piper")
        self.assertEqual(config.tts.voice, "de_DE-thorsten-medium")
        self.assertEqual(config.tts.model_path, "models/tts/de_DE-thorsten-medium.onnx")
        self.assertEqual(config.tts.piper_exe, "tools/piper/piper.exe")
        self.assertEqual(config.tts.length_scale, 1.0)

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
                        "  length_scale: 1.0",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_config(config_path)

        self.assertEqual(config.tts.engine, "piper")
        self.assertEqual(config.tts.speaker, "0")
        self.assertEqual(config.tts.length_scale, 1.0)

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
                        "  log_prob_threshold: -0.8",
                        "  flag_log_prob_threshold: -0.05",
                        "  compression_ratio_threshold: 2.2",
                        "  min_segment_chars: 3",
                    ]
                ),
                encoding="utf-8",
            )

            config = load_config(config_path)

        self.assertEqual(config.asr.log_prob_threshold, -0.8)
        self.assertEqual(config.asr.flag_log_prob_threshold, -0.05)
        self.assertEqual(config.asr.compression_ratio_threshold, 2.2)
        self.assertEqual(config.asr.min_segment_chars, 3)

    def test_flag_log_prob_threshold_defaults_to_disabled(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "app.yaml"
            config_path.write_text("asr:\n  log_prob_threshold: -0.8\n", encoding="utf-8")

            config = load_config(config_path)

        self.assertIsNone(config.asr.flag_log_prob_threshold)

    def test_rejects_flag_threshold_at_or_below_reject_threshold(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "app.yaml"
            config_path.write_text(
                "asr:\n  log_prob_threshold: -0.3\n  flag_log_prob_threshold: -0.3\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "flag_log_prob_threshold"):
                load_config(config_path)

    def test_cli_overrides_chunking_settings(self) -> None:
        config = apply_cli_overrides(
            AppConfig(),
            log_prob_threshold=-1.7,
            flag_log_prob_threshold=-0.1,
            chunker_mode="vad",
            vad_threshold=0.02,
            peak_threshold=0.04,
            min_active_ratio=0.12,
            min_segment_seconds=1.4,
            rolling_window_seconds=2.6,
            silence_ms=450,
            max_seconds=5.0,
        )

        self.assertEqual(config.asr.log_prob_threshold, -1.7)
        self.assertEqual(config.asr.flag_log_prob_threshold, -0.1)
        self.assertEqual(config.chunking.mode, "vad")
        self.assertEqual(config.chunking.rms_threshold, 0.02)
        self.assertEqual(config.chunking.peak_threshold, 0.04)
        self.assertEqual(config.chunking.min_active_ratio, 0.12)
        self.assertEqual(config.chunking.min_segment_seconds, 1.4)
        self.assertEqual(config.chunking.rolling_window_seconds, 2.6)
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
        self.assertEqual(config.audio.playback_gain, 0.7)
        self.assertEqual(config.asr.model, DEFAULT_ASR_MODEL)
        self.assertEqual(config.tts.model_path, "models/tts/en_US-hfc_male-medium.onnx")
        self.assertEqual(config.chunking.mode, "vad")
        self.assertEqual(config.chunking.min_segment_seconds, 0.8)
        self.assertEqual(config.chunking.rolling_window_seconds, 2.4)
        self.assertEqual(config.chunking.silence_ms, 450)
        self.assertEqual(config.asr.device, "cpu")
        self.assertEqual(config.asr.compute_type, "int8")
        self.assertEqual(config.asr.cpu_threads, 8)
        self.assertEqual(config.realtime.recognition_queue_size, 2)
        self.assertEqual(config.realtime.playback_queue_size, 1)
        self.assertEqual(config.asr.log_prob_threshold, -1.3)

    def test_loads_realtime_queue_sizes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "app.yaml"
            config_path.write_text(
                "realtime:\n  recognition_queue_size: 3\n  playback_queue_size: 5\n",
                encoding="utf-8",
            )

            config = load_config(config_path)

        self.assertEqual(config.realtime.recognition_queue_size, 3)
        self.assertEqual(config.realtime.playback_queue_size, 5)


if __name__ == "__main__":
    unittest.main()
