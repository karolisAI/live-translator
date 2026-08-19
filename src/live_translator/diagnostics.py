"""Where captured meeting content goes, and what it is called.

Both facts live here rather than being spelled out wherever they are needed.
Two copies of a filename that must agree is how a Git ignore rule silently
stops matching the files it was written for: the code renames its output, the
rule keeps matching the old name, and nothing fails until a transcript turns
up in a commit.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from live_translator.config import DiagnosticsSettings
from live_translator.runtime import diagnostics_dir


SEGMENT_PREFIX = "segment"
AUDIO_SUFFIX = ".wav"
NOTE_SUFFIX = ".txt"

SESSION_PREFIX = "session"

# Keep `.gitignore` in step with these: it carries `segment-*.txt`, and
# tests/test_gitignore.py imports the helpers below so a rename fails the
# suite instead of quietly widening what Git will offer to commit.


def segment_audio_name(number: int) -> str:
    return f"{SEGMENT_PREFIX}-{number:04d}{AUDIO_SUFFIX}"


def segment_note_name(number: int) -> str:
    return f"{SEGMENT_PREFIX}-{number:04d}{NOTE_SUFFIX}"


def session_directory_name(started_at: datetime | None = None) -> str:
    """A directory per session, because phrase numbers restart at 1.

    Two meetings sharing a directory means the second one's
    segment-0001 silently replaces the first one's, and the evidence
    someone turned capture on to collect is gone. The process id keeps
    two sessions started in the same second apart.
    """
    stamp = (started_at or datetime.now()).strftime("%Y%m%d-%H%M%S")
    return f"{SESSION_PREFIX}-{stamp}-{os.getpid()}"


def resolve_capture_dir(
    settings: DiagnosticsSettings, override: str | Path | None = None
) -> Path:
    """Decide where this session writes, from config and an optional CLI path.

    An absolute path is honoured as given: someone who types a drive letter
    means it. Anything relative is resolved under the per-user directory
    instead of the working directory, because the working directory is usually
    a checkout and that is how meeting transcripts end up next to source code.
    A relative path that climbs back out with `..` is refused rather than
    quietly relocated, since silently writing somewhere other than both what
    the user asked for and what we promised is worse than an error.
    """
    root = diagnostics_dir()
    chosen = override if override else settings.dir
    if not chosen:
        return root

    candidate = Path(chosen)
    if candidate.is_absolute():
        return candidate

    destination = Path(os.path.normpath(root / candidate))
    resolved = destination.resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise ValueError(
            f"Diagnostics path {chosen!r} resolves outside {root_resolved}. "
            "Pass an absolute path if that is really what you want."
        )
    return destination


def capture_warning(directory: Path) -> str:
    """The text shown when capture is switched on.

    A warning, not a status line. The message it replaces said "Writing debug
    audio chunks to X", which named the harmless half: the audio is large and
    obvious, while the note beside it is the phrase in both languages in plain
    text. Someone turning this on in a confidential meeting has to be told
    what is being written and where, in words they do not have to decode.
    """
    return "\n".join(
        [
            "",
            "WARNING: diagnostic capture is ON. This session writes meeting content to disk.",
            f"  Location: {directory}",
            f"  {SEGMENT_PREFIX}-NNNN{AUDIO_SUFFIX}   the recorded audio of each phrase",
            f"  {SEGMENT_PREFIX}-NNNN{NOTE_SUFFIX}   its transcript and its translation, in plain text",
            "  Delete that directory when you no longer need it.",
            "",
        ]
    )
