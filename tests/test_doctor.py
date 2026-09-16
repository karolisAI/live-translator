from __future__ import annotations

import argparse
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from live_translator.audio.devices import AudioDevice
from live_translator.cli import _print_config_checks, build_parser, cmd_doctor, main
from live_translator.config import AppConfig, load_config
from live_translator.profiles import write_meeting_profile
from live_translator.runtime import default_profile_path


def _run_doctor(*, found: set[str] | None = None) -> tuple[int, str, list[str]]:
    """Run `doctor` with dependency probing stubbed out; report what it probed."""
    probed: list[str] = []

    def fake_find_spec(name: str):
        probed.append(name)
        return None if found is not None and name not in found else object()

    args = argparse.Namespace(config=None, profile=None, prepare_models=False)
    buffer = io.StringIO()
    with patch("live_translator.cli.importlib.util.find_spec", fake_find_spec):
        with redirect_stdout(buffer):
            code = cmd_doctor(args)
    return code, buffer.getvalue(), probed


class DoctorDependencyTests(unittest.TestCase):
    def test_checks_onnx_asr_stack_and_not_faster_whisper(self) -> None:
        code, output, probed = _run_doctor()

        self.assertEqual(code, 0)
        self.assertIn("onnx_asr", probed)
        self.assertIn("onnxruntime", probed)
        self.assertNotIn("faster_whisper", probed)
        self.assertNotIn("faster_whisper", output)
        self.assertIn("OK      onnx_asr         required", output)
        self.assertIn("OK      onnxruntime      required", output)

    def test_missing_onnx_asr_is_a_required_failure(self) -> None:
        code, output, _ = _run_doctor(found={"numpy", "sounddevice", "onnxruntime", "ctranslate2", "sentencepiece", "yaml"})

        self.assertEqual(code, 1)
        self.assertIn("MISSING onnx_asr         required", output)
        self.assertIn("python -m pip install -e .", output)

    def test_missing_onnxruntime_is_a_required_failure(self) -> None:
        code, output, _ = _run_doctor(found={"numpy", "sounddevice", "onnx_asr", "ctranslate2", "sentencepiece", "yaml"})

        self.assertEqual(code, 1)
        self.assertIn("MISSING onnxruntime      required", output)


class DoctorPrepareModelsTests(unittest.TestCase):
    def _config_checks(self, *, prepare_models: bool):
        config = AppConfig()
        buffer = io.StringIO()
        with patch("live_translator.cli.create_asr") as create_asr, patch(
            "live_translator.cli._audio_device_detail", return_value="stub device"
        ), patch("live_translator.cli.TranslationEngine") as translation, patch(
            "live_translator.cli.TtsSpeaker"
        ) as tts:
            with redirect_stdout(buffer):
                passed = _print_config_checks(config, prepare_models=prepare_models)
        mocks = SimpleNamespace(create_asr=create_asr, translation=translation, tts=tts)
        return passed, buffer.getvalue(), mocks, config

    def test_prepare_models_loads_the_asr_engine_through_create_asr(self) -> None:
        passed, output, mocks, config = self._config_checks(prepare_models=True)

        self.assertTrue(passed)
        mocks.create_asr.assert_called_once_with(config.asr)
        self.assertIn(f"OK      speech.model     {config.asr.model} loaded", output)

    def test_without_prepare_models_no_asr_engine_is_constructed(self) -> None:
        passed, output, mocks, _ = self._config_checks(prepare_models=False)

        self.assertTrue(passed)
        mocks.create_asr.assert_not_called()
        self.assertIn("INFO    speech.model     run doctor with --prepare-models", output)

    def test_translation_and_voice_are_checked_without_prepare_models(self) -> None:
        """--prepare-models gates only speech.model; the help text says so."""
        _, output, mocks, config = self._config_checks(prepare_models=False)

        mocks.translation.assert_called_once_with(config.translation)
        mocks.translation.return_value.prepare.assert_called_once_with()
        mocks.tts.return_value.validate.assert_called_once_with()
        self.assertIn("OK      translation", output)
        self.assertIn("OK      speech.output", output)

    def test_asr_load_failure_fails_the_config_checks(self) -> None:
        config = AppConfig()
        buffer = io.StringIO()
        with patch(
            "live_translator.cli.create_asr", side_effect=RuntimeError("model download failed")
        ), patch("live_translator.cli._audio_device_detail", return_value="stub device"), patch(
            "live_translator.cli.TranslationEngine"
        ), patch("live_translator.cli.TtsSpeaker"):
            with redirect_stdout(buffer):
                passed = _print_config_checks(config, prepare_models=True)

        self.assertFalse(passed)
        self.assertIn("FAIL    speech.model     model download failed", buffer.getvalue())


class DoctorConfigResolutionTests(unittest.TestCase):
    """--prepare-models is config-scoped: it must never silently do nothing."""

    def test_prepare_models_without_a_profile_fails_instead_of_no_op(self) -> None:
        args = argparse.Namespace(config=None, profile=None, prepare_models=True)

        with self.assertRaisesRegex(ValueError, "--prepare-models needs a profile"):
            with redirect_stdout(io.StringIO()):
                cmd_doctor(args)

    def test_main_reports_the_missing_profile_as_exit_1(self) -> None:
        stderr = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
            code = main(["doctor", "--prepare-models"])

        self.assertEqual(code, 1)
        self.assertIn("--prepare-models needs a profile", stderr.getvalue())

    def test_bare_doctor_still_checks_dependencies_only(self) -> None:
        with patch("live_translator.cli._print_config_checks") as config_checks:
            code, output, _ = _run_doctor()

        config_checks.assert_not_called()
        self.assertEqual(code, 0)
        self.assertIn("onnx_asr", output)

    def test_profile_name_resolves_to_the_profile_directory(self) -> None:
        args = argparse.Namespace(config=None, profile="en-de", prepare_models=True)
        with patch("live_translator.cli.load_config") as load_config, patch(
            "live_translator.cli._print_config_checks", return_value=True
        ):
            with redirect_stdout(io.StringIO()):
                cmd_doctor(args)

        load_config.assert_called_once_with(default_profile_path("en-de"))

    def test_explicit_config_wins_over_profile_name(self) -> None:
        args = argparse.Namespace(config="app.example.yaml", profile="en-de", prepare_models=True)
        with patch("live_translator.cli.load_config") as load_config, patch(
            "live_translator.cli._print_config_checks", return_value=True
        ):
            with redirect_stdout(io.StringIO()):
                cmd_doctor(args)

        load_config.assert_called_once_with(Path("app.example.yaml"))


class DoctorInboundTests(unittest.TestCase):
    """doctor --inbound: derive the inbound direction and check its route and assets.

    Device resolution and the feedback-loop guard run for real against a fake
    device inventory; only device probing, translation and voice loading are stubbed.
    """

    WITH_CABLE_B = [
        ("input", 30, "Microphone (Jabra Evolve2 65)"),
        ("input", 33, "CABLE-A Output (VB-Audio Virtual Cable A)"),
        ("input", 31, "CABLE-B Output (VB-Audio Virtual Cable B)"),
        ("output", 26, "CABLE-A Input (VB-Audio Virtual Cable A)"),
        ("output", 24, "CABLE-B Input (VB-Audio Virtual Cable B)"),
        ("output", 40, "Headphones (Jabra Evolve2 65)"),
    ]

    def _outbound_config(self) -> AppConfig:
        with TemporaryDirectory() as temp_dir:
            return load_config(
                write_meeting_profile(
                    path=Path(temp_dir) / "en-de.yaml",
                    direction="en-de",
                    microphone_device="auto",
                    translated_output_device="auto",
                    meeting_microphone_device="auto",
                )
            )

    def _config_checks(self, inventory, **kwargs):
        devices = [
            AudioDevice(
                index=index,
                name=name,
                max_input_channels=2 if kind == "input" else 0,
                max_output_channels=2 if kind == "output" else 0,
                default_sample_rate=48000.0,
                host_api="Windows WASAPI",
            )
            for kind, index, name in inventory
        ]

        def list_devices(kind=None):
            if kind == "input":
                return [device for device in devices if device.max_input_channels > 0]
            if kind == "output":
                return [device for device in devices if device.max_output_channels > 0]
            return devices

        config = self._outbound_config()
        buffer = io.StringIO()
        with (
            patch("live_translator.audio.devices.list_devices", side_effect=list_devices),
            patch("live_translator.profiles.list_devices", side_effect=list_devices),
            patch(
                "live_translator.audio.devices._sounddevice",
                return_value=SimpleNamespace(default=SimpleNamespace(device=(30, 40))),
            ),
            patch(
                "live_translator.cli._audio_device_detail",
                side_effect=lambda device, kind, rate, role: str(device),
            ),
            patch("live_translator.cli.TranslationEngine") as translation,
            patch("live_translator.cli.TtsSpeaker") as tts,
            redirect_stdout(buffer),
        ):
            passed = _print_config_checks(config, prepare_models=False, **kwargs)
        return passed, buffer.getvalue(), SimpleNamespace(translation=translation, tts=tts)

    def test_reports_the_second_cable_and_headset_with_reversed_languages(self) -> None:
        passed, output, mocks = self._config_checks(self.WITH_CABLE_B, inbound=True)

        self.assertTrue(passed, output)
        self.assertRegex(output, r"OK\s+inbound\.route\s+second cable in, headset out, no feedback loop")
        self.assertRegex(output, r"OK\s+inbound\.input\s+CABLE-B Output \(VB-Audio Virtual Cable B\)")
        self.assertRegex(output, r"OK\s+inbound\.output\s+Headphones \(Jabra Evolve2 65\)")
        self.assertRegex(output, r"OK\s+inbound\.mt\s+argos de->en")
        self.assertRegex(output, r"OK\s+inbound\.speech\s+piper models/tts/en_US-hfc_male-medium\.onnx")
        inbound_translation = mocks.translation.call_args_list[-1].args[0]
        self.assertEqual(inbound_translation.source_language, "de")
        self.assertEqual(inbound_translation.target_language, "en")

    def test_reports_selected_inbound_target_language(self) -> None:
        passed, output, mocks = self._config_checks(
            self.WITH_CABLE_B, inbound=True, their_language="en", inbound_target_language="de"
        )
        self.assertTrue(passed, output)
        self.assertRegex(output, r"OK\s+inbound\.mt\s+argos en->de")
        self.assertIn("models/tts/de_DE-thorsten-medium.onnx", output)
        self.assertEqual(mocks.translation.call_args_list[-1].args[0].target_language, "de")

    def test_without_the_second_cable_gives_one_reason_and_skips_the_rest(self) -> None:
        without_cable_b = [entry for entry in self.WITH_CABLE_B if "CABLE-B" not in entry[2]]

        passed, output, mocks = self._config_checks(without_cable_b, inbound=True)

        self.assertFalse(passed)
        self.assertRegex(output, r"FAIL\s+inbound\.route\s+The inbound direction needs a second virtual cable")
        for label in ("inbound.input", "inbound.output", "inbound.mt", "inbound.speech"):
            self.assertRegex(output, rf"FAIL\s+{label}\s+skipped: inbound\.route failed")
        # Only the outbound direction's translation was loaded.
        self.assertEqual(mocks.translation.call_count, 1)

    def test_inbound_checks_are_opt_in(self) -> None:
        passed, output, _ = self._config_checks(self.WITH_CABLE_B)

        self.assertTrue(passed, output)
        self.assertNotIn("inbound.", output)
        self.assertFalse(build_parser().parse_args(["doctor"]).inbound)

    def test_inbound_without_a_profile_fails_instead_of_no_op(self) -> None:
        args = argparse.Namespace(
            config=None, profile=None, prepare_models=False, inbound=True, their_language=None
        )

        with self.assertRaisesRegex(ValueError, "--inbound needs a profile"):
            with redirect_stdout(io.StringIO()):
                cmd_doctor(args)


class DoctorParserTests(unittest.TestCase):
    def test_prepare_models_flag_is_opt_in(self) -> None:
        parser = build_parser()

        self.assertIs(parser.parse_args(["doctor"]).func, cmd_doctor)
        self.assertFalse(parser.parse_args(["doctor"]).prepare_models)
        self.assertTrue(parser.parse_args(["doctor", "--prepare-models"]).prepare_models)

    def test_profile_is_not_defaulted(self) -> None:
        """A bare `doctor` must not require a profile to exist on disk."""
        parser = build_parser()

        self.assertIsNone(parser.parse_args(["doctor"]).profile)
        self.assertEqual(parser.parse_args(["doctor", "--profile", "en-de"]).profile, "en-de")


if __name__ == "__main__":
    unittest.main()
