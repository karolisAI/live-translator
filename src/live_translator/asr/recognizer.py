from __future__ import annotations

import zlib
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from live_translator.errors import MissingDependency, UnsupportedModel

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
    """Which recovery passes produced this text, or None if the first try did."""
    covered_seconds: float = 0.0
    """How far into the audio the last emitted token sits.

    `duration_seconds - covered_seconds` is the audio that produced no tokens at
    all. A fraction of a second is normal -- segments end on trailing silence.
    Seconds of it on continuous speech is the truncation this class works to
    prevent, and leaving it visible lets a caller measure that for itself.
    """
    avg_logprob: float | None = None
    """Mean per-token logprob, whether or not the text was accepted.

    log_prob_threshold only rejects far below this model's real confidence
    range (see class docstring); this is the raw signal for a caller that
    wants to flag an accepted-but-uncertain segment rather than reject it.
    """
    low_confidence: bool = False
    """True when accepted but avg_logprob fell below flag_log_prob_threshold.

    Never true alongside rejected=True -- a rejected segment has no text to
    flag. Always false when flag_log_prob_threshold is unset (the default):
    this is an opt-in signal, not a second rejection gate.
    """


@dataclass(frozen=True)
class _Decoded:
    """One model call: its text, and the span of audio its tokens cover."""

    text: str
    logprobs: Any
    first: float | None
    last: float | None

    def shifted_by(self, offset: float) -> _Decoded:
        """Move the timestamps onto the caller's timeline.

        A recovery pass decodes audio it has padded or trimmed, so its clock is
        offset from the audio the caller passed in.
        """
        if self.first is None or self.last is None:
            return self
        return _Decoded(
            self.text,
            self.logprobs,
            max(0.0, self.first + offset),
            max(0.0, self.last + offset),
        )


class ParakeetRecognizer:
    """NVIDIA Parakeet TDT via onnx-asr (onnxruntime, no PyTorch or NeMo).

    Unlike Whisper, a transducer processes only the audio it is given instead
    of padding every input to a fixed 30-second window, so inference cost
    scales with utterance length rather than sitting on a constant floor.

    Confidence filtering rejects an utterance instead of returning doubtful
    text, and reports why:

    - Empty output is `no_speech`. There is no no-speech probability to compare
      against; the model simply emits zero tokens for silence and noise.
    - `log_prob_threshold` is applied to the averaged per-token logprobs.
      Measured on this model, clean speech averages about -0.005 and badly
      degraded speech about -0.44, so the default of -1.3 almost never fires.
      Retune against real audio before tightening it.
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

    Emitting nothing turns out to be the extreme case of a broader defect: the
    decoder can stop emitting *part way through* a segment and never resume, so
    the opening is transcribed and the tail is silently lost. Traced through the
    transducer loop, the joint emits the blank token at every remaining frame,
    and at the largest duration it can predict, so it sweeps to the end of the
    segment fast and in silence. Segments that decode cleanly never predict those
    long durations. The result reads downstream as a fluent, confident, and
    incomplete sentence -- worse than a visible gap, because nothing marks it.

    `recover_gaps` closes that gap by treating decoding as a coverage problem
    rather than a one-shot call. The token timestamps say which span of audio the
    decoder actually got to; if a run of at least `min_gap_seconds` is left over
    at either end and still carries energy, that run is decoded on its own and
    joined back on. A fresh call starts from a fresh decoder state, which is what
    breaks the stall -- the audio was never the problem. See `_cover_gaps`.
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
        flag_log_prob_threshold: float | None = None,
        compression_ratio_threshold: float = 2.4,
        recover_empty: bool = True,
        min_recovery_seconds: float = 3.0,
        recover_gaps: bool = True,
        min_gap_seconds: float = 1.0,
        max_gap_passes: int = 3,
    ) -> None:
        try:
            import onnx_asr
        except ImportError as exc:  # pragma: no cover - depends on install state
            raise MissingDependency(
                "Missing dependency 'onnx-asr'. Install dependencies with: "
                "python -m pip install -e ."
            ) from exc

        self.language = language
        self.min_chars = min_chars
        self.log_prob_threshold = log_prob_threshold
        self.flag_log_prob_threshold = flag_log_prob_threshold
        self.compression_ratio_threshold = compression_ratio_threshold
        self.recover_empty = recover_empty
        self.min_recovery_seconds = min_recovery_seconds
        self.recover_gaps = recover_gaps
        self.min_gap_seconds = min_gap_seconds
        self.max_gap_passes = max_gap_passes

        device_key = device.strip().lower()
        if device_key not in _PROVIDERS:
            raise ValueError(
                f"asr.device '{device}' is not supported. Use one of: "
                f"{', '.join(sorted(_PROVIDERS))}."
            )

        try:
            loaded = onnx_asr.load_model(
                model,
                quantization=_normalize_quantization(quantization),
                sess_options=_session_options(cpu_threads),
                providers=_PROVIDERS[device_key],
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
        samples = _as_samples(audio)
        duration_seconds = len(audio) / float(sample_rate)

        start = perf_counter()
        decoded = self._decode(audio, sample_rate, options)

        passes: list[str] = []
        if not decoded.text and self._worth_recovering(audio, sample_rate):
            name, decoded = self._recover(audio, sample_rate, options)
            if name:
                passes.append(name)

        if decoded.text and samples is not None:
            decoded, extra = self._cover_gaps(
                samples, sample_rate, options, decoded, duration_seconds
            )
            passes.extend(extra)

        text, logprobs, covered = decoded.text, decoded.logprobs, decoded.last
        inference_seconds = perf_counter() - start

        reason, avg_logprob = self._rejection_reason(text, logprobs, samples)
        if reason:
            return Transcript(
                text="",
                language=spoken,
                duration_seconds=duration_seconds,
                inference_seconds=inference_seconds,
                rejected=True,
                rejection_reason=reason,
            )

        low_confidence = (
            self.flag_log_prob_threshold is not None
            and avg_logprob is not None
            and avg_logprob < self.flag_log_prob_threshold
        )
        return Transcript(
            text=text,
            language=spoken,
            duration_seconds=duration_seconds,
            inference_seconds=inference_seconds,
            recovered_by="+".join(passes) if passes else None,
            covered_seconds=0.0 if covered is None else covered,
            avg_logprob=avg_logprob,
            low_confidence=low_confidence,
        )

    def _decode(self, audio: Any, sample_rate: int, options: dict[str, Any]) -> _Decoded:
        """One model call, with the span of audio its tokens actually cover.

        The timestamps are what make a partial decode observable at all; without
        them a half-decoded segment is indistinguishable from a short utterance.

        `first`/`last` are None when the model reports no timestamps, which is
        not the same as an empty list -- that is a decode which emitted nothing
        and so covered nothing.
        """
        result = self._model.recognize(audio, sample_rate=sample_rate, **options)
        timestamps = getattr(result, "timestamps", None)
        if timestamps is None:
            first = last = None
        elif len(timestamps):
            first, last = float(timestamps[0]), float(timestamps[-1])
        else:
            first = last = 0.0
        return _Decoded(result.text.strip(), result.logprobs, first, last)

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

        Each pass reports the offset between its own timeline and the caller's,
        so the coverage figure that comes back can still be compared against the
        original duration.
        """
        for name, transform, offset in _RECOVERY_PASSES:
            try:
                candidate = transform(audio, sample_rate)
            except (TypeError, ValueError):
                # Non-array audio a transform cannot handle -- skip that pass
                # rather than fail a call that already has a usable answer.
                continue
            decoded = self._decode(candidate, sample_rate, options)
            if decoded.text:
                return name, decoded.shifted_by(offset)
        return None, _Decoded("", None, None, None)

    def _cover_gaps(
        self,
        samples: Any,
        sample_rate: int,
        options: dict[str, Any],
        decoded: _Decoded,
        duration_seconds: float,
    ) -> tuple[_Decoded, list[str]]:
        """Decode the audio the first pass left without tokens, at either end.

        A stall can leave a gap in front of the first token as well as after the
        last one, and both read downstream as a fluent sentence missing a clause.
        The lead is handled first so the recovered words end up in the order they
        were spoken.
        """
        used: list[str] = []
        if not self.recover_gaps or decoded.last is None:
            # No timestamps means no way to tell a partial decode from a
            # complete one. Re-decoding on a guess would risk transcribing the
            # whole clip twice, so the coverage check simply does not apply.
            return decoded, used

        decoded, lead = self._cover_lead(samples, sample_rate, options, decoded)
        used.extend(lead)
        decoded, tail = self._cover_tail(
            samples, sample_rate, options, decoded, duration_seconds
        )
        used.extend(tail)
        return decoded, used

    def _cover_lead(
        self, samples: Any, sample_rate: int, options: dict[str, Any], decoded: _Decoded
    ) -> tuple[_Decoded, list[str]]:
        """Decode a run of audio in front of the first token and prepend it.

        One plain pass, and only a plain one. The perturbations that rescue a
        dead segment were measured inventing sentences when applied to a lead-in
        -- 'Where is it?' for audio that says 'euphoria or an adrenaline rush' --
        so a lead that decodes to nothing is left lost rather than guessed at.
        """
        first = decoded.first
        if first is None or first < self.min_gap_seconds:
            return decoded, []
        if _rms(samples[: int(first * sample_rate)]) < _GAP_SILENCE_RMS:
            return decoded, []

        # Reach past the first token rather than stopping short of it: a lead cut
        # exactly at the boundary was measured returning nothing where 160 ms
        # more returned the missing words.
        piece = samples[: int((first + _LEAD_MARGIN_SECONDS) * sample_rate)]
        lead = self._decode(piece, sample_rate, options)
        if not lead.text or not _confident_enough(lead.logprobs):
            return decoded, []

        addition = _drop_repeated_suffix(lead.text, decoded.text)
        if not addition:
            return decoded, []
        return (
            _Decoded(
                f"{addition} {decoded.text}",
                _concat_logprobs(lead.logprobs, decoded.logprobs),
                lead.first,
                decoded.last,
            ),
            ["lead"],
        )

    def _cover_tail(
        self,
        samples: Any,
        sample_rate: int,
        options: dict[str, Any],
        decoded: _Decoded,
        duration_seconds: float,
    ) -> tuple[_Decoded, list[str]]:
        """Decode whatever follows the last token, until the audio is covered.

        Each round re-decodes from just before the last token and appends what
        comes back, so a stall that begins mid-segment costs the tail of one pass
        rather than the rest of the utterance. `max_gap_passes` bounds the work
        because a tail decode can stall in turn.

        Three guards keep this from inventing content. A leftover shorter than
        `min_gap_seconds` is ignored, since every segment ends on some trailing
        silence. A leftover too quiet to hold speech is ignored, so the recogniser
        does not interrogate silence until it says something. And a round that
        fails to reach further into the audio than the last one stops the loop
        rather than re-submitting the same samples.
        """
        used: list[str] = []
        covered = decoded.last
        text, logprobs = decoded.text, decoded.logprobs

        for _ in range(max(0, self.max_gap_passes)):
            if duration_seconds - covered < self.min_gap_seconds:
                break
            # Energy is judged on the audio that was actually skipped, while the
            # decode starts a little earlier. Measuring the backed-off piece
            # instead would read the speech already transcribed and conclude
            # there is something there every time.
            if _rms(samples[int(covered * sample_rate) :]) < _GAP_SILENCE_RMS:
                break
            start_at = max(0.0, covered - _TAIL_BACKOFF_SECONDS)
            piece = samples[int(start_at * sample_rate) :]
            if len(piece) < int(self.min_gap_seconds * sample_rate):
                break

            more = self._decode(piece, sample_rate, options)
            if not more.text or not _confident_enough(more.logprobs):
                break
            reached = start_at + more.last
            if reached <= covered + _TAIL_MIN_PROGRESS:
                break

            addition = _drop_repeated_prefix(text, more.text)
            if addition:
                text = f"{text} {addition}"
                logprobs = _concat_logprobs(logprobs, more.logprobs)
            covered = reached
            used.append("tail")

        return _Decoded(text, logprobs, decoded.first, covered), used

    def _rejection_reason(
        self, text: str, logprobs: Any, samples: Any = None
    ) -> tuple[str | None, float | None]:
        """Returns (reason, avg_logprob). avg_logprob is None whenever there's
        no text or no logprobs to average, on both the rejected and accepted
        paths -- the caller (transcribe()) uses it for the separate, opt-in
        low_confidence flag on segments that don't hit a rejection reason."""
        if not text:
            # Empty output has two very different causes, and a caller that
            # cannot tell them apart cannot respond to either. Quiet audio that
            # decodes to nothing is this model's no-speech verdict. Audio loud
            # enough to hold speech that still decodes to nothing, after every
            # recovery pass, is a failed decode and a bug report.
            #
            # Energy is the only evidence available here, and it cannot tell
            # music from a voice -- a music-only segment will be reported as a
            # failed decode. The distinction is still worth drawing: it is the
            # difference between "nothing was said" and "something was lost".
            if samples is not None and _rms(samples) >= _ACTIVE_AUDIO_RMS:
                return "decode_failed", None
            return "no_speech", None
        if len(text) < self.min_chars:
            return "short", None

        scores = [float(value) for value in logprobs] if logprobs is not None else []
        avg_logprob = sum(scores) / len(scores) if scores else None
        if avg_logprob is not None and avg_logprob < self.log_prob_threshold:
            return f"avg_logprob={avg_logprob:.2f}", avg_logprob

        ratio = compression_ratio(text)
        if ratio > self.compression_ratio_threshold:
            return f"compression_ratio={ratio:.2f}", avg_logprob

        return None, avg_logprob


# How far back before the last token a tail decode starts. Enough to give the
# encoder a moment of run-up -- a tail decode started exactly on the boundary
# was measured returning nothing where 160 ms earlier returned a full clause --
# and short enough that it rarely re-reaches the previous word.
_TAIL_BACKOFF_SECONDS = 0.16

# A tail decode must reach at least this much further into the audio than the
# pass before it, otherwise the loop is repeating itself and stops.
_TAIL_MIN_PROGRESS = 0.05

# How far past the first token a lead decode reaches. A lead cut exactly at the
# token boundary was measured returning nothing where 320 ms returned the words.
_LEAD_MARGIN_SECONDS = 0.32

# Below this RMS a gap is treated as silence and not decoded. Well under
# conversational speech (measured 0.2 on the English clip, 0.05 on the German
# one) and well over a digital noise floor.
_GAP_SILENCE_RMS = 0.01

# Above this RMS, audio that decoded to nothing is reported as a failed decode
# rather than as silence. See `_rejection_reason` for what this cannot tell.
_ACTIVE_AUDIO_RMS = 0.02

# A recovered fragment must clear this mean logprob to be spliced in. Stricter
# than `log_prob_threshold`, which guards a whole utterance, because a fragment
# is joined to text that already passed and would otherwise hide inside its
# average. Measured: genuine recoveries ran -0.05 to -0.49 across both languages,
# while decoding the German intro *music* produced a fluent English sentence at
# -1.07. -0.8 sits in that gap. It does not separate a weak recovery from a
# wrong one -- nothing measured here does -- it only stops the worst case.
_RECOVERED_LOGPROB_FLOOR = -0.8

# How many words at the seam to test for repetition when appending a tail.
_SEAM_WORDS = 4


def _as_samples(audio: Any) -> Any:
    """float32 mono view of the audio, or None if it can't be used for
    sample-rate-based slicing.

    _cover_lead/_cover_tail assume one array element is 1/sample_rate
    seconds. A multi-channel array (e.g. stereo shape (n, 2)) doesn't satisfy
    that -- flattening it would silently double the apparent sample count per
    second and slice into the wrong point in the audio. Treated the same as
    any other audio gap-recovery can't handle: skip the recovery pass (see
    transcribe()'s `samples is not None` check) rather than compute against
    the wrong timeline. A trailing size-1 axis (shape (n, 1)) still flattens
    normally -- it's mono, just not already 1-D.
    """
    try:
        import numpy as np

        array = np.asarray(audio, dtype=np.float32)
        if array.ndim > 1 and array.shape[-1] > 1:
            return None
        return array.reshape(-1)
    except (TypeError, ValueError):
        return None


def _rms(samples: Any) -> float:
    import numpy as np

    if len(samples) == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(np.asarray(samples, dtype=np.float32)))))


def _words(text: str) -> list[str]:
    return ["".join(c for c in word.lower() if c.isalnum()) for word in text.split()]


def _drop_repeated_prefix(head: str, tail: str) -> str:
    """Strip any opening of `tail` that just repeats the end of `head`.

    A tail decode starts slightly before the last token it is extending, so it
    can transcribe that word a second time. Appending it would buy back a
    deletion at the price of an insertion, which is not a trade worth making.
    """
    head_words, tail_parts = _words(head), tail.split()
    tail_words = _words(tail)
    for size in range(min(_SEAM_WORDS, len(head_words), len(tail_words)), 0, -1):
        if head_words[-size:] == tail_words[:size]:
            return " ".join(tail_parts[size:])
    return tail


def _drop_repeated_suffix(lead: str, head: str) -> str:
    """Strip any ending of `lead` that just repeats the start of `head`.

    The mirror of `_drop_repeated_prefix`, for text prepended rather than
    appended: a lead decode reaches past the first token it is extending, so it
    can transcribe that word a second time.
    """
    lead_parts, lead_words = lead.split(), _words(lead)
    head_words = _words(head)
    for size in range(min(_SEAM_WORDS, len(lead_words), len(head_words)), 0, -1):
        if lead_words[-size:] == head_words[:size]:
            return " ".join(lead_parts[:-size])
    return lead


def _confident_enough(logprobs: Any) -> bool:
    """Is a recovered fragment good enough to splice into an accepted result?

    A fragment with no logprobs is accepted: the caller may have a model that
    does not report them, and refusing every recovery in that case would disable
    the feature silently.
    """
    if logprobs is None:
        return True
    scores = [float(value) for value in logprobs]
    if not scores:
        return True
    return sum(scores) / len(scores) >= _RECOVERED_LOGPROB_FLOOR


def _concat_logprobs(first: Any, second: Any) -> Any:
    """None whenever either side lacks scores.

    A fragment appended without logprobs (e.g. from a model that doesn't
    report them) still contributes text to the final transcript, so the
    combined result must not claim complete confidence data it doesn't have.
    Silently keeping the scored side (as this used to when only `second` was
    missing) would understate how much of the text was actually scored.
    """
    if first is None or second is None:
        return None
    return [*first, *second]


def _pad_with_silence(audio: Any, sample_rate: int, milliseconds: int = 250) -> Any:
    import numpy as np

    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    margin = np.zeros(int(sample_rate * milliseconds / 1000), dtype=np.float32)
    return np.concatenate([margin, samples, margin])


def _amplify(audio: Any, _sample_rate: int, factor: float = 2.0) -> Any:
    import numpy as np

    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    return np.clip(samples * factor, -1.0, 1.0)


def _trim_front(audio: Any, sample_rate: int, milliseconds: int = 160) -> Any:
    import numpy as np

    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    return samples[int(sample_rate * milliseconds / 1000) :]


# Ordered by how many of the observed failures each one recovered on its own,
# with the offset between each pass's timeline and the caller's so coverage
# stays comparable. `trim` runs last because it is the only pass that discards
# audio: it shifts where the encoder's window begins, which is the one thing
# that moves a decode that stalled from the very first frame, but it can take a
# leading word with it. That is worth risking only once nothing else has worked.
_RECOVERY_PASSES: tuple[tuple[str, Any, float], ...] = (
    ("pad", _pad_with_silence, -0.25),
    ("gain", _amplify, 0.0),
    ("trim", _trim_front, 0.16),
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
