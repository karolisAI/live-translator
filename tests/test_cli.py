import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from live_translator.cli import build_parser, main


class CliTests(unittest.TestCase):
    def test_say_config_does_not_force_tts_engine(self) -> None:
        args = build_parser().parse_args(
            ["say", "--config", "app.example.yaml", "--text", "test"]
        )

        self.assertIsNone(args.tts_engine)

    def test_setup_accepts_de_en_direction(self) -> None:
        args = build_parser().parse_args(
            [
                "setup",
                "--direction",
                "de-en",
                "--input-device",
                "Mic",
                "--translated-output-device",
                "Cable Input",
                "--meeting-microphone-device",
                "Cable Output",
            ]
        )

        self.assertEqual(args.direction, "de-en")

    def test_meeting_accepts_vad_chunker(self) -> None:
        args = build_parser().parse_args(
            [
                "meeting",
                "--profile",
                "en-de",
                "--chunker",
                "vad",
                "--log-prob-threshold",
                "-1.7",
                "--input-gain",
                "1.8",
                "--debug-audio-dir",
                "debug-audio",
                "--silence-ms",
                "450",
                "--peak-threshold",
                "0.04",
                "--min-active-ratio",
                "0.12",
                "--min-segment-seconds",
                "1.4",
                "--rolling-window-seconds",
                "2.4",
            ]
        )

        self.assertEqual(args.chunker, "vad")
        self.assertEqual(args.log_prob_threshold, -1.7)
        self.assertEqual(args.input_gain, 1.8)
        self.assertEqual(args.debug_audio_dir, "debug-audio")
        self.assertEqual(args.silence_ms, 450)
        self.assertEqual(args.peak_threshold, 0.04)
        self.assertEqual(args.min_active_ratio, 0.12)
        self.assertEqual(args.min_segment_seconds, 1.4)
        self.assertEqual(args.rolling_window_seconds, 2.4)

    def test_meeting_accepts_rolling_chunker(self) -> None:
        args = build_parser().parse_args(
            [
                "meeting",
                "--profile",
                "en-de",
                "--chunker",
                "rolling",
            ]
        )

        self.assertEqual(args.chunker, "rolling")


class DiagnosticsFlagTests(unittest.TestCase):
    """Capture must take a deliberate act. Parsing is where that starts."""

    def test_meeting_defaults_to_no_capture(self) -> None:
        args = build_parser().parse_args(["meeting", "--profile", "en-de"])

        self.assertFalse(args.diagnostics)
        self.assertIsNone(args.debug_audio_dir)

    def test_meeting_accepts_the_diagnostics_flag(self) -> None:
        args = build_parser().parse_args(["meeting", "--profile", "en-de", "--diagnostics"])

        self.assertTrue(args.diagnostics)

    def test_loopback_accepts_the_diagnostics_flag(self) -> None:
        args = build_parser().parse_args(["loopback", "--diagnostics"])

        self.assertTrue(args.diagnostics)


    def test_purge_diagnostics_defaults_to_asking_first(self) -> None:
        args = build_parser().parse_args(["purge-diagnostics"])

        self.assertFalse(args.yes)

    def test_purge_diagnostics_accepts_yes_for_scripts(self) -> None:
        args = build_parser().parse_args(["purge-diagnostics", "--yes", "--profile", "en-de"])

        self.assertTrue(args.yes)
        self.assertEqual(args.profile, "en-de")


class PurgeCommandTests(unittest.TestCase):
    """Runs the command, not just the parser.

    The parser tests passed while the command raised NameError on its first
    real invocation, because nothing imported AppConfig. Parsing a command is
    not evidence that it works.
    """

    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name) / "diagnostics"
        patcher = patch("live_translator.diagnostics.diagnostics_dir", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _capture(self, phrases: int = 2) -> Path:
        session = self.root / "session-20260820-120000-1"
        session.mkdir(parents=True)
        for n in range(1, phrases + 1):
            (session / f"segment-{n:04d}.wav").write_bytes(b"x" * 2048)
            (session / f"segment-{n:04d}.txt").write_text("source=x", encoding="utf-8")
        return session

    def _run(self, argv: list[str]) -> tuple[int, str]:
        buffer = io.StringIO()
        # stderr too: the refusal message is printed there, and an
        # uncaptured one makes a passing test look like a failure in
        # the suite output.
        with redirect_stdout(buffer), redirect_stderr(buffer):
            code = main(argv)
        return code, buffer.getvalue()

    def test_purge_removes_the_capture_and_reports_it(self) -> None:
        self._capture()

        code, output = self._run(["purge-diagnostics", "--yes"])

        self.assertEqual(code, 0, output)
        self.assertIn("Removed 4 file(s)", output)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_purge_with_nothing_captured_succeeds_quietly(self) -> None:
        self.root.mkdir(parents=True)

        code, output = self._run(["purge-diagnostics", "--yes"])

        self.assertEqual(code, 0, output)
        self.assertIn("Nothing to remove", output)

    def test_purge_refuses_a_directory_it_did_not_fill(self) -> None:
        self.root.mkdir(parents=True)
        (self.root / "tax-return.pdf").write_bytes(b"x" * 64)

        code, output = self._run(["purge-diagnostics", "--yes"])

        self.assertEqual(code, 1, output)
        self.assertIn("Refusing to delete anything", output)
        self.assertTrue((self.root / "tax-return.pdf").exists())


    def test_meeting_accepts_show_text(self) -> None:
        args = build_parser().parse_args(["meeting", "--profile", "en-de", "--show-text"])

        self.assertTrue(args.show_text)
        self.assertFalse(args.diagnostics)

    def test_loopback_accepts_show_text(self) -> None:
        args = build_parser().parse_args(["loopback", "--show-text"])

        self.assertTrue(args.show_text)


if __name__ == "__main__":
    unittest.main()
