# Windows Packaging

## Required Local Assets

The build script requires these paths before PyInstaller starts:

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
runtime DLLs and `espeak-ng-data` are required beside it.

## Build

From the repository root:

```powershell
.\scripts\build_windows.ps1 -InstallBuildTools
```

Later builds can omit `-InstallBuildTools` once PyInstaller is installed in the
project virtual environment.

Output:

```text
dist/LiveTranslator/LiveTranslator.exe
```

The PyInstaller folder contains the Python runtime, CTranslate2 libraries,
Argos models, Piper, and both voices.

## Speech Model Cache

The current build does not bundle the speech model. A named model such as
`nemo-parakeet-tdt-0.6b-v3` is downloaded to the current Windows user's Hugging
Face cache on its first load. Before offline use on a new machine, run while
online:

```powershell
.\dist\LiveTranslator\LiveTranslator.exe doctor `
  --config "$env:LOCALAPPDATA\LiveTranslator\profiles\en-de.yaml" `
  --prepare-models
```

Repeat for every distinct ASR model referenced by installed profiles.

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

The current binary and installer are unsigned and intended for controlled
internal demonstration. Windows SmartScreen behavior depends on local policy.
