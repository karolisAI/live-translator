# Windows Packaging

## Required Local Assets

The build script verifies these protected roots against
`packaging/runtime-assets.manifest.json` before PyInstaller starts:

```text
models/argos/packages/en_de/
models/argos/packages/de_en/
models/tts/de_DE-thorsten-medium.onnx
models/tts/de_DE-thorsten-medium.onnx.json
models/tts/en_US-hfc_male-medium.onnx
models/tts/en_US-hfc_male-medium.onnx.json
tools/piper/piper.exe
```

The complete Piper directory is bundled, not only `piper.exe`, because the
runtime DLLs and `espeak-ng-data` are required beside it. Existence alone is not
accepted: size, SHA-256 and the absence of unlisted files are checked.

## Build

From the repository root:

```powershell
.\scripts\build_windows.ps1 -InstallBuildTools
```

Later builds can omit `-InstallBuildTools` once PyInstaller is installed in the
project virtual environment.

Run only the source-asset preflight with:

```powershell
.\scripts\build_windows.ps1 -ValidateOnly
```

Output:

```text
dist/LiveTranslator/LiveTranslator.exe
```

The PyInstaller folder contains the Python runtime, CTranslate2 libraries,
Argos models, Piper, both voices and the approved runtime manifest. The build
script verifies the copied assets under `dist/LiveTranslator/_internal` and
runs a packaged `--help` smoke test before reporting success.

## Speech Model Preparation

The installer does not bundle the speech model, so a new machine has to prepare
it once while online:

```powershell
.\dist\LiveTranslator\LiveTranslator.exe prepare-models --profile en-de
```

An installed build writes it to
`%LOCALAPPDATA%\LiveTranslator\models\asr\parakeet-tdt-0.6b-v3`, beside the
profiles rather than inside the application directory, which is replaced on
upgrade. Because it sits outside the application, the model survives an upgrade
or uninstall and is prepared once per Windows user rather than once per version.
Both locations are writable by that Windows user; manifest verification detects
model changes but is not a substitute for managed filesystem permissions.

Both generated profiles use the same model, so this is run once, not once per
profile. Repeat it only for a profile that names a different `asr.model` or
`asr.compute_type`.

Preparation is the only step that needs the network. Meeting mode reads the
prepared directory and cannot fall back to downloading; a machine that skipped
this step fails at startup with the command above, before it opens a
microphone.

To ship the model inside the installer instead, add `("models/asr",
"models/asr")` to the asset list in `packaging/windows/LiveTranslator.spec` and
prepare it in the build tree first. That removes the per-machine step at the
cost of roughly 640 MB on the installer.

## Per-User Installation

```powershell
.\scripts\install_windows_user.ps1
```

The application is copied to:

```text
%LOCALAPPDATA%\Programs\LiveTranslator\
```

Profiles remain under `%LOCALAPPDATA%\LiveTranslator\profiles` and survive an
application reinstall.

## Installed-App Verification

```powershell
$LT = "$env:LOCALAPPDATA\Programs\LiveTranslator\LiveTranslator.exe"
& $LT --help
& $LT doctor --config "$env:LOCALAPPDATA\LiveTranslator\profiles\en-de.yaml" --prepare-models
& $LT route-test --profile en-de
```

Run typed translation in both directions and one `say` test before relying on
the executable in a meeting.

## Installer

`packaging/windows/LiveTranslator.iss` defines the optional Inno Setup wrapper:

```powershell
.\scripts\build_inno_installer.ps1
```

The script revalidates `dist` immediately before invoking Inno Setup. Use
`-ValidateOnly` to perform that gate without creating an installer.

The current binary and installer are unsigned and intended for controlled
internal demonstration. Windows SmartScreen behavior depends on local policy.
