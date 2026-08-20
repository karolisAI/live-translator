"""Where captured meeting content goes, and what it is called.

Both facts live here rather than being spelled out wherever they are needed.
Two copies of a filename that must agree is how a Git ignore rule silently
stops matching the files it was written for: the code renames its output, the
rule keeps matching the old name, and nothing fails until a transcript turns
up in a commit.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from live_translator.config import DiagnosticsSettings
from live_translator.runtime import diagnostics_dir


SEGMENT_PREFIX = "segment"
AUDIO_SUFFIX = ".wav"
NOTE_SUFFIX = ".txt"

SESSION_PREFIX = "session"

# Cleaning to exactly the limit puts the next phrase over it again, so every
# phrase would trigger a deletion. Clean down to 80% and the folder gets that
# much headroom before anything is removed again.
LOW_WATER_FRACTION = 0.8

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


def capture_warning(directory: Path, settings: DiagnosticsSettings) -> str:
    """The text shown when capture is switched on.

    A warning, not a status line. The message it replaces said "Writing debug
    audio chunks to X", which named the harmless half: the audio is large and
    obvious, while the note beside it is the phrase in both languages in plain
    text. Someone turning this on in a confidential meeting has to be told what
    is being written, where, and how long it stays.
    """
    limits = []
    if settings.retention_days > 0:
        limits.append(f"{settings.retention_days} days")
    if settings.max_total_mb > 0:
        limits.append(f"{settings.max_total_mb} MB")
    retention = (
        f"  Kept for at most {' or '.join(limits)}; the oldest is removed after that."
        if limits
        else "  Kept indefinitely: both retention limits are switched off."
    )
    return "\n".join(
        [
            "",
            "WARNING: diagnostic capture is ON. This session writes meeting content to disk.",
            f"  Location: {directory}",
            f"  {SEGMENT_PREFIX}-NNNN{AUDIO_SUFFIX}   the recorded audio of each phrase",
            f"  {SEGMENT_PREFIX}-NNNN{NOTE_SUFFIX}   its transcript and its translation, in plain text",
            retention,
            "",
        ]
    )


@dataclass(frozen=True)
class SweepResult:
    files_removed: int = 0
    bytes_freed: int = 0
    total_bytes: int = 0

    def __bool__(self) -> bool:
        return self.files_removed > 0


def captured_files(root: Path) -> list[Path]:
    """Only the files this application writes, never anything else.

    Retention and purge both delete from a directory the user may have chosen,
    so neither may work by "everything in here". A file counts as ours only if
    it sits in a session directory we named and carries a segment name we
    generate.
    """
    if not root.is_dir():
        return []

    found: list[Path] = []
    for session in root.glob(f"{SESSION_PREFIX}-*"):
        if not session.is_dir():
            continue
        for item in session.iterdir():
            if (
                item.is_file()
                and item.name.startswith(f"{SEGMENT_PREFIX}-")
                and item.suffix in {AUDIO_SUFFIX, NOTE_SUFFIX}
            ):
                found.append(item)
    return found


def sweep(
    settings: DiagnosticsSettings,
    root: Path | None = None,
    *,
    current_session: Path | None = None,
    now: datetime | None = None,
) -> SweepResult:
    """Enforce both retention limits, oldest first.

    Age applies to every captured phrase, including inside a session still
    running: a session left open for days would otherwise keep its first day
    forever. Size deletes finished sessions before the running one, so the
    capture someone is watching is the last to go -- but it does go, because an
    unattended session grows by about 2.7 GB a day.

    Either limit set to 0 disables that dimension.
    """
    root = root if root is not None else resolve_capture_dir(settings)
    entries: list[tuple[float, int, bool, Path]] = []
    for path in captured_files(root):
        try:
            stat = path.stat()
        except OSError:
            continue
        in_current = current_session is not None and path.parent == current_session
        entries.append((stat.st_mtime, stat.st_size, in_current, path))

    total = sum(entry[1] for entry in entries)
    removed = freed = 0

    if settings.retention_days > 0:
        cutoff = ((now or datetime.now()) - timedelta(days=settings.retention_days)).timestamp()
        for entry in list(entries):
            mtime, size, _in_current, path = entry
            if mtime < cutoff and _remove(path):
                entries.remove(entry)
                removed += 1
                freed += size
                total -= size

    cap = settings.max_total_mb * 1024 * 1024
    if cap > 0 and total > cap:
        target = int(cap * LOW_WATER_FRACTION)
        # finished sessions before the running one, oldest first within each
        for _mtime, size, _in_current, path in sorted(entries, key=lambda e: (e[2], e[0])):
            if total <= target:
                break
            if _remove(path):
                removed += 1
                freed += size
                total -= size

    _remove_empty_sessions(root, keep=current_session)
    return SweepResult(files_removed=removed, bytes_freed=freed, total_bytes=total)


def _remove(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except OSError:
        return False


def _remove_empty_sessions(root: Path, *, keep: Path | None = None) -> None:
    if not root.is_dir():
        return
    for session in root.glob(f"{SESSION_PREFIX}-*"):
        if session == keep or not session.is_dir():
            continue
        try:
            session.rmdir()
        except OSError:
            pass


class CaptureLimits:
    """Keeps the folder inside its limits without re-scanning it.

    Walking a full capture folder costs about 1.8 seconds on this hardware,
    measured over 4600 files. That is half a phrase interval, enough to make
    the recognition worker overrun and drop speech. So the folder is measured
    once when capture starts and every write after that adds its own byte
    count; nothing touches the disk again until a limit is actually crossed.
    """

    def __init__(
        self, settings: DiagnosticsSettings, root: Path, current_session: Path
    ) -> None:
        self._settings = settings
        self._root = root
        self._current_session = current_session
        self._cap = settings.max_total_mb * 1024 * 1024
        self._total = sweep(settings, root, current_session=current_session).total_bytes

    @property
    def total_bytes(self) -> int:
        return self._total

    def record(self, path: Path | None) -> SweepResult | None:
        """Account for one written artifact, cleaning up only if needed."""
        if path is None:
            return None
        try:
            self._total += path.stat().st_size
        except OSError:
            return None
        if self._cap <= 0 or self._total <= self._cap:
            return None

        result = sweep(self._settings, self._root, current_session=self._current_session)
        self._total = result.total_bytes
        return result
