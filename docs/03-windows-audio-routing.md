# Windows Audio Routing

## Current POC Reference

The existing C# POC uses NAudio and Azure Speech. It already proves the important Windows routing concept:

- capture from a microphone or virtual cable recording endpoint
- synthesize translated audio
- render translated audio to headphones or a virtual cable playback endpoint

The new product should keep that routing behavior but replace Azure with local inference.

## Endpoint Naming

VB-CABLE naming is easy to confuse:

- `CABLE Input` is usually a Windows playback/render endpoint.
- `CABLE Output` is usually a Windows recording/capture endpoint.

So when the app wants to send audio into a meeting as a fake microphone, it renders to `CABLE Input`, and the meeting app selects `CABLE Output` as its microphone.

For A/B cables, the names are commonly:

- `CABLE-A Input` as playback endpoint
- `CABLE-A Output` as recording endpoint
- `CABLE-B Input` as playback endpoint
- `CABLE-B Output` as recording endpoint

Always verify names with `list-input-devices` and `list-output-devices` because Windows drivers and language settings may present slightly different names.

## One-Way Meeting Mode

Use this for the first serious call test:

```text
my physical microphone
  -> Live Translator app
  -> translated speech
  -> CABLE-A Input playback endpoint
  -> meeting app microphone set to CABLE-A Output
```

The user should listen to the meeting through normal headphones.

The meeting app microphone must be the virtual cable recording endpoint. If it
is set to the physical microphone, peers will hear the original speech directly
and then hear the translated speech from the translator.

For the current local POC, prefer Piper for meeting tests. The temporary
`pyttsx3` engine speaks through the Windows default output device and ignores the
configured `audio.output_device`, which makes routing mistakes much easier.

## Duplex Meeting Mode

Use two cables and headphones:

```text
outbound:
my physical microphone
  -> Live Translator route A
  -> translated speech
  -> CABLE-A Input playback endpoint
  -> meeting app microphone set to CABLE-A Output

inbound:
meeting app speaker set to CABLE-B Input playback endpoint
  -> Live Translator captures CABLE-B Output recording endpoint
  -> translated speech
  -> physical headphones
```

Do not route translated output to speakers during duplex tests. Use headphones to avoid feedback into the microphone.

## Device Selection Rules

The package should implement friendly matching like the C# POC:

- exact friendly-name match first
- single partial match second
- if a cable input/output direction is reversed, suggest or auto-map the opposite endpoint

If multiple devices match, the program should fail with a clear message and ask for the full friendly name.

## Production Audio Driver Path

Do not start with a kernel-mode audio driver.

Reasons:

- driver signing is required
- driver crashes are system-level failures
- enterprise deployment policies are stricter for drivers
- debugging driver/audio endpoint issues will slow down MVP validation

Recommended progression:

1. MVP with VB-CABLE A/B.
2. Product beta with a documented third-party virtual cable dependency or licensed redistribution.
3. Enterprise version with a signed virtual audio endpoint driver or a licensed driver component.

The app architecture should treat the virtual cable as a replaceable adapter so the pipeline does not care whether output goes to VB-CABLE, a future custom endpoint, or normal headphones.
