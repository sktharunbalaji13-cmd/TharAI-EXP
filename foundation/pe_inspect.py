"""Read a PE file's import table. For dependency analysis only.

Used to answer a narrow question for the staging design: if a human selects a
llama.cpp runtime, which files would have to be staged with it? The answer has to
come from the executable's own import table rather than from the fact that other
files sit beside it in the same folder -- Windows resolves an import by *searching*
for it, so a file that merely happens to be nearby may never be loaded, and a file
that is genuinely required may be expected from somewhere else entirely.

Reads only. Loads nothing.
"""

from __future__ import annotations

import struct
from pathlib import Path

_MACHINE_NAMES = {0x014C: "x86", 0x8664: "x64", 0xAA64: "arm64"}


class PEError(ValueError):
    """The file is not a readable PE image."""


def _sections(data: bytes) -> tuple[int, list[tuple[int, int, int, int]]]:
    """The PE header offset and ``(virtual_address, raw_offset, raw_size, ...)``.

    Every read is bounds-checked and every failure becomes :class:`PEError`. A
    staged artifact can plausibly arrive truncated — a partial copy, a full disk,
    an interrupted download — and a parser that raises ``struct.error`` on one
    reports the wrong problem entirely. A malformed binary is a *finding*, and it
    should read as one.
    """
    if len(data) < 0x40:
        raise PEError(f"file is too small to be a PE image ({len(data)} bytes)")
    if data[:2] != b"MZ":
        raise PEError("no MZ signature")
    try:
        pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe_offset:pe_offset + 4] != b"PE\0\0":
            raise PEError("no PE signature")

        machine, section_count = struct.unpack_from("<HH", data, pe_offset + 4)
        optional_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
        optional = pe_offset + 24
        magic = struct.unpack_from("<H", data, optional)[0]
        if magic == 0x20B:            # PE32+
            directories = optional + 112
        elif magic == 0x10B:          # PE32
            directories = optional + 96
        else:
            raise PEError(f"unknown optional header magic 0x{magic:04X}")

        section_table = optional + optional_size
        entries: list[tuple[int, int, int, int]] = []
        for index in range(section_count):
            base = section_table + index * 40
            virtual_size, virtual_address, raw_size, raw_offset = \
                struct.unpack_from("<IIII", data, base + 8)
            # A section whose raw bytes run past the end of the file means the
            # image is truncated. Reported rather than tolerated: without this, a
            # half-copied DLL resolves no RVA to an offset, the import walk finds
            # nothing, and the reader reports "0 imports" for a file that plainly
            # has them. Silence here would let a truncated staged artifact pass as
            # a dependency-free one -- the exact failure the staging design most
            # needs to detect.
            if raw_offset + raw_size > len(data):
                raise PEError(
                    f"the image is truncated: section {index} claims bytes "
                    f"{raw_offset}..{raw_offset + raw_size} but the file is "
                    f"{len(data)} bytes"
                )
            entries.append((virtual_address, raw_offset, raw_size, virtual_size))
    except struct.error as exc:
        raise PEError(f"the PE headers are truncated or malformed: {exc}") from exc
    return directories, entries


def machine_architecture(data: bytes) -> str:
    """``x64``, ``x86``, ``arm64``, or ``unknown (0x....)``."""
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    machine = struct.unpack_from("<H", data, pe_offset + 4)[0]
    return _MACHINE_NAMES.get(machine, f"unknown (0x{machine:04X})")


def _rva_to_offset(rva: int, entries: list[tuple[int, int, int, int]]) -> int | None:
    for virtual_address, raw_offset, raw_size, _ in entries:
        if virtual_address <= rva < virtual_address + max(raw_size, 1):
            return raw_offset + (rva - virtual_address)
    return None


def _read_c_string(data: bytes, offset: int) -> str:
    end = data.find(b"\0", offset)
    return data[offset:end if end != -1 else len(data)].decode(
        "ascii", errors="replace")


def imported_dlls(path: str | Path) -> list[str]:
    """The DLLs this PE imports, in import-table order.

    Case preserved as written, because Windows' loader search is
    case-insensitive but a mismatch still shows up in a diff as a change.
    """
    data = Path(path).read_bytes()
    directories, entries = _sections(data)
    import_rva, import_size = struct.unpack_from(
        "<II", data, directories + 8,
    )
    if not import_rva:
        return []

    names: list[str] = []
    cursor = _rva_to_offset(import_rva, entries)
    if cursor is None:
        return []
    while True:
        chunk = data[cursor:cursor + 20]
        if len(chunk) < 20 or chunk == b"\0" * 20:
            break
        name_rva = struct.unpack_from("<I", chunk, 12)[0]
        if not name_rva:
            break
        name_offset = _rva_to_offset(name_rva, entries)
        if name_offset is None:
            break
        names.append(_read_c_string(data, name_offset))
        cursor += 20
    return names


def imported_symbols(path: str | Path) -> list[tuple[str, str]]:
    """``(dll, symbol)`` pairs, for seeing *which* runtime a symbol comes from."""
    data = Path(path).read_bytes()
    directories, entries = _sections(data)
    import_rva, _ = struct.unpack_from("<II", data, directories + 8)
    if not import_rva:
        return []
    cursor = _rva_to_offset(import_rva, entries)
    if cursor is None:
        return []

    out: list[tuple[str, str]] = []
    while True:
        chunk = data[cursor:cursor + 20]
        if len(chunk) < 20 or chunk == b"\0" * 20:
            break
        name_rva, thunk_rva = struct.unpack_from("<II", chunk, 12)
        if not name_rva:
            break
        dll = _read_c_string(data, _rva_to_offset(name_rva, entries) or 0)
        thunk = _rva_to_offset(thunk_rva, entries)
        if thunk is None:
            cursor += 20
            continue
        step = 8 if machine_architecture(data) in {"x64", "arm64"} else 4
        ordinal_flag = 1 << (63 if step == 8 else 31)
        offset = thunk
        for _ in range(4096):
            value = struct.unpack_from("<Q" if step == 8 else "<I",
                                       data, offset)[0]
            if value == 0:
                break
            if not value & ordinal_flag:
                hint = _rva_to_offset(value & 0x7FFFFFFF, entries)
                if hint is not None:
                    out.append((dll, _read_c_string(data, hint + 2)))
            offset += step
        cursor += 20
    return out


def dependency_report(executable: str | Path, search_dir: str | Path | None = None
                      ) -> dict[str, object]:
    """Which imports are satisfiable from ``search_dir``, and which are not.

    "Satisfiable from here" is not "will load from here": the loader also searches
    the executable's own directory, the system directories, and anything on
    ``PATH``. Staging more files than this reports is harmless; staging fewer is
    the failure this is meant to catch.
    """
    exe = Path(executable)
    directory = Path(search_dir) if search_dir else exe.parent
    available = {p.name.lower() for p in directory.glob("*") if p.is_file()}
    available |= {p.name.lower() for p in directory.glob("*.dll")}

    imports = imported_dlls(exe)
    local = [name for name in imports if name.lower() in available]
    missing = [name for name in imports if name.lower() not in available]
    return {
        "executable": str(exe),
        "architecture": machine_architecture(exe.read_bytes()),
        "imports": imports,
        "import_count": len(imports),
        "satisfiable_from_search_dir": local,
        "not_in_search_dir": missing,
        "note": (
            "imports not present beside the executable are expected to come from "
            "the Windows system directories; that is normal for kernel32, "
            "user32 and the C runtime. A missing llama/ggml DLL would not be "
            "normal and would mean an incomplete stage."
        ),
    }


__all__ = [
    "PEError",
    "dependency_report",
    "imported_dlls",
    "imported_symbols",
    "machine_architecture",
]