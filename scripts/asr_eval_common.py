"""Shared helpers for the ASR accuracy comparison scripts in this directory."""

from __future__ import annotations

import re
import wave
from pathlib import Path

import numpy as np


def read_wav(wav_path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(wav_path), "rb") as w:
        sample_rate = w.getframerate()
        raw = w.readframes(w.getnframes())
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return samples, sample_rate


def normalize(text: str) -> list[str]:
    text = re.sub(r"[^\w\s']", " ", text.lower())
    return text.split()


def word_edit_distance(reference: str, hypothesis: str) -> tuple[int, int]:
    """Returns (edit_distance, reference_word_count)."""
    ref = normalize(reference)
    hyp = normalize(hypothesis)
    if not ref:
        return (0 if not hyp else len(hyp)), 0

    d = [[0] * (len(hyp) + 1) for _ in range(len(ref) + 1)]
    for i in range(len(ref) + 1):
        d[i][0] = i
    for j in range(len(hyp) + 1):
        d[0][j] = j
    for i in range(1, len(ref) + 1):
        for j in range(1, len(hyp) + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
    return d[len(ref)][len(hyp)], len(ref)


def word_error_rate(reference: str, hypothesis: str) -> float:
    edits, ref_len = word_edit_distance(reference, hypothesis)
    if ref_len == 0:
        return 0.0 if edits == 0 else 1.0
    return edits / ref_len
