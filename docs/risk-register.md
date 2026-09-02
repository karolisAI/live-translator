# Live Translator Security Risk Register

This document evaluates and prioritizes the security risks identified in
`docs/threat-model.md`.

## Document status

| Field | Value |
| --- | --- |
| Status | Revalidated for baseline `79f95d6` |
| Security owner | Kristupas |
| Architecture baseline | Parakeet PR #2 plus merged security PRs #3, #4 and #5 and reliability PR #6 |
| Baseline commit | `79f95d6` |
| Component inventory | `docs/component-inventory.md` |
| Threat model | `docs/threat-model.md` |
| Last updated | 2026-09-02 |
| Stakeholder review | Pending project-lead review |

## Risk-assessment method

Each risk is assigned a likelihood score and an impact score. The two values are
multiplied to produce the initial risk score.

### Likelihood

| Score | Rating | Definition |
| --- | --- | --- |
| 1 | Unlikely | Requires unusual access, several difficult conditions or a capability not normally available to the threat actor. |
| 2 | Possible | Can occur under realistic conditions but requires a specific action, configuration, failure or attacker opportunity. |
| 3 | Likely | Can occur during expected use, depends on a common mistake or is directly exposed without an effective preventive control. |

Likelihood must be based on the current architecture and controls, not only on
the theoretical possibility of an attack.

### Impact

Use the highest credible impact across confidentiality, integrity and
availability.

| Score | Rating | Definition |
| --- | --- | --- |
| 1 | Low | Limited technical or operational effect with no expected confidential meeting-data exposure or code execution. |
| 2 | Medium | Meaningful disruption, limited sensitive-data exposure or recoverable integrity impact affecting one user or meeting. |
| 3 | High | Confidential meeting-data exposure, execution of untrusted code, major translation-integrity failure, release compromise or violation of a mandatory offline requirement. |

Impact must describe a credible outcome. The presence of native code or a
security-sensitive component does not automatically make every failure
high-impact.

### Initial risk score

| Score | Rating | Default priority |
| --- | --- | --- |
| 1–2 | Low | P3 / Improvement |
| 3–4 | Medium | P2 |
| 6 | High | P1 |
| 9 | Critical | P0 |

### Priority override

The calculated score is the starting point, not an automatic decision.

A risk may be raised to P0 when it:

- could expose confidential meeting data during normal expected use;
- provides a direct path to launching an unapproved executable or DLL;
- directly violates the mandatory offline meeting requirement;
- compromises the official build or release distributed to multiple users.

A priority override must include a written justification. Risk priority must
not be lowered only to fit available sprint capacity.

## Risk status

| Status | Meaning |
| --- | --- |
| Open | Risk is identified but remediation has not started. |
| In progress | A responsible owner is implementing or validating controls. |
| Mitigated | Required controls are implemented and verification evidence exists. |
| Accepted | The responsible stakeholder has formally accepted the residual risk. |
| Deferred | Work is postponed with an owner, reason and review date. |
| Closed | The threat is no longer applicable and the reason is documented. |

`Mitigated` must not be used only because code was changed. Relevant tests,
release checks or other verification evidence must also exist.

## Risk register

| ID | Threat | Risk statement | Affected components | Likelihood | Impact | Score | Priority | Treatment owner | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| RSK-01 | THR-01 | Untrusted Piper executable or DLL loading | CMP-07, CMP-09, CMP-11, CMP-12 | 2 / Possible | 3 / High | 6 / High | P0 / Critical | Kristupas (remaining integrity work) | In progress |
| RSK-02 | THR-02 | Unapproved or malicious runtime model loading | CMP-03, CMP-04, CMP-05, CMP-06, CMP-07 | 2 / Possible | 3 / High | 6 / High | P1 / High | Kristupas (remaining integrity work) | In progress |
| RSK-03 | THR-03 | Compromised or unexpectedly changed Python dependency | CMP-04, CMP-05, CMP-06, CMP-11, CMP-13 | 2 / Possible | 3 / High | 6 / High | P1 / High | TBD | Open |
| RSK-04 | THR-04 | Unsafe or unapproved Argos package installation | CMP-01, CMP-06 | 2 / Possible | 3 / High | 6 / High | P1 / High | TBD | Open |
| RSK-05 | THR-05 | Unexpected network access during meeting mode | CMP-01, CMP-03, CMP-04, CMP-10 | 2 / Possible | 3 / High | 6 / High | P0 / Critical | Kristupas (verification) | Mitigated |
| RSK-06 | THR-06 | Disclosure of persisted meeting diagnostic data | CMP-01, CMP-02, CMP-10 | 2 / Possible | 3 / High | 6 / High | P1 / High | TBD (policy/ACL follow-up) | In progress |
| RSK-07 | THR-07 | Disclosure through terminal output or terminal logging | CMP-01, CMP-10 | 2 / Possible | 3 / High | 6 / High | P1 / High | Kristupas (verification) | Mitigated |
| RSK-08 | THR-08 | Recoverable Piper temporary audio after abnormal termination | CMP-07, CMP-10 | 2 / Possible | 2 / Medium | 4 / Medium | P2 / Medium | TBD | Open |
| RSK-09 | THR-09 | Profile path escape or security-sensitive configuration tampering | CMP-01, CMP-07, CMP-09 | 2 / Possible | 3 / High | 6 / High | P1 / High | TBD | Open |
| RSK-10 | THR-10 | Incorrect or unauthorized Windows audio routing | CMP-01, CMP-02, CMP-08, CMP-09 | 2 / Possible | 3 / High | 6 / High | P1 / High | TBD | Open |
| RSK-11 | THR-11 | Resource exhaustion or blocked runtime processing | CMP-02, CMP-03, CMP-05, CMP-07, CMP-09 | 2 / Possible | 2 / Medium | 4 / Medium | P2 / Medium | TBD (remaining resource limits) | In progress |
| RSK-12 | THR-12 | Misleading output from incorrect or low-confidence recognition | CMP-03, CMP-04, CMP-06, CMP-07 | 3 / Likely | 2 / Medium | 6 / High | P1 / High | TBD | Open |
| RSK-13 | THR-13 | Unexpected or modified files included in release artifacts | CMP-10, CMP-11, CMP-12 | 2 / Possible | 3 / High | 6 / High | P1 / High | TBD | Open |
| RSK-14 | THR-14 | Distribution of an unsigned or unofficial application | CMP-11, CMP-12 | 2 / Possible | 3 / High | 6 / High | P1 / High | TBD | Open |
| RSK-15 | THR-15 | CI workflow or pull-request supply-chain compromise | CMP-11, CMP-13 | 2 / Possible | 2 / Medium | 4 / Medium | P2 / Medium | TBD | Open |
| RSK-16 | THR-16 | Same-user modification of installed runtime components | CMP-06, CMP-07, CMP-09, CMP-11, CMP-12 | 2 / Possible | 3 / High | 6 / High | P1 / High | Kristupas (remaining integrity work) | In progress |
| RSK-17 | THR-17 | Sensitive profiles, caches or diagnostics remain after uninstall | CMP-09, CMP-10, CMP-12 | 2 / Possible | 2 / Medium | 4 / Medium | P2 / Medium | TBD (uninstall policy) | In progress |

## Risk summary

| Priority | Count | Risks | Required handling |
| --- | ---: | --- | --- |
| P0 / Critical | 2 | RSK-01, RSK-05 | Must be addressed before approving confidential internal meeting use, unless the accountable stakeholder formally accepts the residual risk. |
| P1 / High | 11 | RSK-02, RSK-03, RSK-04, RSK-06, RSK-07, RSK-09, RSK-10, RSK-12, RSK-13, RSK-14, RSK-16 | Plan into the security-hardening roadmap and verify before the related capability or release path is approved. |
| P2 / Medium | 4 | RSK-08, RSK-11, RSK-15, RSK-17 | Implement through planned hardening or formally defer with an owner, reason and review date. |
| P3 / Improvement | 0 | None | No initial risks currently fall into this category. Reassess after controls are implemented. |

The high number of P1 risks must not be interpreted as eleven independent
projects. Several risks share the same root causes and should be treated through
common security workstreams.

### Current status summary for `79f95d6`

| Status | Count | Risks |
| --- | ---: | --- |
| Mitigated | 2 | RSK-05, RSK-07 |
| In progress | 6 | RSK-01, RSK-02, RSK-06, RSK-11, RSK-16, RSK-17 |
| Open | 9 | RSK-03, RSK-04, RSK-08, RSK-09, RSK-10, RSK-12, RSK-13, RSK-14, RSK-15 |

`Mitigated` here means the required application control and regression evidence
exist for the supported path. It does not claim control over unrelated operating
system, endpoint-agent or user network activity, and it does not eliminate the
documented residual risk.

## Treatment workstreams

| Workstream | Included risks | Shared outcome | Treatment owner |
| --- | --- | --- | --- |
| WS-01 — Trusted runtime and offline meeting mode | RSK-01, RSK-02, RSK-04, RSK-05, RSK-09, RSK-16 | Trusted runtime roots, protected asset manifest, safe preparation and fail-closed offline meeting startup. | Assigned in the related Notion implementation stories. |
| WS-02 — Meeting privacy and audio handling | RSK-06, RSK-07, RSK-08, RSK-10, RSK-17 | Approved transcript display, diagnostic retention, temporary-file handling, cleanup and verified audio routing. | Assigned in the related Notion implementation stories. |
| WS-03 — Dependency, build and release security | RSK-03, RSK-13, RSK-14, RSK-15 | Reproducible dependencies, hardened CI, inspected release contents, SBOM and signed Windows artifacts. | Assigned in the related Notion implementation stories. |
| WS-04 — Availability and output integrity | RSK-11, RSK-12 | Bounded runtime behaviour, timeout handling, confidence communication and representative real-speech validation. | Assigned in the related Notion implementation stories. |

`Treatment owner` identifies the person responsible for implementing and
verifying a remediation story; it is intentionally left `TBD` until the project
lead assigns the related Notion work. Kristupas remains the security owner and
coordinates risk tracking, but this does not make him the implementer of every
control. Formal acceptance of residual risk remains a stakeholder decision.

## Risk-review rules

For every risk:

1. Confirm that the linked threat scenario is supported by code or observed
   behaviour.
2. Determine likelihood using the current controls and realistic attacker
   capability.
3. Determine the highest credible impact.
4. Calculate likelihood multiplied by impact.
5. Assign the default priority and document any override.
6. Define remediation and verification evidence.
7. Assign a treatment owner when the related implementation story is approved.
8. Record residual risk after the control is implemented.

Unverified assumptions must be recorded as validation work rather than silently
used to lower the risk.

Completion of this initial register means that the identified baseline risks
have evidence, consistent initial scoring, proposed treatment and required
verification. It does not mean that the open risks have been remediated or
accepted.

## Baseline `79f95d6` control reassessment

The detailed assessments below retain the original threat rationale, initial
score, required treatment and target residual rating. The table here records
the controls actually present in the current baseline and is authoritative when
an older evidence bullet below describes a control as absent.

| Risk | Current control evidence | Remaining gap / condition |
| --- | --- | --- |
| RSK-01 | PR #5 introduces approved runtime roots, rejects `PATH`, current-working-directory, traversal and outside-root resolution, and fails before an untrusted Piper path executes. Tests cover planted CWD executables and outside-root paths. | Piper EXE, DLL, espeak data and voice-model bytes are not checked against a protected SHA-256 manifest; release signing is also absent. |
| RSK-02 | PR #3 pins the default ASR repository and commit, separates `prepare-models`, requires prepared local files and rejects a mismatched revision stamp. PR #5 applies trusted-root loading to applicable Argos/TTS assets. | `revision.txt` and existence checks do not prove file content. Parakeet, Argos and Piper model files still need manifest size/hash verification and approved-source records. |
| RSK-05 | PR #3 makes model download reachable only through explicit preparation. Meeting mode verifies the local directory, uses the supported offline resolver path and fails before microphone capture. Offline tests patch Hugging Face download functions to raise; both language directions are covered. | Keep the regression tests and record packaged Windows network-monitoring evidence for each supported release. Unsupported custom model/runtime changes trigger reassessment. |
| RSK-06 | PR #4 makes capture opt-in, warns, defaults to a per-user root, adds age/size retention, purge, Git exclusions and resolved containment against traversal, symlinks and junctions. | Plaintext capture, inherited ACLs, backup/sync destinations, encryption policy and separate audio/text selection require stakeholder decisions or follow-up controls. |
| RSK-07 | PR #4 makes normal and verbose meeting operation content-free; only explicit `--show-text` displays transcripts/translations and warns about scrollback/screen sharing. Regression tests cover all flag combinations. | Authorized copying, terminal-host logging and external screen capture remain residual organizational/user risks. |
| RSK-11 | Realtime queues and recovery work are bounded; configuration rejects selected invalid values; diagnostics have retention/size limits; PR #5 adds Piper timeout handling and PR #6 adds explicit UTF-8 input. | Native model loading/inference lacks process-level CPU/memory limits and several numeric settings still lack practical upper bounds. |
| RSK-16 | Installed runtime lookup is limited to application/bundle roots, while the development override is explicit and ignored by frozen builds. | Same-user modification inside an approved writable root is not detected without a protected manifest and signed release chain. |
| RSK-17 | Application-owned diagnostics have retention and an explicit purge command. | Uninstall/update policy still does not fully inventory or offer cleanup for profiles, prepared models, caches and abnormal-termination temporary WAVs. |

### Integration verification evidence

- Baseline commit: `79f95d6`.
- Local command: `.venv\\Scripts\\python.exe -m unittest discover -s tests -t tests -q`.
- Result on 2026-09-02: 336 tests passed; 3 tests skipped because the current Windows process could not create directory symlinks.
- Relevant merged changes: [PR #3](https://github.com/karolisAI/live-translator/pull/3), [PR #4](https://github.com/karolisAI/live-translator/pull/4), [PR #5](https://github.com/karolisAI/live-translator/pull/5) and [PR #6](https://github.com/karolisAI/live-translator/pull/6).
- Unit/integration evidence does not replace real VB-CABLE/Teams, controlled network-monitoring, clean Windows build, installer-content or signature validation.

## Detailed risk assessments

Unless a detailed entry has already been rewritten for `79f95d6`, its
`Evidence` subsection describes the original discovery baseline. Read it with
the current-control reassessment above; do not use an old absence statement to
override newer implementation evidence.

### RSK-01 — Untrusted Piper executable or DLL loading

**Linked threat:** THR-01  
**Affected components:** CMP-07, CMP-09, CMP-11, CMP-12  
**Status:** In progress  
**Treatment owner:** Kristupas (remaining integrity work)

#### Evidence

- Piper is launched as a separate subprocess with the current user's
  permissions.
- The executable and model paths can be supplied through configuration.
- Runtime path resolution is restricted to explicit approved source/package,
  PyInstaller bundle and frozen-application roots; the current working directory
  and `PATH` are not trusted.
- Absolute paths, `..` traversal and resolved paths outside approved roots are
  rejected before Piper execution. Frozen builds ignore the development-root
  environment override.
- Build preparation verifies that selected Piper files exist but does not
  verify approved versions, SHA-256 hashes or digital signatures.
- Tests prove that outside-root and planted working-directory executables are
  rejected and that the security error prevents further synthesis attempts.
  They do not verify the bytes of a real Piper binary or companion DLL.

#### Risk scenario

An attacker, compromised build or same-user process modifies Piper or a
companion asset inside an approved runtime location. Live Translator accepts
the file because its path is approved and no content hash is enforced, then
launches it with the current user's permissions.

The substituted runtime can access translated meeting text, local user data and
network resources available to the user.

#### Initial assessment

| Factor | Rating | Justification |
| --- | --- | --- |
| Likelihood | 2 / Possible | Exploitation requires local, configuration, runtime-path, build or release access, but these are realistic same-user or supply-chain conditions and no integrity verification is enforced. |
| Impact | 3 / High | Successful exploitation results in execution of unapproved code with the current user's permissions and may expose confidential meeting data. |
| Calculated score | 6 / High | Likelihood 2 multiplied by impact 3. |
| Final priority | P0 / Critical | Raised from the default P1 because the risk can execute an unapproved runtime component and access confidential meeting content. |

#### Required treatment

- Define trusted runtime roots for installed and development operation.
- Do not resolve Piper from the current working directory or an uncontrolled
  `PATH` during normal packaged meeting operation.
- Create an approved manifest covering `piper.exe`, required DLLs,
  `espeak-ng-data` and configured voice-model files.
- Verify SHA-256 values before starting Piper.
- Protect the manifest through an approved release-signing or equivalent trust
  mechanism; a user-writable unsigned manifest is not sufficient.
- Fail closed when an executable, DLL or model is missing, outside an approved
  root or fails integrity verification.
- Return a sanitized error without executing the rejected component.
- Document the approved Piper version and source.

#### Verification evidence required

- A test proves that a Piper path outside an approved runtime root is rejected.
- A test proves that a modified Piper executable is detected before execution.
- A test proves that a modified companion DLL or voice model is detected.
- A test proves that a planted working-directory executable is ignored.
- A test proves that an approved packaged Piper runtime still launches
  successfully.
- A controlled packaged-application test records the resolved executable and
  manifest verification result without exposing confidential data.
- Release documentation records the approved Piper source, version and hashes.

#### Expected residual risk

After trusted-root enforcement, protected manifest verification and signed
release controls, same-user malware may still attempt to replace or bypass the
application itself. This broader endpoint-compromise risk cannot be fully
eliminated by Live Translator and must also rely on Windows access control,
release signing and organizational endpoint protection.

The target residual rating is:

| Likelihood | Impact | Residual score | Target rating |
| --- | --- | --- | --- |
| 1 / Unlikely | 3 / High | 3 | P2 / Medium |

### RSK-02 — Unapproved or malicious runtime model loading

**Linked threat:** THR-02  
**Affected components:** CMP-03, CMP-04, CMP-05, CMP-06, CMP-07  
**Status:** In progress  
**Treatment owner:** Kristupas (remaining integrity work)

#### Evidence

- The supported default Parakeet model maps to an application-approved
  Hugging Face repository and pinned commit revision.
- Only explicit `prepare-models` calls `snapshot_download`; meeting mode
  requires an existing prepared directory and rejects missing, incomplete or
  differently stamped assets before microphone capture.
- Parakeet model files are passed to ONNX Runtime for native parsing and
  inference.
- Argos translation packages and model files are not verified against an
  application-approved version or SHA-256 manifest.
- Piper voice models are checked for existence but not for approved hashes or
  signatures.
- Model and native-runtime dependency versions are constrained by ranges rather
  than reproduced from a complete lock file.
- Tests cover repository/revision pinning, required-file checks, custom-model
  download rejection and real resolver offline behaviour. They do not detect a
  one-byte change, malicious, oversized or incompatible model content.

#### Risk scenario

An attacker, compromised supplier or contaminated preparation process causes
Live Translator to load an unapproved, modified or malformed ASR, translation
or TTS model.

The model may manipulate transcripts or translations, cause excessive resource
consumption, crash a native runtime or attempt to exploit a vulnerability in a
native model parser.

A model file must not be treated as executable code by default. Arbitrary code
execution would normally require a separate vulnerability in the native parser
or runtime, and no such project-specific exploit was confirmed during this
review.

#### Initial assessment

| Factor | Rating | Justification |
| --- | --- | --- |
| Likelihood | 2 / Possible | Model retrieval, local caches, user-writable files and unverified build inputs create realistic substitution opportunities, but exploitation requires access to one of those preparation or storage paths. |
| Impact | 3 / High | A successful attack may manipulate meeting output, cause major unavailability or target native model-processing code. |
| Calculated score | 6 / High | Likelihood 2 multiplied by impact 3. |
| Final priority | P1 / High | No P0 override is applied because direct arbitrary code execution from a model file was not confirmed; the risk remains high because models influence confidential processing and native runtimes. |

#### Required treatment

- Define the complete set of approved ASR, translation and TTS model files.
- Pin approved model repositories, revisions and package versions.
- Generate a release manifest containing the SHA-256 hash and expected size of
  every approved model and relevant metadata file.
- Verify the manifest before model loading and fail closed on missing,
  unexpected or modified files.
- Force meeting mode to load only verified local model assets.
- Separate explicit online model preparation from offline meeting execution.
- Remove or restrict arbitrary repository-style model identifiers from normal
  production profiles.
- Lock and scan ONNX Runtime, CTranslate2, SentencePiece and related native
  dependencies.
- Define maximum accepted model and configuration sizes where technically
  practical.
- Record model source, license, revision and approval information in release
  documentation.

#### Verification evidence required

- A test proves that an approved model and metadata set is accepted.
- A test proves that a one-byte modification to each protected model type is
  detected before loading.
- A test proves that a missing or additional unapproved model file causes a
  safe failure.
- A test proves that production meeting mode rejects an unapproved remote model
  identifier.
- A controlled network test proves that verified meeting mode makes no model
  retrieval request.
- Corrupted and incompatible models are tested in an isolated environment and
  fail without uncontrolled resource use.
- The release manifest records source, revision, size and SHA-256 for every
  bundled or prepared model.
- Dependency scanning covers the native runtimes used to process the models.

#### Expected residual risk

Even approved models are processed by complex native libraries and may contain
unknown defects. Integrity verification proves that a file is the approved
file; it does not prove that the approved file is vulnerability-free.

The target residual rating is:

| Likelihood | Impact | Residual score | Target rating |
| --- | --- | --- | --- |
| 1 / Unlikely | 3 / High | 3 | P2 / Medium |

### RSK-03 — Compromised or unexpectedly changed Python dependency

**Linked threat:** THR-03  
**Affected components:** CMP-04, CMP-05, CMP-06, CMP-11, CMP-13  
**Status:** Open  
**Treatment owner:** TBD

#### Evidence

- Project dependencies are declared using version ranges rather than a complete
  reproducible lock.
- `requirements.txt` also contains version ranges and does not include package
  hashes.
- CI upgrades `pip` and installs the project and its dependencies from external
  package indexes.
- The optional build workflow may install PyInstaller and related build
  dependencies from the network.
- Several dependencies contain or load native code, including ONNX Runtime,
  CTranslate2, SentencePiece, NumPy and the audio stack.
- No automated dependency vulnerability scan, dependency review, SBOM
  generation or package-hash verification was identified.
- The versions inspected in the development environment are not guaranteed to
  be the versions installed by a future CI or release build.

#### Risk scenario

A compromised package account, malicious package release, dependency-confusion
event or unexpectedly vulnerable dependency version is retrieved during local
development, CI or release preparation.

The installed package can execute code with the developer, CI runner or
application user's permissions and may become part of the distributed
application.

This risk is distinct from RSK-15. RSK-03 covers Python and native package
dependencies, while RSK-15 covers GitHub workflow actions, token permissions
and untrusted pull-request execution.

#### Initial assessment

| Factor | Rating | Justification |
| --- | --- | --- |
| Likelihood | 2 / Possible | Package compromise is not expected during every installation, but dependencies are retrieved automatically without exact reproducibility or hash enforcement. |
| Impact | 3 / High | A malicious dependency can execute code, access confidential data or contaminate CI and distributed release artifacts. |
| Calculated score | 6 / High | Likelihood 2 multiplied by impact 3. |
| Final priority | P1 / High | The calculated priority is retained. No current dependency compromise was confirmed, so a P0 override is not justified. |

#### Required treatment

- Select one supported dependency-locking process for development, CI and
  Windows release builds.
- Resolve and record exact versions of direct and transitive dependencies.
- Use package hashes for release dependency installation where practical.
- Maintain separate reproducible lock or constraint outputs when Windows and
  Linux require different platform artifacts.
- Prevent release builds from silently resolving newer dependency versions.
- Generate an SBOM for the application and bundled runtime components.
- Add automated known-vulnerability scanning to CI.
- Add pull-request dependency review for newly introduced or updated
  dependencies.
- Define how critical dependency vulnerabilities block a build or release.
- Record approved package indexes and prevent unintended additional indexes.
- Review and update locked dependencies through an explicit, auditable process.
- Preserve the selected lock files and SBOM as release evidence.

#### Verification evidence required

- Two clean installations using the same platform lock resolve the same package
  names and versions.
- Release installation fails when a downloaded package does not match an
  expected hash.
- CI fails when the configured vulnerability scanner detects a policy-blocking
  dependency vulnerability.
- CI reports newly added or changed dependencies in a pull request.
- The generated SBOM includes direct dependencies, transitive dependencies and
  relevant native runtime packages.
- The release record links the source commit, lock-file revision, dependency
  scan result and SBOM.
- A documented update procedure demonstrates how a dependency can be upgraded,
  reviewed and re-locked without bypassing security checks.

#### Expected residual risk

Locking and hashing dependencies prevents unexpected version changes and
detects artifact replacement, but it does not prove that an approved version
contains no unknown vulnerability. Recurring vulnerability review and timely
updates remain necessary.

The target residual rating is:

| Likelihood | Impact | Residual score | Target rating |
| --- | --- | --- | --- |
| 1 / Unlikely | 3 / High | 3 | P2 / Medium |

### RSK-04 — Unsafe or unapproved Argos package installation

**Linked threat:** THR-04  
**Affected components:** CMP-01, CMP-06  
**Status:** Open  
**Treatment owner:** TBD

#### Evidence

- `argos-install` is an explicit preparation command that retrieves the remote
  Argos package index and a selected translation-package archive.
- The application does not enforce a project-approved Argos package version,
  download URL, SHA-256 hash or digital signature.
- The inspected Argos Translate 1.11.0 installation path delegates archive
  extraction without an explicit application-level destination-containment
  check.
- Installed package content is later discovered through configured, bundled or
  per-user package directories.
- Translation model files are processed by SentencePiece and CTranslate2,
  including native code.
- No dedicated project tests cover malicious archives, path traversal,
  oversized packages, unexpected files, package integrity or interrupted
  installation.
- No working archive-traversal exploit was demonstrated during this review.

#### Risk scenario

A compromised package source, modified download or intentionally crafted Argos
package is selected during explicit preparation.

The package may contain unapproved model content, unexpected files, excessive
data or archive paths intended to escape the expected installation directory.
Installed content may later be trusted and processed during offline
translation.

The absence of an application-level containment check is treated as a
validation and hardening requirement. It is not recorded as a confirmed
arbitrary-file-write vulnerability until a controlled test demonstrates the
behaviour of the exact supported dependency and Python versions.

#### Initial assessment

| Factor | Rating | Justification |
| --- | --- | --- |
| Likelihood | 2 / Possible | The workflow is explicitly invoked during preparation, but it retrieves and installs externally supplied package content without project-level version or integrity approval. |
| Impact | 3 / High | A successful malicious package may install manipulated models, overwrite user-accessible files or expose native model-processing code to hostile input. |
| Calculated score | 6 / High | Likelihood 2 multiplied by impact 3. |
| Final priority | P1 / High | The calculated priority is retained. A P0 override is not justified without confirming a direct arbitrary-file-write or code-execution path. |

#### Required treatment

- Define the approved Argos source and exact EN-DE and DE-EN package versions.
- Record expected download URLs, package metadata, licenses, sizes and SHA-256
  hashes.
- Download packages to a controlled temporary location before installation.
- Verify package integrity before opening or extracting the archive.
- Reject packages containing absolute paths, drive-qualified paths, `..`
  traversal, links or destinations outside the approved package directory.
- Enforce maximum archive size, extracted size and file-count limits.
- Extract into a new staging directory and validate the complete result before
  making it available to the application.
- Avoid partially replacing an existing working package when installation
  fails.
- Verify the installed model files against the runtime asset manifest described
  under RSK-02.
- Separate online package preparation from offline meeting execution.
- Provide a safe cleanup path for failed or incomplete installation.

#### Verification evidence required

- A valid approved EN-DE package installs successfully.
- A valid approved DE-EN package installs successfully.
- A package with an unexpected hash is rejected before extraction.
- Archives containing `../`, absolute, drive-qualified or mixed-separator
  escape paths are rejected in a controlled test.
- Archives containing unexpected links or files outside the approved allowlist
  are rejected.
- Oversized archives and excessive file counts fail safely.
- An interrupted installation does not replace an existing valid package with
  a partial package.
- The installed package is verified against the approved runtime manifest
  before translation begins.
- A controlled network test confirms that normal meeting translation does not
  contact the Argos package index.

#### Expected residual risk

Approved and safely extracted Argos packages may still contain unknown defects
or malicious behaviour not detectable through integrity checks alone.
Dependency scanning, model provenance review and native-runtime updates remain
necessary.

The target residual rating is:

| Likelihood | Impact | Residual score | Target rating |
| --- | --- | --- | --- |
| 1 / Unlikely | 3 / High | 3 | P2 / Medium |

### RSK-05 — Unexpected network access during meeting mode

**Linked threat:** THR-05  
**Affected components:** CMP-01, CMP-03, CMP-04, CMP-10  
**Status:** Mitigated  
**Treatment owner:** Kristupas (verification)

#### Evidence

- `prepare-models` is the only application command that calls the Hugging Face
  model-download function and it pins repository plus commit revision.
- Meeting mode calls `verify_local_model` and requires an existing complete
  directory before opening the microphone.
- Passing an existing directory to the inspected `onnx-asr 0.12.0` resolver
  selects its offline path and avoids its download branch.
- Offline regression tests patch Hugging Face download functions to raise and
  cover both meeting directions, missing/incomplete assets and the real resolver
  boundary.
- Manual PR #3 verification loaded the real model and both translation chains
  with the network blocked.
- No evidence was identified that meeting audio or transcripts are uploaded.
  The remaining assurance gap is packaged release-level network monitoring,
  not an identified meeting download path.

#### Risk scenario

A future code, dependency or custom-model change bypasses the local preflight or
stops treating the prepared directory as offline. Meeting startup could then
regain a model-retrieval path and violate the offline guarantee. The current
supported default fails locally instead of downloading when required files are
missing.

#### Initial assessment

| Factor | Rating | Justification |
| --- | --- | --- |
| Likelihood | 2 / Possible | Correct preparation normally supplies the model, but cache deletion, a new user profile, model changes or incomplete setup are realistic conditions. |
| Impact | 3 / High | The behaviour directly violates a mandatory offline requirement and may prevent the application from operating during a confidential meeting. No meeting-audio upload was confirmed. |
| Calculated score | 6 / High | Likelihood 2 multiplied by impact 3. |
| Final priority | P0 / Critical | Raised from the default P1 because the risk directly violates the mandatory offline meeting requirement. |

#### Required treatment

- Separate explicit online preparation from offline meeting execution.
- Add a meeting-mode preflight that resolves every required model, executable,
  DLL, translation package and voice file before microphone capture begins.
- Verify required assets against the approved integrity manifest.
- Configure the supported model-loading stack to use local-only resolution
  during meeting mode.
- Fail closed with a clear local error when a required model is missing instead
  of attempting retrieval.
- Ensure profile changes cannot silently select an unprepared remote model.
- Do not rely only on user instructions or the assumption that the cache is
  already populated.
- Add application-level network isolation where technically practical without
  requiring administrator privileges.
- Document which commands require Internet access and which commands are
  guaranteed to remain local.
- Review all runtime dependencies for additional network-capable behaviour,
  including telemetry controlled outside the application.

#### Verification evidence required

- A prepared meeting starts and operates successfully while all outbound
  network access is blocked.
- Network monitoring records no unexpected DNS, TCP, HTTP or HTTPS activity
  during a representative meeting in both language directions.
- Removing a required Parakeet file causes meeting startup to fail before
  microphone capture and does not produce a network request.
- Selecting an unprepared model identifier causes a local failure and does not
  initiate retrieval.
- `doctor --prepare-models` can still retrieve required assets during an
  explicitly online preparation workflow.
- After successful preparation, repeated meeting runs require no Internet
  access.
- Tests distinguish preparation mode from meeting mode and prevent future code
  changes from enabling online model resolution during meetings.
- Controlled tests cover the supported Windows 10 and Windows 11 environments.

#### Expected residual risk

Application-level local-only loading can prevent intended model retrieval, but
the project cannot automatically prove that the entire operating system,
drivers or endpoint software generate no network traffic. The security claim
must therefore be scoped to Live Translator and its supported runtime
components.

The target residual rating is:

| Likelihood | Impact | Residual score | Target rating |
| --- | --- | --- | --- |
| 1 / Unlikely | 2 / Medium | 2 | P3 / Low |

### RSK-06 — Disclosure of persisted meeting diagnostic data

**Linked threat:** THR-06  
**Affected components:** CMP-01, CMP-02, CMP-10  
**Status:** In progress  
**Treatment owner:** TBD (policy/ACL follow-up)

#### Evidence

- Meeting diagnostic persistence is disabled by default and enabled only by an
  explicit flag, configuration choice or explicit diagnostic path.
- Activation warns that raw audio and plaintext transcript/translation files
  will be written and names the location and retention limits.
- Relative destinations are placed below the per-user diagnostics root;
  traversal is rejected and resolved symlink/junction targets outside the root
  are excluded from cleanup and purge.
- Default age and total-size retention are enforced, and
  `purge-diagnostics` provides confirmed cleanup with a safety prompt.
- `.gitignore` covers the application diagnostic directory and generated
  segment text/audio patterns, but remains defense in depth rather than access
  control.
- Tests cover default-off behaviour, warnings, locations, traversal, retention,
  purge and link containment. They do not prove Windows ACL policy, encryption,
  backup/sync behaviour or independent audio/text selection.

#### Risk scenario

A user enables meeting diagnostics to investigate recognition or translation
quality during a confidential meeting.

Raw audio, source transcripts and translations remain in the selected
filesystem location after the meeting. Another process running as the same
user, an unauthorized person using the workstation, a backup tool, sync client
or accidental repository operation obtains the retained files.

#### Initial assessment

| Factor | Rating | Justification |
| --- | --- | --- |
| Likelihood | 2 / Possible | Diagnostic storage requires an explicit option, but using diagnostics during troubleshooting is a realistic project and support activity. |
| Impact | 3 / High | Stored WAV and text files may disclose complete confidential meeting content and personal voice data. |
| Calculated score | 6 / High | Likelihood 2 multiplied by impact 3. |
| Final priority | P1 / High | The calculated priority is retained because persistence is opt-in rather than normal meeting behaviour. Reassess as P0 if diagnostics become routine for confidential meetings. |

#### Required treatment

- Keep meeting diagnostic persistence disabled by default.
- Display a clear warning before diagnostic capture begins.
- Require explicit confirmation or an explicit diagnostic command intended for
  sensitive-data capture.
- Use an application-managed per-user diagnostic root by default.
- Validate custom paths and document when custom storage is permitted.
- Create diagnostic directories and files with the most restrictive practical
  per-user Windows permissions.
- Prevent diagnostic output from following untrusted links or junctions where
  technically practical.
- Define a default retention period and automatic cleanup process.
- Provide a clear command or workflow for securely removing diagnostic
  artifacts.
- Store the minimum information required for the diagnostic purpose.
- Allow audio, transcripts and translations to be enabled separately where
  possible.
- Avoid storing transcript or translation text when audio-only diagnostics are
  sufficient.
- Define when encryption is required and how encryption keys would be managed;
  do not claim that encryption is implemented without a workable key-management
  design.
- Keep public calibration datasets separate from real meeting diagnostics.
- Document whether backups, OneDrive or other synchronization tools are
  approved diagnostic destinations.
- Ensure build and Git processes exclude generated diagnostic data through
  explicit content inspection in addition to `.gitignore`.

#### Verification evidence required

- Normal meeting mode creates no diagnostic WAV or text files.
- Diagnostic capture cannot start without an explicit user action and warning.
- Created files are accessible only according to the approved Windows
  per-user access policy.
- A configured retention test removes expired artifacts.
- Manual cleanup removes all files associated with the selected diagnostic
  session.
- Audio-only and text-disabled modes do not create transcript or translation
  files.
- Invalid, unsafe or disallowed diagnostic paths fail before microphone capture.
- Tests cover links, junctions and custom directory behaviour where supported.
- Repository and release checks detect diagnostic artifacts under unexpected
  names or locations.
- Documentation states what is collected, where it is stored, why it is needed
  and when it is deleted.

#### Expected residual risk

Authorized diagnostic users may still deliberately retain or copy diagnostic
data, and operating-system backups or endpoint software may preserve deleted
files. Policy, access control and user training remain necessary in addition to
application cleanup.

The target residual rating is:

| Likelihood | Impact | Residual score | Target rating |
| --- | --- | --- | --- |
| 1 / Unlikely | 3 / High | 3 | P2 / Medium |

### RSK-07 — Disclosure through terminal output or terminal logging

**Linked threat:** THR-07  
**Affected components:** CMP-01, CMP-10  
**Status:** Mitigated  
**Treatment owner:** Kristupas (verification)

#### Evidence

- Normal meeting operation prints only content-free phrase number, audio length,
  readiness timing and optional low-confidence state.
- `--verbose` adds operational telemetry but does not print source or target
  meeting text.
- `--show-text` is the only meeting option that prints source transcripts and
  translations and it warns about terminal scrollback and screen sharing.
- Regression tests cover default mode, verbose-only, show-text-only and combined
  flag behaviour.
- The application does not control PowerShell scrollback, host logging, screen
  recording, remote-support tooling or endpoint-monitoring retention.

#### Risk scenario

An authorized user explicitly enables `--show-text` during a confidential
meeting.

An unauthorized observer, screen-sharing participant, remote-support session,
screen-capture tool, terminal-logging feature or later workstation user obtains
the displayed or retained terminal content.

Verbose errors or diagnostics may additionally disclose local paths, device
details and model information.

#### Initial assessment

| Factor | Rating | Justification |
| --- | --- | --- |
| Likelihood | 2 / Possible | Terminal display occurs during normal operation, but disclosure requires an unauthorized observer, retained output, screen capture or external logging. |
| Impact | 3 / High | Terminal content may reveal a substantial portion of a confidential meeting, including both the original and translated meaning. |
| Calculated score | 6 / High | Likelihood 2 multiplied by impact 3. |
| Final priority | P1 / High | The calculated priority is retained. The terminal user is normally authorized, so the additional conditions required for unauthorized disclosure do not justify a P0 override. |

#### Required treatment

- Decide with the project stakeholder whether normal meeting transcripts and
  translations must be visible in the terminal.
- Add a privacy-preserving meeting display mode if continuous text visibility
  is not required.
- Allow source text, translated text and technical diagnostics to be controlled
  separately.
- Keep verbose diagnostic output disabled by default.
- Avoid printing full sensitive text in error messages.
- Sanitize errors that expose unnecessary local paths, environment details or
  model repository information.
- Display a warning when starting a mode that continuously prints meeting
  content.
- Document the effect of terminal scrollback, screen sharing, host logging and
  screen-recording tools.
- Recommend a dedicated terminal session for confidential meetings.
- Do not claim that clearing the terminal securely deletes content already
  captured by the operating system or external software.
- Coordinate the application policy with organizational endpoint and logging
  requirements.

#### Verification evidence required

- A privacy mode completes a representative meeting without printing source or
  translated meeting text.
- Source-text, translated-text and verbose-output settings behave independently
  as documented.
- Normal non-verbose errors do not contain transcript content.
- Diagnostic errors expose only the minimum paths and configuration details
  required for troubleshooting.
- Default meeting behaviour matches the stakeholder-approved privacy decision.
- Documentation warns that terminal output may be retained by the terminal host
  or external endpoint tools.
- A release test verifies both the standard display mode and the
  privacy-preserving mode.

#### Expected residual risk

An authorized user can still copy, photograph, screen-record or otherwise
retain information that is legitimately displayed. Live Translator cannot
fully control external terminal hosts, endpoint agents or screen-capture
software.

The target residual rating is:

| Likelihood | Impact | Residual score | Target rating |
| --- | --- | --- | --- |
| 1 / Unlikely | 3 / High | 3 | P2 / Medium |

### RSK-08 — Recoverable Piper temporary audio after abnormal termination

**Linked threat:** THR-08  
**Affected components:** CMP-07, CMP-10  
**Status:** Open  
**Treatment owner:** TBD

#### Evidence

- Piper produces synthesized speech through a temporary WAV file.
- The WAV contains translated meeting speech in plaintext audio form.
- Normal rendering attempts to remove the temporary file in a `finally` block.
- The `finally` cleanup reduces normal retention but cannot run after every
  process termination, system shutdown or fatal runtime failure.
- No application-managed private temporary directory, startup cleanup or
  retention scan was identified.
- No test simulates process termination between WAV creation and cleanup.
- The actual permissions and lifecycle of the operating-system temporary path
  have not been validated on supported Windows versions.

#### Risk scenario

Piper creates a temporary WAV containing a translated meeting phrase. Before
normal cleanup completes, Live Translator crashes, is forcibly terminated, the
workstation restarts or file deletion fails.

The plaintext WAV remains in temporary storage and can later be recovered or
read by another process with access to the same user's files.

#### Initial assessment

| Factor | Rating | Justification |
| --- | --- | --- |
| Likelihood | 2 / Possible | Normal cleanup exists, but crashes, force-close events, restarts and file-lock failures are realistic desktop application conditions. |
| Impact | 2 / Medium | A remaining file may expose a confidential translated phrase, but each temporary file normally contains a limited segment rather than the complete meeting. |
| Calculated score | 4 / Medium | Likelihood 2 multiplied by impact 2. |
| Final priority | P2 / Medium | The calculated priority is retained because normal cleanup already reduces exposure and an additional abnormal event is required. |

#### Required treatment

- Determine whether the supported Piper interface can return audio without a
  persistent filesystem file.
- Prefer an in-memory or pipe-based interface if it is supported and does not
  introduce unacceptable latency or instability.
- If a file remains necessary, use an application-managed per-user temporary
  directory rather than an uncontrolled general-purpose location.
- Apply restrictive per-user permissions to the temporary directory.
- Use unpredictable file names and avoid exposing transcript content in file
  names.
- Track temporary files created by the application.
- Attempt cleanup during normal exit and error handling.
- Scan the application temporary directory during startup and remove stale
  application-owned artifacts according to the approved policy.
- Handle deletion failures without printing confidential text.
- Document that ordinary file deletion may not guarantee forensic erasure,
  especially on SSDs, backups or synchronized storage.
- Do not implement a custom “secure delete” claim without evidence that it is
  effective on supported storage systems.

#### Verification evidence required

- A successful synthesis leaves no application-owned temporary WAV.
- A simulated Piper failure triggers cleanup.
- A simulated deletion failure is reported without exposing translated text.
- Startup cleanup detects and removes stale application-owned temporary files.
- Cleanup does not delete unrelated files from the temporary directory.
- Created temporary files and directories follow the approved per-user access
  policy.
- A forced-termination test documents what remains and confirms that the next
  startup handles it safely.
- Any in-memory replacement is benchmarked to confirm that it preserves
  acceptable translation latency.

#### Expected residual risk

Operating systems, storage devices, backups and endpoint software may retain
copies of data after application-level deletion. The application can minimize
persistence but cannot guarantee forensic erasure on every supported
workstation.

The target residual rating is:

| Likelihood | Impact | Residual score | Target rating |
| --- | --- | --- | --- |
| 1 / Unlikely | 2 / Medium | 2 | P3 / Low |

### RSK-09 — Profile path escape or security-sensitive configuration tampering

**Linked threat:** THR-09  
**Affected components:** CMP-01, CMP-07, CMP-09  
**Status:** Open  
**Treatment owner:** TBD

#### Evidence

- `default_profile_path()` constructs a profile path from a supplied profile
  name without enforcing that the resolved result remains inside the per-user
  profile directory.
- Controlled path-resolution tests confirmed that `..`, directory separators
  and absolute-path-like names can escape the intended profile directory.
- The application separately supports explicit configuration paths through
  `--config` and `--config-out`.
- YAML is parsed with `yaml.safe_load`.
- Unknown configuration sections and settings are rejected.
- Parsed values are converted into typed configuration objects and semantic
  validation is performed.
- Valid configuration can still select model paths, Piper executable paths,
  audio devices, diagnostic locations and resource-related settings.
- Profile files are stored in a user-writable per-user directory.
- Profile writes are not atomic.
- No application-level profile signature or integrity verification was
  identified.
- Existing tests do not cover profile-name containment, symlinks, junctions,
  file ACLs, atomic replacement or all upper bounds for resource-related
  values.

#### Risk scenario

A user supplies a specially formed profile name, or a process running as the
same Windows user modifies a profile file.

Live Translator loads configuration from an unintended location or accepts
security-sensitive values that select an untrusted executable, model,
diagnostic directory or audio endpoint.

The profile-path escape alone does not automatically provide additional
filesystem permissions, and explicit arbitrary configuration paths are already
supported through `--config`. The main risk comes from treating validly parsed
configuration as a source of trust for downstream runtime components.

#### Initial assessment

| Factor | Rating | Justification |
| --- | --- | --- |
| Likelihood | 2 / Possible | Exploitation requires local CLI, profile-file or same-user access, but profiles and their security-sensitive values are intentionally user-controlled. |
| Impact | 3 / High | Modified configuration can influence executable and model loading, confidential diagnostic persistence and meeting-audio routing. |
| Calculated score | 6 / High | Likelihood 2 multiplied by impact 3. |
| Final priority | P1 / High | The calculated priority is retained. A P0 override is not applied because high impact depends on downstream components failing to enforce their own trust boundaries. |

#### Required treatment

- Define an allowed format for named profiles, such as a conservative set of
  letters, numbers, `_` and `-`.
- Reject profile names containing path separators, `..`, drive prefixes,
  rooted paths or other path syntax.
- Resolve the generated named-profile path and verify that it remains within
  the intended per-user profile directory.
- Account for Windows path normalization, case handling, symlinks and junctions
  where technically practical.
- Keep `--config` as an explicit arbitrary-path feature if the project requires
  it, but clearly distinguish it from named-profile lookup.
- Do not treat a valid YAML file as proof that referenced executables, models
  or output paths are trusted.
- Enforce trusted roots and integrity checks inside the downstream Piper,
  model-loading and diagnostic components.
- Write generated profiles atomically to avoid partial configuration after
  interruption.
- Preserve the intended per-user Windows access policy when creating or
  replacing profile files.
- Define upper and lower bounds for all settings that influence CPU, memory,
  queue size, audio duration, subprocess behaviour or diagnostic output.
- Return sanitized validation errors before audio capture or runtime process
  startup.

#### Verification evidence required

- Named profiles containing `..`, `/`, `\`, drive prefixes and rooted paths are
  rejected.
- A valid simple profile name resolves inside the per-user profile directory.
- Path containment tests cover relevant Windows normalization and case
  behaviour.
- Symlink or junction escape behaviour is tested or explicitly documented as a
  residual platform limitation.
- `--config` continues to support an explicit approved custom path without
  weakening named-profile containment.
- A profile referencing an untrusted Piper executable is rejected by the Piper
  trusted-root and integrity control.
- A profile referencing an unapproved model is rejected by the model-integrity
  control.
- Interrupted profile generation does not replace a valid profile with a
  partial file.
- Extreme numeric values are rejected before resource allocation or subprocess
  execution.

#### Expected residual risk

A process already running with the same user's permissions can often modify
user-owned configuration and may also attempt to modify the application
itself. Profile containment reduces accidental and path-based misuse, but
strong protection requires downstream components to independently validate
every security-sensitive asset and destination.

The target residual rating is:

| Likelihood | Impact | Residual score | Target rating |
| --- | --- | --- | --- |
| 1 / Unlikely | 2 / Medium | 2 | P3 / Low |

### RSK-10 — Incorrect or unauthorized Windows audio routing

**Linked threat:** THR-10  
**Affected components:** CMP-01, CMP-02, CMP-08, CMP-09  
**Status:** Open  
**Treatment owner:** TBD

#### Evidence

- Live Translator captures audio from a selected physical input device and
  sends synthesized translation to a selected Windows playback endpoint.
- VB-CABLE exposes paired playback and recording endpoints named `CABLE Input`
  and `CABLE Output`.
- The meeting application must use the matching VB-CABLE recording endpoint as
  its microphone.
- The application contains device-role checks and cable-pair selection logic.
- Device resolution relies partly on Windows friendly names and partial-name
  matching rather than a cryptographically strong device identity.
- A synthetic `route-test` checks selected playback-to-recording behaviour.
- Existing route tests use mocked devices and synthetic audio.
- No test verifies a real Teams meeting, actual installed VB-CABLE driver,
  automatic device switching, Windows “Listen to this device” settings or
  access by another local recording application.
- Live Translator cannot directly enforce the microphone selected inside
  Microsoft Teams.

#### Risk scenario

A user, Windows update, meeting application or device-selection ambiguity
causes Teams or Live Translator to select the wrong microphone or playback
endpoint.

Raw untranslated speech may be sent directly into the meeting, translated
speech may be sent to an unintended device, or another locally authorized
application may record the VB-CABLE output.

A similarly named or changed audio endpoint may also be mistaken for the
approved device.

#### Initial assessment

| Factor | Rating | Justification |
| --- | --- | --- |
| Likelihood | 2 / Possible | Device-role logic and route testing reduce mistakes, but friendly-name ambiguity, Teams settings and Windows device changes remain realistic. |
| Impact | 3 / High | Incorrect routing may expose confidential raw or translated meeting audio to unintended participants, devices or local applications. |
| Calculated score | 6 / High | Likelihood 2 multiplied by impact 3. |
| Final priority | P1 / High | The calculated priority is retained because existing routing controls reduce likelihood and exploitation requires an incorrect or changed endpoint configuration. |

#### Required treatment

- Define the approved physical microphone, translated playback endpoint and
  meeting recording endpoint for each supported workstation.
- Prefer stable Windows endpoint identifiers over friendly-name-only matching
  where the audio API provides suitable identifiers.
- Treat partial friendly-name matching as a usability fallback, not a strong
  trust decision.
- Add a pre-meeting routing check that confirms input and translated-output
  roles before microphone capture begins.
- Warn and fail safely when multiple endpoints ambiguously match a configured
  name.
- Detect relevant device changes between setup, route testing and meeting
  startup where technically practical.
- Require a successful route test during workstation provisioning and after
  audio-driver or Windows changes.
- Document the exact Teams microphone and speaker configuration.
- Document that Teams automatic device switching can invalidate a previously
  correct route.
- Verify that Windows “Listen to this device” and similar monitoring settings
  do not create an unintended path.
- Confirm the approved VB-CABLE version, download source and Windows driver
  signature.
- Document that other same-user applications with microphone permission may be
  able to access a system-wide recording endpoint.
- Provide a clear emergency stop or mute procedure when routing is incorrect.

#### Verification evidence required

- A real Windows workstation test confirms the selected physical microphone.
- A real VB-CABLE test confirms that translated audio reaches only the intended
  paired recording endpoint.
- A real Teams test confirms that Teams receives translated audio and does not
  directly receive the physical microphone.
- Both EN-DE and DE-EN directions are tested.
- Ambiguous friendly-name matches fail with a clear error.
- Disconnecting, renaming or changing a required device causes a safe preflight
  failure.
- A post-update test covers relevant Windows, Teams and VB-CABLE changes.
- Windows privacy and monitoring settings are recorded for the approved
  workstation configuration.
- The validated VB-CABLE package version and driver signature are included in
  workstation or release evidence.

#### Expected residual risk

Live Translator cannot fully control device changes or microphone selection
inside external meeting applications. Other software running with the same
user's audio permissions may also access available recording endpoints.

The target residual rating is:

| Likelihood | Impact | Residual score | Target rating |
| --- | --- | --- | --- |
| 1 / Unlikely | 3 / High | 3 | P2 / Medium |

### RSK-11 — Resource exhaustion or blocked runtime processing

**Linked threat:** THR-11  
**Affected components:** CMP-02, CMP-03, CMP-05, CMP-07, CMP-09  
**Status:** In progress  
**Treatment owner:** TBD (remaining resource limits)

#### Evidence

- Realtime recognition and playback queues have configured maximum sizes.
- Selected Parakeet empty and partial-decode recovery paths are bounded.
- VAD and rolling speech chunking use configured segment durations and queue
  behaviour.
- Piper subprocess calls do not have an application-level timeout.
- Piper `length_scale` does not have an identified application-level upper
  bound.
- Several configuration values influencing duration, queues or resource use do
  not have complete upper-bound validation.
- ONNX Runtime and other native model runtimes execute inside the main
  application process without application-level CPU or memory quotas.
- Malformed, oversized or incompatible models have not been tested.
- Diagnostic capture can continue writing audio and text artifacts without an
  application-level disk quota.
- Existing tests use short synthetic data and mocked runtimes rather than
  long-running resource-pressure scenarios.

#### Risk scenario

A malformed model, extreme configuration, unusually long or noisy input,
blocked Piper process, high inference cost or prolonged diagnostic session
consumes excessive CPU, memory, time or disk space.

Live translation becomes increasingly delayed, stops processing new phrases,
drops useful audio, fills local storage or requires the application to be
terminated.

The condition may be accidental or deliberately triggered by a local user,
configuration change or adversarial meeting input.

#### Initial assessment

| Factor | Rating | Justification |
| --- | --- | --- |
| Likelihood | 2 / Possible | Existing queue and recovery bounds reduce common accumulation, but subprocess, model, configuration and diagnostic resource limits remain incomplete. |
| Impact | 2 / Medium | The primary effect is delayed or unavailable translation for one workstation or meeting. No broader safety-critical availability requirement was established. |
| Calculated score | 4 / Medium | Likelihood 2 multiplied by impact 2. |
| Final priority | P2 / Medium | The calculated priority is retained. Reassess the impact if Live Translator becomes operationally critical. |

#### Required treatment

- Add a timeout to Piper subprocess execution.
- Terminate and clean up Piper safely when the timeout expires.
- Define upper and lower bounds for all duration, threshold, queue-size,
  thread-count, gain and synthesis-speed settings.
- Reject extreme settings before audio capture, model loading or subprocess
  execution.
- Define a maximum accepted speech-segment duration and maximum audio sample
  count at each processing boundary.
- Define maximum supported model and metadata sizes where technically
  practical.
- Monitor recognition, translation, synthesis and queue-delay timings without
  logging confidential text.
- Detect when processing latency consistently exceeds incoming phrase timing.
- Define safe behaviour for overloaded queues, including what may be dropped
  and how the user is warned.
- Limit diagnostic artifact count, size or session duration according to the
  retention policy.
- Check available disk space before starting persistent diagnostic capture.
- Ensure failed or timed-out work does not leave child processes or temporary
  files.
- Document minimum supported workstation CPU, memory and storage requirements.
- Preserve the project latency requirement when introducing security checks.

#### Verification evidence required

- A deliberately blocked Piper process is terminated after the configured
  timeout.
- Timeout handling leaves no orphan Piper process or temporary WAV.
- Extreme configuration values are rejected with clear errors.
- Maximum supported audio segments complete within documented resource limits.
- Prolonged speech and noise tests do not cause unbounded queue or memory
  growth.
- Corrupted and oversized model tests fail safely in an isolated environment.
- Queue-pressure tests document dropped-work behaviour and user notification.
- Diagnostic capture stops or warns according to approved disk and retention
  limits.
- Long-running tests measure memory, CPU, queue depth and end-to-end latency.
- Security controls are benchmarked to confirm that they do not introduce
  unacceptable translation delay.

#### Expected residual risk

Native runtimes and operating-system scheduling can still experience
unexpected performance problems. Resource limits reduce uncontrolled
consumption but cannot guarantee real-time performance on every workstation or
for every audio input.

The target residual rating is:

| Likelihood | Impact | Residual score | Target rating |
| --- | --- | --- | --- |
| 1 / Unlikely | 2 / Medium | 2 | P3 / Low |

### RSK-12 — Misleading output from incorrect or low-confidence recognition

**Linked threat:** THR-12  
**Affected components:** CMP-03, CMP-04, CMP-06, CMP-07  
**Status:** Open  
**Treatment owner:** TBD

#### Evidence

- Parakeet recognition produces transcript text and confidence-related data.
- The application can mark accepted source text as `low_confidence`.
- Low-confidence text may continue into Argos translation instead of being
  rejected.
- Translated text may continue into Piper speech synthesis.
- The terminal can show a low-confidence marker beside the source text.
- Synthesized translated audio does not provide an equivalent visible marker
  to remote meeting participants.
- Recognition quality varies with language, accent, microphone quality, noise,
  phrase length and speech segmentation.
- Previous project evaluation found German speech recognition weaker than
  English under the tested conditions.
- Short utterances and language switching may produce misleading recognition
  or translation.
- Existing tests cover selected confidence and rejection behaviour using fake
  results but do not prove real-world adversarial-audio robustness.

#### Risk scenario

A participant speaks an ambiguous, noisy, accented, short or deliberately
difficult phrase.

Live Translator accepts a low-confidence or incorrect transcript, translates
it and produces synthesized speech. A receiving participant hears the
translation without knowing that the source recognition was uncertain and
treats the output as authoritative.

This risk may result from ordinary model error and does not require a malicious
participant.

#### Initial assessment

| Factor | Rating | Justification |
| --- | --- | --- |
| Likelihood | 3 / Likely | Recognition and translation errors are expected under realistic audio, language and segmentation conditions. |
| Impact | 2 / Medium | Incorrect output may cause misunderstanding or a wrong meeting decision, but the current approved use is not established as safety-critical or automatically action-triggering. |
| Calculated score | 6 / High | Likelihood 3 multiplied by impact 2. |
| Final priority | P1 / High | The calculated priority is retained because the condition is likely and confidence information is not preserved through every output channel. |

#### Required treatment

- Define the approved use cases and decisions for which machine translation may
  be relied upon.
- State that Live Translator output is assistive and must not be treated as an
  authoritative transcript or instruction.
- Define a stakeholder-approved policy for low-confidence source text.
- Decide whether low-confidence phrases should be translated, repeated,
  suppressed or presented with a warning.
- Preserve confidence state through translation and every user-visible output
  path where technically possible.
- Provide an audible or meeting-visible indication when synthesized output is
  based on low-confidence recognition, if this can be done without making the
  meeting unusable.
- Avoid presenting a translated phrase as normal when the source was rejected
  or materially uncertain.
- Allow the user to request repetition or correction.
- Benchmark thresholds separately for EN-DE and DE-EN.
- Test representative real speech, accents, microphones, background noise,
  short phrases and language switching.
- Do not lower confidence thresholds only to improve apparent transcript
  coverage without measuring false or misleading output.
- Do not use translated output to trigger automated security-sensitive actions.
- Reassess impact before approving legal, medical, financial, emergency or
  other high-consequence use.

#### Verification evidence required

- Real-speech tests cover both translation directions.
- Tests include noise, accents, short utterances, silence and language
  switching.
- Every output path behaves according to the approved low-confidence policy.
- Rejected source text does not produce an apparently valid synthesized
  translation.
- Remote meeting participants receive the approved uncertainty indication or
  the uncertain phrase is suppressed.
- Threshold changes include recorded precision, rejection and latency evidence.
- Documentation clearly states limitations and prohibited high-consequence
  uses.
- User testing confirms that warnings are understandable without causing
  unacceptable meeting interruption.

#### Expected residual risk

Speech recognition and machine translation are probabilistic and cannot be
made perfectly accurate. Controls can make uncertainty visible and limit how
the output is used, but some incorrect translations will remain possible.

The target residual rating is:

| Likelihood | Impact | Residual score | Target rating |
| --- | --- | --- | --- |
| 2 / Possible | 2 / Medium | 4 | P2 / Medium |

### RSK-13 — Unexpected or modified files included in release artifacts

**Linked threat:** THR-13  
**Affected components:** CMP-10, CMP-11, CMP-12  
**Status:** Open  
**Treatment owner:** TBD

#### Evidence

- The PyInstaller specification conditionally includes complete local
  `models/argos`, `models/tts`, `tools/piper` and `docs` directories.
- `collect_all` gathers broad data, binaries and hidden imports from selected
  dependencies.
- Local files do not need to be committed to Git before PyInstaller can include
  them.
- Internal security documentation under `docs` is currently within the
  packaging scope.
- The Windows build script checks that selected required files exist but does
  not enforce a complete approved-input allowlist.
- Inno Setup recursively packages the complete `dist/LiveTranslator` directory.
- The installer build script checks only that the main executable exists before
  compiling the installer.
- No automated final-content inventory, clean-workspace proof, malware scan,
  asset-hash verification or unexpected-file rejection was identified.
- A complete clean build and installer-content inspection has not yet been
  performed.

#### Risk scenario

A developer creates a release from a workstation containing stale, modified,
test, diagnostic, untracked or malicious local files.

PyInstaller includes the unexpected content in `dist/LiveTranslator`, and Inno
Setup packages it into the installer. The release is then distributed without
detecting that its contents differ from the approved source and asset set.

The contamination may be accidental or caused by a compromised local build
environment.

#### Initial assessment

| Factor | Rating | Justification |
| --- | --- | --- |
| Likelihood | 2 / Possible | Broad recursive packaging and local builds make accidental contamination realistic, but release creation is an explicit controlled activity rather than normal meeting behaviour. |
| Impact | 3 / High | A contaminated release may distribute modified code, DLLs, models or internal information to multiple users. |
| Calculated score | 6 / High | Likelihood 2 multiplied by impact 3. |
| Final priority | P1 / High | The calculated priority is retained for the current controlled demonstration stage. A confirmed or imminent contaminated official release must be treated as P0. |

#### Required treatment

- Build official artifacts only from a clean, documented and approved build
  environment.
- Require a clean source checkout at the approved commit before release
  packaging.
- Do not package directly from arbitrary developer working directories.
- Replace broad directory inclusion with the narrowest practical allowlist of
  required runtime files.
- Remove internal security documentation and development-only files from the
  application package unless there is an approved distribution reason.
- Define the exact expected contents of `dist/LiveTranslator`.
- Generate a machine-readable release manifest containing relative path, size
  and SHA-256 for every distributed file.
- Reject unexpected, missing or modified files before installer creation.
- Clean or recreate build and `dist` directories before every official build.
- Generate an SBOM for Python, native and bundled runtime components.
- Scan the completed application directory and installer using the approved
  security tooling.
- Link every release to the source commit, dependency lock, model manifest,
  build-tool versions, SBOM and scan results.
- Prevent installer creation when required verification evidence is missing.
- Keep release signing separate from build-content approval: signing a
  contaminated artifact only proves who signed the contaminated artifact.

#### Verification evidence required

- A clean build produces a recorded inventory of every packaged file.
- Adding an unexpected file to a source asset directory causes release
  verification to fail.
- Removing or modifying a required file causes release verification to fail.
- Internal security documentation and development-only artifacts are absent
  from the approved distribution.
- Repeated clean builds use the same approved source, dependency and asset
  inputs.
- The generated manifest matches the complete PyInstaller distribution and
  installer contents.
- Malware and policy scans complete before installer signing.
- Release evidence records the source commit, tool versions, SBOM, manifests
  and scan results.
- Installer creation is blocked when the build workspace is dirty or the
  content inventory is not approved.

#### Expected residual risk

A clean and verified build process reduces accidental contamination but cannot
fully eliminate compromise of the build host, compiler, packaging tool or
signing environment. Those risks require secured build infrastructure,
restricted release permissions and recurring supply-chain review.

The target residual rating is:

| Likelihood | Impact | Residual score | Target rating |
| --- | --- | --- | --- |
| 1 / Unlikely | 3 / High | 3 | P2 / Medium |

### RSK-14 — Distribution of an unsigned or unofficial application

**Linked threat:** THR-14  
**Affected components:** CMP-11, CMP-12  
**Status:** Open  
**Treatment owner:** TBD

#### Evidence

- The current PyInstaller application executable is unsigned.
- The current Inno Setup installer is unsigned.
- No configured Inno Setup `SignTool` was identified.
- No signed-uninstaller verification process was identified.
- No documented organizational code-signing certificate or managed signing
  service was confirmed.
- No automated release step verifies Authenticode signatures before
  distribution.
- No official release channel, artifact-hash publication or user-verification
  procedure was identified.
- The current documentation limits the unsigned artifacts to controlled
  internal demonstration.
- Windows SmartScreen behaviour depends on local policy and reputation and is
  not equivalent to application-level publisher verification.

#### Risk scenario

An attacker or accidental distribution process provides a modified, outdated
or unofficial executable or installer using the Live Translator name.

Because the artifact has no verified publisher signature, a user cannot
reliably distinguish it from the approved release and executes it with their
Windows user permissions.

A valid signature would prove the signing identity and detect post-signing
modification. It would not prove that the signed build was free from
vulnerabilities or contamination.

#### Initial assessment

| Factor | Rating | Justification |
| --- | --- | --- |
| Likelihood | 2 / Possible | Controlled internal distribution reduces exposure, but unsigned files can realistically be replaced, confused or redistributed through normal sharing channels. |
| Impact | 3 / High | A substituted executable or installer can run attacker-controlled code and access data available to the user. |
| Calculated score | 6 / High | Likelihood 2 multiplied by impact 3. |
| Final priority | P1 / High | The calculated priority is retained for the controlled demonstration stage. Wider official distribution must not proceed without approved signing and release verification. |

#### Required treatment

- Confirm whether the organization already has an approved Windows
  code-signing certificate or managed signing service.
- Define who is authorized to request and approve signing.
- Protect signing credentials using the organization's approved key-management
  process.
- Authenticode-sign the main application executable.
- Authenticode-sign the Inno Setup installer.
- Configure and verify signing of the generated uninstaller.
- Use SHA-256 signing and an approved trusted timestamp service.
- Verify signatures after signing and again before publication.
- Bind signing to the approved release manifest, source commit, SBOM,
  dependency scan and malware-scan results.
- Publish releases only through an approved internal distribution channel.
- Publish or retain SHA-256 hashes for independent release verification.
- Document how users and support staff verify the publisher and signature.
- Block release when signing or post-signing verification fails.
- Define certificate-expiry, revocation, key-compromise and emergency
  re-signing procedures.
- Do not use signing as a substitute for clean-build and content-verification
  controls from RSK-13.

#### Verification evidence required

- Windows reports the expected organization as the verified publisher for
  `LiveTranslator.exe`.
- Windows reports the expected organization as the verified publisher for the
  installer and uninstaller.
- Signature verification succeeds on supported Windows 10 and Windows 11
  systems.
- Modifying one byte of a signed artifact causes signature verification to
  fail.
- Release automation blocks unsigned, incorrectly signed or expired artifacts
  according to the approved policy.
- The timestamp remains valid after the signing certificate expires, subject
  to certificate and timestamp trust.
- The published artifact hash matches the signed artifact delivered through
  the approved channel.
- Release evidence links the signature to the approved source commit, manifest,
  SBOM and security scan.
- Key-access and emergency-revocation procedures are documented and reviewed.

#### Expected residual risk

A valid signature does not prevent an authorized signing process from signing a
contaminated build, and it does not stop same-user malware from replacing files
after installation. Clean-build controls, protected signing operations,
runtime integrity verification and endpoint security remain necessary.

The target residual rating is:

| Likelihood | Impact | Residual score | Target rating |
| --- | --- | --- | --- |
| 1 / Unlikely | 3 / High | 3 | P2 / Medium |

### RSK-15 — CI workflow or pull-request supply-chain compromise

**Linked threat:** THR-15  
**Affected components:** CMP-11, CMP-13  
**Status:** Open  
**Treatment owner:** TBD

#### Evidence

- The workflow runs for pull requests, pushes to `main` and manual dispatch.
- Pull-request source and test code are installed and executed on the runner.
- The workflow uses GitHub-hosted Windows and Ubuntu runners.
- The workflow uses `pull_request`, not `pull_request_target`.
- No repository secrets are directly referenced by the workflow.
- The workflow does not currently build, sign or publish release artifacts.
- `actions/checkout` and `actions/setup-python` use mutable major-version tags
  instead of immutable full commit SHAs.
- No explicit least-privilege `permissions` block is declared.
- Actual default `GITHUB_TOKEN` permissions depend on repository or
  organization settings that are not visible in the workflow file.
- Python dependencies are installed from external package indexes; that
  package-specific risk is assessed separately under RSK-03.
- Fork approval policy, branch protection, action allowlists and log retention
  require repository-settings review.

#### Risk scenario

A malicious pull request intentionally executes hostile test or project code,
a mutable action tag is redirected to unexpected code, or repository workflow
permissions are broader than required.

The workflow abuses available token permissions, exposes repository or runner
information, manipulates test results, poisons reusable state or prepares a
path for compromising a future release process.

The current workflow does not directly expose signing credentials or publish
release artifacts. Those additions would materially increase the risk.

#### Initial assessment

| Factor | Rating | Justification |
| --- | --- | --- |
| Likelihood | 2 / Possible | Pull-request code is intentionally executed, action tags are mutable and effective token settings are not declared in the workflow, but GitHub-hosted runners and the absence of direct secrets reduce exposure. |
| Impact | 2 / Medium | The current workflow runs tests but does not sign, publish or deploy releases. Credible impact is therefore limited compared with a privileged release pipeline. |
| Calculated score | 4 / Medium | Likelihood 2 multiplied by impact 2. |
| Final priority | P2 / Medium | The calculated priority is retained for the current test-only workflow. Reassess before adding release, signing, deployment, write permissions, secrets or self-hosted runners. |

#### Required treatment

- Declare explicit least-privilege workflow permissions, beginning with
  `contents: read` where sufficient.
- Pin every external action to a reviewed full commit SHA.
- Retain a comment or update process that identifies the human-readable action
  version associated with each pinned SHA.
- Configure an approved action allowlist at repository or organization level.
- Review and document fork pull-request approval policy.
- Confirm that fork pull-request jobs receive no organization or repository
  secrets.
- Confirm the effective `GITHUB_TOKEN` permissions for pull requests and
  `main` pushes.
- Protect `main` with required pull-request review and required successful
  status checks.
- Restrict who can modify workflow files and review workflow changes as
  security-sensitive.
- Keep untrusted PR testing separate from any future privileged release,
  deployment or signing workflow.
- Do not expose signing credentials to workflows that execute pull-request
  code.
- Review whether dependency caches can be safely reused across trusted and
  untrusted workflow contexts.
- Configure appropriate workflow-log and cache retention.
- Add automated workflow-security linting or scanning.
- Reassess this risk before adopting self-hosted runners.

#### Verification evidence required

- Workflow configuration explicitly grants only the approved permissions.
- Every external action is pinned to a reviewed full commit SHA.
- Repository settings show the approved action allowlist and fork policy.
- A test pull request from a fork cannot access repository or organization
  secrets.
- A test pull request cannot write repository contents, create releases or
  modify protected branches.
- Required review and status-check rules protect `main`.
- Workflow-security scanning reports no policy-blocking findings.
- Trusted and untrusted workflows do not share privileged release or signing
  credentials.
- Any future release workflow has a separate threat and permission review
  before activation.

#### Reassessment triggers

Reassess RSK-15 immediately if the workflow gains any of the following:

- release or package publishing;
- installer creation;
- Authenticode signing;
- deployment credentials;
- repository write permissions;
- organization secrets;
- cloud credentials;
- self-hosted runners;
- `pull_request_target`;
- reusable workflows from additional external sources.

#### Expected residual risk

GitHub-hosted CI intentionally executes repository code, and external platform
or action vulnerabilities remain possible. Immutable action references,
least-privilege permissions and separation from privileged release operations
substantially reduce the credible impact.

The target residual rating is:

| Likelihood | Impact | Residual score | Target rating |
| --- | --- | --- | --- |
| 1 / Unlikely | 2 / Medium | 2 | P3 / Low |

### RSK-16 — Same-user modification of installed runtime components

**Linked threat:** THR-16  
**Affected components:** CMP-06, CMP-07, CMP-09, CMP-11, CMP-12  
**Status:** In progress  
**Treatment owner:** Kristupas (remaining integrity work)

#### Evidence

- Live Translator is installed under the current user's `LocalAppData`
  application directory.
- The per-user installation supports operation without administrator
  privileges.
- Files in the installation directory are writable according to the current
  user's Windows permissions.
- The installed application includes executables, native DLLs, Piper runtime,
  translation models, TTS models and documentation.
- The installer and application are currently unsigned.
- No runtime verification against a signed or otherwise protected approved
  manifest was identified.
- Profiles and selected model caches are also stored in user-accessible
  locations.
- The application does not provide a protected repair or integrity-check
  workflow.
- Existing tests do not modify installed files and verify rejection before
  runtime loading.

#### Risk scenario

Live Translator is installed correctly in the per-user application directory.

Malware or another process already running with the same Windows user's
permissions replaces an application executable, native DLL, Piper component or
model. The user later starts Live Translator, which accepts and uses the
modified component as though it were part of the approved installation.

The modified component may persist across meetings, access meeting data or
perform additional actions using the user's permissions.

#### Initial assessment

| Factor | Rating | Justification |
| --- | --- | --- |
| Likelihood | 2 / Possible | The installation directory is intentionally user-writable, but exploitation requires an existing same-user process, malicious user action or contaminated update. |
| Impact | 3 / High | Modified executable or native runtime content may execute code and access confidential meeting information with the user's permissions. |
| Calculated score | 6 / High | Likelihood 2 multiplied by impact 3. |
| Final priority | P1 / High | The calculated priority is retained. A P0 override is not applied because the threat actor already requires same-user access and therefore already has significant capability. |

#### Required treatment

- Verify installed runtime executables, DLLs and models against the approved
  release manifest before use.
- Protect the manifest with a trusted signature or embed approved hashes in a
  signed application component.
- Authenticode-sign the application executable and installer as defined under
  RSK-14.
- Verify relevant executable signatures before launch where supported.
- Fail closed when a protected installed component is missing, changed or
  unapproved.
- Provide a safe repair or reinstall instruction when integrity verification
  fails.
- Record integrity failures without logging confidential meeting content.
- Perform integrity preflight before microphone capture begins.
- Define which user-writable files are expected to change, such as profiles,
  and keep them separate from immutable runtime assets.
- Do not allow configuration files to disable integrity verification in normal
  production meeting mode.
- Consider organization-level application control, endpoint protection or
  managed deployment for higher-assurance workstations.
- Do not claim that application self-verification can fully defeat malware
  already controlling the same user account.
- Revalidate integrity after application updates or repair operations.

#### Verification evidence required

- A clean approved installation passes integrity preflight.
- Modifying the main executable is detected by release or operating-system
  signature verification.
- Modifying a protected DLL, Piper file or model is detected before it is
  loaded or executed.
- Deleting a required protected file causes a safe preflight failure.
- User-editable profiles remain usable but cannot disable protected-asset
  verification.
- Integrity failure occurs before microphone capture or meeting-data
  processing.
- The repair or reinstall workflow restores the approved file set.
- Release tests validate the manifest against the installed directory, not
  only the build directory.
- Endpoint or application-control requirements for higher-assurance use are
  documented.

#### Expected residual risk

Malware controlling the same user account may modify the application, its
verifier, its launch shortcut or the data displayed to the user. A signed
manifest and runtime checks increase detection and prevent simple
substitution, but they cannot create a complete security boundary against an
already compromised endpoint.

The target residual rating is:

| Likelihood | Impact | Residual score | Target rating |
| --- | --- | --- | --- |
| 1 / Unlikely | 3 / High | 3 | P2 / Medium |

### RSK-17 — Sensitive profiles, caches or diagnostics remain after uninstall

**Linked threat:** THR-17  
**Affected components:** CMP-09, CMP-10, CMP-12  
**Status:** In progress  
**Treatment owner:** TBD (uninstall policy)

#### Evidence

- Per-user YAML profiles are stored separately from the application installation
  directory and intentionally survive application reinstall.
- Parakeet model files are stored in the per-user Hugging Face cache outside the
  application directory.
- Argos packages may be stored in bundled or per-user package locations.
- Meeting diagnostic output can be stored in an arbitrary user-selected
  directory.
- Piper temporary WAV files may remain after abnormal termination.
- The installer does not maintain a complete inventory of every profile, cache,
  diagnostic or temporary location used by the application.
- No application command or uninstall option was identified for reviewing and
  removing all Live Translator-owned user data.
- No user-facing retention notice explains which data survives uninstall.
- Terminal, backup, synchronization and endpoint-monitoring copies are outside
  the direct control of the uninstaller.
- Existing installer tests do not cover uninstall cleanup or retained user
  data.

#### Risk scenario

A user uninstalls Live Translator or believes that application data has been
removed from the workstation.

Profiles, model caches, diagnostic WAV and text files or stale temporary audio
remain in locations outside the installation directory. A later user, process,
backup operation or support activity discovers the retained information.

Automatically deleting every possible location would create a separate risk of
removing shared caches, intentionally retained profiles or unrelated files.
Cleanup must therefore be explicit and scoped.

#### Initial assessment

| Factor | Rating | Justification |
| --- | --- | --- |
| Likelihood | 2 / Possible | Profiles and caches intentionally persist, but sensitive meeting diagnostics exist only when enabled and uninstall is not a normal meeting-time action. |
| Impact | 2 / Medium | Retained diagnostics or temporary audio may expose sensitive content, while profiles and model caches generally expose configuration or software assets rather than complete meetings. |
| Calculated score | 4 / Medium | Likelihood 2 multiplied by impact 2. |
| Final priority | P2 / Medium | The calculated priority is retained because sensitive persistence depends on prior diagnostic use, abnormal cleanup or user expectations during uninstall. |

#### Required treatment

- Create a documented inventory of application-owned per-user storage
  locations.
- Separate application binaries, user configuration, model caches,
  diagnostics and temporary files in the data inventory.
- Define an approved retention policy for each data category.
- Provide a user-visible uninstall or cleanup choice between:
  - removing only application binaries;
  - retaining profiles for reinstall;
  - removing Live Translator profiles and diagnostics;
  - reviewing model caches separately.
- Do not delete a shared Hugging Face or Argos cache without confirming that
  the target data belongs only to Live Translator.
- Provide a safe application cleanup command for known Live Translator
  diagnostics and stale temporary files.
- Track application-managed diagnostic sessions so that they can be listed and
  removed.
- Clearly warn that diagnostics written to arbitrary custom paths may require
  manual cleanup.
- Show users which data categories will remain before uninstall or cleanup.
- Scope every deletion to validated application-owned paths.
- Protect cleanup against traversal, links, junctions and unintended recursive
  deletion.
- Document that backups, sync providers, terminal logs and endpoint tools may
  retain independent copies.
- Record cleanup failures without exposing confidential content.

#### Verification evidence required

- Uninstall removes the approved application directory.
- The “retain profiles” option preserves valid profiles as documented.
- The “remove user data” option removes only validated Live Translator-owned
  profiles and diagnostic locations.
- Shared or unrelated Hugging Face and Argos cache content is not accidentally
  deleted.
- Stale application-owned temporary files can be listed and removed safely.
- Diagnostics stored in a custom path produce a clear manual-cleanup notice.
- Tests cover path traversal, symlinks, junctions and unexpected files before
  recursive cleanup.
- Repeated cleanup is safe and does not fail destructively when files are
  already absent.
- Windows 10 and Windows 11 uninstall behaviour is documented and verified.
- User documentation accurately lists data that may remain outside application
  control.

#### Expected residual risk

Users may intentionally copy diagnostic data, select arbitrary storage paths or
retain data through backups and synchronization services. The application can
manage known application-owned locations but cannot guarantee deletion of all
external copies.

The target residual rating is:

| Likelihood | Impact | Residual score | Target rating |
| --- | --- | --- | --- |
| 1 / Unlikely | 2 / Medium | 2 | P3 / Low |

## Register conclusion

All 17 threats retained for baseline `79f95d6` have an initial likelihood,
impact, calculated score, priority, proposed treatment, verification criteria
and target residual rating. The analysis deliverable is therefore complete for
this baseline.

The priority distribution remains 2 P0, 11 P1 and 4 P2 risks. Current treatment
status is 2 mitigated, 6 in progress and 9 open. Priority records the original
security importance and is not automatically lowered when implementation starts.
Document completion must not be confused with risk remediation or residual-risk
acceptance.

The project lead must review the proposed priorities, assign treatment owners
through the related Notion implementation stories and identify the stakeholder
authorized to accept residual risk. Those governance actions do not require
the baseline-analysis task to remain open, provided they are tracked as
follow-up work.

Review and update this register whenever the threat model baseline changes, a
control is implemented, verification evidence becomes available, a risk is
accepted or deferred, or a reassessment trigger documented in a detailed risk
entry occurs.
