"""Measure runtime asset verification cost without loading meeting models."""

from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path
from typing import Callable

from live_translator.asset_manifest import (
    load_manifest,
    verify_manifest,
    verify_manifest_root,
)


def _measure(action: Callable[[], object], repetitions: int) -> list[float]:
    values: list[float] = []
    for _ in range(repetitions):
        started = time.perf_counter()
        action()
        values.append(time.perf_counter() - started)
    return values


def _verify_meeting_profile(manifest, root: Path, argos_pair: str) -> None:
    verify_manifest_root(
        manifest,
        "models/asr/parakeet-tdt-0.6b-v3",
        root / "models" / "asr" / "parakeet-tdt-0.6b-v3",
    )
    verify_manifest_root(
        manifest,
        f"models/argos/packages/{argos_pair}",
        root / "models" / "argos" / "packages" / argos_pair,
    )
    verify_manifest(
        manifest,
        root,
        components={"piper-runtime", "piper-voice"},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--repetitions", type=int, default=5)
    args = parser.parse_args()
    if args.repetitions <= 0:
        parser.error("--repetitions must be positive")

    root = args.root.resolve()
    manifest = load_manifest(root / "packaging" / "runtime-assets.manifest.json")
    cases: tuple[tuple[str, Callable[[], object]], ...] = (
        (
            "Piper runtime + voices",
            lambda: verify_manifest(
                manifest,
                root,
                components={"piper-runtime", "piper-voice"},
            ),
        ),
        (
            "Parakeet int8",
            lambda: verify_manifest_root(
                manifest,
                "models/asr/parakeet-tdt-0.6b-v3",
                root / "models" / "asr" / "parakeet-tdt-0.6b-v3",
            ),
        ),
        (
            "Argos en_de",
            lambda: verify_manifest_root(
                manifest,
                "models/argos/packages/en_de",
                root / "models" / "argos" / "packages" / "en_de",
            ),
        ),
        (
            "Argos de_en",
            lambda: verify_manifest_root(
                manifest,
                "models/argos/packages/de_en",
                root / "models" / "argos" / "packages" / "de_en",
            ),
        ),
        (
            "Packaged build assets",
            lambda: verify_manifest(
                manifest,
                root,
                components={"piper-runtime", "piper-voice", "argos"},
            ),
        ),
        (
            "Meeting startup en_de",
            lambda: _verify_meeting_profile(manifest, root, "en_de"),
        ),
        (
            "Meeting startup de_en",
            lambda: _verify_meeting_profile(manifest, root, "de_en"),
        ),
    )

    print(f"Runtime asset integrity benchmark ({args.repetitions} repetitions)")
    for name, action in cases:
        values = _measure(action, args.repetitions)
        runs = ", ".join(f"{value:.3f}" for value in values)
        print(
            f"{name}: runs=[{runs}] median={statistics.median(values):.3f}s "
            f"mean={statistics.mean(values):.3f}s"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
