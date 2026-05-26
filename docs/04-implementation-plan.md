# Implementation Plan

## Phase 0: Cleanup And Criteria

Deliverables:

- Rotate the Azure Speech key found in the old `application.yaml`.
- Freeze success criteria for the local MVP.
- Decide the first language pair, likely English to German and German to English.

Acceptance checks:

- Old cloud POC still runs for comparison.
- Local solution has a latency target and quality target.
- No credentials are present in the new repository.

## Phase 1: Local Loopback Prototype

Build:

- Python package skeleton.
- Device listing.
- Microphone capture.
- Local ASR with `faster-whisper`.
- Simple console partial transcript output.
- Local TTS playback to headphones.

First mode:

```text
physical microphone -> ASR -> source-language TTS or placeholder beep/audio
```

Then add MT:

```text
physical microphone -> ASR -> MT -> TTS -> headphones
```

Acceptance checks:

- Runs without Azure or internet after models are installed.
- Captures from selected microphone.
- Plays translated audio to selected output.
- Logs stage timings for every segment.

## Phase 2: Low-Latency Text Segmentation

Build:

- VAD-based chunking.
- Overlapping ASR windows.
- Transcript stabilizer.
- `stream2sentence` integration.
- Optional `wtpsplit` cleanup for finalized chunks.

Acceptance checks:

- Does not wait for long complete paragraphs.
- Can emit phrase-level translated speech.
- Drops stale partial work instead of growing delay.
- Reports p50, p90, and p95 latency per stage.

## Phase 3: Windows Virtual Cable Mode

Build:

- One-way translate mode to `CABLE-A Input`.
- Duplex mode with `CABLE-A` and `CABLE-B`.
- Friendly device matching and clear error messages.
- Config file support matching `app.example.yaml`.

Acceptance checks:

- Meeting app can select translated audio as microphone.
- Peer audio can be captured separately from translated output.
- Headphones prevent feedback.
- App recovers cleanly when a device is missing or busy.

## Phase 4: Executable Packaging

Build:

- `live-translator.exe`.
- `download-models` command.
- Internal Windows installer.
- Model checksum verification.
- Local logs under `%LOCALAPPDATA%/LiveTranslator/logs`.

Acceptance checks:

- Installs on a clean Windows machine.
- Runs without Python installed.
- Runs without Azure credentials.
- Can uninstall cleanly.

## Phase 5: Native Core

Build only after the Python MVP proves the pipeline:

- Native WASAPI capture/playback core.
- Direct CTranslate2 ASR/MT integration.
- Native TTS runtime or a separate local TTS worker process.
- Stable IPC boundary to Java or desktop host if needed.

Acceptance checks:

- Lower CPU use than the Python MVP.
- More stable audio timing under load.
- Same config and route behavior as the Python MVP.

## Phase 6: Enterprise Product

Build:

- Signed binaries.
- MSI installer.
- Admin-install mode.
- Centralized policy/config support.
- Optional telemetry that never records raw audio by default.
- Signed virtual audio endpoint or licensed virtual cable dependency.

Acceptance checks:

- Installs without developer tools.
- Supports model updates.
- Provides privacy guarantees suitable for enterprise review.
- Has a documented deployment and rollback process.
