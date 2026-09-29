"""Laboratory-controlled pause, resume and termination.

Who may call these
------------------
The laboratory, explicitly. There is no subject-side entry point: no method
here accepts a subject-issued request, and the M008 lifecycle already refuses
non-laboratory transitions. These operations are thin, auditable wrappers that
record *why* in the ceremony record when one exists.

What each operation preserves
-----------------------------
* **Pause** suspends interaction and keeps everything. State is untouched;
  history is untouched; resume continues from exactly the held state.
* **Resume** returns a paused record to active. Resuming anything that is not
  paused is refused rather than reinterpreted.
* **Terminate** ends the record permanently and keeps all of it. Termination
  deletes nothing: state, history and provenance remain exactly as they were,
  and any later interaction attempt is refused because the lifecycle is
  terminal. A terminated record that lost its history would be
  indistinguishable from a record that never had one, which is why the
  operation is defined this way.
"""

from __future__ import annotations

from typing import Any

from subject.lifecycle import LifecycleError, LifecycleState


class ControlError(RuntimeError):
    """A refused lifecycle-control operation."""

    def __init__(self, operation: str, reason: str, detail: str = "") -> None:
        super().__init__(
            f"{operation}: {reason}: {detail}" if detail else f"{operation}: {reason}")
        self.operation = operation
        self.reason = reason
        self.detail = detail


def _require_laboratory(authorized_by: str, operation: str) -> None:
    if authorized_by != "LABORATORY":
        raise ControlError(
            operation, "UNAUTHORIZED",
            f"lifecycle control requires laboratory authorization; got "
            f"{authorized_by!r}")


def pause(lifecycle, authorized_by: str, timestamp: str) -> LifecycleState:
    """Suspend interaction. State and history are preserved untouched."""
    _require_laboratory(authorized_by, "pause")
    try:
        return lifecycle.transition(LifecycleState.PAUSED, "LABORATORY", timestamp)
    except LifecycleError as exc:
        raise ControlError("pause", exc.reason, exc.detail) from None


def resume(lifecycle, authorized_by: str, timestamp: str) -> LifecycleState:
    """Return a paused record to active. Anything else is refused."""
    _require_laboratory(authorized_by, "resume")
    if lifecycle.state is not LifecycleState.PAUSED:
        raise ControlError(
            "resume", "INVALID_STATE",
            f"only a PAUSED record may resume; this one is "
            f"{lifecycle.state.value}")
    try:
        return lifecycle.transition(LifecycleState.ACTIVE, "LABORATORY", timestamp)
    except LifecycleError as exc:
        raise ControlError("resume", exc.reason, exc.detail) from None


def terminate(lifecycle, authorized_by: str, timestamp: str,
              reason: str = "") -> LifecycleState:
    """End the record permanently. Nothing is deleted."""
    _require_laboratory(authorized_by, "terminate")
    try:
        return lifecycle.transition(LifecycleState.TERMINATED, "LABORATORY",
                                    timestamp)
    except LifecycleError as exc:
        raise ControlError("terminate", exc.reason, exc.detail) from None


__all__ = ["ControlError", "pause", "resume", "terminate"]
