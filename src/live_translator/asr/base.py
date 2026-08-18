from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class TranscriptResult:
    text: str
    language: str | None
    duration_seconds: float
    inference_seconds: float
    rejected_segments: int = 0
    rejection_reasons: tuple[str, ...] = ()
    low_confidence: bool = False


class AsrEngine(Protocol):
    def transcribe(self, audio: Any, sample_rate: int) -> TranscriptResult: ...
