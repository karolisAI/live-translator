# Translate desktop GUI

The WPF project in `Translator/` is the desktop client for the existing
Live Translator backend. The Python CLI remains independently usable.

## Development

Open `Translator/Translator.slnx` in Visual Studio and run the `Translator`
project. During development the GUI searches for the backend in this order:

1. `LIVE_TRANSLATOR_BACKEND` environment variable.
2. `LiveTranslator.exe` next to `Translator.exe`.
3. The per-user installed `LiveTranslator.exe`.
4. The repository `.venv` Python with `src` on `PYTHONPATH`.
5. `uv run --frozen --with-editable . live-translator` from a parent repository checkout.

`Apply` starts the backend's bidirectional `converse` session. The selected
English/German directions are passed to the CLI, which emits role-tagged JSONL
status and translation events. Outbound text is shown in the "You" card and
inbound meeting-audio text is shown in the "Other person" card.

The GUI reads real Windows capture and playback devices from the backend. Voice,
voice-speed, outbound/inbound audio routing, diagnostics, Confidential mode and
the two speak-translation controls are passed to `converse`. GUI preferences are
stored in `%LOCALAPPDATA%\LiveTranslator\gui-settings.json` and restored when the
app starts. The meeting application's microphone and speaker still need to be
selected in Teams, Zoom or the equivalent meeting client.

`Stop translation` currently terminates the backend process tree. A graceful
backend control channel remains future work.
