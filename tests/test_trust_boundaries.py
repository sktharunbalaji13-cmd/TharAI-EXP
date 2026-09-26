"""Trust boundary tests.

READ THIS BEFORE INTERPRETING ANY RESULT IN THIS FILE
-----------------------------------------------------

Everything in this file is an **APPLICATION SECURITY TEST**. It proves that the
Python path policy in :mod:`babylab.trust` refuses the operations it claims to
refuse. It proves *nothing* about operating-system enforcement, because the
tests run as the same OS user that owns the files.

The three tiers, and where each stands
--------------------------------------
============================================  ==========================
TIER                                          STATUS
============================================  ==========================
1. APPLICATION SECURITY TEST                  **VERIFIED** by this file
2. OPERATING SYSTEM SECURITY TEST -
   ACL configuration present and correct      **AUDITABLE**, see
                                              scripts/trust_boundaries.ps1
                                              -Audit
3. OPERATING SYSTEM SECURITY TEST -
   enforcement proven at runtime by a
   second principal being denied               **NOT VERIFIED**
============================================  ==========================

Tier 3 is not verified because Milestone 001 has no second OS principal. The
current shell runs with a filtered (non-elevated) token and cannot create a
local service account, so there is nothing to test enforcement against. See
docs/security-model.md, section "What Is Not Verified, And Why".

Any future claim that "the subject cannot modify human_control" must cite tier
3. Until then, the honest statement is: "the application refuses, and the OS
boundary is defined but not yet active."
"""

from __future__ import annotations

import json
import unittest

from tests import support  # noqa: F401
from tests.support import LabTestCase

from babylab.errors import TrustBoundaryViolation
from babylab.identity import Actor, Role
from babylab.trust import Domain


class PathClassificationTests(LabTestCase):
    def test_human_control_is_its_own_domain(self):
        self.assertIs(
            self.policy.classify(self.paths.human_control / "x"), Domain.HUMAN_CONTROL
        )

    def test_baby_workspace_is_its_own_domain(self):
        self.assertIs(
            self.policy.classify(self.paths.baby_workspace / "x"), Domain.BABY_WORKSPACE
        )

    def test_workspace_domains_do_not_overlap(self):
        human = (self.paths.human_control / "shared").resolve()
        baby = (self.paths.baby_workspace / "shared").resolve()
        self.assertNotEqual(human, baby)
        self.assertIs(self.policy.classify(human), Domain.HUMAN_CONTROL)
        self.assertIs(self.policy.classify(baby), Domain.BABY_WORKSPACE)

    def test_a_nested_workspace_cannot_impersonate_the_other(self):
        """``baby_workspace/x/../human_control`` must not classify as baby."""
        sneaky = self.paths.baby_workspace / "code" / ".." / ".." / "human_control"
        self.assertIs(self.policy.classify(sneaky), Domain.HUMAN_CONTROL)

    def test_research_and_docs_are_human_authored(self):
        self.assertIs(self.policy.classify(self.paths.research / "log.md"), Domain.RESEARCH_DOCS)
        self.assertIs(self.policy.classify(self.paths.docs / "arch.md"), Domain.RESEARCH_DOCS)

    def test_paths_outside_the_project_are_outside_the_policy(self):
        outside = self.root.parent / "somewhere-else.txt"
        self.assertIs(self.policy.classify(outside), Domain.OUTSIDE)

    def test_relative_paths_are_refused_rather_than_guessed(self):
        with self.assertRaises(TrustBoundaryViolation):
            self.policy.classify("human_control/x")

    def test_assert_inside_root_rejects_escapes(self):
        with self.assertRaises(TrustBoundaryViolation):
            self.policy.assert_inside_root(self.root / ".." / "elsewhere")


class BabyWorkspaceSeparationTests(LabTestCase):
    def test_the_two_workspaces_are_distinct_directories(self):
        self.assertNotEqual(
            self.paths.human_control.resolve(),
            self.paths.baby_workspace.resolve(),
        )

    def test_baby_workspace_has_the_five_specified_subdirectories(self):
        for name in ("code", "experiments", "generated", "memory", "temporary"):
            with self.subTest(name=name):
                self.assertTrue((self.paths.baby_workspace / name).is_dir())

    def test_human_control_has_the_five_specified_subdirectories(self):
        for name in (
            "baseline",
            "provenance",
            "experiment_config",
            "research_records",
            "security",
        ):
            with self.subTest(name=name):
                self.assertTrue((self.paths.human_control / name).is_dir())

    def test_baby_workspace_is_empty_of_protected_material(self):
        """Milestone 001 gives the subject nothing to start from."""
        for candidate in self.paths.baby_workspace.rglob("*"):
            if candidate.is_file():
                self.assertEqual(
                    list(candidate.suffixes),
                    [".gitkeep"],
                    f"unexpected file in baby_workspace: {candidate}",
                )

    def test_secret_material_lives_only_in_human_control(self):
        for key_file in self.paths.private_key_dir.glob("*.key"):
            self.assertTrue(
                self.policy.paths.relative(key_file).startswith("human_control/")
            )
        self.assertTrue(self.paths.control_token.exists())
        self.assertTrue(
            self.policy.paths.relative(self.paths.control_token).startswith(
                "human_control/"
            )
        )


class ApplicationWritePolicyTests(LabTestCase):
    """APPLICATION SECURITY TEST. See the module docstring for the tiers."""

    def test_baby_ai_may_write_its_own_workspace(self):
        baby = self.provision_baby_ai()
        self.policy.assert_writable(baby, self.paths.baby_workspace / "code" / "a.py")

    def test_baby_ai_may_not_write_human_control(self):
        baby = self.provision_baby_ai()
        for relative in (
            "human_control/research_records/loot.md",
            "human_control/baseline/BASELINE.json",
            "human_control/experiment_config/control.json",
            "human_control/provenance/HEAD.json",
            "human_control/security/keys/keyring.json",
            "human_control/security/control.token",
        ):
            with self.subTest(relative=relative), self.assertRaises(TrustBoundaryViolation):
                self.policy.assert_writable(baby, self.root / relative)

    def test_baby_ai_may_not_write_the_research_record(self):
        baby = self.provision_baby_ai()
        with self.assertRaises(TrustBoundaryViolation):
            self.policy.assert_writable(baby, self.paths.research / "experiment-log.md")

    def test_baby_ai_may_not_write_the_documentation(self):
        baby = self.provision_baby_ai()
        with self.assertRaises(TrustBoundaryViolation):
            self.policy.assert_writable(baby, self.paths.docs / "architecture.md")

    def test_human_may_write_everything_inside_the_project(self):
        for target in (
            self.paths.human_control / "research_records" / "a.md",
            self.paths.baby_workspace / "code" / "a.py",
            self.paths.research / "experiment-log.md",
            self.paths.docs / "architecture.md",
        ):
            with self.subTest(target=str(target)):
                self.policy.assert_writable(self.human, target)

    def test_system_may_write_human_control_under_its_own_key(self):
        """Infrastructure needs to write seals and snapshots.

        This is why SYSTEM has a key distinct from HUMAN's: otherwise the two
        would be indistinguishable in the ledger.
        """
        self.policy.assert_writable(
            self.system, self.paths.protected_provenance / "HEAD.json"
        )

    def test_nobody_may_write_outside_the_project(self):
        outside = self.root.parent / "elsewhere.txt"
        for actor in (self.human, self.system, self.provision_baby_ai()):
            with self.subTest(actor=actor.actor_id), self.assertRaises(TrustBoundaryViolation):
                self.policy.assert_writable(actor, outside)

    def test_a_denial_message_explains_itself(self):
        """A refusal the operator cannot interpret is a support incident."""
        baby = self.provision_baby_ai()
        with self.assertRaises(TrustBoundaryViolation) as caught:
            self.policy.assert_writable(baby, self.paths.research / "log.md")
        message = str(caught.exception)
        self.assertIn("BABY_AI", message)
        self.assertIn("authored by", message)

    def test_reads_are_not_restricted_and_the_code_says_so(self):
        """Read separation is a different, stronger property. Not claimed."""
        baby = self.provision_baby_ai()
        self.assertIsNone(
            self.policy.assert_readable(baby, self.paths.human_control / "baseline")
        )


class RecorderBoundaryTests(LabTestCase):
    """APPLICATION SECURITY TEST at the layer that actually writes."""

    def test_the_recorder_refuses_a_baby_ai_write_to_human_control(self):
        baby = self.provision_baby_ai()
        target = self.root / "human_control" / "research_records" / "stolen.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.assertRaises(TrustBoundaryViolation):
            self.recorder.record_creation(target, baby, "MILESTONE-001", "try to write")

    def test_a_refused_write_leaves_the_file_untouched(self):
        baby = self.provision_baby_ai()
        target = self.write("human_control/research_records/precious.md", "original")
        with self.assertRaises(TrustBoundaryViolation):
            self.recorder.record_creation(target, baby, "MILESTONE-001", "overwrite")
        self.assertEqual(target.read_text(encoding="utf-8"), "original")

    def test_a_refused_attempt_is_still_recorded(self):
        """An attempt is research data. It must not vanish silently."""
        baby = self.provision_baby_ai()
        target = self.write("human_control/research_records/precious.md", "original")
        with self.assertRaises(TrustBoundaryViolation):
            self.recorder.record_creation(target, baby, "MILESTONE-001", "overwrite")
        latest = self.ledger.latest_for_path("human_control/research_records/precious.md")
        self.assertIsNotNone(latest)
        self.assertEqual(latest.action.value, "DENY")
        self.assertEqual(latest.author, Role.BABY_AI)

    def test_the_denial_entry_keeps_the_chain_intact(self):
        baby = self.provision_baby_ai()
        target = self.write("human_control/research_records/precious.md", "original")
        with self.assertRaises(TrustBoundaryViolation):
            self.recorder.record_creation(target, baby, "MILESTONE-001", "overwrite")
        report = self.ledger.verify()
        self.assertTrue(report.intact, msg=report.problems)

    def test_baby_ai_may_record_in_its_own_workspace(self):
        baby = self.provision_baby_ai()
        target = self.write("baby_workspace/code/first.py", "print('hi')")
        self.recorder.record_creation(target, baby, "MILESTONE-001", "subject wrote code")
        latest = self.ledger.latest_for_path("baby_workspace/code/first.py")
        self.assertIsNotNone(latest)
        self.assertEqual(latest.author, Role.BABY_AI)

    def test_an_actor_without_a_key_cannot_leave_a_signed_record(self):
        """No key means no provenance. Refusing beats writing an unsigned entry."""
        from babylab.errors import ValidationError
        from provenance.ledger import Action

        naked = Actor(role=Role.BABY_AI, actor_id="baby-ai:nokey", key_id=None)
        with self.assertRaises(ValidationError):
            self.ledger.record(
                action=Action.CREATE,
                path="baby_workspace/code/x.py",
                content_sha256="0" * 64,
                size_bytes=1,
                experiment_id="MILESTONE-001",
                reason="unsigned",
                actor=naked,
            )


class LayoutTests(LabTestCase):
    def test_runtime_data_never_lives_in_a_code_directory(self):
        """Guards the mistake that briefly destroyed this project.

        The specification's suggested layout would put ``events/events.jsonl``
        next to ``events/__init__.py``. Deleting the runtime data then silently
        deletes the source. All runtime data therefore lives under ``var/``.
        """
        from babylab.paths import CODE_DIRECTORIES

        for name in CODE_DIRECTORIES:
            directory = self.root / name
            if not directory.is_dir():
                continue
            for candidate in directory.rglob("*"):
                if candidate.is_file():
                    self.assertIn(
                        candidate.suffix,
                        {".py", ".pyc"},
                        f"non-source file in code directory: {candidate}",
                    )

    def test_secret_material_is_excluded_by_gitignore(self):
        text = (support.ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("human_control/security/keys/private/", text)
        self.assertIn("human_control/security/control.token", text)
        self.assertIn("var/", text)

    def test_keyring_public_file_contains_no_secret_material(self):
        import base64

        text = self.paths.keyring.read_text(encoding="utf-8")
        data = json.loads(text)
        for entry in data["keys"]:
            secret = self.keyring.secret(entry["key_id"])
            self.assertNotIn(base64.b64encode(secret).decode("ascii"), text)
            self.assertNotIn(secret.hex(), text)


if __name__ == "__main__":
    unittest.main()
