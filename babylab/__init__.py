"""Shared foundation library for the Baby AI laboratory infrastructure.

Milestone 001 contains no agent, no autonomy, and no learning. This package
provides only deterministic, side-effect-free primitives that the event
store, provenance ledger, observer and control process share.

See docs/architecture.md for the structural rationale.
"""

from babylab.errors import (
    BabyLabError,
    IntegrityError,
    TrustBoundaryViolation,
    ValidationError,
)
from babylab.identity import Actor, Role
from babylab.paths import ProjectPaths, default_paths

__all__ = [
    "BabyLabError",
    "IntegrityError",
    "TrustBoundaryViolation",
    "ValidationError",
    "Actor",
    "Role",
    "ProjectPaths",
    "default_paths",
]

__version__ = "0.1.0"
