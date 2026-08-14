from __future__ import annotations

__all__ = ["MissingDependency", "UnsupportedModel"]


class MissingDependency(RuntimeError):
    """A runtime dependency of this package is not importable."""


class UnsupportedModel(ValueError):
    """The requested model name is not an onnx-asr Parakeet model.

    Subclasses `ValueError` so callers that already treat bad configuration as
    a `ValueError` keep working without importing this package.
    """
