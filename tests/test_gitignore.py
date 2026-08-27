"""Every artifact diagnostics can generate must be invisible to Git.

The audio was already covered by `*.wav`, but the note beside it holds the
transcript and the translation in plain text, so before these rules it was the
one file `git status` would offer to stage. This is a backstop: diagnostics
default to a per-user directory outside any checkout, and these patterns only
matter when someone points a run back inside one.
"""

import subprocess
import unittest
from pathlib import Path

from live_translator.diagnostics import segment_audio_name, segment_note_name


REPO_ROOT = Path(__file__).resolve().parents[1]

# Built from the names the code actually writes, not from copies of them. A
# rename in diagnostics.py therefore fails here instead of quietly leaving the
# ignore rule matching a filename nothing produces any more.
AUDIO = segment_audio_name(1)
NOTE = segment_note_name(1)

GENERATED_PATHS = [
    f"diagnostics/{AUDIO}",
    f"diagnostics/{NOTE}",
    f"debug-asr/{AUDIO}",
    f"debug-asr/{NOTE}",
    # A directory the rules do not name, standing in for whatever a user calls
    # theirs: the note must be caught by its own filename pattern rather than
    # by its parent having been listed.
    f"any-directory-a-user-picks/{NOTE}",
    f"any-directory-a-user-picks/{AUDIO}",
    "record-test.wav",
    "eval/calibration/log_prob_calibration.csv",
]


def _git_available() -> bool:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        )
    except (OSError, FileNotFoundError):
        return False
    return completed.returncode == 0


@unittest.skipUnless(_git_available(), "not a Git checkout, or Git is not installed")
class GitIgnoreTests(unittest.TestCase):
    def test_generated_diagnostic_artifacts_are_ignored(self) -> None:
        for path in GENERATED_PATHS:
            with self.subTest(path=path):
                completed = subprocess.run(
                    ["git", "check-ignore", "-q", path],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    f"{path} is not ignored; Git would offer to commit it",
                )

    def test_requirements_txt_is_still_tracked(self) -> None:
        """`segment-*.txt` must stay narrow. A blanket `*.txt` would untrack this."""
        completed = subprocess.run(
            ["git", "check-ignore", "-q", "requirements.txt"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 1, "requirements.txt must not be ignored")


if __name__ == "__main__":
    unittest.main()
