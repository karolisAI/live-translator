"""Config and path rules for captured meeting content.

Two questions settled here: what the config says by default and which
directory a setting resolves to, then whether a session captures anything
at all. The activation tests are the ticket's first test case: a normal
meeting must leave no audio, transcript or translation behind.
"""

import io
import os
import unittest
from datetime import datetime, timedelta
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from live_translator.config import AppConfig, DiagnosticsSettings, load_config
from live_translator.pipeline import LocalTranslatorPipeline
from live_translator.diagnostics import (
    NotOurDirectory,
    LOW_WATER_FRACTION,
    CaptureLimits,
    captured_files,
    capture_warning,
    purge,
    sweep,
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
    checkout, which is how transcripts end up beside source code.

    Paths here are built rather than written as literals: CI runs this suite on
    Ubuntu as well as Windows, and a string like "D:\scratch" is an absolute
    path on one and a single filename on the other.
    """

    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name).resolve() / "LiveTranslator" / "diagnostics"
        patcher = patch("live_translator.diagnostics.diagnostics_dir", return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_default_is_the_per_user_directory(self) -> None:
        self.assertEqual(resolve_capture_dir(DiagnosticsSettings()), self.root)

    def test_relative_config_path_is_placed_under_the_per_user_directory(self) -> None:
        settings = DiagnosticsSettings(dir="capture")

        self.assertEqual(resolve_capture_dir(settings), self.root / "capture")

    def test_relative_cli_path_does_not_land_in_the_working_directory(self) -> None:
        """--debug-audio-dir debug-asr is what the README used to teach, and it
        wrote into whatever directory the user was standing in."""
        resolved = resolve_capture_dir(DiagnosticsSettings(), "debug-asr")

        self.assertEqual(resolved, self.root / "debug-asr")
        self.assertNotEqual(resolved, Path("debug-asr").resolve())

    def test_absolute_path_is_honoured_as_given(self) -> None:
        elsewhere = Path(self._temp.name).resolve() / "somewhere-else"

        self.assertTrue(elsewhere.is_absolute(), "the test itself must pass an absolute path")
        self.assertEqual(resolve_capture_dir(DiagnosticsSettings(), str(elsewhere)), elsewhere)

    def test_cli_path_wins_over_the_config_setting(self) -> None:
        settings = DiagnosticsSettings(dir="from-config")

        self.assertEqual(resolve_capture_dir(settings, "from-cli"), self.root / "from-cli")

    def test_relative_path_climbing_out_is_refused(self) -> None:
        # forward slashes parse as a path on both platforms; backslashes do not
        with self.assertRaises(ValueError):
            resolve_capture_dir(DiagnosticsSettings(), "../../../Desktop")


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

    def test_a_path_climbing_out_with_dotdot_does_not_end_the_meeting_either(self) -> None:
        """resolve_capture_dir refuses this with ValueError, not OSError --
        this used to be a different exception type than the one caught above,
        so it crashed loopback() instead of degrading the same way."""
        result, output = self._start(diagnostics=True, debug_audio_dir="../../../Desktop")

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
        directory = Path("somewhere") / "diagnostics"
        text = capture_warning(directory, DiagnosticsSettings())

        self.assertIn("segment-NNNN.wav", text)
        self.assertIn("segment-NNNN.txt", text)
        self.assertIn(str(directory), text)


class RetentionTests(unittest.TestCase):
    """Both limits, and the rule that decides what goes first.

    Covers the ticket test case: retention cleanup removes artifacts exceeding
    the configured age or size.
    """

    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name) / "diagnostics"
        self.root.mkdir(parents=True)

    def _session(self, name: str, *, phrases: int = 1, kb: int = 1, age_days: float = 0.0) -> Path:
        session = self.root / f"session-{name}"
        session.mkdir(exist_ok=True)
        when = (datetime.now() - timedelta(days=age_days)).timestamp()
        for n in range(1, phrases + 1):
            for path in (session / segment_audio_name(n), session / segment_note_name(n)):
                path.write_bytes(b"x" * (kb * 1024))
                os.utime(path, (when, when))
        return session

    def test_artifacts_past_the_age_limit_are_removed(self) -> None:
        old = self._session("20260801-120000-1", age_days=9)
        recent = self._session("20260819-120000-2", age_days=1)

        result = sweep(DiagnosticsSettings(retention_days=7, max_total_mb=0), self.root)

        self.assertFalse(old.exists(), "an expired session should be gone, directory and all")
        self.assertEqual(len(list(recent.iterdir())), 2)
        self.assertEqual(result.files_removed, 2)

    def test_age_limit_reaches_inside_a_running_session(self) -> None:
        """A session left open for days would otherwise keep its first day forever."""
        current = self._session("20260812-090000-3", phrases=2, age_days=9)

        sweep(DiagnosticsSettings(retention_days=7, max_total_mb=0), self.root,
              current_session=current)

        self.assertTrue(current.is_dir(), "the directory of a running session must survive")
        self.assertEqual(list(current.iterdir()), [])

    def test_size_limit_deletes_oldest_first_down_to_the_low_water_mark(self) -> None:
        self._session("20260819-100000-1", phrases=8, kb=64, age_days=3)
        self._session("20260819-110000-2", phrases=8, kb=64, age_days=2)
        self._session("20260819-120000-3", phrases=8, kb=64, age_days=1)

        result = sweep(DiagnosticsSettings(retention_days=0, max_total_mb=2), self.root)

        cap = 2 * 1024 * 1024
        self.assertLessEqual(result.total_bytes, int(cap * LOW_WATER_FRACTION))
        self.assertFalse((self.root / "session-20260819-100000-1").exists())
        self.assertTrue((self.root / "session-20260819-120000-3").exists())

    def test_running_session_is_deleted_last(self) -> None:
        finished = self._session("20260819-100000-1", phrases=8, kb=64, age_days=0.2)
        current = self._session("20260819-120000-2", phrases=8, kb=64, age_days=0.1)

        sweep(DiagnosticsSettings(retention_days=0, max_total_mb=1), self.root,
              current_session=current)

        self.assertFalse(finished.exists())
        self.assertTrue(current.is_dir())

    def test_a_lone_running_session_still_loses_its_oldest(self) -> None:
        """The unattended case: one session, running for days, 2.7 GB a day."""
        current = self._session("20260819-090000-1", phrases=16, kb=64, age_days=0.5)

        result = sweep(DiagnosticsSettings(retention_days=0, max_total_mb=1), self.root,
                       current_session=current)

        self.assertLessEqual(result.total_bytes, int(1024 * 1024 * LOW_WATER_FRACTION))
        self.assertTrue(current.is_dir())
        self.assertTrue(any(current.iterdir()), "it should trim, not empty itself")

    def test_zero_disables_a_limit(self) -> None:
        self._session("20260101-120000-1", phrases=8, kb=64, age_days=400)

        result = sweep(DiagnosticsSettings(retention_days=0, max_total_mb=0), self.root)

        self.assertEqual(result.files_removed, 0)

    def test_nothing_the_application_did_not_write_is_touched(self) -> None:
        """Retention deletes from a directory the user may have chosen, so
        deleting by everything-in-here would be a disaster."""
        session = self._session("20260801-120000-1", age_days=99)
        stranger = session / "my-notes.md"
        stranger.write_text("keep me", encoding="utf-8")
        loose = self.root / "holiday-photo.jpg"
        loose.write_bytes(b"x" * 2048)

        sweep(DiagnosticsSettings(retention_days=1, max_total_mb=1), self.root)

        self.assertTrue(stranger.exists())
        self.assertTrue(loose.exists())


class CaptureLimitsTests(unittest.TestCase):
    """Accounting must not re-walk the folder: a full one costs 1.8 seconds
    here, half a phrase interval, which would make the recognition worker
    overrun and drop speech."""

    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name) / "diagnostics"
        self.session = self.root / "session-20260819-120000-1"
        self.session.mkdir(parents=True)

    def _write(self, limits, number: int, kb: int):
        path = self.session / segment_audio_name(number)
        path.write_bytes(b"x" * (kb * 1024))
        return limits.record(path)

    def test_writes_below_the_cap_do_not_touch_the_disk(self) -> None:
        limits = CaptureLimits(DiagnosticsSettings(max_total_mb=1), self.root, self.session)

        with patch("live_translator.diagnostics.sweep") as swept:
            result = self._write(limits, 1, 64)

        self.assertIsNone(result)
        swept.assert_not_called()

    def test_running_total_tracks_what_was_written(self) -> None:
        limits = CaptureLimits(DiagnosticsSettings(max_total_mb=0), self.root, self.session)

        self._write(limits, 1, 64)
        self._write(limits, 2, 64)

        self.assertEqual(limits.total_bytes, 128 * 1024)

    def test_crossing_the_cap_triggers_one_cleanup(self) -> None:
        limits = CaptureLimits(DiagnosticsSettings(retention_days=0, max_total_mb=1),
                               self.root, self.session)

        result = None
        for number in range(1, 25):
            result = self._write(limits, number, 64) or result

        self.assertIsNotNone(result)
        self.assertGreater(result.files_removed, 0)
        self.assertLessEqual(limits.total_bytes, 1024 * 1024)


class PurgeTests(unittest.TestCase):
    """Covers the ticket test case: the purge action removes all supported
    diagnostic artifacts. And the harder half, that it removes nothing else."""

    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name) / "diagnostics"
        self.root.mkdir(parents=True)

    def _session(self, name: str, phrases: int = 2) -> Path:
        session = self.root / f"session-{name}"
        session.mkdir(exist_ok=True)
        for n in range(1, phrases + 1):
            (session / segment_audio_name(n)).write_bytes(b"x" * 4096)
            (session / segment_note_name(n)).write_text("source=x", encoding="utf-8")
        return session

    def test_purge_removes_every_captured_session(self) -> None:
        self._session("20260819-100000-1")
        self._session("20260820-090000-2", phrases=3)

        result = purge(DiagnosticsSettings(), self.root)

        self.assertEqual(result.sessions_removed, 2)
        self.assertEqual(result.files_removed, 10)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_purge_leaves_the_directory_itself(self) -> None:
        """Removing it would only make the next capture recreate it."""
        self._session("20260819-100000-1")

        purge(DiagnosticsSettings(), self.root)

        self.assertTrue(self.root.is_dir())

    def test_purge_on_an_empty_directory_is_not_an_error(self) -> None:
        result = purge(DiagnosticsSettings(), self.root)

        self.assertEqual(result.files_removed, 0)

    def test_purge_on_a_missing_directory_is_not_an_error(self) -> None:
        result = purge(DiagnosticsSettings(), self.root / "never-created")

        self.assertEqual(result.files_removed, 0)

    def test_purge_refuses_a_directory_that_is_not_ours(self) -> None:
        """diagnostics.dir can point anywhere, so a wrong value must not turn
        purge into a recursive delete of somebody personal folder."""
        (self.root / "tax-return.pdf").write_bytes(b"x" * 128)
        (self.root / "photos").mkdir()

        with self.assertRaises(NotOurDirectory):
            purge(DiagnosticsSettings(), self.root)

        self.assertTrue((self.root / "tax-return.pdf").exists())
        self.assertTrue((self.root / "photos").is_dir())

    def test_purge_keeps_strangers_that_sit_beside_our_sessions(self) -> None:
        session = self._session("20260819-100000-1")
        stranger = session / "my-notes.md"
        stranger.write_text("keep me", encoding="utf-8")

        purge(DiagnosticsSettings(), self.root)

        self.assertTrue(stranger.exists(), "only our own filenames may be deleted")


class SymlinkEscapeTests(unittest.TestCase):
    """A `session-*` entry can be a symlink -- or, on Windows, an NTFS
    junction -- to a directory outside the diagnostics root while still
    passing `is_dir()`. Without resolving and checking containment,
    `captured_files()` would report whatever sits at the far end, and
    `sweep()`/`purge()` would delete it.
    """

    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name) / "diagnostics"
        self.root.mkdir(parents=True)
        self.outside = Path(self._temp.name) / "not-diagnostics"
        self.outside.mkdir(parents=True)

    def _symlinked_session(self) -> Path:
        """A `session-*` entry inside `root` that is really a symlink to
        `outside`, containing a file that satisfies every naming rule
        `captured_files()` checks.

        Skips rather than fails where this process cannot create a directory
        symlink -- on Windows that needs Developer Mode or an elevated
        process. This test is about containment once a symlink exists, not
        about proving symlink creation itself works in every environment.
        """
        (self.outside / segment_audio_name(1)).write_bytes(b"not ours" * 1024)
        link = self.root / "session-escape-attempt"
        try:
            os.symlink(self.outside, link, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"cannot create a directory symlink here: {exc}")
        return link

    def test_captured_files_does_not_follow_a_symlinked_session(self) -> None:
        self._symlinked_session()

        self.assertEqual(captured_files(self.root), [])

    def test_purge_does_not_delete_through_a_symlinked_session(self) -> None:
        self._symlinked_session()
        target_file = self.outside / segment_audio_name(1)

        purge(DiagnosticsSettings(), self.root)

        self.assertTrue(
            target_file.exists(), "a file outside the diagnostics root must survive purge"
        )

    def test_sweep_does_not_delete_through_a_symlinked_session(self) -> None:
        self._symlinked_session()
        target_file = self.outside / segment_audio_name(1)
        ancient = (datetime.now() - timedelta(days=999)).timestamp()
        os.utime(target_file, (ancient, ancient))

        sweep(DiagnosticsSettings(retention_days=1, max_total_mb=0), self.root)

        self.assertTrue(
            target_file.exists(), "age-based retention must not reach outside the root"
        )


if __name__ == "__main__":
    unittest.main()