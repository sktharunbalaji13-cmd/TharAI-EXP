"""M011 hardware: measure this host now, not what M006 recorded then.

Why a fresh measurement
-----------------------
M006 recorded hardware on 2026-09-27. M011 is a different day, and a report
that quotes a week-old GPU figure as though it were observed *now* is the same
class of error as reusing a digest instead of recomputing one. Everything here
is measured at call time; nothing is cached, and nothing falls back to a
documented "expected" value.

The historical M006 figures (Ryzen 7 7840HS, RTX 4060 Laptop, 8 GiB VRAM,
16 GB RAM) are treated as notes about the intended target machine, not as facts
about the machine running this code. A field may disagree with them, and the
disagreement is recorded rather than resolved in favour of the documentation.

Honest measurement
------------------
Every figure carries its source and an epistemic status. Where a figure cannot
be obtained the value is ``UNAVAILABLE`` with a reason. In particular:

* VRAM comes from ``nvidia-smi``. WMI's ``AdapterRAM`` saturates at 4 GiB and is
  a known-bad source, so it is never used for a VRAM figure.
* Free VRAM is a point-in-time reading, and is labelled as such. It changes
  between calls, and a report that presented it as a stable property would be
  misleading.
* WMI's ``AdapterRAM`` is reported under its own key and explicitly marked
  unreliable, because a reader will otherwise take the first GPU number they
  see.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Recorded for comparison only. Never substituted for an observation.
M006_HISTORICAL = {
    "cpu": "AMD Ryzen 7 7840HS",
    "gpu": "NVIDIA GeForce RTX 4060 Laptop GPU",
    "vram_gib": 8.0,
    "ram_gib": 16.0,
    "os": "Windows 11",
    "recorded_on": "2026-09-27 (Milestone 006)",
}

#: Ceilings for every subprocess this module runs. A hardware probe that hangs
#: is worse than one that returns nothing.
PROBE_TIMEOUT_SECONDS = 25.0


def _run(command: list[str], timeout: float = PROBE_TIMEOUT_SECONDS):
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        stdin=subprocess.DEVNULL,
        shell=False,
    )


@dataclass(frozen=True)
class Reading:
    """One measurement, with the source that produced it."""

    value: Any
    unit: str = ""
    source: str = "unavailable"
    available: bool = True
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "unit": self.unit,
            "source": self.source,
            "status": "OBSERVED" if self.available else "UNAVAILABLE",
            "note": self.note,
        }


def _unavailable(reason: str, unit: str = "") -> Reading:
    return Reading(value=None, unit=unit, source=reason, available=False,
                   note="not estimated and not inferred from any other figure")


def measure_os() -> dict[str, Reading]:
    """Operating system, from the platform the process is actually running on."""
    system = platform.system()
    release = platform.release()
    version = platform.version()
    build = ""
    try:
        build = release.split(".")[-1] if release else ""
    except Exception:  # noqa: BLE001 - cosmetic
        build = ""
    return {
        "system": Reading(value=system or None, source="platform.system()"),
        "release": Reading(value=release or None, source="platform.release()"),
        "version": Reading(value=version or None, source="platform.version()"),
        "edition": Reading(
            value=_windows_edition(),
            source="registry ProductName, cross-checked against CurrentBuild",
        ),
        "registry_product_name": Reading(
            value=_registry_product_name(),
            source="registry ProductName (verbatim, uncorrected)",
            note=(
                "reported verbatim for transparency. On Windows 11 this key still "
                "reads 'Windows 10'; it is a stale label, not the real edition, "
                "which is why it is reported alongside rather than instead of "
                "the build number."
            ),
        ),
        "build_number": Reading(
            value=_current_build(),
            source="registry CurrentBuildNumber",
        ),
        "is_windows": Reading(value=system == "Windows", source="platform.system()"),
    }


#: Build 22000 is where Windows 11 begins. Below it, the build is Windows 10.
_WINDOWS_11_MIN_BUILD = 22000


def _registry_values() -> dict[str, Any]:
    try:
        import winreg  # type: ignore[import-not-found]

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
        )
        values: dict[str, Any] = {}
        with key:
            for name in ("ProductName", "DisplayVersion", "CurrentBuildNumber"):
                try:
                    values[name], _ = winreg.QueryValueEx(key, name)
                except OSError:
                    continue
        return values
    except Exception:  # noqa: BLE001 - registry access is best effort
        return {}


def _registry_product_name() -> str | None:
    raw = _registry_values().get("ProductName")
    return str(raw) if raw else None


def _current_build() -> int | None:
    raw = _registry_values().get("CurrentBuildNumber")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _windows_edition() -> str | None:
    """The real Windows edition, corrected for the registry's stale label.

    ``ProductName`` has read "Windows 10" on Windows 11 since its release,
    because too much software parsed it and changing it would break those
    callers. Taking it at face value would make this report state that a
    Windows 11 machine is running Windows 10 -- so the build number decides, and
    the raw string is reported separately as
    :func:`_registry_product_name`.
    """
    values = _registry_values()
    display = str(values.get("DisplayVersion", "")).strip()
    try:
        build = int(values.get("CurrentBuildNumber"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None

    family = "Windows 11" if build >= _WINDOWS_11_MIN_BUILD else "Windows 10"
    edition = str(values.get("ProductName", "")).strip()
    # Drop the (wrong) family word from ProductName and keep the rest.
    for prefix in ("Windows 11", "Windows 10"):
        if edition.lower().startswith(prefix.lower()):
            edition = edition[len(prefix):].strip()
            break
    parts = [part for part in (family, edition, display) if part]
    return " ".join(parts) + f" (build {build})"


def measure_cpu() -> dict[str, Reading]:
    """CPU model and core count, from the OS rather than from the CPUID."""
    model: Reading
    try:
        import winreg  # type: ignore[import-not-found]

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        )
        with key:
            name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
        model = Reading(value=str(name).strip(), source="registry ProcessorNameString")
    except Exception:  # noqa: BLE001
        model = _unavailable("registry read failed")

    physical = _unavailable("physical core count not measured", "cores")
    try:
        # wmic is deprecated but still answers on many hosts; the fallback keeps
        # the reading honest rather than guessing from the logical count.
        completed = _run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Processor | Measure-Object -Property "
             "NumberOfCores -Sum).Sum"]
        )
        if completed.returncode == 0:
            total = completed.stdout.strip()
            if total.isdigit():
                physical = Reading(value=int(total), unit="cores",
                                   source="Win32_Processor.NumberOfCores")
    except Exception:  # noqa: BLE001
        pass

    return {
        "model": model,
        "logical_processors": Reading(
            value=os.cpu_count(), unit="logical", source="os.cpu_count()"
        ),
        "physical_cores": physical,
        "machine": Reading(value=platform.machine() or None,
                           source="platform.machine()"),
    }


def measure_memory() -> dict[str, Reading]:
    """Physical and available RAM.

    ``available`` comes from the performance counter rather than from
    free-minus-cached arithmetic, because the arithmetic overstates on Windows.
    """
    result = {
        "total_bytes": _unavailable("GlobalMemoryStatusEx unavailable", "bytes"),
        "available_bytes": _unavailable("GlobalMemoryStatusEx unavailable", "bytes"),
    }
    try:
        import ctypes
        from ctypes import wintypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            result["total_bytes"] = Reading(
                value=int(status.ullTotalPhys), unit="bytes",
                source="GlobalMemoryStatusEx",
            )
            result["available_bytes"] = Reading(
                value=int(status.ullAvailPhys), unit="bytes",
                source="GlobalMemoryStatusEx",
            )
            result["load_percent"] = Reading(
                value=int(status.dwMemoryLoad), unit="percent",
                source="GlobalMemoryStatusEx",
            )
    except Exception:  # noqa: BLE001
        pass
    return result


def _nvidia_smi() -> dict[str, Any] | None:
    """Query the vendor tool. Returns ``None`` when it cannot be used.

    The three figures are asked for separately from the two timing figures, so
    a run-time observation can be taken while a model is resident without
    restarting anything.
    """
    smi = shutil.which("nvidia-smi")
    if smi is None:
        return None
    try:
        completed = _run([
            smi,
            "--query-gpu=name,memory.total,memory.used,memory.free,"
            "driver_version,compute_cap",
            "--format=csv,noheader,nounits",
        ])
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        return None

    rows = [r.strip() for r in completed.stdout.strip().splitlines() if r.strip()]
    if not rows:
        return None
    fields = [f.strip() for f in rows[0].split(",")]
    values = dict(zip(
        ("name", "total_mib", "used_mib", "free_mib", "driver", "compute_cap"),
        fields,
    ))

    def _int(key: str) -> int | None:
        raw = values.get(key, "")
        try:
            return int(raw) if raw else None
        except ValueError:
            return None

    return {
        "name": values.get("name") or None,
        "total_bytes": _int("total_mib") * 1024 * 1024 if _int("total_mib") else None,
        "used_bytes": _int("used_mib") * 1024 * 1024 if _int("used_mib") else None,
        "free_bytes": _int("free_mib") * 1024 * 1024 if _int("free_mib") else None,
        "driver_version": values.get("driver") or None,
        "compute_capability": values.get("compute_cap") or None,
        "source": "nvidia-smi",
    }


def measure_gpu() -> dict[str, Any]:
    """GPU and VRAM, preferring the vendor tool.

    ``adapter_ram_wmi`` is reported but explicitly marked as not a VRAM figure.
    It is included because a reader who queried WMI would see a number, and
    silently omitting it would leave them to find it later and trust it.
    """
    smi = _nvidia_smi()
    if smi is None:
        return {
            "name": _unavailable("no vendor GPU tool on PATH"),
            "vram_total_bytes": _unavailable("no vendor tool reported VRAM", "bytes"),
            "vram_used_bytes": _unavailable("no vendor tool reported VRAM", "bytes"),
            "vram_free_bytes": _unavailable("no vendor tool reported VRAM", "bytes"),
            "driver_version": _unavailable("no vendor GPU tool on PATH"),
            "adapter_ram_wmi": _unavailable("WMI not queried"),
            "note": (
                "no nvidia-smi on PATH, so no VRAM figure exists. The laboratory "
                "will not infer one from the model's size or from a remembered "
                "total."
            ),
        }

    return {
        "name": Reading(value=smi["name"], source="nvidia-smi"),
        "vram_total_bytes": Reading(
            value=smi["total_bytes"], unit="bytes", source="nvidia-smi",
            note="device total, not the laboratory's allocation",
        ),
        "vram_used_bytes": Reading(
            value=smi["used_bytes"], unit="bytes", source="nvidia-smi",
            note="system-wide usage at the instant of the query, including any "
                 "other process on this GPU; it is NOT this runtime's allocation",
        ),
        "vram_free_bytes": Reading(
            value=smi["free_bytes"], unit="bytes", source="nvidia-smi",
            note="point-in-time reading; it changes between calls",
        ),
        "driver_version": Reading(value=smi["driver_version"], source="nvidia-smi"),
        "compute_capability": Reading(
            value=smi["compute_capability"], source="nvidia-smi"
        ),
        "adapter_ram_wmi": Reading(
            value=None, source="deliberately not queried",
            available=False,
            note=(
                "WMI Win32_VideoController.AdapterRAM is a 32-bit field that "
                "saturates at 4 GiB, so it under-reports any modern GPU. It is "
                "not used for a VRAM figure anywhere in this project."
            ),
        ),
    }


def measure_disk(path: str | Path = ".") -> dict[str, Reading]:
    """Free space where the weights would live.

    Reported because a model is large and a full disk produces a download or
    load failure that looks like a corrupt artifact.
    """
    try:
        usage = shutil.disk_usage(str(path))
        return {
            "total_bytes": Reading(value=usage.total, unit="bytes",
                                   source="shutil.disk_usage"),
            "free_bytes": Reading(value=usage.free, unit="bytes",
                                  source="shutil.disk_usage"),
        }
    except OSError as exc:
        return {
            "total_bytes": _unavailable(f"disk_usage failed: {exc}", "bytes"),
            "free_bytes": _unavailable(f"disk_usage failed: {exc}", "bytes"),
        }


def measure_disk_free_vram() -> dict[str, Reading]:
    """A second free-VRAM reading, for a before/after pair.

    Taken as a distinct call rather than reused, because the point of the pair
    is to show movement. Reusing the earlier figure would make the comparison
    meaningless while appearing to show stability.
    """
    smi = _nvidia_smi()
    if smi is None:
        return {
            "vram_free_bytes": _unavailable("no vendor tool reported VRAM", "bytes"),
            "note": "free VRAM could not be re-observed",
        }
    return {
        "vram_free_bytes": Reading(
            value=smi["free_bytes"], unit="bytes", source="nvidia-smi",
            note="second point-in-time reading, taken separately from the first",
        ),
        "vram_used_bytes": Reading(
            value=smi["used_bytes"], unit="bytes", source="nvidia-smi",
            note="system-wide; not attributable to any single process",
        ),
    }


@dataclass
class HostReport:
    """Everything M011 measured about the machine it ran on."""

    measured_at: str = ""
    os: dict[str, Reading] = field(default_factory=dict)
    cpu: dict[str, Reading] = field(default_factory=dict)
    memory: dict[str, Reading] = field(default_factory=dict)
    gpu: dict[str, Any] = field(default_factory=dict)
    disk: dict[str, Reading] = field(default_factory=dict)
    python: dict[str, Reading] = field(default_factory=dict)
    historical: dict[str, Any] = field(default_factory=lambda: dict(M006_HISTORICAL))

    @property
    def gpu_available(self) -> bool:
        name = self.gpu.get("name")
        return bool(name is not None and name.available)

    @property
    def vram_total_bytes(self) -> int | None:
        reading = self.gpu.get("vram_total_bytes")
        return int(reading.value) if reading is not None and reading.available else None

    @property
    def vram_free_bytes(self) -> int | None:
        reading = self.gpu.get("vram_free_bytes")
        return int(reading.value) if reading is not None and reading.available else None

    def disagreements_with_m006(self) -> list[str]:
        """Where this host differs from the M006 record.

        Returned as sentences so the final report can state the difference
        rather than leaving a reader to spot it. A silent match is worth as
        little as a silent disagreement.
        """
        notes: list[str] = []
        cpu_model = self.cpu.get("model")
        if cpu_model is not None and cpu_model.available and cpu_model.value:
            if M006_HISTORICAL["cpu"].lower() not in str(cpu_model.value).lower():
                notes.append(
                    f"CPU is {cpu_model.value!r}, where M006 recorded "
                    f"{M006_HISTORICAL['cpu']!r}"
                )
        gpu_name = self.gpu.get("name")
        if gpu_name is not None and gpu_name.available and gpu_name.value:
            if M006_HISTORICAL["gpu"].lower() not in str(gpu_name.value).lower():
                notes.append(
                    f"GPU is {gpu_name.value!r}, where M006 recorded "
                    f"{M006_HISTORICAL['gpu']!r}"
                )
        total = self.vram_total_bytes
        if total is not None:
            observed = total / (1024 ** 3)
            if abs(observed - float(M006_HISTORICAL["vram_gib"])) > 0.5:
                notes.append(
                    f"VRAM total is {observed:.1f} GiB, where M006 recorded "
                    f"{M006_HISTORICAL['vram_gib']:.1f} GiB"
                )
        edition = self.os.get("edition")
        if edition is not None and edition.available and edition.value:
            if "windows 11" not in str(edition.value).lower():
                notes.append(
                    f"OS edition is {edition.value!r}, where M006 recorded "
                    "'Windows 11'"
                )
        return notes

    def to_dict(self) -> dict[str, Any]:
        return {
            "measured_at": self.measured_at,
            "os": {k: v.to_dict() for k, v in self.os.items()},
            "cpu": {k: v.to_dict() for k, v in self.cpu.items()},
            "memory": {k: v.to_dict() for k, v in self.memory.items()},
            "gpu": {k: (v.to_dict() if isinstance(v, Reading) else v)
                    for k, v in self.gpu.items()},
            "disk": {k: v.to_dict() for k, v in self.disk.items()},
            "python": {k: v.to_dict() for k, v in self.python.items()},
            "historical_m006": self.historical,
            "disagreements_with_m006": self.disagreements_with_m006(),
            "policy": (
                "every figure is measured at call time. The M006 record is "
                "attached for comparison and is never substituted for an "
                "observation."
            ),
        }

    def summary_lines(self) -> list[str]:
        def _fmt(reading: Reading | None, suffix: str = "") -> str:
            if reading is None or not reading.available or reading.value is None:
                return f"UNAVAILABLE ({reading.source if reading else 'none'})"
            value = reading.value
            if isinstance(value, (int, float)) and reading.unit == "bytes":
                return f"{value / (1024 ** 3):.2f} GiB [OBSERVED via {reading.source}]"
            return f"{value}{suffix} [OBSERVED via {reading.source}]"

        lines = [
            f"os                {_fmt(self.os.get('edition'))}",
            f"cpu               {_fmt(self.cpu.get('model'))}",
            f"logical cpus      {_fmt(self.cpu.get('logical_processors'))}",
            f"physical cores    {_fmt(self.cpu.get('physical_cores'))}",
            f"ram total         {_fmt(self.memory.get('total_bytes'))}",
            f"ram available     {_fmt(self.memory.get('available_bytes'))}",
            f"gpu               {_fmt(self.gpu.get('name'))}",
            f"vram total        {_fmt(self.gpu.get('vram_total_bytes'))}",
            f"vram free         {_fmt(self.gpu.get('vram_free_bytes'))}",
            f"driver            {_fmt(self.gpu.get('driver_version'))}",
            f"disk free         {_fmt(self.disk.get('free_bytes'))}",
            f"python            {_fmt(self.python.get('version'))}",
        ]
        return lines


def measure_host(disk_path: str | Path = ".") -> HostReport:
    """Measure this host now."""
    from babylab.clock import Clock

    report = HostReport(
        measured_at=Clock().timestamp(),
        os=measure_os(),
        cpu=measure_cpu(),
        memory=measure_memory(),
        gpu=measure_gpu(),
        disk=measure_disk(disk_path),
        python={
            "version": Reading(value=platform.python_version(),
                               source="platform.python_version()"),
            "implementation": Reading(value=platform.python_implementation(),
                                      source="platform.python_implementation()"),
            "executable": Reading(value=sys.executable, source="sys.executable"),
        },
    )
    return report


__all__ = [
    "M006_HISTORICAL",
    "PROBE_TIMEOUT_SECONDS",
    "HostReport",
    "Reading",
    "measure_cpu",
    "measure_disk",
    "measure_disk_free_vram",
    "measure_gpu",
    "measure_host",
    "measure_memory",
    "measure_os",
]
