# Local Live Translator Solution

This folder describes a concrete replacement for the current Azure-based live microphone translator.

The current C# POC proves the audio-routing shape: capture microphone or meeting audio, translate it, synthesize translated speech, and send the result into a virtual cable or headphones. The bottleneck is Azure Speech batching and network dependence, which creates roughly 3000 ms latency even on a good connection.

The new solution should be local-first:

1. Capture audio locally from Windows devices.
2. Run speech recognition locally with `faster-whisper`.
3. Segment partial text with `stream2sentence`, with optional `wtpsplit` cleanup.
4. Translate text locally with an offline MT model.
5. Synthesize local speech with a fast TTS engine.
6. Route translated audio to VB-CABLE for the MVP, then replace that with a signed virtual audio endpoint for enterprise.

## Runnable POC

This folder now contains a Python proof of concept under `src/live_translator`.

Install it in editable mode:

```powershell
cd C:\Users\karol\Desktop\live-translator-local-solution
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e .
```

Optional extras:

```powershell
python -m pip install -e ".[tts]"
python -m pip install -e ".[translate]"
python -m pip install -e ".[all]"
```

Check dependencies:

```powershell
live-translator doctor
```

Create a machine-local meeting profile:

```powershell
live-translator setup --direction en-de
live-translator route-test
live-translator meeting
```

The setup command writes `%LOCALAPPDATA%\LiveTranslator\profiles\default.yaml`.
It records the exact devices selected on that Windows machine, so the shipped
POC does not depend on Senary, VB-CABLE, or any other hardcoded device names.

List audio devices:

```powershell
live-translator list-input-devices
live-translator list-output-devices
```

For meeting tests, the meeting app must use a virtual recording endpoint as its
microphone. It must not use the physical microphone, otherwise the other party
will hear the original speech and then the translation. See
`docs/06-meeting-test.md` for the current Senary/VB-CABLE checklist.

First useful test, transcription only:

```powershell
live-translator transcribe-once --config app.quickstart.yaml --seconds 4
```

Then test the pipeline without translation or speech output:

```powershell
live-translator translate-once --config app.quickstart.yaml --seconds 4 --translation-engine identity --tts-engine none
```

To hear output through default Windows speech, use:

```powershell
live-translator translate-once --config app.quickstart.yaml --seconds 4 --translation-engine identity --tts-engine pyttsx3
```

`pyttsx3` is useful only as a quick smoke test. It uses the Windows default
output device, so it is easy to misroute in a meeting. Use Piper for real
meeting tests because it produces audio that the app can play to the configured
output device.

To test speech output without recording:

```powershell
live-translator say --config app.quickstart.yaml --tts-engine pyttsx3 --text "local translator test"
```

For real English to German offline translation, install an Argos language package, then run:

```powershell
live-translator argos-install --source-language en --target-language de
live-translator translate-text --source-language en --target-language de --text "hello, this is a local test"
live-translator translate-once --config app.quickstart.yaml --seconds 4 --translation-engine argos --target-language de --tts-engine none
```

On this machine, `en -> de` has already been installed. The shortest real mic test is:

```powershell
live-translator translate-once --config app.en-de.yaml
```

For the Senary headset devices currently shown on this machine:

```powershell
live-translator probe-input-devices
live-translator probe-output-devices
live-translator record-test --config app.working-devices.yaml --seconds 3 --out working-device-test.wav --play
live-translator transcribe-once --config app.working-devices.yaml --seconds 5
live-translator translate-once --config app.working-devices.yaml --seconds 5 --no-speak
```

`app.working-devices.yaml` is a local override file for this machine only. Keep it out of git and use `app.example.yaml` or `live-translator setup` when starting from a clean checkout.

For continuous fixed-chunk testing:

```powershell
live-translator loopback --config app.en-de.yaml
```

For English-to-German meeting routing with Piper:

```powershell
live-translator say --config app.meeting-en-de.yaml --text "Dies ist ein Test."
live-translator translate-once --config app.meeting-en-de.yaml --seconds 5
live-translator loopback --config app.meeting-en-de.yaml
```

To avoid fixed-window 4-second chunks during meeting tests, use the phrase/VAD
chunker. It commits after trailing silence, with a max-window fallback:

```powershell
live-translator meeting --profile en-de --chunker vad --silence-ms 550 --max-seconds 5
```

Current generated profiles use `chunking.mode: vad` by default. To compare
against the old fixed-window behavior, run:

```powershell
live-translator meeting --profile en-de --chunker fixed
```

For lower-latency overlapping chunks while speech is ongoing, use the rolling
mode:

```powershell
live-translator meeting --profile en-de --chunker rolling
```

The live path also has safety gates before speech is translated or spoken:

- low-energy buffers are skipped before ASR
- Whisper previous-text conditioning is disabled
- Whisper no-speech, low-log-probability, and high-compression-ratio segments are rejected

If silence still triggers ASR on a noisy device, make the gate stricter:

```powershell
live-translator meeting --profile en-de --peak-threshold 0.05 --min-active-ratio 0.15
```

If real speech is detected but rejected as low confidence, loosen the ASR
confidence gate:

```powershell
live-translator meeting --profile en-de --no-speech-threshold 0.95 --log-prob-threshold -2.2
```

If normal phrases are still missed, test a stronger ASR model and a slightly
longer minimum ASR window:

```powershell
live-translator meeting --profile en-de --model base --min-segment-seconds 1.6
```

Current generated meeting profiles use `base` by default because `tiny` misses
too much normal headset speech. Use `--model tiny` only when speed matters more
than recognition quality.

To debug recognition quality, save the exact audio chunks sent to Whisper:

```powershell
live-translator meeting --profile en-de --debug-audio-dir debug-asr
```

Open the newest `debug-asr/segment-####.wav` files and compare what you hear
with the neighboring `segment-####.txt` transcript. If the WAV is muffled or
contains the wrong source, fix the input device/audio driver first. If the WAV
is clear but transcription is poor, use a stronger model or longer chunks.

This is a first latency improvement, not full simultaneous translation. The next
step is rolling partial ASR with stable-prefix emission so translation can start
before the speaker fully stops.

For German-to-English, run setup with the reverse direction:

```powershell
live-translator setup --direction de-en
live-translator meeting
```

## Windows EXE Build

The POC can be packaged into a Windows app folder:

```powershell
.\scripts\build_windows.ps1 -InstallBuildTools
.\dist\LiveTranslator\LiveTranslator.exe setup
.\dist\LiveTranslator\LiveTranslator.exe route-test
.\dist\LiveTranslator\LiveTranslator.exe meeting
```

For a per-user local install:

```powershell
.\scripts\install_windows_user.ps1
```

This copies the built app folder to `%LOCALAPPDATA%\Programs\LiveTranslator`.
The current build is unsigned and console-based. A signed Inno/NSIS/MSI wrapper
should be the next packaging step after the routing profile proves reliable.
An Inno Setup template is included at `packaging/windows/LiveTranslator.iss`;
build it with `.\scripts\build_inno_installer.ps1` after installing Inno Setup.

The current POC uses fixed chunks first. That is deliberate: it proves local capture, local ASR, translation, and output before adding VAD and lower-latency overlapping windows.

Important correction: Whisper is not a general any-language-to-any-language translation engine. It can transcribe many languages, and its built-in translation path translates speech to English. For English to German, German to English, and future language pairs, the product needs three separate stages: ASR, machine translation, and TTS.

## Recommended MVP

Build the first Windows MVP as a Python package because the best local ASR ecosystem is already Python-friendly:

- `sounddevice` / PortAudio for capture and playback.
- `faster-whisper` for local ASR through CTranslate2.
- `silero-vad` or `webrtcvad` for speech gating.
- `stream2sentence` for low-latency sentence-like boundaries.
- `Argos Translate` or CTranslate2-converted Marian/NLLB models for offline text translation.
- `Piper` for local TTS.
- VB-CABLE A/B for Windows routing during testing.
- PyInstaller or Nuitka for an installable Windows executable.

After the MVP proves latency and quality, move the hot path into native code:

- C or C++ audio engine using WASAPI or miniaudio.
- CTranslate2 called directly for ASR and MT.
- ONNX/Piper TTS runtime embedded as native process or library.
- Java only for installer/admin UI/backend orchestration if needed, not the low-latency audio path.

## Files

- `docs/01-architecture.md` - concrete system architecture and latency budget.
- `docs/02-package-layout.md` - proposed Python package, command line, and config structure.
- `docs/03-windows-audio-routing.md` - Windows device routing plan using VB-CABLE A/B.
- `docs/04-implementation-plan.md` - phased build plan with acceptance checks.
- `docs/05-risks-and-decisions.md` - technical risks, decisions, and mitigations.
- `docs/06-meeting-test.md` - concrete meeting-app routing checklist.
- `docs/07-windows-packaging.md` - PyInstaller and local install notes.
- `scripts/build_windows.ps1` - PyInstaller Windows app-folder build.
- `scripts/install_windows_user.ps1` - per-user local install helper.
- `scripts/build_inno_installer.ps1` - optional Inno Setup installer build.
- `app.example.yaml` - initial config shape for the new package.
- `app.quickstart.yaml` - minimal config for the first local test.
- `app.en-de.yaml` - ready local English-to-German test config.
- `app.meeting-en-de.yaml` - Piper-based English-to-German meeting test config.
- `src/live_translator` - runnable Python POC.
