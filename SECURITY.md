# Security Policy

## Supported version

Security fixes are applied to the current `main` branch. Older source checkouts,
locally modified runtime assets and unverified Windows builds are not supported.

## Report a vulnerability privately

Do not disclose vulnerability details, meeting data, diagnostic audio,
transcripts, credentials or exploit steps in a public GitHub issue.

Team members must send a direct Microsoft Teams message to both the project lead
and the security owner. This is the currently supported private reporting
channel. Include only enough information to establish the impact; agree on a
restricted evidence location before uploading logs, audio, transcripts or
proof-of-concept files.

If a repository administrator enables GitHub Private Vulnerability Reporting,
the repository's **Security > Report a vulnerability** form may be used as an
additional private channel. Do not assume that route is available without
testing it while signed in. If neither private route is available, open a public
issue containing only a request for private contact and no vulnerability
details.

Please include, when safe:

- affected version or commit and Windows version;
- affected component and observed behavior;
- reproducible steps with secrets and meeting content removed;
- potential confidentiality, integrity or availability impact;
- whether exploitation or data disclosure may still be active.

The security owner acknowledges reports and assigns severity according to
[`docs/08-vulnerability-management.md`](docs/08-vulnerability-management.md).
Critical reports are escalated to the project lead immediately. Public
disclosure is coordinated only after a fix or explicit residual-risk decision.

## Operational security incidents

Suspected runtime modification, unexpected meeting-mode network access, or
diagnostic-data disclosure is an incident, not only a software bug. Stop using
the affected build and follow
[`docs/09-incident-response.md`](docs/09-incident-response.md). Do not destroy
potential evidence before the incident coordinator authorizes cleanup.
