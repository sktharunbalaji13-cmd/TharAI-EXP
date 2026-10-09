# M088 — Windows-Native Credential Procedure (Settings GUI, Home-compatible)

**Status: PROCEDURE SPECIFICATION ONLY.** No account created, no secret entered,
no state changed. Inspected edition: **Microsoft Windows 11 Home Single Language
(10.0.26200)** — verified read-only via OS version query on this machine.

## 1. Interface decision (evidence-based)

- `lusrmgr.msc` file present in System32, but Home edition does not support the
  Local Users and Groups snap-in (file presence ≠ functionality; the snap-in was
  NOT launched to check — launching GUI is out of read-only scope). NOT recommended.
- Settings app (`windows.immersivecontrolpanel`) present. The Settings path works
  on all Windows 11 editions including Home. RECOMMENDED primary procedure.
- `net.exe` present. Console `net user babyai-subject * /add` (star-prompt, typed
  hidden, never as argument) is a documented FALLBACK only if the Settings flow
  is unavailable at execution; same secrecy constraints apply.

## 2. Exact primary procedure (human hands, elevated interactive session)

1. Preconditions (all re-verified first): Auth-1 digest `ed992f56…c1234`;
   `babyai-subject` absent (`net user` → not found); operator baseline noted.
2. Open Settings (Win+I) → Accounts → Other users → Add account.
3. "I don't have this person's sign-in information" → "Add a user without a
   Microsoft account".
4. Enter user name `babyai-subject` + password twice in the GUI fields.
5. Complete any required security questions the dialog mandates; treat answers
   with password-grade secrecy; record THAT they were set, never content.
6. Finish; confirm the account appears under Other users.
7. DO NOT add to Administrators; DO NOT change the account type afterward.
8. If ANY screen, prompt, or option differs from the above: STOP (flow differs —
   do not improvise; report the exact deviation).

## 3. Observable outcomes (read-only verification after setup)

- `net user babyai-subject` lists the account active.
- `net localgroup administrators` does NOT list it (read-only membership proof).
- `whoami /groups` + `whoami /priv` from an interactive logon as the new account
  show standard-user rights only (no SeImpersonate/SeAssignPrimaryToken/SeTcb).
- Token SID read equals the provisioned account SID (else NOT VERIFIED).

## 4. Abort conditions

Elevation lost; dialog flow differs; account already exists; unexpected group/
privilege; any ACL/production/network side effect observed; partial completion
(report exact state, no improvised rollback beyond separately authorized scope).

## 5. Secret handling (binding)

The password exists ONLY in the human's hands and the OS dialog. It must never
enter chat, prompts, commands, scripts, logs, commits, evidence, or provenance.
This document contains no secret and requests none. Security questions/answers,
if set, inherit the same rule.
