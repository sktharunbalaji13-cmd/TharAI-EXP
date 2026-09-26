<#
.SYNOPSIS
    Verify the integrity of the signed provenance ledger.

.DESCRIPTION
    Re-reads the ledger from disk, recomputes every hash chain link, checks
    every HMAC signature, and validates the seal. Exits non-zero if anything
    fails, so it is usable as a scheduled check.

    IMPORTANT: verification reads from disk and never consults the in-memory
    index cache. A cache is a performance detail, not a source of truth.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\verify_integrity.ps1
#>
[CmdletBinding()]
param([switch]$Quiet)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    $python = (Get-Command python -ErrorAction Stop).Source
    & $python -m provenance.cli verify
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        Write-Host ''
        Write-Host 'INTEGRITY CHECK FAILED' -ForegroundColor Red
        Write-Host 'Treat the ledger as untrustworthy until a human explains the difference.'
    }
    elseif (-not $Quiet) {
        Write-Host ''
        Write-Host 'Integrity check passed.' -ForegroundColor Green
    }
    exit $code
}
finally {
    Pop-Location
}
