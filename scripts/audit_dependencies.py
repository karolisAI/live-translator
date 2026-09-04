"""Run pip-audit with strictly validated, time-limited exceptions."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any


class PolicyError(ValueError):
    """The vulnerability exception policy is invalid or expired."""


def load_active_exceptions(path: Path, *, today: date | None = None) -> list[str]:
    """Return active vulnerability IDs after validating the complete policy."""

    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"Cannot read vulnerability policy '{path}': {exc}") from exc

    if not isinstance(raw, dict) or set(raw) != {"schema_version", "policy", "exceptions"}:
        raise PolicyError("Policy must contain only schema_version, policy and exceptions.")
    if raw["schema_version"] != 1:
        raise PolicyError("Unsupported vulnerability policy schema version.")
    if raw["policy"] != "fail-on-any-known-vulnerability":
        raise PolicyError("Policy must fail on every known vulnerability by default.")
    if not isinstance(raw["exceptions"], list):
        raise PolicyError("Policy exceptions must be an array.")

    current = today or date.today()
    active: list[str] = []
    required = {"id", "package", "justification", "expires"}
    for index, item in enumerate(raw["exceptions"]):
        label = f"exceptions[{index}]"
        if not isinstance(item, dict) or set(item) != required:
            raise PolicyError(f"{label} must contain only {sorted(required)}.")
        if not all(isinstance(item[key], str) and item[key].strip() for key in required):
            raise PolicyError(f"{label} values must be non-empty strings.")
        try:
            expiry = date.fromisoformat(item["expires"])
        except ValueError as exc:
            raise PolicyError(f"{label}.expires must use YYYY-MM-DD.") from exc
        if expiry < current:
            raise PolicyError(
                f"Exception {item['id']} for {item['package']} expired on {expiry.isoformat()}."
            )
        if item["id"] in active:
            raise PolicyError(f"Duplicate vulnerability exception: {item['id']}.")
        active.append(item["id"])
    return active


def build_command(requirements: Path, vulnerability_ids: list[str]) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "pip_audit",
        "--requirement",
        str(requirements),
        "--disable-pip",
        "--progress-spinner",
        "off",
    ]
    for vulnerability_id in vulnerability_ids:
        command.extend(["--ignore-vuln", vulnerability_id])
    return command


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    args = parser.parse_args(argv)

    if not args.requirements.is_file():
        print(f"Dependency export is missing: {args.requirements}", file=sys.stderr)
        return 2
    try:
        exceptions = load_active_exceptions(args.policy)
    except PolicyError as exc:
        print(f"Invalid vulnerability policy: {exc}", file=sys.stderr)
        return 2

    completed = subprocess.run(build_command(args.requirements, exceptions), check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
