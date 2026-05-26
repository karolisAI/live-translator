from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from live_translator.config import AsrSettings
from live_translator.errors import MissingDependency


@dataclass(frozen=True)
class TranscriptResult:
    text: str
    language: str | None
    duration_seconds: float
    inference_seconds: float
    rejected_segments: int = 0
    rejection_reasons: tuple[str, ...] = ()


class FasterWhisperAsr:
    def __init__(self, settings: AsrSettings) -> None:
        if settings.engine != "faster-whisper":
            raise ValueError(f"Unsupported ASR engine: {settings.engine}")

        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise MissingDependency(
                "Missing dependency 'faster-whisper'. Install dependencies with: python -m pip install -e ."
            ) from exc

        self._settings = settings
        print(
            "Loading faster-whisper model "
            f"'{settings.model}' on device={settings.device} compute_type={settings.compute_type}..."
        )
        self._model = WhisperModel(
            settings.model,
            device=settings.device,
            compute_type=settings.compute_type,
        )

    def transcribe(self, audio: Any, sample_rate: int) -> TranscriptResult:
        start = perf_counter()
        language = self._settings.source_language
        segments, info = self._model.transcribe(
            audio,
            language=language,
            beam_size=self._settings.beam_size,
            vad_filter=False,
            condition_on_previous_text=self._settings.condition_on_previous_text,
            no_speech_threshold=self._settings.no_speech_threshold,
            log_prob_threshold=self._settings.log_prob_threshold,
            compression_ratio_threshold=self._settings.compression_ratio_threshold,
        )
        accepted_text: list[str] = []
        rejected_segments = 0
        rejection_reasons: list[str] = []
        for segment in segments:
            segment_text = segment.text.strip()
            reason = self._segment_rejection_reason(segment, segment_text)
            if reason:
                rejected_segments += 1
                rejection_reasons.append(reason)
                continue
            if segment_text:
                accepted_text.append(segment_text)

        text = " ".join(accepted_text).strip()
        inference_seconds = perf_counter() - start
        duration_seconds = len(audio) / float(sample_rate)
        detected_language = getattr(info, "language", None)
        return TranscriptResult(
            text=text,
            language=detected_language,
            duration_seconds=duration_seconds,
            inference_seconds=inference_seconds,
            rejected_segments=rejected_segments,
            rejection_reasons=tuple(rejection_reasons),
        )

    def _segment_rejection_reason(self, segment: Any, text: str) -> str | None:
        if len(text) < self._settings.min_segment_chars:
            return "short"

        no_speech_prob = _float_attr(segment, "no_speech_prob")
        if no_speech_prob is not None and no_speech_prob >= self._settings.no_speech_threshold:
            return f"no_speech_prob={no_speech_prob:.2f}"

        avg_logprob = _float_attr(segment, "avg_logprob")
        if avg_logprob is not None and avg_logprob < self._settings.log_prob_threshold:
            return f"avg_logprob={avg_logprob:.2f}"

        compression_ratio = _float_attr(segment, "compression_ratio")
        if (
            compression_ratio is not None
            and compression_ratio > self._settings.compression_ratio_threshold
        ):
            return f"compression_ratio={compression_ratio:.2f}"

        return None


def _float_attr(value: Any, name: str) -> float | None:
    raw = getattr(value, name, None)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
