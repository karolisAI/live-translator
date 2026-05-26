# Package Layout

## Repository Shape

```text
live-translator/
  pyproject.toml
  README.md
  app.example.yaml
  src/
    live_translator/
      __init__.py
      cli.py
      config.py
      logging_config.py
      pipeline.py
      routes.py
      audio/
        devices.py
        capture.py
        playback.py
        resample.py
        ring_buffer.py
      vad/
        base.py
        silero.py
        webrtc.py
      asr/
        faster_whisper_engine.py
        stabilizer.py
      segmentation/
        sentence_stream.py
        wtpsplit_cleanup.py
      mt/
        argos_engine.py
        ctranslate2_engine.py
      tts/
        piper_engine.py
        playback_queue.py
      packaging/
        model_registry.py
        healthcheck.py
  scripts/
    download_models.ps1
    benchmark_latency.ps1
    package_windows.ps1
  installer/
    wix/
    nsis/
  tests/
    unit/
    integration/
```

## Command Line

The package should expose one command: `live-translator`.

Required commands:

```powershell
live-translator list-input-devices
live-translator list-output-devices
live-translator loopback --config app.yaml
live-translator translate --config app.yaml
live-translator duplex --config app.yaml
live-translator benchmark-latency --config app.yaml --seconds 60
live-translator download-models --config app.yaml
```

`loopback` should be the first working mode because it avoids meeting software complexity:

```text
my microphone -> local ASR -> local MT -> local TTS -> my headphones
```

`translate` should be the one-way meeting mode:

```text
my microphone -> translated audio -> virtual cable -> meeting microphone
```

`duplex` should be the later call mode:

```text
my microphone -> translated audio -> peer
peer audio -> translated audio -> my headphones
```

## Internal Interfaces

Keep module interfaces small and replaceable.

```python
class AudioCapture:
    def frames(self) -> Iterable[AudioFrame]: ...

class VadEngine:
    def accept(self, frame: AudioFrame) -> VadDecision: ...

class AsrEngine:
    def transcribe(self, audio: AudioChunk) -> TranscriptUpdate: ...

class Segmenter:
    def accept(self, text: str) -> list[TextSegment]: ...

class TranslationEngine:
    def translate(self, text: str, source: str, target: str) -> str: ...

class TtsEngine:
    def synthesize(self, text: str, voice: str) -> AudioChunk: ...

class AudioPlayback:
    def play(self, audio: AudioChunk) -> None: ...
```

Avoid passing raw dictionaries between stages. Use typed dataclasses for:

- `AudioFrame`
- `AudioChunk`
- `TranscriptUpdate`
- `TextSegment`
- `TranslatedSegment`
- `RouteMetrics`

## Queue Rules

Each stage should communicate through bounded queues.

Rules:

- Audio capture queue may drop old silence.
- ASR queue may replace an older unprocessed chunk with a newer one.
- MT queue should not translate stale partial text.
- TTS queue should cancel stale audio if a newer finalized segment supersedes it.
- Playback queue should prefer continuity, but it must never grow without bound.

The product should fail by dropping stale work, not by accumulating delay.

## Model Packaging

Initial executable strategy:

- Build a PyInstaller or Nuitka executable.
- Do not bundle large models in the first internal build.
- Add `download-models` to install models into `%LOCALAPPDATA%/LiveTranslator/models`.
- For enterprise installs, move shared models to `%PROGRAMDATA%/LiveTranslator/models`.

Model registry should record:

- model name
- language pair
- version
- local path
- sha256 checksum
- license text
- minimum recommended hardware

## Windows Installer

Use this progression:

1. Zip or PyInstaller folder build for internal testing.
2. NSIS installer for quick user testing.
3. WiX/MSI for enterprise deployment.
4. Signed installer and signed binaries.
5. Optional signed virtual audio driver or licensed cable dependency.

The installer must not require an Azure key or any cloud account.
