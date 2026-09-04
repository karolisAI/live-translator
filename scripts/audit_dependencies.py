"""Run pip-audit with strictly validated, package-scoped exceptions."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

class PolicyError(ValueError):
    """The vulnerability exception policy is invalid or expired."""

ExceptionPair = tuple[str, str]

def load_active_exceptions(path: Path, *, today: date | None = None) -> set[ExceptionPair]:
    """Return normalized ``(package, advisory ID)`` exception pairs."""
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
    active: set[ExceptionPair] = set()
    required = {"id", "package", "justification", "expires"}
    for index, item in enumerate(raw["exceptions"]):
        label = f"exceptions[{index}]"
        if not isinstance(item, dict) or set(item) != required:
            raise PolicyError(f"{label} must contain only {sorted(required)}.")
        if not all(isinstance(item[key], str) and item[key].strip() for key in required):
            raise PolicyError(f"{label} values must be non-empty strings.")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", item["expires"]) is None:
            raise PolicyError(f"{label}.expires must use YYYY-MM-DD.")
        try:
            expiry = date.fromisoformat(item["expires"])
        except ValueError as exc:
            raise PolicyError(f"{label}.expires must use YYYY-MM-DD.") from exc
        if expiry < current:
            raise PolicyError(
                f"Exception {item['id']} for {item['package']} expired on {expiry.isoformat()}."
            )
        pair = (item["package"].strip().lower(), item["id"].strip().upper())
        if pair in active:
            raise PolicyError(f"Duplicate vulnerability exception: {item['id']} for {item['package']}.")
        active.add(pair)
    return active

def build_command(requirements: Path) -> list[str]:
    return [
        sys.executable, "-m", "pip_audit", "--requirement", str(requirements),
        "--disable-pip", "--progress-spinner", "off", "--format", "json",
    ]

def evaluate_report(report: Any, exceptions: set[ExceptionPair]) -> tuple[list[ExceptionPair], set[ExceptionPair]]:
    """Return unsuppressed findings and exceptions that matched actual findings."""
    if not isinstance(report, dict) or not isinstance(report.get("dependencies"), list):
        raise PolicyError("pip-audit returned an unexpected JSON report.")
    unsuppressed: list[ExceptionPair] = []
    matched: set[ExceptionPair] = set()
    for dependency in report["dependencies"]:
        if not isinstance(dependency, dict) or not isinstance(dependency.get("name"), str):
            raise PolicyError("pip-audit dependency entry is malformed.")
        vulnerabilities = dependency.get("vulns")
        if not isinstance(vulnerabilities, list):
            raise PolicyError("pip-audit vulnerability list is malformed.")
        package = dependency["name"].strip().lower()
        for vulnerability in vulnerabilities:
            if not isinstance(vulnerability, dict) or not isinstance(vulnerability.get("id"), str):
                raise PolicyError("pip-audit vulnerability entry is malformed.")
            pair = (package, vulnerability["id"].strip().upper())
            if pair in exceptions:
                matched.add(pair)
            else:
                unsuppressed.append(pair)
    return unsuppressed, matched

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
    completed = subprocess.run(
        build_command(args.requirements), check=False, capture_output=True, text=True
    )
    if completed.returncode not in {0, 1}:
        print(completed.stderr, file=sys.stderr, end="")
        print(f"pip-audit failed with exit code {completed.returncode}.", file=sys.stderr)
        return 2
    if not completed.stdout.strip():
        print(completed.stderr, file=sys.stderr, end="")
        print("pip-audit returned no JSON report.", file=sys.stderr)
        return 2
    try:
        report = json.loads(completed.stdout)
        unsuppressed, matched = evaluate_report(report, exceptions)
    except (json.JSONDecodeError, PolicyError) as exc:
        print(f"Cannot evaluate pip-audit report: {exc}", file=sys.stderr)
        return 2
    stale = exceptions - matched
    if stale:
        for package, advisory in sorted(stale):
            print(f"Unused vulnerability exception: {advisory} for {package}.", file=sys.stderr)
        return 2
    if unsuppressed:
        print("Known vulnerabilities without an approved package-scoped exception:", file=sys.stderr)
        for package, advisory in unsuppressed:
            print(f"- {advisory} in {package}", file=sys.stderr)
        return 1
    print("No unapproved known vulnerabilities found.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
