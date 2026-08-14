"""EN mirror of the live DE numbers benchmark
(20260813-070153_numbers-parakeet-f16-4t_meeting-benchmark.csv) -- same 30
numbers (the DE test's own target_reference English phrasing), same
categories, synthesized via Piper and transcribed with ParakeetAsr at the
CURRENT production config (q8_0, 8 threads -- matching en-de.yaml, not the
f16/4-thread config that benchmark actually used).

Checks specifically for the length-sensitivity / empty-output pattern found
in the DE numbers test (empty results skewed to shorter clips, mean 1.71s vs
2.35s for successful ones) -- does that reproduce in English too.

Usage:
    .venv/Scripts/python.exe scripts/evaluate_en_numbers.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from live_translator.asr import ParakeetAsr
from live_translator.config import AsrSettings

from asr_eval_common import normalize, read_wav, word_error_rate

REPO = Path(__file__).resolve().parents[1]
PIPER = REPO / "tools" / "piper" / "piper.exe"
VOICE = REPO / "models" / "tts" / "en_US-hfc_male-medium.onnx"
OUT_DIR = REPO / "eval" / "en-de" / "numbers-diagnostic"

# case_id, category, English number phrase (== the DE test's target_reference)
CASES = [
    ("number-001", "number_1_digit", "Seven"),
    ("number-002", "number_2_digits", "Twelve"),
    ("number-003", "number_2_digits", "Eighteen"),
    ("number-004", "number_2_digits", "Twenty-four"),
    ("number-005", "number_2_digits", "Thirty-three"),
    ("number-006", "number_2_digits", "Forty-seven"),
    ("number-007", "number_2_digits", "Fifty-nine"),
    ("number-008", "number_2_digits", "Sixty-one"),
    ("number-009", "number_2_digits", "Seventy-eight"),
    ("number-010", "number_2_digits", "Eighty-six"),
    ("number-011", "number_2_digits", "Ninety-nine"),
    ("number-012", "number_3_digits", "One hundred five"),
    ("number-013", "number_3_digits", "Two hundred twelve"),
    ("number-014", "number_3_digits", "Five hundred forty"),
    ("number-015", "number_4_digits", "One thousand"),
    ("number-016", "number_4_digits", "Two thousand forty-one"),
    ("number-017", "number_4_digits", "Eight thousand seven hundred thirty-four"),
    ("number-018", "number_4_digits", "Seven thousand six hundred fifty-two"),
    ("number-019", "number_4_digits", "Three thousand nine hundred eighteen"),
    ("number-020", "number_4_digits", "Six thousand two hundred forty-three"),
    ("number-021", "number_4_digits", "Four thousand five hundred sixty-nine"),
    ("number-022", "number_4_digits", "Nine thousand one hundred twenty-seven"),
    ("number-023", "number_4_digits", "Five thousand eight hundred sixty-four"),
    ("number-024", "number_4_digits", "One thousand seven hundred ninety-two"),
    ("number-025", "number_4_digits", "Eight thousand three hundred fifteen"),
    ("number-026", "number_4_digits", "Six thousand nine hundred forty-eight"),
    ("number-027", "number_4_digits", "Two thousand four hundred eighty-six"),
    ("number-028", "number_4_digits", "Seven thousand one hundred fifty-three"),
    ("number-029", "number_4_digits", "Four thousand eight hundred twenty-two"),
    ("number-030", "number_4_digits", "Nine thousand five hundred eleven"),
]


def synthesize(text: str, out_wav: Path) -> None:
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [str(PIPER), "--model", str(VOICE), "--output_file", str(out_wav)],
        input=text,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"piper failed: {proc.stderr}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    settings = AsrSettings(
        engine="parakeet",
        model="models/parakeet/nemotron-3.5-asr-streaming-0.6b-q8_0.gguf",
        cpu_threads=8,
        source_language="en",
        min_segment_chars=2,
    )
    asr = ParakeetAsr(settings)

    empty_durations = []
    nonempty_durations = []
    total_edits = 0.0
    total_words = 0
    empty_count = 0

    print(f"{'case':>12} {'dur_s':>6} {'text':<45} status")
    for case_id, category, phrase in CASES:
        wav_path = OUT_DIR / f"{case_id}.wav"
        synthesize(phrase, wav_path)
        samples, sr = read_wav(str(wav_path))
        dur = len(samples) / sr

        result = asr.transcribe(samples, sr)
        text = result.text.strip()

        if not text:
            empty_count += 1
            empty_durations.append(dur)
            print(f"{case_id:>12} {dur:>6.2f} {'(empty)':<45} EMPTY")
        else:
            nonempty_durations.append(dur)
            wer = word_error_rate(phrase, text)
            words = max(1, len(normalize(phrase)))
            total_edits += wer * words
            total_words += words
            status = "OK" if wer == 0 else f"wer={wer:.2f}"
            print(f"{case_id:>12} {dur:>6.2f} {text[:45]:<45} {status}")

    print(f"\nempty results: {empty_count}/{len(CASES)}")
    if empty_durations:
        print(f"  empty clip durations:    min={min(empty_durations):.2f}s max={max(empty_durations):.2f}s "
              f"mean={sum(empty_durations)/len(empty_durations):.2f}s")
    if nonempty_durations:
        print(f"  non-empty clip durations: min={min(nonempty_durations):.2f}s max={max(nonempty_durations):.2f}s "
              f"mean={sum(nonempty_durations)/len(nonempty_durations):.2f}s")
    if total_words:
        print(f"\nWER over non-empty results: {total_edits/total_words:.3f} ({total_words} reference words)")


if __name__ == "__main__":
    main()
