# Parakeet ASR Integration — Setup Guide

This is the `parakeet.cpp`-based ASR engine evaluation for `live-translator`,
shared for comparison against the parallel `onnx-asr` track. See
`parakeet-evaluation-team-summary.md` for the full findings, open items, and
where this track's numbers agree/conflict with the onnx-asr numbers — read
that alongside this doc, not instead of it. This README is just "how to get
it running," not "what it means."

## Status before you start

This is an **in-progress evaluation, not a finished candidate.** Two open
items block a real go/no-go call:
- Real meeting-style German audio hasn't been tested yet (current DE
  results use a broadcast-style clip that isn't representative).
- A recurring numeric-transcription error is under investigation, not yet
  explained.

Treat everything here as "useful to compare against your numbers," not
"ready to ship."

## What you're getting

Three things travel separately — this isn't a single-file drop-in:

1. **Code** — `parakeet_engine.py` (the `ParakeetAsr` class), `parakeet_capi.py`
   (the ctypes binding), and the `live-translator` diff (config schema +
   pipeline dispatch changes that add `parakeet` as a valid
   `config.asr.engine` value). Shareable normally via git — both files live
   in `src/live_translator/asr/`.

   **Offline only.** This integration only wires up `transcribe_pcm` /
   `transcribe_pcm_lang` / `transcribe_pcm_batch_json_lang` (one-shot decode
   per VAD-committed phrase, same call shape faster-whisper already uses).
   There is no `ParakeetStream` / `.stream()` streaming API in what's shared
   here — that exists only in a separate standalone prototype, not in this
   `live-translator` integration. If you need parakeet.cpp's cache-aware
   streaming path, that's a distinct, larger piece of work, not something
   you already have.
2. **The compiled `parakeet.cpp` DLL** — a native binary, not something
   that travels through code review sensibly. See "Getting the DLL" below.
3. **Model weights** — GGUF file, converted from
   `nemotron-3.5-asr-streaming-0.6b`. Too large for git. See "Getting the
   model" below.

## ⚠️ Read this before debugging anything

Only the **thread-count control** (`set_num_threads`) calls into an
**undocumented DLL export**. This build has `WINDOWS_EXPORT_ALL_SYMBOLS`
enabled (baked into this parakeet.cpp version's own `CMakeLists.txt`,
unconditionally, whenever `-DPARAKEET_SHARED=ON` is used), which exposes
`pk::set_num_threads` under its mangled MSVC name — that symbol isn't part
of the official `parakeet_capi.h` C-API.

**Correction from an earlier draft of this doc:** the JSON/confidence path
(`transcribe_pcm_json`) is *not* in this category — it calls
`parakeet_capi_transcribe_pcm_batch_json_lang`, a documented, ABI-versioned
(v3+) entry point in `parakeet_capi.h`. It'll work on any correctly built
parakeet.cpp DLL, export flag or not.

What this means in practice:
- If you build `parakeet.cpp` yourself without `WINDOWS_EXPORT_ALL_SYMBOLS`,
  or with a different compiler (different C++ name mangling), only thread
  pinning is affected — the engine still works, it just runs at
  parakeet.cpp's own built-in default of 8 threads regardless of your
  `cpu_threads` config. `parakeet_capi.py` now probes for this at import
  time and prints/raises a `ParakeetCapabilityWarning` naming exactly
  what's missing, rather than degrading silently.
- **Use the vendored DLL in `tools/parakeet/` rather than building your
  own** — see "Getting the DLL" below. This isn't just about the export
  flag; it's the exact binary every number in this doc was measured
  against.
- If something works for me and not for you (or vice versa), check the
  startup warning first before assuming it's a code bug.

## Prerequisites

- Windows (this has only been tested on Windows; `parakeet_capi.py`
  currently hard-fails on `sys.platform != "win32"`. The DLL-export
  fragility above is specifically about `set_num_threads` — the
  `.dll`/`GetProcAddress`+mangled-name mechanism is Windows-specific, so a
  Linux/macOS port would need its own approach for thread control
  specifically. JSON/confidence output needs no special handling on any
  platform — it's the documented C-API.)
- Python environment matching `live-translator`'s existing venv
  requirements (no new Python dependencies were added for this track —
  deliberately avoided adding `psutil` etc., using `ctypes` + Windows API
  directly instead, consistent with how this project already talks to
  native code)
- CMake + a C++ toolchain capable of building `parakeet.cpp`, if building
  the DLL from source rather than receiving a prebuilt one

## Getting the DLL

Four files: `parakeet.dll`, `ggml.dll`, `ggml-base.dll`, `ggml-cpu.dll`. They go
in `src/live_translator/asr`'s sibling runtime folder, `tools/parakeet/` (same
convention as `tools/piper/` — gitignored, not distributed via git).

**Use the vendored copy, don't rebuild.** `tools/parakeet/BUILD.md` has the
exact `parakeet.cpp` commit (`1bfbebfaaf493866f49597cd3b7901959d395c60`), the
exact CMake commands used, and SHA256 checksums for all four files — verify
against those after copying. That doc also explains exactly what breaks (and
what doesn't) if you build your own instead.

Same shared Drive folder as the GGUF files below — all four DLLs plus
`BUILD.md` are there:
https://drive.proton.me/urls/RJCBWEKXQC#2BPzT9pqh6Et

Verify checksums against `tools/parakeet/BUILD.md` (the copy in this repo,
not the one on Drive — same content, but the repo copy is the one that
travels with version control) after copying. That table is the integrity
check, not the download source.

## Getting the model

The model is `nemotron-3.5-asr-streaming-0.6b`, converted to GGUF. Two
precision levels have been tested:

| Variant | Disk size | Model-load memory | English WER (25 real segments, this repo's own test) |
|---|---|---|---|
| f16 | ~1.4GB | +1420MB | 14.1% (10.4% vs. a beam=5 whisper reference) |
| q8_0 | ~940MB | +941MB | 15.1% |

**Run q8_0, not f16.** The table above (this repo's original 25-segment test)
found f16 slightly more accurate, and that's what shipped as the
recommendation initially — but it's now superseded. Edvinas independently
re-tested both variants against `parakeet-live` using a more rigorous
shared-VAD-segment, shared-scorer harness, confirmed **twice, on two
languages**: q8_0 is *both* more accurate and faster in each case —
English 3.99% (q8_0) vs. 4.09% (f16) WER, and q8_0 is 23% faster (RTF 0.192
vs. 0.250) and uses 500MB less RAM either way. Two independent
confirmations across languages outweighs this repo's single English-only
test, so q8_0 is the recommendation now — the original table above is kept
for its own record, not as the current guidance. See Edvinas's
`parakeet-engine-comparison-de.md` §6 and `parakeet-engine-comparison-en.md`
§9.5 for the full comparison — as of this note these aren't confirmed
committed anywhere in this repo, so ask Edvinas directly if you need the
source documents.

Neither variant has been tested on real meeting-style German audio yet
(only DW broadcast news) — see Status above.

Regenerating either variant (rather than copying the GGUF as a binary blob):

```bash
# f16 (what most testing in this doc used)
python scripts/convert_parakeet_to_gguf.py --model nvidia/nemotron-3.5-asr-streaming-0.6b \
    --dtype f16 --output nemotron-3.5-asr-streaming-0.6b-f16.gguf

# q8_0 -- NOTE: parakeet-cli's quantize step silently no-ops (0 tensors
# quantized, file unchanged) if you feed it an f16 source. It requires an
# F32 source:
python scripts/convert_parakeet_to_gguf.py --model nvidia/nemotron-3.5-asr-streaming-0.6b \
    --output nemotron-3.5-asr-streaming-0.6b-f32.gguf   # no --dtype = f32, ~2.4GB
```

Then run `parakeet-cli.exe quantize <f32.gguf> <out-q8_0.gguf> q8_0` — see
`tools/parakeet/BUILD.md`'s "Gotcha 2" for the exact PowerShell invocation.
The bare command above will fail with `STATUS_DLL_NOT_FOUND` unless the
ggml DLLs' directory is on PATH first; that doc has the working sequence,
not duplicated here to avoid the two copies drifting out of sync.

The conversion script lives in the `parakeet.cpp` checkout (`scripts/convert_parakeet_to_gguf.py`),
not in `live-translator` — needs its own one-time Python env (`torch` CPU +
`nemo_toolkit[asr]` + `gguf`, see that repo's README). The source checkpoint
downloads from `nvidia/nemotron-3.5-asr-streaming-0.6b` on Hugging Face
automatically; nothing to fetch by hand.

Converted GGUF files go in `models/parakeet/` (gitignored, same convention
as `models/argos/` and `models/tts/`).

Both variants (f16 and q8_0) are on the same shared Drive folder as the
DLLs above:
https://drive.proton.me/urls/RJCBWEKXQC#2BPzT9pqh6Et

## Installing into live-translator

1. Place `parakeet_engine.py` and `parakeet_capi.py` in `src/live_translator/asr/`.
2. Apply the `live-translator` diff — adds `parakeet` as a valid
   `config.asr.engine` value and wires `ParakeetAsr` into the same
   dispatch `FasterWhisperAsr` uses (`transcribe(audio, sample_rate) ->
   TranscriptResult`).
3. Place the DLL bundle at `tools/parakeet/` and the GGUF model at
   `models/parakeet/` (both relative to the repo root — see "Getting the
   DLL" / "Getting the model" above). **Neither is a config field** — the
   DLL location is a fixed convention resolved via `resolve_runtime_path()`
   at import time (same mechanism Piper's exe/voice paths already use), so
   there's nothing to set for it. The model path *is* configurable: reuse
   the existing `asr.model` field (the same one faster-whisper uses for its
   model name) and point it at your GGUF file's path, e.g.
   `asr.model: models/parakeet/nemotron-3.5-asr-streaming-0.6b-q8_0.gguf`
   (q8_0, not f16 — see "Getting the model" above for why).
4. Set `config.asr.engine: parakeet` in your profile config to opt in —
   default remains `faster-whisper`, unchanged.

## Language coverage — EN vs. DE readiness

The model and code support both directions — `nemotron-3.5-asr-streaming-0.6b`
covers EN+DE in a single checkpoint (no separate download or model swap
needed), and `target_lang` is wired from `ParakeetAsr.transcribe()` (via
`asr.source_language` in config) through `ParakeetModel.transcribe_pcm()`
down to the `_lang` C-API variants nemotron needs for language selection.
`test_parakeet_asr.py` covers this wiring.

**But the evidence backing each direction is not at the same level of
rigor — don't treat DE as equally proven:**

| | EN | DE |
|---|---|---|
| WER measured | 14.1% (10.4% vs. beam=5 reference) | 11.3% whole-clip / 17.1% VAD-segmented |
| Ear-verified against real audio | Yes — all 6 flagged disagreements checked | No |
| Test audio | Real recorded meeting (25 segments) | Non-representative broadcast clip |
| Real meeting-style audio tested | Yes | **Not yet — in progress** |
| Confidence/rejection gate tested | Yes | No |
| Numeric-transcription accuracy | Not specifically checked | Recurring error flagged, under investigation |

Bottom line: colleagues can select German today (`target_lang: de`, config
support is real and tested at the wiring level), but the DE accuracy
numbers above should be treated as preliminary — weaker evidence than the
EN side, not yet validated on the audio style (real meetings, natural
pacing) that matters for production. Flag this explicitly if anyone runs
their own DE testing against this build, so a bad result doesn't get
mistaken for a settled finding, and a good result doesn't get treated as
more validated than it is.

## Verifying it works

```
pytest tests/test_parakeet_asr.py tests/test_config.py tests/test_pipeline.py
```

Full suite is 75 tests (was 63 before this integration), all passing, no
regressions to the existing faster-whisper path. `test_parakeet_asr.py`
specifically covers: engine validation, thread pinning, `target_lang`
wiring, and both rejection paths (silence/empty-output behavior and the
compression-ratio garbage-rejection gate).

## Known behavior differences from faster-whisper worth knowing upfront

- **Thread count:** defaults to 8 regardless of available cores — this is
  `parakeet.cpp`'s own hardcoded default (confirmed via source, not just
  observed), not something this binding imposes.
- **Capability warning at import time:** `parakeet_capi.py` now probes for
  the undocumented thread-pinning export when the DLL first loads. If it's
  missing (wrong build, different compiler), you'll get a loud
  `ParakeetCapabilityWarning` naming exactly what's unavailable and why —
  not a crash, not silence. Thread pinning degrades to parakeet.cpp's own
  default (8) either way; everything else is unaffected.
- **Silence/noise handling:** returns empty string on silence, white
  noise, pure tones, clipped distortion, and repetitive clicks — no
  whisper-style silence hallucination, so nothing extra was needed for
  that failure mode.
- **No per-word confidence rejection.** Investigated (the
  `transcribe_pcm_json` binding exists) but not shipped — tested across
  25 real segments and found disputed vs. clean segment confidence scores
  overlap too much to threshold reliably. If you need this, the binding
  infrastructure is there, but the actual gating logic still needs real
  calibration data, not a guess.
- **Language switching on short utterances:** not yet tested on this
  track — this is the "Ja"→"Yeah" issue found on the onnx-asr track;
  unknown whether nemotron shares it.

## Licensing

CC-BY-4.0 attribution required for the NVIDIA model before this ships in
any form — applies here same as on the onnx-asr track, since both use
NVIDIA NeMo-family weights.
