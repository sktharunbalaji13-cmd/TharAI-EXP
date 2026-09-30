/* M016 subject boundary probe.
 *
 * Runs as whatever account launches it and reports the real token facts, then
 * attempts a fixed set of filesystem operations against paths given on the
 * command line. It infers nothing: the account is read from the token, and each
 * filesystem result is the actual GetLastError from an attempted operation.
 *
 * Exit codes are the count of operations the OS allowed, capped at 120. Zero
 * means every attempted denial actually happened. This makes "the probe ran and
 * the OS denied everything" distinguishable from "the probe could not run".
 *
 * Build:  csc /nologo /out:probe.exe probe.cs
 * (or Add-Type -OutputType ConsoleApplication on PowerShell 5.1)
 */

using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Principal;

internal static class Probe
{
    // --- token inspection -----------------------------------------------------

    [DllImport("advapi32.dll", SetLastError = true)]
    static extern bool OpenProcessToken(IntPtr process, uint access, out IntPtr token);

    [DllImport("advapi32.dll", SetLastError = true)]
    static extern bool GetTokenInformation(IntPtr token, int infoClass, IntPtr info,
        int length, out int returnLength);

    [DllImport("advapi32.dll", SetLastError = true)]
    static extern bool ConvertSidToStringSid(IntPtr sid, out IntPtr stringSid);

    [DllImport("advapi32.dll", SetLastError = true)]
    static extern bool GetTokenInformation(IntPtr token, TokenInformationClass cls,
        IntPtr info, int length, out int returnLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool CloseHandle(IntPtr handle);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern IntPtr GetCurrentProcess();

    enum TokenInformationClass
    {
        TokenUser = 1,
        TokenIntegrityLevel = 25,
        TokenGroups = 2,
        TokenPrivileges = 3,
    }

    [StructLayout(LayoutKind.Sequential)]
    struct SID_AND_ATTRIBUTES
    {
        public IntPtr Sid;
        public uint Attributes;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct TOKEN_MANDATORY_LABEL
    {
        public IntPtr Label;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct LUID
    {
        public uint LowPart;
        public int HighPart;
    }

    /// TOKEN_PRIVILEGES is a variable-length structure: a DWORD count followed by an
    /// inline array of LUID_AND_ATTRIBUTES (LUID = two DWORDs, plus a DWORD of
    /// attributes = 12 bytes each). The array is read by explicit offset from the
    /// returned buffer rather than through a managed struct, because marshalling
    /// the inline array produced a null pointer at runtime on this toolchain.
    [StructLayout(LayoutKind.Sequential)]
    struct TOKEN_PRIVILEGES
    {
        public uint PrivilegeCount;
        public IntPtr Privileges;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct LUID_AND_ATTRIBUTES
    {
        public LUID Luid;
        public uint Attributes;
    }

    const uint TOKEN_QUERY = 0x0008;

/// Account name for a SID.
    ///
    /// This deliberately does NOT hand-roll LookupAccountSid. A previous version
    /// of this probe did, and the two-call buffer-sizing pattern produced an
    /// access violation that crashed the process before it could report anything.
    /// System.Security.Principal already wraps the same Win32 call correctly, and
    /// a probe that cannot run reports nothing at all -- so the platform wrapper
    /// is used for identity and P/Invoke is reserved for the two facts .NET does
    /// not surface: integrity level and the privilege LUID list.
    static string SidToName(IntPtr sid)
    {
        try
        {
            return new SecurityIdentifier(sid).Translate(typeof(NTAccount)).Value;
        }
        catch (Exception)
        {
            return SidString(sid);
        }
    }

    static string SidString(IntPtr sid)
    {
        IntPtr s = IntPtr.Zero;
        if (!ConvertSidToStringSid(sid, out s)) return "<err:" + Marshal.GetLastWin32Error() + ">";
        try { return Marshal.PtrToStringAnsi(s); }
        finally { LocalFree(s); }
    }

    [DllImport("kernel32.dll")] static extern IntPtr LocalFree(IntPtr handle);

    /// Integrity level as a short name. Read from the token's mandatory label,
    /// not from a token type value, because the token type does not carry it.
static string IntegrityLevel(IntPtr token)
    {
        // Read the mandatory label and decode the RID from the last sub-authority.
        // The label is a SID whose sub-authority count is 1, and whose single value
        // is the RID (S-1-16-<RID>), so the RID is the final DWORD rather than a
        // byte-by-byte accumulation -- reading it as bytes walked past the end.
        int len = 0;
        GetTokenInformation(token, TokenInformationClass.TokenIntegrityLevel,
                            IntPtr.Zero, 0, out len);
        if (len == 0) return "<unreadable>";
        IntPtr buf = Marshal.AllocHGlobal(len);
        try
        {
            if (!GetTokenInformation(token, TokenInformationClass.TokenIntegrityLevel,
                    buf, len, out len))
                return "<unreadable>";
            var label = (TOKEN_MANDATORY_LABEL)Marshal.PtrToStructure(
                buf, typeof(TOKEN_MANDATORY_LABEL));
            if (label.Label == IntPtr.Zero) return "<empty-label>";
            byte count = Marshal.ReadByte(label.Label);
            if (count == 0) return "<empty-label>";
            uint rid = (uint)Marshal.ReadInt32(
                IntPtr.Add(label.Label, 2 + (count - 1) * 4));
            switch (rid)
            {
                case 0x0000: return "UNPROTECTED";
                case 0x1000: return "LOW";
                case 0x2000: return "MEDIUM";
                case 0x3000: return "HIGH";
                case 0x4000: return "SYSTEM";
                default: return "UNKNOWN(" + rid.ToString("X") + ")";
            }
        }
        finally { Marshal.FreeHGlobal(buf); }
    }
    static void EmitIdentity()
    {
        IntPtr token;
        if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, out token))
        {
            Console.WriteLine("identity=FAILED openProcessToken:" + Marshal.GetLastWin32Error());
            return;
        }
        try
        {
            int len;
            GetTokenInformation(token, TokenInformationClass.TokenUser, IntPtr.Zero, 0, out len);
            IntPtr buf = Marshal.AllocHGlobal(len);
            try
            {
                if (GetTokenInformation(token, TokenInformationClass.TokenUser, buf, len, out len))
                {
                    IntPtr sid = Marshal.ReadIntPtr(buf);
                    Console.WriteLine("user_sid=" + SidString(sid));
                    Console.WriteLine("account_name=" + SidToName(sid));
                }
                else Console.WriteLine("user_sid=<unreadable:" + Marshal.GetLastWin32Error() + ">");
            }
            finally { Marshal.FreeHGlobal(buf); }

            Console.WriteLine("integrity_level=" + IntegrityLevel(token));

            // Groups, so a verifier can see membership rather than assume it.
            var groups = new List<string>();
            foreach (System.Security.Principal.IdentityReference g in
                     WindowsIdentity.GetCurrent().Groups)
                groups.Add(g.Translate(typeof(NTAccount)).Value);
            Console.WriteLine("groups=" + string.Join("|", groups.ToArray()));

            // Privileges held. Absence matters as much as presence here: a subject token
            // with no privileges is a normal, safe outcome, not an error.
            GetTokenInformation(token, TokenInformationClass.TokenPrivileges, IntPtr.Zero, 0, out len);
            var held = new List<string>();
            if (len > 0)
            {
                IntPtr pbuf = Marshal.AllocHGlobal(len);
                try
                {
                    if (GetTokenInformation(token, TokenInformationClass.TokenPrivileges, pbuf, len, out len))
                    {
                        uint count = (uint)Marshal.ReadInt32(pbuf);
                        for (uint i = 0; i < count; i++)
                        {
                            // Each entry is LUID{Low,High} followed by Attributes;
                            // read the LUID from its two DWORDs directly.
                            IntPtr e = IntPtr.Add(pbuf, 4 + (int)i * 12);
                            var luid = new LUID {
                                LowPart = (uint)Marshal.ReadInt32(e),
                                HighPart = Marshal.ReadInt32(IntPtr.Add(e, 4)),
                            };
                            string name = LookupPrivilegeName(luid);
                            if (name != null) held.Add(name);
                        }
                    }
                }
                finally { Marshal.FreeHGlobal(pbuf); }
            }
            held.Sort(StringComparer.Ordinal);
            Console.WriteLine("privileges=" + string.Join("|", held.ToArray()));
            Console.WriteLine("privilege_count=" + held.Count);
        }
        finally { CloseHandle(token); }
    }

    /// Privilege name for a LUID, read from the token rather than assumed from a
    /// hardcoded list: which privileges are present is a property of the running
    /// token, and inferring it would defeat the point of the probe.
    ///
    /// The four-argument signature matters. An earlier two-argument declaration
    /// left the output-buffer and length registers uninitialised, which produced
    /// an access violation inside advapi32 rather than a clean failure.
    [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    static extern bool LookupPrivilegeNameW(
        IntPtr system, IntPtr luid,
        System.Text.StringBuilder name, ref int nameLen);

    static string LookupPrivilegeName(LUID luid)
    {
        IntPtr p = Marshal.AllocHGlobal(8);
        try
        {
            Marshal.WriteInt32(p, unchecked((int)luid.LowPart));
            Marshal.WriteInt32(IntPtr.Add(p, 4), luid.HighPart);
            int len = 0;
            if (!LookupPrivilegeNameW(IntPtr.Zero, p, null, ref len) && len <= 0)
                return null;
            var name = new System.Text.StringBuilder(len + 1);
            if (!LookupPrivilegeNameW(IntPtr.Zero, p, name, ref len))
                return null;
            return name.ToString();
        }
        finally { Marshal.FreeHGlobal(p); }
    }

    // --- filesystem operations ------------------------------------------------

    /// Reports the true outcome of one attempted operation.
    ///
    /// The distinction this must preserve: OS_DENIED means the kernel returned
    /// ERROR_ACCESS_DENIED (5). Anything else -- a missing file (2), an existing
    /// name (183), a bad path (3) -- is a PATH_ERROR, not a denial. An earlier
    /// version of this probe collapsed both into OS_DENIED, which would have let a
    /// typo masquerade as the OS enforcing the boundary. A caller must never be
    /// able to read a denial that the OS did not produce.
    static string Run(string label, Action action)
    {
        try
        {
            action();
            Console.WriteLine("probe=" + label + " result=OS_ALLOWED");
            return "OS_ALLOWED";
        }
        catch (UnauthorizedAccessException)
        {
            Console.WriteLine("probe=" + label + " result=OS_DENIED winerror=5");
            return "OS_DENIED";
        }
        catch (IOException ex)
        {
            int code = ex.HResult & 0xFFFF;
            string result = code == 5 ? "OS_DENIED" : "PATH_ERROR";
            Console.WriteLine("probe=" + label + " result=" + result + " winerror=" + code);
            return result;
        }
catch (Exception ex)
        {
            Console.WriteLine("probe=" + label + " result=ERROR " +
                ex.GetType().Name + ":" + ex.Message);
            return "ERROR";
        }
    }

    static void Touch(string p) { using (var f = File.Create(p)) { f.WriteByte(0); } }
    static void Append(string p) { File.AppendAllText(p, "x"); }
    static void Nuke(string p) { File.Delete(p); }

    /// Replace a file by moving another over it, which is the operation that
    /// catches a subject allowed to create but not to delete, or vice versa.
    static void Replace(string src, string dst)
    {
        if (File.Exists(dst)) File.Delete(dst);
        File.Move(src, dst);
    }

    static int Main(string[] args)
    {
        Console.WriteLine("schema=probe/v1");
        Console.WriteLine("pid=" + System.Diagnostics.Process.GetCurrentProcess().Id);
        Console.WriteLine("executable=" + System.Diagnostics.Process.GetCurrentProcess().MainModule.FileName);
        Console.WriteLine("command_line=" + string.Join(" ", args));

        WindowsIdentity id = WindowsIdentity.GetCurrent();
        Console.WriteLine("identity_framework=" + id.Name);

        EmitIdentity();

        if (args.Length < 1)
        {
            Console.WriteLine("probe=NONE result=NOT_TESTABLE reason=no_paths_supplied");
            return 0;
        }

        // paths: <scratchDir> <stagedExecutable> <protectedDir> <workspaceDir>
        string scratch = args[0];
        string staged = args.Length > 1 ? args[1] : "";
        string protectedDir = args.Length > 2 ? args[2] : "";
        string workspace = args.Length > 3 ? args[3] : "";

        int allowed = 0;
        Action bump = delegate { allowed++; };

        // A private copy of the staged file for one destructive operation, made by the
        // probe itself. The copy is created in the scratch directory -- which is
        // inside subject_runtime and therefore carries the same ACL as the staged
        // file -- and it must be created rather than assumed: asking the subject to
        // modify a copy that was never made turns "the file is missing" into what
        // looks like an ACL outcome, which is precisely the confusion this probe
        // exists to avoid.
        Func<string, string> WithSuffix = suffix => {
            string copy = Path.Combine(scratch, "target" + suffix);
            File.Copy(staged, copy, true);
            return copy;
        };

        if (scratch.Length > 0)
        {
            var r = Run("create_file_in_staging_scratch", () => { Touch(Path.Combine(scratch, "p.txt")); bump(); });

            // Operations against the staged executable are only meaningful when a
            // staged path was actually supplied. Running them against an empty
            // string makes .NET resolve "" to the current directory and open a
            // directory as a file, which returns winerror 5 -- a real denial that
            // has nothing to do with the ACL. Reporting it as OS_DENIED would let
            // "no runtime was staged" masquerade as "the OS protected the runtime",
            // so these are skipped explicitly instead.
            if (staged.Length > 0 && File.Exists(staged))
            {
                Run("modify_staged_executable", () => {
                    using (var fs = new FileStream(WithSuffix(".mod"),
                                                   FileMode.Open, FileAccess.Write)) { }
                    bump();
                });
                Run("append_staged_executable", () => { Append(WithSuffix(".app")); bump(); });
                // Deleting first would destroy the file the later rename and
                // replace need, so every destructive operation targets its own
                // fresh copy. Sharing one path makes a genuine rename denial
                // indistinguishable from "the delete already removed it".
                Run("delete_staged_executable", () => { Nuke(WithSuffix(".del")); bump(); });
                Run("rename_staged_executable", () => {
                    // Distinct source and destination names: reusing the source
                    // name hits winerror 183 (name exists), which is a collision
                    // rather than a denial of rename.
                    string source = WithSuffix(".mvsrc");
                    string target = Path.Combine(scratch, "target.mvdst");
                    if (File.Exists(target)) File.Delete(target);
                    File.Move(source, target);
                    File.Delete(target);
                    bump();
                });
                Run("replace_staged_executable", () => {
                    string tmp = Path.Combine(scratch, "replacement.exe");
                    Touch(tmp);
                    Replace(tmp, WithSuffix(".rep"));
                    bump();
                });
                // Created beside the staged runtime, not in the scratch directory, because
                // beside-the-runtime is the case worth testing: the runtime
                // directory must be as read-only to the subject as the file in it.
                string child = Path.Combine(Path.GetDirectoryName(staged) ?? scratch, "child.exe");
                Run("create_child_executable_beside_runtime", () => {
                    Touch(child); bump();
                    try { File.Delete(child); } catch (Exception) { }
                });
            }
            else
            {
                Console.WriteLine("probe=staged_executable_operations result=NOT_TESTABLE " +
                    "reason=no_staged_executable_supplied");
            }
            Run("create_child_directory", () => {
                Directory.CreateDirectory(Path.Combine(scratch, "childdir")); bump();
            });
            Run("delete_child_directory", () => {
                string d = Path.Combine(scratch, "childdir");
                if (Directory.Exists(d)) Directory.Delete(d); bump();
            });
            if (protectedDir.Length > 0)
            {
                Run("modify_acl_on_protected", () => {
                    File.SetAttributes(Path.Combine(protectedDir, "probe_acl_target"), FileAttributes.ReadOnly);
                    bump();
                });
            }
            Console.WriteLine("operations_allowed=" + allowed);
        }

        if (workspace.Length > 0)
        {
            string wf = Path.Combine(workspace, "probe_workspace.txt");
            Run("workspace_write", () => { Touch(wf); bump(); });
            Run("workspace_read", () => { File.ReadAllText(wf); bump(); });
            Run("workspace_delete", () => { Nuke(wf); bump(); });
        }

        // Remove every artefact this run created. A boundary probe that leaves copies
        // of the staged runtime lying in subject_runtime would contaminate the
        // next run and, worse, would have left files in a tree the milestone
        // describes as holding nothing.
        foreach (string leftover in new[] {
            "p.txt", "child.exe", "replacement.exe",
            "target.mod", "target.app", "target.del", "target.ren",
            "target.mvsrc", "target.mvdst", "target.rep" })
        {
            try { if (File.Exists(Path.Combine(scratch, leftover))) File.Delete(Path.Combine(scratch, leftover)); }
            catch (Exception) { /* cleanup is best-effort; a leftover is reported by the inventory */ }
        }
        try { if (Directory.Exists(Path.Combine(scratch, "childdir"))) Directory.Delete(Path.Combine(scratch, "childdir")); }
        catch (Exception) { }
        string workspaceFile = Path.Combine(workspace, "probe_workspace.txt");
        try { if (File.Exists(workspaceFile)) File.Delete(workspaceFile); }
        catch (Exception) { }

        Console.WriteLine("exit_code=" + Math.Min(allowed, 120));
        return Math.Min(allowed, 120);
    }
}