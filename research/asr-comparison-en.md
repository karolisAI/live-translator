# ASR engine comparison: English (en-de source direction)

Companion to [asr-comparison-de.md](asr-comparison-de.md), which ran the same
comparison on German. Same VAD segmentation, same engines, same metrics — so the
two are directly comparable.

**Bottom line:** on English, whisper originally won on raw WER — the opposite of
the German result. But the gap was **not** caused by worse recognition.
Parakeet's substitution count is *lower* than whisper's (23 vs 26). Its entire
deficit came from silently dropping three whole segments of clear speech — a bug,
not a capability gap.

**That bug has since been fixed** (see
[§4](#4-the-flip-was-a-bug-not-a-capability-gap)). With the fix, Parakeet drops
to **7.12% WER**, beating whisper-base and landing within 0.6 points of
whisper-small while using a quarter of its compute and a quarter of its latency.

---

## 1. Setup

| | |
|---|---|
| Audio | TED-Ed, *One of the world's oldest beverages* — 363 s (6:03) |
| Reference | TED's published transcript, 706 words |
| Segmentation | Same offline VAD replica, same `app.example.yaml` thresholds → **72 segments** |
| Host | CPU only, `cpu_threads=8`, no GPU |
| Engines | parakeet int8 + fp32, whisper-base, whisper-small (`medium`/`turbo` excluded as too CPU-heavy) |

Audio was pulled from the HLS audio rendition (TED's direct MP4 is S3-denied).

### Reference validated before use

Learned from a discarded earlier attempt: an ASR probe was run first and matched
the transcript nearly word-for-word, confirming it is verbatim rather than an
edited article version. The reference has no hyphenation artifacts, no
run-together tokens, no page furniture, no annotation cues, no duplicated
sentences. Implied rate 117 words/min, consistent with the German test.

---

## 2. The audio broke the VAD

Before any accuracy number: **71 of 72 segments were committed by the 5 s
timeout, and only 1 by detected silence.** In the German test that split was
57.8% / 42.2%.

TED-Ed runs a continuous background music bed, so energy never falls to a true
silence floor:

| | DW German | TED-Ed English |
|---|---|---|
| frames below VAD threshold (RMS 0.008) | 29.4% | **3.6%** |
| noise floor (p1 RMS) | 0.00002 | **0.0028** — 100× higher |
| longest continuous silence | 2340 ms | 1050 ms |

The VAD needs 450 ms of sub-threshold audio to commit an endpoint. It almost
never gets it, so it degenerates into blind fixed-interval chopping and nearly
every cut lands mid-clause.

**This matters beyond this benchmark.** Any background noise with a steady floor
— music, air conditioning, a busy room, an open Teams call — will do the same
thing to this VAD. It is an energy-threshold detector with no spectral
discrimination, so it cannot tell a music bed from speech.

All engines received identical segments, so the comparison stays fair. But
absolute WER is inflated for everyone, and this is a worst-case chunking regime.

---

## 3. Results

| Engine | WER | CER | S / D / I | lat p50 | lat p95 | agg RTF | load |
|---|---|---|---|---|---|---|---|
| whisper-small int8 | **6.56%** | 3.19% | 26 / 13 / 8 | 3.25 s | 3.96 s | 0.678 | 1.7 s |
| **parakeet int8** (recovery fix) | 7.12% | 3.51% | 26 / 7 / 18 | **0.80 s** | 1.65 s | **0.174** | 3.9 s |
| whisper-base int8 | 7.54% | 4.67% | 26 / 18 / 10 | 0.99 s | 1.04 s | 0.202 | 0.9 s |
| parakeet fp32 | 12.43% | 8.92% | 25 / 32 / 32 | 0.96 s | 1.86 s | 0.210 | 6.9 s |
| *parakeet int8, before the fix* | *9.78%* | *7.05%* | *23 / 33 / 14* | *0.73 s* | *0.81 s* | *0.146* | — |

All rows come from one uncontended pass, so they are directly comparable; the
final row is retained from the pre-fix run for reference.

whisper-small edges Parakeet by 0.56 points here — but it needs **3.9× the
compute** (RTF 0.678 vs 0.174) and **4× the latency** (p50 3.25 s vs 0.80 s) to
get it. At RTF 0.678 there is little budget left for MT and TTS. Parakeet beats
whisper-base, the only whisper size with comparable latency.

Note `fp32` recovered only 1 of its 3 drops where int8 recovered 3, and remains
much worse than int8 on this recording.

### Long-form (whole recording with full context)

| Engine | WER | CER | cost |
|---|---|---|---|
| whisper-small int8 | **2.23%** | 1.20% | RTF 0.182 |
| whisper-base int8 | 4.19% | 1.69% | RTF 0.057 |
| parakeet int8, 120 s windows | 8.52% | 6.72% | RTF 0.207 |
| parakeet fp32, 120 s windows | 8.52% | 7.72% | RTF 0.199 |

Note whisper does *not* lose content in long-form here, unlike the German run
where base dropped ~12% of words. On this recording whisper's long-form is its
strongest mode.

---

## 4. The flip was a bug, not a capability gap

Parakeet has the **lowest substitution count of any engine** (23, against 26 for
both whisper sizes). Where it actually attempts a word, it is at least as
accurate as whisper. Its WER was worse purely because of deletions: 33 and 40,
against whisper's 18 and 13.

Those deletions were whole dropped segments:

| Engine | empty segments | of which real speech | audio lost |
|---|---|---|---|
| parakeet int8 | 4 | **3** | 15.0 s |
| parakeet fp32 | 3 | 2 | 10.0 s |
| whisper-base | 1 | 0 | 0 s |
| whisper-small | 0 | — | 0 s |

**Correction to an earlier version of this note.** Segment 0 was first counted as
a dropped speech segment because it measures RMS ~0.10 with 79% of samples above
0.02. Those figures are the music bed, not a voice: `0–5s` returns empty under
every transformation tried, while `0–8s` yields the opening words, so narration
only starts around 5–6 s. Parakeet was right to return nothing there. Energy
statistics cannot distinguish music from speech, which is the same blind spot the
VAD has in §2.

The other three are genuine. Each is a full 5.01 s segment of continuous
narration decoding to zero tokens, which `ParakeetRecognizer` then reports as
`no_speech` — indistinguishable, downstream, from silence.

### Root cause

Not loudness, and not the music. The same clip decodes correctly after a change
as small as halving its amplitude, and different clips are rescued by different
perturbations — one needs gain, another needs padding, a third accepts either.
That pattern is an unstable decode, not a property of the audio.

### The fix

`ParakeetRecognizer` now re-decodes a clip that produced zero tokens, perturbing
the input (silence padding, then gain) and taking the first pass that returns
text. Because the passes only perturb and never add signal, non-speech stays
empty — verified against digital silence, near-silence, white noise, and the
music-only segment above.

Retries are gated to clips of at least 3 s. Below that the retry has too little
context: on the German recording, retries of 1–2.4 s clips produced roughly as
much garbage as signal and made WER *worse* (11.44% → 12.15%), since the spurious
insertions outweighed the recovered deletions. With the gate, German is unchanged
and English gains fully.

| Recording | before | after |
|---|---|---|
| English (TED) | 9.78% WER, D=33, 4 empty | **7.12% WER, D=7, 1 empty** |
| German (DW) | 11.44% WER, D=4 | 11.44% (below gate, unchanged) |

Cost is one extra inference, paid only on a clip that produced nothing: p50
latency is barely moved (p50 0.80 s), while p95 rises to 1.65 s on the rare
recovered clip. 26 unit tests cover the behaviour.

With the fix Parakeet beats whisper-base (7.12% vs 7.54%) at lower latency, and
comes within 0.6 points of whisper-small for a quarter of the compute.

---

## 5. Other findings

**fp32 is worse than int8 on English (12.43% vs 7.12%)** — the reverse of German,
where fp32 was equal on the live path and much better long-form. The fp32 run has
more deletions (40 vs 33) *and* far more insertions (30 vs 14). Full precision is
not reliably the safer choice.

**whisper-small hallucinated `thank you for watching`** — a well-known Whisper
artifact emitted over non-speech audio, triggered here by the music bed. It
survived the app's rejection filter (`no_speech_threshold`, `log_prob_threshold`,
`compression_ratio_threshold`) and landed in the output as confident text. Worth
noting that whisper's failure mode is *inventing* content where Parakeet's is
*losing* it. For a translation pipeline both are bad, but a hallucinated sentence
is arguably worse than a gap, because it will be translated and spoken aloud.

**Shared errors across all four engines** are domain vocabulary — a South
American beverage name, an Andean region name, a Mesopotamian ruler. These are
lexical and no amount of chunking or precision fixes them.

---

## 6. A scoring bug found and fixed

The first version of these numbers was wrong and is not reported here. The German
scorer spells digits out **in German** (`13000` → `dreizehntausend`) and only for
numbers up to four digits. Applied unchanged to English audio it produced
nonsense alignments — German number words appeared in the error list for English
transcripts, and `13,000` in the reference never matched `13 thousand` in the
hypothesis.

English scoring now reduces both sides to a canonical numeric form, so
`13,000`, `13 thousand` and `thirteen thousand` all compare equal. The effect was
roughly 0.2–0.8 WER points per engine — small, but it inflated some engines more
than others, which is exactly the kind of error that corrupts a comparison.

---

## 7. German vs English side by side

| Engine | German WER | English WER | German RTF | English RTF |
|---|---|---|---|---|
| **parakeet int8** (with recovery fix) | **11.44%** | 7.12% | **0.129** | **0.174** |
| whisper-base int8 | 22.01% | 7.54% | 0.199 | 0.202 |
| whisper-small int8 | 13.20% | **6.56%** | 0.818 | 0.678 |
| *parakeet int8 before the fix* | *11.44%* | *9.78%* | — | *0.146* |

Whisper improves dramatically on English (base 22.01% → 7.54%) while Parakeet is
roughly flat. This is consistent with Whisper's training distribution being
heavily English-weighted.

Parakeet is best on German and second on English by 0.56 points, and it is the
cheapest engine in both directions by a wide margin. whisper-small buys its
English lead with 3.9× the compute.

Note what this does to the premise in the user story. Before the fix, English
looked like Parakeet's weaker direction, matching the 12/15 vs 13/15 finding
there. After the fix Parakeet is best or tied-best in **both** directions, so the
"English is marginally worse" result is better explained by the dropout bug than
by weaker English recognition — its substitution count was already the lowest of
any engine.

The two recordings still differ in more than language (news vs narration, silence
vs music bed), so this table compares *situations* as much as languages.

---

## 8. What this means for the en-de decision

1. **Keep Parakeet for `en` as well as `de`.** With the fix it beats whisper-base
   outright and trails whisper-small by 0.56 points while costing a quarter as
   much compute and a quarter the latency. There is no longer a reason to switch
   engines by direction.
2. **The dropout is fixed above 3 s, not below it.** Short utterances can still
   vanish, and `min_recovery_seconds` is the knob. Decide deliberately whether a
   lost 1–2 s utterance is worse for the pipeline than a wrong guess — in
   translation, a dropped segment is invisible downstream, but a confident wrong
   sentence gets spoken aloud.
3. **The VAD is now the most urgent problem.** An energy-threshold detector that
   collapses under background music will collapse in a Teams call. This affects
   both engines and both directions, and is independent of which ASR is chosen.
4. **Latency conclusions from the German run hold.** Parakeet p50 0.80 s at RTF
   0.174; whisper-small spends RTF 0.678 and a 3.25 s p50 to buy 0.56 WER points.
   On CPU that remains a poor trade for a live pipeline.

---

## 9. Caveats

- **n=1, again.** One narrated, scripted, single-voice recording with a music
  bed. Not conversational, not two-party, not a Teams call. The Teams-call gate
  in the user story is still open.
- **This is a worst-case chunking regime** (98.6% timeout-committed cuts).
  Absolute WER is inflated for all engines; the German run is the better guide to
  normal operation.
- **The post-fix Parakeet numbers are measured, not projected.** An earlier draft
  estimated ~5.9% by arithmetic; the measured result after the fix is 7.12%, so
  treat that estimate as superseded.
- **CPU only.** A GPU changes the latency picture entirely.
- **whisper `medium` and `large-v3-turbo` were not run** on either language, by
  request. `large-v3-turbo` remains the most plausible untested competitor.

---

## 10. Reproducing

Scratchpad scripts: `ted_extract.py` (transcript + media from page data),
`segment.py` (VAD replica), `ted_validate.py` (reference validation),
`energy.py` (music/VAD floor analysis), `bench_en.py` (all engines),
`num_en.py` (English normalization), `score_ted.py` (metrics),
`ted_drops.py` (dropout analysis).

Versions: onnx-asr 0.12.0, onnxruntime 1.28.0, faster-whisper 1.2.1.
