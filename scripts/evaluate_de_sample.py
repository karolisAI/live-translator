"""Whole-clip DE accuracy check for ParakeetAsr against a user-supplied
reference transcript in eval/de-en/.

Unlike compare_asr_accuracy.py (pre-segmented phrase clips matching the
production VAD pipeline), this transcribes one long clip in a single offline
call and compares against one long reference transcript. It answers "is DE
transcription quality reasonable at all", not "does it behave correctly at
production phrase boundaries" — a real VAD-segmented follow-up is a separate,
more production-faithful test once this looks good.

Usage:
    .venv/Scripts/python.exe scripts/evaluate_de_sample.py eval/de-en/sample1
    (expects sample1.wav and sample1.txt next to each other)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from live_translator.asr import ParakeetAsr
from live_translator.config import AsrSettings

from asr_eval_common import normalize, read_wav, word_error_rate


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

    settings = AsrSettings(
        engine="parakeet",
        model="models/parakeet/nemotron-3.5-asr-streaming-0.6b-f16.gguf",
        cpu_threads=8,
        source_language="de",
        min_segment_chars=2,
    )
    asr = ParakeetAsr(settings)

    samples, sample_rate = read_wav(wav_path)
    duration_s = len(samples) / sample_rate
    print(f"transcribing {wav_path.name} ({duration_s:.1f}s)...")

    result = asr.transcribe(samples, sample_rate)
    wer = word_error_rate(reference, result.text)

    print(f"\ninference time: {result.inference_seconds:.1f}s for {duration_s:.1f}s audio "
          f"(realtime factor {result.inference_seconds / duration_s:.3f})")
    print(f"reference word count: {len(normalize(reference))}")
    print(f"WER: {wer:.3f}\n")
    print("--- reference ---")
    print(reference)
    print("\n--- parakeet hypothesis ---")
    print(result.text)

    hyp_path = stem.with_name(stem.name + ".parakeet-hyp.txt")
    hyp_path.write_text(result.text, encoding="utf-8")
    print(f"\nhypothesis written to {hyp_path}")


if __name__ == "__main__":
    main()
