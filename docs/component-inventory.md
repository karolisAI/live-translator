# Live Translator Component Inventory

This document records the security-relevant components in the current
Parakeet-based Live Translator architecture. It is a working document for the
threat model and risk register.

## Document status

| Field | Value |
| --- | --- |
| Status | Revalidated for baseline `79f95d6` |
| Security owner | Kristupas |
| Architecture baseline | [Parakeet PR #2](https://github.com/karolisAI/live-translator/pull/2) plus security PRs [#3](https://github.com/karolisAI/live-translator/pull/3), [#4](https://github.com/karolisAI/live-translator/pull/4), [#5](https://github.com/karolisAI/live-translator/pull/5) and reliability PR [#6](https://github.com/karolisAI/live-translator/pull/6) |
| Baseline commit | `79f95d6` |
| Previous reviewed baseline | `11c7752` |
| Last updated | 2026-09-02 |

## Review conventions

- Start **Network access** with `Yes`, `No`, `Preparation only`, or
  `Conditional`, followed by a short explanation where necessary.
- Record both sensitive inputs and generated outputs in **Data handled**.
- Use **Initial security notes** only for observations; risks will be assessed
  separately in the risk register.
- Use `Not reviewed`, `Partially reviewed`, or `Reviewed` in **Review status**.
  `Reviewed` means that the component was inspected for this inventory; it does
  not mean that every identified risk has been remediated or accepted.
- Mark third-party runtime behaviour as reviewed only after inspecting the
  installed dependency version, authoritative documentation, or behaviour in a
  controlled test. Record any remaining validation gaps under **Review notes**.

## Scope and limitations

This inventory covers the source tree and development environment at baseline
commit `79f95d6`. It is based on source inspection, installed-dependency
inspection and automated tests that primarily use mocked models and audio
devices. It is an input to the threat model and risk register, not a security
certification.

The review does not by itself prove real-device behaviour, Windows 10/11
compatibility, strict network isolation, release reproducibility, artifact
integrity, malware resistance or safe processing of confidential meetings.
Those claims require controlled system, network, installer and release tests.

## Security delta since `11c7752`

The following merged changes invalidate or refine parts of the earlier
security analysis. They have been inspected against baseline `79f95d6`.

| Area | Change | Security consequence | Follow-up |
| --- | --- | --- | --- |
| Offline Parakeet preparation (PR #3) | Adds `prepare-models`, pins the approved Hugging Face repository to commit `8f23f0c03c8761650bdb5b40aaf3e40d2c15f1ce`, records the revision locally and makes meeting mode load an already prepared directory. | Meeting startup no longer reaches the model-download path. Missing, incomplete or differently stamped assets fail before microphone capture. | Retain the offline regression tests and complete SHA-256 verification; `revision.txt` identifies the expected revision but does not prove file contents. |
| Trusted runtime loading (PR #5) | Removes current-working-directory and `PATH` trust, defines approved runtime roots, rejects traversal and outside-root paths, and propagates a distinct security error. | A planted Piper executable or runtime asset outside approved roots is rejected before execution. Argos and TTS model lookup use the same trusted resolver where applicable. | Add an approved integrity manifest because an approved directory can still contain a modified file. Protect that manifest through the later signed-release process. |
| Diagnostics privacy (PR #4) | Makes capture opt-in, moves the default destination to a per-user application directory, adds warnings, age/size retention, purge, Git exclusions and symlink/junction containment. Normal meeting output no longer prints transcript content unless `--show-text` is selected. | Default meetings create no diagnostic artifacts or transcript scrollback. Explicit diagnostics still store plaintext meeting content and inherit filesystem permissions. | Confirm the organization's retention and Windows ACL policy; decide whether audio and text capture must be independently selectable or encrypted. |
| Piper reliability (PR #6) | Adds explicit UTF-8 stdin encoding while retaining the timeout and trusted-path protections introduced earlier. | Non-ASCII translated text is no longer dependent on the Windows ANSI code page. A blocked Piper process remains bounded by the configured timeout. | Keep the regression test and include a real packaged Piper smoke test in release validation. |
| Test baseline | The current local suite executes 336 tests successfully; 3 Windows symlink tests are skipped where the process cannot create symlinks. | The suite covers offline model startup, trusted roots, diagnostics retention/purge, console privacy and Piper timeout/encoding behaviour. | Unit tests still use mocked models/audio for many paths and do not replace controlled network, real-device, installer and signed-release validation. |
| Supply chain and release | Dependency ranges, mutable GitHub Action tags, recursive local asset packaging and unsigned Windows artifacts remain unchanged. | Builds are not reproducible and a modified file already inside an approved local runtime directory can be packaged or loaded without detection. | Implement runtime asset integrity, dependency locking/scanning, SBOM, CI hardening, release allowlisting and Authenticode signing. |

## Component inventory

| ID | Component | Category | Purpose | Data handled | Source or location | Network access | Initial security notes | Review status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CMP-01 | CLI | Application interface | Provides commands for setup, explicit model/package preparation, diagnostics and offline meetings. | Arguments, profile/configuration paths, language directions, audio devices, model/runtime paths, typed text and diagnostic destinations. Normal meeting mode prints content-free phrase progress; `--show-text` deliberately prints transcripts/translations, while `--diagnostics` or `--debug-audio-dir` persists them. | `src/live_translator/cli.py` | Preparation only — `prepare-models` and `argos-install` may use the network. Meeting mode verifies and loads prepared local assets and does not call model-download code. | User-controlled paths and profiles remain security-sensitive. Text display and diagnostic persistence are now separate opt-ins. Profile names are not yet constrained to a simple contained filename. | Reviewed for baseline `79f95d6` |
| CMP-02 | Audio capture and speech chunking | Audio processing | Captures raw audio from the selected microphone, converts it to the pipeline sample rate and divides continuous audio into speech segments using voice activity detection before passing those segments to the ASR component. | Raw microphone audio samples, buffered audio frames, detected speech segments, sample-rate information, audio-device selection and calculated audio-energy measurements. Audio may also be written to WAV files when an explicit recording or diagnostic function requests it. | `src/live_translator/audio/` | No direct network access identified. | Processes potentially confidential raw meeting audio in memory. Incorrect audio-device selection could capture unintended audio. Explicit recording and diagnostic functions can write raw audio to local WAV files. User-controlled recording duration, VAD thresholds and segment limits may affect memory use, latency and availability. The component relies on `sounddevice` and the native PortAudio stack. | Reviewed |
| CMP-03 | Parakeet TDT | Speech recognition model | Converts meeting-audio segments into timestamped text and confidence data. | Raw speech, language identifiers, transcripts, timestamps/log probabilities, rejection reasons and low-confidence state. | Pinned external model staged under `models/asr/parakeet-tdt-0.6b-v3`; adapter in `src/live_translator/asr/parakeet_engine.py` | Preparation only — `prepare-models` downloads the approved repository/revision. Meeting inference reads a verified-present local directory. | Repository and revision are pinned and mismatched revision stamps are rejected. Required-file presence is checked, but model bytes are not yet verified by SHA-256; a manually staged custom model directory remains supported and must be covered by policy. | Reviewed for baseline `79f95d6` |
| CMP-04 | `onnx-asr` | Speech recognition library | Loads the prepared Parakeet directory, exposes timestamped decoding and constructs the native runtime. | Local model path, ONNX/config/vocabulary files, audio tensors, transcripts, timestamps and confidence values. | External `onnx-asr`; version `0.12.0` inspected. Called by `src/live_translator/asr/recognizer.py` and guarded by `src/live_translator/asr/model_store.py`. | No during meeting mode — the application first requires an existing prepared directory, causing the supported resolver to use its offline path. | Offline resolver behaviour is covered by a real-resolver regression test and download functions are patched to fail in offline tests. The dependency remains range-constrained and model-content integrity is not yet verified. | Reviewed for baseline `79f95d6` |
| CMP-05 | ONNX Runtime | Native model runtime | Loads and executes the Parakeet ONNX model through native inference sessions, applies graph optimizations and performs CPU or configured-provider inference. | ONNX model and configuration files, native runtime libraries, raw meeting-audio tensors, intermediate model tensors, token probabilities, timestamps and inference results. | External `onnxruntime` Python and native dependency; version `1.29.0` inspected in the current development environment. Sessions are created through `onnx-asr` and configured by `src/live_translator/asr/recognizer.py` | No direct model-inference network access identified. Model acquisition is handled by `onnx-asr`/Hugging Face. Official Windows builds may emit ETW events subject to Windows telemetry configuration, so strict offline release behaviour requires a controlled network test. | Parses and executes externally obtained ONNX model files using native code in the Live Translator process. The application explicitly selects the CPU provider by default, but does not verify an approved model manifest, sandbox inference, impose a model-loading timeout or enforce process-level memory limits. A malicious or malformed model may target parser/runtime defects or consume excessive CPU and memory. Native DLL provenance depends on the Python package installation process. The project permits `onnxruntime>=1.20,<2`, so the reviewed `1.29.0` version is not reproducibly pinned. | Reviewed |
| CMP-06 | Argos Translate | Machine translation | Performs local EN-DE/DE-EN translation through CTranslate2 and SentencePiece. | Confidential transcripts, translated text, package metadata and native model/tokenizer files. | `src/live_translator/mt/`; inspected environment uses Argos Translate `1.11.0`, CTranslate2 `4.8.1` and SentencePiece `0.2.2`. | Preparation only — normal translation uses local assets; `argos-install` updates the remote index and downloads a selected package. | Runtime lookup no longer trusts the current working directory and bundled assets use trusted roots. Online package selection, archive provenance, exact version/hash approval and final model integrity remain unresolved. | Reviewed for baseline `79f95d6` |
| CMP-07 | Piper | Speech synthesis runtime | Converts translated text to temporary WAV audio and then plays it through the configured output. | Translated text on UTF-8 subprocess stdin, executable/model paths, temporary WAV files, decoded samples and playback-device selection. | `src/live_translator/tts/speaker.py`; external Piper executable, companion DLLs, espeak data and ONNX voices. | No application-level network access identified. | Piper is invoked without a shell, only from approved runtime roots, with a configurable positive timeout. Current-working-directory and `PATH` fallback are removed. Existence and containment are checked, but executable, DLL, data and voice-model SHA-256 values/signatures are not; temporary plaintext WAV recovery after abnormal termination remains possible. | Reviewed for baseline `79f95d6` |
| CMP-08 | VB-CABLE | Virtual audio routing | Routes Piper-generated translated speech from a Windows playback endpoint to a paired recording endpoint that the meeting application can use as its microphone. | Synthesized translated meeting audio, playback and recording endpoint identifiers, sample-rate and channel information, generated route-test tones and recorded route-test samples. | External VB-Audio VB-CABLE Windows kernel audio driver and paired `CABLE Input`/`CABLE Output` endpoints; application integration in `src/live_translator/audio/devices.py`, `src/live_translator/audio/io.py` and `src/live_translator/audio/route_test.py` | No runtime network access identified. The driver package is downloaded separately during administrative workstation preparation. | Carries confidential translated speech through a system-wide Windows recording endpoint that other locally authorized audio applications may also access. Incorrect meeting-device selection, automatic microphone switching, acoustic feedback or Windows “Listen to this device” settings may disclose untranslated or translated meeting audio. Automatic endpoint-role and cable-pair selection reduces configuration mistakes but relies on friendly names and is not a strong identity control. VB-CABLE is a privileged third-party Windows driver whose source, version and digital signature must be approved. Driver installation requires administrator privileges and a reboot, so the per-user no-admin requirement applies only to Live Translator after VB-CABLE has been provisioned by IT. | Reviewed |
| CMP-09 | Profiles and YAML configuration | Configuration | Loads, validates and writes per-user meeting profiles that select runtime, models, devices, limits and diagnostics. | YAML, profile names/paths, model/runtime paths, languages, thresholds, queue sizes and diagnostic settings. | `src/live_translator/config.py`, `src/live_translator/profiles.py`, `src/live_translator/defaults.py` and per-user profiles. | No direct network access; explicit preparation commands may use values from a profile. | `yaml.safe_load`, unknown-field rejection, type checks and positive/bounded validation are present. Runtime paths cannot widen approved roots in a packaged build. Profile-name traversal/containment, atomic profile writes, configuration-size limits and complete upper bounds remain open. | Reviewed for baseline `79f95d6` |
| CMP-10 | Diagnostics, calibration and benchmarks | Diagnostics | Provides dependency checks, explicit capture, retention/purge, route tests, public calibration retrieval and ASR metrics. | Device/path metadata, raw audio, transcripts/translations, public dataset samples and benchmark results. | `src/live_translator/diagnostics.py`, CLI/pipeline diagnostics and development scripts. | Yes only for explicit preparation/development retrieval; meeting diagnostics themselves are local. | Meeting capture is disabled by default, warns when enabled, defaults to a per-user root, enforces age/size retention, supports purge and rejects traversal plus symlink/junction escapes. Normal/verbose meeting output hides content unless `--show-text` is explicit. Captured content remains plaintext; ACL, synchronization, encryption and independently selectable audio/text policy remain stakeholder decisions. | Reviewed for baseline `79f95d6` |
| CMP-11 | PyInstaller application | Packaging | Creates the Windows onedir application from Python code, native libraries, local models, Piper runtime and documentation. | Source/bytecode, dependencies, executables/DLLs, models, documentation and build output. | `packaging/windows/LiveTranslator.spec`, `scripts/build_windows.ps1`, dependency metadata and local ignored `models/`/`tools/` directories. | Conditional — optional build-tool installation uses package indexes; packaging consumes local files. | Required files are checked for existence, but ignored local asset directories are recursively packaged without SHA-256/version verification or a complete allowlist. Dependencies are range-constrained, `collect_all` is broad, no SBOM/release manifest is produced and the EXE is unsigned. | Reviewed for baseline `79f95d6` |
| CMP-12 | Windows installer | Distribution | Recursively packages the PyInstaller output and installs it per user under `LocalAppData`. | Application/runtime/model files, installer metadata, shortcuts, installed files and uninstall output. | Inno Setup configuration and Windows build/install scripts. | No direct installer network access identified. | `PrivilegesRequired=lowest` preserves no-admin application installation, but VB-CABLE remains an IT prerequisite. The complete `dist/LiveTranslator` tree is accepted without a manifest/allowlist, source traceability or signature. EXE, installer and uninstaller are unsigned, and per-user installed files remain same-user writable. | Reviewed for baseline `79f95d6` |
| CMP-13 | GitHub Actions test workflow | CI/CD | Automatically checks out the repository, installs the Python project, runs the unit-test suite and compiles Python sources on Windows and Ubuntu with Python 3.11 and 3.12 for pushes to `main`, pull requests and manual workflow runs. | Repository source and test code, dependency metadata and downloaded packages, GitHub runner and matrix metadata, `pip` cache contents, unit-test and compilation output, `GITHUB_TOKEN` permissions and any secrets or credentials that may be added to the workflow in the future. | `.github/workflows/tests.yml`, GitHub-hosted Windows and Ubuntu runners, `actions/checkout`, `actions/setup-python`, Python package repositories and generated workflow logs and `pip` caches. | Yes. The workflow retrieves GitHub Actions, Python runtimes and project dependencies from external services. Application model downloads are intentionally avoided by mocked tests, but the workflow has not been validated as a network-isolated application test. | The workflow uses GitHub-hosted runners, has a 15-minute timeout, does not reference repository secrets and uses `pull_request` rather than `pull_request_target`. These choices reduce risk from untrusted pull-request code. `actions/checkout` and `actions/setup-python` are referenced through mutable major-version tags instead of approved full commit SHAs. No explicit least-privilege `permissions` block is declared, so effective `GITHUB_TOKEN` permissions depend on repository or organization settings. `pip` and project dependencies are installed from the network without a lock file or package-hash verification, making CI results and dependency provenance non-reproducible. The workflow does not perform dependency CVE scanning, dependency review, static security analysis, secret scanning, SBOM generation, release build inspection, asset-integrity verification or signature validation. The unit tests use mocked models and audio devices. Successful CI tests therefore do not prove real Windows audio routing, confidential-data handling, strict offline meeting operation or release-artifact security. | Reviewed |

## Review notes

Record uncertainties and questions here while reviewing the code. Do not treat
an assumption as a confirmed fact until it has been verified.

- The full local suite passed 336 tests at baseline `79f95d6`; 3 symlink tests
  were skipped because this Windows process could not create directory
  symlinks. A real Windows junction escape was separately verified during PR
  #4 review and remained outside purge/retention scope.
- Meeting model loading now has both mocked download-denial tests and a test
  that drives the supported `onnx-asr` resolver with an existing directory.
  These demonstrate the application path, but packaged Windows DNS/TCP/HTTP
  monitoring is still needed for release assurance.
- Parakeet repository/revision and required files are pinned and checked. No
  SHA-256 check proves that the prepared ONNX/config/vocabulary bytes still
  match the approved release.
- Argos and Piper runtime lookup no longer trusts the current working directory.
  Argos online package selection/archive provenance and all runtime/model content
  hashes remain open.
- Piper tests cover trusted paths, timeout handling, failure containment and
  UTF-8 stdin with a mocked subprocess. A packaged real-binary smoke test and
  approved EXE/DLL/model hashes remain release requirements.
- Diagnostics tests cover default-off behaviour, warnings, per-user placement,
  traversal, retention, purge and symlink/junction containment. They do not
  establish an organizational Windows ACL, encryption, backup/sync or separate
  audio/text capture policy.
- Configuration tests cover safe YAML, unknown fields, types and selected
  numeric rules. `--profile` name containment, atomic writes, size/nesting
  limits and practical upper bounds are not complete.
- VB-CABLE selection and synthetic route tests do not validate a real approved
  driver/signature, Teams configuration, Windows privacy settings or recording
  by another local application.
- `models/` and `tools/` are Git-ignored local inputs, while PyInstaller and Inno
  Setup recursively package broad directories. No complete asset allowlist,
  protected manifest, SBOM, reproducible dependency lock or final-dist content
  inspection is enforced.
- GitHub Actions uses `pull_request`, directly references no secrets and has a
  timeout, but action tags are not pinned to commit SHAs and no explicit
  least-privilege `permissions` block is present. Repository-level branch/token
  settings still require separate review.
- No verified Authenticode signing chain exists for the EXE, installer or
  uninstaller. Uninstall cleanup for profiles, prepared models and caches is not
  complete.

## Inventory conclusion

All components identified in baseline `79f95d6` have been reviewed for this
inventory. The review identified four recurring security themes that must be
carried into the threat model and risk register:

1. Runtime executables and sensitive assets are restricted to approved roots,
   but their bytes are not yet verified against a protected SHA-256 manifest.
2. Parakeet meeting startup is structurally offline and fails before microphone
   capture when preparation is missing. Controlled release-level network tests
   on supported Windows versions remain required.
3. Diagnostic capture and terminal text are privacy-preserving by default.
   Explicit diagnostics still create plaintext meeting artifacts and require an
   approved retention, ACL, synchronization and encryption decision.
4. Dependencies, CI actions, build inputs, executables and installers are not
   yet covered by a reproducible, scanned and digitally signed release chain.

Completing this inventory does not make Live Translator ready for unrestricted
confidential use. Identified findings must next be converted into risk-register
entries, assigned owners and priorities, remediated or formally accepted, and
verified through security regression and release-validation tests.

## External references

- [Live Translator Parakeet pull request](https://github.com/karolisAI/live-translator/pull/2)
- [Offline Parakeet preparation pull request](https://github.com/karolisAI/live-translator/pull/3)
- [Diagnostics privacy pull request](https://github.com/karolisAI/live-translator/pull/4)
- [Trusted runtime loading pull request](https://github.com/karolisAI/live-translator/pull/5)
- [Piper UTF-8 reliability pull request](https://github.com/karolisAI/live-translator/pull/6)
- [PyInstaller: Using spec files](https://pyinstaller.org/en/stable/spec-files.html)
- [Inno Setup: `PrivilegesRequired`](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm)
- [Inno Setup: `SignTool`](https://jrsoftware.org/ishelp/topic_setup_signtool.htm)
- [GitHub Actions secure-use reference](https://docs.github.com/en/actions/reference/security/secure-use)
- [VB-Audio VB-CABLE product and driver information](https://vb-audio.com/Cable/)
