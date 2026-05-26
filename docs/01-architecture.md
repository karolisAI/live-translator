# Architecture

## Target

Replace Azure Speech with a local pipeline that can run as a Windows executable, then evolve into an enterprise installable product. The first quality bar is lower latency than the current 3000 ms cloud path while keeping understandable translated speech.

Target latency for the MVP:

- Good GPU laptop: 900-1500 ms perceived delay.
- Good CPU-only laptop: 1500-2500 ms perceived delay.
- Low-end CPU-only device: may need a smaller model or push-to-talk mode.

## Pipeline

```text
microphone / meeting audio
  -> Windows audio capture
  -> frame ring buffer
  -> VAD
  -> overlapping ASR windows
  -> partial transcript stabilizer
  -> stream2sentence boundary detector
  -> offline machine translation
  -> local TTS
  -> playback queue
  -> headphones or virtual cable
```

For duplex calls, run two isolated copies of the pipeline:

```text
my mic -> translated audio -> meeting microphone virtual cable
meeting speaker virtual cable -> translated audio -> my headphones
```

The two paths must not share audio buffers. They can share model instances only if profiling proves that sharing does not block real-time performance.

## Concrete Components

### Audio Engine

MVP:

- Use `sounddevice`, which wraps PortAudio.
- Capture at 16 kHz mono when possible.
- If the device mix format differs, resample immediately at the edge.
- Use fixed frames, usually 20 ms.
- Keep an internal ring buffer per route.

Production:

- Replace Python audio I/O with C or C++ WASAPI code.
- Keep shared-mode WASAPI for normal desktop compatibility.
- Add exclusive-mode support only after the shared-mode product is stable.
- Avoid a kernel driver in the MVP. A signed virtual audio endpoint is a later enterprise feature.

### VAD

Use VAD before ASR to avoid wasting model time on silence.

MVP choices:

- `silero-vad` for better speech detection.
- `webrtcvad` if installation size and CPU use matter more than accuracy.

Commit audio to ASR after either:

- speech has reached the minimum duration, or
- silence reaches the configured commit threshold.

### ASR

Use `faster-whisper`, backed by CTranslate2.

Initial model path:

- `base` for quickest CPU testing.
- `small` for the first real quality test.
- `medium` only after GPU acceleration is available.

Use short overlapping windows:

- Window: 800-1600 ms.
- Step: 250-500 ms.
- Beam size: 1 for latency.
- Stabilize partial text by comparing the new transcript with previous output and only emitting stable prefixes.

### Sentence Boundary

Use the idea from the existing note:

- `stream2sentence` decides when enough partial text is ready to translate.
- `wtpsplit` optionally cleans finalized chunks, especially for noisy ASR output.

Do not wait for perfect full sentences. The UX should prefer short phrase-level updates over long waits.

### Machine Translation

Whisper alone is not enough for the product because it does not translate arbitrary source and target pairs. Add a dedicated offline MT stage.

MVP options:

- `Argos Translate` for fastest integration and installable offline packages.
- CTranslate2-converted MarianMT or OPUS-MT models for lower-level control.

Enterprise path:

- Standardize on CTranslate2 for ASR and MT if model quality is sufficient.
- Keep model packages versioned, signed, and stored under `%LOCALAPPDATA%` or `%PROGRAMDATA%`.

### TTS

Use local TTS to avoid cloud latency and enterprise privacy issues.

MVP:

- `Piper` because it is fast, local, and easy to package.

Later:

- Evaluate higher-quality voices only after latency is measured.
- Keep TTS streaming support on the roadmap. Full-utterance TTS will add avoidable delay.

### Router

For Windows testing, use VB-CABLE A/B:

- App output to meeting software: render translated audio to the playback endpoint named like `CABLE-A Input`.
- Meeting software microphone: select the recording endpoint named like `CABLE-A Output`.
- Meeting audio into app: set meeting speaker output to playback endpoint named like `CABLE-B Input`.
- App captures peer audio from recording endpoint named like `CABLE-B Output`.

Production enterprise options:

- Ship with a supported third-party virtual cable dependency at first.
- Later build or license a signed virtual audio endpoint driver.
- Treat kernel-mode driver work as a separate product line item because signing, updates, crashes, and enterprise deployment policies are materially different from application code.

## Latency Budget

| Stage | MVP Target |
| --- | ---: |
| Capture frame | 20 ms |
| VAD decision | 80-200 ms |
| ASR window delay | 500-1200 ms |
| ASR inference | 80-600 ms |
| Text boundary decision | 50-250 ms |
| MT inference | 30-250 ms |
| TTS first audio | 150-600 ms |
| Output buffer | 50-100 ms |

The main knobs are ASR model size, ASR window length, sentence boundary aggressiveness, and TTS voice speed. The MVP should expose those as config values instead of hardcoding them.

## Process Model

Start with one Python process and one thread or async task per route:

- route A: my mic to peer
- route B: peer to my ears

Within each route, separate queues should connect capture, ASR, MT, TTS, and playback. Bounded queues are required so overload drops old work rather than increasing latency forever.

When moving toward production, split into:

- `audio-core` native process or library
- `inference-core` native or Python-hosted model runtime
- `app-host` Java or native host for config, UI, updates, and enterprise controls

Keep the queue contracts stable so the implementation language can change without redesigning the whole product.
