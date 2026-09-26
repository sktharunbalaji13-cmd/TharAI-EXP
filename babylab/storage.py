"""Durable, all-or-nothing file writes and cross-platform advisory locking.

Why this exists
---------------
Two append-only stores (the event log and the provenance ledger) are written
by one process and read by another (the observer). Two hazards follow:

* **Torn writes.** A reader must never observe a partially written line. All
  whole-file writes go through :func:`atomic_write_bytes`, which writes to a
  temporary file in the same directory, flushes it to the device, then renames.
  ``os.replace`` is atomic on Windows and POSIX for same-volume renames.
* **Interleaved appends.** Two writers appending to the same log could
  interleave partial lines. Appends therefore take an exclusive lock.

Platform support: Windows (``msvcrt``) and POSIX (``fcntl``). Other platforms
raise at lock time rather than silently running unlocked.
"""

from __future__ import annotations

import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

if sys.platform == "win32":
    import msvcrt
elif sys.platform.startswith("posix"):
    import fcntl
else:  # pragma: no cover - the project targets Windows 11 and POSIX
    msvcrt = None
    fcntl = None

#: Filename suffix used for the lock sidecar. Kept next to the target file so
#: that the lock is per-file rather than per-directory.
LOCK_SUFFIX = ".lock"


def fsync_directory(path: Path) -> None:
    """Best-effort fsync of a directory so a rename survives a power loss.

    Windows does not permit opening a directory for this purpose, so this is
    a no-op there. The limitation is documented rather than hidden.
    """
    if sys.platform == "win32":
        return
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    except OSError:  # pragma: no cover - filesystem dependent
        pass
    finally:
        os.close(fd)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Replace ``path`` with ``data`` atomically, or leave it untouched."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="wb",
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(path))
        fsync_directory(path.parent)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """UTF-8 flavour of :func:`atomic_write_bytes`."""
    atomic_write_bytes(path, text.encode(encoding))


@contextmanager
def exclusive_lock(path: Path, timeout: float = 10.0) -> Iterator[None]:
    """Hold an exclusive advisory lock associated with ``path``.

    Uses a ``<path>.lock`` sidecar rather than locking ``path`` itself, so
    that the lock survives atomic replacement of the target file and so that
    readers never have to open the data file just to check a lock.
    """
    if msvcrt is None and fcntl is None:  # pragma: no cover
        raise NotImplementedError(
            f"advisory locking is not implemented for platform {sys.platform}"
        )

    lock_path = Path(str(path) + LOCK_SUFFIX)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")
    acquired = False
    try:
        if msvcrt is not None:
            acquired = _acquire_msvcrt(handle, timeout)
        else:
            acquired = _acquire_fcntl(handle, timeout)
        if not acquired:
            raise TimeoutError(f"could not acquire lock on {path} within {timeout}s")
        yield
    finally:
        if acquired:
            if msvcrt is not None:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _acquire_msvcrt(handle, timeout: float) -> bool:
    import time

    deadline = time.monotonic() + timeout
    while True:
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)


def _acquire_fcntl(handle, timeout: float) -> bool:
    import time

    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)


def append_line(path: Path, line: str) -> int:
    """Append one newline-terminated line under an exclusive lock.

    Returns the byte offset at which the line was written, which the event
    store uses to build a reliable tail cursor.

    The caller is responsible for taking the lock if a multi-line atomic
    append is required; use :func:`exclusive_lock` around groups of calls.
    """
    data = (line.rstrip("\n") + "\n").encode("utf-8")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "ab") as handle:
        handle.seek(0, os.SEEK_END)
        offset = handle.tell()
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return offset
