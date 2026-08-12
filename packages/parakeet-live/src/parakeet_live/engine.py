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
    recovered_by: str | None = None
    """Which recovery pass produced this text, or None if the first try did."""


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

    The mirror-image failure is that the decoder sometimes emits *zero* tokens
    for audio that plainly contains speech, which would otherwise be reported as
    `no_speech` and silently drop the utterance. Measured on two recordings, this
    hit 7 of 206 segments, including full-length 5s ones. It is not a loudness
    threshold: the same clip can decode correctly after a change as small as
    halving its amplitude, which points at an unstable decode rather than a
    property of the audio. `recover_empty` retries such clips through the passes
    in `_RECOVERY_PASSES`, which recovered all 7. Retries cost an extra inference
    each, but only on the rare clip that produced nothing, and only on clips at
    least `min_recovery_seconds` long -- see `_worth_recovering` for why short
    ones are left alone.
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
        recover_empty: bool = True,
        min_recovery_seconds: float = 3.0,
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
        self.recover_empty = recover_empty
        self.min_recovery_seconds = min_recovery_seconds

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
        options = {"language": spoken} if spoken else {}

        start = perf_counter()
        result = self._model.recognize(audio, sample_rate=sample_rate, **options)

        text = result.text.strip()
        logprobs = result.logprobs
        recovered_by = None
        if not text and self._worth_recovering(audio, sample_rate):
            recovered_by, text, logprobs = self._recover(audio, sample_rate, options)

        inference_seconds = perf_counter() - start
        duration_seconds = len(audio) / float(sample_rate)

        reason = self._rejection_reason(text, logprobs)
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
            recovered_by=recovered_by,
        )

    def _worth_recovering(self, audio: Any, sample_rate: int) -> bool:
        """Retry only clips long enough for a retry to be worth trusting.

        A long clip that decodes to nothing is almost certainly a failed decode,
        and recovering it returns a whole sentence. A very short clip carries too
        little context for the retry to settle on the right words: measured on
        German news audio, retries on sub-2.5s clips produced as much garbage as
        signal, and the garbage cost more in insertions than the recovered words
        won back. Above the threshold the same fix was unambiguously positive
        (English WER 9.78% -> 7.12%).

        Set `min_recovery_seconds=0.0` to retry everything.
        """
        if not self.recover_empty:
            return False
        try:
            duration = len(audio) / float(sample_rate)
        except TypeError:
            return True
        return duration >= self.min_recovery_seconds

    def _recover(self, audio: Any, sample_rate: int, options: dict[str, Any]):
        """Re-decode a clip that produced no tokens, perturbed a little each time.

        Returns on the first pass that yields text. Genuine silence and music
        stay empty through every pass, which is what keeps this from inventing
        speech: the passes only perturb the input, they never add signal.
        """
        for name, transform in _RECOVERY_PASSES:
            try:
                candidate = transform(audio, sample_rate)
            except (TypeError, ValueError):
                # Non-array audio a transform cannot handle -- skip that pass
                # rather than fail a call that already has a usable answer.
                continue
            result = self._model.recognize(candidate, sample_rate=sample_rate, **options)
            text = result.text.strip()
            if text:
                return name, text, result.logprobs
        return None, "", None

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


def _pad_with_silence(audio: Any, sample_rate: int, milliseconds: int = 250) -> Any:
    import numpy as np

    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    margin = np.zeros(int(sample_rate * milliseconds / 1000), dtype=np.float32)
    return np.concatenate([margin, samples, margin])


def _amplify(audio: Any, _sample_rate: int, factor: float = 2.0) -> Any:
    import numpy as np

    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    return np.clip(samples * factor, -1.0, 1.0)


# Ordered by how many of the observed failures each one recovered on its own
# (6 of 8 and 5 of 8). Neither covers every case, but together they covered all
# of them, so both are kept and the cheaper-to-explain one runs first.
_RECOVERY_PASSES: tuple[tuple[str, Any], ...] = (
    ("pad", _pad_with_silence),
    ("gain", _amplify),
)


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
