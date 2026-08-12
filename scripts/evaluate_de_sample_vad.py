"""VAD-segmented DE accuracy check: same sample1.wav/.txt as
evaluate_de_sample.py, but chunked through the same frame-based state machine
as live_translator.audio.vad.record_speech_segment (same thresholds, same
formulas — reimplemented here as a pure function over a numpy array instead of
a live sounddevice stream, since record_speech_segment is wired directly to
sd.InputStream). This is the production-faithful comparison: does chunking
audio into short VAD-committed phrases (<=5s, matching the app's real
behavior) change accuracy versus the single whole-clip offline decode in
evaluate_de_sample.py.

Usage:
    .venv/Scripts/python.exe scripts/evaluate_de_sample_vad.py eval/de-en/sample1
"""

from __future__ import annotations

import sys
from math import ceil
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from live_translator.asr import ParakeetAsr
from live_translator.config import AsrSettings, ChunkingSettings

from asr_eval_common import normalize, read_wav, word_error_rate


def segment_offline(samples: np.ndarray, sample_rate: int, chunking: ChunkingSettings) -> list[np.ndarray]:
    """Replays live_translator.audio.vad.record_speech_segment's frame state
    machine over a pre-loaded array instead of a live InputStream. Same
    thresholds/formulas; the only addition is padding the tail with silence
    so a final in-progress phrase still commits instead of hanging forever
    the way a live stream ending abruptly never would in production."""
    frame_samples = max(1, int(sample_rate * chunking.frame_ms / 1000.0))
    silence_frames = max(1, ceil(chunking.silence_ms / chunking.frame_ms))
    min_speech_frames = max(1, ceil(chunking.min_speech_ms / chunking.frame_ms))
    min_segment_frames = max(1, ceil(chunking.min_segment_seconds * 1000.0 / chunking.frame_ms))
    pre_roll_frames = max(0, ceil(chunking.pre_roll_ms / chunking.frame_ms))
    max_frames = max(1, ceil(chunking.max_seconds * 1000.0 / chunking.frame_ms))

    pad = np.zeros(frame_samples * (silence_frames + 1), dtype=np.float32)
    padded = np.concatenate([samples, pad])

    segments: list[np.ndarray] = []
    from collections import deque

    pre_roll: deque = deque(maxlen=pre_roll_frames)
    frames: list[np.ndarray] = []
    speech_started = False
    speech_frames = 0
    silence_after_speech = 0
    noise_floor = 0.0

    for start in range(0, len(padded), frame_samples):
        frame = padded[start : start + frame_samples]
        if len(frame) < frame_samples:
            break

        rms = float(np.sqrt(np.mean(np.square(frame))))
        peak = float(np.max(np.abs(frame)))
        adaptive_threshold = (
            min(noise_floor * chunking.noise_multiplier, chunking.rms_threshold * 2.0)
            if noise_floor > 0.0
            else 0.0
        )
        threshold = max(chunking.rms_threshold, adaptive_threshold)
        is_speech = rms >= threshold or peak >= chunking.peak_threshold

        if not speech_started:
            if not is_speech:
                pre_roll.append(frame)
                noise_floor = rms if noise_floor <= 0.0 else (0.98 * noise_floor + 0.02 * rms)
                continue
            speech_started = True
            frames.extend(item.copy() for item in pre_roll)
            frames.append(frame.copy())
            speech_frames = 1
            silence_after_speech = 0
            continue

        frames.append(frame)
        if is_speech:
            speech_frames += 1
            silence_after_speech = 0
        else:
            silence_after_speech += 1

        if silence_after_speech >= silence_frames and speech_frames < min_speech_frames:
            recent_silence = frames[-pre_roll_frames:] if pre_roll_frames > 0 else []
            frames = []
            pre_roll.clear()
            pre_roll.extend(item.copy() for item in recent_silence)
            speech_started = False
            speech_frames = 0
            silence_after_speech = 0
            noise_floor = rms if noise_floor <= 0.0 else (0.98 * noise_floor + 0.02 * rms)
            continue

        committed = len(frames) >= max_frames or (
            speech_frames >= min_speech_frames
            and silence_after_speech >= silence_frames
            and len(frames) >= min_segment_frames
        )
        if committed:
            segments.append(np.concatenate(frames).astype(np.float32))
            frames = []
            pre_roll.clear()
            speech_started = False
            speech_frames = 0
            silence_after_speech = 0
            noise_floor = 0.0

    return segments


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <path-stem-without-extension>")
        sys.exit(1)

    stem = Path(sys.argv[1])
    wav_path = stem.with_suffix(".wav")
    txt_path = stem.with_suffix(".txt")

    reference = " ".join(
        line.strip() for line in txt_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()
    )

    samples, sample_rate = read_wav(wav_path)
    chunking = ChunkingSettings()  # same defaults as app.example.yaml
    segments = segment_offline(samples, sample_rate, chunking)
    print(f"VAD produced {len(segments)} segments from {len(samples) / sample_rate:.1f}s of audio")

    settings = AsrSettings(
        engine="parakeet",
        model="models/parakeet/nemotron-3.5-asr-streaming-0.6b-f16.gguf",
        cpu_threads=8,
        source_language="de",
        min_segment_chars=2,
    )
    asr = ParakeetAsr(settings)

    hyp_parts = []
    for i, seg in enumerate(segments, start=1):
        result = asr.transcribe(seg, sample_rate)
        dur = len(seg) / sample_rate
        print(f"[{i:02d}] {dur:5.2f}s  {result.text!r}")
        if result.text:
            hyp_parts.append(result.text)

    hypothesis = " ".join(hyp_parts)
    wer = word_error_rate(reference, hypothesis)
    print(f"\nreference word count: {len(normalize(reference))}")
    print(f"VAD-segmented WER: {wer:.3f}")

    hyp_path = stem.with_name(stem.name + ".parakeet-vad-hyp.txt")
    hyp_path.write_text(hypothesis, encoding="utf-8")
    print(f"hypothesis written to {hyp_path}")


if __name__ == "__main__":
    main()
