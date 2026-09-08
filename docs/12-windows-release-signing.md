# Windows Release Signing

## Current status

The repository contains a fail-closed Authenticode signing and verification
path, but the organization has not yet supplied an approved signing identity.
Consequently, no current build may be represented as an approved signed
release. Ordinary local builds remain unsigned development artifacts.

Completion is blocked on these recorded decisions:

- the organization-approved publisher identity and certificate or managed
  signing service;
- the person accountable for the signing identity and release approval;
- the protected Windows signing environment and RFC 3161 timestamp service.

The project lead must record those decisions before the production signing
path is used. A self-signed certificate is only for the isolated automated
test and must never be used to distribute Live Translator.

## Security model

`scripts/windows_release_security.psm1` centralizes SignTool discovery,
SHA-256 Authenticode signing, signer verification, trusted-timestamp
verification and release checksums. The approved workflow is intentionally
fail closed:

```text
build EXE
  -> sign EXE with SHA-256 and RFC 3161 timestamp
  -> verify trust, expected signer and timestamp
  -> build installer
  -> sign installer with SHA-256 and RFC 3161 timestamp
  -> verify trust, expected signer and timestamp
  -> retain signatures, SHA256SUMS and matching SBOM
```

`build_inno_installer.ps1 -ApprovedRelease` verifies the executable before
Inno Setup runs. A missing, untrusted, wrongly signed or untimestamped
executable therefore cannot be wrapped in an approved installer. Any signing,
verification, timestamping, SBOM or checksum failure stops the script.

## Credential handling requirements

The implementation selects a certificate by thumbprint from the Windows
certificate store. The thumbprint and timestamp URL are identifiers, not
secrets. They may be supplied through these environment variables:

```text
LIVE_TRANSLATOR_SIGNING_CERT_THUMBPRINT
LIVE_TRANSLATOR_SIGNING_TIMESTAMP_URL
```

The private key must remain outside the repository and build artifacts. It
must be non-exportable where the chosen certificate or service supports that,
accessible only to the approved signing identity, and installed or made
available only on a protected Windows release runner. Do not pass a PFX
password on a command line, print it to logs, store a PFX in GitHub artifacts,
or use an ordinary pull-request runner for production signing. Production
signing must run only for a reviewed commit through a protected environment
with restricted approvers.

If the organization chooses a managed signing service instead of a
certificate in `CurrentUser\My`, adapt the signing function to that service
after its identity, authentication and evidence model are approved. Do not
store a long-lived service token in the repository.

The timestamp URL may use HTTP or HTTPS, as supported by common RFC 3161
services. Timestamp authenticity and integrity come from the cryptographically
signed timestamp token, which is verified with the artifact signature; the
transport scheme is not treated as the timestamp's trust boundary.

## Local unsigned build

These commands continue to produce development artifacts and print an
explicit warning that they are not approved releases:

```powershell
.\scripts\build_windows.ps1
.\scripts\build_inno_installer.ps1
```

An unsigned local build is useful for development and testing, but it must not
be published in the approved release channel or described as organization
signed.

## Approved release commands

After the external decisions and certificate provisioning are complete, run
from the protected Windows signing environment:

```powershell
$env:LIVE_TRANSLATOR_SIGNING_CERT_THUMBPRINT = "<approved certificate thumbprint>"
$env:LIVE_TRANSLATOR_SIGNING_TIMESTAMP_URL = "https://<approved-rfc3161-service>"

.\scripts\build_windows.ps1 -ApprovedRelease
.\scripts\build_inno_installer.ps1 -ApprovedRelease
```

The first command signs and verifies `dist\LiveTranslator\LiveTranslator.exe`.
The second refuses to invoke Inno Setup until that signature is valid, then
signs and verifies `dist\installer\LiveTranslatorSetup.exe`.

The final evidence directory is `dist\installer\release-evidence`:

```text
LiveTranslator.exe.signature.txt
LiveTranslatorSetup.exe.signature.txt
SHA256SUMS.txt
live-translator.cdx.json
```

Retain that directory with the exact installer, executable, source commit and
release record. The checksum file covers the executable, installer and SBOM,
so reviewers can demonstrate that the evidence belongs to the same release.

## Automated development test

On Windows, run:

```powershell
.\scripts\test_windows_signing.ps1
```

The test creates an ephemeral self-signed certificate in the current user's
personal store, signs a disposable copy of an unsigned launcher, confirms that
the embedded signature belongs to that certificate, modifies a byte in the
signed DOS-stub region and confirms an Authenticode hash mismatch. It does not
add the development certificate to the trusted-root store. Its `finally` block
removes the certificate and deletes the temporary files. The test-only script
inspects the self-signed signature directly; the production verification
function has no untrusted-certificate bypass and always requires SignTool and
Windows to report a trusted signature. GitHub Actions runs the same test on a
disposable Windows runner.

This proves the signing and tamper-detection mechanics. It does not prove a
production publisher identity, public certificate trust, timestamp service,
protected-runner authorization or a complete signed release dry run.

## Production completion checklist

Do not mark the signing card complete until all of the following evidence
exists:

- project lead approval of the publisher, owner, protected environment and
  timestamp service;
- a successful `-ApprovedRelease` build using the production identity;
- Windows reports both the executable and installer signatures as valid;
- both signatures contain trusted timestamps and the expected signer;
- `SHA256SUMS.txt`, both signature reports and the matching CycloneDX SBOM are
  retained with the release;
- installation and execution succeed for a standard Windows 10/11 user without
  administrator privileges;
- the security owner reviews the evidence and records the dry-run result.
