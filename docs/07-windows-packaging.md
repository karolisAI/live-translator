# Windows Packaging

## POC Package Shape

The current POC target is a PyInstaller app folder:

```text
dist/LiveTranslator/
  LiveTranslator.exe
  tools/piper/
  models/tts/
  ...
```

This keeps Piper and voice models next to the executable. The app resolves
relative paths from the current directory, the executable directory, and the
PyInstaller bundle directory, so profiles can keep portable paths such as:

```yaml
tts:
  piper_exe: tools/piper/piper.exe
  model_path: models/tts/de_DE-thorsten-medium.onnx
```

## Build

```powershell
.\scripts\build_windows.ps1 -InstallBuildTools
```

After the first build, `-InstallBuildTools` is optional.

## Per-User Install

```powershell
.\scripts\install_windows_user.ps1
```

This copies `dist/LiveTranslator` to:

```text
%LOCALAPPDATA%\Programs\LiveTranslator
```

## First Run

```powershell
LiveTranslator.exe setup --direction en-de
LiveTranslator.exe route-test
LiveTranslator.exe meeting
```

The setup command writes:

```text
%LOCALAPPDATA%\LiveTranslator\profiles\default.yaml
```

## Next Installer Step

For enterprise-style distribution, wrap the app folder with Inno Setup, NSIS, or
WiX/MSI after the routing profile is stable. That installer should:

- install the app under `%LOCALAPPDATA%\Programs\LiveTranslator` or `%PROGRAMFILES%`
- create Start Menu shortcuts for Setup and Meeting mode
- preserve user profiles under `%LOCALAPPDATA%\LiveTranslator`
- check for a usable virtual cable recording endpoint
- remain unsigned for internal testing only, then move to signed binaries

An Inno Setup definition is present at:

```text
packaging/windows/LiveTranslator.iss
```

Build it after installing Inno Setup:

```powershell
.\scripts\build_inno_installer.ps1
```
