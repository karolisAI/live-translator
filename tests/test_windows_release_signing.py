import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class WindowsReleaseSigningContractTests(unittest.TestCase):
    def _read(self, relative: str) -> str:
        return (REPO_ROOT / relative).read_text(encoding="utf-8")

    def _normalized(self, relative: str) -> str:
        return " ".join(self._read(relative).split()).casefold()

    def test_release_security_files_exist(self):
        for relative in (
            "scripts/windows_release_security.psm1",
            "scripts/test_windows_signing.ps1",
            "docs/12-windows-release-signing.md",
        ):
            with self.subTest(relative=relative):
                self.assertTrue((REPO_ROOT / relative).is_file())

    def test_approved_signing_uses_sha256_and_rfc3161(self):
        module = self._read("scripts/windows_release_security.psm1")
        for required in ('"/fd", "SHA256"', '"/tr", $TimestampUrl', '"/td", "SHA256"'):
            with self.subTest(required=required):
                self.assertIn(required, module)
        self.assertIn("RequireTimestamp", module)
        self.assertIn("TimeStamperCertificate", module)
        self.assertIn('$timestampUri.Scheme -notin @("http", "https")', module)

    def test_signtool_sdk_versions_are_sorted_semantically(self):
        module = self._read("scripts/windows_release_security.psm1")
        self.assertIn("[Version]::TryParse", module)
        self.assertIn("Sort-Object Version -Descending", module)

    def test_executable_is_verified_before_installer_creation(self):
        script = self._read("scripts/build_inno_installer.ps1")
        verification = script.index("Assert-WindowsSignature")
        installer_build = script.index("& $Iscc.Source")
        self.assertLess(verification, installer_build)

    def test_approved_release_signs_and_verifies_both_artifacts(self):
        executable_build = self._read("scripts/build_windows.ps1")
        installer_build = self._read("scripts/build_inno_installer.ps1")
        for script in (executable_build, installer_build):
            with self.subTest(script=script[:30]):
                self.assertIn("ApprovedRelease", script)
                self.assertIn("Invoke-WindowsSign", script)
                self.assertIn("Assert-WindowsSignature", script)
                self.assertIn("RequireTimestamp", script)
                self.assertNotIn("AllowUntrustedDevelopmentCertificate", script)

        module = self._read("scripts/windows_release_security.psm1")
        self.assertNotIn("AllowUntrustedDevelopmentCertificate", module)

    def test_installer_validation_uses_locked_build_environment(self):
        installer_build = self._read("scripts/build_inno_installer.ps1")
        self.assertIn(".build-venv", installer_build)
        self.assertIn("sync --frozen --extra build --no-default-groups", installer_build)
        self.assertIn("run --frozen --extra build --no-default-groups", installer_build)
        self.assertNotIn('.venv\\Scripts\\python.exe', installer_build)

    def test_release_evidence_includes_hashes_signatures_and_sbom(self):
        installer_build = self._read("scripts/build_inno_installer.ps1")
        for evidence in (
            "SHA256SUMS.txt",
            "LiveTranslator.exe.signature.txt",
            "LiveTranslatorSetup.exe.signature.txt",
            "live-translator.cdx.json",
            "Write-ReleaseChecksums",
        ):
            with self.subTest(evidence=evidence):
                self.assertIn(evidence, installer_build)

    def test_unsigned_local_builds_are_explicit(self):
        for relative in ("scripts/build_windows.ps1", "scripts/build_inno_installer.ps1"):
            with self.subTest(relative=relative):
                script = self._read(relative)
                self.assertIn("Unsigned local", script)
                self.assertIn("not an approved release", script)

    def test_ephemeral_test_checks_tampering_and_cleans_certificate(self):
        test_script = self._read("scripts/test_windows_signing.ps1")
        self.assertIn("New-SelfSignedCertificate", test_script)
        self.assertIn("FileMode]::Open", test_script)
        self.assertIn("WriteByte", test_script)
        self.assertIn("HashMismatch", test_script)
        self.assertNotIn("AppendAllText", test_script)
        self.assertIn("Tampered executable unexpectedly passed", test_script)
        self.assertIn("certutil.exe -user -delstore", test_script)
        self.assertIn("finally", test_script)

    def test_ci_runs_windows_signing_contract(self):
        workflow = self._read(".github/workflows/tests.yml")
        self.assertIn("windows-signing-contract:", workflow)
        self.assertIn(".\\scripts\\test_windows_signing.ps1", workflow)

    def test_documentation_keeps_production_completion_blocked(self):
        documentation = self._normalized("docs/12-windows-release-signing.md")
        self.assertIn("no current build may be represented as an approved signed release", documentation)
        self.assertIn("organization-approved publisher identity", documentation)
        self.assertIn("complete signed release dry run", documentation)


if __name__ == "__main__":
    unittest.main()
