# Reducing Startup Silence (Time-to-First-Translated-Audio)

## Problem

The gap the user feels is not "TTS latency" in isolation — it's the full serial chain
from *end of speech* to *first translated audio out*:

```
[user stops talking]
   -> VAD trailing-silence wait (chunking.silence_ms)
   -> queue hop to recognition worker
   -> full-segment ASR (faster-whisper)
   -> full-text MT (translator.translate)
   -> full-utterance TTS synthesis (Piper)
   -> first audio byte reaches the output device
```

Every stage currently waits for the *entire* previous stage's output before starting.
That serial, whole-segment design is why the measured latency floor is ~650ms and why
300ms isn't reachable without changing the architecture (per earlier tuning notes:
switching to a resident Piper process roughly halved TTS/total latency, but that
work didn't touch this chain).

Relevant code:
- `src/live_translator/config.py` — `ChunkingSettings` (defaults: `silence_ms=450`,
  `min_speech_ms=180`, `pre_roll_ms=200`, `frame_ms=30`)
- `src/live_translator/audio/rolling.py` — `RollingSpeechChunker.next_chunk`, uses
  `silence_frames = ceil(chunking.silence_ms / chunking.frame_ms)` to decide when a
  segment is "done"
- `src/live_translator/pipeline.py:267` — `_process_live_segment`, runs
  transcribe -> translate -> synthesize serially per segment

---

## 1. Cheap config tuning (no code changes)

### 1.1 Lower `chunking.silence_ms`
This is pure dead air paid on *every* utterance before ASR even starts — the chunker
won't commit a segment until it sees this much trailing silence.

- Current default: `450ms`
- Try: `300-350ms` and listen for false early-cutoffs on trailing consonants or
  natural mid-sentence pauses (dropped words at the end of phrases is the failure
  mode to watch for)
- How: set in `app.yaml` under `chunking.silence_ms`, or pass
  `--silence-ms 300` if the CLI exposes it (check `src/live_translator/cli.py`)

### 1.2 Lower `pre_roll_ms` / `min_speech_ms`
- `pre_roll_ms` (default `200ms`) pads the segment with audio captured *before*
  speech was detected, so quiet syllable onsets aren't clipped. Shrinking it saves
  a small fixed amount of ASR input length, but risks clipping consonant onsets.
- `min_speech_ms` (default `180ms`) guards against false-trigger commits; usually
  not worth lowering, it's already small.

### 1.3 Re-confirm ASR thread count
Earlier tuning found a sweet spot of 6-8 ASR threads on this box. If that config has
drifted (e.g. after an env change), re-benchmark before assuming the bottleneck is
architectural.

**Effort: minutes. Do this first and re-measure before touching code.**

---

## 2. Streaming / incremental ASR

Instead of "wait for `silence_ms` trailing silence, then transcribe the whole
segment," start transcribing while the user is still talking.

- **What it fixes**: removes `silence_ms` + full-decode time from the critical path
  — by the time VAD confirms end-of-speech, most of the transcript is already done;
  only the tail needs finalizing.
- **How**: faster-whisper doesn't support true streaming decoding natively, but you
  can approximate it:
  - Run ASR on a rolling window every N ms (e.g. every 500ms-1s) over the
    in-progress segment, keep only the latest partial transcript.
  - On VAD-confirmed silence, run one final pass over the last short tail (not the
    whole segment) and stitch it onto the last stable partial.
  - Alternative: switch to a model/runtime built for streaming (e.g. whisper.cpp's
    streaming example, or a dedicated streaming ASR like Vosk) for the "committing"
    workflow, keeping faster-whisper for a final high-accuracy pass if needed.
- **Where it plugs in**: `RollingSpeechChunker` already has `emit_while_speaking`
  (used by `rolling` chunker mode) — the pieces for incremental emission exist,
  but `_process_live_segment` (`pipeline.py:267`) still treats each callback as an
  independent full ASR->MT->TTS run rather than as an update to an in-flight one.
- **Effort: substantial.** This is the highest-leverage change but requires
  reworking segment identity (a "phrase" becomes a mutable, updatable thing rather
  than an immutable emitted chunk) and re-testing chunking correctness
  (`tests/test_rolling.py`, `tests/test_vad.py`).

---

## 3. Clause/sentence-level pipelining

For longer utterances, don't wait for the whole sentence to finish before
translating and speaking the first clause.

- **What it fixes**: perceived latency on long utterances scales with utterance
  length today; clause-level pipelining decouples "time to first sound" from
  "how long the sentence is."
- **How**: split ASR output on sentence/clause boundaries (punctuation from
  faster-whisper, or a lightweight sentence segmenter) as soon as each boundary is
  stable, translate and synthesize that clause immediately, keep decoding the rest
  in parallel.
- **Caveat**: MT quality can suffer when translating clauses out of full-sentence
  context (word order differences between source/target languages, e.g. German verb-
  final clauses need the whole clause before translation makes sense). Test
  translation quality regression before shipping, especially on DE->EN given the
  ASR-accuracy sensitivity already documented for that language pair
  (`research/de-problem.md`).
- **Effort: substantial**, and MT-language-pair dependent — smaller payoff for
  language pairs with very different word order.

---

## 4. Overlap ASR/MT/TTS stages across segments

`_process_live_segment` already overlaps *synthesis of segment N* with *playback of
segment N-1* (see the docstring at `pipeline.py:274-282` — deliberate, measured
2026-08-18: playback worker busy 4.01s/phrase vs phrases arriving every 3.52s).
That's a same-worker overlap across consecutive segments, not overlap *within* one
segment's ASR->MT->TTS chain.

- **What's next**: nothing more to gain here for a single segment (ASR must finish
  before MT can start, MT must finish before TTS can start — hard dependency) unless
  paired with #2 or #3, which make those dependencies partial rather than all-or-
  nothing.

---

## 5. Streaming TTS output (first-audio-byte vs synthesis-done)

Right now the code waits for the *entire* translated utterance to synthesize before
starting playback.

- **What it fixes**: cuts the "last stage" wait — for a multi-second translated
  sentence, this can be several hundred ms of avoidable wait between "translation
  text ready" and "first sound out."
- **How**:
  - Check whether the resident Piper process (`TtsSpeaker`, `src/live_translator/tts/`)
    can stream audio chunks to the output device as they're generated, rather than
    buffering the full WAV before playback starts. Piper's CLI streams stdout PCM
    incrementally; the question is whether `TtsSpeaker`'s consumption of that stream
    already plays as it reads, or waits for EOF first.
  - Simpler version: synthesize the first short sub-phrase and start playing it
    while synthesizing the rest (needs an MT output that can be safely chunked,
    same clause-boundary caveat as #3).
- **Effort: moderate** if Piper's stdout is already being read incrementally and
  it's just the playback call buffering; **substantial** if it requires restructuring
  `TtsSpeaker` to accept and play streamed audio chunks.

---

## 6. Perceived-latency tricks (mask, don't reduce)

These don't reduce real latency but make the wait feel shorter — cheap, safe,
worth doing regardless of what else ships.

### 6.1 Filler/tick sound on speech-end detection
Play a very short (50-100ms) non-intrusive sound the instant VAD confirms
end-of-speech, so the user gets immediate feedback that the system registered they
stopped talking, instead of dead silence during ASR/MT/TTS. Common pattern in voice
assistants (Siri/Alexa "listening" chime equivalent, but for "processing").

- **Effort: small.** Play a short pre-rendered WAV through the existing output
  device path as soon as `RollingSpeechChunker.next_chunk` returns a committed
  segment, before `_process_live_segment` starts.

### 6.2 Show partial text before audio is ready
If `show_text` is enabled, print ASR transcript and MT translation as soon as each
is available, independent of when TTS audio starts. Gives the user something well
before the audio does. Already structurally close — `_print_translation` in
`pipeline.py` runs before `_render_speech`; just needs to actually flush/print
before TTS starts rather than only after (verify ordering).

- **Effort: small**, mostly verifying/adjusting existing print ordering.

---

## 7. Better VAD for a shorter safe silence window

The current VAD is RMS+peak-threshold based (`chunking.rms_threshold`,
`chunking.peak_threshold`, adaptive noise floor in `rolling.py`/`vad.py`). It can't
distinguish "natural mid-sentence pause" from "sentence actually over" as well as a
trained model can, which is why `silence_ms` has to be conservatively long.

- **What it fixes**: potentially allows a shorter `silence_ms` without more false
  early-cutoffs, because a model-based VAD (e.g. Silero VAD, ONNX, CPU-cheap) is
  better at classifying trailing silence as "still mid-utterance" vs "utterance
  ended."
- **How**: swap the RMS-threshold speech/silence classifier in
  `RollingSpeechChunker`/`record_speech_segment` for a Silero VAD inference call per
  frame. Silero is small and fast enough to run per-frame without adding meaningful
  latency itself.
- **Effort: moderate.** Self-contained change (one classifier swap), testable in
  isolation against the existing `tests/test_vad.py`/`tests/test_rolling.py` suites
  before wiring into the live pipeline.

---

## Suggested order of attack

1. **Measure first**: instrument `_process_live_segment` (it already times
   `queue_seconds` and total `recognition+translation+synthesis` per segment in
   verbose mode — `pipeline.py:305-309`) and break that total down further into
   ASR/MT/TTS sub-timings, plus separately measure the VAD trailing-silence wait
   itself. Don't guess which stage dominates.
2. Try §1 (config tuning) — free, immediate, reversible.
3. Add §6.1 (filler sound) and verify §6.2 (partial text ordering) — cheap wins,
   improve perceived latency regardless of what else happens.
4. If the ASR/MT/TTS sum is still the dominant cost after §1: prioritize §5
   (streaming TTS first-audio-byte) since it's the shallowest architectural change
   with a real latency payoff, before attempting §2/§3 (streaming/clause ASR),
   which are the biggest undertakings and touch chunking correctness.
5. Revisit §7 only if a shorter `silence_ms` from §1.1 is causing real false
   early-cutoffs — it's a fix for a problem you may not have.
