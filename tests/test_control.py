"""Control process tests.

Covers what the specification requires: the control process starts, it
communicates correctly, and unauthorised access is rejected.

Test tiers
----------
Most of this file is an **APPLICATION SECURITY TEST**: it proves the
authentication logic rejects requests without a valid tag.

The tests that prove a *second, unauthorised process cannot drive the control
plane* are weaker than they look, and the file says so where it matters: a
test running as the same OS user can still read the token file, because that
user owns it. What the tests actually establish is that the token is required
and that its absence is refused and logged. Whether the subject can *read the
token* is an operating-system question answered by
scripts/trust_boundaries.ps1, not here. See docs/security-model.md.
"""

from __future__ import annotations

import socket
import threading
import unittest

from tests import support  # noqa: F401
from tests.support import LabTestCase

from babylab.errors import AuthorizationError, BabyLabError, ValidationError
from control.client import ControlClient
from control.protocol import (
    PROTOCOL_VERSION,
    Operation,
    Request,
    Response,
    State,
    TRANSITIONS,
    build_request,
    new_nonce,
    sign_request,
    verify_request,
)
from control.server import ControlServer, load_token


class ProtocolTests(LabTestCase):
    def test_a_signed_request_verifies(self):
        request = build_request(Operation.PING, self.control_token)
        self.assertTrue(verify_request(self.control_token, request))

    def test_a_request_without_a_tag_is_rejected(self):
        request = Request(op=Operation.PING, nonce=new_nonce())
        self.assertFalse(verify_request(self.control_token, request))
        self.assertEqual(request.auth, "")

    def test_a_request_with_the_wrong_tag_is_rejected(self):
        request = build_request(Operation.PING, b"the wrong token entirely!")
        self.assertFalse(verify_request(self.control_token, request))

    def test_a_tag_does_not_transfer_to_a_different_operation(self):
        """Otherwise a ping authorisation could be replayed as a shutdown."""
        request = build_request(Operation.PING, self.control_token)
        escalated = Request(
            op=Operation.SHUTDOWN, nonce=request.nonce, args={}, auth=request.auth
        )
        self.assertFalse(verify_request(self.control_token, escalated))

    def test_a_tag_does_not_transfer_to_different_arguments(self):
        request = build_request(Operation.SNAPSHOT, self.control_token, {"label": "safe"})
        escalated = Request(
            op=Operation.SNAPSHOT,
            nonce=request.nonce,
            args={"label": "tampered"},
            auth=request.auth,
        )
        self.assertFalse(verify_request(self.control_token, escalated))

    def test_each_request_gets_a_fresh_nonce(self):
        nonces = {build_request(Operation.PING, self.control_token).nonce for _ in range(20)}
        self.assertEqual(len(nonces), 20)

    def test_the_token_itself_never_crosses_the_wire(self):
        import base64

        request = build_request(Operation.PING, self.control_token)
        wire = request.to_json()
        self.assertNotIn(base64.b64encode(self.control_token).decode("ascii"), wire)
        self.assertNotIn(self.control_token.hex(), wire)

    def test_unknown_operations_are_rejected_at_parse_time(self):
        with self.assertRaises(ValidationError):
            Request.from_json('{"op":"self_destruct","nonce":"x"}')

    def test_malformed_frames_are_rejected(self):
        for frame in ("not json", "[]", '{"op":"ping","args":"not an object"}'):
            with self.subTest(frame=frame), self.assertRaises(ValidationError):
                Request.from_json(frame)

    def test_oversized_frames_are_rejected_before_allocation(self):
        with self.assertRaises(ValidationError):
            Request.from_json("{" + "x" * 200000)

    def test_every_state_is_reachable_and_every_target_is_a_known_state(self):
        self.assertEqual(
            set(TRANSITIONS), set(State), "a state has no declared transitions"
        )
        for state, targets in TRANSITIONS.items():
            self.assertTrue(targets, f"{state} is a dead end")
            for target in targets:
                self.assertIn(target, State)

    def test_illegal_transitions_are_refused_by_the_guard(self):
        """The transition table is the enforcement, so it is tested directly."""
        from control.server import ControlServer

        server = ControlServer(paths=self.paths, port=0, clock=self.clock)
        for source, targets in TRANSITIONS.items():
            for target in State:
                server.state = source
                if target in targets:
                    server._transition(target)
                    self.assertEqual(server.state, target)
                else:
                    with self.subTest(source=source, target=target):
                        with self.assertRaises(BabyLabError) as caught:
                            server._transition(target)
                        self.assertIn("illegal control state transition", str(caught.exception))
                    self.assertEqual(server.state, source)

    def test_running_cannot_jump_straight_to_shutdown(self):
        """Shutdown must pass through SHUTTING_DOWN so it is observable."""
        self.assertNotIn(State.SHUTDOWN, TRANSITIONS[State.RUNNING])
        self.assertIn(State.SHUTDOWN, TRANSITIONS[State.SHUTTING_DOWN])


class ServerLifecycleTests(LabTestCase):
    def test_the_server_starts_and_reaches_running(self):
        server = ControlServer(paths=self.paths, port=0, clock=self.clock)
        with server:
            self.assertEqual(server.state, State.RUNNING)
            self.assertGreater(server.port, 0)

    def test_starting_twice_is_refused(self):
        server = ControlServer(paths=self.paths, port=0, clock=self.clock)
        with server:
            with self.assertRaises(BabyLabError):
                server.start()

    def test_starting_emits_an_event(self):
        before = self.store.count()
        with ControlServer(paths=self.paths, port=0, clock=self.clock) as server:
            self.assertGreater(self.store.count(), before)
        types = [event.event_type for event in self.store.iter_events()]
        self.assertIn("control.server.started", types)

    def test_a_missing_token_refuses_to_start(self):
        """No authentication means no control plane, not a lax mode."""
        self.paths.control_token.unlink()
        with self.assertRaises(AuthorizationError):
            ControlServer(paths=self.paths, port=0, clock=self.clock)

    def test_a_corrupt_token_refuses_to_start(self):
        self.paths.control_token.write_text("not base64 !!!", encoding="ascii")
        with self.assertRaises(AuthorizationError):
            ControlServer(paths=self.paths, port=0, clock=self.clock)

    def test_stopping_returns_to_stopped(self):
        server = ControlServer(paths=self.paths, port=0, clock=self.clock)
        server.start()
        server.stop()
        self.assertEqual(server.state, State.STOPPED)


class CommunicationTests(LabTestCase):
    def setUp(self):
        super().setUp()
        self.server = ControlServer(paths=self.paths, port=0, clock=self.clock)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.client = ControlClient(
            paths=self.paths, host="127.0.0.1", port=self.server.port
        )

    def test_an_authorised_client_can_reach_the_server(self):
        response = self.client.ping()
        self.assertTrue(response.ok)
        self.assertTrue(response.result["pong"])

    def test_the_response_carries_the_request_nonce(self):
        response = self.client.status()
        self.assertTrue(response.nonce)

    def test_status_reports_the_lifecycle_state(self):
        response = self.client.status()
        self.assertEqual(response.result["state"], State.RUNNING.value)
        self.assertFalse(response.result["subject_attached"])

    def test_pause_and_resume_change_the_state(self):
        self.assertEqual(self.client.pause().result["state"], State.PAUSED.value)
        self.assertEqual(self.client.resume().result["state"], State.RUNNING.value)

    def test_pause_reports_honestly_that_no_subject_is_attached(self):
        """The laboratory must not pretend an experiment is being controlled."""
        response = self.client.pause()
        self.assertFalse(response.result["subject_attached"])
        self.assertIn("No experimental subject", response.result["note"])
        self.assertIn("No simulated behaviour", response.result["note"])

    def test_inspect_reports_counters_and_paths(self):
        self.client.ping()
        result = self.client.inspect().result
        # The inspect request counts itself, hence >= 1 rather than == 1.
        self.assertGreaterEqual(result["server"]["requests_authorized"], 1)
        self.assertEqual(result["server"]["by_operation"]["ping"], 1)
        self.assertEqual(result["server"]["requests_rejected"], 0)
        self.assertIn("event_store", result["paths"])
        self.assertIn("provenance", result)

    def test_snapshot_writes_a_file_into_human_control(self):
        response = self.client.snapshot(label="unitcheck")
        self.assertTrue(response.ok)
        target = self.root / response.result["path"]
        self.assertTrue(target.exists())
        self.assertTrue(
            response.result["path"].startswith("human_control/snapshots/")
        )

    def test_a_snapshot_is_recorded_in_provenance_under_the_system_key(self):
        """The control process must be distinguishable from the human."""
        response = self.client.snapshot(label="provenance-check")
        entry = self.ledger.latest_for_path(response.result["path"])
        self.assertIsNotNone(entry, "snapshot was not recorded in the ledger")
        self.assertEqual(entry.author.value, "SYSTEM")

    def test_snapshot_emits_an_event(self):
        self.client.snapshot(label="eventcheck")
        types = [event.event_type for event in self.store.iter_events()]
        self.assertIn("control.snapshot.taken", types)

    def test_shutdown_moves_the_server_to_shutdown(self):
        response = self.client.shutdown()
        self.assertTrue(response.ok)
        self.assertEqual(response.result["state"], State.SHUTDOWN.value)

    def test_a_client_with_the_wrong_token_is_refused(self):
        rogue = ControlClient(
            paths=self.paths,
            host="127.0.0.1",
            port=self.server.port,
            token=b"x" * 32,
        )
        response = rogue.ping()
        self.assertFalse(response.ok)
        self.assertEqual(response.error_code, "UNAUTHORIZED")

    def test_a_dead_server_raises_rather_than_lying(self):
        """A connection failure is an error; an authorisation failure is data."""
        orphan = ControlClient(
            paths=self.paths, host="127.0.0.1", port=1, timeout=1.0
        )
        with self.assertRaises(BabyLabError) as caught:
            orphan.ping()
        self.assertIn("cannot reach", str(caught.exception))


class AuthorisationTests(LabTestCase):
    """APPLICATION SECURITY TEST. See the module docstring for the tiers."""

    def setUp(self):
        super().setUp()
        self.server = ControlServer(paths=self.paths, port=0, clock=self.clock)
        self.server.start()
        self.addCleanup(self.server.stop)

    def _raw_send(self, payload: str) -> Response:
        with socket.create_connection(("127.0.0.1", self.server.port), timeout=5) as conn:
            conn.sendall((payload + "\n").encode("utf-8"))
            # Half-close the write side. Without this, a server that rejects a
            # frame early (such as an oversized one) closes while we are still
            # writing, which the stack reports as a connection reset rather
            # than the error response it actually sent.
            conn.shutdown(socket.SHUT_WR)
            buffer = b""
            while b"\n" not in buffer:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buffer += chunk
        line, _ = buffer.split(b"\n", 1)
        return Response.from_json(line.decode("utf-8"))

    def test_an_unauthenticated_shutdown_is_refused(self):
        response = self._raw_send(
            '{"op":"shutdown","nonce":"abc","args":{},"auth":""}'
        )
        self.assertFalse(response.ok)
        self.assertEqual(response.error_code, "UNAUTHORIZED")
        self.assertEqual(self.server.state, State.RUNNING)

    def test_an_unauthenticated_snapshot_is_refused(self):
        response = self._raw_send('{"op":"snapshot","nonce":"abc","args":{}}')
        self.assertFalse(response.ok)
        self.assertEqual(self.server.stats.requests_rejected, 1)

    def test_a_forged_tag_is_refused(self):
        response = self._raw_send(
            '{"op":"pause","nonce":"abc","args":{},"auth":"' + "0" * 64 + '"}'
        )
        self.assertFalse(response.ok)
        self.assertEqual(self.server.state, State.RUNNING)

    def test_a_rejected_request_is_recorded_as_a_security_event(self):
        """Unauthorised attempts are research data, not noise to discard."""
        self._raw_send('{"op":"shutdown","nonce":"abc","args":{},"auth":""}')
        types = [event.event_type for event in self.store.iter_events()]
        self.assertIn("security.control.request_rejected", types)

    def test_the_rejection_event_names_the_attempted_operation(self):
        self._raw_send('{"op":"shutdown","nonce":"abc","args":{},"auth":""}')
        event = next(
            e
            for e in self.store.iter_events()
            if e.event_type == "security.control.request_rejected"
        )
        self.assertEqual(event.payload["operation"], "shutdown")

    def test_a_malformed_frame_is_refused_without_killing_the_server(self):
        response = self._raw_send("this is not json")
        self.assertFalse(response.ok)
        self.assertEqual(response.error_code, "MALFORMED")
        self.assertTrue(
            ControlClient(
                paths=self.paths, host="127.0.0.1", port=self.server.port
            ).ping().ok
        )

    def test_a_wrong_protocol_version_is_refused(self):
        body = {"op": "ping", "nonce": "abc", "args": {}}
        response = self._raw_send(
            '{"protocol":"babylab/control/v999","op":"ping","nonce":"abc",'
            '"args":{},"auth":"'
            + sign_request(self.control_token, body)
            + '"}'
        )
        self.assertFalse(response.ok)
        self.assertEqual(response.error_code, "BAD_PROTOCOL")

    def test_a_correctly_signed_request_is_accepted(self):
        body = {"op": "ping", "nonce": "abc", "args": {}}
        response = self._raw_send(
            '{"protocol":"'
            + PROTOCOL_VERSION
            + '","op":"ping","nonce":"abc","args":{},"auth":"'
            + sign_request(self.control_token, body)
            + '"}'
        )
        self.assertTrue(response.ok)

    def test_an_oversized_frame_is_refused(self):
        response = self._raw_send("{" + "x" * 200000)
        self.assertFalse(response.ok)
        self.assertEqual(response.error_code, "FRAME_TOO_LARGE")

    def test_counters_separate_authorised_from_rejected(self):
        self._raw_send('{"op":"ping","nonce":"a","args":{},"auth":""}')
        self._raw_send('{"op":"ping","nonce":"b","args":{},"auth":""}')
        ControlClient(
            paths=self.paths, host="127.0.0.1", port=self.server.port
        ).ping()
        stats = self.server.stats.to_dict()
        self.assertEqual(stats["requests_rejected"], 2)
        self.assertEqual(stats["requests_authorized"], 1)


class SnapshotLabelTests(LabTestCase):
    """A snapshot label reaches the filesystem, so it must be inert.

    Authenticated is not the same as trusted: a compromised operator client
    must not be able to steer the write out of human_control/.
    """

    def setUp(self):
        super().setUp()
        self.server = ControlServer(paths=self.paths, port=0, clock=self.clock)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.client = ControlClient(
            paths=self.paths, host="127.0.0.1", port=self.server.port
        )

    def test_a_traversal_label_stays_inside_the_snapshots_directory(self):
        for hostile in (
            "../../../../Windows/System32/drivers/etc/pwn",
            "..\\..\\escape",
            "/absolute/path",
            "sub/dir/label",
        ):
            with self.subTest(label=hostile):
                response = self.client.snapshot(label=hostile)
                self.assertTrue(response.ok)
                target = (self.root / response.result["path"]).resolve()
                self.assertTrue(
                    target.is_relative_to(self.paths.snapshots.resolve()),
                    f"{hostile!r} escaped to {target}",
                )
                self.assertTrue(target.exists())

    def test_a_dot_label_falls_back_rather_than_escaping(self):
        response = self.client.snapshot(label="..")
        self.assertTrue(response.ok)
        target = (self.root / response.result["path"]).resolve()
        self.assertEqual(target.parent, self.paths.snapshots.resolve())

    def test_the_requested_label_is_preserved_in_the_body_for_audit(self):
        """Sanitising the filename must not erase what the operator asked for."""
        response = self.client.snapshot(label="../../escape")
        body = __import__("json").loads(
            (self.root / response.result["path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(body["requested_label"], "../../escape")
        self.assertNotEqual(body["label"], body["requested_label"])

    def test_a_normal_label_is_preserved_readably(self):
        response = self.client.snapshot(label="before-run-01")
        self.assertEqual(response.result["label"], "before-run-01")
        self.assertIn("before-run-01", response.result["path"])

    def test_the_label_length_is_bounded(self):
        response = self.client.snapshot(label="x" * 500)
        self.assertTrue(response.ok)
        target = self.root / response.result["path"]
        self.assertLessEqual(len(target.name), 128)

    def test_a_non_string_label_does_not_crash_the_server(self):
        response = self.client.snapshot(label=1234)
        self.assertTrue(response.ok)
        self.assertTrue((self.root / response.result["path"]).exists())

    def test_the_snapshot_is_still_anchored_in_provenance(self):
        response = self.client.snapshot(label="../../escape")
        entry = self.ledger.latest_for_path(response.result["path"])
        self.assertIsNotNone(entry)
        self.assertEqual(entry.author.value, "SYSTEM")

    def test_the_server_still_answers_ping_after_hostile_labels(self):
        self.client.snapshot(label="../../../etc")
        self.assertTrue(self.client.ping().ok)


class TokenLoadingTests(LabTestCase):
    def test_the_token_is_read_from_human_control(self):
        token = load_token(self.paths.control_token)
        self.assertEqual(token, self.control_token)
        self.assertEqual(len(token), 32)

    def test_a_missing_token_is_an_error_not_a_default(self):
        self.paths.control_token.unlink()
        with self.assertRaises(AuthorizationError):
            load_token(self.paths.control_token)

    def test_the_token_lives_inside_the_protected_area(self):
        relative = self.paths.relative(self.paths.control_token)
        self.assertTrue(relative.startswith("human_control/security/"))


if __name__ == "__main__":
    unittest.main()
