param(
    [switch]$InstallBuildTools
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Missing venv Python at $Python. Create the venv and install dependencies first."
}

if ($InstallBuildTools) {
    & $Python -m pip install -U pyinstaller
}

& $Python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not installed. Re-run with: .\scripts\build_windows.ps1 -InstallBuildTools"
}

if (-not (Test-Path "tools\piper\piper.exe")) {
    throw "Missing tools\piper\piper.exe. Run the Piper setup/download step first."
}

foreach ($voice in @(
    "models\tts\de_DE-thorsten-medium.onnx",
    "models\tts\de_DE-thorsten-medium.onnx.json",
    "models\tts\en_US-hfc_male-medium.onnx",
    "models\tts\en_US-hfc_male-medium.onnx.json"
)) {
    if (-not (Test-Path $voice)) {
        throw "Missing $voice"
    }
}

foreach ($package in @(
    "models\argos\packages\en_de",
    "models\argos\packages\de_en"
)) {
    if (-not (Test-Path $package)) {
        throw "Missing bundled Argos package: $package"
    }
}

& $Python -m PyInstaller --clean --noconfirm "packaging\windows\LiveTranslator.spec"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

Write-Host ""
Write-Host "Built: $Root\dist\LiveTranslator\LiveTranslator.exe"
Write-Host "Try:   $Root\dist\LiveTranslator\LiveTranslator.exe setup"
