"""Perform structural validation of the generated CycloneDX SBOM."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def validate_sbom(path: Path) -> int:
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Invalid SBOM '{path}': {exc}", file=sys.stderr)
        return 1
    if not isinstance(raw, dict) or raw.get("bomFormat") != "CycloneDX":
        print("SBOM must use the CycloneDX format.", file=sys.stderr)
        return 1
    if raw.get("specVersion") != "1.5":
        print("SBOM must use CycloneDX specification 1.5.", file=sys.stderr)
        return 1
    components = raw.get("components")
    if not isinstance(components, list) or not components:
        print("SBOM must contain at least one component.", file=sys.stderr)
        return 1
    for index, component in enumerate(components):
        if not isinstance(component, dict):
            print(f"SBOM component {index} is not an object.", file=sys.stderr)
            return 1
        for field in ("name", "version"):
            if not isinstance(component.get(field), str) or not component[field].strip():
                print(f"SBOM component {index} has no {field}.", file=sys.stderr)
                return 1
    print(f"Valid CycloneDX 1.5 SBOM with {len(components)} components.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sbom", type=Path)
    args = parser.parse_args(argv)
    return validate_sbom(args.sbom)


if __name__ == "__main__":
    raise SystemExit(main())
