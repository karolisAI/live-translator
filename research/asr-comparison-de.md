# ASR engine comparison: Parakeet TDT vs faster-whisper (German)

Head-to-head on one German news recording, with **both engines fed the exact
same audio segments** and scored with the exact same normalization. Companion to
[parakeet-dw-benchmark.md](parakeet-dw-benchmark.md), which covers Parakeet alone
in more depth.

**Bottom line:** Parakeet TDT 0.6b at int8 is the right engine for this pipeline.
It matches `whisper-medium` on accuracy while running **12× faster**, and beats
`whisper-base` by half the error rate while still being faster than it. The
reason is architectural, not incidental — see [Why](#why-parakeet-wins-on-latency).

---

## 1. What was tested

| | |
|---|---|
| Audio | DW *Langsam gesprochene Nachrichten*, 10 Aug 2026 — 526.4 s (8:46) |
| Reference | The article text published alongside the audio, 568 words after trimming |
| Segmentation | Offline replica of `live_translator.audio.vad` → **134 segments**, identical for every engine |
| Host | CPU only, `cpu_threads=8`, Python 3.11, no GPU |
| Settings | Exactly those in `app.example.yaml` (`beam_size=1`, `condition_on_previous_text=false`, same rejection thresholds) |

Both engines were driven through the same code path the app uses
(`FasterWhisperAsr.transcribe` logic replicated verbatim, including its
rejection filter), so this measures *the pipeline*, not just the models.

### Two modes per engine

- **Segmented** — the real live path. Audio cut into ≤5 s VAD segments, each
  transcribed independently. This is what the app actually does.
- **Long-form** — the whole recording at once (Parakeet: 120 s windows, because
  it cannot take more; whisper: full file, it windows internally). This shows
  the accuracy ceiling when the model gets full context.

### How to read the numbers

- **WER** (Word Error Rate) — % of reference words wrong. Substitutions +
  deletions + insertions, divided by reference length. **Lower is better.** This
  is the headline accuracy number.
- **CER** (Character Error Rate) — same at character level. A word can be wrong
  by one letter and still cost a full word error, so CER ≪ WER usually means
  "nearly right", e.g. German compound-splitting.
- **RTF** (Real-Time Factor) — compute seconds per audio second. **RTF 0.2 = 5×
  faster than realtime.** RTF ≥ 1.0 means the engine cannot keep up at all.
- **Latency** — time from end of speech to text available: the VAD's trailing
  silence wait plus inference. ASR only; MT and TTS add more on top.

Scoring normalizes case, punctuation, umlauts (ä→ae, ß→ss), and spells digits
out in German so `2026` and `zweitausendsechsundzwanzig` count as equal.

---

## 2. Results

### Live path (segmented — the number that matters)

| Engine | WER | CER | latency p50 | latency p95 | aggregate RTF | load |
|---|---|---|---|---|---|---|
| **parakeet-tdt-0.6b int8** | **11.44%** | 5.38% | **0.71 s** | **1.03 s** | **0.129** | 4.1 s |
| parakeet-tdt-0.6b fp32 | 11.44% | 5.49% | 0.76 s | 1.09 s | 0.148 | 5.1 s |
| whisper-base int8 | 22.01% | 4.72% | 1.11 s | 1.21 s | 0.199 | 1.2 s |
| whisper-small int8 | 13.20% | 3.25% | 3.29 s | 3.87 s | 0.818 | 1.8 s |
| whisper-medium int8 | 11.27% | 5.54% | 8.54 s * | 10.74 s * | 2.307 * | 9.1 s |

All rows except `medium` come from one uncontended pass, so they are directly
comparable.

\* `medium` was measured in an earlier run while another process was using the
CPU, so its timings are inflated by an unknown amount; its *accuracy* is
unaffected. It was not re-measured — far too slow for live use either way.

The headline pairing: **Parakeet 11.44% @ RTF 0.13 vs whisper-medium 11.27% @
RTF 2.31.** Statistically the same accuracy; Parakeet is well over an order of
magnitude cheaper. `whisper-small` is the only whisper size in the same accuracy
neighbourhood that is even arguably runnable, and at RTF 0.818 it consumes most
of the realtime budget before MT and TTS get a turn.

### Long-form (accuracy ceiling with full context)

| Engine | WER | CER | words emitted (ref 567) | cost |
|---|---|---|---|---|
| parakeet fp32, 120 s windows | **2.99%** | 0.47% | 562 | RTF 0.161 |
| parakeet int8, 120 s windows | 6.16% | 1.27% | 563 | RTF 0.135 |
| whisper-small int8, full file | 14.26% | 10.48% | 508 | RTF 0.150 |
| whisper-base int8, full file | 22.36% | 14.66% | 497 | RTF 0.035 |
| whisper-medium int8, full file | 29.05% | 27.16% | — | RTF 0.328 |

This table inverts the usual expectation and needs care — see
[§5](#5-whisper-long-form-loses-content). The word counts are the tell: both
whisper sizes emit far fewer words than the reference contains, while Parakeet
matches it.

---

## 3. Why Parakeet wins on latency

This is the core structural finding. Fitting `inference_time = a × duration + b`
across the 127 content segments:

| Engine | slope `a` | fixed cost `b` | mean inference |
|---|---|---|---|
| parakeet int8 | 0.095 | **0.128 s** | 0.484 s |
| parakeet fp32 | 0.108 | 0.151 s | 0.557 s |
| whisper-base int8 | **−0.015** | **0.804 s** | 0.747 s |
| whisper-small int8 | **−0.070** | **3.332 s** | 3.070 s |
| whisper-medium int8 | 0.111 | 8.239 s | 8.656 s |

**Whisper's slope is negative.** A 1-second segment costs the same as a
5-second segment — the duration term is statistical noise around zero. That is
Whisper's encoder padding every input to a fixed 30-second window: you pay for
30 seconds of compute no matter how little audio you hand it.

Parakeet is a transducer with no fixed window, so cost tracks actual content
(slope 0.095, i.e. ~0.1 s of compute per second of speech) on top of a small
0.13 s overhead.

**Why this decides the comparison:** this pipeline emits short segments — mean
3.75 s, and 13 of 127 are under 1.5 s. Short segments are exactly where Whisper's
padding is most wasteful. Whisper-small spends ~3.3 s to transcribe a 1 s
utterance; Parakeet spends ~0.22 s — roughly 15× less. Any future work that
lowers latency by cutting *smaller* segments makes Whisper proportionally worse
and Parakeet better.

---

## 4. Accuracy: what the errors actually are

The WER ordering (parakeet ≈ medium < small < base) hides that the engines fail
in different ways.

**whisper-base has low CER but high WER** (4.72% CER, 22.01% WER). Characters are
mostly right, word boundaries are not — it splits German compounds that the
reference writes solid. These errors are mild for a translation pipeline: MT
often recovers a split compound, and the meaning survives.

**parakeet's errors are concentrated in proper nouns.** At its 2.99% ceiling
what remains is almost entirely names rendered phonetically — a Russian party
name and `Copernicus` given a German spelling. Lexical, not acoustic; they do not
respond to better chunking, and a slightly misspelled name survives MT better
than a dropped clause.

**whisper-medium trades substitutions for deletions.** Its S/D/I is 32/13/19
against parakeet's 35/4/26 — medium drops **13 segments entirely** (vs parakeet's
4, base's 1, small's 2). Equal WER, worse failure mode: a deletion removes a fact
silently, while a substitution usually leaves something recoverable downstream.

**Casing and punctuation were good from every engine**, which matters because the
MT stage is sentence-segmented and depends on sentence boundaries.

---

## 5. Whisper long-form loses content

The long-form table looks wrong at first: whisper gains nothing from more context
(base 22.01% segmented → 22.36% long-form) while Parakeet improves sharply
(11.44% → 2.99%). This is real, and I verified the cause rather than assuming it.

Whisper-base emits **497 words for the whole recording against 567 in the
reference** — roughly 12% of the content never appears in the output;
whisper-small emits 508. Parakeet emits 563. I checked whether the app's
rejection filter was discarding segments: **it rejected zero**. The decoder
itself skips audio. This is a known Whisper long-form failure mode, made more
likely here by `condition_on_previous_text=false` (which the app sets
deliberately, to stop repetition loops from propagating).

Whisper-medium is worst (29.05% WER, 27.16% CER) — larger models drift further
once they start skipping.

The character-level numbers say the same thing more sharply than WER does:
whisper-base's long-form CER is 14.66% against 4.72% segmented. Word errors can
cancel out; missing characters cannot.

Note also that whisper's long-form output is not bit-stable between runs — an
earlier pass scored base at 26.76%. Temperature fallback fires when its internal
thresholds trip, so the amount skipped varies. Parakeet's output was identical
across runs. The figures above come from the final consistent pass.

**Practical consequence:** the accuracy ceiling numbers are only meaningful for
Parakeet. For whisper, feeding longer audio does not buy accuracy in this
configuration — it loses content. Whisper's usable accuracy is its segmented
number.

One caveat on my own method: my first attempt at this comparison scored whisper's
long-form output ~2 points too harshly, because the intro/outro stripper used
literal anchors and whisper spells one of them differently. The stripper now
matches on normalized text, so no engine is penalized for spelling. The numbers
above are post-fix.

---

## 6. Bugs found (Parakeet, both carried over from the solo benchmark)

**int8 silently drops short real speech — since fixed, but not for these four.**
Four segments returned zero tokens and were classified `no_speech` despite RMS
~0.04 and 20–38% active samples — plainly speech. One dropped segment costs a
year value in a sentence that otherwise reads fluently, the worst kind of error
for a translation pipeline because nothing downstream can detect it.

The English run ([asr-comparison-en.md](asr-comparison-en.md)) showed the same
defect destroying full 5 s segments, which pinned the root cause: an unstable
decode, not a length floor and not a loudness threshold — the same clip decodes
correctly after nothing more than halving its amplitude. `ParakeetRecognizer` now
re-decodes an empty result with the input perturbed, which cut English WER from
9.78% to 7.12%.

These four German segments are deliberately **not** recovered: all are 1.0–2.4 s,
below the 3 s `min_recovery_seconds` gate. Retrying them did return text, but two
of four were garbage, and the added insertions outweighed the recovered
deletions — German WER got worse, 11.44% → 12.15%. So German is unchanged at
11.44%, and short-utterance loss remains a real limitation on conversational
audio.

**Hard length ceiling.** A single call over the full 526 s recording fails inside
onnxruntime with a raw broadcast error (`Add_2`, 1581 vs 6581). 300 s works,
480 s does not. Never fires on the live path (≤5 s segments); it matters for any
batch mode, and it should be a typed error rather than an ONNX crash.

---

## 7. Recommendation

1. **Keep Parakeet int8 as the engine** for `de`. Best accuracy-per-CPU-second by
   a wide margin, and the only engine whose cost scales with segment length —
   which is the property this pipeline needs.
2. **`whisper-base` is the fallback**, not `small` or `medium`. It is the only
   whisper size with realtime headroom (RTF 0.265), at roughly double the error
   rate.
3. **Do not use `whisper-small`/`medium` live.** RTF 0.818 and 2.307 leave nothing
   for MT and TTS.
4. **The biggest available accuracy win is not the model — it is the chunking.**
   Parakeet goes from 11.44% to 2.99% purely from longer context, because 57.8% of
   audio is currently cut by the 5 s `max_seconds` timeout mid-clause rather than
   at a silence. RTF 0.13 leaves ample compute headroom to spend on longer
   segments; the cost is latency, currently under 1 s.
5. **Short-utterance loss is fixed above 3 s, not below it.** The recovery pass
   added to `ParakeetRecognizer` does not apply to these four German segments by
   design (§6). Before trusting Parakeet on conversational audio — where short
   utterances are far more common than in read news — decide whether losing a
   1–2 s utterance is worse for the pipeline than receiving a wrong guess, and
   set `min_recovery_seconds` accordingly.
6. **The VAD, not the engine, is the next thing to fix.** The English run found
   it collapsing into blind 5 s chopping under a steady background noise floor.
   It is an energy detector with no spectral discrimination, so an open call will
   do the same. That is engine-independent and affects both directions.

---

## 8. Caveats — read before generalizing

- **n=1.** One recording, one speaker, one domain, studio-clean and deliberately
  slowly read. This is close to a best case for every engine. Nothing here
  predicts noisy or conversational performance, and the ranking could change.
- **The reference is the published article, not a verbatim transcript.** It
  matches the read audio closely, but a small error floor remains even for a
  perfect ASR. This affects all engines equally, so comparisons are sound;
  absolute WER values are slightly pessimistic.
- **whisper-medium's timings were taken under CPU contention** and are inflated.
  Its accuracy numbers are clean.
- **`large-v3-turbo` was not run** — cancelled as too CPU-heavy for this machine.
  It is the one genuine gap in this comparison: at 809M params with a shallow
  decoder it is the whisper variant most likely to be competitive, and it remains
  untested.
- **CPU only.** A GPU would change the latency picture completely and could make
  the larger whisper models viable. This comparison only answers the CPU question.
- **int8 vs fp32 is a wash on aggregate WER** for Parakeet (11.44% both). The
  quantization cost is real but concentrated in the dropout bug above, which WER
  under-counts — 4 lost segments register as only 4 deletions.

---

## 9. Reproducing

Scratchpad scripts (not committed): `decode.py` (PyAV → 16 kHz), `segment.py`
(offline VAD replica), `bench.py`/`bench2.py` (Parakeet), `bench_whisper.py`
(faster-whisper, any model), `score.py`/`refine.py`/`strip2.py` (normalization,
WER/CER, latency), `compare.py` (the tables above), `dropped.py` and
`filter_check.py` (bug diagnosis).

Engine versions: onnx-asr 0.12.0, onnxruntime 1.28.0, faster-whisper 1.2.1.
