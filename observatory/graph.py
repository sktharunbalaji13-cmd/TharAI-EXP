"""The state graph: real relationships only.

What this is not
----------------
It is not a brain picture, and it is not a fixed pipeline diagram. There is a
strong temptation, when building a "cognitive state visualizer", to draw a
head with lobes and connect them prettily, because that is what a reader
expects a brain visualisation to look like. That would be a lie told in
pixels. The scientific literature's central methodological complaint about
brain imagery is precisely that decorative renderings are read as data.

So this graph contains exactly two things:

* nodes, each of which is either a reported state domain, a derived
  observation, or the laboratory infrastructure that recorded the events;
* edges, each of which is either a reported cross-reference between domains, or
  a derivation from events to the state they produced.

Nothing is invented. If the subject reported no relationship between
``memory`` and ``decision``, there is no edge, and the graph says so by being
absent. If the subject has reported nothing at all, the graph is empty and the
renderer says the telemetry is unavailable. An empty graph is a valid, honest
result.

Edge provenance
---------------
Every edge names where it came from:

``reported``
    The subject declared it, in a domain's ``links`` list. The claiming event
    ID is recorded, so a reader can check the claim against the event store.
``derived``
    The Observatory computed it from event ordering, and the event IDs are
    recorded.

An edge is never rendered without one of these. A line on a graph that nobody
can trace is decoration, and decoration is what this project exists to avoid.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Iterable

from events.model import Event
from observatory.model import CognitiveState, EpistemicStatus


class NodeKind(str, enum.Enum):
    """What a node is. ``SUBJECT`` exists for the future, and is never created now."""

    SUBJECT = "SUBJECT"
    DOMAIN = "DOMAIN"
    DERIVED = "DERIVED"
    INFRASTRUCTURE = "INFRASTRUCTURE"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


class EdgeKind(str, enum.Enum):
    """Why an edge exists."""

    REPORTED = "reported"
    DERIVED = "derived"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


@dataclass(frozen=True)
class Node:
    """A single graph node."""

    node_id: str
    kind: NodeKind
    label: str
    status: EpistemicStatus | None = None
    source_event_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "kind": self.kind.value,
            "label": self.label,
            "status": self.status.value if self.status else None,
            "source_event_ids": list(self.source_event_ids),
        }


@dataclass(frozen=True)
class Edge:
    """A relationship between two nodes, with its basis."""

    source: str
    target: str
    kind: EdgeKind
    source_event_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "kind": self.kind.value,
            "source_event_ids": list(self.source_event_ids),
        }


@dataclass
class StateGraph:
    """Nodes and edges built from a state snapshot. Serializable, no rendering."""

    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    #: Domains for which the subject reported no cross-references. Kept so the
    #: renderer can say "no relationships were reported" instead of silently
    #: drawing an isolated node that looks like a rendering failure.
    unreferenced_domains: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.edges and not self.nodes

    def node_count(self) -> int:
        return len(self.nodes)

    def edge_count(self) -> int:
        return len(self.edges)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [self.nodes[k].to_dict() for k in sorted(self.nodes)],
            "edges": [e.to_dict() for e in self.edges],
            "unreferenced_domains": list(self.unreferenced_domains),
        }

    def to_ascii(self, width: int = 72) -> str:
        """A plain-text adjacency listing.

        A listing rather than a box-drawing diagram, on purpose: an adjacency
        listing cannot be misread as a picture of something it is not. It shows
        the actual topology, one real relationship per line.
        """
        if self.is_empty:
            return "(no relationships have been reported)"
        lines = [f"nodes: {len(self.nodes)}  edges: {len(self.edges)}", ""]
        by_node: dict[str, list[Edge]] = {node_id: [] for node_id in self.nodes}
        for edge in self.edges:
            by_node.setdefault(edge.source, []).append(edge)
        for node_id in sorted(self.nodes):
            node = self.nodes[node_id]
            marker = f" [{node.status.value}]" if node.status else ""
            lines.append(f"{node.label} <{node.kind.value}>{marker}")
            outgoing = by_node.get(node_id, [])
            if not outgoing:
                lines.append("    (no outgoing relationships)")
            for edge in outgoing:
                target = self.nodes.get(edge.target)
                target_label = target.label if target else edge.target
                lines.append(f"    --{edge.kind.value}--> {target_label}")
                for event_id in edge.source_event_ids:
                    lines.append(f"        source: {event_id}")
        if self.unreferenced_domains:
            lines.append("")
            lines.append(
                "no relationships were reported for: "
                + ", ".join(self.unreferenced_domains)
            )
        return "\n".join(lines)


def build_graph(state: CognitiveState, events: Iterable[Event] = ()) -> StateGraph:
    """Build a graph from a state snapshot.

    Nodes come from the state's reported domains. Edges come only from
    relationships the subject actually reported in a domain's ``links`` list.
    A link naming a domain that has never been reported is dropped rather than
    drawn to a node we would have to invent, and the dangling reference is left
    visible in the snapshot rather than papered over.
    """
    graph = StateGraph()
    reported = state.reported()
    if not reported:
        return graph

    if state.subject_id:
        graph.nodes["subject"] = Node(
            node_id="subject",
            kind=NodeKind.SUBJECT,
            label=f"SUBJECT {state.subject_id}",
            source_event_ids=(),
        )

    for domain, value in reported.items():
        node_id = f"domain:{domain}"
        graph.nodes[node_id] = Node(
            node_id=node_id,
            kind=NodeKind.DOMAIN,
            label=domain,
            status=value.status,
            source_event_ids=value.source_event_ids,
        )

    referenced: set[str] = set()
    for domain, value in reported.items():
        links = _links_of(value)
        for target_domain in links:
            if target_domain not in reported:
                # Do not invent the other end. The subject referred to
                # something that was never reported; that is a fact about the
                # report, and dropping it silently would hide a discrepancy.
                continue
            graph.edges.append(
                Edge(
                    source=f"domain:{domain}",
                    target=f"domain:{target_domain}",
                    kind=EdgeKind.REPORTED,
                    source_event_ids=value.source_event_ids,
                )
            )
            referenced.add(domain)
            referenced.add(target_domain)

    unreferenced = tuple(sorted(d for d in reported if d not in referenced))
    graph.unreferenced_domains = unreferenced
    return graph


def _links_of(value: Any) -> list[str]:
    """Read reported cross-references off a domain value.

    Convention: a domain's value may carry a ``links`` list naming other
    domains. This is read only from values the subject reported, never
    inferred.
    """
    raw = getattr(value, "value", None)
    if not isinstance(raw, dict):
        return []
    links = raw.get("links")
    if not isinstance(links, list):
        return []
    return [item for item in links if isinstance(item, str) and item]
