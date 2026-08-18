"""Measure whether avg_logprob actually separates correct from incorrect
transcripts on this model, using the FLEURS sample pulled by
fetch_calibration_audio.py.

The public ParakeetRecognizer.transcribe() only reports avg_logprob when it's
already the reason for rejection -- an accepted transcript's confidence is
computed internally and discarded. Calibration needs it for every clip
regardless of outcome, so this script replicates transcribe()'s pipeline
(decode -> empty recovery -> gap recovery) via the recognizer's internal
methods instead of going through the public API, and computes avg_logprob
itself the same way _rejection_reason does.

Usage:
    .venv/Scripts/python.exe scripts/calibrate_log_prob_threshold.py
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from live_translator.asr.recognizer import ParakeetRecognizer, _as_samples

REPO = Path(__file__).resolve().parents[1]
CAL_DIR = REPO / "eval" / "calibration"
LANGUAGES = {"en": "en", "de": "de"}


def normalize(text: str) -> list[str]:
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    return text.split()


def word_error_rate(reference: str, hypothesis: str) -> float:
    ref, hyp = normalize(reference), normalize(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0

    # Standard Levenshtein edit distance over words.
    d = [[0] * (len(hyp) + 1) for _ in range(len(ref) + 1)]
    for i in range(len(ref) + 1):
        d[i][0] = i
    for j in range(len(hyp) + 1):
        d[0][j] = j
    for i in range(1, len(ref) + 1):
        for j in range(1, len(hyp) + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
    return d[len(ref)][len(hyp)] / len(ref)


def decode_with_confidence(recognizer: ParakeetRecognizer, audio, sample_rate: int, language: str):
    """Replicates transcribe()'s pipeline but returns (text, avg_logprob)
    for every clip, including ones the public API would accept without ever
    surfacing their confidence."""
    options = {"language": language}
    decoded = recognizer._decode(audio, sample_rate, options)

    if not decoded.text and recognizer._worth_recovering(audio, sample_rate):
        _name, decoded = recognizer._recover(audio, sample_rate, options)

    samples = _as_samples(audio)
    duration_seconds = len(audio) / float(sample_rate)
    if decoded.text and samples is not None:
        decoded, _extra = recognizer._cover_gaps(
            samples, sample_rate, options, decoded, duration_seconds
        )

    scores = [float(v) for v in decoded.logprobs] if decoded.logprobs is not None else []
    avg_logprob = sum(scores) / len(scores) if scores else None
    return decoded.text, avg_logprob


def run_language(recognizer: ParakeetRecognizer, lang: str) -> list[dict]:
    lang_dir = CAL_DIR / lang
    manifest_path = lang_dir / "manifest.csv"
    with manifest_path.open(encoding="utf-8") as f:
        clips = list(csv.DictReader(f))

    rows = []
    for clip in clips:
        wav_path = lang_dir / f"{clip['clip_id']}.wav"
        audio, sr = sf.read(wav_path, dtype="float32")

        text, avg_logprob = decode_with_confidence(recognizer, audio, sr, LANGUAGES[lang])
        wer = word_error_rate(clip["reference"], text)

        rows.append(
            {
                "clip_id": clip["clip_id"],
                "language": lang,
                "source": clip.get("source", ""),
                "wer": f"{wer:.3f}",
                "avg_logprob": f"{avg_logprob:.4f}" if avg_logprob is not None else "",
                "reference": clip["reference"],
                "hypothesis": text,
            }
        )
        print(f"{clip['clip_id']}: wer={wer:.3f} avg_logprob={avg_logprob} -- {text[:60]!r}")
    return rows


def main() -> None:
    recognizer = ParakeetRecognizer(cpu_threads=8)

    all_rows: list[dict] = []
    for lang in LANGUAGES:
        all_rows.extend(run_language(recognizer, lang))

    out_path = CAL_DIR / "log_prob_calibration.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["clip_id", "language", "source", "wer", "avg_logprob", "reference", "hypothesis"],
        )
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"\nWrote {len(all_rows)} rows to {out_path}")


if __name__ == "__main__":
    main()
