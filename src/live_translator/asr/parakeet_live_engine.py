from __future__ import annotations

from typing import Any

from live_translator.asr.base import TranscriptResult
from live_translator.config import AsrSettings


class ParakeetLiveAsr:
    """Drop-in `parakeet-live` (onnx-asr, NVIDIA Parakeet TDT) alternative to
    FasterWhisperAsr / ParakeetAsr.

    Adapts `parakeet_live.ParakeetRecognizer` (a package maintained outside
    this repo, vendored under `packages/parakeet-live/`) to this project's
    `AsrEngine` protocol -- `ParakeetRecognizer.transcribe()` returns its own
    `Transcript` dataclass, mapped to `TranscriptResult` below.

    Named "parakeet-live" (not "parakeet") to avoid colliding with the
    existing "parakeet" engine value, which already means the nemotron/
    parakeet.cpp stack (`ParakeetAsr`) throughout this codebase's config,
    tests, and docs.
    """

    def __init__(self, settings: AsrSettings) -> None:
        if settings.engine.lower() != "parakeet-live":
            raise ValueError(f"Unsupported ASR engine: {settings.engine}")

        from parakeet_live import ParakeetRecognizer

        self._settings = settings
        self._recognizer = ParakeetRecognizer(
            model=settings.model,
            quantization=settings.compute_type,
            device=settings.device,
            cpu_threads=settings.cpu_threads,
            language=settings.source_language,
            min_chars=settings.min_segment_chars,
            log_prob_threshold=settings.log_prob_threshold,
            compression_ratio_threshold=settings.compression_ratio_threshold,
        )

    def transcribe(self, audio: Any, sample_rate: int) -> TranscriptResult:
        result = self._recognizer.transcribe(audio, sample_rate)

        rejected_segments = 1 if result.rejected else 0
        rejection_reasons = (result.rejection_reason,) if result.rejected else ()

        return TranscriptResult(
            text=result.text,
            language=result.language,
            duration_seconds=result.duration_seconds,
            inference_seconds=result.inference_seconds,
            rejected_segments=rejected_segments,
            rejection_reasons=rejection_reasons,
        )
