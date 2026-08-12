# Parakeet TDT 0.6b v3 on DW "Langsam gesprochene Nachrichten" (de)

Benchmark of `packages/parakeet-live` against a known-good reference transcript,
run through the same VAD segmentation the live pipeline uses.

## Setup

| | |
|---|---|
| Source | DW *Langsam gesprochene Nachrichten*, 10 Aug 2026 (`a-78300262`) |
| Audio | 526.4 s (8:46), mp3 → 16 kHz mono, peak 0.50, RMS 0.051 |
| Reference | Article body from the page (12 paragraphs), 579 words / 568 after trimming intro+outro |
| Model | `nemo-parakeet-tdt-0.6b-v3` via onnx-asr 0.12.0, onnxruntime 1.28.0 |
| Host | CPU only (`CPUExecutionProvider`), `cpu_threads=8`, Python 3.11 |
| Segmentation | Offline replica of `live_translator.audio.vad`, thresholds from `app.example.yaml` |

This is close to a best case for the acoustics: studio-clean, deliberately slow,
single speaker, no crosstalk. Treat the numbers as an upper bound, not as what
a noisy meeting will give.

Scoring normalizes case, punctuation, umlauts (ä→ae, ß→ss) and spells digits out
in German, so `2026` and `zweitausendsechsundzwanzig` compare equal. Hyphenated
reference compounds (`Anti-Drohnen-Einheit`) are joined, because the model emits
spoken compounds as one token; without that join the live-path WER reads 12.95%
instead of 11.44%, which is a scoring artifact rather than a real error.

## Headline results

| Configuration | WER | CER | S / D / I |
|---|---|---|---|
| **VAD-segmented, int8 — the live path** | **11.44%** | 5.38% | 35 / 4 / 26 |
| VAD-segmented, fp32 | 11.44% | 5.49% | 37 / 4 / 24 |
| 120 s windows, int8 | 6.16% | 1.27% | 25 / 7 / 3 |
| 120 s windows, fp32 | **2.99%** | 0.47% | 12 / 5 / 0 |

The model is not the bottleneck. Given long windows and full precision it
transcribes this recording at ~3% WER. The live configuration gives up roughly
**4× that error rate**, and the loss is caused by how the audio is cut, not by
the acoustic model.

## Latency (live path, int8, per committed segment)

| Metric | mean | p50 | p90 | p95 | max |
|---|---|---|---|---|---|
| Segment duration | 3.75 s | 4.44 | 5.01 | 5.01 | 5.01 |
| Inference | 0.71 s | 0.77 | 0.95 | 1.01 | 1.34 |
| RTF | 0.201 | 0.186 | 0.267 | 0.298 | 0.364 |
| **Endpoint wait + inference** | **0.96 s** | 0.92 | 1.20 | 1.29 | 1.43 |

Aggregate RTF 0.188 (89.7 s of compute for 476.6 s of audio) — about 5× realtime
headroom on CPU before ASR alone saturates a core budget. Cold start is 9.7 s
(int8) / 12.9 s (fp32), which is load-once, not per utterance.

The 0.96 s figure is ASR-only lag measured from end of speech. It excludes MT and
TTS, so the end-to-end number the user hears will be higher.

### Cost is dominated by a fixed per-call overhead

Linear fit over the 127 content segments:

```
inference ≈ 0.139 × duration + 0.185 s
```

| Segment length | n | mean inference | mean RTF |
|---|---|---|---|
| 0.0–1.5 s | 13 | 0.359 s | 0.295 |
| 1.5–3.0 s | 30 | 0.507 s | 0.224 |
| 3.0–4.5 s | 22 | 0.691 s | 0.184 |
| 4.5–6.0 s | 62 | 0.882 s | 0.177 |

~0.19 s is paid per call regardless of length. Short segments are therefore
disproportionately expensive: a 1 s utterance costs RTF 0.30, a 5 s one 0.18.
Cutting segments smaller to chase lower latency buys less than it looks like it
should, because the fixed cost is re-paid every time.

## Why the live path loses 8 points of WER

**57.8% of content audio is committed by `max_seconds: 5.0`, not by silence.**
55 of 127 content segments hit the 5 s ceiling, meaning the cut lands mid-clause.
19 of those 55 end without terminal punctuation and 12 start lowercase — the
model itself is signalling that it was cut off mid-thought.

The damage shows up as insertions at the seams: `ja` (3×), `und` (3×), `zu` (2×),
plus fragments like `s`, `it`, `vor`. The live path has 26 insertions; the 120 s
fp32 run has **zero**. That gap is the boundary tax, and it is the single largest
contributor to the live WER.

Numbers straddling a boundary get mangled the same way: a decimal temperature is
split across segments 8/9 and comes out as two separate number words, and
`dreihundert` is truncated to `hundert`.

## Bug: int8 silently drops short real speech — FIXED (partially)

Four segments were rejected as `no_speech` — meaning the model emitted zero
tokens, which `ParakeetRecognizer` treats as silence. All four are unambiguously
speech:

| seg | dur | RMS | peak | samples >0.02 |
|---|---|---|---|---|
| 11 | 2.43 s | 0.049 | 0.44 | 38.4% |
| 25 | 1.29 s | 0.032 | 0.34 | 20.6% |
| 44 | 1.86 s | 0.043 | 0.41 | 31.6% |
| 55 | 1.08 s | 0.039 | 0.32 | 31.7% |

Re-running the identical spans at fp32 recovers text in 3 of the 4 (`sei
entschärft`, etc.); int8 returns empty on all 4. Adding 0.5 s of real audio
context on either side recovers all 4 even at int8. Zero-padding does **not**
help, so this is not a minimum-input-length floor — it is int8 losing short,
low-context utterances outright.

Consequence: segment 10 ends on "…aus dem Jahr" and segment 11 is empty, so the
year is dropped from the output entirely. In a translation pipeline this is worse
than a substitution — a confident, fluent sentence is emitted with a fact missing
and nothing downstream can tell.

Note this is the mirror image of the hallucination caveat in the package
docstring: that one warns about text appearing on silence, this one is speech
vanishing into `no_speech`. Neither is separable by a confidence threshold.

**Update — root cause and fix.** The same defect showed up far more severely on
English audio (see [asr-comparison-en.md](asr-comparison-en.md)), where it
destroyed three full 5 s segments. It is not a loudness threshold and not a
minimum-length floor: the same clip decodes correctly after a perturbation as
small as halving its amplitude, and different clips need different perturbations.
That is an unstable decode.

`ParakeetRecognizer` now re-decodes an empty result with the input perturbed
(padding, then gain), taking the first pass that yields text; non-speech stays
empty because the passes never add signal. On English this cut WER from 9.78% to
7.12% and deletions from 33 to 7.

**These four German segments are deliberately not recovered.** They are all
1.0–2.4 s, below the 3 s `min_recovery_seconds` gate. Retrying them did work
mechanically — all four produced text — but two of the four were garbage
(`Not Austin.` for German audio), and the resulting insertions cost more than the
recovered deletions won back: German WER got *worse*, 11.44% → 12.15%. Short
clips carry too little context for a retry to settle on the right words. Lower
the gate if losing the audio is worse for your pipeline than receiving a wrong
guess; for translation, a confident wrong sentence is arguably worse than a gap.

## Bug: hard length ceiling, undiagnosed

A single `transcribe()` call over the whole 526 s recording fails inside
onnxruntime:

```
FAIL: Add node '/layers.0/self_attn/Add_2'
Attempting to broadcast an axis by a dimension other than 1. 1581 by 6581
```

Bisecting: 300 s succeeds, 480 s fails. The relative-position buffer in the
attention layers is fixed-size, so there is a hard cap somewhere in 300–480 s.
RTF also degrades with window length (0.172 at 60 s → 0.269 at 300 s), consistent
with quadratic attention.

This never fires on the live path, where segments are ≤5 s. It matters for any
batch/file-transcription mode, and it surfaces as a raw onnxruntime broadcast
error rather than anything a caller can act on. `ParakeetRecognizer` should cap
input length and either window internally or raise a typed error.

## Remaining error character

With the boundary and quantization effects removed (120 s fp32, 2.99% WER), what
is left is almost entirely proper nouns:

- `Jabloko` → `Jablocko` (4×) — Russian party name
- `Copernicus` → `Copernikus` / `Kopernikus` — German-phonetic spelling
- `CNN` → `CN` / `CL`, `Leipzig Halle` merged into one token

These are lexical, not acoustic. They do not respond to better chunking, and for
a translation pipeline they are relatively benign — a misspelled proper noun
usually survives MT better than a dropped clause does. Casing and punctuation
were good throughout, which matters because the MT stage is sentence-segmented.

int8 vs fp32 on the *segmented* path is a wash (11.44% both), so the quantization
cost is not visible in aggregate WER — it is concentrated in the short-segment
dropout above, which WER under-counts because 4 dropped segments are only 4
deletions.

## What to change

1. **Raise `max_seconds` or cut on a smarter boundary.** 57.8% of audio being
   cut by timeout is the main accuracy cost. RTF 0.19 means there is compute
   headroom for longer segments; the tradeoff is latency, which is currently
   under 1 s and has room to spend.
2. **Empty output is no longer treated as silence unconditionally — done.**
   `ParakeetRecognizer` now re-decodes an empty result with the input perturbed,
   which recovers the failed decodes without inventing text on real silence. It
   only applies above `min_recovery_seconds` (3 s), so the four German drops here
   are still lost; see §6 of [asr-comparison-de.md](asr-comparison-de.md) for why
   recovering them made German WER worse.
3. **Decide the short-utterance policy for conversational audio.** Read news has
   few sub-3 s utterances; conversation is mostly made of them. Lower
   `min_recovery_seconds` if losing an utterance is worse than a wrong guess.
4. **Bound the input length** in `ParakeetRecognizer` instead of letting
   onnxruntime throw a broadcast error.

## Caveats

- One recording, one speaker, one domain. n=1 for a news-register voice reading
  slowly; nothing here predicts conversational or noisy performance.
- The reference is the published article text. It matches the read audio closely
  but is not a verbatim transcript, so a small floor of spurious error remains
  even for a perfect ASR.
- Scoring normalization choices move the live-path number by ~1.5 points
  (see above). Comparisons across configurations are sound because normalization
  is identical; comparisons against externally published WER figures are not.
- CPU-only. A CUDA provider would change the latency picture entirely and might
  make fp32 free.

## Reproducing

Scripts used (scratchpad, not committed): `decode.py` (PyAV → 16 kHz npy),
`segment.py` (offline VAD replica), `bench.py` / `bench2.py` (int8, fp32,
120 s windows), `score.py` / `refine.py` (WER/CER + latency), `dropped.py`
(short-segment diagnosis).
