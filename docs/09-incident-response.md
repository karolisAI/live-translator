# Security Incident Response

## When to activate

Activate this procedure for suspected or confirmed compromise, including:

- modified or unapproved Piper, Parakeet, Argos, DLL or packaged runtime files;
- unexpected network access during meeting mode;
- diagnostic audio, transcript or translation disclosure;
- malicious dependency, CI workflow, build artifact or maintainer credential;
- exploitation of a vulnerability affecting supported use.

When uncertain, open an incident at the higher plausible class and downgrade it
after evidence review.

## Incident classes

| Class | Criteria | Initial coordination |
| --- | --- | --- |
| SEV-1 | Confirmed active compromise, untrusted code execution, broad/ongoing confidential-data disclosure, release compromise or meeting-mode exfiltration. | Security owner and project lead immediately; stop affected use and release. |
| SEV-2 | Credible suspected compromise, integrity bypass, or limited confirmed sensitive-data disclosure. | Security owner within 4 hours; project lead and technical owner the same day. |
| SEV-3 | Contained control failure or policy breach with no evidence of exploitation or sensitive-data exposure. | Security owner within 1 business day. |
| SEV-4 | Suspicious event requiring review but no credible security impact after initial triage. | Record in the security backlog; review within 5 business days. |

## Response procedure

### 1. Detect and declare

The receiver privately alerts the security owner. The security owner assigns an
incident ID, class, incident coordinator and scribe using
`docs/templates/security-incident-report.md`. Record times in UTC and identify
whether meeting use, distribution or model preparation must stop.

### 2. Contain

- Stop the affected process and use of the affected build; disconnect the host
  from networks if active compromise or exfiltration is plausible.
- Do not run an untrusted executable again. Preserve the executable, manifest,
  hashes, logs and relevant configuration in restricted storage.
- Revoke exposed sharing links or credentials and restrict diagnostic folders.
- Block release/download artifacts and notify known affected internal users.
- Maintain offline meeting guarantees: containment must not introduce telemetry
  or cloud calls into meeting mode.

### 3. Investigate

Build a timeline and determine entry point, affected commits/releases, hosts,
assets and data. Compare runtime files with the approved manifest and release
SBOM. Review dependency/audit results and GitHub workflow history. Collect only
the minimum meeting content needed; prefer hashes and metadata. Record who
accessed evidence and every transfer or transformation.

### 4. Eradicate and recover

Remove the cause, rotate affected credentials, rebuild from reviewed source and
locked dependencies, regenerate/verify manifests and SBOMs, and add regression
tests. Restore only from approved assets. Before returning to use, the technical
owner demonstrates the fix and the security owner verifies relevant tests,
offline behavior and absence of unexpected retained data.

### 5. Communicate

The project lead owns stakeholder and external communication. Share the minimum
necessary facts through restricted channels. Legal/privacy escalation is a
project-lead decision when personal or confidential meeting data may be
affected. Do not promise notification or regulatory conclusions without the
appropriate organizational owner.

### 6. Close and learn

Closure requires the evidence in `docs/08-vulnerability-management.md`, an
approved incident report and a post-incident review for SEV-1/SEV-2. Hold that
review within 5 business days of recovery. Track corrective actions with owners
and dates; project lead accepts any residual risk.

## Evidence handling and retention

Store sensitive evidence only in an access-restricted company location approved
by the incident coordinator. Never attach raw meeting audio, transcripts,
credentials or exploit code to public issues or ordinary CI artifacts. Record
SHA-256 hashes for collected files, original location, collector, UTC time and
authorized recipients. Do not delete or alter evidence until the coordinator
records the retention decision; after that date, securely remove copies that no
longer have an approved purpose.
