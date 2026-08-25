import importlib

from live_translator.config import AsrSettings
from live_translator.defaults import ASR_ENGINES, SUPPORTED_ASR_ENGINES

from .base import AsrEngine, TranscriptResult
from .parakeet_engine import ParakeetAsr
from .recognizer import DEFAULT_MODEL, ParakeetRecognizer, Transcript

__all__ = [
    "DEFAULT_MODEL",
    "AsrEngine",
    "ParakeetAsr",
    "ParakeetRecognizer",
    "SUPPORTED_ASR_ENGINES",
    "Transcript",
    "TranscriptResult",
    "create_asr",
]


def create_asr(settings: AsrSettings) -> AsrEngine:
    target = ASR_ENGINES.get(settings.engine.lower())
    if target is None:
        raise ValueError(f"Unsupported ASR engine: {settings.engine}")
    module_name, _, attribute = target.partition(":")
    engine_class = getattr(importlib.import_module(module_name), attribute)
    return engine_class(settings)
