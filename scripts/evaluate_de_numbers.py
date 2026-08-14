"""DE mirror of evaluate_en_numbers.py -- same 30 numbers as the live DE
benchmark, same production config (q8_0, 8 threads), to isolate whether that
test's 20.8% empty-output rate was caused by the f16/4-thread config it
actually used, or is specific to German content regardless of config.

Usage:
    .venv/Scripts/python.exe scripts/evaluate_de_numbers.py
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
VOICE = REPO / "models" / "tts" / "de_DE-thorsten-medium.onnx"
OUT_DIR = REPO / "eval" / "de-en" / "numbers-diagnostic"

# case_id, category, German number phrase (source_reference from the live DE benchmark)
CASES = [
    ("number-001", "number_1_digit", "Sieben"),
    ("number-002", "number_2_digits", "Zwölf"),
    ("number-003", "number_2_digits", "Achtzehn"),
    ("number-004", "number_2_digits", "Vierundzwanzig"),
    ("number-005", "number_2_digits", "Dreiunddreißig"),
    ("number-006", "number_2_digits", "Siebenundvierzig"),
    ("number-007", "number_2_digits", "Neunundfünfzig"),
    ("number-008", "number_2_digits", "Einundsechzig"),
    ("number-009", "number_2_digits", "Achtundsiebzig"),
    ("number-010", "number_2_digits", "Sechsundachtzig"),
    ("number-011", "number_2_digits", "Neunundneunzig"),
    ("number-012", "number_3_digits", "Einhundertfünf"),
    ("number-013", "number_3_digits", "Zweihundertzwölf"),
    ("number-014", "number_3_digits", "Fünfhundertvierzig"),
    ("number-015", "number_4_digits", "Eintausend"),
    ("number-016", "number_4_digits", "Zweitausendeinundvierzig"),
    ("number-017", "number_4_digits", "Achttausendsiebenhundertvierunddreißig"),
    ("number-018", "number_4_digits", "Siebentausendsechshundertzweiundfünfzig"),
    ("number-019", "number_4_digits", "Dreitausendneunhundertachtzehn"),
    ("number-020", "number_4_digits", "Sechstausendzweihundertdreiundvierzig"),
    ("number-021", "number_4_digits", "Viertausendfünfhundertneunundsechzig"),
    ("number-022", "number_4_digits", "Neuntausendeinhundertsiebenundzwanzig"),
    ("number-023", "number_4_digits", "Fünftausendachthundertvierundsechzig"),
    ("number-024", "number_4_digits", "Eintausendsiebenhundertzweiundneunzig"),
    ("number-025", "number_4_digits", "Achttausenddreihundertfünfzehn"),
    ("number-026", "number_4_digits", "Sechstausendneunhundertachtundvierzig"),
    ("number-027", "number_4_digits", "Zweitausendvierhundertsechsundachtzig"),
    ("number-028", "number_4_digits", "Siebentausendeinhundertdreiundfünfzig"),
    ("number-029", "number_4_digits", "Viertausendachthundertzweiundzwanzig"),
    ("number-030", "number_4_digits", "Neuntausendfünfhundertelf"),
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
        source_language="de",
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
