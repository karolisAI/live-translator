from __future__ import annotations

import argparse
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from live_translator.cli import _print_config_checks, build_parser, cmd_doctor, main
from live_translator.config import AppConfig
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
