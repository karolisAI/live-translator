# Changelog

This project follows [Semantic Versioning](https://semver.org/).

## 0.1.0 — unreleased

Initial release.

- `ParakeetRecognizer` loads NVIDIA Parakeet TDT through `onnx-asr` on
  onnxruntime, with no PyTorch or NeMo dependency.
- `transcribe()` recognizes one complete utterance and returns a `Transcript`
  carrying the text, the timings, and whether the result was rejected.
- Confidence filtering rejects empty output as `no_speech`, output below
  `min_chars` as `short`, low mean per-token logprob, and degenerate repetition
  caught by compression ratio.
- `recover_empty` (default on) re-decodes a clip that produced zero tokens,
  perturbing the input rather than adding to it, so real speech is recovered
  while silence, noise and music stay empty. `Transcript.recovered_by` reports
  which pass succeeded. Gated by `min_recovery_seconds` (default `3.0`) because
  retries on very short clips were as likely to produce garbage as words.
- Language can be set on the recognizer or overridden per `transcribe()` call,
  so a bidirectional pipeline needs only one loaded model.
- Whisper model names raise `UnsupportedModel` rather than a bare onnx-asr
  error, and a missing `onnx-asr` raises `MissingDependency`.
