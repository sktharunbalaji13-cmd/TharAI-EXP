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
/// The integrity RID read from a mandatory-label SID.
    ///
    /// Returns null when the SID is structurally unusable, so the caller can
    /// report a parse failure instead of inventing a level. A mandatory-label SID
    /// is S-1-16-&lt;RID&gt;: revision 1, one sub-authority, identifier authority 6.
    ///
    /// The header is 8 bytes, not 2:
    ///
    ///     offset 0  BYTE  Revision
    ///     offset 1  BYTE  SubAuthorityCount
    ///     offset 2  BYTE  IdentifierAuthority[6]
    ///     offset 8  DWORD SubAuthority[SubAuthorityCount]
    ///
    /// Reading the RID from offset 2 lands inside the identifier authority, whose
    /// bytes are 00 00 00 00 00 10 for S-1-16 — so the low DWORD is 0 and a Medium
    /// token reports as UNPROTECTED. Verified on this host: the same token reads
    /// 0x0 at offset 2 and 0x2000 at offset 8.
    static uint? IntegrityRid(IntPtr label)
    {
        if (label == IntPtr.Zero) return null;
        byte count = Marshal.ReadByte(label, 1);
        if (count == 0) return null;
        return (uint)Marshal.ReadInt32(label, 8 + (count - 1) * 4);
    }

    /// Independent second opinion on the integrity level.
    ///
    /// This does not share the offset arithmetic with :meth:`IntegrityLevel` --
    /// it asks advapi32 to format the SID as a string and reads the last
    /// component. Two independent paths agreeing is what makes a reported level
    /// trustworthy; a single path that silently returns 0 looks identical to a
    /// genuinely unprotected token.
    static string IntegrityLevelIndependent(IntPtr token)
    {
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
            IntPtr label = Marshal.ReadIntPtr(buf);
            if (label == IntPtr.Zero) return "<no-label>";
            IntPtr text = IntPtr.Zero;
            if (!ConvertSidToStringSid(label, out text))
                return "<unconvertible>";
            try
            {
                string sid = Marshal.PtrToStringAnsi(text);
                if (sid == null) return "<unconvertible>";
                int dash = sid.LastIndexOf('-');
                if (dash < 0) return "<no-rid:" + sid + ">";
                uint rid;
                if (!uint.TryParse(sid.Substring(dash + 1), out rid)) return "<no-rid:" + sid + ">";
                return NameForRid(rid);
            }
            finally { LocalFree(text); }
        }
        finally { Marshal.FreeHGlobal(buf); }
    }

    static string NameForRid(uint rid)
    {
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

            // A null label pointer means the API returned no mandatory label at
            // all, which is a distinct fact from a RID of zero. They are reported
            // differently so "no label" is never read as "unprotected".
            if (label.Label == IntPtr.Zero) return "<no-label>";

            uint? rid = IntegrityRid(label.Label);
            if (rid == null) return "<unreadable-sid>";
            return NameForRid(rid.Value);
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

            // Two independent reads of the same token fact. They must agree; a
            // disagreement is itself reported, because a probe that cannot tell
            // you it is confused is not evidence of anything.
            string integrityDirect = IntegrityLevel(token);
            string integrityViaSid = IntegrityLevelIndependent(token);
            Console.WriteLine("integrity_level=" + integrityDirect);
            Console.WriteLine("integrity_level_independent=" + integrityViaSid);
            Console.WriteLine("integrity_paths_agree=" +
                (integrityDirect == integrityViaSid ? "true" : "FALSE"));
            if (integrityDirect != integrityViaSid)
                Console.WriteLine("integrity_note=DISAGREEMENT between direct RID read and ConvertSidToStringSid path");
            if (integrityDirect.StartsWith("<"))
                Console.WriteLine("integrity_note=PARSE_FAILED — this is not an integrity level, do not treat it as UNPROTECTED");

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

    /// Positional argument at `index`, with "-" and blank treated as absent.
    ///
    /// The blank case exists because PowerShell removes empty arguments, so a
    /// caller that wants to skip a positional slot must pass something. Treating a
    /// real path as a flag is how the workspace test once ran against an option
    /// string and reported a spurious format error.
    static string Arg(string[] args, int index)
    {
        if (args.Length <= index) return "";
        string value = args[index];
        if (value == null || value.Trim().Length == 0) return "";
        if (value == "-") return "";
        return value;
    }

    /// Reads a --name=value argument. Returns "" when absent.
    ///
    /// An absent option is not an error: the caller decides whether the missing
    /// path means the case is not applicable or that the harness is misconfigured,
    /// and reporting that distinction is the whole point of the NOT_TESTABLE value.
    static string Option(string[] args, string name)
    {
        foreach (string a in args)
            if (a.StartsWith(name, StringComparison.OrdinalIgnoreCase))
                return a.Substring(name.Length);
        return "";
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

    /// A boundary case that reports whether the path was even reached.
    ///
    /// The distinction this protects: "the OS denied this" and "I never got to
    /// ask" are different findings, and only the first says anything about an
    /// ACL. A test that cannot reach its target must say so, because a probe that
    /// reports denial for an unreachable path would let a misconfigured harness
    /// masquerade as a working security boundary.
    static string Reach(string path)
    {
        if (path == null || path.Length == 0) return "NOT_TESTABLE";
        try
        {
            if (Directory.Exists(path)) return "REACHABLE";
            if (File.Exists(path)) return "REACHABLE";
            return "NOT_REACHABLE";
        }
        catch (Exception ex)
        {
            // An exception while merely *asking* whether the path exists is itself
            // evidence the path is not usable, not a pass and not a denial.
            return "NOT_REACHABLE:" + ex.GetType().Name;
        }
    }

    static string RunGuarded(string label, string target, Action action)
    {
        string reach = Reach(target);
        if (reach != "REACHABLE")
        {
            Console.WriteLine("probe=" + label + " result=NOT_TESTABLE reason=" +
                (reach == "NOT_TESTABLE" ? "no_path_supplied" : "path_not_reached(" + reach + ")"));
            return "NOT_TESTABLE";
        }
        return Run(label, action);
    }

    static void Enumerate(string label, string dir)
    {
        string reach = Reach(dir);
        if (reach != "REACHABLE")
        {
            Console.WriteLine("probe=" + label + " result=" +
                (reach == "NOT_TESTABLE" ? "NOT_TESTABLE" : "PATH_ERROR") +
                " reason=" + (reach == "NOT_TESTABLE" ? "no_path_supplied" : "path_not_reached"));
            return;
        }
        try
        {
            string[] entries = Directory.GetFileSystemEntries(dir);
            Console.WriteLine("probe=" + label + " result=OS_ALLOWED entries=" + entries.Length);
        }
        catch (UnauthorizedAccessException)
        {
            Console.WriteLine("probe=" + label + " result=OS_DENIED winerror=5");
        }
        catch (Exception ex)
        {
            Console.WriteLine("probe=" + label + " result=ERROR " + ex.GetType().Name);
        }
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

        // Positional paths, unchanged from the M016 interface so a previously
        // captured run remains comparable:
        //   [0] scratch      a staging directory the subject should not be able to write
        //   [1] staged       a staged runtime, or "" when none is staged
        //   [2] protectedDir an M005 protected directory, or ""
        //   [3] workspace    the intentionally writable experimentation area
        //
        // Named options follow, added for the M015 boundary test. Each carries an
        // explicit directory to traverse and enumerate, so the read-only halves of
        // the boundary (which a scratch argument alone cannot express) are testable:
        //   --traverse=<dir> --enumerate-runtime=<dir> --enumerate-model=<dir>
        //   --enumerate-config=<dir> --read-file=<path> --acl-target=<path>
        // Windows PowerShell DROPS an empty-string argument: passing `"" "d"` delivers
        // only two arguments, which silently shifts every later positional value.
        // A named placeholder keeps the positions aligned, and "-" is normalised to
        // "not supplied" rather than being treated as the path "-".
        string scratch = Arg(args, 0);
        string staged = Arg(args, 1);
        string protectedDir = Arg(args, 2);
        string workspace = Arg(args, 3);

        string traverseDir = Option(args, "--traverse=");
        string enumRuntime = Option(args, "--enumerate-runtime=");
        string enumModel = Option(args, "--enumerate-model=");
        string enumConfig = Option(args, "--enumerate-config=");
        string readFile = Option(args, "--read-file=");
        string aclTarget = Option(args, "--acl-target=");

        int allowed = 0;
        Action bump = delegate { allowed++; };

        // --- read-only halves of the boundary, first -----------------------
        RunGuarded("traverse_directory", traverseDir, () => {
                Directory.GetFileSystemEntries(traverseDir); bump();
            });
        // No implicit fallback. Deriving `..\runtime` from the scratch argument looked
        // convenient but meant a run with a bogus scratch path still "tested" the
        // real staging directory -- so a broken harness could report OS_ALLOWED
        // for a case it never actually targeted. An unsupplied option is reported
        // as unsupplied.
        Enumerate("enumerate_runtime", enumRuntime);
        Enumerate("enumerate_model", enumModel);
        Enumerate("enumerate_config", enumConfig);
        RunGuarded("read_disposable_file", readFile, () => {
                File.ReadAllText(readFile); bump();
            });
        RunGuarded("modify_acl", aclTarget, () => {
                File.SetAttributes(aclTarget, FileAttributes.ReadOnly); bump();
            });

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
            RunGuarded("create_file_in_staging_scratch", scratch,
                () => { Touch(Path.Combine(scratch, "p.txt")); bump(); });

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
            RunGuarded("create_child_directory", scratch, () => {
                Directory.CreateDirectory(Path.Combine(scratch, "childdir")); bump();
            });
            RunGuarded("delete_child_directory", scratch, () => {
                string d = Path.Combine(scratch, "childdir");
                if (Directory.Exists(d)) Directory.Delete(d); bump();
            });
            if (protectedDir.Length > 0)
            {
                // Reaches for an existing file rather than naming one that may not
                // exist: a SetAttributes on a missing path returns winerror 2, which
                // is a path error, and reporting that as a denial would be a lie.
                RunGuarded("modify_acl_on_protected", protectedDir, () => {
                    string[] entries = Directory.GetFileSystemEntries(protectedDir);
                    if (entries.Length == 0) throw new DirectoryNotFoundException("empty");
                    File.SetAttributes(entries[0], FileAttributes.ReadOnly);
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