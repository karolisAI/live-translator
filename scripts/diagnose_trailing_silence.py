"""Reproduce the parakeet-live tail-truncation bug reported in
parakeet-engine-comparison-en.md, tracing it to the known NVIDIA-NeMo/Speech
issue #15757: log-mel normalization computed over the WHOLE buffer means
trailing silence in a VAD-committed segment (e.g. a fixed 5.0s max_seconds
cutoff that lands after speech has already ended) skews the feature
representation of the speech itself, causing empty or truncated decode.

Synthesizes a phrase via Piper, then transcribes it with increasing amounts
of trailing silence appended, to see at what point (if any) onnx-asr's
nemo-parakeet-tdt-0.6b-v3 breaks -- and whether trimming the silence back off
before inference recovers it.

Usage:
    .venv/Scripts/python.exe scripts/diagnose_trailing_silence.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import onnx_asr

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from asr_eval_common import read_wav  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PIPER = REPO / "tools" / "piper" / "piper.exe"
VOICE_EN = REPO / "models" / "tts" / "en_US-hfc_male-medium.onnx"
OUT_DIR = REPO / "eval" / "en-de" / "trailing-silence-diagnostic"

TEXT = (
    "Circus performers and things they do don't look at all happy to me "
    "even with the big painted smile they wear on stage every single night."
)

SILENCE_TAILS_MS = [0, 100, 200, 300, 400, 600, 900, 1300, 1800]


def synthesize(text: str, out_wav: Path) -> None:
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [str(PIPER), "--model", str(VOICE_EN), "--output_file", str(out_wav)],
        input=text,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"piper failed: {proc.stderr}")


def trim_trailing_silence(samples: np.ndarray, sample_rate: int, threshold: float = 0.01) -> np.ndarray:
    """Simplest possible fix for the NeMo issue: drop trailing near-silence
    so the buffer handed to the model ends where speech actually ends."""
    frame = int(sample_rate * 0.02)  # 20ms frames
    n_frames = len(samples) // frame
    last_active = 0
    for i in range(n_frames):
        chunk = samples[i * frame : (i + 1) * frame]
        if np.sqrt(np.mean(chunk**2)) > threshold:
            last_active = i
    end = min(len(samples), (last_active + 1) * frame + int(sample_rate * 0.05))  # +50ms margin
    return samples[:end]


def main() -> None:
    base_wav = OUT_DIR / "base.wav"
    synthesize(TEXT, base_wav)
    base_samples, sr = read_wav(str(base_wav))
    print(f"base clip: {len(base_samples) / sr:.2f}s, text: {TEXT!r}\n")

    model = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3", quantization="int8").with_timestamps()

    print(f"{'tail_ms':>8} {'buf_s':>7}  transcript")
    for tail_ms in SILENCE_TAILS_MS:
        tail = np.zeros(int(sr * tail_ms / 1000), dtype=np.float32)
        padded = np.concatenate([base_samples, tail]).astype(np.float32)
        result = model.recognize(padded, sample_rate=sr, language="en")
        print(f"{tail_ms:>8} {len(padded) / sr:>7.2f}  {result.text.strip()!r}")

    print("\n--- with the trim-before-inference fix applied ---")
    for tail_ms in SILENCE_TAILS_MS:
        tail = np.zeros(int(sr * tail_ms / 1000), dtype=np.float32)
        padded = np.concatenate([base_samples, tail]).astype(np.float32)
        trimmed = trim_trailing_silence(padded, sr)
        result = model.recognize(trimmed, sample_rate=sr, language="en")
        print(f"{tail_ms:>8} {len(trimmed) / sr:>7.2f}  {result.text.strip()!r}")


if __name__ == "__main__":
    main()
