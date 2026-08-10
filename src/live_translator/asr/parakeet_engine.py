from __future__ import annotations

from typing import Any

from live_translator.asr.base import TranscriptResult
from live_translator.config import _DEFAULT_ASR_MODELS, AsrSettings
from live_translator.errors import MissingDependency

__all__ = ["ParakeetAsr"]

DEFAULT_MODEL = _DEFAULT_ASR_MODELS["parakeet"]

_INSTALL_HINT = (
    "Missing dependency 'parakeet-live'. Install it with: "
    "python -m pip install -e .\\packages\\parakeet-live"
)


class ParakeetAsr:
    """Adapts the standalone `parakeet_live` package to this project's ASR contract.

    The recognizer itself lives in `packages/parakeet-live` so it can be
    released on its own and knows nothing about this application. This class
    only maps `AsrSettings` onto its constructor and its `Transcript` back onto
    `TranscriptResult`.

    Several `AsrSettings` fields are Whisper-specific and have no effect here:
    `beam_size` and `condition_on_previous_text` have no equivalent in TDT
    greedy decoding, and `no_speech_threshold` has no probability to compare
    against. See the package README for the confidence-threshold caveats.
    """

    def __init__(self, settings: AsrSettings) -> None:
        if settings.engine.lower() != "parakeet":
            raise ValueError(f"Unsupported ASR engine: {settings.engine}")

        try:
            from parakeet_live import MissingDependency as RecognizerMissingDependency
            from parakeet_live import ParakeetRecognizer, UnsupportedModel
        except ImportError as exc:
            raise MissingDependency(_INSTALL_HINT) from exc

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
        except RecognizerMissingDependency as exc:
            raise MissingDependency(str(exc)) from exc
        except UnsupportedModel as exc:
            # Restate the package's model complaint in terms of the config keys
            # the user actually edits.
            raise ValueError(
                f"asr.model '{settings.model}' is not a Parakeet model. Whisper model "
                f"names such as 'base' or 'small' only work with asr.engine "
                f"'faster-whisper'. Use '{DEFAULT_MODEL}' (or another onnx-asr model "
                f"name) with asr.engine 'parakeet'."
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
