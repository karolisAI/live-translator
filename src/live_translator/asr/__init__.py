from live_translator.config import _SUPPORTED_ASR_ENGINES, AsrSettings

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

SUPPORTED_ASR_ENGINES = _SUPPORTED_ASR_ENGINES


def create_asr(settings: AsrSettings) -> AsrEngine:
    if settings.engine.lower() == "parakeet":
        return ParakeetAsr(settings)
    raise ValueError(f"Unsupported ASR engine: {settings.engine}")
