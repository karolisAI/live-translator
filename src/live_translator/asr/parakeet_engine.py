from __future__ import annotations

from typing import Any

from live_translator.asr.base import TranscriptResult
from live_translator.asr.recognizer import DEFAULT_MODEL, ParakeetRecognizer
from live_translator.config import AsrSettings
from live_translator.errors import UnsupportedModel

__all__ = ["DEFAULT_MODEL", "ParakeetAsr"]


class ParakeetAsr:
    """Maps `AsrSettings` onto the recognizer and its result back onto `TranscriptResult`.

    The recognizer in `recognizer.py` knows nothing about this application's
    configuration; this class is the only place the two meet.
    """

    def __init__(self, settings: AsrSettings) -> None:
        if settings.engine.lower() != "parakeet":
            raise ValueError(f"Unsupported ASR engine: {settings.engine}")

        self._settings = settings
        try:
            self._recognizer = ParakeetRecognizer(
                settings.model,
                quantization=settings.compute_type,
                device=settings.device,
                cpu_threads=settings.cpu_threads,
                language=settings.source_language,
                min_chars=settings.min_segment_chars,
                log_prob_threshold=settings.log_prob_threshold,
                compression_ratio_threshold=settings.compression_ratio_threshold,
            )
        except UnsupportedModel as exc:
            # Restate the recognizer's model complaint in terms of the config
            # key the user actually edits.
            raise ValueError(
                f"asr.model '{settings.model}' is not a Parakeet model. Use "
                f"'{DEFAULT_MODEL}', or another onnx-asr Parakeet model name."
            ) from exc

    def transcribe(self, audio: Any, sample_rate: int) -> TranscriptResult:
        transcript = self._recognizer.transcribe(audio, sample_rate)
        return TranscriptResult(
            text=transcript.text,
            language=transcript.language,
            duration_seconds=transcript.duration_seconds,
            inference_seconds=transcript.inference_seconds,
            rejected_segments=1 if transcript.rejected else 0,
            rejection_reasons=(
                (transcript.rejection_reason,) if transcript.rejection_reason else ()
            ),
        )
