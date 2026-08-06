# German Speech Recognition Accuracy

Speech-to-text on the `de-en` profile is noticeably inaccurate: words get
dropped, swapped, or cut off, more often than on the `en-de` profile. This
comes from the faster-whisper ASR stage and its settings for German, in
`de-en.yaml`.

## Likely causes

- **`asr.model: base`** — the smallest Whisper size. Its accuracy gap between
  English and other languages is much bigger than for the larger models, so
  German suffers more than English does on the same model.
- **`beam_size: 1`** — greedy decoding. The model commits to each word
  immediately and can't backtrack if an early guess was wrong. German's long
  compound words and case endings give it more chances to lock in a mistake.
- **`condition_on_previous_text: false`** — each phrase is transcribed with
  no memory of the previous one, losing context that helps disambiguate
  unclear words.
- **`chunking.max_seconds: 5.0`** — a hard cutoff on how long one spoken
  segment can be. German sentences often put the main verb at the very end
  (subordinate clauses), so a long sentence can get cut before that verb is
  even spoken, truncating the transcript.
- **Amplitude-based VAD** — phrase start/end points are picked by volume
  threshold, not a trained speech model. If the boundary lands mid-word, the
  first or last sound gets clipped, which matters more for German's
  consonant clusters and word-final sounds.
- **`vad_filter: False` in the Whisper call itself** — faster-whisper's own
  built-in speech detector is turned off, so there's no second check
  besides the amplitude VAD above.
- **Fixed rejection thresholds** (`no_speech_threshold`, `log_prob_threshold`,
  `compression_ratio_threshold`) — these are the same for every profile. If
  they were tuned around English audio, German phrases with unfamiliar words
  can score as "low confidence" and get silently dropped instead of shown
  with a mistake.

## Try next

1. Run with `--debug-audio-dir` and listen to a few recordings next to their
   transcripts, to see which failure mode is actually happening (wrong words,
   dropped words, or truncated sentences).
2. Bump `asr.model` to `small` or `medium` for the `de-en` profile only.
3. Raise `beam_size` (e.g. 5) and measure the added latency.
4. Raise `chunking.max_seconds` so long sentences aren't cut before the verb.
5. Re-check the rejection thresholds against real German audio once
   debug recordings are available.
