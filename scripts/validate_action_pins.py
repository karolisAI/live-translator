"""Reject mutable third-party action references in GitHub workflows."""

from __future__ import annotations

import re
import sys
from pathlib import Path


USES = re.compile(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)", re.MULTILINE)
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
DOCKER_DIGEST = re.compile(r"^docker://[^\s@]+@sha256:[0-9a-f]{64}$")


def unpinned_actions(root: Path) -> list[str]:
    findings: list[str] = []
    for workflow in sorted(root.rglob("*.y*ml")):
        text = workflow.read_text(encoding="utf-8")
        for reference in USES.findall(text):
            if reference.startswith("./"):
                continue
            if reference.startswith("docker://"):
                if not DOCKER_DIGEST.fullmatch(reference):
                    findings.append(f"{workflow}: mutable container action reference {reference}")
                continue
            if "@" not in reference:
                findings.append(f"{workflow}: missing @ref in {reference}")
                continue
            _, revision = reference.rsplit("@", 1)
            if not FULL_SHA.fullmatch(revision):
                findings.append(f"{workflow}: mutable action reference {reference}")
    return findings


def main() -> int:
    findings = unpinned_actions(Path(".github"))
    if findings:
        print("GitHub Actions must be pinned to full commit SHAs:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print("All external GitHub Actions are pinned to full commit SHAs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
