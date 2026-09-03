# Runtime Asset Integrity

## Security Objective

Live Translator must not execute or load a runtime binary or model merely
because a file with the expected name exists. Before meeting components are
loaded, the application compares protected files with the approved manifest in
`packaging/runtime-assets.manifest.json` using exact byte size and SHA-256.

The manifest covers 386 files:

| Component | Protected files | Approved version or revision |
| --- | ---: | --- |
| Piper Windows runtime | 361 | `2023.11.14-2` |
| Piper English and German voices | 4 | `39ab474be869e9181350af6a65e4953eef67aaa0` |
| Parakeet int8 model and revision stamp | 5 | `8f23f0c03c8761650bdb5b40aaf3e40d2c15f1ce` |
| Argos `en_de` and `de_en` packages | 16 | package `1.3`, Argos `1.9.0` |

The approved sources are recorded per file in the manifest. Source assets were
verified against pinned upstream archives, downloads or cryptographic metadata
before their hashes were recorded. Model and runtime binaries remain excluded
from Git; the manifest, verification code and evidence are tracked.

Upstream references:

- [Piper `2023.11.14-2`](https://github.com/rhasspy/piper/releases/tag/2023.11.14-2)
- [Piper Voices](https://huggingface.co/rhasspy/piper-voices)
- [Parakeet ONNX revision](https://huggingface.co/istupakov/parakeet-tdt-0.6b-v3-onnx/tree/8f23f0c03c8761650bdb5b40aaf3e40d2c15f1ce)
- [Argos package index](https://github.com/argosopentech/argospm-index/blob/main/index.json)

## Runtime Enforcement

- Piper runtime files and both bundled voices are verified before
  `subprocess.run` can execute `piper.exe`.
- The selected Parakeet directory is verified before `onnx-asr` loads the
  model and before meeting capture opens. `revision.txt` is mandatory.
- The selected Argos direction is verified before CTranslate2 or SentencePiece
  loads it. `ARGOS_PACKAGES_DIR` and `XDG_DATA_HOME` may relocate an approved
  package, but cannot authorize different bytes.
- Missing, modified and unlisted files fail closed. Manifest paths reject
  absolute paths, Windows drive or UNC prefixes, `.` and `..` segments, and
  symbolic links within protected roots.
- Parakeet's `.cache/**` download metadata is the only excluded subtree. The
  files actually loaded by the recognizer are not excluded.

Successful checks are retained for the lifetime of their prepared engine. They
are not recalculated for every phrase.

## Build and Distribution Enforcement

`scripts/build_windows.ps1` verifies all 381 assets bundled by PyInstaller
before the build starts. After PyInstaller finishes, it verifies the copied
files under `dist/LiveTranslator/_internal` and runs
`dist/LiveTranslator/LiveTranslator.exe --help`.

Use validation without producing a new build:

```powershell
.\scripts\build_windows.ps1 -ValidateOnly
.\scripts\build_inno_installer.ps1 -ValidateOnly
```

The Inno Setup script repeats dist validation immediately before installer
creation. The runtime manifest itself is included in the PyInstaller output.

## Verification Evidence

Evidence collected on Windows 11 on 2026-09-03:

- Piper: 361 local runtime files matched the official `2023.11.14-2` Windows
  archive; zero differences.
- Piper voices: both ONNX files and both JSON files matched the pinned upstream
  revision; zero differences.
- Parakeet: both ONNX files matched upstream size and SHA-256 metadata; the two
  smaller files matched pinned upstream downloads byte-for-byte.
- Argos: both official `1.3` archives contained eight files and matched the
  local package directories; zero differences.
- A real PyInstaller build passed source preflight, dist validation, packaged
  `--help`, packaged `en` to `de` translation, and packaged `doctor` checks for
  Argos and Piper.
- The automated suite passed 406 tests; four environment-dependent tests were
  skipped. Negative tests prove that integrity failures block Piper execution,
  Parakeet recognizer construction and Argos model loading.

Reproduce the automated and performance checks:

```powershell
python -m unittest discover -s tests
python -m compileall -q src tests scripts
python .\scripts\benchmark_asset_integrity.py --repetitions 5
python .\scripts\benchmark_meeting_integrity.py
```

## Performance Evidence

Five-run warm-cache medians on the same machine:

| Check | Median |
| --- | ---: |
| Piper runtime and voices | 1.439 s |
| Parakeet int8 | 1.101 s |
| Argos `en_de` | 0.312 s |
| Argos `de_en` | 0.311 s |
| Meeting startup, `en_de` | 2.859 s |
| Meeting startup, `de_en` | 2.864 s |
| Windows packaged assets | 2.006 s |

The meeting startup measurement is the added integrity-check cost, not total
model initialization. Instrumented phrase runs confirmed that no integrity
hash is recalculated after the engines are prepared, so the added per-phrase
integrity latency is zero.

## Residual Risk and Scope

Risk disposition: runtime executable and model tampering is **mitigated, not
closed**. The implemented controls detect changes relative to reviewed bytes;
the remaining authenticity and time-of-check/time-of-use limitations below
must stay recorded against the corresponding Notion risk.

This control detects changes relative to the manifest; it does not establish
who published the manifest. The Windows executable and installer remain
unsigned. An attacker who can replace both the application and its manifest can
bypass an in-application hash check. Code signing, controlled release
publication and independent release-hash verification remain required.

Verification occurs during engine preparation and is cached. A same-user
attacker who can modify an asset after verification but before a later use may
still create a time-of-check/time-of-use condition. Restrictive installation
permissions or executing from a managed, read-only location reduce that risk.

SHA-256 also does not prove that an approved upstream model is free of malicious
or unsafe behavior; it proves only that the local bytes match the version the
project reviewed. Approving a new runtime, voice or model therefore requires a
manifest update, upstream provenance review and regression testing.
