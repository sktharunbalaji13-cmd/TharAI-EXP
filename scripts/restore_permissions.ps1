<#
.SYNOPSIS
    Capture and restore NTFS permissions for the Baby AI research paths.

.DESCRIPTION
    Milestone 005 recovery. A HUMAN / CONTROL operation that must never be
    reachable from the subject trust domain.

        -Capture   Save the current ACL of every protected path.
        -Restore   Return every protected path to its captured state.

    Implementation note
    -------------------
    Both directions use `icacls` rather than the .NET access-control API. A
    composite `FileSystemRights` such as GENERIC_ALL (268435456) has no single
    enum name, and PowerShell refuses to cast or construct it, so a
    .NET-based round trip aborts partway through the protected set and leaves
    the operator worse off than before. `icacls` takes and reports the same
    information without the round-trip hazard, so the recovery path is built on
    it end to end.

    Why recovery is possible at all
    ------------------------------
    The operator is the OWNER of these files and an owner holds implicit
    WRITE_DAC. That is what lets -Capture and -Restore run without elevation --
    and it is precisely why this script must stay outside the subject's reach.

.NOTES
    Snapshots are written under var/, which is excluded from version control, so
    a machine-specific ACL record never enters the research history.
#>
[CmdletBinding(DefaultParameterSetName = 'Capture')]
param(
    [Parameter(Mandatory, ParameterSetName = 'Capture')][switch]$Capture,
    [Parameter(Mandatory, ParameterSetName = 'Restore')][switch]$Restore,
    [string]$RepositoryRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$SnapshotPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($SnapshotPath)) {
    $SnapshotPath = Join-Path $RepositoryRoot 'var\acl-snapshots\protected-paths.json'
}

# The protected set, resolved from the real laboratory layout.
$Protected = @(
    'human_control',
    'human_control\provenance',
    'human_control\security\keys',
    'human_control\security\keys\private',
    'human_control\security\control.token',
    'human_control\birth_records',
    'human_control\research_records',
    'human_control\snapshots',
    'human_control\experiment_config',
    'var\events',
    'var\provenance',
    'docs',
    'research',
    '.git',
    'baby_workspace',
    'baby_workspace\temporary'
)

# icacls prints:  <path> <TRUSTEE>:<rights>
# Milestone 004 shipped a parser that read <path> as the trustee; this one
# splits off exactly one leading path token and takes the remainder.
function ConvertFrom-IcaclsLine {
    param([Parameter(Mandatory)][string]$Line)
    $parts = $Line.Trim() -split ' ', 2
    if ($parts.Count -ne 2) { return $null }
    $remainder = $parts[1]
    $idx = $remainder.LastIndexOf(':')
    if ($idx -lt 0) { return $null }
    return [pscustomobject]@{
        Trustee = $remainder.Substring(0, $idx)
        Rights  = $remainder.Substring($idx + 1)
    }
}

if ($Capture) {
    $records = @()
    foreach ($rel in $Protected) {
        $full = Join-Path $RepositoryRoot $rel
        if (-not (Test-Path -LiteralPath $full)) {
            $records += [pscustomobject]@{ path = $rel; exists = $false; entries = @() }
            continue
        }
        $raw = & icacls $full
        $entries = @()
        foreach ($line in @($raw)) {
            if ([string]::IsNullOrWhiteSpace($line)) { continue }
            if ($line -match '^Successfully processed') { continue }
            $entry = ConvertFrom-IcaclsLine -Line $line
            if ($null -ne $entry) { $entries += $entry }
        }
        $records += [pscustomobject]@{
            path    = $rel
            exists  = $true
            owner   = (Get-Acl -LiteralPath $full).Owner
            entries = @($entries | ForEach-Object {
                [pscustomobject]@{
                    trustee   = $_.Trustee
                    rights    = $_.Rights
                    inherited = [bool]($_.Rights -match '\(I\)')
                    deny      = [bool]($_.Rights -match '\(DENY\)')
                }
            })
        }
    }

    $payload = [pscustomobject]@{
        schema     = 'babylab/acl-snapshot/v1'
        capturedAt = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
        operator   = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        note       = 'Human-only recovery record. Excluded from version control.'
        paths      = $records
    }

    $parent = Split-Path -Parent $SnapshotPath
    if (-not [string]::IsNullOrWhiteSpace($parent)) {
        [System.IO.Directory]::CreateDirectory($parent) | Out-Null
    }
    [System.IO.File]::WriteAllText(
        $SnapshotPath, ($payload | ConvertTo-Json -Depth 8), [System.Text.UTF8Encoding]::new($false))
    Write-Output ("Captured {0} path records to {1}" -f $records.Count, $SnapshotPath)
    return
}

if ($Restore) {
    if (-not (Test-Path -LiteralPath $SnapshotPath -PathType Leaf)) {
        throw ("No ACL snapshot found at {0}. Run -Capture first." -f $SnapshotPath)
    }
    $snapshot = Get-Content -Raw -LiteralPath $SnapshotPath | ConvertFrom-Json
    $restored = 0

    foreach ($record in @($snapshot.paths)) {
        if (-not $record.exists) { continue }
        $full = Join-Path $RepositoryRoot $record.path
        if (-not (Test-Path -LiteralPath $full)) { continue }

        # Return the path to its inherited state first, so a partially applied
        # change cannot survive, then re-apply the captured EXPLICIT entries
        # (inherited ones come back on their own).
        & icacls $full /reset | Out-Null

        foreach ($entry in @($record.entries)) {
            if ($entry.inherited) { continue }
            if ([string]::IsNullOrWhiteSpace($entry.trustee)) { continue }
            $verb = if ($entry.deny) { '/deny' } else { '/grant' }
            & icacls $full $verb ("{0}:{1}" -f $entry.trustee, $entry.rights) | Out-Null
        }
        $restored++
    }
    Write-Output ("Restored {0} path records from {1}" -f $restored, $SnapshotPath)
    Write-Output 'Verify the human operator and the control process can still read and write their paths.'
    return
}
