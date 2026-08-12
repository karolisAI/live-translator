"""Test faster-whisper at beam_size=5 (vs. production's beam_size=1) on the
same debug-en-de/ segments, two comparisons:

1. beam=5 whisper vs. the recorded beam=1 transcript -- how much does beam
   size alone change faster-whisper's own output on this data.
2. Parakeet vs. beam=5 whisper -- a fresher baseline than the recorded beam=1
   transcript, in case beam=1 was leaving accuracy on the table that closes
   (or widens) the gap seen in compare_asr_accuracy.py.

Usage:
    .venv/Scripts/python.exe scripts/compare_beam_size.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from live_translator.asr import FasterWhisperAsr, ParakeetAsr
from live_translator.config import AsrSettings

from asr_eval_common import normalize, read_wav, word_error_rate

DEBUG_DIR = Path(__file__).resolve().parents[1] / "debug-en-de"


def read_reference(txt_path: Path) -> str:
    for line in txt_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("source="):
            return line[len("source=") :]
    return ""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    whisper5_settings = AsrSettings(
        engine="faster-whisper", model="base", device="cpu", compute_type="int8",
        cpu_threads=8, source_language="en", beam_size=5,
    )
    parakeet_settings = AsrSettings(
        engine="parakeet", model="models/parakeet/nemotron-3.5-asr-streaming-0.6b-f16.gguf",
        cpu_threads=8, source_language="en",
    )

    whisper5 = FasterWhisperAsr(whisper5_settings)
    parakeet = ParakeetAsr(parakeet_settings)

    total_ref_words_vs_recorded = 0
    total_edits_vs_recorded = 0.0
    total_ref_words_vs_beam5 = 0
    total_edits_vs_beam5 = 0.0
    whisper5_time = 0.0
    n = 0

    print(f"{'segment':>12} {'beam5_s':>8}  beam1(recorded) / beam5 / parakeet")
    for wav_path in sorted(DEBUG_DIR.glob("segment-*.wav")):
        txt_path = wav_path.with_suffix(".txt")
        if not txt_path.exists():
            continue
        recorded = read_reference(txt_path)
        if not recorded.strip():
            continue

        samples, sample_rate = read_wav(wav_path)

        t0 = perf_counter()
        r5 = whisper5.transcribe(samples, sample_rate)
        whisper5_time += perf_counter() - t0

        rp = parakeet.transcribe(samples, sample_rate)

        wer_vs_recorded = word_error_rate(recorded, r5.text)
        wer_vs_beam5 = word_error_rate(r5.text, rp.text)

        ref_words = max(1, len(normalize(recorded)))
        total_edits_vs_recorded += wer_vs_recorded * ref_words
        total_ref_words_vs_recorded += ref_words

        beam5_words = max(1, len(normalize(r5.text)))
        total_edits_vs_beam5 += wer_vs_beam5 * beam5_words
        total_ref_words_vs_beam5 += beam5_words

        n += 1

        print(f"{wav_path.stem:>12} {r5.inference_seconds:>8.2f}")
        print(f"{'':>12} {'':>8}  recorded(beam1): {recorded!r}")
        print(f"{'':>12} {'':>8}  beam5:           {r5.text!r}")
        print(f"{'':>12} {'':>8}  parakeet:        {rp.text!r}")

    print(f"\nbeam5-whisper vs recorded-beam1  WER: {total_edits_vs_recorded / total_ref_words_vs_recorded:.3f} "
          f"over {total_ref_words_vs_recorded} words")
    print(f"parakeet vs beam5-whisper        WER: {total_edits_vs_beam5 / total_ref_words_vs_beam5:.3f} "
          f"over {total_ref_words_vs_beam5} words")
    print(f"\nbeam5 total inference time: {whisper5_time:.2f}s over {n} segments "
          f"({whisper5_time / n * 1000:.0f}ms/segment avg)")


if __name__ == "__main__":
    main()
