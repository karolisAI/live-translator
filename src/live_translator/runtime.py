from __future__ import annotations

import os
import sys
from pathlib import Path

from live_translator.errors import UntrustedRuntimePath

APP_NAME = "LiveTranslator"

_DEV_RUNTIME_ROOT_ENV = "LIVE_TRANSLATOR_DEV_RUNTIME_ROOT"

_approved_roots_cache: list[Path] | None = None
"""Cache for approved_runtime_roots(). Piper's render() alone resolves two
paths (exe + model) per phrase, so without this a live meeting rebuilds the
roots list -- including the dev-root env lookup and its warning print --
twice per phrase for the whole meeting. The inputs (sys.frozen, _MEIPASS,
__file__, the dev-root env var) don't change once a process is running, so
computing this once is safe in production. Tests that vary those inputs
reset this explicitly -- see test_runtime.py's _reset_roots_cache()."""


def user_data_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    if root:
        return Path(root) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


def profile_dir() -> Path:
    return user_data_dir() / "profiles"


def diagnostics_dir() -> Path:
    """Per-user home for captured meeting content.

    Resolved through `user_data_dir` on every call rather than cached, because
    group policy can redirect %LOCALAPPDATA% on a corporate machine.
    """
    return user_data_dir() / "diagnostics"


def default_profile_path(profile_name: str = "default") -> Path:
    return profile_dir() / f"{profile_name}.yaml"


def dev_runtime_root() -> Path | None:
    """Explicit, opt-in override for local development. `None` unless a
    developer deliberately sets LIVE_TRANSLATOR_DEV_RUNTIME_ROOT, never
    active by default, and never silently.

    Separate in purpose from the production-facing overrides in
    mt/translator.py (ARGOS_PACKAGES_DIR, XDG_DATA_HOME). Those exist so an
    operator can point at a real external package location and stay
    supported. This one exists only to unblock a developer running from
    source and testing against a build somewhere approved_runtime_roots()
    wouldn't otherwise trust.

    Never honored in a frozen build (see the check below), so it structurally
    cannot widen trust for a real installed app even if the variable is set
    in its environment, for example left over from an earlier test session
    on a shared machine. A frozen build already trusts its own directory
    unconditionally, so it never needed this override in the first place.
    """
    if getattr(sys, "frozen", False):
        return None
    value = os.environ.get(_DEV_RUNTIME_ROOT_ENV)
    if not value:
        return None
    root = Path(value).resolve()
    print(
        f"WARNING: {_DEV_RUNTIME_ROOT_ENV} is set, trusting runtime "
        f"executables and assets from {root}. This must never be set outside "
        f"local development."
    )
    return root


def approved_runtime_roots() -> list[Path]:
    """Trusted locations for runtime executables and the assets they need.

    Deliberately excludes the current working directory: anyone able to
    launch the app from an arbitrary directory, or drop a file into one
    that's already on this list, can otherwise get a file of their choosing
    resolved and, for executables, run. The app's own installed/bundled/
    package location is what's actually trustworthy, not wherever the
    process happened to start.

    For the shipped onedir PyInstaller build, sys.executable's parent and
    _MEIPASS are NOT the same directory -- PyInstaller 6.x nests bundled data
    (including tools/piper/) under an `_internal/` subdirectory rather than
    next to the exe. Confirmed by actually building and running the frozen
    exe, not assumed: an earlier version of this comment claimed they were
    the same, which a real build proved wrong. Both roots are listed because
    of this, not despite it -- resolution genuinely depends on _MEIPASS being
    present and correct. That's a second reason (beyond onefile mode) this
    would need re-review if packaging ever changes: _MEIPASS carrying the
    actual trust-bearing role here, not just belt-and-suspenders alongside
    sys.executable's parent.

    Computed once per process and cached -- see _approved_roots_cache.
    """
    global _approved_roots_cache
    if _approved_roots_cache is not None:
        return _approved_roots_cache

    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        roots.append(Path(bundle_root).resolve())
    roots.append(Path(__file__).resolve().parents[2])

    dev_root = dev_runtime_root()
    if dev_root is not None:
        roots.append(dev_root)

    unique: list[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    _approved_roots_cache = unique
    return unique


def resolve_trusted_path(path: str | Path) -> Path:
    """Resolve `path` and require it land inside an approved runtime root.

    For anything executed as a subprocess, or otherwise sensitive enough that
    loading it from an unexpected location is a security concern. Unlike a
    plain existence-based resolver, this:

    - never trusts a path just because it's absolute -- the resolved,
      normalized result still has to land inside an approved root.
    - rejects any candidate containing a `..` component outright, before
      even searching, so a traversal attempt fails fast and legibly rather
      than relying solely on the containment check to catch it.
    - never falls back to searching PATH -- PATH is not an approved
      location.

    Raises FileNotFoundError if `path` isn't found under any approved root.
    Raises UntrustedRuntimePath if it's found somewhere that isn't an
    approved root -- worth telling apart from "not found at all", since it
    usually means a config value points somewhere unexpected rather than
    something being missing.
    """
    candidate = Path(path)
    if ".." in candidate.parts:
        raise UntrustedRuntimePath(
            f"'{path}' contains a '..' path segment, which is not allowed here."
        )

    roots = approved_runtime_roots()

    if candidate.is_absolute():
        found = candidate if candidate.exists() else None
        searched_desc = str(candidate)
    else:
        found = None
        for root in roots:
            resolved = root / candidate
            if resolved.exists():
                found = resolved
                break
        searched_desc = ", ".join(str(root / candidate) for root in roots)

    if found is None:
        raise FileNotFoundError(f"'{path}' was not found. Searched: {searched_desc}")

    resolved = found.resolve()
    if not any(_is_within(resolved, root) for root in roots):
        raise UntrustedRuntimePath(
            f"'{path}' resolved to {resolved}, which is outside every approved "
            f"runtime location ({', '.join(str(root) for root in roots)}). Refusing to use it."
        )
    return resolved


def approved_runtime_root_for(path: str | Path) -> Path:
    """Return the approved root containing an already resolved runtime path."""
    resolved = Path(path).resolve()
    containing = [root.resolve() for root in approved_runtime_roots() if _is_within(resolved, root)]
    if not containing:
        raise UntrustedRuntimePath(
            f"'{resolved}' is outside every approved runtime location."
        )
    return max(containing, key=lambda root: len(root.parts))


def find_runtime_manifest(runtime_root: str | Path | None = None) -> Path:
    """Find the application-owned manifest.

    When ``runtime_root`` is provided, only that approved root is searched.
    Callers verifying assets from a known root must use this form so a manifest
    belonging to another approved root cannot be selected accidentally.
    """
    searched: list[str] = []
    roots = (
        (Path(runtime_root).resolve(),)
        if runtime_root is not None
        else tuple(root.resolve() for root in approved_runtime_roots())
    )
    for root in roots:
        candidates = (
            root / "runtime-assets.manifest.json",
            root / "packaging" / "runtime-assets.manifest.json",
        )
        for candidate in candidates:
            searched.append(str(candidate))
            if candidate.is_file():
                return candidate
    raise FileNotFoundError(
        "Runtime asset manifest was not found. Searched: " + ", ".join(searched)
    )


def _is_within(path: Path, root: Path) -> bool:
    """Containment check that stays correct on Windows, where two paths
    naming the same location can differ in case (NTFS is case-insensitive)
    or in short (8.3) vs. long form. Resolves both sides itself rather than
    trusting callers to have already done so -- a real false-rejection
    surfaced in testing from exactly this: TemporaryDirectory() can hand back
    a short-form path (...\\ALEKSA~1\\...) that only matches its long form
    (...\\AleksandrasBaceviciu\\...) after resolving both. `path`'s one
    current caller already resolves it first, so this is a no-op there --
    kept anyway so this function is correct on its own, not just for today's
    one call site."""
    normalized_path = os.path.normcase(str(path.resolve()))
    normalized_root = os.path.normcase(str(root.resolve()))
    return normalized_path == normalized_root or normalized_path.startswith(
        normalized_root + os.sep
    )
