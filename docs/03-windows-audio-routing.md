# Windows Audio Routing

## Endpoint Direction

VB-CABLE names its endpoints from the cable's perspective:

- `CABLE Input` is a Windows playback device. Live Translator plays translated
  speech to it.
- `CABLE Output` is a Windows recording device. The meeting application uses it
  as its microphone.

```text
physical microphone -> Live Translator -> CABLE Input
CABLE Output -> meeting application microphone
meeting application speaker -> real headset
```

One matched cable pair is sufficient for the current one-way translator.

## Profile Setup

Run:

```powershell
live-translator setup --profile en-de --direction en-de
```

Repeat with `--profile de-en --direction de-en` for the reverse language
direction. Setup writes automatic selectors by default. Each run follows the
Windows default physical microphone and resolves a complete standard CABLE-A
playback/recording pair.

Device lists include the current PortAudio index and Windows host API. Windows
often publishes the same endpoint through MME, DirectSound, and WASAPI. The
automatic resolver prefers WASAPI and does not persist the temporary index.

If the wrong physical microphone is selected, change the Windows default input
or pass its full friendly name to `setup --input-device`. Use
`--interactive-devices` only when automatic selection is unsuitable.

## Validation

```powershell
live-translator doctor --config "$env:LOCALAPPDATA\LiveTranslator\profiles\en-de.yaml"
live-translator route-test --profile en-de
```

`doctor` verifies that each selected endpoint still exists and supports a usable
sample rate. `route-test` sends an 880 Hz tone to the playback endpoint and
requires the same tone on the recording endpoint.

## Meeting Configuration

Set the meeting application to:

- Microphone: selected `CABLE Output`
- Speaker: real headset or speakers

Do not select the physical microphone as the meeting microphone. Otherwise the
remote participant can hear untranslated speech. Do not select `CABLE Input` as
the meeting speaker; that creates incorrect routing and may feed meeting audio
back into the microphone path.

Disable automatic microphone switching. For the first test, disable aggressive
noise suppression or studio-audio processing until the translated Piper voice
is known to reach the meeting input.

## Leak Test

1. Stop Live Translator.
2. Speak into the physical microphone.
3. Confirm the meeting microphone meter does not move.
4. Run `say` with the profile.
5. Confirm the meeting microphone meter moves only for the synthesized voice.

If translated speech is audible locally, open the Windows recording-device
properties for `CABLE Output` and disable `Listen to this device`.
