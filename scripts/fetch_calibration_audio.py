"""Pull a small open-source audio sample for log_prob_threshold calibration.

Two sources, streamed rather than downloading full corpora, decoded via
soundfile rather than datasets' default torchcodec backend (which pulls in a
full torch install for no benefit here):

- google/fleurs (CC BY 4.0) -- clean, read-aloud speech.
- facebook/voxpopuli (CC0) -- real European Parliament recordings: natural
  reverb, distant mics, many non-native accents. The "less clean" complement
  to fleurs, since neither this project's real meeting audio nor a
  representative noisy sample is available locally.

Usage:
    .venv/Scripts/python.exe scripts/fetch_calibration_audio.py
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

import soundfile as sf
from datasets import Audio, load_dataset

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "eval" / "calibration"
CLIPS_PER_SOURCE = 25

# source -> lang -> (hf_dataset, hf_config, split, text_field)
SOURCES = {
    "fleurs": {
        "en": ("google/fleurs", "en_us", "test", "transcription"),
        "de": ("google/fleurs", "de_de", "test", "transcription"),
    },
    "voxpopuli": {
        "en": ("facebook/voxpopuli", "en", "test", "normalized_text"),
        "de": ("facebook/voxpopuli", "de", "test", "normalized_text"),
    },
}


def fetch(source: str, lang: str, dataset: str, config: str, split: str, text_field: str) -> list[dict]:
    out_dir = OUT_DIR / lang
    out_dir.mkdir(parents=True, exist_ok=True)

    ds = load_dataset(dataset, config, split=split, streaming=True)
    ds = ds.cast_column("audio", Audio(decode=False))

    rows = []
    for i, example in enumerate(ds):
        if i >= CLIPS_PER_SOURCE:
            break
        data, sr = sf.read(io.BytesIO(example["audio"]["bytes"]))
        clip_id = f"{source}-{lang}-{i:03d}"
        wav_path = out_dir / f"{clip_id}.wav"
        sf.write(wav_path, data, sr)
        reference = example[text_field]
        rows.append(
            {
                "clip_id": clip_id,
                "source": source,
                "reference": reference,
                "duration_seconds": f"{len(data) / sr:.2f}",
                "sample_rate": sr,
            }
        )
        print(f"{clip_id}: {len(data) / sr:.2f}s -- {reference[:60]}")
    return rows


def main() -> None:
    fieldnames = ["clip_id", "source", "reference", "duration_seconds", "sample_rate"]
    for lang in ("en", "de"):
        rows = []
        for source, per_lang in SOURCES.items():
            dataset, config, split, text_field = per_lang[lang]
            rows.extend(fetch(source, lang, dataset, config, split, text_field))

        manifest_path = OUT_DIR / lang / "manifest.csv"
        with manifest_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"Wrote {len(rows)} clips + manifest to {manifest_path}")


if __name__ == "__main__":
    main()
