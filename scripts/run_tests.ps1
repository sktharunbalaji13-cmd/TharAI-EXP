<#
.SYNOPSIS
    Run the Baby AI laboratory test suite.

.DESCRIPTION
    Runs the standard-library test suite (189 tests, no third-party
    dependencies) and, unless -NoPytest is given, the optional pytest runner as
    a second opinion.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\run_tests.ps1
#>
[CmdletBinding()]
param([switch]$NoPytest)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    $python = (Get-Command python -ErrorAction Stop).Source
    $failed = $false

    Write-Host '=== unittest ===' -ForegroundColor Cyan
    & $python -m unittest discover -s tests -t . -v
    if ($LASTEXITCODE -ne 0) { $failed = $true }

    if (-not $NoPytest) {
        Write-Host ''
        Write-Host '=== pytest (optional) ===' -ForegroundColor Cyan
        if (& $python -c 'import pytest' 2>$null) {
            & $python -m pytest -q
            if ($LASTEXITCODE -ne 0) { $failed = $true }
        }
        else {
            Write-Host 'pytest is not installed; skipping. It is optional.'
            Write-Host 'Install it with: python -m pip install -r requirements-dev.txt'
        }
    }

    if ($failed) {
        Write-Host ''
        Write-Host 'TESTS FAILED' -ForegroundColor Red
        exit 1
    }
    Write-Host ''
    Write-Host 'All tests passed.' -ForegroundColor Green
    exit 0
}
finally {
    Pop-Location
}
