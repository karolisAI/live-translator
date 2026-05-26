# Meeting Test Checklist

## Goal

The meeting app must hear only translated speech.

```text
physical mic -> live-translator -> Piper voice -> virtual playback endpoint
virtual recording endpoint -> meeting microphone
meeting speaker -> real headphones
```

Do not select the physical microphone in the meeting app. If the meeting app uses
`Microphone Array (AMD Audio Device)`, the other party will hear the original
English before the translated German.

## Current Senary Test Shape

The reusable path is to generate a local profile:

```powershell
live-translator setup --direction en-de
```

That writes `%LOCALAPPDATA%\LiveTranslator\profiles\default.yaml` with device
names from the current machine. The checked-in `app.meeting-en-de.yaml` is only a
known-good example from this development machine.

The current local example config is `app.meeting-en-de.yaml`:

- translator input: `9`, currently the AMD microphone array
- translator output: `Output 2 (Senary Audio output)`
- meeting microphone: the recording endpoint paired with that output, for example `Input (Senary Audio output)`
- meeting speaker: `Speakers (Senary Audio)` or another real headphone output

If Google Meet only lists `Microphone Array (AMD Audio Device)` and does not list
the Senary recording endpoint, the browser cannot receive translated audio as a
microphone. Use VB-CABLE or another virtual cable that exposes a recording
endpoint to Windows and the browser.

## Piper Voice Setup

Install Piper into `tools/piper` so this file exists:

```text
tools/piper/piper.exe
```

Download a German Piper voice and its matching JSON config:

```powershell
New-Item -ItemType Directory -Force models\tts
Invoke-WebRequest -Uri "https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/medium/de_DE-thorsten-medium.onnx" -OutFile "models\tts\de_DE-thorsten-medium.onnx"
Invoke-WebRequest -Uri "https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/medium/de_DE-thorsten-medium.onnx.json" -OutFile "models\tts\de_DE-thorsten-medium.onnx.json"
```

The `.onnx` and `.onnx.json` files must sit next to each other.

## Test Commands

Check the devices:

```powershell
live-translator doctor --config app.meeting-en-de.yaml
live-translator list-input-devices
live-translator list-output-devices
live-translator probe-output-devices
live-translator route-test --config app.meeting-en-de.yaml
```

Test Piper routing without the microphone:

```powershell
live-translator say --config app.meeting-en-de.yaml --text "Dies ist ein Test."
```

Then test one translated chunk:

```powershell
live-translator translate-once --config app.meeting-en-de.yaml --seconds 5
```

For a call test:

```powershell
live-translator loopback --config app.meeting-en-de.yaml
```

Stop with `Ctrl+C`.
