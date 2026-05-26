# VB-CABLE Meeting Test Routine

Use this after installing VB-CABLE and rebooting Windows.

## Current Machine Status - 2026-05-25

Verified with the installed executable:

```powershell
$LT = "$env:LOCALAPPDATA\Programs\LiveTranslator\LiveTranslator.exe"
```

Generated profiles:

- `%LOCALAPPDATA%\LiveTranslator\profiles\en-de.yaml`
- `%LOCALAPPDATA%\LiveTranslator\profiles\de-en.yaml`

Current device indices used by those profiles with the Jabra/Senary headset
connected:

| Purpose | Device |
| --- | --- |
| Physical microphone | `30` - `Microphone (Senary Audio)` |
| Translated output to cable | `26` - `CABLE-A Input (VB-Audio Virtual Cable A)` |
| Meeting microphone | `33` - `CABLE-A Output (VB-Audio Virtual Cable A)` |

Smoke-test results:

- `route-test --profile en-de`: `PASS`, output `26` to input `33`, `sample_rate=48000`.
- `translate-text en->de`: `hello world` translated to `Hallo, die Welt`.
- `translate-text de->en`: `guten morgen` translated to `good morning`.
- `say --config %LOCALAPPDATA%\LiveTranslator\profiles\en-de.yaml`: Piper generated audio and played it into CABLE-A.
- `transcribe-once --config %LOCALAPPDATA%\LiveTranslator\profiles\en-de.yaml --seconds 1`: mic opened and faster-whisper loaded; transcript was blank because no speech was provided during the test.

Device indices can change after driver changes or reboot. If any command fails,
rerun `list-input-devices`, `list-output-devices`, and `setup` with the current
indices.

## Goal

```text
your real mic -> LiveTranslator -> translated Piper voice -> CABLE Input
CABLE Output -> meeting app microphone
meeting app speaker -> real headphones
```

Expected final behavior:

- You speak English in EN-DE mode.
- The other party hears German only.
- You do not hear your own translated voice.
- The other party does not hear your raw English.
- Several seconds of delay is expected in this fixed-chunk POC.

## 1. Open PowerShell

```powershell
$LT = "$env:LOCALAPPDATA\Programs\LiveTranslator\LiveTranslator.exe"
& $LT --help
```

Expected: command list appears, including `setup`, `route-test`, `meeting`, and `translate-text`.

If it fails, reinstall the current build:

```powershell
cd C:\Users\karol\Desktop\live-translator-local-solution
.\scripts\install_windows_user.ps1
```

## 2. Confirm VB-CABLE Devices

```powershell
& $LT list-input-devices
& $LT list-output-devices
```

Expected:

- input device: `CABLE Output (VB-Audio Virtual Cable)`
- output device: `CABLE Input (VB-Audio Virtual Cable)`

If either is missing, reboot again or reinstall VB-CABLE as administrator.

## 3. Create EN-DE Profile

First check the physical mic index:

```powershell
& $LT list-input-devices
```

On the current test machine with the Jabra/Senary headset connected, `30` is the
real microphone, `26` is CABLE-A Input, and `33` is CABLE-A Output:

```powershell
& $LT setup --profile en-de --direction en-de --input-device 30 --translated-output-device 26 --meeting-microphone-device 33
```

If your real microphone or cable endpoints have different indices, replace those
numbers with the current values from `list-input-devices` and
`list-output-devices`.

Expected:

```text
Wrote profile: C:\Users\karol\AppData\Local\LiveTranslator\profiles\en-de.yaml

Meeting app setup:
  Microphone: CABLE Output ...
  Speaker: your real headphones, not the translated output endpoint
```

## 4. Validate Virtual Cable Routing

```powershell
& $LT route-test --profile en-de
```

Expected:

```text
PASS: output 'CABLE Input ...' -> input 'CABLE Output ...' rms=... peak=...
```

If it fails:

- The input/output may be swapped.
- VB-CABLE may need a reboot.
- Another app may have the cable endpoint locked.
- Run interactive setup:

```powershell
& $LT setup --profile en-de --direction en-de
```

## 5. Test Translation Models

```powershell
& $LT translate-text --source-language en --target-language de --text "hello world"
& $LT translate-text --source-language de --target-language en --text "guten morgen"
```

Expected:

- First command returns German text.
- Second command returns English text.

## 6. Test Physical Mic Transcription

```powershell
& $LT transcribe-once --config "$env:LOCALAPPDATA\LiveTranslator\profiles\en-de.yaml" --seconds 5
```

Speak English during the 5 seconds.

Expected:

```text
Detected language: en
Transcript: ...
```

If transcript is blank, the wrong mic is selected or Windows mic level/permissions need adjustment.

## 7. Test One Translated Chunk

```powershell
& $LT translate-once --config "$env:LOCALAPPDATA\LiveTranslator\profiles\en-de.yaml" --seconds 5
```

Speak English during the recording window.

Expected terminal output:

```text
Source: ...
Target: ...
Timings: audio=5.00s asr=... mt=... tts=... total=...
```

Expected audio behavior:

- You should not hear the translation.
- If the meeting app is already set to `CABLE Output`, its mic meter should move when Piper speaks.

## 8. Configure Google Meet

In Meet audio settings:

- Microphone: `CABLE Output (VB-Audio Virtual Cable)`
- Speaker: your real headphones or speakers, for example `Speakers (Senary Audio)`
- Do not use `Microphone Array (AMD Audio Device)` as the Meet microphone.
- Turn off Meet noise suppression/studio sound for the first test if available.

Leak test:

1. Stop LiveTranslator.
2. Speak English.
3. Meet mic meter should not move.

If it moves, Meet is still hearing your physical microphone.

## 9. Start Meeting Mode

Fixed 4-second chunks are the baseline mode:

```powershell
& $LT meeting --profile en-de
```

Current generated profiles use phrase/VAD chunks by default. It starts ASR after
speech ends instead of waiting for every fixed 4-second window:

```powershell
& $LT meeting --profile en-de --chunker vad --silence-ms 550 --max-seconds 5
```

For lower-latency overlapping chunks while speech is ongoing, try:

```powershell
& $LT meeting --profile en-de --chunker rolling
```

The live path now also rejects likely non-speech before it reaches translation:

- low-energy buffers are skipped before ASR
- Whisper previous-text conditioning is disabled
- Whisper no-speech, low-log-probability, and high-compression-ratio segments are rejected

Tuning notes:

- Lower `--silence-ms`, for example `400`, reduces latency but may cut phrases too early.
- Higher `--silence-ms`, for example `750`, waits for cleaner phrase endings.
- Lower `--vad-threshold`, for example `0.008`, makes speech detection more sensitive.
- Higher `--vad-threshold`, for example `0.02`, avoids background noise triggering translation.
- Higher `--peak-threshold` or `--min-active-ratio` makes the no-speech safety gate stricter.
- Higher `--no-speech-threshold`, for example `0.95`, accepts more detected speech after Whisper.
- Lower `--log-prob-threshold`, for example `-2.2`, accepts rougher tiny-model transcriptions.
- Higher `--min-segment-seconds`, for example `1.6`, gives Whisper more audio context.
- Current generated profiles use `base`; `--model tiny` is faster but misses more normal headset speech.
- `--debug-audio-dir debug-asr` writes the exact chunks sent to Whisper for inspection.
- Fixed-window mode is still available for comparison with `--chunker fixed`.

Speak English in short phrases.

Expected:

- Console prints source and target chunks.
- Other party hears German only.
- You do not hear your own translated voice.

Stop with `Ctrl+C`.

## 10. Test DE-EN

```powershell
& $LT setup --profile de-en --direction de-en --input-device 30 --translated-output-device 26 --meeting-microphone-device 33
& $LT route-test --profile de-en
& $LT meeting --profile de-en
```

Expected:

- You speak German.
- Other party hears English with the English Piper voice.

## Troubleshooting

If you hear your own translation:

```text
mmsys.cpl
```

Then check:

- Recording tab -> `CABLE Output` -> Properties -> Listen -> uncheck `Listen to this device`.
- Recording tab -> real mic -> Properties -> Listen -> uncheck `Listen to this device`.
- Meeting speaker must not be `CABLE Input`.

If the other party hears English and German:

- Meeting microphone is wrong.
- It must be `CABLE Output (VB-Audio Virtual Cable)`.
- It must not be `Microphone Array (AMD Audio Device)`.

## Success Criteria

The POC passes if:

- `route-test` returns `PASS`.
- `transcribe-once` captures your physical mic.
- `translate-once` prints correct source and target.
- Meeting mic meter is silent when LiveTranslator is stopped.
- Meeting mic meter moves when LiveTranslator speaks.
- Other party hears translated language only.
