# Live Translator

Live Translator is an offline, near-real-time Windows speech translator for
English and German meetings. It uses faster-whisper for speech recognition,
Argos CTranslate2 models for text translation, Piper for speech synthesis, and
VB-CABLE to expose translated speech as a meeting microphone. NVIDIA Parakeet
TDT is available as an optional alternative recognizer; see
[Parakeet ASR](#parakeet-asr-optional).

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

For an installation from `LiveTranslatorSetup.exe`:

- Windows 10 or Windows 11
- A microphone and headset
- [VB-CABLE](https://vb-audio.com/Cable/) or an equivalent virtual cable
- Internet access during the first model preparation

The installer bundles the application, Python runtime, Argos translation
models, Piper runtime, and the English and German voices. Python does not need
to be installed separately on the target computer.

Building from source additionally requires:

- Python 3.11
- [Piper Windows runtime](https://github.com/rhasspy/piper/releases/tag/2023.11.14-2)
- [Piper voices](https://huggingface.co/rhasspy/piper-voices)
- Argos `en_de` and `de_en` packages
- Inno Setup 6 when producing the Windows installer
- `onnx-asr` and `onnxruntime` only when using the optional Parakeet ASR engine

Model binaries, voices, and Piper are intentionally excluded from Git. The
source checkout expects:

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

## Install From the Local Windows Installer

This is the recommended setup for developers, testers, and demo machines that
do not need to modify the Python source.

1. Install VB-CABLE and restart Windows if its driver installer requests it.
2. Obtain the internally provided `LiveTranslatorSetup.exe`. A locally built
   copy is produced at `dist\installer\LiveTranslatorSetup.exe`.
3. Close any running LiveTranslator process, then run the installer. The
   application itself is installed per-user and does not require administrator
   rights. VB-CABLE installation may require them.
4. Leave **Configure LiveTranslator now** selected on the final installer page
   to create the default English-to-German profile with automatic audio-device
   selection.

The installer is currently unsigned. Only continue past a Windows SmartScreen
warning when the file came from the project's trusted internal distribution
channel. The installed executable is located at:

```text
%LOCALAPPDATA%\Programs\LiveTranslator\LiveTranslator.exe
```

The installer does not add the executable to `PATH`. Open PowerShell and use
the installed path for setup and verification:

```powershell
$LT = "$env:LOCALAPPDATA\Programs\LiveTranslator\LiveTranslator.exe"
$Profiles = "$env:LOCALAPPDATA\LiveTranslator\profiles"

& $LT --help
& $LT setup --profile en-de --direction en-de
& $LT setup --profile de-en --direction de-en
```

Both profiles default to automatic device selection. LiveTranslator follows
the Windows default physical microphone and finds a matching VB-CABLE playback
and recording pair without storing fragile device indices.

Prepare the faster-whisper model once while the machine is online, then verify
translation and audio routing:

```powershell
& $LT doctor --config "$Profiles\en-de.yaml" --prepare-models
& $LT doctor --config "$Profiles\de-en.yaml" --prepare-models
& $LT translate-text --source-language en --target-language de --text "Good morning"
& $LT translate-text --source-language de --target-language en --text "Guten Morgen"
& $LT route-test --profile en-de
& $LT route-test --profile de-en
```

In Teams, Zoom, or another meeting application, select the configured
`CABLE Output` endpoint as the microphone and the real headset as the speaker.
Then start the required direction from PowerShell:

```powershell
& $LT meeting --profile en-de
& $LT meeting --profile de-en
```

Run only one direction per LiveTranslator process. The process listens and
translates continuously between phrases; `Ctrl+C` is only used when the whole
meeting session should end.

The Start menu contains **LiveTranslator Setup** and **LiveTranslator Meeting**
shortcuts. Those shortcuts use the `default` profile; use the PowerShell
commands above for the named `en-de` and `de-en` profiles.

To update the application, close it and run the newer installer over the
existing installation. Profiles are stored separately under
`%LOCALAPPDATA%\LiveTranslator\profiles` and remain available after an update
or uninstall. Remove the application through Windows **Installed apps**.

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

## Parakeet ASR (Optional)

`faster-whisper` is the default recognizer. `parakeet` runs NVIDIA Parakeet TDT
0.6B v3 and is faster on short phrases; see `research/benchmarks.md`. It
requires the source checkout, not the Windows installer.

The recognizer is a standalone MIT-licensed package in
[packages/parakeet-live](packages/parakeet-live/) with no dependency on this
application; `live_translator` only adapts it to its own ASR contract. Install
it from the checkout, which pulls `onnx-asr` and `onnxruntime` with it:

```powershell
python -m pip install -e .\packages\parakeet-live
```

Run any command with `--asr-engine parakeet`. Accepted by `meeting`,
`transcribe-once`, `translate-once`, `loopback`, and `record-test`. The engine's
default model comes with it, so `--model` is not needed:

```powershell
$DEEN = "$env:LOCALAPPDATA\LiveTranslator\profiles\de-en.yaml"

live-translator transcribe-once --config $DEEN --asr-engine parakeet --seconds 5
live-translator meeting --profile de-en --asr-engine parakeet
```

The first run downloads the model into the Hugging Face cache and needs
internet access. Later runs are offline.

To make it permanent, edit the `asr` block of the profile at
`%LOCALAPPDATA%\LiveTranslator\profiles\<name>.yaml`:

```yaml
asr:
  engine: parakeet
  model: nemo-parakeet-tdt-0.6b-v3
  compute_type: int8
```

`doctor` takes the engine from the profile and has no `--asr-engine` flag, so
make that edit before preparing the model:

```powershell
live-translator doctor --config $DEEN --prepare-models
```

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

## Build the Windows Installer

Contributors producing a new installer need the source environment and all
local model, voice, and Piper assets listed above. Install Inno Setup 6 and
make sure its `ISCC.exe` compiler is available on `PATH`, then run from the
repository root:

```powershell
.\scripts\build_windows.ps1 -InstallBuildTools
.\scripts\build_inno_installer.ps1

& .\dist\LiveTranslator\LiveTranslator.exe --help
Get-FileHash .\dist\installer\LiveTranslatorSetup.exe -Algorithm SHA256
```

The distributable file is `dist\installer\LiveTranslatorSetup.exe`. It contains
the complete PyInstaller application folder; recipients do not also need the
`dist\LiveTranslator` directory. Update `MyAppVersion` in
`packaging\windows\LiveTranslator.iss` before producing a release build.

The faster-whisper model remains in each Windows user's Hugging Face cache, so
run `doctor --prepare-models` online once on every target machine before relying
on offline operation.

## Verification

```powershell
python -m unittest discover -s tests -v
python -m compileall -q src tests
python -m pip check
```

`packages/parakeet-live` has its own suite, run only when that optional package
is installed:

```powershell
python -m unittest discover -s .\packages\parakeet-live\tests -t .\packages\parakeet-live\tests -v
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
- `research/benchmarks.md`: measured ASR latency, accuracy, and footprint
- `research/stt-replacements.md`: ASR engine alternatives that were evaluated
