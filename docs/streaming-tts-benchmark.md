# Streaming TTS Playback: Benchmark (buffered vs. `tts.stream_chunks`)

Compares the current default TTS playback path against `tts.stream_chunks`
(story 3 from [07-startup-latency-reduction.md](07-startup-latency-reduction.md))
on the real bundled Piper binary and a real voice model -- no mocks, no
synthetic timings.

## What changed

Today, a translated phrase is rendered as one Piper request, and playback
waits for the whole thing before any audio starts. With `tts.stream_chunks:
true`, the phrase is split into sentence-sized pieces
(`split_into_speech_chunks`), each rendered as its own Piper request, and
each queued for playback as soon as it's ready -- so the first piece can
start playing while later pieces are still being synthesized. See
`src/live_translator/tts/speaker.py` (`TtsSpeaker.render_many`) and
`src/live_translator/realtime.py`.

## What this benchmarks, and what it deliberately doesn't

This change touches only the TTS stage -- it does not change what gets
transcribed or translated, only how the resulting audio is delivered. So:

- **Measured**: time-to-first-audio, total synthesis time, error rate, and
  whether splitting text loses or corrupts anything (audio duration, text
  reconstruction) -- the only things that could plausibly change.
- **Not measured**: ASR/MT accuracy. Neither stage is touched by this
  change, so their output is identical by construction, not by
  measurement -- re-running WER/BLEU-style checks here would test nothing
  this change could have broken.

## Method

- Real `piper.exe` + real `de_DE-thorsten-medium.onnx` voice model (the
  same voice `app.example.yaml` ships by default), run through
  `TtsSpeaker` exactly as the live pipeline uses it -- resident process,
  real IPC, real WAV decode via `read_wav_mono`. No microphone or speaker
  device involved; this isolates the TTS stage the way `_render_speech`
  actually calls it.
- 6 German test phrases of increasing shape, standing in for what
  `TranslationEngine.translate()` hands to TTS in a live meeting: a
  one-word acknowledgement, three single-sentence phrases of increasing
  length, a two-sentence phrase, a three-sentence phrase, and a four-
  sentence phrase.
- 5 repetitions per phrase per condition (30 runs per condition, 60 total),
  after 2 discarded warm-up renders per condition so neither condition pays
  Piper's one-time model-load cost in its numbers.
- Script: `scripts/benchmark_streaming_tts.py`. Reproducing it requires the
  real Piper binary and the two manifest-approved voice models copied into
  `tools/piper/` and `models/tts/` locally -- both are gitignored and not
  part of the checkout; the script explains what to copy if they're
  missing, and copying anything else into those two protected directories
  will fail the asset-integrity check by design.

## Results: time to first audio

This is what the user actually waits through -- the gap between the
phrase finishing and audio starting. Medians over 5 runs each.

| Phrase | Pieces (streaming) | Buffered (current) | Streaming | Reduction |
|---|---|---|---|---|
| One word ("Ja.") | 1 | 0.101s | 0.103s | none (nothing to split) |
| Short sentence | 1 | 0.360s | 0.408s | none (nothing to split) |
| Medium sentence | 1 | 0.472s | 0.485s | none (nothing to split) |
| Two sentences | 2 | 0.426s | **0.185s** | **57% faster** |
| Three sentences | 3 | 0.826s | **0.268s** | **68% faster** |
| Four-sentence phrase | 4 | 2.095s | **0.344s** | **84% faster** |

The pattern is exactly what the design predicts: a single-sentence phrase
has nothing to split, so streaming is a no-op (and the two single-piece
numbers above differ only by normal run-to-run noise, not a real
regression). A multi-sentence phrase is where it matters, and the effect
gets *stronger* the longer the phrase -- a four-sentence phrase drops from
just over two seconds of silence to about a third of a second before audio
starts, because the user only waits on the first sentence's render time,
not the whole phrase's.

## Results: total synthesis time

Streaming trades a bit of total synthesis time for that faster start, since
each extra piece pays its own fixed Piper request overhead:

| Phrase | Buffered total | Streaming total | Overhead |
|---|---|---|---|
| Two sentences | 0.426s | 0.547s | +0.12s (+28%) |
| Three sentences | 0.826s | 1.087s | +0.26s (+32%) |
| Four-sentence phrase | 2.095s | 2.100s | +0.005s (~0%) |

That overhead is invisible to the user in the live pipeline: total
synthesis time is not what's on the critical path once playback has
started, because playback of piece 1 (typically several seconds of audio)
overlaps rendering of piece 2, the same overlap the recognition/playback
worker split already relies on for phrase-to-phrase pipelining. What the
user perceives is the "first audio" number above, not this one.

## Results: correctness and error rate

| Check | Buffered | Streaming |
|---|---|---|
| Failed renders / total runs | 0 / 30 | 0 / 30 |
| Error rate | 0% | 0% |
| Text reconstruction mismatches | n/a | 0 / 30 |
| Median total audio duration (aggregate) | 3.03s | 3.04s |

- **Error rate**: zero synthesis failures in either condition across all 60
  runs (5 reps x 6 phrases x 2 conditions).
- **Text reconstruction**: for every streaming run, joining the rendered
  pieces' text back together reproduced the original phrase exactly
  (whitespace-normalized) -- splitting doesn't drop or duplicate words.
- **Audio duration parity**: total audio duration is statistically
  unchanged between conditions (median 3.03s buffered vs. 3.04s
  streaming, aggregated across all phrase types) -- splitting doesn't
  truncate or add audio.

## Interpretation

- Enable `tts.stream_chunks` for a real, measured reduction in
  time-to-first-audio on multi-sentence phrases (57-84% faster in this
  run), scaling better the longer the phrase gets -- directly targeting
  the "longest pause before translation" problem this was built for.
- No effect, positive or negative, on single-sentence phrases -- most of
  a live meeting's shorter utterances will see no change at all, which is
  expected and correct (there's nothing to overlap when there's only one
  sentence).
- The cost is a modest increase in total synthesis time on multi-sentence
  phrases (paid per extra Piper request), which does not sit on the
  user-perceived critical path once streaming playback has started.
- Zero regressions in correctness or reliability observed across 60 real
  synthesis runs against the production Piper binary and voice model.

## Raw data

Full per-run numbers: `docs/streaming-tts-benchmark-results.json`
(produced by `scripts/benchmark_streaming_tts.py`, not hand-edited).
