from __future__ import annotations

import importlib.util


class MissingDependency(RuntimeError):
    pass


class UnsupportedModel(ValueError):
    """The configured `asr.model` is not a Parakeet model onnx-asr can load.

    Subclasses `ValueError` so callers that already treat bad configuration as
    a `ValueError` keep working.
    """


class UntrustedRuntimePath(RuntimeError):
    """A resolved runtime path exists, but not inside an approved location.

    Distinct from FileNotFoundError (nothing exists anywhere approved) --
    this means something was found, just not somewhere this app trusts,
    which usually points at a misconfigured path rather than a missing
    install. Subclasses RuntimeError so it's caught wherever MissingDependency
    already is.
    """


def require_package(module_name: str, install_name: str | None = None) -> None:
    if importlib.util.find_spec(module_name) is None:
        package = install_name or module_name
        raise MissingDependency(
            f"Missing dependency '{package}'. Install dependencies with: python -m pip install -e ."
        )
