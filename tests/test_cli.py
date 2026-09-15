import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from live_translator.asr.model_store import recorded_revision
from live_translator.audio.devices import AudioDevice
from live_translator.cli import build_parser, cmd_prepare_models, main
from live_translator.defaults import ASR_MODEL_REVISION
from live_translator.config import AppConfig
from live_translator.profiles import inbound_config, validate_inbound_config, write_meeting_profile
from test_model_store import network_blocked, prepare_dir


def _converse_device(index: int, name: str, *, inputs: int = 0, outputs: int = 0) -> AudioDevice:
    return AudioDevice(
        index=index,
        name=name,
        max_input_channels=inputs,
        max_output_channels=outputs,
        default_sample_rate=48000.0,
        host_api="Windows WASAPI",
    )


CONVERSE_DEVICES = [
    _converse_device(30, "Microphone (Jabra Evolve2 65)", inputs=1),
    _converse_device(33, "CABLE-A Output (VB-Audio Virtual Cable A)", inputs=2),
    _converse_device(31, "CABLE-B Output (VB-Audio Virtual Cable B)", inputs=2),
    _converse_device(26, "CABLE-A Input (VB-Audio Virtual Cable A)", outputs=2),
    _converse_device(24, "CABLE-B Input (VB-Audio Virtual Cable B)", outputs=2),
    _converse_device(40, "Headphones (Jabra Evolve2 65)", outputs=2),
]


def _list_converse_devices(kind: str | None = None) -> list[AudioDevice]:
    if kind == "input":
        return [device for device in CONVERSE_DEVICES if device.max_input_channels > 0]
    if kind == "output":
        return [device for device in CONVERSE_DEVICES if device.max_output_channels > 0]
    return list(CONVERSE_DEVICES)


class ConverseTests(unittest.TestCase):
    """converse with a real config, real device resolution and the real route guard.

    Only the device inventory, audio start-up, pipelines and the session are
    faked, so nothing loads models or opens a stream.
    """

    def _profile(self, temp_dir: str, direction: str) -> Path:
        return write_meeting_profile(
            path=Path(temp_dir) / f"{direction}.yaml",
            direction=direction,
            microphone_device="auto",
            translated_output_device="auto",
            meeting_microphone_device="auto",
        )

    def _run(self, argv: list[str]):
        stderr = io.StringIO()
        with (
            patch("live_translator.audio.devices.list_devices", side_effect=_list_converse_devices),
            # profiles imports list_devices by name, so patch it where it is used too.
            patch("live_translator.profiles.list_devices", side_effect=_list_converse_devices),
            patch(
                "live_translator.audio.devices._sounddevice",
                # Windows defaults: the Jabra microphone and the Jabra headphones.
                return_value=SimpleNamespace(default=SimpleNamespace(device=(30, 40))),
            ),
            patch("live_translator.cli.ensure_audio_ready"),
            patch("live_translator.cli.LocalTranslatorPipeline") as pipeline,
            patch("live_translator.cli.BidirectionalSession") as session,
            redirect_stdout(io.StringIO()),
            redirect_stderr(stderr),
        ):
            code = main(argv)
        return code, pipeline, session, stderr.getvalue()

    def test_derives_inbound_with_cable_b_in_and_headset_out(self) -> None:
        with TemporaryDirectory() as temp_dir:
            profile = self._profile(temp_dir, "en-de")
            code, pipeline, session, stderr = self._run(["converse", "--outbound-config", str(profile)])

        self.assertEqual(code, 0, stderr)
        outbound, inbound = (call.args[0] for call in pipeline.call_args_list)
        self.assertEqual(outbound.translation.target_language, "de")
        self.assertEqual(inbound.asr.source_language, "de")
        self.assertEqual(inbound.translation.source_language, "de")
        self.assertEqual(inbound.translation.target_language, "en")
        self.assertEqual(inbound.tts.model_path, "models/tts/en_US-hfc_male-medium.onnx")
        self.assertEqual(inbound.audio.input_device, "CABLE-B Output (VB-Audio Virtual Cable B)")
        self.assertEqual(inbound.audio.output_device, "Headphones (Jabra Evolve2 65)")
        self.assertIsNone(inbound.audio.peer_input_device)
        session.return_value.run.assert_called_once()

    def test_refuses_a_looping_inbound_profile_before_loading_anything(self) -> None:
        # A de-en profile written by setup plays into the outbound cable, which
        # for an inbound direction feeds translated speech back into the meeting.
        with TemporaryDirectory() as temp_dir:
            outbound = self._profile(temp_dir, "en-de")
            inbound = self._profile(temp_dir, "de-en")
            code, pipeline, session, stderr = self._run(
                ["converse", "--outbound-config", str(outbound), "--inbound-config", str(inbound)]
            )

        self.assertEqual(code, 1)
        self.assertIn("is a virtual device", stderr)
        pipeline.assert_not_called()
        session.assert_not_called()

    def test_explicit_inbound_language_and_voice_are_validated_before_startup(self) -> None:
        cases = (
            ("en-de", "en_US", False, "must use de->en"),
            ("de-en", "de_DE", False, "English Piper voice"),
            ("de-en", "en_US", True, ""),
        )
        for direction, voice_language, accepted, error in cases:
            with self.subTest(direction=direction, voice_language=voice_language), TemporaryDirectory() as temp:
                outbound = self._profile(temp, "en-de")
                explicit = Path(temp) / "inbound.yaml"
                payload = yaml.safe_load(self._profile(temp, direction).read_text())
                payload["audio"].update(input_device=CONVERSE_DEVICES[2].name,
                                        output_device=CONVERSE_DEVICES[-1].name)
                explicit.write_text(yaml.safe_dump(payload))
                metadata = Path(temp) / "voice.onnx.json"
                metadata.write_text(json.dumps({"language": {"code": voice_language}}))
                with patch("live_translator.profiles.resolve_trusted_path",
                           side_effect=[Path(temp) / "voice.onnx", metadata]):
                    code, pipeline, session, stderr = self._run(
                        ["converse", "--outbound-config", str(outbound), "--inbound-config", str(explicit)]
                    )
                self.assertEqual(code, 0 if accepted else 1, stderr)
                if accepted:
                    session.return_value.run.assert_called_once()
                else:
                    self.assertIn(error, stderr)
                    pipeline.assert_not_called()
                    session.assert_not_called()

    def test_inbound_validator_explains_a_missing_voice_path(self) -> None:
        outbound = AppConfig()
        inbound = inbound_config(outbound)
        for missing in (None, ""):
            with self.subTest(model_path=missing):
                invalid = replace(inbound, tts=replace(inbound.tts, engine="piper", model_path=missing))
                with patch("live_translator.profiles.resolve_trusted_path") as resolve:
                    with self.assertRaisesRegex(ValueError, "tts.model_path is required"):
                        validate_inbound_config(outbound, invalid)
                resolve.assert_not_called()

    def test_explicit_inbound_without_voice_path_reports_a_config_error(self) -> None:
        with TemporaryDirectory() as temp:
            outbound = self._profile(temp, "en-de")
            explicit = self._profile(temp, "de-en")
            payload = yaml.safe_load(explicit.read_text())
            del payload["tts"]["model_path"]
            explicit.write_text(yaml.safe_dump(payload))
            code, pipeline, session, stderr = self._run(
                ["converse", "--outbound-config", str(outbound), "--inbound-config", str(explicit)]
            )
        self.assertEqual(code, 1)
        self.assertIn("tts.model_path is required", stderr)
        self.assertNotIn("Traceback", stderr)
        pipeline.assert_not_called()
        session.assert_not_called()

    def test_their_language_needs_a_derived_inbound_direction(self) -> None:
        with TemporaryDirectory() as temp_dir:
            outbound = self._profile(temp_dir, "en-de")
            inbound = self._profile(temp_dir, "de-en")
            code, pipeline, session, stderr = self._run(
                [
                    "converse",
                    "--outbound-config",
                    str(outbound),
                    "--inbound-config",
                    str(inbound),
                    "--their-language",
                    "de",
                ]
            )

        self.assertEqual(code, 1)
        self.assertIn("--their-language", stderr)
        session.assert_not_called()


class RouteTestInboundTests(unittest.TestCase):
    def _run(self, extra_args: list[str], *, passed: bool = True):
        stdout = io.StringIO()
        result = SimpleNamespace(passed=passed, tone_rms=0.1400, tone_ratio=0.99, sample_rate=48000)
        with TemporaryDirectory() as temp_dir:
            profile = write_meeting_profile(
                path=Path(temp_dir) / "en-de.yaml",
                direction="en-de",
                microphone_device="auto",
                translated_output_device="auto",
                meeting_microphone_device="auto",
            )
            with (
                patch("live_translator.cli.test_output_to_input_route", return_value=result) as route,
                patch(
                    "live_translator.cli.describe_device_selection",
                    side_effect=lambda name, kind, role: f"<{role}>",
                ),
                redirect_stdout(stdout),
                redirect_stderr(io.StringIO()),
            ):
                code = main(["route-test", "--config", str(profile), *extra_args])
        return code, route, stdout.getvalue()

    def test_inbound_plays_into_the_second_cable_and_listens_where_inbound_captures(self) -> None:
        code, route, output = self._run(["--inbound"])

        self.assertEqual(code, 0, output)
        self.assertEqual(route.call_args.kwargs["output_role"], "remote_playback")
        self.assertEqual(route.call_args.kwargs["input_role"], "remote_input")
        self.assertIn("PASS: <remote_playback> -> <remote_input>", output)

    def test_inbound_failure_says_the_inbound_direction_will_not_hear_the_meeting(self) -> None:
        code, _, output = self._run(["--inbound"], passed=False)

        self.assertEqual(code, 1)
        self.assertIn("FAIL: <remote_playback> -> <remote_input>", output)
        self.assertIn("inbound direction", output)

    def test_outbound_route_test_keeps_its_roles(self) -> None:
        code, route, output = self._run([])

        self.assertEqual(code, 0, output)
        self.assertEqual(route.call_args.kwargs["output_role"], "translated_output")
        self.assertEqual(route.call_args.kwargs["input_role"], "meeting_input")
        self.assertIn("PASS: <translated_output> -> <meeting_input>", output)


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

    def setUp(self) -> None:
        integrity = patch("live_translator.asr.model_store.verify_manifest_root")
        integrity.start()
        self.addCleanup(integrity.stop)

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
