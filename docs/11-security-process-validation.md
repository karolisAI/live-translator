# Security Process Validation

Validated as a tabletop exercise against the process documents on 2026-09-07.
This validates decision paths and required records; it is not evidence that a
real incident occurred. Repeat quarterly and after material process changes.

| Scenario | Walk-through and expected control | Result |
| --- | --- | --- |
| New dependency advisory | CI/Dependabot privately identifies the package and advisory. Security owner opens a finding, assigns severity/owner/dates, and requires upgrade plus audit and compatibility evidence. If no fix exists, only an exact package/advisory exception with project-lead acceptance and expiry is allowed. CI detects expired or stale exceptions. | Pass — owner, escalation, remediation and closure evidence are defined. |
| Modified runtime asset | Manifest verification fails before the unapproved Piper/model/runtime asset is used. Operator stops the affected build and privately declares SEV-2 pending investigation (SEV-1 if execution or exposure is confirmed). Coordinator preserves the file and hash, blocks distribution, rebuilds from approved assets, verifies manifest/SBOM/tests and records recovery. | Pass — detection, containment, investigation and recovery paths are defined. |
| Diagnostic disclosure | A shared diagnostic folder containing audio/transcript is treated as at least SEV-2 until scope is known. Sharing is revoked, minimum evidence is preserved privately, affected data/users are determined, and the project lead owns privacy/stakeholder escalation. Recovery verifies opt-in diagnostics, retention and purge behavior. | Pass — confidentiality and evidence-handling rules are defined without requiring public disclosure. |

## Cross-check results

- Critical, High, Medium and Low vulnerabilities each have an owner, escalation
  path and acknowledgement/remediation target.
- SEV-1 through SEV-4 incidents define coordination and response expectations.
- Sensitive reports use GitHub Security Advisories or direct internal contact;
  public issues do not require confidential details.
- Closure requires commits/versions, impact/root cause, tests or manual evidence,
  security-owner verification and project-lead approval for residual risk.
- The recurring schedule covers weekly automation, monthly review, every release
  and quarterly tabletop validation.
- None of the procedures adds network access to meeting mode. Network use is
  limited to reporting, investigation, dependency/model preparation and updates
  outside active meeting operation.
