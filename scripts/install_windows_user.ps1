param(
    [string]$InstallDir = "$env:LOCALAPPDATA\Programs\LiveTranslator"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$BuildDir = Join-Path $Root "dist\LiveTranslator"
$Exe = Join-Path $BuildDir "LiveTranslator.exe"

if (-not (Test-Path $Exe)) {
    throw "Build output not found. Run .\scripts\build_windows.ps1 first."
}

New-Item -ItemType Directory -Force $InstallDir | Out-Null
Copy-Item -Path (Join-Path $BuildDir "*") -Destination $InstallDir -Recurse -Force

$Command = Join-Path $InstallDir "LiveTranslator.exe"
Write-Host "Installed LiveTranslator to $InstallDir"
Write-Host "First run: & `"$Command`" setup"
Write-Host "Meeting:   & `"$Command`" meeting"
