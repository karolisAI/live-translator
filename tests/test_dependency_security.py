import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts.audit_dependencies import (
    PolicyError,
    build_command,
    evaluate_report,
    load_active_exceptions,
)
from scripts.validate_action_pins import WorkflowScanError, unpinned_actions
from scripts.validate_sbom import validate_sbom


class VulnerabilityPolicyTests(unittest.TestCase):
    def _policy(self, data):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "policy.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_empty_policy_is_valid(self):
        path = self._policy(
            {
                "schema_version": 1,
                "policy": "fail-on-any-known-vulnerability",
                "exceptions": [],
            }
        )
        self.assertEqual(load_active_exceptions(path, today=date(2026, 9, 4)), set())

    def test_active_exception_is_scoped_to_package_and_advisory(self):
        path = self._policy(
            {
                "schema_version": 1,
                "policy": "fail-on-any-known-vulnerability",
                "exceptions": [
                    {
                        "id": "GHSA-example",
                        "package": "example",
                        "justification": "Not reachable; tracked in ISSUE-1.",
                        "expires": "2026-09-05",
                    }
                ],
            }
        )
        exceptions = load_active_exceptions(path, today=date(2026, 9, 4))
        self.assertEqual(exceptions, {("example", "GHSA-EXAMPLE")})
        self.assertNotIn("--ignore-vuln", build_command(Path("locked.txt")))

    def test_exception_only_suppresses_matching_package(self):
        report = {
            "dependencies": [
                {"name": "example", "vulns": [{"id": "GHSA-example"}]},
                {"name": "other", "vulns": [{"id": "GHSA-example"}]},
            ]
        }
        unsuppressed, matched = evaluate_report(report, {("example", "GHSA-EXAMPLE")})
        self.assertEqual(unsuppressed, [("other", "GHSA-EXAMPLE")])
        self.assertEqual(matched, {("example", "GHSA-EXAMPLE")})

    def test_expired_exception_fails_closed(self):
        path = self._policy(
            {
                "schema_version": 1,
                "policy": "fail-on-any-known-vulnerability",
                "exceptions": [
                    {
                        "id": "GHSA-example",
                        "package": "example",
                        "justification": "Temporary exception.",
                        "expires": "2026-09-03",
                    }
                ],
            }
        )
        with self.assertRaisesRegex(PolicyError, "expired"):
            load_active_exceptions(path, today=date(2026, 9, 4))

    def test_unknown_policy_fields_are_rejected(self):
        path = self._policy(
            {
                "schema_version": 1,
                "policy": "fail-on-any-known-vulnerability",
                "exceptions": [],
                "ignore_everything": True,
            }
        )
        with self.assertRaises(PolicyError):
            load_active_exceptions(path)

    def test_compact_expiry_date_is_rejected(self):
        path = self._policy(
            {
                "schema_version": 1,
                "policy": "fail-on-any-known-vulnerability",
                "exceptions": [{
                    "id": "GHSA-example", "package": "example",
                    "justification": "Temporary.", "expires": "20260905",
                }],
            }
        )
        with self.assertRaisesRegex(PolicyError, "YYYY-MM-DD"):
            load_active_exceptions(path, today=date(2026, 9, 4))

    def test_iso_week_expiry_date_is_rejected(self):
        path = self._policy(
            {
                "schema_version": 1,
                "policy": "fail-on-any-known-vulnerability",
                "exceptions": [{
                    "id": "GHSA-example", "package": "example",
                    "justification": "Temporary.", "expires": "2026-W36-5",
                }],
            }
        )
        with self.assertRaisesRegex(PolicyError, "YYYY-MM-DD"):
            load_active_exceptions(path, today=date(2026, 9, 4))


class ActionPinTests(unittest.TestCase):
    def test_mutable_action_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "test.yml").write_text(
                "steps:\n  - uses: actions/checkout@v7\n", encoding="utf-8"
            )
            self.assertEqual(len(unpinned_actions(root)), 1)

    def test_full_sha_and_local_action_are_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "test.yml").write_text(
                "steps:\n"
                "  - uses: actions/checkout@" + "a" * 40 + "\n"
                "  - uses: ./local-action\n",
                encoding="utf-8",
            )
            self.assertEqual(unpinned_actions(root), [])

    def test_quoted_full_sha_references_are_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sha = "a" * 40
            (root / "test.yml").write_text(
                f"steps:\n  - uses: \"actions/checkout@{sha}\"\n"
                f"  - uses: 'actions/setup-python@{sha}'\n",
                encoding="utf-8",
            )
            self.assertEqual(unpinned_actions(root), [])

    def test_missing_workflow_directory_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(WorkflowScanError):
                unpinned_actions(Path(directory) / "missing")

    def test_empty_workflow_directory_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(WorkflowScanError):
                unpinned_actions(Path(directory))

    def test_mutable_container_action_is_rejected(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "workflow.yml").write_text("steps:\n  - uses: docker://alpine:latest\n", encoding="utf-8")
        self.assertEqual(len(unpinned_actions(root)), 1)

    def test_digest_pinned_container_action_is_accepted(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        digest = "a" * 64
        (root / "workflow.yml").write_text(
            f"steps:\n  - uses: docker://alpine@sha256:{digest}\n", encoding="utf-8"
        )
        self.assertEqual(unpinned_actions(root), [])


class SbomValidationTests(unittest.TestCase):
    def test_valid_cyclonedx_document_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sbom.json"
            path.write_text(
                json.dumps(
                    {
                        "bomFormat": "CycloneDX",
                        "specVersion": "1.5",
                        "components": [{"name": "numpy", "version": "2.0.0"}],
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(validate_sbom(path), 0)

    def test_empty_component_list_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sbom.json"
            path.write_text(
                json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.5", "components": []}),
                encoding="utf-8",
            )
            self.assertEqual(validate_sbom(path), 1)


if __name__ == "__main__":
    unittest.main()
