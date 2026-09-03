param(
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$DistRoot = Join-Path $Root "dist\LiveTranslator"
$DistInternal = Join-Path $DistRoot "_internal"
$DistExe = Join-Path $DistRoot "LiveTranslator.exe"
if (-not (Test-Path -LiteralPath $DistExe -PathType Leaf)) {
    throw "Build output not found. Run .\scripts\build_windows.ps1 first."
}

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Missing venv Python at $Python. It is required to verify dist before packaging."
}

& $Python -m live_translator.validate_assets `
    --root $DistInternal `
    --manifest (Join-Path $DistInternal "runtime-assets.manifest.json")
if ($LASTEXITCODE -ne 0) {
    throw "Packaged dist asset validation failed. Installer creation stopped."
}

if ($ValidateOnly) {
    Write-Host "Packaged dist validation complete; Inno Setup was not run."
    return
}

$Iscc = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
if (-not $Iscc) {
    throw "Inno Setup compiler ISCC.exe was not found on PATH. Install Inno Setup, then re-run this script."
}

& $Iscc.Source (Join-Path $Root "packaging\windows\LiveTranslator.iss")
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup build failed."
}

Write-Host "Built installer under $Root\dist\installer"
