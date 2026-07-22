# Runtime Architecture

## Scope

Live Translator runs one speech-translation direction per process. A profile
binds one physical microphone, one source language, one target language, one
Piper voice, and one output endpoint.

English to German and German to English use separate profiles. The application
does not currently capture the remote meeting audio or translate both sides of
a conversation simultaneously.

## Startup

Meeting mode completes these steps before reporting `Ready`:

1. Load the configured faster-whisper model.
2. Open the configured Argos CTranslate2 model and SentencePiece tokenizer.
3. Validate the Piper executable, voice model, and voice JSON.
4. Resolve the configured input and output devices when capture begins.

`doctor --prepare-models` performs the same asset and model checks without
starting the meeting loop.

## Live Processing

```text
long-lived microphone InputStream
  -> VAD segmenter
  -> bounded phrase queue
  -> faster-whisper ASR and confidence rejection
  -> Argos CTranslate2 translation
  -> bounded playback queue
  -> Piper synthesis and virtual-cable playback
```

The ASR input rate is fixed at 16 kHz mono. Audio devices that do not accept
16 kHz are opened at a supported rate and resampled with PyAV/libswresample for
the inference path.

The default VAD path is amplitude-based and adaptive. It maintains a short pre-roll, starts on
RMS or peak activity, ignores short false triggers, and commits after trailing
silence or the configured maximum duration. Input gain is applied consistently
to detection and ASR audio.

### Phrase Boundary Semantics

The generated demo profiles inspect one 30 ms audio frame at a time. They do
not detect punctuation, sentence-final words, or linguistic word boundaries.
The active settings behave as follows:

1. Keep the configured 200 ms of quiet audio as pre-roll so the first consonant
   is not clipped. Frame rounding makes this seven frames, about 210 ms.
2. Start a candidate phrase when RMS or peak energy crosses the adaptive
   threshold.
3. Reject the candidate as a false trigger unless at least 180 ms (six frames)
   of its frames contain speech activity. These active frames need not be
   consecutive.
4. Commit after 450 ms (15 frames) of trailing inactivity once the complete
   buffered segment is at least 0.8 seconds long (27 frames, about 810 ms).
5. Commit at the configured 5.0-second ceiling during uninterrupted speech (167
   frames, about 5.01 seconds) so one segment cannot grow without bound.

The microphone stream remains open after a commit. The completed segment is
queued for recognition while the same capture stream begins collecting the next
phrase. Faster-whisper still receives each completed segment as one offline
inference request; the current release does not revise partial transcripts as
new words arrive.

The 450 ms boundary is only the endpointing delay. Recognition, translation,
whole-phrase Piper synthesis, output stream startup, and playback add their own
latency.

Before ASR, the energy gate requires a configurable ratio of active frames.
After ASR, segments can be rejected using Whisper no-speech probability,
average log probability, compression ratio, and minimum text length.

## Concurrency Model

VAD and rolling meeting modes have three ordered stages. Capture and VAD run continuously on the
long-lived input stream. A single recognition worker owns faster-whisper and
Argos. A separate playback worker owns Piper and sounddevice output. Recognition
therefore continues while an earlier translation is being synthesized or
played, and neither stage closes the microphone stream.

Complete phrases, rather than raw audio frames, are queued between stages. The
generated profiles allow two pending recognition phrases and one pending
playback phrase. Under normal operation this absorbs transient model or playback
latency. When either queue is full, the oldest pending item is skipped and a
warning is printed so latency cannot grow without bound or fail silently.
Phrase ordering is preserved otherwise.

Generated profiles use VAD mode. It waits for sustained speech and commits one
phrase after trailing silence or the configured maximum length. Rolling mode can
also emit 2.4-second windows during uninterrupted speech, but overlap can repeat
context or split a word, so it remains an explicit experimental option.

## Lower-Latency Direction

Word-by-word translation is not the intended next step. A word boundary alone
does not establish a stable translation, especially between English and German,
where later verbs and clause structure can change earlier output. Speaking each
word immediately would also make Piper output discontinuous and difficult to
understand.

The safer streaming design is:

1. Use neural VAD and acoustic endpointing to distinguish short hesitations
   from likely phrase boundaries.
2. Re-run ASR over a short overlapping audio context several times per second.
3. Commit only the longest transcript prefix that remains unchanged across
   consecutive hypotheses; keep revising the unstable suffix.
4. Translate stable prefixes with a simultaneous or prefix-to-prefix policy,
   while retaining enough uncommitted context for German clause structure.
5. Synthesize short stable clauses or stream TTS audio, rather than synthesizing
   isolated words.

This preserves understandable language while allowing captions to update before
a pause. It requires transcript stabilization and duplicate suppression that the
current experimental rolling-window mode does not yet implement.

Fixed mode is retained for diagnosis. It records independent time windows and
reopens capture for each block; it does not use the persistent VAD stream.

## Models

- ASR: faster-whisper through CTranslate2
- Text translation: Argos `en_de` and `de_en` CTranslate2 packages
- Speech output: Piper CLI and local ONNX voices

Piper produces a complete WAV phrase before playback begins. Playback runs on
its own worker, but speech synthesis itself is not streamed.

Playback uses an explicit blocking PortAudio output stream. A Windows host
failure while opening that stream is retried twice on the same verified WASAPI
endpoint. If all three starts fail, that phrase is skipped with a warning while
capture and recognition remain active. Recognition or translation worker
failures remain fatal because subsequent phrases cannot be processed safely.

Argos packages are discovered in `ARGOS_PACKAGES_DIR`, the bundled
`models/argos/packages` directory, or the normal per-user Argos data directory.
Piper models and the executable are resolved relative to the working directory,
the installed executable directory, or the PyInstaller bundle directory.

Named faster-whisper models use the Hugging Face user cache. That cache is not
inside this repository or the packaged application.

## Error Handling

Configuration keys are validated when loaded. Unknown sections, unknown
settings, unsupported engines, invalid language combinations, and non-16 kHz
pipeline rates fail with a clear message.

`doctor` reports each configured device and asset independently. `route-test`
uses the strength and dominance of a generated 880 Hz reference tone, preventing
ambient noise on the wrong input from producing a false pass.

## Known Limits

- One direction per running profile
- No simultaneous incoming-audio translation
- Phrase-level output rather than stabilized word-by-word streaming
- No partial transcript stabilization or streaming TTS
- No bundled faster-whisper model in the current Windows build
- Unsigned internal Windows executable
