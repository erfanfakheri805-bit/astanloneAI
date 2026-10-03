"""
Tests for agent/code_change_version_snapshot.py - connects an
already-READY CODE_CHANGE Self-Upgrade readiness check (agent/
code_change_self_upgrade_validation.py, Prompt 350) to the existing
Self-Upgrade Version System (self_upgrade/version_system.py's
`VersionSystem`, unchanged), made available on the existing AgentLoop
via `AgentLoop.snapshot_self_upgrade_version` (agent/agent_loop.py,
Prompt 352).

Covers: a snapshot is created (via the real, unmodified VersionSystem)
for a READY change and carries the required metadata; a REJECTED
change (failed validation, failed test, or failed application) never
creates a version snapshot; the snapshot is created without advancing
any upgrade to "installed" and without deactivating rollback history;
AgentLoop wiring, including the `version_system=` constructor
injection and the existing "no version system unless explicitly
given" contract from Prompt 350's own test suite.

Run directly:
    python -m unittest tests.test_code_change_version_snapshot -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.code_change_version_snapshot import (
    CHANGE_TYPE_CODE_CHANGE,
    SNAPSHOT_STATUS_CREATED,
    SNAPSHOT_STATUS_SKIPPED,
    ALL_CODE_CHANGE_SNAPSHOT_STATUSES,
    build_code_change_version_snapshot,
)
from agent.code_change_self_upgrade_validation import (
    STATUS_READY,
    STATUS_REJECTED,
    build_code_change_self_upgrade_readiness,
)
from agent.code_change_self_upgrade_audit import build_code_change_audit_record
from agent.code_correction_proposal import STATUS_PROPOSED
from agent.code_error_analysis import ERROR_TYPE_NAME
from agent.code_correction_proposal_validation import (
    VALIDATION_STATUS_VALID,
    VALIDATION_STATUS_INVALID,
)
from agent.code_correction_application import (
    STATUS_APPLIED,
    STATUS_NOT_READY as APPLICATION_STATUS_NOT_READY,
)
from agent.test_result_evaluation import RESULT_PASSED, RESULT_FAILED

from memory.memory_system import MemorySystem
from self_upgrade.version_system import VersionSystem

from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from execution.plan_execution_controller import PlanExecutionController
from agent.agent_loop import AgentLoop


def _proposal(target_file, status=STATUS_PROPOSED):
    return {
        "target_file": target_file,
        "error_type": ERROR_TYPE_NAME,
        "reason": "NameError detected",
        "change_description": "Define the missing name.",
        "status": status,
        "ready_to_apply": False,
        "apply_capability": "code_change_plan",
        "learned_patterns": [],
        "learned_pattern_used": False,
    }


def _validation_result(target_file, status=VALIDATION_STATUS_VALID, is_safe_to_apply=True, reason="valid"):
    return {
        "status": status,
        "target_file": target_file,
        "reason": reason,
        "is_safe_to_apply": is_safe_to_apply,
    }


def _application(target_file, status=STATUS_APPLIED, changed=True, error=None):
    return {
        "status": status,
        "target_file": target_file,
        "changed": changed,
        "error": error,
    }


def _correction_result(proposal, validation_result, application):
    return {
        "proposal": proposal,
        "validation_result": validation_result,
        "application": application,
    }


def _ready_correction_result(target_file):
    return _correction_result(
        _proposal(target_file), _validation_result(target_file), _application(target_file),
    )


def _rejected_correction_result(target_file):
    return _correction_result(
        _proposal(target_file),
        _validation_result(
            target_file, status=VALIDATION_STATUS_INVALID, is_safe_to_apply=False,
            reason="The proposal does not include error information.",
        ),
        _application(target_file, status="REJECTED", changed=False),
    )


def _new_version_system():
    return VersionSystem(MemorySystem(tempfile.mktemp(suffix=".db")))


class TestSuccessfulSnapshotCreation(unittest.TestCase):
    """Requirement 9: focused test for successful snapshot creation on
    an already-READY change, via the real, unmodified VersionSystem."""

    def setUp(self):
        self.target_file = "/tmp/allowed/generated.py"
        self.correction_result = _ready_correction_result(self.target_file)
        self.readiness_result = build_code_change_self_upgrade_readiness(
            self.correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        self.audit_record = build_code_change_audit_record(
            self.correction_result, "undefined_name", "42", RESULT_PASSED, self.readiness_result,
        )
        self.versions = _new_version_system()
        self.result = build_code_change_version_snapshot(
            self.correction_result, RESULT_PASSED, self.readiness_result,
            self.audit_record, self.versions,
        )

    def test_readiness_is_ready(self):
        self.assertEqual(self.readiness_result["status"], STATUS_READY)

    def test_snapshot_status_created(self):
        self.assertEqual(self.result["status"], SNAPSHOT_STATUS_CREATED)

    def test_snapshot_target_file(self):
        self.assertEqual(self.result["target_file"], self.target_file)

    def test_snapshot_version_is_the_real_versionsystem_row(self):
        self.assertIsNotNone(self.result["version"])
        self.assertEqual(self.result["version"], self.versions.current_version())

    def test_snapshot_metadata_preserves_required_fields(self):
        import json
        stored = json.loads(self.result["version"]["snapshot"])
        self.assertEqual(stored["target_file"], self.target_file)
        self.assertEqual(stored["change_type"], CHANGE_TYPE_CODE_CHANGE)
        self.assertEqual(stored["test_status"], RESULT_PASSED)
        self.assertEqual(stored["validation_status"], VALIDATION_STATUS_VALID)
        self.assertEqual(stored["audit_record"], self.audit_record)

    def test_snapshot_is_not_tied_to_an_upgrade_record(self):
        # No upgrade_id - this snapshot never went through
        # UpgradeSystem.propose_upgrade's own install/upgrade lifecycle.
        self.assertIsNone(self.result["version"]["upgrade_id"])


class TestRejectedChangeNeverSnapshotted(unittest.TestCase):
    """Requirement 8: if validation or testing fails, do not create a
    successful version snapshot."""

    def setUp(self):
        self.versions = _new_version_system()

    def test_failed_validation_is_skipped(self):
        target_file = "/tmp/allowed/generated.py"
        correction_result = _rejected_correction_result(target_file)
        readiness_result = build_code_change_self_upgrade_readiness(
            correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        self.assertEqual(readiness_result["status"], STATUS_REJECTED)
        before = self.versions.current_version()
        result = build_code_change_version_snapshot(
            correction_result, RESULT_PASSED, readiness_result, None, self.versions,
        )
        self.assertEqual(result["status"], SNAPSHOT_STATUS_SKIPPED)
        self.assertIsNone(result["version"])
        self.assertEqual(self.versions.current_version(), before)

    def test_failed_test_is_skipped(self):
        target_file = "/tmp/allowed/generated.py"
        correction_result = _ready_correction_result(target_file)
        readiness_result = build_code_change_self_upgrade_readiness(
            correction_result, "undefined_name", "42", RESULT_FAILED,
        )
        self.assertEqual(readiness_result["status"], STATUS_REJECTED)
        before = self.versions.current_version()
        result = build_code_change_version_snapshot(
            correction_result, RESULT_FAILED, readiness_result, None, self.versions,
        )
        self.assertEqual(result["status"], SNAPSHOT_STATUS_SKIPPED)
        self.assertIsNone(result["version"])
        self.assertEqual(self.versions.current_version(), before)

    def test_change_not_applied_is_skipped(self):
        target_file = "/tmp/allowed/generated.py"
        correction_result = _correction_result(
            _proposal(target_file),
            _validation_result(target_file),
            _application(
                target_file, status=APPLICATION_STATUS_NOT_READY, changed=False,
                error="The correction could not be applied.",
            ),
        )
        readiness_result = build_code_change_self_upgrade_readiness(
            correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        before = self.versions.current_version()
        result = build_code_change_version_snapshot(
            correction_result, RESULT_PASSED, readiness_result, None, self.versions,
        )
        self.assertEqual(result["status"], SNAPSHOT_STATUS_SKIPPED)
        self.assertEqual(self.versions.current_version(), before)

    def test_reason_reuses_readiness_reason(self):
        target_file = "/tmp/allowed/generated.py"
        correction_result = _ready_correction_result(target_file)
        readiness_result = build_code_change_self_upgrade_readiness(
            correction_result, "undefined_name", "42", RESULT_FAILED,
        )
        result = build_code_change_version_snapshot(
            correction_result, RESULT_FAILED, readiness_result, None, self.versions,
        )
        self.assertEqual(result["reason"], readiness_result["reason"])


class TestSnapshotPreservesRollbackFunctionality(unittest.TestCase):
    """Requirement 7: existing rollback functionality is untouched -
    a snapshot created this way can still be rolled back to/from using
    VersionSystem's own, unmodified rollback_to/history/current_version."""

    def test_history_and_rollback_still_work_around_a_code_change_snapshot(self):
        target_file = "/tmp/allowed/generated.py"
        versions = _new_version_system()

        # An unrelated, pre-existing version (e.g. from a normal
        # UpgradeSystem upgrade) already active.
        first_version = versions.create_version(None, "upgrade-1", snapshot={"x": 1})
        history_before = versions.history()

        correction_result = _ready_correction_result(target_file)
        readiness_result = build_code_change_self_upgrade_readiness(
            correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        result = build_code_change_version_snapshot(
            correction_result, RESULT_PASSED, readiness_result, None, versions,
        )
        self.assertEqual(result["status"], SNAPSHOT_STATUS_CREATED)

        # The new snapshot is now active, and history/rollback both
        # still work exactly as VersionSystem itself already defines.
        self.assertEqual(versions.current_version()["id"], result["version"]["id"])
        history_after = versions.history()
        self.assertEqual(len(history_after), len(history_before) + 1)

        rolled_back = versions.rollback_to(first_version["id"])
        self.assertEqual(rolled_back["id"], first_version["id"])
        self.assertEqual(versions.current_version()["id"], first_version["id"])


class TestBuildCodeChangeVersionSnapshotNeverRaises(unittest.TestCase):
    def test_none_readiness_result(self):
        result = build_code_change_version_snapshot({}, RESULT_PASSED, None, None, _new_version_system())
        self.assertEqual(result["status"], SNAPSHOT_STATUS_SKIPPED)

    def test_missing_version_system_on_a_ready_change(self):
        target_file = "/tmp/allowed/generated.py"
        correction_result = _ready_correction_result(target_file)
        readiness_result = build_code_change_self_upgrade_readiness(
            correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        result = build_code_change_version_snapshot(
            correction_result, RESULT_PASSED, readiness_result, None, None,
        )
        self.assertEqual(result["status"], SNAPSHOT_STATUS_SKIPPED)
        self.assertIsNone(result["version"])

    def test_all_snapshot_statuses_fixed_two_way_vocabulary(self):
        self.assertEqual(
            ALL_CODE_CHANGE_SNAPSHOT_STATUSES, (SNAPSHOT_STATUS_CREATED, SNAPSHOT_STATUS_SKIPPED),
        )


class TestAgentLoopSnapshotSelfUpgradeVersion(unittest.TestCase):
    """Requirement: make the version-snapshot step available on the
    existing AgentLoop, without creating a new version-management
    system and without installing/activating anything automatically."""

    def setUp(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        self.versions = _new_version_system()
        self.loop = AgentLoop(goals, plans, controller, version_system=self.versions)

    def test_creates_a_snapshot_for_a_ready_change(self):
        target_file = "/tmp/allowed/generated.py"
        correction_result = _ready_correction_result(target_file)
        readiness_result = self.loop.evaluate_self_upgrade_readiness(
            correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        result = self.loop.snapshot_self_upgrade_version(
            correction_result, RESULT_PASSED, readiness_result,
        )
        self.assertEqual(result["status"], SNAPSHOT_STATUS_CREATED)
        self.assertEqual(self.versions.current_version()["id"], result["version"]["id"])

    def test_skips_a_rejected_change(self):
        target_file = "/tmp/allowed/generated.py"
        correction_result = _rejected_correction_result(target_file)
        readiness_result = self.loop.evaluate_self_upgrade_readiness(
            correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        before = self.versions.current_version()
        result = self.loop.snapshot_self_upgrade_version(
            correction_result, RESULT_PASSED, readiness_result,
        )
        self.assertEqual(result["status"], SNAPSHOT_STATUS_SKIPPED)
        self.assertEqual(self.versions.current_version(), before)

    def test_explicit_versions_argument_overrides_constructor_one(self):
        other_versions = _new_version_system()
        target_file = "/tmp/allowed/generated.py"
        correction_result = _ready_correction_result(target_file)
        readiness_result = self.loop.evaluate_self_upgrade_readiness(
            correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        before = self.versions.current_version()
        result = self.loop.snapshot_self_upgrade_version(
            correction_result, RESULT_PASSED, readiness_result, versions=other_versions,
        )
        self.assertEqual(result["status"], SNAPSHOT_STATUS_CREATED)
        self.assertEqual(self.versions.current_version(), before)
        self.assertEqual(other_versions.current_version()["id"], result["version"]["id"])

    def test_rejects_non_versionsystem_instance(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        with self.assertRaises(TypeError):
            AgentLoop(goals, plans, controller, version_system="not a version system")


class TestAgentLoopWithoutVersionSystemStillSkipsSafely(unittest.TestCase):
    """A plain AgentLoop (no version_system= supplied) must never
    fabricate its own VersionSystem, and must preserve the existing
    Prompt-350 contract that `hasattr(loop, "versions")` is False."""

    def setUp(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        self.loop = AgentLoop(goals, plans, controller)

    def test_no_versions_attribute_by_default(self):
        self.assertFalse(hasattr(self.loop, "versions"))

    def test_snapshot_is_skipped_without_a_version_system(self):
        target_file = "/tmp/allowed/generated.py"
        correction_result = _ready_correction_result(target_file)
        readiness_result = self.loop.evaluate_self_upgrade_readiness(
            correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        result = self.loop.snapshot_self_upgrade_version(
            correction_result, RESULT_PASSED, readiness_result,
        )
        self.assertEqual(result["status"], SNAPSHOT_STATUS_SKIPPED)

    def test_never_creates_an_upgrade_or_version_system_of_its_own(self):
        self.assertFalse(hasattr(self.loop, "upgrades"))
        self.assertFalse(hasattr(self.loop, "versions"))


if __name__ == "__main__":
    unittest.main()
