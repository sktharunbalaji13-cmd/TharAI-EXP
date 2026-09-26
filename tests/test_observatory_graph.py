"""The relationship graph: real edges only, and honest emptiness.

An empty graph is a valid result. A graph with an invented edge is a failure.
These tests cover both, and specifically cover the case where a subject refers
to something it never reported — the temptation there is to draw the missing
node so the picture looks complete.
"""

from __future__ import annotations

import unittest

from events.model import Event
from observatory.attribution import Attributor
from observatory.derive import StateDeriver
from observatory.graph import EdgeKind, NodeKind, build_graph
from observatory.model import CognitiveState, StateValue
from tests.support import LabTestCase


def subject_event(seq: int, state: dict, namespace: str = "baby") -> Event:
    return Event(
        event_id=f"EVENT-{seq:06d}",
        seq=seq,
        timestamp="2026-01-01T00:00:00.000Z",
        event_type=f"{namespace}.report",
        source="subject.runtime",
        payload={"state": state},
    )


def state_with(**domains) -> CognitiveState:
    return CognitiveState(
        subject_id="baby-ai:subject",
        version=1,
        timestamp="2026-01-01T00:00:00.000Z",
        domains={
            name: StateValue.observed(name, value, ("EVENT-000001",))
            for name, value in domains.items()
        },
    )


class EmptyGraphTests(unittest.TestCase):
    def test_no_state_gives_an_empty_graph(self) -> None:
        self.assertTrue(build_graph(CognitiveState.empty()).is_empty)

    def test_empty_graph_says_so_in_text(self) -> None:
        self.assertIn("no relationships", build_graph(CognitiveState.empty()).to_ascii())

    def test_state_with_no_links_produces_no_edges(self) -> None:
        graph = build_graph(state_with(memory={"count": 1}))
        self.assertEqual(graph.edge_count(), 0)
        # The subject node plus the one reported domain. Nothing else.
        self.assertEqual(graph.node_count(), 2)
        self.assertEqual(graph.unreferenced_domains, ("memory",))

    def test_empty_graph_serialises(self) -> None:
        data = build_graph(CognitiveState.empty()).to_dict()
        self.assertEqual(data["nodes"], [])
        self.assertEqual(data["edges"], [])


class ReportedLinkTests(unittest.TestCase):
    def test_reported_link_becomes_an_edge(self) -> None:
        state = state_with(
            perception={"summary": "a wall"},
            decision={"choice": "look left", "links": ["perception"]},
        )
        graph = build_graph(state)
        self.assertEqual(graph.edge_count(), 1)
        edge = graph.edges[0]
        self.assertEqual(edge.source, "domain:decision")
        self.assertEqual(edge.target, "domain:perception")
        self.assertIs(edge.kind, EdgeKind.REPORTED)

    def test_every_edge_cites_its_source_event(self) -> None:
        state = state_with(
            perception={"summary": "a wall"},
            decision={"choice": "look left", "links": ["perception"]},
        )
        graph = build_graph(state)
        for edge in graph.edges:
            self.assertTrue(edge.source_event_ids)

    def test_node_carries_status_and_source(self) -> None:
        graph = build_graph(state_with(memory={"count": 1}))
        node = graph.nodes["domain:memory"]
        self.assertIs(node.kind, NodeKind.DOMAIN)
        self.assertEqual(node.source_event_ids, ("EVENT-000001",))

    def test_subject_node_exists_when_a_subject_is_attached(self) -> None:
        graph = build_graph(state_with(memory={"count": 1}))
        self.assertIn("subject", graph.nodes)
        self.assertIs(graph.nodes["subject"].kind, NodeKind.SUBJECT)

    def test_referenced_domains_are_not_listed_as_unreferenced(self) -> None:
        state = state_with(
            perception={"summary": "a wall"},
            decision={"choice": "look left", "links": ["perception"]},
        )
        self.assertEqual(build_graph(state).unreferenced_domains, ())

    def test_link_to_an_unreported_domain_is_not_drawn(self) -> None:
        # The subject referred to something it never reported. We do not invent
        # the other end just to make the picture look complete.
        state = state_with(decision={"choice": "look left", "links": ["memory"]})
        graph = build_graph(state)
        self.assertEqual(graph.edge_count(), 0)
        self.assertNotIn("domain:memory", graph.nodes)
        self.assertEqual(graph.unreferenced_domains, ("decision",))

    def test_non_dict_domain_value_has_no_links(self) -> None:
        self.assertEqual(build_graph(state_with(memory=[1, 2, 3])).edge_count(), 0)

    def test_links_of_wrong_type_are_ignored(self) -> None:
        state = state_with(
            perception={"summary": "a wall"},
            decision={"links": "perception"},
        )
        self.assertEqual(build_graph(state).edge_count(), 0)

    def test_ascii_listing_names_each_edge_and_its_source(self) -> None:
        state = state_with(
            perception={"summary": "a wall"},
            decision={"choice": "look left", "links": ["perception"]},
        )
        text = build_graph(state).to_ascii()
        self.assertIn("reported", text)
        self.assertIn("EVENT-000001", text)
        self.assertIn("perception", text)

    def test_ascii_marks_domains_with_no_outgoing_edges(self) -> None:
        text = build_graph(state_with(memory={"count": 1})).to_ascii()
        self.assertIn("no outgoing relationships", text)

    def test_graph_serialises(self) -> None:
        state = state_with(
            perception={"summary": "a wall"},
            decision={"choice": "look left", "links": ["perception"]},
        )
        data = build_graph(state).to_dict()
        self.assertEqual(len(data["nodes"]), 3)
        self.assertEqual(len(data["edges"]), 1)
        self.assertEqual(data["edges"][0]["kind"], "reported")


class GraphHasNoFixedPipelineTests(LabTestCase):
    """The pipeline perception -> memory -> ... must not be assumed."""

    def setUp(self) -> None:
        super().setUp()
        self.provision_baby_ai("baby-ai:subject")
        self.deriver = StateDeriver(
            attributor=Attributor(
                subject_namespace=frozenset({"baby"}), subject_label="SUBJECT"
            ),
            subject_id="baby-ai:subject",
            clock=self.clock,
        )

    def test_a_single_reported_domain_yields_one_node(self) -> None:
        self.deriver.apply(subject_event(1, {"tooling": {"editor": "open"}}))
        state = self.deriver.snapshot(self.clock.now())
        graph = build_graph(state)
        # No perception, no memory, no action invented around the one real fact.
        self.assertEqual(graph.edge_count(), 0)
        self.assertIn("domain:tooling", graph.nodes)
        self.assertNotIn("domain:memory", graph.nodes)
        self.assertNotIn("domain:perception", graph.nodes)

    def test_domains_outside_the_conventional_list_are_still_shown(self) -> None:
        self.deriver.apply(subject_event(1, {"zzz_unknown_domain": 7}))
        state = self.deriver.snapshot(self.clock.now())
        self.assertIn("zzz_unknown_domain", state.reported())
        self.assertIn("domain:zzz_unknown_domain", build_graph(state).nodes)


if __name__ == "__main__":
    unittest.main()
