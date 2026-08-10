# parakeet-live

NVIDIA Parakeet TDT speech recognition through
[onnx-asr](https://github.com/istupakov/onnx-asr) on onnxruntime — no PyTorch,
no NeMo — plus the confidence filtering a live pipeline needs in order to drop
doubtful output instead of speaking it.

A transducer processes only the audio it is given, instead of padding every
input to Whisper's fixed 30-second window, so latency scales with utterance
length rather than sitting on a constant floor. On short meeting phrases that
measured roughly 3x faster than faster-whisper's `base` at comparable accuracy.

**Scope:** this recognizes one complete utterance per call. It is not a
streaming recognizer and does not segment audio — voice activity detection and
phrase cutting stay with the caller.

## Install

```
pip install parakeet-live
```

`onnx-asr` and `onnxruntime` come with it. The model itself is downloaded into
the Hugging Face cache on first use and needs internet access once; every run
after that is offline.

## Use

```python
import numpy as np
from parakeet_live import ParakeetRecognizer

recognizer = ParakeetRecognizer(language="de")
transcript = recognizer.transcribe(np.zeros(16000, dtype=np.float32), 16000)

if transcript.rejected:
    print("dropped:", transcript.rejection_reason)
else:
    print(transcript.text, transcript.inference_seconds)
```

`transcribe()` takes a mono float32 array and its sample rate, and returns a
`Transcript` with `text`, `language`, `duration_seconds`, `inference_seconds`,
`rejected`, and `rejection_reason`.

Rejection reasons are `no_speech`, `short`, `avg_logprob=<value>`, and
`compression_ratio=<value>`.

### Switching language per call

Loading the model is the expensive part, so a bidirectional pipeline should
keep one recognizer and pass the language per call rather than hold one
session per language:

```python
recognizer = ParakeetRecognizer()

de = recognizer.transcribe(audio, 16000, language="de")
en = recognizer.transcribe(audio, 16000, language="en")
```

Omitting the argument uses the language given to the constructor. Leaving both
unset lets the model detect the language itself.

## Options

| Argument | Default | Notes |
|---|---|---|
| `model` | `nemo-parakeet-tdt-0.6b-v3` | Any onnx-asr Parakeet model name. Whisper sizes raise `UnsupportedModel`. |
| `quantization` | `int8` | ONNX file suffix. `None`, `auto`, `float32`, `fp32`, `float`, `none` all mean full precision. |
| `device` | `cpu` | `cuda` selects onnxruntime's CUDA provider and needs a GPU build. |
| `cpu_threads` | `0` | `0` leaves onnxruntime's own default alone. |
| `language` | `None` | Default for `transcribe()`; omitted from the call entirely when unset. |
| `min_chars` | `2` | Shorter output is rejected as `short`. |
| `log_prob_threshold` | `-1.3` | See the scale warning below. |
| `compression_ratio_threshold` | `2.4` | Catches degenerate repetition. |

`int8` is the recommended quantization: measured against `fp32` it gave
identical accuracy, lower latency, and a 3.7x smaller model on disk.

## Two things worth knowing

**The logprob scale is not Whisper's.** Measured on this model, clean speech
averages about -0.005 and badly degraded speech about -0.44. The -1.3 default
is inherited from faster-whisper, whose range is much wider, so it is
effectively permissive here. Retune against your own audio before tightening
it.

**Gate on input energy before calling `transcribe()`.** On digital silence the
model occasionally hallucinates a short phrase ("Thank you.", "Yeah.") with
confidence (-0.19 to -0.65) that overlaps genuine short speech ("Ja, genau."
measured -0.39). No threshold separates the two, so this package does not
pretend to — keep silence from reaching it in the first place.

## Licenses

This package is MIT licensed. It does not redistribute any model.

The models it loads carry their own terms: NVIDIA's Parakeet TDT weights are
released under [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/), which
permits commercial use but requires attribution.
