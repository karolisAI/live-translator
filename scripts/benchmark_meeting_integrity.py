"""Confirm integrity hashing is startup-only and measure warmed phrase work."""

from __future__ import annotations

import statistics
import time
from unittest.mock import patch

import numpy as np

from live_translator.asr.parakeet_engine import ParakeetAsr
from live_translator.config import AsrSettings, AudioSettings, TranslationSettings, TtsSettings
from live_translator.mt.translator import TranslationEngine
from live_translator.tts.speaker import TtsSpeaker


def _seconds(action, repetitions: int) -> list[float]:
    values = []
    for _ in range(repetitions):
        started = time.perf_counter()
        action()
        values.append(time.perf_counter() - started)
    return values


def _report(name: str, values: list[float]) -> None:
    print(
        f"{name}: median={statistics.median(values):.3f}s "
        f"runs=[{', '.join(f'{value:.3f}' for value in values)}]"
    )


def main() -> int:
    translation = TranslationEngine(
        TranslationSettings(engine="argos", source_language="en", target_language="de")
    )
    translation.prepare()
    with patch(
        "live_translator.mt.translator.verify_manifest_root",
        side_effect=AssertionError("Argos integrity was recalculated during a phrase"),
    ):
        _report(
            "Argos warmed phrase",
            _seconds(lambda: translation.translate("This is a security test."), 5),
        )

    speaker = TtsSpeaker(
        TtsSettings(
            engine="piper",
            model_path="models/tts/de_DE-thorsten-medium.onnx",
            piper_exe="tools/piper/piper.exe",
        ),
        AudioSettings(),
    )
    speaker.validate()
    with patch(
        "live_translator.tts.speaker.verify_manifest",
        side_effect=AssertionError("Piper integrity was recalculated during a phrase"),
    ):
        _report("Piper warmed render", _seconds(lambda: speaker.render("Sicherheitstest."), 3))

    asr = ParakeetAsr(AsrSettings(source_language="en"))
    silence = np.zeros(16000, dtype=np.float32)
    with patch(
        "live_translator.asr.model_store.verify_manifest_root",
        side_effect=AssertionError("Parakeet integrity was recalculated during a phrase"),
    ):
        _report("Parakeet 1s inference", _seconds(lambda: asr.transcribe(silence, 16000), 3))

    print("No integrity hashes were recalculated during phrase processing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
