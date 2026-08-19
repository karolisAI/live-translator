import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import yaml

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
