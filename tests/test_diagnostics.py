"""Config and path rules for captured meeting content.

Two questions settled here: what the config says by default and which
directory a setting resolves to, then whether a session captures anything
at all. The activation tests are the ticket's first test case: a normal
meeting must leave no audio, transcript or translation behind.
"""

import io
import unittest
from datetime import datetime
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from live_translator.config import AppConfig, DiagnosticsSettings, load_config
from live_translator.pipeline import LocalTranslatorPipeline
from live_translator.diagnostics import (
    capture_warning,
    segment_note_name,
    session_directory_name,
    resolve_capture_dir,
    segment_audio_name,
)


class DiagnosticsDefaultsTests(unittest.TestCase):
    def test_capture_is_off_in_the_shipped_defaults(self) -> None:
        """The ticket's central acceptance criterion, asserted directly."""
        self.assertFalse(AppConfig().diagnostics.enabled)

    def test_retention_defaults_are_the_provisional_numbers(self) -> None:
        settings = AppConfig().diagnostics

        self.assertEqual(settings.retention_days, 7)
        self.assertEqual(settings.max_total_mb, 500)

    def test_config_file_can_enable_capture_without_a_cli_flag(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "app.yaml"
            config_path.write_text(
                "diagnostics:\n  enabled: true\n  retention_days: 3\n", encoding="utf-8"
            )

            config = load_config(config_path)

        self.assertTrue(config.diagnostics.enabled)
        self.assertEqual(config.diagnostics.retention_days, 3)
        self.assertEqual(config.diagnostics.max_total_mb, 500)

    def test_omitted_section_leaves_capture_off(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "app.yaml"
            config_path.write_text("asr:\n  device: cpu\n", encoding="utf-8")

            self.assertFalse(load_config(config_path).diagnostics.enabled)

    def test_unknown_key_is_rejected_rather_than_ignored(self) -> None:
        """A misspelled key must not read as 'capture stayed off, all good'."""
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "app.yaml"
            config_path.write_text("diagnostics:\n  enable: true\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                load_config(config_path)


class CaptureDirectoryTests(unittest.TestCase):
    """Every path must land under the per-user directory unless the user was
    explicit about an absolute one. The working directory is usually a
    checkout, which is how transcripts end up beside source code."""

    def setUp(self) -> None:
        self.root = Path(r"C:\Users\test\AppData\Local\LiveTranslator\diagnostics")
        patcher = patch("live_translator.diagnostics.diagnostics_dir", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_default_is_the_per_user_directory(self) -> None:
        self.assertEqual(resolve_capture_dir(DiagnosticsSettings()), self.root)

    def test_relative_config_path_is_placed_under_the_per_user_directory(self) -> None:
        settings = DiagnosticsSettings(dir="capture")

        self.assertEqual(resolve_capture_dir(settings), self.root / "capture")

    def test_relative_cli_path_does_not_land_in_the_working_directory(self) -> None:
        """`--debug-audio-dir debug-asr` is what the README used to teach, and
        it wrote into whatever directory the user was standing in."""
        resolved = resolve_capture_dir(DiagnosticsSettings(), "debug-asr")

        self.assertEqual(resolved, self.root / "debug-asr")
        self.assertNotEqual(resolved, Path("debug-asr").resolve())

    def test_absolute_path_is_honoured_as_given(self) -> None:
        resolved = resolve_capture_dir(DiagnosticsSettings(), r"D:\scratch\asr")

        self.assertEqual(resolved, Path(r"D:\scratch\asr"))

    def test_cli_path_wins_over_the_config_setting(self) -> None:
        settings = DiagnosticsSettings(dir="from-config")

        self.assertEqual(resolve_capture_dir(settings, "from-cli"), self.root / "from-cli")

    def test_relative_path_climbing_out_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            resolve_capture_dir(DiagnosticsSettings(), r"..\..\..\Desktop")


class ArtifactNameTests(unittest.TestCase):
    def test_names_are_zero_padded_and_paired(self) -> None:
        self.assertEqual(segment_audio_name(7), "segment-0007.wav")
        self.assertEqual(segment_note_name(7), "segment-0007.txt")

    def test_note_is_named_by_the_module_that_names_the_audio(self) -> None:
        """The writer derives the note from the WAV path, so both names have
        to come from here or the ignore rule can outlive the filename.
        """
        from live_translator.diagnostics import NOTE_SUFFIX

        self.assertTrue(segment_note_name(7).endswith(NOTE_SUFFIX))
        self.assertEqual(
            Path(segment_audio_name(7)).with_suffix(NOTE_SUFFIX).name, segment_note_name(7)
        )

    def test_session_name_carries_a_stamp_and_the_process_id(self) -> None:
        name = session_directory_name(datetime(2026, 8, 19, 14, 32, 5))

        self.assertTrue(name.startswith("session-20260819-143205-"))


class CaptureActivationTests(unittest.TestCase):
    """Nothing is captured, and no directory is even created, until somebody
    asks. This is the ticket's first test case: a normal meeting must leave no
    audio, transcript or translation artifact behind."""

    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name) / "diagnostics"
        patcher = patch("live_translator.diagnostics.diagnostics_dir", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _start(self, *, config=None, diagnostics=False, debug_audio_dir=None):
        pipeline = LocalTranslatorPipeline(config or AppConfig())
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            result = pipeline._start_diagnostics(
                diagnostics=diagnostics, debug_audio_dir=debug_audio_dir
            )
        return result, buffer.getvalue()

    def test_normal_run_captures_nothing_and_creates_no_directory(self) -> None:
        result, output = self._start()

        self.assertIsNone(result)
        self.assertFalse(self.root.exists(), "a normal meeting must not create the directory")
        self.assertEqual(output, "")

    def test_flag_turns_capture_on(self) -> None:
        result, _ = self._start(diagnostics=True)

        self.assertEqual(result.parent, self.root)
        self.assertTrue(result.is_dir())

    def test_config_setting_turns_capture_on_without_a_flag(self) -> None:
        config = AppConfig(diagnostics=DiagnosticsSettings(enabled=True))

        result, _ = self._start(config=config)

        self.assertEqual(result.parent, self.root)

    def test_explicit_path_implies_the_flag(self) -> None:
        """`--debug-audio-dir` is what people already type; it must keep working."""
        result, _ = self._start(debug_audio_dir="from-cli")

        self.assertEqual(result.parent, self.root / "from-cli")
        self.assertTrue(result.is_dir())

    def test_capture_that_cannot_start_does_not_end_the_meeting(self) -> None:
        """Diagnostics are a convenience; the meeting is the product. A
        directory that cannot be created must not raise out of loopback().
        """
        self.root.parent.mkdir(parents=True, exist_ok=True)
        self.root.write_text("a file is in the way", encoding="utf-8")

        result, output = self._start(diagnostics=True)

        self.assertIsNone(result)
        self.assertIn("could not start", output)
        self.assertIn("meeting is not affected", output)

    def test_two_sessions_do_not_share_a_directory(self) -> None:
        """Phrase numbers restart at 1, so a shared directory means the
        second meeting overwrites the first one's transcripts.
        """
        first, _ = self._start(diagnostics=True)
        with patch("live_translator.diagnostics.os.getpid", return_value=999999):
            second, _ = self._start(diagnostics=True)

        self.assertNotEqual(first, second)
        self.assertEqual(first.parent, second.parent)

    def test_activation_warns_rather_than_reporting_status(self) -> None:
        _, output = self._start(diagnostics=True)

        self.assertIn("WARNING", output)
        self.assertIn(str(self.root), output)
        self.assertIn("transcript", output)
        self.assertIn("translation", output)


class CaptureWarningTests(unittest.TestCase):
    def test_warning_names_both_kinds_of_artifact(self) -> None:
        """The message this replaced said only "debug audio chunks", naming the
        large obvious file and not the readable one beside it."""
        text = capture_warning(Path(r"C:\some\where"))

        self.assertIn("segment-NNNN.wav", text)
        self.assertIn("segment-NNNN.txt", text)
        self.assertIn(r"C:\some\where", text)


if __name__ == "__main__":
    unittest.main()