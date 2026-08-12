"""Export every debug-en-de/ segment where ParakeetAsr and the recorded
faster-whisper transcript diverge by at least MIN_EDITS words, for manual
audio review (not just the handful already called out in conversation).

Each debug-en-de/segment-NNNN.wav is already a standalone per-segment clip
(that's how the live pipeline writes debug output), so no audio cutting is
needed -- this just re-scores every segment and copies the disputed ones.

Usage:
    .venv/Scripts/python.exe scripts/export_disputed_segments.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from live_translator.asr import ParakeetAsr
from live_translator.config import AsrSettings

from asr_eval_common import normalize, read_wav, word_edit_distance

DEBUG_DIR = Path(__file__).resolve().parents[1] / "debug-en-de"
OUT_DIR = Path(__file__).resolve().parents[1] / "eval" / "en-de-disputed"
MIN_EDITS = 2  # at least 2 word-level edits (insert/delete/substitute) to count as "diverge"


def read_reference(txt_path: Path) -> str:
    for line in txt_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("source="):
            return line[len("source=") :]
    return ""


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    settings = AsrSettings(
        engine="parakeet",
        model="models/parakeet/nemotron-3.5-asr-streaming-0.6b-f16.gguf",
        cpu_threads=8,
        source_language="en",
        min_segment_chars=2,
    )
    asr = ParakeetAsr(settings)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_lines = [f"disputed segments: >= {MIN_EDITS} word-level edits between faster-whisper (ref) and parakeet (hyp)\n"]

    disputed = []
    for wav_path in sorted(DEBUG_DIR.glob("segment-*.wav")):
        txt_path = wav_path.with_suffix(".txt")
        if not txt_path.exists():
            continue
        reference = read_reference(txt_path)
        if not reference.strip():
            continue

        samples, sample_rate = read_wav(wav_path)
        result = asr.transcribe(samples, sample_rate)
        edits, ref_words = word_edit_distance(reference, result.text)
        wer = edits / ref_words if ref_words else 0.0

        print(f"{wav_path.stem}  edits={edits:2d}  wer={wer:5.2f}  ref={reference!r}  hyp={result.text!r}")

        if edits >= MIN_EDITS:
            disputed.append((wav_path.stem, edits, wer, reference, result.text))

    print(f"\n{len(disputed)} segments meet the >= {MIN_EDITS}-edit threshold, exporting to {OUT_DIR}")

    for stem, edits, wer, reference, hypothesis in disputed:
        src_wav = DEBUG_DIR / f"{stem}.wav"
        dst_wav = OUT_DIR / f"{stem}.wav"
        shutil.copy2(src_wav, dst_wav)
        manifest_lines.append(
            f"{stem}: edits={edits} wer={wer:.2f}\n  faster-whisper: {reference}\n  parakeet:       {hypothesis}\n"
        )

    manifest_path = OUT_DIR / "manifest.txt"
    manifest_path.write_text("\n".join(manifest_lines), encoding="utf-8")
    print(f"manifest written to {manifest_path}")


if __name__ == "__main__":
    main()
