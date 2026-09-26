<#
.SYNOPSIS
    Initialise the Baby AI laboratory (Milestone 001).

.DESCRIPTION
    Creates the directory skeleton, provisions separate HUMAN and SYSTEM
    provenance keys, records the baseline in the signed ledger, and emits the
    first events.

    This script only prepares the laboratory. It does not start a subject,
    because Milestone 001 contains no subject: there is no AI here to run, and
    simulating one would contaminate the experiment's first observations.

.PARAMETER Force
    Re-run even if the laboratory already looks initialised. Existing keys and
    the existing ledger are never overwritten.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
#>
[CmdletBinding()]
param([switch]$Force)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    $python = (Get-Command python -ErrorAction Stop).Source
    Write-Host "Python: $python"
    & $python --version

    $humanControl = Join-Path $root 'human_control\security\keys\keyring.json'
    $events = Join-Path $root 'var\events\events.jsonl'

    if ((Test-Path -LiteralPath $humanControl) -and -not $Force) {
        Write-Warning 'Laboratory already appears initialised (keyring present).'
        Write-Warning 'Pass -Force to run the idempotent steps again.'
        Write-Host 'Existing keys and ledger data are left untouched.'
        exit 0
    }

    Write-Host 'Bootstrapping laboratory...'
    & $python -m babylab.bootstrap
    if ($LASTEXITCODE -ne 0) {
        throw "bootstrap failed with exit code $LASTEXITCODE"
    }

    Write-Host ''
    Write-Host 'Verifying provenance ledger...'
    & $python -m provenance.cli verify
    if ($LASTEXITCODE -ne 0) {
        throw "provenance verification failed with exit code $LASTEXITCODE"
    }

    Write-Host ''
    Write-Host 'Bootstrap complete.'
    Write-Host "  Keyring : $humanControl"
    Write-Host "  Events  : $events"
    Write-Host ''
    Write-Host 'Next:'
    Write-Host '  1. Review docs\security-model.md and scripts\trust_boundaries.ps1.'
    Write-Host '  2. Run the tests:      python -m unittest discover -s tests -t .'
    Write-Host '  3. Watch the stream:   python -m observer.cli'
}
finally {
    Pop-Location
}
