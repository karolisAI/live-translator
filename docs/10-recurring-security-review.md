# Recurring Security Review Checklist

The security owner coordinates reviews; the project lead confirms ownership and
accepts overdue or residual risk. Store a dated copy or linked Notion record as
evidence instead of checking off this source template permanently.

## Weekly automated review

- [ ] Dependabot pull requests and failed dependency-security jobs triaged.
- [ ] `pip-audit`, Action pin validation and the test matrix are green on `main`.
- [ ] New or expired vulnerability exceptions investigated immediately.
- [ ] Critical/High findings checked against containment and remediation dates.

## Monthly manual review

- [ ] Open findings and incidents have owners, severity, next action and due date.
- [ ] `security/vulnerability-policy.json` exceptions remain necessary and approved.
- [ ] Runtime manifest and release SBOM match current approved components.
- [ ] GitHub Actions remain least-privilege and pinned to full commit SHAs.
- [ ] Diagnostic defaults, retention and purge behavior have not regressed.
- [ ] Meeting mode still has no unexpected network access.
- [ ] `SECURITY.md` private reporting routes are usable by the current team.

## Before every release

- [ ] All Critical findings are closed; High findings are closed or explicitly accepted.
- [ ] Full CI, dependency audit, runtime integrity validation and packaged smoke test pass.
- [ ] Release SBOM, runtime manifest, commit and artifact hashes are retained together.
- [ ] Executable and installer signatures match the approved publisher and contain trusted timestamps.
- [ ] Signature-verification reports and `SHA256SUMS.txt` are retained with the matching SBOM.
- [ ] Offline meeting behavior and normal no-diagnostics retention behavior are verified.
- [ ] Known residual risks have project-lead approval and a review/expiry date.

## Quarterly tabletop review

- [ ] Walk through dependency vulnerability, runtime tampering and diagnostic disclosure scenarios.
- [ ] Confirm current security owner, technical owners and project-lead approver.
- [ ] Review response targets and private evidence storage with the team.
- [ ] Record gaps as findings with severity, owner and due date.

Minimum evidence for each review: date, participants, source commit/release,
completed checks, command or CI links, findings, owners, due dates and project-
lead decisions. A green checkbox without evidence is not closure.
