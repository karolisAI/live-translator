from __future__ import annotations

import zlib
from time import perf_counter
from typing import Any

from live_translator.asr.faster_whisper_engine import TranscriptResult
from live_translator.asr.parakeet_capi import ParakeetModel, set_num_threads
from live_translator.config import AsrSettings


def _compression_ratio(text: str) -> float:
    """Same heuristic faster-whisper uses (compression_ratio_threshold):
    highly repetitive/looping output compresses very well and produces a
    high ratio. Normal short phrases sit well under 1.0 -- zlib's fixed
    header/checksum overhead outweighs the savings on non-repetitive text,
    so this doesn't false-trigger on ordinary short segments."""
    raw = text.encode("utf-8")
    if not raw:
        return 0.0
    return len(raw) / len(zlib.compress(raw))


class ParakeetAsr:
    """Drop-in Parakeet (parakeet.cpp) alternative to FasterWhisperAsr.

    Offline decode only: each VAD-committed phrase is transcribed in one
    transcribe_pcm_lang call, same as faster-whisper transcribes each phrase
    in one offline call today. This does not use parakeet.cpp's cache-aware
    streaming API — see docs/01-architecture.md's "Lower-Latency Direction"
    for that as a separate, later change.

    Rejection gate: only "short" (min_segment_chars) and "compression_ratio"
    (repetition/looping) are checked. A word-confidence-based gate mirroring
    faster-whisper's no_speech_prob/avg_logprob was evaluated and NOT added:
    parakeet_capi_transcribe_pcm_batch_json_lang does expose per-word
    confidence, and it clearly flagged a known bad word in one manual check
    (0.30 vs 0.95+ on correctly-recognized neighbors) -- but across all 25
    debug-en-de segments, disputed segments' min-word-confidence (0.31-0.64)
    overlapped so heavily with clean segments' (0.27-0.85; 15 of 19 clean
    segments scored BELOW the worst disputed segment) that no threshold
    would separate them. Ship this only with better-labeled calibration data
    (real ground truth, not "disagrees with faster-whisper"), not a guess.
    """

    def __init__(self, settings: AsrSettings) -> None:
        if settings.engine.lower() != "parakeet":
            raise ValueError(f"Unsupported ASR engine: {settings.engine}")

        self._settings = settings
        if settings.cpu_threads > 0:
            set_num_threads(settings.cpu_threads)
        self._model = ParakeetModel(settings.model)

    def transcribe(self, audio: Any, sample_rate: int) -> TranscriptResult:
        start = perf_counter()
        target_lang = self._settings.source_language
        text = self._model.transcribe_pcm(audio, sample_rate, target_lang=target_lang).strip()
        inference_seconds = perf_counter() - start
        duration_seconds = len(audio) / float(sample_rate)

        rejection_reason = self._rejection_reason(text) if text else None
        rejected_segments = 0
        rejection_reasons: tuple[str, ...] = ()
        if rejection_reason:
            rejection_reasons = (rejection_reason,)
            rejected_segments = 1
            text = ""

        return TranscriptResult(
            text=text,
            language=target_lang,
            duration_seconds=duration_seconds,
            inference_seconds=inference_seconds,
            rejected_segments=rejected_segments,
            rejection_reasons=rejection_reasons,
        )

    def _rejection_reason(self, text: str) -> str | None:
        if len(text) < self._settings.min_segment_chars:
            return "short"

        ratio = _compression_ratio(text)
        if ratio > self._settings.compression_ratio_threshold:
            return f"compression_ratio={ratio:.2f}"

        return None
