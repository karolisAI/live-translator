from __future__ import annotations

import zlib
from time import perf_counter
from typing import Any

from live_translator.asr.base import TranscriptResult
from live_translator.config import _DEFAULT_ASR_MODELS, AsrSettings
from live_translator.errors import MissingDependency

__all__ = ["ParakeetAsr"]

DEFAULT_MODEL = _DEFAULT_ASR_MODELS["parakeet"]

# onnx-asr exposes quantization as a suffix on the ONNX file names. The config
# reuses faster-whisper's `compute_type` key, so translate the values that mean
# "full precision" into onnx-asr's None.
_FULL_PRECISION = {"auto", "default", "float32", "fp32", "float", "none"}

_PROVIDERS = {
    "cpu": ["CPUExecutionProvider"],
    "cuda": ["CUDAExecutionProvider", "CPUExecutionProvider"],
}


class ParakeetAsr:
    """NVIDIA Parakeet TDT via onnx-asr (onnxruntime, no PyTorch or NeMo).

    Unlike Whisper, a transducer processes only the audio it is given instead of
    padding every input to a fixed 30-second window, so inference cost scales
    with utterance length. See research/benchmarks.md.

    The engine reuses `AsrSettings` rather than adding a parallel schema, so a
    few Whisper-specific keys do not apply here:

    - `beam_size` / `condition_on_previous_text`: no equivalent in TDT greedy
      decoding; ignored.
    - `no_speech_threshold`: no probability to compare against. The model
      usually emits zero tokens for silence, which is handled directly.
    - `log_prob_threshold` / `compression_ratio_threshold`: honoured, but the
      numeric scale differs from Whisper's. Measured on this model, clean
      speech averages about -0.005 and badly degraded speech about -0.44,
      where faster-whisper's default of -1.3 was chosen against Whisper's
      wider range. Retune against real audio before tightening.

    Known limitation: on digital silence the model occasionally hallucinates a
    short phrase ("Thank you.", "Yeah.") rather than returning nothing, and it
    does so with confidence (-0.19 to -0.65 average logprob) that overlaps
    genuine short speech ("Ja, genau." measured -0.39). No `log_prob_threshold`
    can separate the two, so this engine does not try to. The pipeline's
    pre-ASR energy gate is what prevents it: silence never reaches
    `transcribe()` in the live path. Keep that gate in front of this engine.
    """

    def __init__(self, settings: AsrSettings) -> None:
        if settings.engine.lower() != "parakeet":
            raise ValueError(f"Unsupported ASR engine: {settings.engine}")

        try:
            import onnx_asr
        except ImportError as exc:
            raise MissingDependency(
                "Missing dependency 'onnx-asr'. Install it with: "
                'python -m pip install -e ".[parakeet]"'
            ) from exc

        self._settings = settings
        quantization = settings.compute_type.strip().lower()
        try:
            model = onnx_asr.load_model(
                settings.model,
                quantization=None if quantization in _FULL_PRECISION else quantization,
                sess_options=self._session_options(),
                providers=_PROVIDERS.get(settings.device.strip().lower()),
            )
        except ValueError as exc:
            if "not supported" not in str(exc):
                raise
            raise ValueError(
                f"asr.model '{settings.model}' is not a Parakeet model. Whisper model "
                f"names such as 'base' or 'small' only work with "
                f"asr.engine 'faster-whisper'. Use '{DEFAULT_MODEL}' "
                f"(or another onnx-asr model name) with asr.engine 'parakeet'."
            ) from exc
        # with_timestamps() is what surfaces per-token logprobs, which back the
        # low-confidence rejection below.
        self._model = model.with_timestamps()

    def _session_options(self) -> Any:
        if self._settings.cpu_threads <= 0:
            return None
        import onnxruntime

        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = self._settings.cpu_threads
        options.inter_op_num_threads = 1
        return options

    def transcribe(self, audio: Any, sample_rate: int) -> TranscriptResult:
        start = perf_counter()
        language = self._settings.source_language
        result = self._model.recognize(
            audio,
            sample_rate=sample_rate,
            **({"language": language} if language else {}),
        )
        inference_seconds = perf_counter() - start

        text = result.text.strip()
        reason = self._rejection_reason(text, result.logprobs)
        if reason:
            return TranscriptResult(
                text="",
                language=language,
                duration_seconds=len(audio) / float(sample_rate),
                inference_seconds=inference_seconds,
                rejected_segments=1,
                rejection_reasons=(reason,),
            )

        return TranscriptResult(
            text=text,
            language=language,
            duration_seconds=len(audio) / float(sample_rate),
            inference_seconds=inference_seconds,
        )

    def _rejection_reason(self, text: str, logprobs: Any) -> str | None:
        if not text:
            # Silence and noise produce no tokens at all, which is this model's
            # equivalent of a no-speech verdict.
            return "no_speech"
        if len(text) < self._settings.min_segment_chars:
            return "short"

        scores = [float(value) for value in logprobs] if logprobs is not None else []
        if scores:
            avg_logprob = sum(scores) / len(scores)
            if avg_logprob < self._settings.log_prob_threshold:
                return f"avg_logprob={avg_logprob:.2f}"

        compression_ratio = _compression_ratio(text)
        if compression_ratio > self._settings.compression_ratio_threshold:
            return f"compression_ratio={compression_ratio:.2f}"

        return None


def _compression_ratio(text: str) -> float:
    encoded = text.encode("utf-8")
    return len(encoded) / len(zlib.compress(encoded))
