from live_translator.config import _SUPPORTED_ASR_ENGINES, AsrSettings

from .base import AsrEngine, TranscriptResult
from .faster_whisper_engine import FasterWhisperAsr
from .parakeet_engine import ParakeetAsr

__all__ = [
    "AsrEngine",
    "FasterWhisperAsr",
    "ParakeetAsr",
    "SUPPORTED_ASR_ENGINES",
    "TranscriptResult",
    "create_asr",
]

SUPPORTED_ASR_ENGINES = _SUPPORTED_ASR_ENGINES


def create_asr(settings: AsrSettings) -> AsrEngine:
    engine = settings.engine.lower()
    if engine == "faster-whisper":
        return FasterWhisperAsr(settings)
    if engine == "parakeet":
        return ParakeetAsr(settings)
    raise ValueError(f"Unsupported ASR engine: {settings.engine}")
