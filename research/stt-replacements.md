# STT Replacement Candidates

Context: current ASR stage is faster-whisper (`base` model, CPU, int8), chosen
for the `LiveTranslatorSetup.exe` installer to run on any Windows machine with
no GPU and a small bundle size (see [de-problem.md](de-problem.md) for the
accuracy issues this causes on the `de-en` profile). Any replacement has to
fit into the same `transcribe(audio, sample_rate) -> TranscriptResult`
interface in [faster_whisper_engine.py](../src/live_translator/asr/faster_whisper_engine.py),
selected via `asr.engine` in the profile config.

## 1. NVIDIA Parakeet TDT 0.6B v3

FastConformer encoder + TDT (token-and-duration transducer) decoder from
NVIDIA NeMo, 600M params. v3 added multilingual support (~25 European
languages, including German) where earlier Parakeet releases were
English-only. Tops the Hugging Face Open ASR Leaderboard for accuracy and is
very fast on GPU (real-time factor in the thousands on an A100/RTX class
card). License is CC-BY-4.0, commercially usable.

**Original assessment (2026-08-05) — WRONG, superseded:** I claimed this
was a poor fit because it "runs through the NeMo toolkit, which pulls in the
full PyTorch + NeMo dependency chain" and that "its speed advantage only
shows up on an NVIDIA GPU." Both premises were incorrect, and I should have
checked rather than assumed.

**Corrected assessment (2026-08-06):** Pre-exported ONNX builds exist
([istupakov/parakeet-tdt-0.6b-v3-onnx](https://huggingface.co/istupakov/parakeet-tdt-0.6b-v3-onnx))
and run under [`onnx-asr`](https://github.com/istupakov/onnx-asr) on plain
`onnxruntime` — **no PyTorch, no NeMo, no CUDA**. And it is genuinely fast
on CPU. Benchmarked on the same 15 German samples as everything else
(full data in [benchmarks.md](benchmarks.md)):

- **11/15 exact match** — ties `small`, beats `base` (9/15)
- **0.30s–0.87s latency**, scaling with utterance length rather than
  hitting a fixed floor — ~3.3x faster than `base` on short phrases
- **Fixes the compound-word failures** that started this whole
  investigation: `Umsatzanstieg` and `Verantwortlichkeiten` both correct,
  where `base` *and* `small` failed them
- 640 MB on disk (int8), 861 MB peak RAM

Two things make this fit the project better than I first thought: the
runtime is `onnxruntime`, and **the installer already ships
`onnxruntime.dll`** for Piper TTS ([tools/piper/](../tools/piper/)) — so the
native runtime isn't a new bundle burden, only the Python binding and the
model file are.

**Remaining concerns:** it's a new engine class, not a config change (see
"Integration cost" below); it introduces a language code-switching failure
on very short utterances ("Ja" → "Yeah"); and 640 MB vs `base`'s 142 MB is
a real installer size increase.

## 2. NVIDIA Nemotron 3.5 ASR Streaming 0.6B

A cache-aware streaming FastConformer model from the same NeMo ASR line,
built specifically for low-latency incremental recognition rather than
whole-utterance batch transcription. This is the more relevant shape for a
live translator, since it's designed to emit partial results as audio
arrives instead of waiting for a VAD-committed phrase like the current
`chunking.max_seconds` approach.

**Original assessment (2026-08-05) — WRONG, superseded:** same mistaken
"NeMo runtime, needs an NVIDIA GPU" reasoning as Parakeet above.

**Corrected assessment (2026-08-06):** ONNX exports exist
([pantinor/nemotron-3.5-asr-streaming-0.6b-onnx](https://huggingface.co/pantinor/nemotron-3.5-asr-streaming-0.6b-onnx)),
and [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) added support for
the multilingual streaming variant (1.13.4+), running real-time streaming
on a normal laptop CPU with no Python, PyTorch, or CUDA. The model is
decomposed into three ONNX sessions (cache-aware FastConformer encoder,
LSTM prediction network, joiner) and covers 40 language-locales with
auto-detection, or explicit conditioning via a `prompt_index` input.

**Not benchmarked here** — unlike Parakeet, this isn't already installed,
and exercising it means taking on `sherpa-onnx` as a dependency. It's the
architecturally *most* interesting option, because it's the only true
streaming candidate: it emits partial results while the speaker is still
talking, rather than waiting for VAD to commit a phrase. That could cut
perceived latency far more than any batch model swap.

But it's also the largest change. Today's pipeline is explicitly
phrase-at-a-time (README: "phrase-level, one-direction translation... not
simultaneous duplex interpretation"), and the whole
VAD → ASR → MT → TTS → queue chain assumes discrete committed phrases.
Adopting streaming ASR only pays off if the downstream stages change too —
otherwise partial hypotheses just get buffered until a phrase boundary and
nothing is gained. **Right idea, wrong sequencing**: revisit if/when
word-by-word output becomes a product goal.

## 3. German-fine-tuned Whisper large-v3-turbo

Community fine-tunes of OpenAI's `large-v3-turbo` (a pruned/distilled
`large-v3` with 4 decoder layers instead of 32, ~8x faster than full
`large-v3` with minor accuracy loss) trained further on German audio
specifically. `large-v3-turbo` is already supported by faster-whisper /
CTranslate2 conversion (built-in alias, no manual conversion needed).

**Fit on paper:** looked like the best match — same code path as `base`
today, just a different `asr.model` value, no new engine, no dependency or
installer changes. **Disqualified by the CPU benchmark below**: the 4-layer
decoder is cheap, but the encoder is unchanged from full `large-v3`, and that
dominates cost. It's too slow to run in real time on this CPU config, so a
German fine-tune of it inherits the same problem regardless of accuracy
gains — the bottleneck is architectural, not language-specific.

## 4. Moonshine (Moonshine AI / Useful Sensors)

Purpose-built edge ASR, 26M–245M params, explicitly designed around
Whisper's weakness here: it uses flexible input windows and "only spend[s]
compute on that input, no zero-padding required." Claims ~5x faster than
Whisper on 10s segments, and runs on a Raspberry Pi 5.

**Fit: ruled out — no German ASR.** Speech recognition covers English,
Spanish, Mandarin, Japanese, Korean, Vietnamese, Ukrainian, and Arabic.
(German appears only in their *TTS* list, which is irrelevant here.) Worth
rechecking if they extend coverage, since the architecture is otherwise
ideal for this app. It also independently corroborates the padding finding
in [benchmarks.md](benchmarks.md).

## 5. sherpa-onnx streaming Zipformer

k2-fsa's ONNX runtime for streaming transducers — very CPU-efficient
(published RTFs around 0.06–0.15), small models, true streaming, no Python
required.

**Fit: no German model published.** Available online/streaming Zipformer
models cover Chinese, English, Korean, Bengali, and Chinese+English
bilingual. Relevant mainly as the *runtime* for Nemotron (#2) rather than as
a model source in its own right.

## 6. Vosk (Kaldi-based)

Mature offline engine with a long-standing German model, true streaming,
and famously small footprint (~50 MB compact models).

**Fit: fallback only.** Consistently reported below Whisper-class accuracy,
particularly with background noise, accents, or domain vocabulary — the
exact conditions a meeting app runs in. Given the current problem is
*accuracy*, trading further accuracy away for size makes no sense here. Only
interesting if footprint ever becomes the binding constraint.

## 7. German fine-tuned Whisper (CTranslate2)

German fine-tunes do exist in CT2 form —
`Reality-Interface/whisper-large-v3-german-faster-whisper`,
`jimmymeister/whisper-large-v3-turbo-german-ct2`, and others derived from
`primeline/whisper-large-v3-german`.

**Fit: blocked by the same wall as #3.** They cluster at the `large-v3` /
`turbo` tier, so they inherit the full `large-v3` encoder and its RTF > 1.0
cost on this CPU. A `small`-tier German fine-tune would be the ideal
Whisper-family answer, but nothing established seems to exist at that size —
and even if it did, it would still carry Whisper's ~3.2s fixed floor at that
tier, which is the disqualifier for short utterances regardless of accuracy.

## Integration cost (applies to any non-Whisper engine)

Worth stating plainly, because it's the main hidden cost of moving to
Parakeet or Nemotron. The current
[faster_whisper_engine.py](../src/live_translator/asr/faster_whisper_engine.py)
rejects low-confidence output using three Whisper-specific per-segment
signals — `no_speech_prob`, `avg_logprob`, and `compression_ratio` — which
back the config's `no_speech_threshold`, `log_prob_threshold`, and
`compression_ratio_threshold`, and implement the README's "Low-energy noise
and low-confidence Whisper output are not spoken."

**Transducer models don't expose equivalents.** A new engine would need
either its own confidence measure or a different guard against speaking
garbage — this is real design work, not a config swap, and it directly
affects output quality in a live meeting. Any Parakeet trial should treat
this as the main implementation risk, not the model call itself.

## Benchmarks

All CPU/accuracy measurements referenced above live in
[benchmarks.md](benchmarks.md), not in this file — that includes the
single-sample RTF comparison across `base`/`small`/`medium`/`large-v3-turbo`,
and a 15-sample head-to-head between `base` and `small` on the same German
sentence set.

## Recommendation

**Superseded by the 2026-08-06 deep dive.** Current standing:

| Candidate | Verdict |
|---|---|
| **Parakeet TDT 0.6B v3 (ONNX int8)** | **Strongest option found.** Benchmarked, CPU-viable, fixes compound words, 3.3x faster than `base` on short phrases |
| Nemotron 3.5 streaming (ONNX) | Architecturally best, but only pays off with a streaming redesign — premature |
| large-v3-turbo (+ German fine-tunes) | Ruled out — RTF 1.62 on CPU |
| Moonshine | Ruled out — no German ASR |
| sherpa-onnx Zipformer | Ruled out — no German model |
| Vosk | Fallback only — below Whisper accuracy |
| `beam_size=5` on current `base` | Free ~7pt accuracy gain, ~5% latency cost — unrelated to model choice |

The `de-en` accuracy problem has a real candidate fix now, and it costs
latency *nothing* — Parakeet is faster than the current `base` at every
utterance length, not slower. That's a different situation from the earlier
`small` trade-off, which is why this is worth revisiting despite the earlier
"drop the model swap" decision.

Suggested order if picked back up:
1. **`beam_size=5`** — independent of everything else, essentially free.
2. **Parakeet trial behind an `asr.engine` switch** — keep faster-whisper as
   the default and make the new engine opt-in, so the installer story and
   fallback stay intact while it's evaluated on real audio.
3. **Real-audio validation** — every number in
   [benchmarks.md](benchmarks.md) comes from clean synthetic Piper speech.
   The short-utterance code-switching bug ("Ja" → "Yeah") in particular
   needs testing against real microphone input before trusting it.
4. Nemotron/streaming only if word-by-word output becomes a goal.

Prior verdicts on #3 (too slow) and the original #1/#2 dependency objection
are kept above for history — the latter was simply wrong.

The 15-sample `base` baseline in [benchmarks.md](benchmarks.md) is a useful
finding on its own: `base` gets German compounds and loanwords wrong even
on clean, noise-free audio (60% exact match), so the `de-en` accuracy
problem is at least partly a model-capacity issue, not solely
noise/truncation from real recordings.

The follow-up `small` run on the identical 15 sentences confirms it's a
real, not imagined, improvement — 73% exact match vs `base`'s 60%, and it
recovers several of the specific words `base` got wrong. But it comes with
a real cost: `small`'s per-phrase latency floor is ~3.0–3.4s regardless of
utterance length, about 3x `base`'s ~1.0–1.2s, and that floor doesn't shrink
for short acknowledgements the way `base`'s does. `medium` and
`large-v3-turbo` remain ruled out outright (RTF > 1.0 even on long audio).

**Decision (2026-08-06): dropped** — Whisper-tier model swaps aren't worth
the latency. Superseded later the same day by the Parakeet TDT finding
below, which is faster *and* more accurate than the current `base`; the
reasoning that killed `small` doesn't apply to it.

So the honest framing is a trade, not a fix: `small` measurably reduces the
`de-en` accuracy problem at the cost of roughly 2 extra seconds of latency
per phrase, stacked on top of VAD wait, translation, and TTS synthesis.
Worth trying in the live app to judge whether that latency is tolerable in
practice — synthetic-audio benchmarks can say "how much slower" but not
"does it still feel live." If it doesn't feel live, the fix isn't a bigger
CPU Whisper model — it's real-audio diagnosis
([de-problem.md](de-problem.md)'s "try next" list), a GPU-capable engine, or
chunking/threading changes to buy latency headroom.
