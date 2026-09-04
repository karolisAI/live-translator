# Dependency and CI Security

## Dependency source of truth

`pyproject.toml` declares direct dependency ranges. `uv.lock` is the reviewed,
machine-managed record of exact direct and transitive versions for supported
environments. Do not edit `uv.lock` manually and do not maintain a second set of
versions in `requirements.txt`.

The repository requires uv 0.12.9. Developer and CI installs use `--frozen`, so
an outdated or missing lock fails instead of being silently regenerated:

```powershell
uv sync --frozen
uv run --frozen python -m unittest discover -s tests -t tests -v
```

Optional environments are explicit:

```powershell
uv sync --frozen --extra translate
uv sync --frozen --extra tts
uv sync --frozen --extra build
```

The supported Python range is intentionally limited to 3.11 and 3.12. CI
tests and audits both versions on Windows and Linux so platform markers cannot
hide a vulnerable platform-specific dependency.

`argostranslate` 1.11.0 declares the vulnerable `stanza` 1.10.1 release as an
exact transitive dependency. The lock therefore applies a reviewed uv override
to require `stanza>=1.12.2,<2`, which contains the fix for
`GHSA-v5jw-96jm-7h2c`. The Argos package-management import path is covered by
a CI compatibility smoke check and must be rechecked when either dependency
changes.

The Windows build script synchronizes the `build` extra from the lock into a
dedicated `.build-venv`. It neither relies on packages left in a developer's
environment nor prunes the developer's selected optional extras.

## Vulnerability policy

CI exports the complete locked dependency graph and scans it with the locked
`pip-audit` version. The default is zero tolerance: any vulnerability reported
by the scanner fails the job. A scanner error also fails the job.

An unavoidable temporary exception belongs in
`security/vulnerability-policy.json` and requires all of:

- the vulnerability identifier;
- affected package name;
- a concrete justification;
- an ISO `YYYY-MM-DD` expiry date.

Expired, duplicate, malformed, or undocumented exceptions fail before the
scanner runs. Each exception suppresses only the exact normalized package-name
and vulnerability-ID pair; the same advisory in another package still fails.
An exception that matches no current finding also fails so stale approvals are
removed. Exceptions must be reviewed in a pull request and removed as soon as
an upstream fix is usable. Example (not an approval):

```json
{
  "id": "GHSA-example",
  "package": "example-package",
  "justification": "Not reachable in the packaged application; tracked in ISSUE-123.",
  "expires": "2026-10-01"
}
```

## SBOM

CI and the Windows build generate a CycloneDX 1.5 JSON SBOM from the frozen
lock. CI validates it and uploads it as `live-translator-sbom`. A Windows build
writes `dist/LiveTranslator/live-translator.cdx.json`; retain it with the exact
installer and release hashes it describes.

## GitHub Actions

Every external action reference must use a full 40-character commit SHA. The
human-readable release tag remains as an inline comment. CI runs
`scripts/validate_action_pins.py` to prevent a mutable tag or branch from being
introduced later.

Dependabot checks both the `uv` lock and GitHub Actions weekly. Its pull
requests do not bypass review: lock changes, vulnerability results, tests and
SBOM generation must all pass before merge.

## Review procedure

For each dependency update:

1. Read upstream release notes and identify security or compatibility changes.
2. Review both `pyproject.toml` and `uv.lock`; unexpected packages require an
   explanation.
3. Run the full Windows/Linux CI matrix and dependency-security job.
4. For release-affecting updates, rebuild the Windows application and retain
   the generated SBOM.
5. Record any accepted vulnerability in the policy with an owner-traceable
   justification and expiry date.
