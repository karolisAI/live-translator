import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class SecurityProcessDocumentationTests(unittest.TestCase):
    def _read(self, relative: str) -> str:
        return (REPO_ROOT / relative).read_text(encoding="utf-8")

    def _normalized(self, relative: str) -> str:
        return " ".join(self._read(relative).split())

    def test_all_security_process_deliverables_exist(self):
        required = [
            "SECURITY.md",
            "docs/08-vulnerability-management.md",
            "docs/09-incident-response.md",
            "docs/10-recurring-security-review.md",
            "docs/11-security-process-validation.md",
            "docs/templates/security-finding.md",
            "docs/templates/security-incident-report.md",
            "docs/templates/post-incident-review.md",
        ]
        for relative in required:
            with self.subTest(relative=relative):
                self.assertTrue((REPO_ROOT / relative).is_file())

    def test_private_reporting_does_not_require_public_disclosure(self):
        policy = self._normalized("SECURITY.md")
        self.assertIn("Do not disclose", policy)
        self.assertIn("Microsoft Teams", policy)
        self.assertIn("currently supported private reporting channel", policy)
        self.assertIn("no vulnerability details", policy)

    def test_every_vulnerability_severity_has_targets_and_escalation(self):
        procedure = self._read("docs/08-vulnerability-management.md")
        matrix = re.search(
            r"\| Severity \| Project criteria \|.*?(?=\n\n)", procedure, re.DOTALL
        )
        self.assertIsNotNone(matrix)
        for severity in ("Critical", "High", "Medium", "Low"):
            with self.subTest(severity=severity):
                row = next(
                    line for line in matrix.group(0).splitlines()
                    if line.startswith(f"| {severity} |")
                )
                self.assertGreaterEqual(row.count("|"), 7)
                self.assertRegex(row, r"\b(hour|day|days|release)\b")

    def test_roles_and_residual_risk_approver_are_explicit(self):
        procedure = self._read("docs/08-vulnerability-management.md")
        for role in ("Security owner", "Technical owner", "Project lead"):
            self.assertIn(role, procedure)
        self.assertIn("project lead is the residual-risk approver", procedure.lower())

    def test_incident_lifecycle_and_classes_are_complete(self):
        procedure = self._read("docs/09-incident-response.md")
        for incident_class in ("SEV-1", "SEV-2", "SEV-3", "SEV-4"):
            self.assertIn(incident_class, procedure)
        for phase in ("Detect and declare", "Contain", "Investigate", "Eradicate and recover", "Close and learn"):
            self.assertIn(phase, procedure)

    def test_closure_requires_evidence_and_independent_verification(self):
        procedure = self._normalized("docs/08-vulnerability-management.md")
        self.assertIn("Closure evidence", procedure)
        self.assertIn("regression test", procedure)
        self.assertIn("security-owner verification", procedure)
        self.assertIn("should not be its only verifier", procedure)

    def test_review_schedule_covers_all_required_cadences(self):
        checklist = self._read("docs/10-recurring-security-review.md")
        for cadence in ("Weekly", "Monthly", "Before every release", "Quarterly"):
            self.assertIn(cadence, checklist)

    def test_tabletop_validation_covers_required_scenarios(self):
        validation = self._read("docs/11-security-process-validation.md")
        for scenario in ("dependency advisory", "Modified runtime asset", "Diagnostic disclosure"):
            self.assertIn(scenario, validation)
        self.assertGreaterEqual(validation.count("| Pass"), 3)

    def test_process_preserves_offline_meeting_operation(self):
        combined = " ".join(
            self._normalized(path)
            for path in (
                "docs/08-vulnerability-management.md",
                "docs/09-incident-response.md",
                "docs/11-security-process-validation.md",
            )
        )
        self.assertIn("no response step may add network access to meeting mode", combined)
        self.assertIn("procedures adds network access to meeting mode", combined)


if __name__ == "__main__":
    unittest.main()
