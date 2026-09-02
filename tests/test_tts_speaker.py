import json
import os
import unittest
from pathlib import Path
from queue import Queue
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import Mock, patch

import numpy as np

from live_translator.config import AudioSettings, TtsSettings
from live_translator.errors import UntrustedRuntimePath
from live_translator.tts.speaker import TtsSpeaker, resolve_piper_exe


class _BlockingIter:
    """Blocks forever on the next item, simulating Piper going silent
    without exiting -- unlike an empty iterator, which ends (and so signals
    "process exited") immediately."""

    def __iter__(self):
        return self

    def __next__(self):
        Event().wait()
        raise AssertionError("unreachable")  # pragma: no cover


class _FakeProcess:
    """Stands in for what `subprocess.Popen` returns, so the resident-process
    mechanics (background reader threads, the response queue, is_alive) can
    be tested without a real `piper.exe`.

    `echo=True` answers each request with the `output_file` that request named,
    which is what the real binary does: verified against the bundled
    piper.exe, which prints the exact path, one line per request. Scripting
    `stdout_lines` instead is how a wrong, missing or absent answer is
    simulated.
    """

    def __init__(self, stdout_lines=(), stderr_lines=(), echo=False):
        self.stdin = Mock()
        self._requests: Queue = Queue()
        if echo:
            self.stdin.write.side_effect = self._record_request
            self.stdout = self._echo_requested_paths()
        else:
            self.stdout = iter(stdout_lines) if stdout_lines is not None else _BlockingIter()
        self.stderr = iter(stderr_lines)
        self._exited = False
        self.wait = Mock(return_value=0)
        self.kill = Mock(side_effect=self.mark_exited)

    def _record_request(self, data):
        text = data.strip()
        if text:
            self._requests.put(json.loads(text)["output_file"])

    def _echo_requested_paths(self):
        while True:
            yield self._requests.get() + "\n"

    def poll(self):
        return None if not self._exited else 1

    def mark_exited(self) -> None:
        self._exited = True


READ_WAV_STUB = (np.zeros(160, dtype=np.float32), 16000)


class TtsSpeakerTests(unittest.TestCase):
    def test_piper_length_scale_is_passed_at_process_startup(self) -> None:
        speaker = TtsSpeaker(
            TtsSettings(engine="piper", model_path="voice.onnx", length_scale=1.0),
            AudioSettings(),
        )
        fake = _FakeProcess(echo=True)

        with (
            patch.object(speaker, "_resolve_piper_assets", return_value=("piper.exe", Path("voice.onnx"))),
            patch("live_translator.tts.speaker.subprocess.Popen", return_value=fake) as popen,
            patch("live_translator.tts.speaker.read_wav_mono", return_value=READ_WAV_STUB),
            patch("live_translator.tts.speaker.play_mono"),
        ):
            speaker.speak("Hello")

        args = popen.call_args.args[0]
        self.assertEqual(args[-2:], ["--length_scale", "1.0"])

    def test_piper_runs_as_an_argument_list_without_a_shell(self) -> None:
        """Regression lock: Piper must be started from a list, never a shell
        string, and never with shell=True -- a list is what keeps text handed
        to it from being interpreted by a shell at all."""
        speaker = TtsSpeaker(
            TtsSettings(engine="piper", model_path="voice.onnx"),
            AudioSettings(),
        )
        fake = _FakeProcess(echo=True)

        with (
            patch.object(speaker, "_resolve_piper_assets", return_value=("piper.exe", Path("voice.onnx"))),
            patch("live_translator.tts.speaker.subprocess.Popen", return_value=fake) as popen,
            patch("live_translator.tts.speaker.read_wav_mono", return_value=READ_WAV_STUB),
            patch("live_translator.tts.speaker.play_mono"),
        ):
            speaker.speak("Hello")

        args = popen.call_args.args[0]
        self.assertIsInstance(args, list)
        self.assertNotIn("shell", popen.call_args.kwargs)

    def test_os_error_starting_piper_becomes_a_clear_runtime_error(self) -> None:
        """A trusted, existing piper_exe can still fail to actually start --
        permissions, a corrupted binary, or (Windows) 'not a valid Win32
        application'. Popen raises OSError for these; it must not propagate
        raw."""
        speaker = TtsSpeaker(
            TtsSettings(engine="piper", model_path="voice.onnx"),
            AudioSettings(),
        )

        with (
            patch.object(speaker, "_resolve_piper_assets", return_value=("piper.exe", Path("voice.onnx"))),
            patch("live_translator.tts.speaker.subprocess.Popen", side_effect=PermissionError("Access is denied")),
        ):
            with self.assertRaisesRegex(RuntimeError, "piper.exe"):
                speaker.speak("Hello")

    def test_a_hanging_piper_request_is_reported_within_the_configured_timeout(self) -> None:
        """The resident process going silent mid-request must still be
        bounded by piper_timeout_seconds -- a blocking read on the pipe has
        no timeout of its own, which is why the response wait goes through a
        queue instead."""
        speaker = TtsSpeaker(
            TtsSettings(engine="piper", model_path="voice.onnx", piper_timeout_seconds=0.05),
            AudioSettings(),
        )
        fake = _FakeProcess(stdout_lines=None)  # never responds

        with (
            patch.object(speaker, "_resolve_piper_assets", return_value=("piper.exe", Path("voice.onnx"))),
            patch("live_translator.tts.speaker.subprocess.Popen", return_value=fake),
        ):
            with self.assertRaisesRegex(RuntimeError, "did not finish within"):
                speaker.speak("Hello")

    def test_text_outside_the_console_codepage_reaches_piper(self) -> None:
        """A Polish or Czech character in a translation used to end the whole
        meeting with UnicodeEncodeError: the text was written to Piper with the
        locale encoding (cp1252 on Windows), which cannot represent it. The
        encoding is now named explicitly, and the request is JSON, so what goes
        down the pipe is ASCII-escaped whatever the phrase contains."""
        speaker = TtsSpeaker(
            TtsSettings(engine="piper", model_path="voice.onnx"),
            AudioSettings(),
        )
        fake = _FakeProcess(echo=True)

        with (
            patch.object(speaker, "_resolve_piper_assets", return_value=("piper.exe", Path("voice.onnx"))),
            patch("live_translator.tts.speaker.subprocess.Popen", return_value=fake) as popen,
            patch("live_translator.tts.speaker.read_wav_mono", return_value=READ_WAV_STUB),
            patch("live_translator.tts.speaker.play_mono"),
        ):
            speaker.speak("Zażółć gęślą jaźń")

        self.assertEqual(popen.call_args.kwargs["encoding"], "utf-8")
        written = "".join(call.args[0] for call in fake.stdin.write.call_args_list)
        self.assertTrue(
            written.isascii(),
            "the JSON request must be ASCII on the wire, whatever the phrase contains",
        )
        written.encode("cp1252")  # what the old code raised on

    def test_a_timed_out_request_cannot_desync_later_phrases(self) -> None:
        """Requests and responses are matched only by order, so a process that
        answers *after* its request timed out would hand that stale answer to
        the next phrase -- reporting success while naming the previous
        request's WAV, for every phrase after it. Killing the process on
        timeout is what stops one slow phrase from silently breaking synthesis
        for the rest of the meeting."""
        speaker = TtsSpeaker(
            TtsSettings(engine="piper", model_path="voice.onnx", piper_timeout_seconds=0.05),
            AudioSettings(),
        )
        fake = _FakeProcess(stdout_lines=None)  # never answers in time

        with (
            patch.object(speaker, "_resolve_piper_assets", return_value=("piper.exe", Path("voice.onnx"))),
            patch("live_translator.tts.speaker.subprocess.Popen", return_value=fake),
        ):
            piper = speaker._get_resident_piper()
            with self.assertRaisesRegex(RuntimeError, "did not finish within"):
                piper.synthesize("phrase A", Path("a.wav"))

        fake.kill.assert_called_once()
        self.assertFalse(piper.is_alive(), "a timed-out Piper must not be reused")

    def test_an_answer_naming_another_file_is_refused(self) -> None:
        """The other half of the same problem. Killing on timeout stops a late
        answer reaching the next phrase, but nothing stopped an answer that
        arrived on time and belonged to a different request: it was accepted
        without ever being read, and render() went on to load a WAV that Piper
        had not written. That fails quietly and stays wrong for every phrase
        after it, because the ordering never recovers on its own. Real
        piper.exe echoes back the output_file it just wrote, which is what
        makes the mismatch detectable at all."""
        speaker = TtsSpeaker(
            TtsSettings(engine="piper", model_path="voice.onnx"),
            AudioSettings(),
        )
        fake = _FakeProcess(stdout_lines=["some-other-phrase.wav" + chr(10)])

        with (
            patch.object(speaker, "_resolve_piper_assets", return_value=("piper.exe", Path("voice.onnx"))),
            patch("live_translator.tts.speaker.subprocess.Popen", return_value=fake),
        ):
            piper = speaker._get_resident_piper()
            with self.assertRaisesRegex(RuntimeError, "different request"):
                piper.synthesize("phrase A", Path("a.wav"))

        fake.kill.assert_called_once()
        self.assertFalse(piper.is_alive(), "an out-of-order stream must not be reused")

    def test_piper_exiting_unexpectedly_is_reported_clearly(self) -> None:
        """stdout ending with no response (as opposed to hanging) means the
        process exited -- a crash, not a slow phrase -- and must be reported
        as that, not as a silent failure to read anything."""
        speaker = TtsSpeaker(
            TtsSettings(engine="piper", model_path="voice.onnx"),
            AudioSettings(),
        )
        fake = _FakeProcess(stdout_lines=[])

        with (
            patch.object(speaker, "_resolve_piper_assets", return_value=("piper.exe", Path("voice.onnx"))),
            patch("live_translator.tts.speaker.subprocess.Popen", return_value=fake),
        ):
            with self.assertRaisesRegex(RuntimeError, "exited unexpectedly"):
                speaker.speak("Hello")

    def test_resident_process_is_reused_across_multiple_phrases(self) -> None:
        """The whole point of this design: one process serves every phrase in
        the session, not one spawned per phrase."""
        speaker = TtsSpeaker(
            TtsSettings(engine="piper", model_path="voice.onnx"),
            AudioSettings(),
        )
        fake = _FakeProcess(echo=True)

        with (
            patch.object(speaker, "_resolve_piper_assets", return_value=("piper.exe", Path("voice.onnx"))),
            patch("live_translator.tts.speaker.subprocess.Popen", return_value=fake) as popen,
            patch("live_translator.tts.speaker.read_wav_mono", return_value=READ_WAV_STUB),
            patch("live_translator.tts.speaker.play_mono"),
        ):
            speaker.warm_up()
            speaker.speak("Hello")
            speaker.speak("World")

        self.assertEqual(popen.call_count, 1)

    def test_dead_resident_process_is_restarted_on_the_next_call(self) -> None:
        """A resident process can legitimately die mid-meeting. The next
        phrase must not just keep failing against a corpse -- it should
        notice and start a fresh one."""
        speaker = TtsSpeaker(
            TtsSettings(engine="piper", model_path="voice.onnx"),
            AudioSettings(),
        )
        first = _FakeProcess(echo=True)
        second = _FakeProcess(echo=True)

        with (
            patch.object(speaker, "_resolve_piper_assets", return_value=("piper.exe", Path("voice.onnx"))),
            patch("live_translator.tts.speaker.subprocess.Popen", side_effect=[first, second]) as popen,
            patch("live_translator.tts.speaker.read_wav_mono", return_value=READ_WAV_STUB),
            patch("live_translator.tts.speaker.play_mono"),
        ):
            speaker.warm_up()
            first.mark_exited()
            speaker.speak("Hello")

        self.assertEqual(popen.call_count, 2)

    def test_close_stops_the_resident_process(self) -> None:
        speaker = TtsSpeaker(
            TtsSettings(engine="piper", model_path="voice.onnx"),
            AudioSettings(),
        )
        fake = _FakeProcess(echo=True)

        with (
            patch.object(speaker, "_resolve_piper_assets", return_value=("piper.exe", Path("voice.onnx"))),
            patch("live_translator.tts.speaker.subprocess.Popen", return_value=fake),
            patch("live_translator.tts.speaker.read_wav_mono", return_value=READ_WAV_STUB),
            patch("live_translator.tts.speaker.play_mono"),
        ):
            speaker.warm_up()
            speaker.close()

        fake.stdin.close.assert_called_once()
        fake.wait.assert_called_once()

    def test_warm_up_synthesizes_once_without_playing(self) -> None:
        """The point of warming up is to pay Piper's first-run cost at startup.
        Playing the warm-up audio would put a noise into the meeting instead."""
        speaker = TtsSpeaker(
            TtsSettings(engine="piper", model_path="voice.onnx"),
            AudioSettings(),
        )
        fake = _FakeProcess(echo=True)

        with (
            patch.object(speaker, "_resolve_piper_assets", return_value=("piper.exe", Path("voice.onnx"))),
            patch("live_translator.tts.speaker.subprocess.Popen", return_value=fake) as popen,
            patch("live_translator.tts.speaker.play_mono") as play,
        ):
            speaker.warm_up()

        self.assertEqual(popen.call_count, 1)
        play.assert_not_called()

    def test_warm_up_is_skipped_when_piper_is_not_the_engine(self) -> None:
        speaker = TtsSpeaker(TtsSettings(engine="none"), AudioSettings())

        with patch("live_translator.tts.speaker.subprocess.Popen") as popen:
            speaker.warm_up()

        popen.assert_not_called()

    def test_warm_up_failure_does_not_stop_startup(self) -> None:
        """A warm-up that cannot run means a slow first phrase, not a dead session."""
        speaker = TtsSpeaker(
            TtsSettings(engine="piper", model_path="voice.onnx"),
            AudioSettings(),
        )

        with (
            patch.object(speaker, "_resolve_piper_assets", return_value=("piper.exe", Path("voice.onnx"))),
            patch(
                "live_translator.tts.speaker.subprocess.Popen",
                side_effect=PermissionError("Access is denied"),
            ),
        ):
            speaker.warm_up()  # must not raise

    def test_warm_up_survives_a_hanging_piper_process(self) -> None:
        """warm_up()'s broad except must also cover a timed-out request, not
        just a failure to start -- a slow first phrase is still the
        acceptable outcome, not a dead startup."""
        speaker = TtsSpeaker(
            TtsSettings(engine="piper", model_path="voice.onnx", piper_timeout_seconds=0.05),
            AudioSettings(),
        )
        fake = _FakeProcess(stdout_lines=None)  # never responds

        with (
            patch.object(speaker, "_resolve_piper_assets", return_value=("piper.exe", Path("voice.onnx"))),
            patch("live_translator.tts.speaker.subprocess.Popen", return_value=fake),
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
