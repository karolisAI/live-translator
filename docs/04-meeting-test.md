# Meeting Validation Checklist

## Before Opening the Meeting

```powershell
$ENDE = "$env:LOCALAPPDATA\LiveTranslator\profiles\en-de.yaml"
$DEEN = "$env:LOCALAPPDATA\LiveTranslator\profiles\de-en.yaml"

live-translator doctor --config $ENDE --prepare-models
live-translator doctor --config $DEEN --prepare-models
live-translator route-test --profile en-de
live-translator route-test --profile de-en
```

Every configured check must report `OK`, and both route checks must report
`PASS`. The checks print the concrete endpoints selected by each automatic
audio role.

Verify text translation independently:

```powershell
live-translator translate-text --source-language en --target-language de --text "Good morning, this is a translation test."
live-translator translate-text --source-language de --target-language en --text "Guten Morgen, dies ist ein Uebersetzungstest."
```

Verify physical microphone capture:

```powershell
live-translator transcribe-once --config $ENDE --seconds 5
```

Speak during the recording interval and confirm the transcript matches.

## Meeting Settings

- Microphone: the `CABLE Output` endpoint stored in the profile
- Speaker: the real headset or speakers
- Automatic microphone switching: off
- Noise suppression or studio sound: off for the first route test

With Live Translator stopped, speaking into the physical microphone must not
move the meeting microphone meter.

Test synthesized output:

```powershell
live-translator say --config $ENDE --text "Dies ist ein Audiotest."
```

The meeting microphone meter should move. The voice should not play through the
local headset unless Windows `Listen to this device` is enabled.

## Live Test

Start English to German:

```powershell
live-translator meeting --profile en-de
```

Wait for `Ready`, then speak a short English phrase and pause. Confirm:

- the terminal prints one line per phrase, such as
  `Phrase   1    3.4s    ready in 1.9s`
- the meeting microphone meter moves during Piper output
- the remote participant hears only translated speech
- the microphone remains active while the previous phrase is recognized and
  played; a second phrase spoken during playback is translated next

Normal mode prints no transcript and no translation, so a confidential meeting
leaves no content in the terminal or its scrollback. To check the text itself,
repeat the run with `--show-text`, which prints the source phrase and its
translation and nothing else. `--verbose` no longer shows this text; it is
telemetry only (audio gates, per-segment timing).

End that meeting process with `Ctrl+C`, then test the reverse profile. This key
combination ends the session only; capture and translation do not require a key
press between phrases.

```powershell
live-translator meeting --profile de-en
```

## Diagnostic Mode

```powershell
live-translator meeting --profile en-de --verbose --show-text --debug-audio-dir debug-asr
```

`--show-text` prints the source text and its translation, which normal mode
withholds; `--verbose` adds energy levels, confidence rejections, and segment
timing. Each accepted or skipped chunk is written as a WAV with a neighboring
text file.
Listen to the WAV before changing model or threshold settings; an incorrect or
muffled source device cannot be fixed by ASR tuning.

## Failure Guide

`doctor` cannot select an input or output:

- Run `list-input-devices` and `list-output-devices`.
- Confirm the intended physical microphone is the Windows default input.
- Confirm both sides of one standard VB-CABLE pair are enabled.
- Use full friendly-name setup overrides only when automatic selection is not
  appropriate.

`route-test` fails:

- Confirm the playback endpoint is `CABLE Input`.
- Confirm the meeting microphone endpoint is the matching `CABLE Output`.
- Close applications that may hold either endpoint exclusively.
- Reboot after installing or updating VB-CABLE.

A translated phrase reports a Windows host or `WdmSyncIoctl` playback warning:

- The runtime retries the same verified WASAPI endpoint automatically.
- If the phrase is skipped, continuous listening remains active; speak the next
  phrase after checking that the meeting still uses `CABLE Output`.
- Close other audio tools using CABLE-A and disable exclusive control for both
  CABLE-A endpoints if the warning repeats.

Transcription is empty:

- Confirm Windows microphone permission for desktop applications.
- Run `record-test` and listen to the WAV.
- Use `--verbose` to inspect the VAD and energy-gate values.

The remote participant hears original and translated speech:

- The meeting microphone is still the physical microphone or an automatic input.
- Select only the configured `CABLE Output` endpoint.

An overload warning appears:

- Return to the default VAD mode for the demonstration.
- Use shorter phrases and allow a brief pause so the recognition queue can
  catch up. Capture itself remains active during recognition and playback.
