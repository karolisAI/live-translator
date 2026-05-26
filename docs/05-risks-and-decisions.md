# Risks And Decisions

## Decisions

### Use Python For The First MVP

Reason:

- Fastest path to `faster-whisper`, VAD, segmentation, and local TTS experiments.
- Lets the team measure real latency before investing in a native rewrite.

Constraint:

- Python should not become the permanent low-latency audio engine if timing or packaging becomes unreliable.

### Use Local ASR + MT + TTS

Reason:

- Removes Azure batching and network latency.
- Better enterprise privacy story.
- Works offline after model installation.

Constraint:

- More model packaging and hardware variability to manage.

### Avoid Kernel Driver Work In The MVP

Reason:

- Kernel/audio driver work changes the risk profile.
- Driver signing, crashes, and enterprise deployment policies will slow validation.

Constraint:

- VB-CABLE or another virtual cable remains a dependency until a signed endpoint is built or licensed.

### Treat Java As Control Plane, Not Audio Hot Path

Reason:

- Java is strong for admin UI, configuration, licensing, updates, and backend service structure.
- The low-latency audio/inference path is better suited to Python for MVP and C/C++ for production.

Constraint:

- If Java is used early, keep it outside the timing-critical audio loop.

## Main Risks

### Latency May Move From Azure To Local Models

Risk:

- A slow CPU can make local ASR/TTS slower than expected.

Mitigation:

- Benchmark `base`, `small`, and `medium` ASR models.
- Expose model size, compute type, ASR window, and beam size in config.
- Prefer stale-work dropping over growing queues.

### Offline Translation Quality May Be Uneven

Risk:

- Argos or small Marian models may not match Azure quality.

Mitigation:

- Start with one or two enterprise-relevant language pairs.
- Compare Argos against CTranslate2-converted models.
- Keep MT model choice behind an interface.

### TTS Quality May Feel Less Natural

Risk:

- Fast local TTS can sound worse than cloud neural voices.

Mitigation:

- Use Piper for latency first.
- Add higher-quality optional voices after the product meets latency goals.
- Keep TTS voice and speed configurable.

### Full Duplex Can Feed Back

Risk:

- Speaker audio can leak into microphone and cause repeated translation.

Mitigation:

- Require headphones for duplex testing.
- Keep two virtual cables.
- Add echo cancellation only after routing is stable.

### Model Distribution Can Create Licensing Issues

Risk:

- ASR, MT, and TTS models may have different redistribution licenses.

Mitigation:

- Maintain a model registry with license metadata.
- Use a model downloader for early builds.
- Bundle models only after legal review.

### Enterprise Driver Work Is A Separate Project

Risk:

- A custom virtual audio endpoint can consume more time than the translator itself.

Mitigation:

- Keep routing abstracted.
- Prove product value with VB-CABLE.
- Decide later whether to build, buy, or license the virtual audio component.

## First Technical Spike

Build a one-way local loopback in this order:

1. `sounddevice` capture and playback.
2. `faster-whisper` transcription with timings.
3. VAD chunking.
4. `stream2sentence` segmentation.
5. English to German offline MT.
6. Piper German TTS.
7. Output to `CABLE-A Input`.

Stop and evaluate after this spike. If p90 perceived latency is still above 2500 ms on the target Windows laptop, tune model size and chunking before adding duplex complexity.
