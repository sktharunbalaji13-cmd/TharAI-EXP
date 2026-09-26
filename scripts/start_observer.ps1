<#
.SYNOPSIS
    Start the read-only terminal observer.

.DESCRIPTION
    Streams the laboratory's event log to the terminal. The observer opens the
    event log for reading only: it cannot append, rewrite, or delete anything,
    and it holds no key capable of writing to the provenance ledger.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start_observer.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start_observer.ps1 -Mode detail -MaxHistory 50

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start_observer.ps1 -Namespace security -NoFollow
#>
[CmdletBinding()]
param(
    [string[]]$Namespace,
    [string[]]$Type,
    [ValidateSet('normal', 'summary', 'detail')]
    [string]$Mode = 'normal',
    [int]$MaxHistory = 0,
    [int]$PollMs = 500,
    [int]$ProgressEvery = 0,
    [switch]$NoFollow,
    [switch]$NoColor
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    $python = (Get-Command python -ErrorAction Stop).Source

    $argv = @('-m', 'observer.cli')
    if ($Namespace)      { foreach ($n in $Namespace) { $argv += @('--namespace', $n) } }
    if ($Type)           { foreach ($t in $Type)     { $argv += @('--type', $t) } }
    if ($Mode -eq 'summary') { $argv += '--summary' }
    if ($Mode -eq 'detail')  { $argv += @('--detail', '--source') }
    if ($MaxHistory -gt 0)   { $argv += @('--max-history', $MaxHistory) }
    if ($ProgressEvery -gt 0){ $argv += @('--progress-every', $ProgressEvery) }
    if ($NoFollow)           { $argv += '--no-follow' }
    if ($NoColor)            { $argv += '--no-color' }
    if (-not $NoFollow)      { $argv += @('--poll-interval', ($PollMs / 1000.0)) }

    Write-Host "Starting observer: $python $($argv -join ' ')" -ForegroundColor DarkGray
    Write-Host 'The observer is read-only. Ctrl-C to stop following.' -ForegroundColor DarkGray
    & $python @argv
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
