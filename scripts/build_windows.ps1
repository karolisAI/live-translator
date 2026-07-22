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
    & $Python -m pip install -e ".[build]"
}

& $Python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not installed. Re-run with: .\scripts\build_windows.ps1 -InstallBuildTools"
}

foreach ($asset in @(
    "tools\piper\piper.exe",
    "tools\piper\piper_phonemize.dll",
    "tools\piper\onnxruntime.dll",
    "tools\piper\espeak-ng-data"
)) {
    if (-not (Test-Path $asset)) {
        throw "Missing Piper runtime asset: $asset"
    }
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

foreach ($asset in @(
    "models\argos\packages\en_de\model\model.bin",
    "models\argos\packages\en_de\sentencepiece.model",
    "models\argos\packages\de_en\model\model.bin",
    "models\argos\packages\de_en\sentencepiece.model"
)) {
    if (-not (Test-Path $asset)) {
        throw "Missing bundled Argos asset: $asset"
    }
}

& $Python -m PyInstaller --clean --noconfirm "packaging\windows\LiveTranslator.spec"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

Write-Host ""
Write-Host "Built: $Root\dist\LiveTranslator\LiveTranslator.exe"
Write-Host "Try:   $Root\dist\LiveTranslator\LiveTranslator.exe setup"
