from __future__ import annotations

import os
from pathlib import Path

from live_translator.runtime import resolve_trusted_path


_last_validated_packages_dir: str | None = None
"""Cache for configure_argos_runtime()'s ARGOS_PACKAGES_DIR check.

configure_argos_runtime() runs once per translated phrase (_prepare_argos()
calls it on every _translate_argos()), not once per session, so without this
a live meeting stats and prints "Using ARGOS_PACKAGES_DIR override: ..." on
every single phrase once the env var is set. Keyed by value rather than a
plain do-this-once flag: a value that changes still gets validated, only an
identical repeat is skipped. Assumes configure_argos_runtime() is called
serially from one worker, matching today's single recognition thread -- a
second caller thread would need a lock around this.
"""


def configure_argos_runtime() -> None:
    global _last_validated_packages_dir
    os.environ.setdefault("ARGOS_CHUNK_TYPE", "ARGOSTRANSLATE")
    env_dir = os.environ.get("ARGOS_PACKAGES_DIR")
    if env_dir:
        # Validated here, once per distinct value, rather than in
        # _argos_package_path(): this is the one place _prepare_argos()
        # guarantees runs first, and ARGOS_PACKAGES_DIR is also read directly
        # by the argostranslate library itself, not just our own resolution
        # -- a malformed value needs to be caught before either consumer sees
        # it. A directory that later becomes unavailable mid-session isn't
        # re-caught here, but _argos_package_path()'s own per-call
        # candidate.exists() check still catches that on the very same call,
        # just with a slightly less specific error message.
        if env_dir != _last_validated_packages_dir:
            validate_override_dir("ARGOS_PACKAGES_DIR", env_dir)
            _last_validated_packages_dir = env_dir
        return

    try:
        bundled_packages = resolve_trusted_path("models/argos/packages")
    except FileNotFoundError:
        return
    os.environ["ARGOS_PACKAGES_DIR"] = str(bundled_packages)
    # Already trusted (just resolved from an approved root) -- recording it
    # here means the *next* call's `if env_dir:` branch above sees a match
    # and skips re-validating a value we ourselves just proved is good.
    _last_validated_packages_dir = str(bundled_packages)


def validate_override_dir(env_var_name: str, value: str) -> Path:
    """Validate and announce an operator-configured override directory.

    Covers ARGOS_PACKAGES_DIR and XDG_DATA_HOME: legitimate to point outside
    the app's bundle -- an operator pointing at a custom or updated package
    location is a supported use, not a fallback for something missing.
    Absolute-only closes the CWD-relative loophole this class of override
    would otherwise reintroduce, without removing the feature. Printing when
    active means it's never silently in effect.
    """
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(
            f"{env_var_name} must be an absolute path (got '{value}'). A "
            f"relative path would resolve against the current working "
            f"directory, which this app does not trust."
        )
    if not path.is_dir():
        raise ValueError(
            f"{env_var_name} is set to '{path}', which is not an existing directory."
        )
    print(f"Using {env_var_name} override: {path}")
    return path
