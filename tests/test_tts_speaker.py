import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np

from live_translator.config import AudioSettings, TtsSettings
from live_translator.errors import UntrustedRuntimePath
from live_translator.tts.speaker import TtsSpeaker, resolve_piper_exe


class TtsSpeakerTests(unittest.TestCase):
    def test_piper_length_scale_is_passed_explicitly(self) -> None:
        speaker = TtsSpeaker(
            TtsSettings(
                engine="piper",
                model_path="voice.onnx",
                length_scale=1.0,
            ),
            AudioSettings(),
        )

        with (
            patch.object(
                speaker,
                "_resolve_piper_assets",
                return_value=("piper.exe", Path("voice.onnx")),
            ),
            patch(
                "live_translator.tts.speaker.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ) as run,
            patch(
                "live_translator.tts.speaker.read_wav_mono",
                return_value=(np.zeros(160, dtype=np.float32), 16000),
            ),
            patch("live_translator.tts.speaker.play_mono"),
        ):
            speaker.speak("Hello")

        command = run.call_args.args[0]
        self.assertEqual(command[-2:], ["--length_scale", "1.0"])

    def test_piper_runs_as_an_argument_list_without_a_shell(self) -> None:
        """Regression lock: subprocess.run must receive a list, never a shell
        string, and must never be invoked with shell=True -- a list command
        is what keeps text passed to Piper from being interpreted by a shell
        at all."""
        speaker = TtsSpeaker(
            TtsSettings(engine="piper", model_path="voice.onnx"),
            AudioSettings(),
        )

        with (
            patch.object(
                speaker,
                "_resolve_piper_assets",
                return_value=("piper.exe", Path("voice.onnx")),
            ),
            patch(
                "live_translator.tts.speaker.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ) as run,
            patch(
                "live_translator.tts.speaker.read_wav_mono",
                return_value=(np.zeros(160, dtype=np.float32), 16000),
            ),
            patch("live_translator.tts.speaker.play_mono"),
        ):
            speaker.speak("Hello")

        command = run.call_args.args[0]
        self.assertIsInstance(command, list)
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_os_error_from_subprocess_becomes_a_clear_runtime_error(self) -> None:
        """A trusted, existing piper_exe can still fail to actually run --
        permissions, a corrupted binary, or (Windows) 'not a valid Win32
        application'. subprocess.run raises OSError for these rather than
        returning a CompletedProcess, so it must not propagate raw."""
        speaker = TtsSpeaker(
            TtsSettings(engine="piper", model_path="voice.onnx"),
            AudioSettings(),
        )

        with (
            patch.object(
                speaker,
                "_resolve_piper_assets",
                return_value=("piper.exe", Path("voice.onnx")),
            ),
            patch(
                "live_translator.tts.speaker.subprocess.run",
                side_effect=PermissionError("Access is denied"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "piper.exe"):
                speaker.speak("Hello")

    def test_piper_runs_with_the_configured_timeout(self) -> None:
        speaker = TtsSpeaker(
            TtsSettings(engine="piper", model_path="voice.onnx", piper_timeout_seconds=45.0),
            AudioSettings(),
        )

        with (
            patch.object(
                speaker,
                "_resolve_piper_assets",
                return_value=("piper.exe", Path("voice.onnx")),
            ),
            patch(
                "live_translator.tts.speaker.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ) as run,
            patch(
                "live_translator.tts.speaker.read_wav_mono",
                return_value=(np.zeros(160, dtype=np.float32), 16000),
            ),
            patch("live_translator.tts.speaker.play_mono"),
        ):
            speaker.speak("Hello")

        self.assertEqual(run.call_args.kwargs["timeout"], 45.0)

    def test_a_hanging_piper_process_is_terminated_and_reported_clearly(self) -> None:
        """subprocess.run(timeout=...) already kills the child process itself
        when it fires -- this only needs to confirm that TimeoutExpired
        becomes a clear error instead of propagating raw."""
        speaker = TtsSpeaker(
            TtsSettings(engine="piper", model_path="voice.onnx", piper_timeout_seconds=5.0),
            AudioSettings(),
        )

        with (
            patch.object(
                speaker,
                "_resolve_piper_assets",
                return_value=("piper.exe", Path("voice.onnx")),
            ),
            patch(
                "live_translator.tts.speaker.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["piper.exe"], timeout=5.0),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "did not finish within"):
                speaker.speak("Hello")

    def test_warm_up_survives_a_hanging_piper_process(self) -> None:
        """warm_up()'s existing broad except must also cover a timeout, not
        just an ordinary synthesis failure -- a slow first phrase is still
        the acceptable outcome, not a dead startup."""
        speaker = TtsSpeaker(
            TtsSettings(engine="piper", model_path="voice.onnx", piper_timeout_seconds=5.0),
            AudioSettings(),
        )

        with (
            patch.object(
                speaker,
                "_resolve_piper_assets",
                return_value=("piper.exe", Path("voice.onnx")),
            ),
            patch(
                "live_translator.tts.speaker.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["piper.exe"], timeout=5.0),
            ),
        ):
            speaker.warm_up()  # must not raise

    def test_warm_up_synthesizes_once_without_playing(self) -> None:
        """The point of warming up is to pay Piper's first-run cost at startup.
        Playing the warm-up audio would put a noise into the meeting instead."""
        speaker = TtsSpeaker(
            TtsSettings(engine="piper", model_path="voice.onnx"),
            AudioSettings(),
        )

        with (
            patch.object(
                speaker,
                "_resolve_piper_assets",
                return_value=("piper.exe", Path("voice.onnx")),
            ),
            patch(
                "live_translator.tts.speaker.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ) as run,
            patch("live_translator.tts.speaker.play_mono") as play,
        ):
            speaker.warm_up()

        self.assertEqual(run.call_count, 1)
        play.assert_not_called()

    def test_warm_up_is_skipped_when_piper_is_not_the_engine(self) -> None:
        speaker = TtsSpeaker(TtsSettings(engine="none"), AudioSettings())

        with patch("live_translator.tts.speaker.subprocess.run") as run:
            speaker.warm_up()

        run.assert_not_called()

    def test_warm_up_failure_does_not_stop_startup(self) -> None:
        """A warm-up that cannot run means a slow first phrase, not a dead session."""
        speaker = TtsSpeaker(
            TtsSettings(engine="piper", model_path="voice.onnx"),
            AudioSettings(),
        )

        with (
            patch.object(
                speaker,
                "_resolve_piper_assets",
                return_value=("piper.exe", Path("voice.onnx")),
            ),
            patch(
                "live_translator.tts.speaker.subprocess.run",
                return_value=subprocess.CompletedProcess([], 1, "", "piper exploded"),
            ),
        ):
            speaker.warm_up()  # must not raise


class ResolvePiperExeTests(unittest.TestCase):
    """resolve_piper_exe is a thin wrapper over resolve_trusted_path -- this
    covers its own contract (None on not-found, propagate on untrusted), not
    resolve_trusted_path's own search/containment logic (see test_runtime.py)."""

    def test_finds_an_executable_under_an_approved_root(self) -> None:
        with TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            exe = root / "tools" / "piper" / "piper.exe"
            exe.parent.mkdir(parents=True)
            exe.write_text("fake")

            with patch("live_translator.runtime.approved_runtime_roots", return_value=[root]):
                result = resolve_piper_exe("tools/piper/piper.exe")

            self.assertEqual(Path(result), exe.resolve())

    def test_returns_none_when_not_found_anywhere_approved(self) -> None:
        with TemporaryDirectory() as root_dir:
            with patch(
                "live_translator.runtime.approved_runtime_roots", return_value=[Path(root_dir)]
            ):
                result = resolve_piper_exe("tools/piper/piper.exe")

            self.assertIsNone(result)

    def test_a_cwd_only_executable_is_not_trusted(self) -> None:
        """The actual regression this guards: piper.exe sitting only in the
        working directory must never resolve, even though it used to."""
        with TemporaryDirectory() as approved_dir, TemporaryDirectory() as cwd_dir:
            fake_in_cwd = Path(cwd_dir) / "tools" / "piper" / "piper.exe"
            fake_in_cwd.parent.mkdir(parents=True)
            fake_in_cwd.write_text("fake")

            original_cwd = os.getcwd()
            os.chdir(cwd_dir)
            try:
                with patch(
                    "live_translator.runtime.approved_runtime_roots",
                    return_value=[Path(approved_dir)],
                ):
                    result = resolve_piper_exe("tools/piper/piper.exe")
            finally:
                os.chdir(original_cwd)

            self.assertIsNone(result)

    def test_untrusted_path_propagates_rather_than_becoming_none(self) -> None:
        """An executable that exists but isn't under an approved root is a
        different, more actionable situation than 'nothing installed' --
        collapsing it to None would hide that distinction from the caller."""
        with TemporaryDirectory() as approved_dir, TemporaryDirectory() as elsewhere_dir:
            untrusted_exe = Path(elsewhere_dir) / "piper.exe"
            untrusted_exe.write_text("fake")

            with patch(
                "live_translator.runtime.approved_runtime_roots",
                return_value=[Path(approved_dir)],
            ):
                with self.assertRaises(UntrustedRuntimePath):
                    resolve_piper_exe(str(untrusted_exe))


if __name__ == "__main__":
    unittest.main()
