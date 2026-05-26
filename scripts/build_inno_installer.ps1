$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Iscc = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue

if (-not $Iscc) {
    throw "Inno Setup compiler ISCC.exe was not found on PATH. Install Inno Setup, then re-run this script."
}

if (-not (Test-Path (Join-Path $Root "dist\LiveTranslator\LiveTranslator.exe"))) {
    throw "Build output not found. Run .\scripts\build_windows.ps1 first."
}

& $Iscc.Source (Join-Path $Root "packaging\windows\LiveTranslator.iss")
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup build failed."
}

Write-Host "Built installer under $Root\dist\installer"
