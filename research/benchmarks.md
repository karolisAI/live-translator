## CPU benchmark (2026-08-06)

Ran on the actual dev machine (12 logical cores, `cpu_threads=8`, matching
`app.example.yaml`: `compute_type: int8`, `beam_size: 1`,
`condition_on_previous_text: false`). Test input: an 8.3s German sentence
synthesized with the project's own Piper voice (`de_DE-thorsten-medium`),
fed straight into `faster-whisper`'s `transcribe()`, no VAD/chunking layer
involved.

| Model            | Inference time | RTF\*  | Transcript correct? |
|------------------|----------------|--------|----------------------|
| `base` (current)  | 1.3s           | 0.15   | Yes |
| `small`           | 3.4s           | 0.41   | No — misheard "zusammen" as "Susann" |
| `medium`          | 10.5s          | 1.26   | Yes |
| `large-v3-turbo`  | 13.4s          | 1.62   | No — same "Susann" miss |

\*RTF = inference time / audio duration. RTF < 1.0 means the model keeps up
with incoming speech; RTF > 1.0 means each chunk takes longer to transcribe
than it took to speak, so the bounded phrase queue
([README](../README.md): "Bounded phrase queues prevent unlimited latency
and report any overload") backs up and grows unbounded latency.

**Takeaway:** `large-v3-turbo` is not viable on this hardware for the
real-time chunked design as it stands — it's ~10x slower than `base` and
past the RTF 1.0 line. `medium` is in the same disqualified territory.
`small` is the only middle ground with headroom to spare (RTF 0.41), but on
this one sample it was *less* accurate than `base`, not more — the opposite
of what motivated this search.

Caveats on this data: single synthetic (TTS-generated, clean, no
background noise) sentence, run once per model. The RTF numbers are solid —
they're pure compute cost, roughly independent of audio content — but the
accuracy column is a single data point and shouldn't be trusted as a
real accuracy ranking. It would take a real German meeting recording (ideally
via `--debug-audio-dir`) run through several models to say anything reliable
about accuracy.

## Base model accuracy baseline (15 samples, 2026-08-06)

Follow-up to the RTF benchmark above: 15 German sentences synthesized with
the project's own Piper voice (`de_DE-thorsten-medium`), ranging from 1.1s
short acknowledgements to 6.8s meeting-style sentences (62.9s of audio
total), run through the current production model (`base`, int8, CPU,
`beam_size=1`, same thresholds as `app.example.yaml`). Purpose: check
whether `base`'s accuracy problem shows up even on clean, noise-free audio,
independent of everything a real microphone/room adds on top.

| # | Duration | RTF | Match | Truth → ASR (only where different) |
|---|---|---|---|---|
| 01 | 1.1s | 0.87 | OK | — |
| 02 | 1.8s | 0.54 | DIFF | "verschieben" → "verschieden" |
| 03 | 1.3s | 0.74 | OK | — |
| 04 | 2.0s | 0.49 | OK | — |
| 05 | 3.4s | 0.31 | DIFF | "Deadline" → "Diardlöne" |
| 06 | 3.2s | 0.34 | OK | — |
| 07 | 4.9s | 0.23 | OK | — |
| 08 | 4.9s | 0.25 | OK | — |
| 09 | 5.2s | 0.24 | DIFF | "um zwei" → "uns zwei" |
| 10 | 4.8s | 0.23 | OK | — |
| 11 | 5.3s | 0.21 | DIFF | "Quartalszahlen" → "Quart- als Zahlen", "Umsatzanstieg" → "Umsatzanstik" |
| 12 | 6.1s | 0.18 | DIFF | "Verantwortlichkeiten" → "Verantwortlichkeit" (plural dropped) |
| 13 | 6.3s | 0.18 | OK | — |
| 14 | 5.8s | 0.20 | DIFF | "Mikrofone stummschalten" → "mikrofonisch dumm schalten" |
| 15 | 6.8s | 0.17 | OK | — |

**RTF:** min 0.17, max 0.87, mean 0.34 — comfortable real-time headroom
across every sample, shortest to longest. Confirms `base` was never the
latency problem.

**Accuracy: 9/15 exact match (60%)**, on studio-clean synthetic speech with
no background noise, no accent, no overlapping talk — the easiest possible
case. Every miss clusters around the same two failure modes:

- **Compound-word splitting/garbling**: `Quartalszahlen` → "Quart- als
  Zahlen", `stummschalten` → "dumm schalten", `Umsatzanstieg` →
  "Umsatzanstik". `base`'s vocabulary/context window seems to lose the
  thread on longer German compounds specifically.
- **Loanword/near-homophone substitution**: `Deadline` → "Diardlöne",
  `verschieben` → "verschieden", `um` → "uns". Small, phonetically close
  substitutions — consistent with a model that's undersized for the
  language rather than one confused by audio quality.

This lines up with [de-problem.md](de-problem.md)'s hypothesis and rules out
one alternative explanation: the accuracy problem isn't solely a room-noise
or truncation artifact from real recordings — `base` mishandles German
compounds and loanwords even on clean, isolated sentences. That's a genuine
model-capacity signal, not just a chunking/VAD symptom.

## `small` — same 15-sample set (2026-08-06)

Identical 15 sentences, identical settings, model swapped to `small`.

| # | Duration | Latency | RTF | Match | Truth → ASR (only where different) |
|---|---|---|---|---|---|
| 01 | 1.14s | 3.00s | 2.63 | OK | — |
| 02 | 1.78s | 3.21s | 1.81 | OK | — |
| 03 | 1.28s | 3.10s | 2.42 | OK | — |
| 04 | 2.03s | 3.04s | 1.50 | OK | — |
| 05 | 3.35s | 3.31s | 0.99 | DIFF | "Deadline" → "Deateline" |
| 06 | 3.15s | 3.26s | 1.04 | OK | — |
| 07 | 4.93s | 3.18s | 0.65 | OK | — |
| 08 | 4.90s | 3.19s | 0.65 | OK | — |
| 09 | 5.20s | 3.22s | 0.62 | OK | — |
| 10 | 4.84s | 3.32s | 0.69 | OK | — |
| 11 | 5.25s | 3.18s | 0.61 | DIFF | "Quartalszahlen" → "Quad als Zahlen", "Umsatzanstieg" → "Umsatz an Stick" |
| 12 | 6.14s | 3.26s | 0.53 | DIFF | "Verantwortlichkeiten" → "Verantwortlichkeit" |
| 13 | 6.31s | 3.40s | 0.54 | OK | — |
| 14 | 5.82s | 3.41s | 0.59 | DIFF | "stummschalten" → "stumm schalten" (rest of sentence correct) |
| 15 | 6.81s | 3.33s | 0.49 | OK | — |

**RTF:** min 0.49, max 2.63, mean 1.05 — misleading in aggregate. **The real
story is the latency floor**: every sample takes ~3.0–3.4s regardless of
whether the audio is 1.1s or 6.8s long. That's a near-fixed per-call cost,
not a duration-scaled one — for short acknowledgements the RTF spikes past
2.6 because there's almost no audio to amortize the floor against.

**Accuracy: 11/15 (73%)** exact match — a real improvement over `base`'s
9/15. On inspection, sample 14's "miss" is a compound-word space, not a
wrong word (`base` mangled the same sentence to "mikrofonisch dumm
schalten"; `small` gets every word right and only splits `stummschalten`
into two). `small` still fumbles the same compound-word case `base` did
(11) and still garbles `Deadline`, but recovers `verschieben`, `um`/`uns`,
and `Mikrofone` correctly where `base` didn't.

## `base` vs `small` — direct comparison

| | `base` | `small` |
|---|---|---|
| Exact match (15 samples) | 9/15 (60%) | 11/15 (73%) |
| Per-phrase latency floor | ~1.0–1.2s | ~3.0–3.4s |
| RTF at longest sample (6.8s) | 0.17 | 0.49 |
| RTF at shortest sample (1.1s) | 0.87 | 2.63 |

`small` is measurably more accurate on this set, but roughly **3x slower
per phrase in absolute terms**, and that gap doesn't shrink for short
utterances — a one-word "Ja, genau." costs about the same ~3s as a full
sentence. In a live pipeline that lands on top of VAD wait, translation,
and TTS synthesis, so it's a real user-facing latency increase, not just a
number that looks fine because RTF stays under 1.0. Whether that trade is
acceptable is a product call, not a benchmarking one — worth trying in the
live app before deciding either way.

## `base` — `beam_size=1` vs `beam_size=5` (2026-08-06)

Same 15-sample set, `base` model kept fixed, only `beam_size` changed
(current production value is 1, greedy decoding).

| # | `beam=1` | `beam=5` | Changed? |
|---|---|---|---|
| 01 | OK | OK | — |
| 02 | DIFF ("verschieben"→"verschieden") | DIFF (same) | no |
| 03 | OK | OK | — |
| 04 | OK | OK | — |
| 05 | DIFF ("Deadline"→"Diardlöne") | DIFF (same) | no |
| 06 | OK | OK | — |
| 07 | OK | OK | — |
| 08 | OK | OK | — |
| 09 | DIFF ("um"→"uns") | **OK** | fixed |
| 10 | OK | OK | — |
| 11 | DIFF (compound-word garble) | DIFF (same) | no |
| 12 | DIFF ("Verantwortlichkeiten"→singular) | DIFF (same) | no |
| 13 | OK | OK | — |
| 14 | DIFF (compound-word garble) | DIFF (same) | no |
| 15 | OK | OK | — |

**Accuracy: 9/15 → 10/15 (60% → 67%)** — one sample fixed (09), the rest
unchanged. Doesn't touch the compound-word garbling (11, 14) or the
`Deadline` loanword miss (05) — beam search picks a better path through the
same vocabulary, it doesn't give the model new German vocabulary.

**Latency: essentially free.** Total inference across all 15 samples: 16.32s
(beam=1) → 17.22s (beam=5), about +5.5%. Mean RTF 0.34 → 0.36. Unlike the
`small`/`medium`/`large-v3-turbo` swaps, this isn't a real trade — for a
model this size, the decoder's extra branching at `beam_size=5` costs almost
nothing next to the encoder's fixed per-call cost.

**Conclusion: `beam_size=5` is a strictly better setting than the current
`beam_size=1` for `base`** — a real (if modest) accuracy gain at
negligible latency cost, no dependency changes, no new model to download.
Worth shipping regardless of what happens with the model-swap question.
It doesn't fix the compound-word/loanword failure modes though — those need
either a bigger model (ruled out above) or a fix upstream of decoding
(training data, tokenizer, or the VAD/chunking issues `de-problem.md`
already flagged).

## Why Whisper has a fixed latency floor (2026-08-06)

Both the `base` and `small` runs above showed per-phrase latency that barely
moved with utterance length (`small`: ~3.2s whether the clip was 1.1s or
6.8s). Tested directly by truncating one sample to different lengths and
re-running `base`:

| Audio length | Inference | Output chars |
|---|---|---|
| 1.0s | 0.803s | 19 |
| 2.0s | 0.869s | 33 |
| 4.0s | 0.920s | 74 |
| 6.0s | 0.983s | 123 |

**6x more audio costs only ~22% more time.** This is Whisper's architecture,
not a tuning problem: it pads every input to a fixed 30-second mel window,
so the encoder does identical work for a 1-second "Ja" and a 25-second
monologue. Only the decoder loop scales, and it scales with *output tokens*,
not input duration. (A 0.5s trial came in at 1.99s — treated as
allocation/warmup noise, not signal.)

This matters a lot for this app specifically. It's phrase-based, and
meeting speech is full of 1–2s utterances ("ja", "genau", "moment", "kurz
Frage") — every one of those pays the full 30-second encoder cost. It also
means **no amount of chunking tuning can reduce the floor**, and it's the
single reason `small` is unusable here despite being more accurate.

Architectures that don't pad — transducers (RNNT/TDT) and CTC models —
process only the audio actually present, so latency scales with utterance
length. That's the property worth shopping for; see the Parakeet run below.

## Parakeet TDT 0.6B v3 (ONNX, CPU) — same 15-sample set (2026-08-06)

Run via [`onnx-asr`](https://github.com/istupakov/onnx-asr) on
`onnxruntime` **with no PyTorch or NeMo involved** — which invalidates the
dependency objection originally raised against this model in
[stt-replacements.md](stt-replacements.md). Same 15 German samples, same
machine. Language pinned to `de`.

| # | Duration | Latency (int8) | RTF | Match | Truth → ASR (where different) |
|---|---|---|---|---|---|
| 01 | 1.14s | 0.30s | 0.29 | DIFF | "Ja, genau" → "**Yeah**, genau" |
| 02 | 1.78s | 0.41s | 0.23 | OK | — |
| 03 | 1.28s | 0.31s | 0.24 | OK | — |
| 04 | 2.03s | 0.44s | 0.22 | OK | — |
| 05 | 3.35s | 0.59s | 0.18 | DIFF | "Deadline" → "DR-Löhne" |
| 06 | 3.15s | 0.60s | 0.19 | OK | — |
| 07 | 4.93s | 0.78s | 0.16 | OK | — |
| 08 | 4.90s | 0.66s | 0.13 | OK | — |
| 09 | 5.20s | 0.78s | 0.15 | OK | — |
| 10 | 4.84s | 0.69s | 0.14 | OK | — |
| 11 | 5.25s | 0.74s | 0.14 | DIFF | "Quartalszahlen" → "Quartalstahlen"; "zwölf Prozent" → "12%" |
| 12 | 6.14s | 0.81s | 0.13 | OK | — |
| 13 | 6.31s | 0.82s | 0.13 | OK | — |
| 14 | 5.82s | 0.76s | 0.13 | DIFF | "stummschalten" → "stumm schalten" (rest correct) |
| 15 | 6.81s | 0.87s | 0.13 | OK | — |

**Accuracy: 11/15 (73%)** — ties `small`, beats `base` (9/15). But the
*quality* of the remaining misses is better than the count suggests:

- **11** is a one-letter slip (`Quartalstahlen`) plus a numeral-formatting
  choice (`12%` vs `zwölf Prozent`) — semantically intact. Compare `base`,
  which produced "Quart- als Zahlen ... Umsatzanstik", which is not.
- **14** is a compound-word space, every word correct.
- It gets `Umsatzanstieg` and `Verantwortlichkeiten` right — **both of which
  `base` and `small` got wrong.** The compound-word failure mode that
  motivated this whole search is largely gone.
- **01 is a genuine new failure mode**: "Ja" → "Yeah". This is a
  multilingual model code-switching on a very short utterance with almost no
  context to language-ID from, despite `language="de"`. Short interjections
  are exactly what a meeting app sees constantly, so this needs watching.

**Latency scales with audio length** (0.30s → 0.87s), as the transducer
architecture predicts — no fixed floor:

| | `base` (Whisper) | Parakeet TDT int8 |
|---|---|---|
| Shortest sample (1.1s) | 1.00s | **0.30s** |
| Longest sample (6.8s) | 1.15s | 0.87s |
| Total (62.9s audio) | 16.3s | **9.9s** |
| Mean RTF | 0.34 | **0.18** |

On short utterances it is **~3.3x faster than `base`** and ~10x faster than
`small`, while matching `small`'s accuracy.

### fp32 vs int8

| | fp32 | int8 |
|---|---|---|
| Exact match | 11/15 | 11/15 |
| Total inference | 11.14s | 9.85s |
| Max latency | 1.14s | 0.87s |
| Encoder on disk | 2,323 MB | **622 MB** |

int8 is strictly better here — same accuracy, faster, ~3.7x smaller. Use it.

### Footprint vs the current engine

| | `base` (CT2 int8) | Parakeet TDT (ONNX int8) |
|---|---|---|
| Model on disk | 142 MB | 640 MB |
| Peak process RAM | 489 MB | 861 MB |

Measured peak working set over 3 sequential transcriptions. Parakeet needs
~1.8x the RAM and ~4.5x the disk — real installer cost, but not
disqualifying on any machine that can run a video call.

## Low-end hardware: thread scaling (2026-08-06)

All benchmarks above ran with 8 threads on a 12-logical-core machine, which
is **not** representative of the "any Windows PC, even low-end" target. This
run restricts thread count to simulate weaker CPUs. Three clips: short
(1.14s), medium (4.90s), long (6.81s). Best of 3 runs each.

`cores_used` = CPU-seconds ÷ wall-seconds, i.e. how many cores were actually
saturated. CPU-seconds is the honest measure of battery/thermal cost.

### `base` (faster-whisper, int8)

| Threads | 1.14s clip | 4.90s clip | 6.81s clip | CPU-s (all 3) |
|---|---|---|---|---|
| 1 | 2.126s (**RTF 1.86**) | 2.325s | 2.416s | 6.81 |
| 2 | 1.190s (RTF 1.04) | 1.346s | 1.387s | 7.86 |
| 4 | 0.779s | 0.902s | 0.925s | 10.64 |
| 8 | 0.852s | 0.994s | 1.003s | 22.23 |

### Parakeet TDT 0.6B v3 (ONNX, int8)

| Threads | 1.14s clip | 4.90s clip | 6.81s clip | CPU-s (all 3) |
|---|---|---|---|---|
| 1 | **0.361s** (RTF 0.32) | 1.346s | 1.845s | 3.56 |
| 2 | 0.223s | 0.796s | 1.087s | 4.42 |
| 4 | 0.187s | 0.573s | 0.757s | 7.02 |
| 8 | 0.298s | 0.735s | 0.971s | 17.58 |

### Findings

**1. Parakeet's advantage grows as hardware gets weaker.** At 1 thread it is
**5.9x faster** than `base` on the short clip (0.36s vs 2.13s) and still
1.3x faster on the long one. Parakeet on a *single* thread beats `base` on
*four* threads for short utterances (0.361s vs 0.779s).

**2. `base` fails real-time on a single core.** RTF 1.86 on the 1.14s clip —
a single-core machine cannot keep up with short utterances using the current
engine. Parakeet stays at RTF 0.27–0.32 across all lengths at 1 thread.

**3. Parakeet burns roughly half the total CPU.** 3.56 vs 6.81 CPU-seconds
at 1 thread. Whisper's 30s padding means it performs full-window encoder
work no matter how short the phrase, so it wastes CPU precisely on the short
utterances a meeting is full of. Lower CPU means less fan noise, less
battery drain, and less contention with the video-call app sharing the
machine.

**4. `cpu_threads: 8` in the current config is a pessimisation.** For
`base`, 4 threads is *faster* than 8 (0.902s vs 0.994s on the medium clip)
while using **less than half** the CPU (10.6 vs 22.2 CPU-seconds). Past ~4
threads the coordination overhead exceeds the gain. The same holds for
Parakeet (4 threads beats 8). Lowering `cpu_threads` to 4 looks like a free
win for latency *and* CPU cost — worth verifying on real audio, but it is a
one-line config change with no model swap involved.

**5. No GPU anywhere in these numbers.** The installed `onnxruntime` 1.28.0
exposes only `['AzureExecutionProvider', 'CPUExecutionProvider']` — there is
no CUDA execution provider in this build, so a GPU path does not exist even
if a GPU were present. Every measurement here is pure CPU.

## Both directions through the real engine interface (2026-08-06)

Earlier Parakeet numbers came from a standalone script. These run through the
shipped `create_asr()` path in
[asr/\_\_init\_\_.py](../src/live_translator/asr/__init__.py) — same code the
app uses — at `cpu_threads=4`, for **both** profile directions. English
samples are the German set's counterparts, synthesized with the project's
`en_US-hfc_male-medium` Piper voice.

| Direction | Engine | Match | Latency min | Latency max | Total inference |
|---|---|---|---|---|---|
| de-en | faster-whisper `base` | 9/15 | 1.087s | 1.317s | 18.16s |
| de-en | **parakeet tdt int8** | **11/15** | **0.277s** | **1.154s** | **11.54s** |
| en-de | **faster-whisper `base`** | **13/15** | 1.106s | 1.206s | 17.43s |
| en-de | parakeet tdt int8 | 12/15 | **0.266s** | **0.939s** | **9.03s** |

**The accuracy result flips by direction.** Parakeet wins German (11 vs 9);
`base` edges out English (13 vs 12). That is consistent with Whisper being
strongest on English — English was never the problem this search set out to
solve. Latency, by contrast, favours Parakeet in *both* directions, by a
wide margin at the short end (0.27s vs 1.09s).

Parakeet's English misses: `in time` → "and time", and `background noise` →
"backgroise" (a genuine word mangling). `base`'s English miss: `postpone` →
"post poem".

**Both engines produce `12%` for "twelve percent"** (sample 11, both
directions). That is numeral normalisation, not a recognition error — it
would translate correctly downstream — so the strict exact-match score
understates both engines by one.

**Implication for configuration:** profiles are already per-direction
([profiles.py](../src/live_translator/profiles.py)), so the two directions
can use different engines. On this evidence the defensible split is Parakeet
for `de-en` (better accuracy *and* ~3x faster on short phrases) and either
engine for `en-de` (Parakeet trades one sample of accuracy for a large
latency win). Real-audio testing should settle `en-de`.

### Caveats for genuinely old machines

- **RAM is where `base` wins**: 489 MB vs 861 MB peak. On a 4 GB laptop
  already running a browser and a video-call client, ~370 MB extra is a real
  cost and the most likely low-end failure mode for Parakeet.
- **Instruction sets untested**: both CTranslate2 and ONNX Runtime lean on
  AVX2 for int8 throughput. This machine has it; a pre-2013 CPU would not,
  and neither engine was tested in that condition. Unknown, not measured.
- Core *count* was simulated by limiting threads. That models core count
  well but does not model a slower per-core machine (older/low-power silicon
  at lower clocks), which would scale both engines down further.