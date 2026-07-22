# Live Translator

Live Translator is an offline, near-real-time Windows speech translator for
English and German meetings. It uses faster-whisper for speech recognition,
Argos CTranslate2 models for text translation, Piper for speech synthesis, and
VB-CABLE to expose translated speech as a meeting microphone.

No API key is required after the local models are prepared.

## Runtime Behavior

- English to German and German to English use separate profiles.
- The microphone remains open while earlier phrases are recognized, translated,
  synthesized, and played.
- Recognition/translation and playback run on separate ordered workers.
- Voice activity detection commits a phrase after a short pause.
- ASR and translation models load, and Piper assets are validated, before the
  application reports `Ready`.
- Low-energy noise and low-confidence Whisper output are not spoken.
- Bounded phrase queues prevent unlimited latency and report any overload.
- Transient Windows output-start failures are retried on the verified WASAPI
  endpoint. A phrase that still cannot play is reported without closing the
  microphone or ending the meeting session.

This is phrase-level, one-direction translation per process. It is not
simultaneous duplex interpretation or stabilized word-by-word captioning.

```text
physical microphone -> continuous VAD capture -> faster-whisper -> Argos
                                                        |
meeting microphone <- CABLE Output <- CABLE Input <- Piper playback worker
```

Use a headset during a meeting. Speaker bleed into the physical microphone can
cause the translator to hear its own synthesized output.

## Requirements

- Windows 10 or Windows 11
- Python 3.11
- A microphone and headset
- [VB-CABLE](https://vb-audio.com/Cable/) or an equivalent virtual cable
- [Piper Windows runtime](https://github.com/rhasspy/piper/releases/tag/2023.11.14-2)
- [Piper voices](https://huggingface.co/rhasspy/piper-voices)
- Argos `en_de` and `de_en` packages
- Internet access for initial installation and the first Whisper model load

Model binaries, voices, and Piper are intentionally excluded from Git. The
runtime expects:

```text
models/argos/packages/en_de/model/model.bin
models/argos/packages/en_de/sentencepiece.model
models/argos/packages/de_en/model/model.bin
models/argos/packages/de_en/sentencepiece.model
models/tts/de_DE-thorsten-medium.onnx
models/tts/de_DE-thorsten-medium.onnx.json
models/tts/en_US-hfc_male-medium.onnx
models/tts/en_US-hfc_male-medium.onnx.json
tools/piper/piper.exe
tools/piper/piper_phonemize.dll
tools/piper/onnxruntime.dll
tools/piper/espeak-ng-data/
```

## Source Setup

A `vscode-vfs://github/...` VS Code window is a virtual repository view, not a
runnable checkout. Open PowerShell in a local clone first:

```powershell
Set-Location C:\path\to\live-translator
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

To download Argos models on a clean machine, install the optional package
manager and direct it to the repository-local build assets:

```powershell
python -m pip install -e ".[translate]"
New-Item -ItemType Directory -Force .\models\argos\packages | Out-Null
$env:ARGOS_PACKAGES_DIR = (Resolve-Path .\models\argos\packages).Path
live-translator argos-install --source-language en --target-language de
live-translator argos-install --source-language de --target-language en
```

Download and extract the complete `piper_windows_amd64.zip` release into
`tools\piper`. Download both `.onnx` voice files and their matching `.onnx.json`
files into `models\tts`:

- [German Thorsten medium](https://huggingface.co/rhasspy/piper-voices/tree/main/de/de_DE/thorsten/medium)
- [English hfc_male medium](https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/hfc_male/medium)

## Profiles

List devices and note the Windows host API. WASAPI endpoints are recommended:

```powershell
live-translator list-input-devices
live-translator list-output-devices
```

Create one profile per direction:

```powershell
live-translator setup --profile en-de --direction en-de
live-translator setup --profile de-en --direction de-en
```

Generated profiles use `auto` for all three audio roles. At runtime the
translator follows the Windows default physical microphone, prefers its WASAPI
endpoint, and selects a complete standard CABLE-A playback/recording pair.
Current PortAudio indices are never stored in an automatic profile.

Profiles are stored under `%LOCALAPPDATA%\LiveTranslator\profiles`. Run setup
with `--interactive-devices` or an explicit `--input-device` only when the
Windows default microphone is not the microphone you want. Full friendly-name
overrides remain stable when Windows reorders device indices.

`app.example.yaml` documents supported settings. It is a template, not a
machine-ready meeting profile.

## Preflight

Run before a demonstration or meeting:

```powershell
$ENDE = "$env:LOCALAPPDATA\LiveTranslator\profiles\en-de.yaml"
$DEEN = "$env:LOCALAPPDATA\LiveTranslator\profiles\de-en.yaml"

live-translator doctor --config $ENDE --prepare-models
live-translator doctor --config $DEEN --prepare-models
live-translator route-test --profile en-de
live-translator route-test --profile de-en
live-translator translate-text --source-language en --target-language de --text "Good morning"
live-translator translate-text --source-language de --target-language en --text "Guten Morgen"
live-translator transcribe-once --config $ENDE --seconds 5
```

`route-test` sends an 880 Hz reference tone through the virtual cable and checks
for that specific tone on the matching recording endpoint.

## Meeting Use

In the meeting application select:

- Microphone: the configured `CABLE Output`
- Speaker: the real headset, never the virtual cable
- Automatic microphone switching: off

Start a direction:

```powershell
live-translator meeting --profile en-de
live-translator meeting --profile de-en
```

In the default VAD meeting mode, capture remains active for the full session and
no input is required between phrases. `Ctrl+C` only ends the running meeting
process; it does not trigger translation. Fixed-window diagnostic mode reopens
capture for each block.

Normal mode prints only accepted source text and its translation. Diagnostic
mode adds audio gates, queue delay, timing, and saved input chunks:

```powershell
live-translator meeting --profile en-de --verbose --debug-audio-dir debug-asr
```

## Windows Build

The local model and Piper assets above must exist before building:

```powershell
.\scripts\build_windows.ps1 -InstallBuildTools
.\dist\LiveTranslator\LiveTranslator.exe --help
.\scripts\install_windows_user.ps1
```

The installed application is written to
`%LOCALAPPDATA%\Programs\LiveTranslator`. The faster-whisper model remains in
the Windows user's Hugging Face cache; run `doctor --prepare-models` online once
on each target machine before relying on offline operation.

## Verification

```powershell
python -m unittest discover -s tests -v
python -m compileall -q src tests
python -m pip check
```

The automated suite covers configuration, audio analysis, resampling,
continuous segmentation, concurrent recognition/playback, overload behavior,
worker failure propagation, and virtual-route tone detection. Hardware and
model checks are performed with `doctor`, `route-test`, `say`, and the one-shot
commands.

Additional references:

- `docs/01-architecture.md`: implemented concurrency and limits
- `docs/02-stakeholder-overview.md`: high-level current-state briefing
- `docs/03-windows-audio-routing.md`: Windows endpoint routing
- `docs/04-meeting-test.md`: meeting validation checklist
- `docs/05-windows-packaging.md`: executable build and installation
