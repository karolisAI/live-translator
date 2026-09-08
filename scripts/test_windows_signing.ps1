[CmdletBinding()]
param(
    [string]$SignToolPath,
    [string]$UnsignedExecutablePath = (Join-Path $PSScriptRoot "..\.venv\Scripts\live-translator.exe")
)

$ErrorActionPreference = "Stop"
$module = Join-Path $PSScriptRoot "windows_release_security.psm1"
Import-Module $module -Force

$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("live-translator-signing-" + [Guid]::NewGuid().ToString("N"))
$certificate = $null

try {
    New-Item -ItemType Directory -Path $testRoot | Out-Null
    if (-not (Test-Path -LiteralPath $UnsignedExecutablePath -PathType Leaf)) {
        throw "Unsigned test executable was not found: $UnsignedExecutablePath"
    }
    $sourceSignature = Get-AuthenticodeSignature -LiteralPath $UnsignedExecutablePath
    if ($sourceSignature.Status -ne [System.Management.Automation.SignatureStatus]::NotSigned) {
        throw "Signing test requires an unsigned source executable; status was $($sourceSignature.Status)."
    }
    $testExe = Join-Path $testRoot "LiveTranslator-signing-test.exe"
    Copy-Item -LiteralPath $UnsignedExecutablePath -Destination $testExe
    [System.IO.File]::SetAttributes($testExe, [System.IO.FileAttributes]::Normal)

    $certificate = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject "CN=Live Translator Ephemeral Signing Test" `
        -CertStoreLocation "Cert:\CurrentUser\My" `
        -NotAfter (Get-Date).AddHours(1)
    Invoke-WindowsSign `
        -FilePath $testExe `
        -CertificateThumbprint $certificate.Thumbprint `
        -SignToolPath $SignToolPath
    $signature = Get-AuthenticodeSignature -LiteralPath $testExe
    if ($null -eq $signature.SignerCertificate -or
        $signature.SignerCertificate.Thumbprint -ne $certificate.Thumbprint) {
        throw "The test executable was not signed by the ephemeral test certificate."
    }
    if ($signature.Status -notin @(
            [System.Management.Automation.SignatureStatus]::Valid,
            [System.Management.Automation.SignatureStatus]::UnknownError
        )) {
        throw "The ephemeral test signature could not be read (status: $($signature.Status))."
    }

    # Offset 0x40 is in the signed DOS-stub region, before the PE certificate table.
    $stream = [System.IO.File]::Open(
        $testExe,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
    try {
        $stream.Position = 0x40
        $originalByte = $stream.ReadByte()
        if ($originalByte -lt 0) {
            throw "The test executable is too small for the tamper test."
        }
        $stream.Position = 0x40
        $stream.WriteByte($originalByte -bxor 0x01)
    }
    finally {
        $stream.Dispose()
    }

    $tamperedSignature = Get-AuthenticodeSignature -LiteralPath $testExe
    if ($tamperedSignature.Status -ne [System.Management.Automation.SignatureStatus]::HashMismatch) {
        throw "Tampered executable unexpectedly passed signature verification (status: $($tamperedSignature.Status))."
    }

    Write-Host "Ephemeral signing test passed: valid signature accepted and tampering rejected."
}
finally {
    if ($null -ne $certificate) {
        & certutil.exe -user -delstore My $certificate.Thumbprint *> $null
        $remaining = Get-ChildItem -LiteralPath "Cert:\CurrentUser\My" |
            Where-Object Thumbprint -eq $certificate.Thumbprint
        if ($remaining) {
            throw "Ephemeral signing certificate cleanup failed."
        }
    }
    if (Test-Path -LiteralPath $testRoot) {
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}
