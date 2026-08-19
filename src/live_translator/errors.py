from __future__ import annotations

import importlib.util


class MissingDependency(RuntimeError):
    pass


class UnsupportedModel(ValueError):
    """The configured `asr.model` is not a Parakeet model onnx-asr can load.

    Subclasses `ValueError` so callers that already treat bad configuration as
    a `ValueError` keep working.
    """


def require_package(module_name: str, install_name: str | None = None) -> None:
    if importlib.util.find_spec(module_name) is None:
        package = install_name or module_name
        raise MissingDependency(
            f"Missing dependency '{package}'. Install dependencies with: python -m pip install -e ."
        )


class ModelNotPrepared(FileNotFoundError):
    """The pinned Parakeet model is not present in the local model directory.

    Subclasses `FileNotFoundError` so the CLI's existing handler reports it as
    a plain error, and so it is not mistaken for a bug: a machine that was
    never prepared is a supported state with a documented fix, which the
    message carries.
    """
