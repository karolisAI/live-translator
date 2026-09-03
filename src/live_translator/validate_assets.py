"""Command-line validation of assets before Windows packaging."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from live_translator.asset_manifest import load_manifest, verify_manifest
from live_translator.errors import AssetIntegrityError

PACKAGED_COMPONENTS = ("piper-runtime", "piper-voice", "argos")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify runtime assets against the approved SHA-256 manifest."
    )
    parser.add_argument("--root", type=Path, required=True, help="runtime asset root")
    parser.add_argument("--manifest", type=Path, required=True, help="approved manifest JSON")
    parser.add_argument(
        "--component",
        action="append",
        dest="components",
        help="component to verify; repeat as needed",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    components = tuple(args.components or PACKAGED_COMPONENTS)
    try:
        manifest = load_manifest(args.manifest)
        verified = verify_manifest(manifest, args.root, components=components)
    except (AssetIntegrityError, OSError, ValueError) as exc:
        print(f"Runtime asset validation failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"Runtime asset validation passed: {len(verified)} files "
        f"({', '.join(components)})."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
