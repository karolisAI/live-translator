"""Benchmark story 3 (tts.stream_chunks): buffered vs. streaming TTS playback.

Runs the real bundled Piper binary and a real voice model -- no mocks -- to
compare the current default (render the whole translated phrase, then play)
against tts.stream_chunks (render sentence-sized pieces one at a time,
letting the first one start playing while later ones are still rendering).

Isolates the TTS stage on purpose: story 3 does not touch ASR or MT, so
transcription/translation accuracy and error rate are unaffected by
definition and are not re-measured here (see docs/07-startup-latency-reduction.md).
What this measures is the only thing that changed: time-to-first-audio,
total synthesis time, and whether splitting text into pieces loses or
corrupts anything (audio duration, reconstructed text).

Usage: python scripts/benchmark_streaming_tts.py
Requires the real Piper binary + a German voice model, gitignored and not
checked into the worktree -- run with LIVE_TRANSLATOR_DEV_RUNTIME_ROOT
pointed at a checkout that has tools/piper and models/tts populated (the
main checkout, in this project's setup). See runtime.dev_runtime_root().
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from live_translator.config import AudioSettings, TtsSettings  # noqa: E402
from live_translator.tts.speaker import TtsSpeaker, split_into_speech_chunks  # noqa: E402

REPETITIONS = 5
WARMUP_RUNS = 2

# Translated (German) phrases of increasing shape/length, representative of
# what TranslationEngine.translate() hands to the TTS stage in a live
# meeting -- from a one-word acknowledgement to a multi-sentence phrase.
TEST_PHRASES: list[tuple[str, str]] = [
    ("one_word", "Ja."),
    ("short_sentence", "Guten Morgen, wie geht es Ihnen heute?"),
    ("medium_sentence", "Wir sollten das Budget für nächstes Quartal besprechen."),
    ("two_sentences", "Ich stimme zu. Lass uns das im Detail durchgehen."),
    (
        "three_sentences",
        "Das ist ein guter Punkt. Wir sollten das ganze Team informieren. "
        "Können wir das bis Freitag erledigen?",
    ),
    (
        "long_phrase",
        "Vielen Dank für die ausführliche Erklärung. Ich denke, wir haben jetzt "
        "ein gutes Verständnis der Anforderungen. Als Nächstes sollten wir einen "
        "Zeitplan erstellen und die Verantwortlichkeiten im Team klären. Gibt es "
        "noch offene Fragen, bevor wir das Meeting beenden?",
    ),
]


@dataclass
class PhraseRun:
    phrase_id: str
    text: str
    piece_count: int
    time_to_first_piece: float
    time_to_last_piece: float
    total_audio_seconds: float
    reconstructed_text: str
    failed: bool = False
    error: str | None = None


@dataclass
class Condition:
    name: str
    stream_chunks: bool
    runs: list[PhraseRun] = field(default_factory=list)


def _build_speaker(*, stream_chunks: bool) -> TtsSpeaker:
    settings = TtsSettings(
        engine="piper",
        model_path="models/tts/de_DE-thorsten-medium.onnx",
        piper_exe="tools/piper/piper.exe",
        stream_chunks=stream_chunks,
    )
    speaker = TtsSpeaker(settings, AudioSettings())
    speaker.validate()
    speaker.warm_up()
    return speaker


def _run_phrase(speaker: TtsSpeaker, phrase_id: str, text: str, *, stream_chunks: bool) -> PhraseRun:
    pieces = split_into_speech_chunks(text) if stream_chunks else [text]
    started = time.perf_counter()
    first_piece_done: float | None = None
    rendered = []
    try:
        for piece_text in pieces:
            rendered.append(speaker.render(piece_text))
            if first_piece_done is None:
                first_piece_done = time.perf_counter()
        finished = time.perf_counter()
    except Exception as exc:  # pragma: no cover - reported, not raised
        finished = time.perf_counter()
        return PhraseRun(
            phrase_id=phrase_id,
            text=text,
            piece_count=len(pieces),
            time_to_first_piece=(first_piece_done or finished) - started,
            time_to_last_piece=finished - started,
            total_audio_seconds=0.0,
            reconstructed_text="",
            failed=True,
            error=str(exc),
        )

    total_audio_seconds = sum(
        (len(r.samples) / r.sample_rate if r.samples is not None and r.sample_rate else 0.0)
        for r in rendered
    )
    return PhraseRun(
        phrase_id=phrase_id,
        text=text,
        piece_count=len(pieces),
        time_to_first_piece=(first_piece_done or finished) - started,
        time_to_last_piece=finished - started,
        total_audio_seconds=total_audio_seconds,
        reconstructed_text=" ".join(r.text for r in rendered),
    )


def _summarize(values: list[float]) -> dict[str, float]:
    return {
        "median": statistics.median(values),
        "mean": statistics.mean(values),
        "min": min(values),
        "max": max(values),
    }


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    if not (repo_root / "tools" / "piper" / "piper.exe").exists():
        print(
            f"Piper binary not found under {repo_root}. Copy tools/piper and the "
            "manifest-approved models/tts/de_DE-thorsten-medium.onnx(.json) in first.",
            file=sys.stderr,
        )
        return 1

    conditions = [
        Condition(name="buffered (current default)", stream_chunks=False),
        Condition(name="streaming (tts.stream_chunks)", stream_chunks=True),
    ]

    for condition in conditions:
        print(f"\n=== {condition.name} ===")
        speaker = _build_speaker(stream_chunks=condition.stream_chunks)
        try:
            # Warm-up phrases, discarded, so the first *measured* phrase for
            # each condition isn't paying Piper's one-time model-load cost.
            for _ in range(WARMUP_RUNS):
                _run_phrase(speaker, "warmup", "Das ist ein Aufwärmsatz.", stream_chunks=condition.stream_chunks)

            for phrase_id, text in TEST_PHRASES:
                for rep in range(REPETITIONS):
                    run = _run_phrase(speaker, phrase_id, text, stream_chunks=condition.stream_chunks)
                    condition.runs.append(run)
                    status = "FAIL" if run.failed else "ok"
                    print(
                        f"  [{status}] {phrase_id:16s} rep={rep} pieces={run.piece_count} "
                        f"first={run.time_to_first_piece:.3f}s total={run.time_to_last_piece:.3f}s "
                        f"audio={run.total_audio_seconds:.2f}s"
                        + (f" error={run.error}" if run.failed else "")
                    )
        finally:
            speaker.close()

    # ---- integrity checks: does streaming lose or corrupt anything? ----
    print("\n=== Text reconstruction check (streaming only) ===")
    text_mismatches = 0
    streaming_runs = conditions[1].runs
    by_phrase_text = dict(TEST_PHRASES)
    for run in streaming_runs:
        if run.failed:
            continue
        original_normalized = " ".join(by_phrase_text[run.phrase_id].split())
        reconstructed_normalized = " ".join(run.reconstructed_text.split())
        if original_normalized != reconstructed_normalized:
            text_mismatches += 1
            print(f"  MISMATCH [{run.phrase_id}]: {reconstructed_normalized!r} != {original_normalized!r}")
    if text_mismatches == 0:
        print("  All streaming reconstructions matched the original text exactly.")

    # ---- aggregate report ----
    report: dict = {"phrases": {}, "conditions": {}}
    for condition in conditions:
        failed = [r for r in condition.runs if r.failed]
        ok = [r for r in condition.runs if not r.failed]
        report["conditions"][condition.name] = {
            "stream_chunks": condition.stream_chunks,
            "total_runs": len(condition.runs),
            "failed_runs": len(failed),
            "error_rate": len(failed) / len(condition.runs) if condition.runs else None,
            "time_to_first_piece": _summarize([r.time_to_first_piece for r in ok]) if ok else None,
            "time_to_last_piece": _summarize([r.time_to_last_piece for r in ok]) if ok else None,
            "total_audio_seconds": _summarize([r.total_audio_seconds for r in ok]) if ok else None,
        }
        by_phrase: dict[str, list[PhraseRun]] = {}
        for run in ok:
            by_phrase.setdefault(run.phrase_id, []).append(run)
        for phrase_id, runs in by_phrase.items():
            report["phrases"].setdefault(phrase_id, {})[condition.name] = {
                "piece_count": runs[0].piece_count,
                "time_to_first_piece_median": statistics.median(r.time_to_first_piece for r in runs),
                "time_to_last_piece_median": statistics.median(r.time_to_last_piece for r in runs),
                "total_audio_seconds_median": statistics.median(r.total_audio_seconds for r in runs),
            }
    report["text_reconstruction_mismatches"] = text_mismatches

    out_path = Path(__file__).resolve().parents[1] / "docs" / "streaming-tts-benchmark-results.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote raw results to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
