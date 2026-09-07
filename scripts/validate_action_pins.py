"""Reject mutable third-party action references in GitHub workflows."""

from __future__ import annotations

import re
import sys
from pathlib import Path

USES = re.compile(r"^\s*(?:-\s*)?uses:\s*([^#]+?)\s*$", re.MULTILINE)
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
DOCKER_DIGEST = re.compile(r"^docker://[^\s@]+@sha256:[0-9a-f]{64}$")

class WorkflowScanError(ValueError):
    """The workflow tree cannot be scanned safely."""

def unpinned_actions(root: Path) -> list[str]:
    if not root.is_dir():
        raise WorkflowScanError(f"GitHub workflow directory is missing: {root}")
    workflows = sorted({*root.rglob("*.yml"), *root.rglob("*.yaml")})
    if not workflows:
        raise WorkflowScanError(f"No GitHub workflow or action YAML files found under: {root}")
    findings: list[str] = []
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        for captured in USES.findall(text):
            reference = captured.strip().strip("\"'")
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
    workflow_root = Path(__file__).resolve().parents[1] / ".github"
    try:
        findings = unpinned_actions(workflow_root)
    except (OSError, UnicodeError, WorkflowScanError) as exc:
        print(f"Cannot validate GitHub Action pins: {exc}", file=sys.stderr)
        return 2
    if findings:
        print("GitHub Actions must be pinned to full commit SHAs:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print("All external GitHub Actions are pinned to full commit SHAs.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
