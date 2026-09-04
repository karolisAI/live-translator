param([switch]$ValidateOnly)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

$Uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $Uv) {
    throw "uv is required for a reproducible build. Install the pinned version from pyproject.toml."
}

& $Uv.Source sync --frozen --extra build --no-default-groups
if ($LASTEXITCODE -ne 0) {
    throw "Locked build environment synchronization failed."
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"

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

& $Python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is missing from the locked build environment."
}

& $Python -m PyInstaller --clean --noconfirm "packaging\windows\LiveTranslator.spec"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

$DistRoot = Join-Path $Root "dist\LiveTranslator"
$DistInternal = Join-Path $DistRoot "_internal"
$DistExe = Join-Path $DistRoot "LiveTranslator.exe"
$DistManifest = Join-Path $DistInternal "runtime-assets.manifest.json"
$DistSbom = Join-Path $DistRoot "live-translator.cdx.json"

if (-not (Test-Path -LiteralPath $DistExe -PathType Leaf)) {
    throw "Packaged executable is missing: $DistExe"
}

& $Python -m live_translator.validate_assets `
    --root $DistInternal `
    --manifest $DistManifest
if ($LASTEXITCODE -ne 0) {
    throw "Packaged dist asset validation failed. The build must not be distributed."
}

& $Uv.Source export --frozen --no-dev --no-emit-project `
    --format cyclonedx1.5 --output-file $DistSbom
if ($LASTEXITCODE -ne 0) {
    throw "Release SBOM generation failed. The build must not be distributed."
}

& $Python (Join-Path $Root "scripts\validate_sbom.py") $DistSbom
if ($LASTEXITCODE -ne 0) {
    throw "Release SBOM validation failed. The build must not be distributed."
}

& $DistExe --help *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Packaged executable smoke test failed with exit code $LASTEXITCODE."
}

Write-Host ""
Write-Host "Built and verified: $DistExe"
Write-Host "Dependency SBOM:   $DistSbom"
Write-Host "Try:                $DistExe setup"
