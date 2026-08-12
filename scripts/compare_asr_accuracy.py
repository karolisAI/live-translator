"""Compare ParakeetAsr against the faster-whisper transcripts already recorded
in debug-en-de/ from a real EN meeting run, to get accuracy numbers before
deciding on ParakeetAsr as anything more than an available engine option.

Each debug-en-de/segment-NNNN.wav has a matching segment-NNNN.txt with the
faster-whisper `source=` transcript that was actually used in that run. This
script runs the same audio through ParakeetAsr and reports word error rate
against that recorded transcript (as a comparison baseline, not ground truth).

Usage:
    .venv/Scripts/python.exe scripts/compare_asr_accuracy.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from live_translator.asr import ParakeetAsr
from live_translator.config import AsrSettings

from asr_eval_common import normalize, read_wav, word_error_rate

DEBUG_DIR = Path(__file__).resolve().parents[1] / "debug-en-de"


def read_reference(txt_path: Path) -> str:
    for line in txt_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("source="):
            return line[len("source=") :]
    return ""


def main() -> None:
    settings = AsrSettings(
        engine="parakeet",
        model="models/parakeet/nemotron-3.5-asr-streaming-0.6b-f16.gguf",
        cpu_threads=8,
        source_language="en",
        min_segment_chars=2,
    )
    asr = ParakeetAsr(settings)

    pairs = sorted(DEBUG_DIR.glob("segment-*.wav"))
    total_wer = 0.0
    total_ref_words = 0

    print(f"{'segment':>12} {'wer':>6}  reference / parakeet")
    for wav_path in pairs:
        txt_path = wav_path.with_suffix(".txt")
        if not txt_path.exists():
            continue
        reference = read_reference(txt_path)
        if not reference.strip():
            continue

        samples, sample_rate = read_wav(wav_path)
        result = asr.transcribe(samples, sample_rate)
        wer = word_error_rate(reference, result.text)

        ref_word_count = max(1, len(normalize(reference)))
        total_wer += wer * ref_word_count
        total_ref_words += ref_word_count

        print(f"{wav_path.stem:>12} {wer:>6.2f}  ref: {reference!r}")
        print(f"{'':>12} {'':>6}  hyp: {result.text!r}")

    if total_ref_words:
        print(f"\naggregate WER: {total_wer / total_ref_words:.3f} over {total_ref_words} reference words")


if __name__ == "__main__":
    main()
