from live_translator.config import AsrSettings, _SUPPORTED_ASR_ENGINES

from .base import AsrEngine, TranscriptResult
from .faster_whisper_engine import FasterWhisperAsr
from .parakeet_engine import ParakeetAsr
from .parakeet_live_engine import ParakeetLiveAsr

__all__ = [
    "AsrEngine",
    "FasterWhisperAsr",
    "ParakeetAsr",
    "ParakeetLiveAsr",
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
    if engine == "parakeet-live":
        return ParakeetLiveAsr(settings)
    raise ValueError(f"Unsupported ASR engine: {settings.engine}")
