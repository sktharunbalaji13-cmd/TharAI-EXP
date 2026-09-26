<#
.SYNOPSIS
    Start the Baby AI control process.

.DESCRIPTION
    Runs the control server as a separate process. The server listens on the
    loopback interface only and requires an HMAC-SHA256 tag computed with the
    token stored under human_control\security\control.token.

    Milestone 001 has no experimental subject. PAUSE and RESUME therefore act
    on the control process's own lifecycle state and say so in their response;
    they do not simulate anything.

.PARAMETER Port
    TCP port to listen on. Use 0 (the default) to let the OS choose; the chosen
    port is recorded in human_control/experiment_config/control.json and printed
    on startup.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\start_control.ps1
#>
[CmdletBinding()]
param([int]$Port = 0, [switch]$Foreground)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    $python = (Get-Command python -ErrorAction Stop).Source
    $token = Join-Path $root 'human_control\security\control.token'

    if (-not (Test-Path -LiteralPath $token)) {
        throw "Control token not found: $token`nRun scripts\bootstrap.ps1 first."
    }

    $argv = @('-m', 'control.cli')
    if ($Port -ne 0) { $argv += @('--port', $Port) }
    $argv += 'serve'
    Write-Host "Starting control process: $python $($argv -join ' ')" -ForegroundColor DarkGray
    Write-Host "Token: $token (required by the client; never sent over the wire)" -ForegroundColor DarkGray

    if ($Foreground) {
        & $python @argv
        exit $LASTEXITCODE
    }

    $proc = Start-Process -FilePath $python -ArgumentList $argv -PassThru -NoNewWindow
    Write-Host "Control process started (PID $($proc.Id))." -ForegroundColor Green
    Write-Host ''
    Write-Host 'Drive it from another terminal:'
    Write-Host "  python -m control.cli status"
    Write-Host "  python -m control.cli snapshot --label before-run"
    Write-Host "  python -m control.cli shutdown"
    Write-Host ''
    Write-Host "Stop it with:  Stop-Process -Id $($proc.Id)"
    exit 0
}
finally {
    Pop-Location
}
