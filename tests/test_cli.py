import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import yaml

from live_translator.asr.model_store import recorded_revision
from live_translator.cli import build_parser, cmd_prepare_models, main
from live_translator.defaults import ASR_MODEL_REVISION
from test_model_store import network_blocked, prepare_dir


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


class PrepareModelsCommandTests(unittest.TestCase):
    """`prepare-models` is the only command allowed to download a model, which
    makes it the only place these assertions can live -- and makes the absence
    of a download everywhere else meaningful."""

    def write_profile(self, root: Path, model_dir: Path) -> Path:
        path = root / "en-de.yaml"
        path.write_text(
            yaml.safe_dump({"asr": {"model_dir": str(model_dir)}}),
            encoding="utf-8",
        )
        return path

    def test_downloads_the_pinned_revision_when_nothing_is_prepared(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_dir = root / "parakeet"
            profile = self.write_profile(root, model_dir)

            def fake_download(repo_id, **kwargs):
                prepare_dir(Path(kwargs["local_dir"]), revision=None)
                return kwargs["local_dir"]

            with patch("huggingface_hub.snapshot_download", side_effect=fake_download) as spy:
                with redirect_stdout(io.StringIO()):
                    code = cmd_prepare_models(
                        build_parser().parse_args(["prepare-models", "--config", str(profile)])
                    )

            self.assertEqual(code, 0)
            self.assertEqual(spy.call_args.kwargs["revision"], ASR_MODEL_REVISION)

    def test_an_already_prepared_machine_needs_no_network(self) -> None:
        """Re-running preparation is the normal state on a machine that is
        already set up, so it must not be the thing that reaches out."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_dir = prepare_dir(root / "parakeet")
            profile = self.write_profile(root, model_dir)

            with network_blocked():
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    code = cmd_prepare_models(
                        build_parser().parse_args(["prepare-models", "--config", str(profile)])
                    )

        self.assertEqual(code, 0)
        self.assertIn("Already prepared", buffer.getvalue())

    def test_re_downloads_when_the_prepared_revision_is_stale(self) -> None:
        """After a build bumps the pinned revision, re-running preparation must
        replace the out-of-date model rather than accept it: verify_local_model
        rejects the old revision and prepare-models falls through to a download."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_dir = prepare_dir(root / "parakeet", revision="0" * 40)
            profile = self.write_profile(root, model_dir)

            def fake_download(repo_id, **kwargs):
                prepare_dir(Path(kwargs["local_dir"]), revision=None)
                return kwargs["local_dir"]

            with patch("huggingface_hub.snapshot_download", side_effect=fake_download) as spy:
                with redirect_stdout(io.StringIO()):
                    code = cmd_prepare_models(
                        build_parser().parse_args(["prepare-models", "--config", str(profile)])
                    )

            self.assertEqual(code, 0)
            spy.assert_called_once()
            self.assertEqual(spy.call_args.kwargs["revision"], ASR_MODEL_REVISION)
            self.assertEqual(recorded_revision(model_dir), ASR_MODEL_REVISION)

    def test_custom_model_with_a_missing_directory_says_to_stage_it(self) -> None:
        """prepare-models for a non-default asr.model must not fetch the pinned
        default into the custom directory -- it should tell the operator to
        stage that model by hand, without touching the network."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = root / "custom.yaml"
            profile.write_text(
                yaml.safe_dump(
                    {
                        "asr": {
                            "model": "nemo-parakeet-tdt-0.6b-v2",
                            "model_dir": str(root / "staged"),
                        }
                    }
                ),
                encoding="utf-8",
            )

            errors = io.StringIO()
            with network_blocked():
                with patch("sys.stderr", errors):
                    code = main(["prepare-models", "--config", str(profile)])

        self.assertEqual(code, 1)
        self.assertIn("cannot be downloaded", errors.getvalue())

    def test_missing_default_profile_points_at_setup(self) -> None:
        """Running prepare-models before setup has created a profile should name
        the fix command, like every other error in this feature, rather than a
        bare 'Config file not found'."""
        with TemporaryDirectory() as tmp:
            missing = Path(tmp) / "default.yaml"
            with patch("live_translator.cli.default_profile_path", return_value=missing):
                errors = io.StringIO()
                with patch("sys.stderr", errors):
                    code = main(["prepare-models"])

        self.assertEqual(code, 1)
        self.assertIn("setup --profile default", errors.getvalue())

    def test_meeting_on_an_unprepared_machine_reports_how_to_prepare(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = self.write_profile(root, root / "never-prepared")

            errors = io.StringIO()
            with network_blocked():
                with patch("sys.stderr", errors):
                    code = main(["meeting", "--config", str(profile)])

        self.assertEqual(code, 1)
        self.assertIn("prepare-models", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
