# Translate desktop GUI

The WPF project in `Translator/` is the desktop client for the existing
Live Translator backend. The Python CLI remains independently usable.

## Development

Open `Translator/Translator.slnx` in Visual Studio and run the `Translator`
project. During development the GUI searches for the backend in this order:

1. `LIVE_TRANSLATOR_BACKEND` environment variable.
2. `LiveTranslator.exe` next to `Translator.exe`.
3. The per-user installed `LiveTranslator.exe`.
4. `uv run --frozen live-translator` from a parent repository checkout.

`Apply` starts the backend's bidirectional `converse` session. The selected
English/German directions are passed to the CLI, which emits role-tagged JSONL
status and translation events. Outbound text is shown in the "You" card and
inbound meeting-audio text is shown in the "Other person" card.

This is the first integration slice. The voice, voice-speed, audio-device,
diagnostics and speak-translation controls are still visual settings; the
current `converse` command does not expose all of those overrides yet. Its
profiles continue to select the actual devices, models and voices.

`Stop translation` currently terminates the backend process. A graceful control
channel and audio pass-through must be added before this behavior is suitable
for an active meeting.
