param(
    [switch]$InstallBuildTools,
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Missing venv Python at $Python. Create the venv and install dependencies first."
}

& $Python -m live_translator.validate_assets `
    --root $Root `
    --manifest (Join-Path $Root "packaging\runtime-assets.manifest.json")
if ($LASTEXITCODE -ne 0) {
    throw "Runtime asset integrity validation failed. Build stopped before PyInstaller."
}

if ($ValidateOnly) {
    Write-Host "Asset validation complete; PyInstaller was not run."
    return
}

if ($InstallBuildTools) {
    & $Python -m pip install -e ".[build]"
}

& $Python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is not installed. Re-run with: .\scripts\build_windows.ps1 -InstallBuildTools"
}

& $Python -m PyInstaller --clean --noconfirm "packaging\windows\LiveTranslator.spec"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

$DistRoot = Join-Path $Root "dist\LiveTranslator"
$DistInternal = Join-Path $DistRoot "_internal"
$DistExe = Join-Path $DistRoot "LiveTranslator.exe"
$DistManifest = Join-Path $DistInternal "runtime-assets.manifest.json"

if (-not (Test-Path -LiteralPath $DistExe -PathType Leaf)) {
    throw "Packaged executable is missing: $DistExe"
}

& $Python -m live_translator.validate_assets `
    --root $DistInternal `
    --manifest $DistManifest
if ($LASTEXITCODE -ne 0) {
    throw "Packaged dist asset validation failed. The build must not be distributed."
}

& $DistExe --help *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Packaged executable smoke test failed with exit code $LASTEXITCODE."
}

Write-Host ""
Write-Host "Built and verified: $DistExe"
Write-Host "Try:                $DistExe setup"
