"""Terminal observer: a read-only view of the event stream.

The observer is deliberately incapable of influencing the experiment. It has
no write path into the event log, no provenance signing key, and no control
operations. See docs/architecture.md, "Why the observer is read-only".
"""

from observer.format import RenderOptions, Renderer, category_of, short_time
from observer.terminal import ObserverStats, TerminalObserver

__all__ = [
    "TerminalObserver",
    "ObserverStats",
    "Renderer",
    "RenderOptions",
    "category_of",
    "short_time",
]
