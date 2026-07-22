# Stakeholder Overview

## Purpose

Live Translator provides local English-to-German or German-to-English speech
translation for Windows meetings. It converts a physical microphone into a
translated virtual microphone that can be selected in Teams, Zoom, Meet, or a
similar meeting application.

The current release is designed for near-real-time phrase translation. The
speaker talks naturally and pauses briefly at phrase boundaries. No key press or
manual stop is required between phrases.

## Implemented Flow

```text
Physical Microphone
  -> Continuous sounddevice InputStream
  -> Adaptive phrase detection
  -> Bounded recognition queue
  -> faster-whisper speech recognition
  -> Argos English/German translation
  -> Bounded playback queue
  -> Piper target-language speech
  -> VB-CABLE virtual microphone
  -> Meeting application
```

Capture, recognition/translation, and playback are independent ordered stages.
The microphone therefore continues listening while an earlier phrase is being
recognized or played. Complete phrases are queued with explicit limits so the
application cannot accumulate unbounded delay. If a limit is reached, the
oldest pending phrase is skipped and the operator sees a warning.

## Technology Map

| Responsibility | Implemented technology |
| --- | --- |
| Microphone capture and playback | sounddevice / PortAudio |
| Audio representation | NumPy with PyAV/libswresample, 16 kHz mono inference path |
| Phrase detection | Adaptive RMS/peak VAD with pre-roll and trailing silence |
| Speech recognition | faster-whisper on CTranslate2 |
| Text translation | Argos CTranslate2 models with SentencePiece |
| Speech synthesis | Piper CLI with local ONNX voices |
| Meeting routing | VB-CABLE virtual playback and recording endpoints |
| Configuration | Validated YAML direction profiles |
| Windows packaging | PyInstaller; optional Inno Setup wrapper |

## Local Operation

After dependencies and models are installed, the speech recognition,
translation, and synthesis path runs locally. It does not require a cloud API
key. Named faster-whisper models are loaded from the Windows user's local
Hugging Face cache.

Two profiles are generated because direction and output voice are explicit:

- `en-de`: English recognition, German translation, German Piper voice
- `de-en`: German recognition, English translation, English Piper voice

## Performance Profile

The current demo machine is an AMD Ryzen 5 7535HS with 12 logical processors
and no CUDA device. Generated profiles use the faster-whisper `base` model on
CPU with `int8` compute and eight inference threads. On clean synthetic
benchmark speech, this mode was
faster than `auto` compute while retaining the more accurate German transcript.
The `tiny` model was faster but produced a German word error, so it is not the
demo default.

Perceived latency is reduced with a 450 ms trailing-silence commit, a 0.8-second
minimum phrase window, a 5-second maximum phrase, and separate recognition and
playback workers. These are machine-tested demo defaults, not universal latency
or accuracy guarantees.

The 450 ms value is a trailing acoustic-silence threshold, not a one-second
timer or an end-word detector. Audio is evaluated in 30 ms frames. The current
release sends a completed phrase to faster-whisper after that boundary (or at
the 5-second ceiling), while the microphone immediately continues collecting
the next phrase.

## Operational Checks

- `doctor --prepare-models` validates dependencies, configured endpoints,
  translation assets, Piper assets, and Whisper model loading.
- `route-test` sends a known 880 Hz tone and verifies that the paired virtual
  microphone receives that specific signal.
- Low-energy audio and low-confidence Whisper segments are rejected before
  speech synthesis.
- Direction profiles and role-based automatic device selectors are stored
  outside the repository under the current Windows user's local application
  data.

## Current Boundary

- Phrase-level near-real-time output, not stabilized word-by-word captions
- One configured language direction per running process
- No capture or translation of remote meeting audio in this release
- No simultaneous duplex interpretation
- Whole-phrase Piper synthesis, not streaming TTS
- A headset is required to avoid acoustic feedback into the physical microphone

The architecture is structured for future input sources or bidirectional
orchestration, but those capabilities are not part of the current demonstrated
release.

The preferred latency roadmap is stabilized incremental recognition and
clause-level simultaneous translation. Translating isolated words is not a
product target because English/German word order makes early word translations
unstable and word-at-a-time speech output would be fragmented.
