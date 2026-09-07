Set-StrictMode -Version Latest

function Resolve-SignTool {
    [CmdletBinding()]
    param([string]$SignToolPath)

    if ($SignToolPath) {
        if (-not (Test-Path -LiteralPath $SignToolPath -PathType Leaf)) {
            throw "SignTool was not found at the configured path: $SignToolPath"
        }
        return (Resolve-Path -LiteralPath $SignToolPath).Path
    }

    $command = Get-Command "signtool.exe" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $kitsRoot = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    if (Test-Path -LiteralPath $kitsRoot -PathType Container) {
        $candidate = Get-ChildItem -LiteralPath $kitsRoot -Filter "signtool.exe" -File -Recurse |
            Where-Object { $_.FullName -match "\\x64\\signtool\.exe$" } |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        if ($candidate) {
            return $candidate.FullName
        }
    }

    throw "signtool.exe was not found. Install the Windows SDK signing tools or pass -SignToolPath."
}

function Assert-ApprovedSigningConfiguration {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$CertificateThumbprint,
        [Parameter(Mandatory = $true)][string]$TimestampUrl
    )

    $normalizedThumbprint = $CertificateThumbprint.Replace(" ", "").ToUpperInvariant()
    if ($normalizedThumbprint -notmatch "^[0-9A-F]{40}$|^[0-9A-F]{64}$") {
        throw "Certificate thumbprint must be a 40- or 64-character hexadecimal value."
    }

    $timestampUri = $null
    if (-not [Uri]::TryCreate($TimestampUrl, [UriKind]::Absolute, [ref]$timestampUri) -or
        $timestampUri.Scheme -ne "https") {
        throw "Approved releases require an absolute HTTPS RFC 3161 timestamp URL."
    }

    return $normalizedThumbprint
}

function Invoke-WindowsSign {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string]$CertificateThumbprint,
        [string]$TimestampUrl,
        [string]$SignToolPath
    )

    $resolvedFile = (Resolve-Path -LiteralPath $FilePath -ErrorAction Stop).Path
    $resolvedSignTool = Resolve-SignTool -SignToolPath $SignToolPath
    $thumbprint = $CertificateThumbprint.Replace(" ", "").ToUpperInvariant()
    $arguments = @("sign", "/sha1", $thumbprint, "/fd", "SHA256")
    if ($TimestampUrl) {
        $arguments += @("/tr", $TimestampUrl, "/td", "SHA256")
    }
    $arguments += @("/v", $resolvedFile)

    & $resolvedSignTool @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Authenticode signing failed for $resolvedFile."
    }
}

function Assert-WindowsSignature {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string]$ExpectedThumbprint,
        [switch]$RequireTimestamp,
        [switch]$AllowUntrustedDevelopmentCertificate,
        [string]$EvidencePath,
        [string]$SignToolPath
    )

    $resolvedFile = (Resolve-Path -LiteralPath $FilePath -ErrorAction Stop).Path
    $resolvedSignTool = Resolve-SignTool -SignToolPath $SignToolPath
    if (-not $AllowUntrustedDevelopmentCertificate) {
        $output = & $resolvedSignTool verify /pa /all /v $resolvedFile 2>&1
        $exitCode = $LASTEXITCODE
        if ($EvidencePath) {
            $evidenceParent = Split-Path -Parent $EvidencePath
            New-Item -ItemType Directory -Path $evidenceParent -Force | Out-Null
            $output | Out-File -LiteralPath $EvidencePath -Encoding utf8
        }
        if ($exitCode -ne 0) {
            throw "Authenticode verification failed for $resolvedFile."
        }
    }

    $signature = Get-AuthenticodeSignature -LiteralPath $resolvedFile
    $acceptedStatus = @([System.Management.Automation.SignatureStatus]::Valid)
    if ($AllowUntrustedDevelopmentCertificate) {
        $acceptedStatus += [System.Management.Automation.SignatureStatus]::UnknownError
    }
    if ($signature.Status -notin $acceptedStatus) {
        throw "Windows does not trust the Authenticode signature on $resolvedFile (status: $($signature.Status))."
    }
    $actualThumbprint = $signature.SignerCertificate.Thumbprint.Replace(" ", "").ToUpperInvariant()
    $expected = $ExpectedThumbprint.Replace(" ", "").ToUpperInvariant()
    if ($actualThumbprint -ne $expected) {
        throw "Unexpected signer for $resolvedFile. Expected $expected but found $actualThumbprint."
    }
    if ($RequireTimestamp -and $null -eq $signature.TimeStamperCertificate) {
        throw "The signature on $resolvedFile has no trusted timestamp."
    }
    if ($RequireTimestamp -and $AllowUntrustedDevelopmentCertificate) {
        throw "An approved timestamp cannot be verified in development-certificate mode."
    }
}

function Write-ReleaseChecksums {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string[]]$ArtifactPath,
        [Parameter(Mandatory = $true)][string]$OutputPath
    )

    $lines = foreach ($path in $ArtifactPath) {
        $resolved = (Resolve-Path -LiteralPath $path -ErrorAction Stop).Path
        $hash = Get-FileHash -LiteralPath $resolved -Algorithm SHA256
        "{0}  {1}" -f $hash.Hash.ToLowerInvariant(), (Split-Path -Leaf $resolved)
    }
    $parent = Split-Path -Parent $OutputPath
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $lines | Set-Content -LiteralPath $OutputPath -Encoding ascii
}

Export-ModuleMember -Function Resolve-SignTool, Assert-ApprovedSigningConfiguration, Invoke-WindowsSign, Assert-WindowsSignature, Write-ReleaseChecksums
