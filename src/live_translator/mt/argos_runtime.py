from __future__ import annotations

import os
from pathlib import Path

from live_translator.runtime import resolve_trusted_path


def configure_argos_runtime() -> None:
    os.environ.setdefault("ARGOS_CHUNK_TYPE", "ARGOSTRANSLATE")
    env_dir = os.environ.get("ARGOS_PACKAGES_DIR")
    if env_dir:
        # Validated here, once, rather than in _argos_package_path(): this is
        # the one place _prepare_argos() guarantees runs first, and
        # ARGOS_PACKAGES_DIR is also read directly by the argostranslate
        # library itself, not just our own resolution -- a malformed value
        # needs to be caught before either consumer sees it.
        validate_override_dir("ARGOS_PACKAGES_DIR", env_dir)
        return

    try:
        bundled_packages = resolve_trusted_path("models/argos/packages")
    except FileNotFoundError:
        return
    os.environ["ARGOS_PACKAGES_DIR"] = str(bundled_packages)


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
