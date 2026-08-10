from __future__ import annotations

import zlib
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from .errors import MissingDependency, UnsupportedModel

__all__ = ["DEFAULT_MODEL", "ParakeetRecognizer", "Transcript", "compression_ratio"]

DEFAULT_MODEL = "nemo-parakeet-tdt-0.6b-v3"

# onnx-asr exposes quantization as a suffix on the ONNX file names. Callers
# often carry a Whisper-style `compute_type` string instead, so the values that
# mean "full precision" are accepted here and translated to onnx-asr's None.
_FULL_PRECISION = frozenset({"auto", "default", "float32", "fp32", "float", "none"})

_PROVIDERS = {
    "cpu": ["CPUExecutionProvider"],
    "cuda": ["CUDAExecutionProvider", "CPUExecutionProvider"],
}


@dataclass(frozen=True)
class Transcript:
    text: str
    language: str | None
    duration_seconds: float
    inference_seconds: float
    rejected: bool = False
    rejection_reason: str | None = None


class ParakeetRecognizer:
    """NVIDIA Parakeet TDT via onnx-asr (onnxruntime, no PyTorch or NeMo).

    Unlike Whisper, a transducer processes only the audio it is given instead
    of padding every input to a fixed 30-second window, so inference cost
    scales with utterance length rather than sitting on a constant floor.

    Confidence filtering rejects an utterance instead of returning doubtful
    text, and reports why:

    - Empty output is `no_speech`. There is no no-speech probability to compare
      against; the model simply emits zero tokens for silence and noise.
    - `log_prob_threshold` is applied to the averaged per-token logprobs. The
      numeric scale differs from Whisper's: measured on this model, clean
      speech averages about -0.005 and badly degraded speech about -0.44, where
      faster-whisper's default of -1.3 was chosen against Whisper's much wider
      range. Retune against real audio before tightening it.
    - `compression_ratio_threshold` catches degenerate repetition.

    Known limitation: on digital silence the model occasionally hallucinates a
    short phrase ("Thank you.", "Yeah.") and does so with confidence (-0.19 to
    -0.65 average logprob) that overlaps genuine short speech ("Ja, genau."
    measured -0.39). No threshold can separate the two, so this class does not
    try to. Gate on input energy before calling `transcribe()`.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        quantization: str | None = "int8",
        device: str = "cpu",
        cpu_threads: int = 0,
        language: str | None = None,
        min_chars: int = 2,
        log_prob_threshold: float = -1.3,
        compression_ratio_threshold: float = 2.4,
    ) -> None:
        try:
            import onnx_asr
        except ImportError as exc:  # pragma: no cover - depends on install state
            raise MissingDependency(
                "Missing dependency 'onnx-asr'. Install it with: "
                "python -m pip install parakeet-live"
            ) from exc

        self.language = language
        self.min_chars = min_chars
        self.log_prob_threshold = log_prob_threshold
        self.compression_ratio_threshold = compression_ratio_threshold

        try:
            loaded = onnx_asr.load_model(
                model,
                quantization=_normalize_quantization(quantization),
                sess_options=_session_options(cpu_threads),
                providers=_PROVIDERS.get(device.strip().lower()),
            )
        except ValueError as exc:
            if "not supported" not in str(exc):
                raise
            raise UnsupportedModel(
                f"'{model}' is not a Parakeet model. Whisper model names such as "
                f"'base' or 'small' do not work here. Use '{DEFAULT_MODEL}' or "
                f"another onnx-asr Parakeet model name."
            ) from exc
        # with_timestamps() is what surfaces per-token logprobs, which back the
        # confidence rejection below.
        self._model = loaded.with_timestamps()

    def transcribe(
        self, audio: Any, sample_rate: int, language: str | None = None
    ) -> Transcript:
        """Recognize one complete utterance.

        `language` overrides the instance default for this call only. Loading
        the model is the expensive part, so a bidirectional pipeline should
        construct one recognizer and switch language per call rather than keep
        one session per language.
        """
        spoken = self.language if language is None else language

        start = perf_counter()
        result = self._model.recognize(
            audio,
            sample_rate=sample_rate,
            **({"language": spoken} if spoken else {}),
        )
        inference_seconds = perf_counter() - start
        duration_seconds = len(audio) / float(sample_rate)

        text = result.text.strip()
        reason = self._rejection_reason(text, result.logprobs)
        if reason:
            return Transcript(
                text="",
                language=spoken,
                duration_seconds=duration_seconds,
                inference_seconds=inference_seconds,
                rejected=True,
                rejection_reason=reason,
            )

        return Transcript(
            text=text,
            language=spoken,
            duration_seconds=duration_seconds,
            inference_seconds=inference_seconds,
        )

    def _rejection_reason(self, text: str, logprobs: Any) -> str | None:
        if not text:
            # Silence and noise produce no tokens at all, which is this model's
            # equivalent of a no-speech verdict.
            return "no_speech"
        if len(text) < self.min_chars:
            return "short"

        scores = [float(value) for value in logprobs] if logprobs is not None else []
        if scores:
            avg_logprob = sum(scores) / len(scores)
            if avg_logprob < self.log_prob_threshold:
                return f"avg_logprob={avg_logprob:.2f}"

        ratio = compression_ratio(text)
        if ratio > self.compression_ratio_threshold:
            return f"compression_ratio={ratio:.2f}"

        return None


def compression_ratio(text: str) -> float:
    encoded = text.encode("utf-8")
    return len(encoded) / len(zlib.compress(encoded))


def _normalize_quantization(quantization: str | None) -> str | None:
    if quantization is None:
        return None
    value = quantization.strip().lower()
    return None if not value or value in _FULL_PRECISION else value


def _session_options(cpu_threads: int) -> Any:
    if cpu_threads <= 0:
        return None
    import onnxruntime

    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = cpu_threads
    options.inter_op_num_threads = 1
    return options
