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

1. Verify the prepared Parakeet model against the approved SHA-256 manifest,
   then load it.
2. Verify and open the configured Argos CTranslate2 model and SentencePiece
   tokenizer.
3. Verify the complete Piper runtime and bundled voices, select the configured
   voice, and start the resident synthesis process (see
   [Piper Process Lifecycle](#piper-process-lifecycle)).
4. Resolve the configured input and output devices when capture begins.

Step 1 runs before step 4, so an unprepared machine fails while no audio device
is open and no meeting audio exists in the process. The model is loaded by
handing `onnx-asr` the prepared directory, which puts its resolver in offline
mode: a missing file becomes an error rather than a download. `prepare-models`
is the only command that fetches one, and it is not part of this sequence.

`doctor --prepare-models` performs the same asset and model checks without
starting the meeting loop or the Piper process, and likewise never downloads.

## Live Processing

```text
long-lived microphone InputStream
  -> VAD segmenter
  -> bounded phrase queue
  -> Parakeet ASR and confidence rejection            \
  -> Argos CTranslate2 translation                      } recognition worker
  -> Piper synthesis, producing rendered audio          /
  -> bounded playback queue
  -> virtual-cable playback                            } playback worker
```

Synthesis happens on the recognition worker, not the playback worker; see
[Concurrency Model](#concurrency-model) for why.

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
phrase. The recognizer still receives each completed segment as one offline
inference request; the current release does not revise partial transcripts as
new words arrive.

The 450 ms boundary is only the endpointing delay. Recognition, translation,
whole-phrase Piper synthesis, output stream startup, and playback add their own
latency.

Before ASR, the energy gate requires a configurable ratio of active frames.
After ASR, a segment can be rejected outright on empty output, average log
probability, compression ratio, or minimum text length. A segment that clears
rejection but still has a low average log probability is not rejected: it is
translated and spoken in full, and only marked `low_confidence` in the
displayed transcript (both the source and target line, under `--show-text`).
Calibration on a 100-clip set found this distinction necessary rather than
cosmetic: most flagged English segments were near-misses (5 of 7 had a word
error rate under 0.19), and average log probability does not separate a
near-miss from a real error cleanly enough on English (r = -0.52) to gate
speech on it without also silencing mostly-correct phrases. The correlation is
stronger on German (r = -0.84); the marker-only behavior is intentionally the
same for both directions today.

## Concurrency Model

VAD and rolling meeting modes have three ordered stages, but only two workers.
Capture and VAD run continuously on the long-lived input stream, feeding a
bounded phrase queue. A single **recognition worker** owns the recognizer,
Argos, and Piper synthesis: for each phrase it runs ASR, translation, and
`render()`, which synthesizes audio without playing it. A separate
**playback worker** owns only sounddevice output: it calls `play()` on
whatever the recognition worker already rendered. Neither stage closes the
microphone stream.

Synthesis sits on the recognition worker rather than the playback worker so
the two overlap: the recognition worker can render the next phrase while the
previous one is still being spoken, rather than paying synthesis and playback
back to back on the same worker. This was a measured change, not a stylistic
one: with both on one worker, that worker was busy 4.01s per phrase while
phrases arrived every 3.52s, so it fell behind on every phrase and its queue
discarded roughly a fifth of them.

Complete phrases, rather than raw audio frames, are queued between stages. The
generated profiles allow two pending recognition phrases and one pending
playback phrase. Under normal operation this absorbs transient model or
playback latency. When either queue is full, it applies backpressure by
dropping the oldest pending item rather than blocking capture, and a warning
is printed so latency cannot grow without bound or fail silently. Phrase
ordering is preserved otherwise.

A synthesis failure on the recognition worker (a Piper timeout, a corrupted
response, an untrusted resolved path) does not stop the meeting: transcription
and translation for that phrase are already done, so only that phrase's audio
is skipped, with a warning naming the phrase number. An untrusted Piper path
is treated differently from a transient failure: because it will resolve the
same way again, it permanently disables further synthesis for the rest of the
session rather than retrying every phrase, while transcription and translation
keep running normally. A failure in recognition or translation itself remains
fatal, since later phrases cannot be produced safely once that stage has
failed.

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

- ASR: Parakeet TDT through onnx-asr and onnxruntime
- Text translation: Argos `en_de` and `de_en` CTranslate2 packages
- Speech output: Piper CLI and local ONNX voices

Piper produces a complete WAV phrase before playback begins; synthesis itself
is not streamed. See [Concurrency Model](#concurrency-model) for which worker
renders it and why, and [Piper Process Lifecycle](#piper-process-lifecycle)
for how the `piper.exe` subprocess itself is managed across a session.

Playback uses an explicit blocking PortAudio output stream. A Windows host
failure while opening that stream is retried twice on the same verified WASAPI
endpoint. If all three starts fail, that phrase is skipped with a warning while
capture and recognition remain active.

Piper's executable and voice model, and the bundled-default candidate for
Argos packages, resolve only against the app's own installed/bundled
location (`runtime.approved_runtime_roots()`: the frozen executable's
directory, the PyInstaller bundle directory, or the package root when running
from source) -- never the current working directory, since anyone able to
launch the app from an arbitrary directory, or place a file in one already on
that list, could otherwise get an untrusted file resolved and, for Piper,
run. A local development override (`LIVE_TRANSLATOR_DEV_RUNTIME_ROOT`) exists
to unblock testing a build from somewhere else, but is never active unless
explicitly set, and never honored in a frozen build regardless of whether
the variable is set, so it structurally cannot widen trust for a real
installed app.

Argos packages additionally check `ARGOS_PACKAGES_DIR` and the normal
per-user Argos data directory (`XDG_DATA_HOME`, or `~/.local/share`) ahead of
and after the bundled default, respectively. Unlike the bundled-default path,
these two remain deliberately unrestricted in *where* they may point -- an
operator pointing at a custom or updated package location is a supported
use, not a fallback for something missing. Location flexibility does not widen
content trust: the selected directory must still match an approved `en_de` or
`de_en` manifest root byte-for-byte.

The pinned Parakeet model is prepared under the repository when running from
source and under `%LOCALAPPDATA%\LiveTranslator` in an installed build. The
application verifies its four model files and mandatory `revision.txt`; only
Hugging Face `.cache` download metadata is excluded from verification.

The complete integrity design, provenance evidence, benchmarks and residual
risks are documented in [06-runtime-asset-integrity.md](06-runtime-asset-integrity.md).

### Piper Process Lifecycle

One `piper.exe` is started when a session starts and kept alive for the whole
meeting, fed one JSON request per phrase over `--json-input`, rather than a
fresh process per phrase. The earlier per-phrase design paid a fixed cost
before it could synthesize anything -- process start plus a voice-model reload,
about 0.41s isolated from playback, on top of Piper's own ~0.02s/word once
warm. The resident process pays that load once, at startup, in `warm_up()`.

Measured on a controlled stimulus, keeping the process resident drops median
synthesis from 0.65s to 0.25s and the median delay from end of speech to
translated audio starting from 1.69s to 1.26s, since nothing else on the
critical path changes.

The process is driven so a single slow or misbehaving phrase cannot corrupt
the rest of the meeting:

- Requests and responses are matched only by arrival order, and Piper echoes
  back the output path it wrote. A response naming a different file, or one
  that does not arrive within `tts.piper_timeout_seconds`, kills the process
  rather than letting a stale answer be handed to a later phrase.
- A dead process is detected and transparently replaced on the next call
  rather than reused.
- Every command that starts the process (`meeting`, `loopback`,
  `translate_once`, `say`) closes it on every exit path, since Windows does
  not terminate a subprocess child automatically when the parent process
  exits. Meeting shutdown waits out a phrase still blocked in synthesis before
  tearing the process down, so a hung phrase cannot orphan a replacement.

## Error Handling

Configuration keys are validated when loaded. Unknown sections, unknown
settings, unsupported engines, invalid language combinations, and non-16 kHz
pipeline rates fail with a clear message.

`doctor` reports each configured device and asset independently. `route-test`
uses the strength and dominance of a generated 880 Hz reference tone, preventing
ambient noise on the wrong input from producing a false pass.

Diagnostic capture (`--diagnostics`, `--debug-audio-dir`, or a profile's
`diagnostics.enabled`) is opt-in and off by default. A capture write the
operating system refuses -- a full disk, a revoked permission, a file held
open by a scanner or sync client -- is reported once per meeting rather than
ending the session: the realistic causes tend to fail on every subsequent
phrase too, so a warning printed every few seconds would be its own kind of
broken, and capture is still attempted again on the next phrase in case the
cause was transient.

## Known Limits

- One direction per running profile
- No simultaneous incoming-audio translation
- Phrase-level output rather than stabilized word-by-word streaming
- No partial transcript stabilization or streaming TTS
- No bundled speech model in the current Windows build
- Unsigned internal Windows executable
- Unsigned runtime manifest and installer; hashes do not authenticate their publisher
- Startup verification is cached, leaving a same-user time-of-check/time-of-use window
- No automated test exercises the real Piper binary; synthesis correctness is
  verified manually and through a scripted test double of its request/response protocol
