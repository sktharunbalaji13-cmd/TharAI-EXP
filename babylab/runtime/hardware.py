"""Actual host hardware and resource detection for Milestone 006.

The rule this module exists to enforce
--------------------------------------
Report what the machine *says*, with the provenance of each number attached.
Never estimate a VRAM figure and present it as observed; never assume a GPU is
present because the specification says one should be; never report zero for
something that was not measured.

Every field is a :class:`~babylab.runtime.contract.Measurement`, so a caller
cannot accidentally treat ``DERIVED`` as ``OBSERVED`` or read ``UNAVAILABLE`` as
a real value.

Provenance of each source
-------------------------
``nvidia-smi``   OBSERVED -- the vendor's own tool queried directly.
WMI              OBSERVED -- Windows' own inventory.
``psutil``       OBSERVED -- when installed; otherwise UNAVAILABLE.
arithmetic       DERIVED  -- e.g. tokens/second from two observed counts.
absent probe     UNAVAILABLE, with the reason recorded.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

from babylab.runtime.contract import EpistemicStatus, Measurement

#: Probe budgets. A detection routine must never become the thing that hangs.
_PROBE_TIMEOUT_SECONDS = 15.0


def _run(command: list[str], timeout: float = _PROBE_TIMEOUT_SECONDS):
    """Run a probe with no shell and no inherited stdin."""
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


# ---------------------------------------------------------------------------
# GPU
# ---------------------------------------------------------------------------

#: Quantities that mean "bytes of video memory" across the tools we might use.
_VRAM_KEYS = (
    "memory.total",
    "memory.total_mib",
    "adapterram",
    "vram",
    "totalvram",
)


def _nvidia_smi() -> dict[str, Any]:
    """Query the vendor tool. Authoritative when present."""
    smi = shutil.which("nvidia-smi")
    if not smi:
        return {"source": "none", "detail": "nvidia-smi not found on PATH"}
    completed = _run([
        smi,
        "--query-gpu=name,memory.total,memory.used,driver_version",
        "--format=csv,noheader,nounits",
    ])
    if completed is None:
        return {"source": "nvidia-smi", "detail": "nvidia-smi could not be executed"}
    if completed.returncode != 0:
        return {
            "source": "nvidia-smi",
            "detail": f"nvidia-smi exited {completed.returncode}",
        }
    rows = [line for line in (completed.stdout or "").splitlines() if line.strip()]
    if not rows:
        return {"source": "nvidia-smi", "detail": "nvidia-smi returned no rows"}
    parts = [p.strip() for p in rows[0].split(",")]
    info: dict[str, Any] = {"source": "nvidia-smi", "detail": rows[0].strip(), "rows": len(rows)}
    if parts and parts[0]:
        info["name"] = parts[0]
    for index, key in enumerate(("vram_total_mib", "vram_used_mib", "driver_version"), start=1):
        if len(parts) > index and parts[index]:
            if key.endswith("_mib"):
                try:
                    info[key] = int(float(parts[index]))
                except ValueError:
                    info[key] = None
            else:
                info[key] = parts[index]
    return info


def _wmi_gpu() -> dict[str, Any]:
    """Windows' own display-adapter inventory. Observed, coarser than nvidia-smi."""
    try:
        import subprocess as sp

        completed = sp.run(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_VideoController | "
                "Select-Object -First 1 Name,AdapterRAM,DriverVersion | "
                "ConvertTo-Json -Compress",
            ],
            capture_output=True, text=True, timeout=30.0, shell=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"source": "none", "detail": "WMI query could not be executed"}
    if completed.returncode != 0 or not (completed.stdout or "").strip():
        return {"source": "none", "detail": "WMI reported no display adapter"}
    import json

    try:
        data = json.loads(completed.stdout.strip())
    except json.JSONDecodeError:
        return {"source": "wmi", "detail": "WMI output was not valid JSON"}
    if isinstance(data, list):
        data = data[0] if data else {}
    return {
        "source": "wmi",
        "detail": f"WMI: {data.get('Name')}",
        "name": data.get("Name"),
        "driver_version": data.get("DriverVersion"),
        # AdapterRAM is a uint32 and saturates at 4 GiB on many adapters, so it
        # is reported but explicitly marked as a known-poor source for VRAM.
        "adapter_ram_bytes": data.get("AdapterRAM"),
    }


@dataclass(frozen=True)
class GpuReport:
    """What the host reports about its graphics hardware."""

    available: bool
    name: Measurement
    vram_total_bytes: Measurement
    vram_used_bytes: Measurement
    driver_version: Measurement
    backend_hint: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "name": self.name.to_dict(),
            "vram_total_bytes": self.vram_total_bytes.to_dict(),
            "vram_used_bytes": self.vram_used_bytes.to_dict(),
            "driver_version": self.driver_version.to_dict(),
            "backend_hint": self.backend_hint,
            "detail": self.detail,
        }


def detect_gpu() -> GpuReport:
    """Report the GPU, preferring the vendor tool over WMI.

    The reason nvidia-smi wins is accuracy: WMI's ``AdapterRAM`` is a 32-bit
    field that saturates at 4 GiB, so an 8 GiB card reports as 4 GiB. Reporting
    that as the VRAM figure would be a false negative that could wrongly reject
    a model that in fact fits, so the saturating source is never used for the
    total and is only mentioned in ``detail``.
    """
    smi = _nvidia_smi()
    if smi.get("name"):
        total_mib = smi.get("vram_total_mib")
        used_mib = smi.get("vram_used_mib")
        return GpuReport(
            available=True,
            name=Measurement.observed(smi["name"], source="nvidia-smi"),
            vram_total_bytes=(
                Measurement.observed(int(total_mib) * 1024 * 1024, "bytes", "nvidia-smi")
                if total_mib is not None
                else Measurement.unavailable("nvidia-smi did not report memory.total")
            ),
            vram_used_bytes=(
                Measurement.observed(int(used_mib) * 1024 * 1024, "bytes", "nvidia-smi")
                if used_mib is not None
                else Measurement.unavailable("nvidia-smi did not report memory.used")
            ),
            driver_version=(
                Measurement.observed(smi.get("driver_version", ""), source="nvidia-smi")
            ),
            backend_hint="cuda",
            detail=smi.get("detail", ""),
        )

    wmi = _wmi_gpu()
    if wmi.get("name"):
        return GpuReport(
            available=True,
            name=Measurement.observed(wmi["name"], source="wmi"),
            # Deliberately UNAVAILABLE, not the saturating AdapterRAM figure.
            vram_total_bytes=Measurement.unavailable(
                "no vendor tool reported VRAM; WMI AdapterRAM saturates at 4 GiB "
                "and is not used as a total"
            ),
            vram_used_bytes=Measurement.unavailable("no vendor tool reported VRAM"),
            driver_version=(
                Measurement.observed(wmi.get("driver_version", ""), source="wmi")
                if wmi.get("driver_version")
                else Measurement.unavailable("WMI did not report a driver version")
            ),
            backend_hint="unknown",
            detail=wmi.get("detail", ""),
        )

    return GpuReport(
        available=False,
        name=Measurement.unavailable("no GPU probe succeeded"),
        vram_total_bytes=Measurement.unavailable("no GPU probe succeeded"),
        vram_used_bytes=Measurement.unavailable("no GPU probe succeeded"),
        driver_version=Measurement.unavailable("no GPU probe succeeded"),
        backend_hint="cpu",
        detail=f"nvidia-smi: {smi.get('detail')}; wmi: {wmi.get('detail')}",
    )


# ---------------------------------------------------------------------------
# CPU and system memory
# ---------------------------------------------------------------------------

def detect_cpu() -> dict[str, Measurement]:
    """CPU description. Observed from the OS, never assumed from the spec."""
    detail: dict[str, Measurement] = {
        "logical_cores": Measurement.observed(os.cpu_count(), "count", "os.cpu_count"),
        "machine": Measurement.observed(platform.machine(), source="platform"),
        "processor": Measurement.observed(platform.processor() or "unknown",
                                          source="platform.processor"),
    }
    try:
        completed = _run([
            "powershell", "-NoProfile", "-Command",
            "(Get-CimInstance Win32_Processor | Select-Object -First 1 Name,"
            "NumberOfCores,NumberOfLogicalProcessors | ConvertTo-Json -Compress)",
        ], timeout=30.0)
        if completed and completed.returncode == 0 and (completed.stdout or "").strip():
            import json

            data = json.loads(completed.stdout.strip())
            if isinstance(data, list):
                data = data[0] if data else {}
            if data.get("Name"):
                detail["name"] = Measurement.observed(data["Name"], source="wmi")
            if data.get("NumberOfCores") is not None:
                detail["physical_cores"] = Measurement.observed(
                    int(data["NumberOfCores"]), "count", "wmi"
                )
            if data.get("NumberOfLogicalProcessors") is not None:
                detail["logical_cores"] = Measurement.observed(
                    int(data["NumberOfLogicalProcessors"]), "count", "wmi"
                )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return detail


def detect_system_memory() -> dict[str, Measurement]:
    """System RAM. Uses psutil when present, else UNAVAILABLE."""
    try:
        import psutil  # type: ignore

        virtual = psutil.virtual_memory()
        return {
            "total_bytes": Measurement.observed(int(virtual.total), "bytes", "psutil"),
            "available_bytes": Measurement.observed(int(virtual.available), "bytes", "psutil"),
            "percent_used": Measurement.observed(float(virtual.percent), "percent", "psutil"),
        }
    except ImportError:
        return {
            "total_bytes": Measurement.unavailable("psutil is not installed"),
            "available_bytes": Measurement.unavailable("psutil is not installed"),
            "percent_used": Measurement.unavailable("psutil is not installed"),
        }
    except Exception as exc:  # noqa: BLE001 - detection must never crash the lab
        return {
            "total_bytes": Measurement.unavailable(f"psutil failed: {exc}"),
            "available_bytes": Measurement.unavailable(f"psutil failed: {exc}"),
            "percent_used": Measurement.unavailable(f"psutil failed: {exc}"),
        }


def detect_disk(path: str = ".") -> dict[str, Measurement]:
    """Free space where the weights would live. Observed."""
    try:
        usage = shutil.disk_usage(path)
        return {
            "total_bytes": Measurement.observed(usage.total, "bytes", "shutil.disk_usage"),
            "free_bytes": Measurement.observed(usage.free, "bytes", "shutil.disk_usage"),
        }
    except OSError as exc:
        return {
            "total_bytes": Measurement.unavailable(f"disk_usage failed: {exc}"),
            "free_bytes": Measurement.unavailable(f"disk_usage failed: {exc}"),
        }


@dataclass(frozen=True)
class HardwareReport:
    """Everything M006 knows about this machine, with epistemic status intact."""

    gpu: GpuReport
    cpu: dict[str, Measurement]
    memory: dict[str, Measurement]
    disk: dict[str, Measurement]
    platform_info: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "gpu": self.gpu.to_dict(),
            "cpu": {k: v.to_dict() for k, v in self.cpu.items()},
            "memory": {k: v.to_dict() for k, v in self.memory.items()},
            "disk": {k: v.to_dict() for k, v in self.disk.items()},
            "platform": self.platform_info,
        }

    def summary_lines(self) -> list[str]:
        """Human-readable, status-annotated. Never prints a bare number."""
        lines: list[str] = []
        if self.gpu.available:
            lines.append(f"gpu            {self.gpu.name.value} [OBSERVED]")
            vram = self.gpu.vram_total_bytes
            if vram.is_available:
                lines.append(
                    f"vram           {vram.value / (1024 ** 3):.2f} GiB "
                    f"[{vram.status.value}]"
                )
            else:
                lines.append(f"vram           UNAVAILABLE ({vram.source})")
        else:
            lines.append("gpu            UNAVAILABLE (no probe succeeded)")
        name = self.cpu.get("name")
        if name is not None and name.is_available:
            lines.append(f"cpu            {name.value} [OBSERVED]")
        logical = self.cpu.get("logical_cores")
        if logical is not None and logical.is_available:
            lines.append(f"cores          {logical.value} logical [OBSERVED]")
        total = self.memory.get("total_bytes")
        if total is not None and total.is_available:
            lines.append(f"system_ram     {total.value / (1024 ** 3):.2f} GiB [OBSERVED]")
        else:
            lines.append("system_ram     UNAVAILABLE")
        free = self.disk.get("free_bytes")
        if free is not None and free.is_available:
            lines.append(f"disk_free      {free.value / (1024 ** 3):.2f} GiB [OBSERVED]")
        return lines


def detect_hardware(disk_path: str = ".") -> HardwareReport:
    """Probe the host. Cheap, bounded, and never fatal."""
    return HardwareReport(
        gpu=detect_gpu(),
        cpu=detect_cpu(),
        memory=detect_system_memory(),
        disk=detect_disk(disk_path),
        platform_info={
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "python": sys.version.split()[0],
            "python_executable": sys.executable,
        },
    )


__all__ = [
    "EpistemicStatus",
    "GpuReport",
    "HardwareReport",
    "Measurement",
    "detect_cpu",
    "detect_disk",
    "detect_gpu",
    "detect_hardware",
    "detect_system_memory",
]
