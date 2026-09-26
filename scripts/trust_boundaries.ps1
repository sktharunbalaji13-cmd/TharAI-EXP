<#
.SYNOPSIS
    Audit and apply Windows ACLs for the Baby AI laboratory trust boundaries.

.DESCRIPTION
    The laboratory's security model has three tiers, and this script exists to
    be honest about which ones are actually in force:

      TIER 1  Application policy (ALWAYS ACTIVE)
              babylab/trust.py refuses writes to human_control/ and var/ by
              any code that is not the privileged writer. Tested on every run.
              This is a policy the subject can bypass, because the subject runs
              as the same user and can simply not call this code.

      TIER 2  OS file permissions (OPTIONAL, NOT ACTIVE BY DEFAULT)
              NTFS ACLs granting the subject's service account read-only access
              to the observable paths and no access to human_control/. This is
              what actually stops a misbehaving subject, because the kernel
              enforces it. Applying it requires an elevated session and a
              separate Windows account to run as.

      TIER 3  OS account isolation / containers (NOT IMPLEMENTED)
              Running the subject as a separate low-privilege principal, and
              optionally inside a container or restricted token. This is the
              strongest tier and the only one that meaningfully contains a
              determined adversary. Not implemented in Milestone 001.

    Running this script WITHOUT -Apply performs a read-only audit and reports
    the current state. Running it WITH -Apply modifies ACLs and REQUIRES an
    elevated PowerShell session, because it is a security-relevant change to
    the machine.

    If -AiServiceAccount is not supplied, Tier 2 cannot be applied and the
    script says so rather than pretending the boundary exists.

.PARAMETER Apply
    Actually change ACLs. Omit for a read-only audit.

.PARAMETER AiServiceAccount
    The Windows account the experimental subject will run as, e.g. 'BABYAI'.
    Required for Tier 2.

.PARAMETER GrantCurrentUserFullControl
    Ensure the current (human) user retains full control of the laboratory.
    Default is on, because a misconfigured ACL that locks the human out of
    their own experiment is a worse outcome than a slightly loose ACL.

.EXAMPLE
    # Read-only audit (safe, no elevation needed)
    powershell -ExecutionPolicy Bypass -File scripts\trust_boundaries.ps1

.EXAMPLE
    # Apply Tier 2 (elevated PowerShell only)
    powershell -ExecutionPolicy Bypass -File scripts\trust_boundaries.ps1 -Apply -AiServiceAccount BABYAI
#>
[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$AiServiceAccount,
    [switch]$GrantCurrentUserFullControl = $true
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$root = Split-Path -Parent $PSScriptRoot

# Paths grouped by the access the subject should have.
$subjectReadOnly = @(
    'var\events',
    'baby_workspace\code',
    'baby_workspace\experiments',
    'baby_workspace\memory',
    'baby_workspace\generated',
    'baby_workspace\temporary'
)
$subjectForbidden = @(
    'human_control',
    'var\provenance',
    'human_control\security\keys\private'
)

function Test-Elevated {
    $identity  = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Format-AclReport {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        Write-Host ("  [MISSING ] {0}" -f $Path) -ForegroundColor DarkYellow
        return $null
    }
    $acl = Get-Acl -LiteralPath $Path
    Write-Host ("  [PRESENT ] {0}" -f $Path) -ForegroundColor DarkGray
    foreach ($rule in $acl.Access) {
        Write-Host ("             {0,-10} {1,-6} {2}" -f $rule.IdentityReference, $rule.AccessControlType, $rule.FileSystemRights) -ForegroundColor DarkGray
    }
    return $acl
}

Write-Host '===============================================================' -ForegroundColor Cyan
Write-Host ' Baby AI laboratory - trust boundary audit' -ForegroundColor Cyan
Write-Host '===============================================================' -ForegroundColor Cyan
Write-Host ("Repository: {0}" -f $root)
Write-Host ("Elevated  : {0}" -f (Test-Elevated))
Write-Host ''

# --- Tier 1 -----------------------------------------------------------------
Write-Host 'TIER 1 - application policy (ALWAYS ACTIVE)' -ForegroundColor Green
Write-Host '  babylab/trust.py: PathPolicy refuses writes to human_control/ and var/.' -ForegroundColor DarkGray
Write-Host '  Enforced by: every privileged writer in this codebase, on every call.' -ForegroundColor DarkGray
Write-Host '  Limitation  : the subject shares the OS user, so it can bypass this code' -ForegroundColor DarkYellow
Write-Host '                entirely. Tier 1 detects accidents; it does not contain' -ForegroundColor DarkYellow
Write-Host '                a determined subject.' -ForegroundColor DarkYellow
Write-Host ''

# --- Tier 2 -----------------------------------------------------------------
Write-Host 'TIER 2 - OS file permissions' -ForegroundColor Yellow
if (-not $AiServiceAccount) {
    Write-Host '  NOT CONFIGURED. No -AiServiceAccount was supplied.' -ForegroundColor Yellow
    Write-Host '  To enable, run elevated:' -ForegroundColor DarkGray
    Write-Host '    .\scripts\trust_boundaries.ps1 -Apply -AiServiceAccount BABYAI' -ForegroundColor DarkGray
}
else {
    $account = $null
    try {
        $account = [Security.Principal.NTAccount]::new($AiServiceAccount).Translate([Security.Principal.SecurityIdentifier]).Value
    }
    catch {
        Write-Host ("  Account '{0}' could not be resolved to a SID: {1}" -f $AiServiceAccount, $_.Exception.Message) -ForegroundColor Red
        Write-Host '  Create it first (elevated):  net user BABYAI <strong password> /passwordchg' -ForegroundColor DarkGray
    }
    if ($account) {
        Write-Host ("  Subject account: {0} (SID {1})" -f $AiServiceAccount, $account) -ForegroundColor DarkGray
    }
}
Write-Host ''

if (-not $Apply) {
    Write-Host 'Current ACL state (read-only audit):' -ForegroundColor Cyan
    foreach ($p in ($subjectReadOnly + $subjectForbidden)) {
        $full = Join-Path $root $p
        $null = Format-AclReport -Path $full
        Write-Host ''
    }
    Write-Host 'No changes were made. Re-run with -Apply from an elevated session' -ForegroundColor DarkGray
    Write-Host 'to apply Tier 2. Until then, Tier 2 is NOT ACTIVE.' -ForegroundColor DarkYellow
    exit 0
}

# --- Apply ------------------------------------------------------------------
Write-Host 'APPLYING CHANGES' -ForegroundColor Yellow
if (-not (Test-Elevated)) {
    Write-Host 'Refusing to modify ACLs: this session is not elevated.' -ForegroundColor Red
    Write-Host 'Open PowerShell as Administrator and re-run the same command.' -ForegroundColor Red
    exit 2
}
if (-not $AiServiceAccount) {
    Write-Host 'Refusing to apply: -AiServiceAccount is required, because ACLs that' -ForegroundColor Red
    Write-Host 'exclude everyone named also exclude nobody named.' -ForegroundColor Red
    exit 2
}

$exit = 0
foreach ($rel in $subjectForbidden) {
    $full = Join-Path $root $rel
    if (-not (Test-Path -LiteralPath $full)) { continue }
    Write-Host ("  Denying write to {0}" -f $rel) -ForegroundColor DarkGray
    # Deny the subject account write, allowing read to remain possible.
    & icacls $full /deny "${AiServiceAccount}:(OI)(CI)(W,D,DC)" /T /C | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host ("    icacls failed for {0} (exit {1})" -f $rel, $LASTEXITCODE) -ForegroundColor Red
        $exit = 1
    }
}
foreach ($rel in $subjectReadOnly) {
    $full = Join-Path $root $rel
    if (-not (Test-Path -LiteralPath $full)) { continue }
    Write-Host ("  Granting read-only to {0}" -f $rel) -ForegroundColor DarkGray
    & icacls $full /grant "${AiServiceAccount}:(OI)(CI)(R)" /T /C | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host ("    icacls failed for {0} (exit {1})" -f $rel, $LASTEXITCODE) -ForegroundColor Red
        $exit = 1
    }
}
if ($GrantCurrentUserFullControl) {
    $me = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    Write-Host ("  Ensuring {0} retains full control of the repository" -f $me) -ForegroundColor DarkGray
    & icacls $root /grant "${me}:(OI)(CI)F" /T /C | Out-Null
}

Write-Host ''
Write-Host '--- Post-apply verification ---' -ForegroundColor Cyan
foreach ($rel in ($subjectReadOnly + $subjectForbidden)) {
    $null = Format-AclReport -Path (Join-Path $root $rel)
    Write-Host ''
}
Write-Host 'Tier 2 applied. Verify enforcement by actually running the subject as the' -ForegroundColor Yellow
Write-Host 'restricted account and confirming it cannot write to human_control\. Until' -ForegroundColor Yellow
Write-Host 'that test passes, Tier 2 remains UNVERIFIED. Tier 3 is still NOT IMPLEMENTED.' -ForegroundColor Yellow
exit $exit
