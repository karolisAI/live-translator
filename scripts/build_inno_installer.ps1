param(
    [switch]$ValidateOnly,
    [switch]$ApprovedRelease,
    [string]$CertificateThumbprint = $env:LIVE_TRANSLATOR_SIGNING_CERT_THUMBPRINT,
    [string]$TimestampUrl = $env:LIVE_TRANSLATOR_SIGNING_TIMESTAMP_URL,
    [string]$SignToolPath
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$DistRoot = Join-Path $Root "dist\LiveTranslator"
$DistInternal = Join-Path $DistRoot "_internal"
$DistExe = Join-Path $DistRoot "LiveTranslator.exe"
$DistSbom = Join-Path $DistRoot "live-translator.cdx.json"
$Installer = Join-Path $Root "dist\installer\LiveTranslatorSetup.exe"
$EvidenceDir = Join-Path $Root "dist\installer\release-evidence"
$releaseSecurityModule = Join-Path $PSScriptRoot "windows_release_security.psm1"
Import-Module $releaseSecurityModule -Force
$normalizedThumbprint = $null
$resolvedSignTool = $null
if ($ApprovedRelease) {
    $normalizedThumbprint = Assert-ApprovedSigningConfiguration `
        -CertificateThumbprint $CertificateThumbprint `
        -TimestampUrl $TimestampUrl
    $resolvedSignTool = Resolve-SignTool -SignToolPath $SignToolPath
}
if (-not (Test-Path -LiteralPath $DistExe -PathType Leaf)) {
    throw "Build output not found. Run .\scripts\build_windows.ps1 first."
}

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Missing venv Python at $Python. It is required to verify dist before packaging."
}
if (-not (Test-Path -LiteralPath $DistSbom -PathType Leaf)) {
    throw "Release SBOM is missing: $DistSbom"
}

& $Python -m live_translator.validate_assets `
    --root $DistInternal `
    --manifest (Join-Path $DistInternal "runtime-assets.manifest.json")
if ($LASTEXITCODE -ne 0) {
    throw "Packaged dist asset validation failed. Installer creation stopped."
}

if ($ApprovedRelease) {
    Assert-WindowsSignature `
        -FilePath $DistExe `
        -ExpectedThumbprint $normalizedThumbprint `
        -RequireTimestamp `
        -EvidencePath (Join-Path $EvidenceDir "LiveTranslator.exe.signature.txt") `
        -SignToolPath $resolvedSignTool
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

if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) {
    throw "Inno Setup reported success but the installer is missing: $Installer"
}

if ($ApprovedRelease) {
    Invoke-WindowsSign `
        -FilePath $Installer `
        -CertificateThumbprint $normalizedThumbprint `
        -TimestampUrl $TimestampUrl `
        -SignToolPath $resolvedSignTool
    Assert-WindowsSignature `
        -FilePath $Installer `
        -ExpectedThumbprint $normalizedThumbprint `
        -RequireTimestamp `
        -EvidencePath (Join-Path $EvidenceDir "LiveTranslatorSetup.exe.signature.txt") `
        -SignToolPath $resolvedSignTool
    Copy-Item -LiteralPath $DistSbom -Destination (Join-Path $EvidenceDir "live-translator.cdx.json") -Force
    Write-ReleaseChecksums `
        -ArtifactPath @($DistExe, $Installer, $DistSbom) `
        -OutputPath (Join-Path $EvidenceDir "SHA256SUMS.txt")
    Write-Host "Approved release evidence: $EvidenceDir"
}
else {
    Write-Warning "Unsigned local installer: this output is not an approved release."
}

Write-Host "Built installer under $Root\dist\installer"
