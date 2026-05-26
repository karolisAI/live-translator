from __future__ import annotations

import os

from live_translator.runtime import resolve_runtime_path


def configure_argos_runtime() -> None:
    os.environ.setdefault("ARGOS_CHUNK_TYPE", "ARGOSTRANSLATE")
    if "ARGOS_PACKAGES_DIR" in os.environ:
        return

    bundled_packages = resolve_runtime_path("models/argos/packages")
    if bundled_packages.exists():
        os.environ["ARGOS_PACKAGES_DIR"] = str(bundled_packages)
