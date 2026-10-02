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
 *
 * v2 measurement correction. Four Windows capabilities that this probe previously
 * collapsed into two operations are now measured separately, because the collapse
 * produced evidence that named a capability it had not tested:
 *
 *   FILE_TRAVERSE       `traverse_to_leaf`        CreateFileW(leaf, FILE_READ_ATTRIBUTES)
 *   FILE_LIST_DIRECTORY `enumerate_*`             Enumerate(dir)
 *   FILE_READ_ATTRIBUTES `read_metadata`          GetFileAttributesExW(path)
 *   FILE_READ_DATA      `read_file_bytes`         FileStream.Read()
 *
 * The old `traverse_directory` operation called Directory.GetFileSystemEntries,
 * which requests FILE_LIST_DIRECTORY on the directory itself and never descends
 * into a child. It was a listing test wearing a traversal label. The old read
 * operation called FileInfo.Length before File.OpenRead inside a single lambda,
 * so a stat failure was reported as a read denial without any read being
 * attempted. Both are fixed here; see Traverse, Enumerate, Metadata, ReadBytes.
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

    // --- native access-check primitives ---------------------------------------
    //
    // The M015 investigation showed that Directory.GetFileSystemEntries cannot
    // answer "can this account traverse into the directory": that call requests
    // FILE_LIST_DIRECTORY on the directory itself, so it measures enumeration and
    // nothing else. Naming that operation `traverse_directory` made the evidence
    // claim a capability it never tested.
    //
    // Traversal is a property of PATH RESOLUTION, not of any single handle. The
    // Windows way to test it is to open a target that lives BENEATH the directory
    // and succeed. The kernel must walk the path component by component, and for
    // each intermediate directory it checks FILE_TRAVERSE (0x20) before descending.
    // CreateFileW on the leaf therefore fails with ERROR_ACCESS_DENIED when an
    // ancestor lacks traverse, and succeeds when every ancestor has it.
    //
    // The leaf's own access is a different question, so it is requested explicitly
    // and reported separately: FILE_READ_DATA (0x01) for content, and
    // FILE_READ_ATTRIBUTES (0x80) alone for a metadata-only probe. A traversal test
    // that requests read on the leaf cannot distinguish "cannot descend" from
    // "descended but cannot read", so the two are reported as separate numbers.

    const uint FILE_READ_DATA = 0x0001;
    // FILE_LIST_DIRECTORY shares bit 0x01 with FILE_READ_DATA; the two names
    // describe the same bit on different object types. Declared separately so the
    // emitted evidence names the directory capability rather than reusing the
    // file-side constant.
    const uint FILE_LIST_DIRECTORY = 0x0001;
    const uint FILE_TRAVERSE = 0x0020;
    const uint FILE_READ_ATTRIBUTES = 0x0080;
    const uint GENERIC_READ = 0x80000000;

    const uint ERROR_FILE_NOT_FOUND = 2;
    const uint ERROR_PATH_NOT_FOUND = 3;
    const uint ERROR_ACCESS_DENIED = 5;
    const uint ERROR_SHARING_VIOLATION = 32;
    const uint ERROR_INVALID_NAME = 123;

    const uint OPEN_EXISTING = 3;
    const uint FILE_ATTRIBUTE_NORMAL = 0x00000080;
    const uint FILE_FLAG_BACKUP_SEMANTICS = 0x02000000;

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern IntPtr CreateFileW(string name, uint access, uint share,
        IntPtr security, uint creation, uint flags, IntPtr templateFile);

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern uint GetLastError();

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern bool GetFileAttributesExW(string name, int level, IntPtr data);

    const int GetFileExInfoStandard = 0;

    [StructLayout(LayoutKind.Sequential)]
    struct WIN32_FILE_ATTRIBUTE_DATA
    {
        public uint FileAttributes;
        public System.Runtime.InteropServices.ComTypes.FILETIME CreationTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastAccessTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWriteTime;
        public uint FileSizeHigh;
        public uint FileSizeLow;
    }

    /// Open a path with an EXACT access mask and report the raw Win32 outcome.
    /// No managed wrapper sits between the call and the error code, so the result
    /// is the kernel's own verdict rather than a re-derived approximation.
    ///
    /// The error code is classified rather than flattened: ERROR_ACCESS_DENIED is
    /// a security verdict, while ERROR_FILE_NOT_FOUND and ERROR_PATH_NOT_FOUND
    /// mean the target is not there. Returning OS_DENIED for all three would let
    /// a typo in a path masquerade as a working security control.
    static string TryNativeOpen(string path, uint access, out uint winError)
    {
        winError = 0;
        IntPtr handle = CreateFileW(path, access,
            0x00000001 | 0x00000002 | 0x00000004, // FILE_SHARE_READ|WRITE|DELETE
            IntPtr.Zero, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, IntPtr.Zero);
        if (handle == new IntPtr(-1)) // INVALID_HANDLE_VALUE, spelled out for this toolchain
        {
            winError = GetLastError();
            if (winError == ERROR_FILE_NOT_FOUND) return "PATH_ERROR";
            if (winError == ERROR_PATH_NOT_FOUND) return "PATH_ERROR";
            if (winError == ERROR_INVALID_NAME) return "PATH_ERROR";
            if (winError == ERROR_SHARING_VIOLATION) return "IO_ERROR";
            if (winError == ERROR_ACCESS_DENIED) return "OS_DENIED";
            return "OS_ERROR";
        }
        CloseHandle(handle);
        return "OS_ALLOWED";
    }

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

    /// Normalise a path to a comparable absolute form, or return null.
    ///
    /// Path.GetFullPath is not total. It throws ArgumentException for an extended
    /// `\\?\` prefix and NotSupportedException for a device `\\.\` prefix, and it
    /// resolves a relative path against the process working directory -- which
    /// differs between an operator shell and a child process, so a relative path
    /// would be compared against two different bases. Both prefixes denote the
    /// same object as the plain form, so they are stripped before normalising.
    ///
    /// Null means "cannot be compared", and callers must treat that as unknown
    /// rather than as false-because-outside.
    static string TryNormalize(string path)
    {
        if (path == null) return null;
        string p = path.Trim();
        if (p.Length == 0) return null;
        if (p == "-") return null;

        // \\?\UNC\server\share  ->  \\server\share
        if (p.StartsWith(@"\\?\UNC\", StringComparison.OrdinalIgnoreCase))
        {
            p = @"\\" + p.Substring(8);
        }
        else if (p.StartsWith(@"\\?\", StringComparison.OrdinalIgnoreCase))
        {
            p = p.Substring(4);
        }
        // \\.\C:\dir is the device namespace spelling of the same volume, so it
        // strips to the drive-letter form and compares correctly. Returning null
        // here instead would have reported the leaf as OUTSIDE staging when it is
        // inside -- a false negative that reads exactly like the harness
        // misconfiguration this field exists to surface.
        else if (p.StartsWith(@"\\.\", StringComparison.OrdinalIgnoreCase))
        {
            string rest = p.Substring(4);
            // Only a drive-qualified remainder is a filesystem path. A real
            // device name such as \\.\PhysicalDrive0 is not, and is left
            // unnormalised rather than mangled into something that looks valid.
            if (rest.Length >= 2 && rest[1] == ':' &&
                (rest[0] >= 'A' && rest[0] <= 'Z' || rest[0] >= 'a' && rest[0] <= 'z'))
            {
                p = rest;
            }
            else
            {
                return null;
            }
        }

        try
        {
            string full = Path.GetFullPath(p);
            if (full.Length > 3) full = full.TrimEnd('\\');
            return full;
        }
        catch (ArgumentException)
        {
            return null;
        }
        catch (NotSupportedException)
        {
            return null;
        }
        catch (PathTooLongException)
        {
            return null;
        }
        catch (IOException)
        {
            return null;
        }
    }

    /// Whether a path lies inside the staging directory.
    ///
    /// Reported rather than enforced, because the interesting fact is when a
    /// boundary test was aimed somewhere else entirely. Silently rewriting the
    /// target would hide the misconfiguration; refusing it outright would be a
    /// behaviour change beyond this probe's remit.
    ///
    /// This is a pure reporting helper, so it must never throw. It previously
    /// called Path.GetFullPath unguarded, and an extended or device path prefix
    /// propagated out of it -- taking down the run at the point where the read
    /// result was about to be reported, so the operator lost every measurement
    /// after this line. A helper whose job is to describe the harness cannot be
    /// allowed to end the harness.
    static bool IsUnder(string path, string root)
    {
        string a = TryNormalize(path);
        string b = TryNormalize(root);
        if (a == null || b == null) return false;
        if (a.Length <= b.Length) return false;
        if (!a.StartsWith(b, StringComparison.OrdinalIgnoreCase)) return false;
        // Guard the index: b may be a drive root such as "C:\" already trimmed
        // to "C:", and a[len] would still be in range, but an empty b is possible
        // if GetFullPath ever reduced to one.
        return a.Length > b.Length && a[b.Length] == '\\';
    }

    /// Whether an exception means the OS refused access.
    ///
    /// .NET surfaces a denial as `UnauthorizedAccessException` from the
    /// convenience helpers but as a plain `IOException` carrying ERROR_ACCESS_DENIED
    /// from `Directory.GetFiles` and friends. Catching only the former is what let
    /// a denied directory enumeration become an unhandled crash and take the rest
    /// of the report with it.
    static bool IsAccessDenied(Exception ex)
    {
        // The whole chain, because the denial is routinely on an inner exception.
        // A masked `HResult & 0xFFFF` comparison only ever looked at the outer
        // exception, which is how a real denial was once read as PATH_ERROR.
        for (Exception e = ex; e != null; e = e.InnerException)
        {
            uint code;
            if (TryWin32Error(e.HResult, out code) && code == ERROR_ACCESS_DENIED)
                return true;
        }
        return false;
    }

    /// The classification of one attempted operation, plus the evidence for it.
    ///
    /// `winError` is only meaningful when `winErrorEstablished` is true. A false
    /// flag means no genuine Win32 error could be identified, and the caller must
    /// not print the number as though it were one -- that is the defect this type
    /// exists to prevent.
    class Verdict
    {
        public string Result;
        public uint WinError;
        public bool WinErrorEstablished;
        public string OuterType;
        public int OuterHResult;
        public string InnerType;
        public int InnerHResult;
        public int ChainDepth;
    }

    const int FACILITY_WIN32 = 0x0;      // HRESULT_FROM_WIN32 high word
    const int CLR_HRESULT_MASK = 0x8013; // COR_* and other runtime-raised codes

    /// Identify a Win32 error from an HRESULT, without inventing one.
    ///
    /// Two rules, both learned from a real subject run:
    ///
    /// 1. Only an HRESULT whose high word is 0 is a HRESULT_FROM_WIN32 value. The
    ///    earlier code masked unconditionally (`HResult & 0xFFFF`) and so turned
    ///    0x80131620 -- the runtime's own IOException code -- into "5664", a
    ///    number shaped like a Win32 error that has no Win32 meaning. The probe
    ///    then reported PATH_ERROR and the denial vanished.
    ///
    /// 2. A genuine 0x80070005 is ERROR_ACCESS_DENIED. Verified to survive.
    ///
    /// Returns false when the code cannot be established as Win32-backed, so the
    /// caller classifies UNCLASSIFIED rather than inventing a number.
    static bool TryWin32Error(int hresult, out uint winError)
    {
        // Assigned on every path before any `return`: PowerShell 5.1's C# compiler
        // requires an `out` parameter be definitely assigned on every path.
        winError = 0;
        if (hresult >= 0) return false;                 // a .NET success code
        if (hresult == unchecked((int)0x80004001)) return false;  // E_NOTIMPL
        if (hresult == unchecked((int)0x80131509)) return false;  // MethodInvocation
        // HRESULT_FROM_WIN32(code) == 0x80070000 | code: severity ERROR, facility WIN32
        // (7), so a genuine Win32-backed HRESULT has exactly that high word. This
        // is what distinguishes 0x80070005 (ERROR_ACCESS_DENIED, real) from
        // 0x80131620 (the runtime's own IOException code, not real) -- and the
        // latter is what the previous unconditional mask turned into "5664".
        if ((uint)(hresult & 0xFFFF0000) == 0x80070000)
        {
            winError = (uint)(hresult & 0xFFFF);
            return true;
        }
        return false;
    }

    /// Walk the exception chain and classify the operation.
    ///
    /// A wrapped denial is the common case: `Directory.Delete(path, false)` on a
    /// denied directory surfaces an outer exception whose inner exception carries
    /// ERROR_ACCESS_DENIED. Classifying only the outer type loses the verdict, so
    /// the whole chain is searched and the FIRST genuine Win32 error found decides
    /// the result. Outer and inner information are always recorded so a reader can
    /// see which level produced the verdict.
    static Verdict Classify(Exception ex)
    {
        var v = new Verdict();
        v.OuterType = ex.GetType().FullName;
        v.OuterHResult = ex.HResult;
        v.ChainDepth = 1;

        // Collect the chain first, so the outer/inner pair is well defined even
        // when the verdict comes from deeper down.
        var chain = new System.Collections.Generic.List<Exception>();
        for (Exception e = ex; e != null; e = e.InnerException)
        {
            chain.Add(e);
            v.ChainDepth++;
        }
        if (chain.Count > 1)
        {
            v.InnerType = chain[1].GetType().FullName;
            v.InnerHResult = chain[1].HResult;
        }

        // First genuine Win32 error anywhere in the chain wins. Scanning outward-in
        // means a specific cause beats a generic wrapper.
        foreach (Exception e in chain)
        {
            uint code;
            if (TryWin32Error(e.HResult, out code))
            {
                v.WinError = code;
                v.WinErrorEstablished = true;
                v.Result = code == ERROR_ACCESS_DENIED ? "OS_DENIED"
                        : (code == ERROR_FILE_NOT_FOUND || code == ERROR_PATH_NOT_FOUND
                           || code == ERROR_INVALID_NAME) ? "PATH_ERROR"
                        : code == ERROR_SHARING_VIOLATION ? "IO_ERROR"
                        : "OS_ERROR";
                return v;
            }
        }

        // No Win32 error anywhere in the chain. Say so rather than fabricating one.
        v.Result = "UNCLASSIFIED";
        return v;
    }

    static string WinErrorField(Verdict v)
    {
        return v.WinErrorEstablished
            ? " winerror=" + v.WinError
            : " winerror=UNCLASSIFIED hresult=0x" + v.OuterHResult.ToString("x8");
    }

    static string ChainField(Verdict v)
    {
        string s = " outer=" + v.OuterType + "/0x" + v.OuterHResult.ToString("x8");
        if (v.InnerType != null)
            s += " inner=" + v.InnerType + "/0x" + v.InnerHResult.ToString("x8");
        s += " depth=" + v.ChainDepth;
        return s;
    }

    static string Run(string label, Action action)
    {
        try
        {
            action();
            Console.WriteLine("probe=" + label + " result=OS_ALLOWED");
            return "OS_ALLOWED";
        }
        catch (Exception ex)
        {
            Verdict v = Classify(ex);
            Console.WriteLine("probe=" + label + " result=" + v.Result +
                WinErrorField(v) + ChainField(v));
            return v.Result;
        }
    }

    /// Delete a path, but only claim a verdict when there was something to delete.
    ///
    /// `File.Delete` on a missing path is a successful no-op, so reporting
    /// OS_ALLOWED for it would assert a delete permission that was never
    /// exercised. A subject run hit exactly this: the preceding create was denied,
    /// so the target never existed, and the no-op delete read as OS_ALLOWED.
    /// Deleting nothing is NOT_TESTABLE, not a pass.
    static string RunDelete(string label, string path, bool expectDirectory)
    {
        bool present = expectDirectory ? Directory.Exists(path) : File.Exists(path);
        Console.WriteLine("probe=" + label + " target=" + path);
        Console.WriteLine("probe=" + label + " target_preexisted=" + present);
        // target_preexisted is repeated on the RESULT line as well as on its own line,
        // because a consumer parsing one finding per operation only sees the
        // result line. Without it here a reader cannot tell a real delete from a
        // no-op after the fact.
        if (!present)
        {
            Console.WriteLine("probe=" + label +
                " result=NOT_TESTABLE reason=target_not_present target_preexisted=false");
            return "NOT_TESTABLE";
        }
        try
        {
            if (expectDirectory) Directory.Delete(path, true);
            else File.Delete(path);
        }
        catch (Exception ex)
        {
            Verdict v = Classify(ex);
            Console.WriteLine("probe=" + label + " result=" + v.Result +
                WinErrorField(v) + " target_preexisted=true" + ChainField(v));
            return v.Result;
        }
        Console.WriteLine("probe=" + label + " result=OS_ALLOWED target_preexisted=true");
        return "OS_ALLOWED";
    }

    /// A token identifying this invocation, used to name the files the probe owns.
    ///
    /// Ownership by creation, not by filename prefix: the cleanup sweep deletes
    /// exactly the names this function generated, so a pre-existing staged runtime
    /// or an artefact from another run cannot be caught by it. The process id
    /// plus the start time makes the token unique per invocation while remaining
    /// reproducible enough to trace back to the run that produced a file.
    static string RunToken()
    {
        var me = System.Diagnostics.Process.GetCurrentProcess();
        return me.Id + "x" + me.StartTime.Ticks.ToString("X");
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

    /// Directory enumeration. This measures FILE_LIST_DIRECTORY and is named for
    /// exactly that. It is NOT a traversal test: GetFileSystemEntries requests
    /// FILE_LIST_DIRECTORY on `dir` itself and never descends into a child path.
    ///
    /// NOTE: the Reach() preflight below has the same defect that was just
    /// corrected in Traverse -- Exists() cannot distinguish "inaccessible" from
    /// "absent". It is left in place because this correction is scoped to the
    /// traversal measurement, and the observed subject evidence shows this
    /// operation does reach its call (enumerate_runtime reported OS_DENIED
    /// winerror=5, not NOT_TESTABLE). Recorded here so the limitation is
    /// explicit rather than rediscovered later.
    static void Enumerate(string label, string dir)
    {
        string reach = Reach(dir);
        if (reach != "REACHABLE")
        {
            Console.WriteLine("probe=" + label + " result=" +
                (reach == "NOT_TESTABLE" ? "NOT_TESTABLE" : "PATH_ERROR") +
                " capability=FILE_LIST_DIRECTORY reason=" +
                (reach == "NOT_TESTABLE" ? "no_path_supplied" : "path_not_reached"));
            return;
        }
        try
        {
            string[] entries = Directory.GetFileSystemEntries(dir);
            Console.WriteLine("probe=" + label + " result=OS_ALLOWED capability=FILE_LIST_DIRECTORY entries=" +
                entries.Length);
        }
        catch (UnauthorizedAccessException)
        {
            Console.WriteLine("probe=" + label + " result=OS_DENIED capability=FILE_LIST_DIRECTORY winerror=5");
        }
        catch (Exception ex)
        {
            Console.WriteLine("probe=" + label + " result=ERROR capability=FILE_LIST_DIRECTORY " + ex.GetType().Name);
        }
    }

    /// Path traversal. Distinct from Enumerate by construction.
    ///
    /// The directory under test is NOT opened. Instead a target BENEATH it is
    /// opened, because traversal is enforced by the kernel while it walks the path
    /// toward that target. Three measurements are reported because a single one
    /// cannot attribute a denial:
    ///
    ///   traverse_to_leaf  CreateFileW(leaf, FILE_READ_ATTRIBUTES)
    ///       Minimal access. Succeeds only if every ancestor is traversable, so this
    ///       is the traversal verdict with the target's own rights made trivial.
    ///   traverse_leaf_read  CreateFileW(leaf, FILE_READ_DATA)
    ///       The same walk plus real content rights on the leaf. A denial here when
    ///       traverse_to_leaf succeeded localises the failure to the LEAF, not a parent.
    ///   traverse_ancestor_list  CreateFileW(dir, FILE_LIST_DIRECTORY)
    ///       Whether the directory itself can be enumerated, which is a different
    ///       right and must not be inferred from either of the above.
    ///
    /// Nothing here calls Directory.GetFileSystemEntries, so a method named
    /// traverse can no longer be reporting an enumeration result.
    static void Traverse(string label, string dir, string leaf)
    {
        // NO Reach() PREFLIGHT. This is the correction.
        //
        // Reach() asks Directory.Exists / File.Exists, and under a restricted
        // account those return FALSE for a path that exists but cannot be
        // traversed. So a preflight on the DIRECTORY could report NOT_TESTABLE or
        // PATH_ERROR and return before the capability under test was ever
        // attempted -- publishing an untested capability as if it had been
        // measured. The first two subject runs of the corrected experiment did
        // exactly that: `traverse result=NOT_TESTABLE reason=no_path_supplied`
        // while the directory was present and its own ACL was readable.
        //
        // The leaf is the capability probe, and the kernel's own answer to the
        // native open is the evidence. The error code distinguishes a denial
        // (ERROR_ACCESS_DENIED) from an absent target, so no existence check is
        // needed to tell those apart -- the open itself does.
        if (string.IsNullOrEmpty(leaf))
        {
            // Still an honest NOT_TESTABLE: a traversal test with no target has
            // nothing to traverse to. It is reported as untested rather than
            // silently degraded into a directory open, which would reintroduce
            // the exact conflation this method exists to remove.
            Console.WriteLine("probe=" + label +
                " result=NOT_TESTABLE capability=FILE_TRAVERSE reason=no_traversal_target_supplied");
            return;
        }

        // Field order matters: `result=` comes immediately after the operation so
        // the harness parser matches the line, and the describing fields follow in
        // `detail`. Emitting them first would push every line into `unparsed` and
        // the evidence would silently vanish from the report.
        uint err;
        string toLeaf = TryNativeOpen(leaf, FILE_READ_ATTRIBUTES, out err);
        Console.WriteLine("probe=" + label + "_to_leaf result=" + toLeaf + WinErr(err) +
            " capability=FILE_TRAVERSE access=FILE_READ_ATTRIBUTES target=" + leaf);

        uint errRead;
        string leafRead = TryNativeOpen(leaf, FILE_READ_DATA, out errRead);
        Console.WriteLine("probe=" + label + "_leaf_read result=" + leafRead + WinErr(errRead) +
            " capability=FILE_TRAVERSE access=FILE_READ_DATA target=" + leaf);

        // The ancestor listing is a DIFFERENT capability and is reported as one.
        // It is attempted whenever a directory was supplied, with no Reach()
        // preflight for the same reason. An absent directory here does not
        // invalidate the traverse results above, so this runs last and cannot
        // suppress them.
        if (string.IsNullOrEmpty(dir))
        {
            Console.WriteLine("probe=" + label + "_ancestor_list result=NOT_TESTABLE" +
                " capability=FILE_LIST_DIRECTORY reason=no_path_supplied");
            return;
        }
        uint errList;
        string ancList = TryNativeOpen(dir, FILE_LIST_DIRECTORY, out errList);
        Console.WriteLine("probe=" + label + "_ancestor_list result=" + ancList + WinErr(errList) +
            " capability=FILE_LIST_DIRECTORY target=" + dir);
    }

    static string WinErr(uint err)
    {
        return err == 0 ? "" : " winerror=" + err;
    }

    /// Actual content read. Opens the file for reading, calls Read(), and reports
    /// the number of bytes the Read call actually returned. The count is never
    /// taken from a length or stat call, so `bytes_observed` cannot describe a file
    /// whose content was never fetched.
    static void ReadBytes(string label, string path, Action onAllowed)
    {
        // NOTE: the caller's Reach() gate has the same Exists() defect corrected
        // in Traverse. Left as-is because this correction is scoped to traversal.
        FileStream stream = null;
        try
        {
            stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
            byte[] buffer = new byte[64];
            int observed = stream.Read(buffer, 0, buffer.Length);
            Console.WriteLine("probe=" + label + " result=OS_ALLOWED capability=FILE_READ_DATA" +
                " bytes_observed=" + observed);
            if (onAllowed != null)
            {
                onAllowed();
            }
        }
        catch (UnauthorizedAccessException)
        {
            Console.WriteLine("probe=" + label + " result=OS_DENIED capability=FILE_READ_DATA winerror=5");
        }
        catch (FileNotFoundException)
        {
            Console.WriteLine("probe=" + label + " result=PATH_ERROR capability=FILE_READ_DATA reason=file_not_found");
        }
        catch (DirectoryNotFoundException)
        {
            Console.WriteLine("probe=" + label + " result=PATH_ERROR capability=FILE_READ_DATA reason=directory_not_found");
        }
        catch (IOException ex)
        {
            // Reported distinctly so a sharing violation is never read as an access
            // denial. The code goes through TryWin32Error rather than a mask, so
            // a runtime-raised IOException cannot present itself as a Win32 error.
            Verdict rv = Classify(ex);
            Console.WriteLine("probe=" + label + " result=" + rv.Result +
                " capability=FILE_READ_DATA" + WinErrorField(rv) + ChainField(rv));
        }
        finally
        {
            if (stream != null)
            {
                stream.Dispose();
            }
        }
    }

    /// Metadata access, reported on its own so it can never be mistaken for a read.
    /// GetFileAttributesExW requests no content access at all, so a denial here is a
    /// metadata denial and is labelled as one.
    static void Metadata(string label, string path)
    {
        // NOTE: the caller's Reach() gate has the same Exists() defect corrected
        // in Traverse. Left as-is because this correction is scoped to traversal.
        IntPtr buffer = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(WIN32_FILE_ATTRIBUTE_DATA)));
        try
        {
            if (!GetFileAttributesExW(path, GetFileExInfoStandard, buffer))
            {
                // Classify by error code. Labelling every failure OS_DENIED made a
                // nonexistent path report `OS_DENIED winerror=3`, which contradicts
                // itself and would let a misconfigured target look like a security
                // control that fired. Only ERROR_ACCESS_DENIED is a denial.
                uint err = GetLastError();
                string verdict;
                if (err == ERROR_ACCESS_DENIED) verdict = "OS_DENIED";
                else if (err == ERROR_FILE_NOT_FOUND || err == ERROR_PATH_NOT_FOUND
                         || err == ERROR_INVALID_NAME) verdict = "PATH_ERROR";
                else if (err == ERROR_SHARING_VIOLATION) verdict = "IO_ERROR";
                else verdict = "OS_ERROR";
                Console.WriteLine("probe=" + label + " result=" + verdict +
                    " capability=FILE_READ_ATTRIBUTES" + WinErr(err));
                return;
            }
            var data = (WIN32_FILE_ATTRIBUTE_DATA)Marshal.PtrToStructure(
                buffer, typeof(WIN32_FILE_ATTRIBUTE_DATA));
            long size = ((long)data.FileSizeHigh << 32) | data.FileSizeLow;
            Console.WriteLine("probe=" + label + " result=OS_ALLOWED capability=FILE_READ_ATTRIBUTES" +
                " metadata_bytes_reported=" + size);
        }
        finally
        {
            Marshal.FreeHGlobal(buffer);
        }
    }

    static int Main(string[] args)
    {
        Console.WriteLine("schema=probe/v2");
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
        //   --traverse=<dir> --traverse-leaf=<path> --enumerate-runtime=<dir>
        //   --enumerate-model=<dir> --enumerate-config=<dir>
        //   --read-file=<path> --acl-target=<path>
        // Windows PowerShell DROPS an empty-string argument: passing `"" "d"` delivers
        // only two arguments, which silently shifts every later positional value.
        // A named placeholder keeps the positions aligned, and "-" is normalised to
        // "not supplied" rather than being treated as the path "-".
        string scratch = Arg(args, 0);
        string staged = Arg(args, 1);
        string protectedDir = Arg(args, 2);
        string workspace = Arg(args, 3);
        string stagedTree = Option(args, "--staging-root=");

        // The staging root drives the destructive-copy location and the
        // read-inside-staging report. It falls back to the staged file's own
        // directory only when no explicit root is given, and that substitution is
        // announced rather than made silently.
        if (stagedTree.Length == 0 && staged.Length > 0)
        {
            string guess = Path.GetDirectoryName(staged);
            if (guess != null && Directory.Exists(guess))
            {
                stagedTree = guess;
                Console.WriteLine("staging_root_source=DERIVED_FROM_STAGED_FILE");
            }
        }
        Console.WriteLine("staging_root=" + (stagedTree.Length > 0 ? stagedTree : "<none>"));

        string traverseDir = Option(args, "--traverse=");
        // The leaf the traversal test walks to. Traversal is a property of
        // descending to a target, so the leaf is a required input to that
        // measurement rather than an optional extra.
        string traverseLeaf = Option(args, "--traverse-leaf=");
        string enumRuntime = Option(args, "--enumerate-runtime=");
        string enumModel = Option(args, "--enumerate-model=");
        string enumConfig = Option(args, "--enumerate-config=");
        string readFile = Option(args, "--read-file=");
        string aclTarget = Option(args, "--acl-target=");
        string deleteFixture = Option(args, "--delete-fixture=");

        int allowed = 0;
        Action bump = delegate { allowed++; };

        // --- read-only halves of the boundary, first -----------------------
        //
        // Traversal, enumeration, metadata, and content read are four DIFFERENT
        // Windows capabilities and are now four differently named operations. They
        // were previously two operations with three capabilities collapsed into
        // them, which is how a `traverse_directory` result came to be a listing
        // result and a "read denied" came to be a stat denial.
        Traverse("traverse", traverseDir, traverseLeaf);
        // No implicit fallback. Deriving `..\runtime` from the scratch argument looked
        // convenient but meant a run with a bogus scratch path still "tested" the
        // real staging directory -- so a broken harness could report OS_ALLOWED
        // for a case it never actually targeted. An unsupplied option is reported
        // as unsupplied.
        Enumerate("enumerate_runtime", enumRuntime);
        Enumerate("enumerate_model", enumModel);
        Enumerate("enumerate_config", enumConfig);
        // The read test. The exact target is echoed before the attempt, and the byte count
        // after, so a reader can confirm which object produced the result.
        //
        // The staging root is echoed too, because a read of a file OUTSIDE it is a
        // true observation of that file and says nothing about the boundary. The
        // first subject run read a file in the writable baby_workspace and reported
        // OS_ALLOWED directly beside thirteen staging denials, with nothing in the
        // output to distinguish the two.
        Console.WriteLine("read_file_target=" + (readFile.Length > 0 ? readFile : "<none>"));
        Console.WriteLine("read_file_in_staging=" +
                (IsUnder(readFile, stagedTree) || IsUnder(readFile, staged)));

        // The read comes FIRST and is attempted on its own. The previous code
        // called FileInfo.Length inside the read lambda, so a stat failure aborted
        // the read and was reported as `read_disposable_file result=OS_DENIED` --
        // a read denial that had never attempted a read. Reading first means the
        // content result exists regardless of what metadata later reports.
        string readReach = Reach(readFile);
        if (readReach != "REACHABLE")
        {
            Console.WriteLine("probe=read_file_bytes result=" +
                (readReach == "NOT_TESTABLE" ? "NOT_TESTABLE" : "PATH_ERROR") +
                " capability=FILE_READ_DATA reason=" +
                (readReach == "NOT_TESTABLE" ? "no_path_supplied" : "path_not_reached"));
        }
        else
        {
            ReadBytes("read_file_bytes", readFile, delegate { bump(); });
        }

        // Metadata is measured after, and separately, so its outcome can never
        // stand in for the read above.
        Metadata("read_metadata", readFile);
        // The ACL-modification test. The ReadOnly attribute it sets MUST be restored
        // before this function returns: the attribute is not part of the ACL, so
        // icacls keeps reporting a clean boundary while every write to the file
        // fails for everyone, operator included. Leaving it set made five
        // operations return OS_DENIED for the operator, which looked like a
        // working boundary and was in fact a corrupted fixture.
        // Reported even when no path was supplied, so an absent option is visibly
        // "not tested" rather than silently missing from the output. A harness
        // reading only the operations it expects would otherwise conclude nothing
        // was attempted.
        FileAttributes original = FileAttributes.Normal;
        bool captured = false;
        RunGuarded("modify_acl", aclTarget, () => {
                original = File.GetAttributes(aclTarget);
                captured = true;
                File.SetAttributes(aclTarget, FileAttributes.ReadOnly);
                bump();
            });
            if (captured)
        {
            try { File.SetAttributes(aclTarget, original); }
            catch (Exception ex)
            {
                // A refusal here is CORRECT behaviour, not a harness fault: the
                // subject holds no FILE_WRITE_ATTRIBUTES under the M015 boundary, so
                // it cannot undo what the test asked it to do. That refusal is itself
                // evidence. The operator restores the attribute after the run; the
                // probe must never treat its own inability as something to escalate.
                bool denied = IsAccessDenied(ex);
                Console.WriteLine("probe=restore_acl_target_attributes result=" +
                    (denied ? "EXPECTED_OS_DENIED" : "ERROR") +
                    (denied
                        ? " note=subject lacks FILE_WRITE_ATTRIBUTES, which is the" +
                          " intended boundary; operator must restore after the run"
                        : " " + ex.GetType().Name));
            }
        }

        // The staged target's DOS/Windows attributes are recorded but NEVER changed.
        // The ReadOnly bit is not part of the ACL, so a fixture carrying it makes
        // every write fail for the operator too -- which reads as an ACL denial
        // while the ACL is in fact perfect. Recording it lets a reader tell a
        // permission problem from an attribute problem; correcting it is the
        // harness's job, because only the harness created the fixture.
        if (staged.Length > 0 && File.Exists(staged))
        {
            FileAttributes stagedAttrs = File.GetAttributes(staged);
            Console.WriteLine("staged_target_attributes=" + stagedAttrs);
            Console.WriteLine("staged_target_readonly=" +
                ((stagedAttrs & FileAttributes.ReadOnly) != 0));
        }

        // A private copy of the staged file for one destructive operation, made by the
        // probe itself -- it must be created rather than assumed, because asking
        // the subject to modify a copy that was never made turns "the file is
        // missing" into what looks like an ACL outcome.
        //
        // The copy goes in the STAGED FILE'S OWN DIRECTORY, not in the scratch
        // directory. This matters more than it looks. The destructive operations
        // exist to test the ACL that governs the staged runtime, and a copy
        // placed elsewhere inherits *that other directory's* ACL instead. With
        // scratch set to subject_runtime\config (R-only for the subject) the
        // copies inherited the config ACL, so modify/append/delete/rename/replace
        // came back OS_DENIED even for the operator who holds full control --
        // proving the target was wrong, and meaning a later OS_DENIED from
        // BABY_AI_TEST would have said nothing about the runtime subtree at all.
        //
        // No fallback: if the staged file has no resolvable directory the
        // operations are reported NOT_TESTABLE rather than quietly retried
        // somewhere else.
        // The copy is created by this probe, so it is owned by this probe: the copy
        // name carries an invocation-specific token, and only files this run
        // created are deleted. A staged runtime, a model, or any pre-existing
        // artefact in the tree is never touched.
        string runToken = RunToken();
        string ownedPrefix = "m016_copy_" + runToken + "_";

        // The destructive-copy directory is the staging root when supplied, and only
        // otherwise the staged file's own directory. Either way it must exist.
        string stagedDir = stagedTree.Length > 0 ? stagedTree
            : (staged.Length > 0 ? Path.GetDirectoryName(staged) : "");
        if (stagedDir == null || !Directory.Exists(stagedDir)) stagedDir = "";
        Console.WriteLine("run_token=" + runToken);
        Console.WriteLine("destructive_scratch_dir=" +
            (stagedDir.Length > 0 ? stagedDir : "UNRESOLVED"));
        Console.WriteLine("owned_artifact_prefix=" + ownedPrefix);

        Func<string, string> WithSuffix = suffix => {
            string copy = Path.Combine(stagedDir, ownedPrefix + suffix.TrimStart('.'));
            File.Copy(staged, copy, true);
            // File.Copy propagates the source's DOS attributes, so a ReadOnly
            // source yields ReadOnly copies -- and every write to those copies
            // then fails for the operator as well, which looks exactly like a
            // working ACL boundary. The copy is created by this probe, so the
            // probe may normalise it. The staged source is left untouched.
            FileAttributes copyAttrs = File.GetAttributes(copy);
            if ((copyAttrs & FileAttributes.ReadOnly) != 0)
            {
                File.SetAttributes(copy, copyAttrs & ~FileAttributes.ReadOnly);
                Console.WriteLine("probe=clear_copy_readonly result=OS_ALLOWED file=" + copy);
            }
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
                    // Both ends stay inside the staged file's own directory. A
                    // rename that crosses into another directory is a different
                    // test -- it would be governed by two ACLs, not the one the
                    // runtime subtree is supposed to enforce.
                    // Distinct names: reusing the source name hits winerror 183,
                    // which is a collision rather than a denial of rename.
                    string source = WithSuffix(".mvsrc");
                    string target = Path.Combine(stagedDir, ownedPrefix + "mvdst");
                    if (File.Exists(target)) File.Delete(target);
                    File.Move(source, target);
                    File.Delete(target);
                    bump();
                });
                Run("replace_staged_executable", () => {
                    // The replacement is created in the same directory, so the
                    // only thing under test is whether the subject can overwrite
                    // an existing file there.
                    string tmp = Path.Combine(stagedDir, ownedPrefix + "replacement");
                    Touch(tmp);
                    Replace(tmp, WithSuffix("rep"));
                    bump();
                });
                // Created beside the staged runtime for the same reason: the
                // runtime directory must be as read-only to the subject as the
                // file inside it.
                string child = Path.Combine(stagedDir, ownedPrefix + "child");
                Run("create_child_executable_beside_runtime", () => {
                    Touch(child); bump();
                });
            }
            else
            {
                Console.WriteLine("probe=staged_executable_operations result=NOT_TESTABLE " +
                    "reason=no_staged_executable_supplied");
            }
            // The child-directory pair. These use two DISTINCT, explicitly named
            // directories rather than one shared name, and the delete asserts the
            // directory is actually present first.
            //
            // An earlier version created "childdir" and then deleted "childdir"
            // behind `if (Directory.Exists(...))`. When creation was denied, the
            // delete silently did nothing -- and the probe reported OS_ALLOWED,
            // because the skip lived inside the lambda that counted success. That
            // turned "the subject could not create a directory" into "the subject
            // could delete a directory", which is the opposite of what happened.
            string childCreate = Path.Combine(scratch, "m016_child_create_dir");

            RunGuarded("create_child_directory", scratch, () => {
                Directory.CreateDirectory(childCreate); bump();
            });
            Console.WriteLine("create_child_directory_target=" + childCreate);

            // The delete target is a directory the OPERATOR created beforehand. The
            // probe never creates it, because a probe that creates the thing it is
            // about to delete cannot distinguish "the subject deleted it" from "the
            // subject created it, so of course it was there".
            //
            // Two earlier versions were wrong in opposite directions. One shared a
            // single name and guarded the delete behind Directory.Exists, so a
            // refused creation produced OS_ALLOWED for a delete that never happened.
            // The next one created the fixture itself through the same guarded path,
            // which meant the delete target could appear during the very run meant
            // to test deletion of a pre-existing object.
            string childDelete = deleteFixture;
            bool deletePreexisted = childDelete.Length > 0 && Directory.Exists(childDelete);
            Console.WriteLine("delete_child_directory_target=" +
                (childDelete.Length > 0 ? childDelete : "<none>"));
            Console.WriteLine("delete_child_directory_target_preexisted=" + deletePreexisted);

            if (childDelete.Length == 0)
            {
                Console.WriteLine("probe=delete_child_directory result=NOT_TESTABLE " +
                    "reason=no_delete_fixture_supplied; pass --delete-fixture=<dir>");
            }
else if (!deletePreexisted)
              {
                  // target_preexisted=false on the result line, so a consumer sees
                  // that nothing was deleted even before reading the reason.
                  Console.WriteLine("probe=delete_child_directory result=NOT_TESTABLE " +
                      "reason=delete_fixture_absent target_preexisted=false " +
                      "note=the operator must pre-create it");
              }
            else
            {
// RunDelete, not RunGuarded: the fixture is asserted present here
                  // and RunDelete re-asserts it immediately before deleting, so a
                  // missing target reports NOT_TESTABLE rather than a no-op
                  // OS_ALLOWED. Recursive, because the operator's fixture may hold a
                  // sentinel file.
                  RunDelete("delete_child_directory", childDelete, true); bump();
            }
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
            // RunDelete, not Run: if the write above was denied the file was never
            // created, and File.Delete on a missing path is a successful no-op. That
            // no-op read as OS_ALLOWED in a subject run, asserting a delete
            // permission that was never exercised.
            RunDelete("workspace_delete", wf, false); bump();
        }

        // Delete only what this invocation created. The names come from ownedPrefix,
        // which embeds this process's run token, so the sweep cannot match a
        // staged runtime, a model, an artefact from an earlier run, or anything an
        // operator placed in the tree.
        //
        // The enumeration itself is inside the try. When the running account
        // cannot list the scratch directory -- which is exactly the case for the
        // subject, whose deny ACE removes list permission -- Directory.GetFiles
        // throws. An unguarded call there crashed the probe after every result had
        // already been recorded, which is how the first subject run ended with an
        // unhandled exception instead of a report.
        //
        // A denial here is not a failure to clean up: the account could not have
        // created anything in a directory it cannot list. It is recorded as
        // CLEANUP_NOT_PERMITTED so an operator can finish the job afterwards, and
        // the probe reports which artefacts are left rather than claiming success.
        int cleanupFailed = 0;
        int cleanupRemoved = 0;
        string cleanupState = "NOT_REQUIRED";
        if (stagedDir.Length > 0)
        {
            string[] leftovers;
            try
            {
                leftovers = Directory.GetFiles(stagedDir, ownedPrefix + "*");
                cleanupState = "ENUMERATED";
            }
            catch (Exception ex)
            {
                leftovers = new string[0];
                bool denied = IsAccessDenied(ex);
                cleanupState = denied ? "CLEANUP_NOT_PERMITTED" : "CLEANUP_ENUMERATION_FAILED";
                Verdict cv = Classify(ex);
                Console.WriteLine("probe=cleanup_enumerate_owned_copies result=" +
                    (denied ? "OS_DENIED" : "ERROR") +
                    WinErrorField(cv) + ChainField(cv) +
                    (denied
                        ? " note=account cannot list the scratch directory; " +
                          "operator-side cleanup required"
                        : ""));
            }
            foreach (string leftover in leftovers)
            {
                if (Path.GetFileName(leftover).Contains(runToken))
                {
                    try
                    {
                        FileAttributes attrs = File.GetAttributes(leftover);
                        if ((attrs & FileAttributes.ReadOnly) != 0)
                            File.SetAttributes(leftover, attrs & ~FileAttributes.ReadOnly);
                        File.Delete(leftover);
                        cleanupRemoved++;
                    }
                    catch (Exception ex)
                    {
                        cleanupFailed++;
                        Console.WriteLine("probe=cleanup_owned_copy result=ERROR file=" +
                            Path.GetFileName(leftover) + " " + ex.GetType().Name);
                    }
                }
            }
            if (cleanupState == "ENUMERATED")
                cleanupState = cleanupFailed == 0 ? "CLEAN" : "PARTIAL";
        }
        Console.WriteLine("cleanup_owned_copies_removed=" + cleanupRemoved);
        Console.WriteLine("cleanup_owned_copies_failed=" + cleanupFailed);
        Console.WriteLine("cleanup_state=" + cleanupState);
        Console.WriteLine("cleanup_operator_followup=" + ownedPrefix + "*");

        // The scratch-directory artefacts. Every name the probe created is listed
        // explicitly -- a cleanup that knows only some of its own artefacts leaves
        // the rest behind, and a stray directory then makes a later run's
        // "fixture absent" assertion untrue for the wrong reason.
        //
        // Deletion is attempted by exact name and any refusal is reported rather
        // than swallowed. An empty Directory.Exists guard is deliberately NOT used
        // for these: skipping a delete silently makes it indistinguishable from a
        // successful one, which is the defect that produced a false OS_ALLOWED in
        // the first subject run.
        if (scratch.Length > 0)
        {
            try
            {
                string p = Path.Combine(scratch, "p.txt");
                if (File.Exists(p)) { File.Delete(p); Console.WriteLine("probe=cleanup_p_txt result=OS_ALLOWED"); }
                else Console.WriteLine("probe=cleanup_p_txt result=NOT_PRESENT");
            }
            catch (Exception ex)
            {
                Console.WriteLine("probe=cleanup_p_txt result=" +
                    (IsAccessDenied(ex) ? "OS_DENIED" : "ERROR") +
                    " " + ex.GetType().Name);
            }

            foreach (string name in new[] {
                "m016_child_create_dir", "m016_child_delete_dir", "childdir" })
            {
                string dir = Path.Combine(scratch, name);
                try
                {
                    if (Directory.Exists(dir))
                    {
                        Directory.Delete(dir, true);
                        Console.WriteLine("probe=cleanup_childdir result=OS_ALLOWED name=" + name);
                    }
                    else Console.WriteLine("probe=cleanup_childdir result=NOT_PRESENT name=" + name);
                }
                catch (Exception ex)
                {
                    Console.WriteLine("probe=cleanup_childdir result=" +
                        (IsAccessDenied(ex) ? "OS_DENIED" : "ERROR") +
                        " name=" + name + " " + ex.GetType().Name);
                }
            }
        }
        string workspaceFile = Path.Combine(workspace, "probe_workspace.txt");
        try { if (File.Exists(workspaceFile)) File.Delete(workspaceFile); }
        catch (Exception) { }

        Console.WriteLine("exit_code=" + Math.Min(allowed, 120));
        return Math.Min(allowed, 120);
    }
}