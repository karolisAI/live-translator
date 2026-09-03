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


class AssetIntegrityError(RuntimeError):
    """A protected runtime asset does not match its approved identity.

    Kept distinct from path-trust and dependency errors so callers can fail
    closed while still giving an actionable, content-free explanation: the
    expected asset is missing, has the wrong size, or has the wrong SHA-256.
    """


class ManifestValidationError(ValueError):
    """The runtime asset manifest is malformed or internally inconsistent."""


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
