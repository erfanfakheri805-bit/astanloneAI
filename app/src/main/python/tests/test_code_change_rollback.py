"""
Tests for agent/code_change_rollback.py - connects an already-applied,
already-tested CODE_CHANGE to the existing rollback mechanism
(self_upgrade/version_system.py's `VersionSystem.rollback_to`,
unchanged), made available on the existing AgentLoop via
`AgentLoop.decide_code_change_rollback` (agent/agent_loop.py,
Prompt 353).

Covers: a successful (PASSED) change requires no rollback and is kept
as-is; a failed (FAILED/TIMEOUT) change is marked rollback_required
and successfully rolled back via the real, unmodified VersionSystem
using the version snapshot created for that change; a rollback
attempt that itself cannot complete (no version, no versions system,
or an unknown version id) is reported as a rollback failure rather
than raising; the change is never automatically retried; and AgentLoop
wiring.

Run directly:
    python -m unittest tests.test_code_change_rollback -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.code_change_rollback import (
    CHANGE_STATUS_KEPT,
    CHANGE_STATUS_ROLLED_BACK,
    CHANGE_STATUS_ROLLBACK_FAILED,
    ALL_CODE_CHANGE_STATUSES,
    ROLLBACK_STATUS_NOT_REQUIRED,
    ROLLBACK_STATUS_SUCCEEDED,
    ROLLBACK_STATUS_FAILED,
    ALL_ROLLBACK_STATUSES,
    build_code_change_rollback_decision,
)
from agent.test_result_evaluation import RESULT_PASSED, RESULT_FAILED, RESULT_TIMEOUT, RESULT_INVALID

from memory.memory_system import MemorySystem
from self_upgrade.version_system import VersionSystem

from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from execution.plan_execution_controller import PlanExecutionController
from agent.agent_loop import AgentLoop


def _new_version_system():
    return VersionSystem(MemorySystem(tempfile.mktemp(suffix=".db")))


class TestSuccessfulChangeNoRollback(unittest.TestCase):
    """Requirement 9: focused test for a successful change with no
    rollback - PASSED keeps the current state untouched."""

    def setUp(self):
        self.target_file = "/tmp/allowed/generated.py"
        self.versions = _new_version_system()
        self.version = self.versions.create_version(
            None, f"code_change:{self.target_file}", snapshot={"x": 1},
        )
        self.before = self.versions.current_version()
        self.result = build_code_change_rollback_decision(
            RESULT_PASSED, self.target_file, self.version, self.versions,
        )

    def test_change_status_kept(self):
        self.assertEqual(self.result["change_status"], CHANGE_STATUS_KEPT)

    def test_rollback_not_required(self):
        self.assertFalse(self.result["rollback_required"])

    def test_rollback_status_not_required(self):
        self.assertEqual(self.result["rollback_status"], ROLLBACK_STATUS_NOT_REQUIRED)

    def test_test_status_and_target_file_reported(self):
        self.assertEqual(self.result["test_status"], RESULT_PASSED)
        self.assertEqual(self.result["target_file"], self.target_file)

    def test_current_version_is_unchanged(self):
        self.assertEqual(self.versions.current_version(), self.before)

    def test_result_has_exactly_the_five_required_fields(self):
        self.assertEqual(
            set(self.result.keys()),
            {"change_status", "test_status", "rollback_required", "rollback_status", "target_file"},
        )


class TestFailedChangeRequiresRollback(unittest.TestCase):
    """Requirement 9: focused test for a failed change requiring
    rollback - FAILED/TIMEOUT marks rollback_required and rolls back
    to the version snapshot created for that change, via the real,
    unmodified VersionSystem.rollback_to."""

    def setUp(self):
        self.target_file = "/tmp/allowed/generated.py"
        self.versions = _new_version_system()
        # A prior good version, then the (bad) change's own snapshot.
        self.good_version = self.versions.create_version(None, "good", snapshot={"good": True})
        self.bad_version = self.versions.create_version(
            None, f"code_change:{self.target_file}", snapshot={"good": False},
        )

    def test_failed_test_status_triggers_rollback(self):
        result = build_code_change_rollback_decision(
            RESULT_FAILED, self.target_file, self.good_version, self.versions,
        )
        self.assertTrue(result["rollback_required"])
        self.assertEqual(result["change_status"], CHANGE_STATUS_ROLLED_BACK)
        self.assertEqual(result["rollback_status"], ROLLBACK_STATUS_SUCCEEDED)
        self.assertEqual(self.versions.current_version()["id"], self.good_version["id"])

    def test_timeout_test_status_triggers_rollback(self):
        result = build_code_change_rollback_decision(
            RESULT_TIMEOUT, self.target_file, self.good_version, self.versions,
        )
        self.assertTrue(result["rollback_required"])
        self.assertEqual(result["change_status"], CHANGE_STATUS_ROLLED_BACK)
        self.assertEqual(result["rollback_status"], ROLLBACK_STATUS_SUCCEEDED)

    def test_rollback_uses_the_version_supplied_for_this_change(self):
        # Rolling back to the *bad* version's own id is honored exactly
        # as asked - this module rolls back to whatever version it is
        # given, never a version it guesses or re-derives itself.
        result = build_code_change_rollback_decision(
            RESULT_FAILED, self.target_file, self.bad_version, self.versions,
        )
        self.assertEqual(result["change_status"], CHANGE_STATUS_ROLLED_BACK)
        self.assertEqual(self.versions.current_version()["id"], self.bad_version["id"])

    def test_test_status_and_target_file_reported(self):
        result = build_code_change_rollback_decision(
            RESULT_FAILED, self.target_file, self.good_version, self.versions,
        )
        self.assertEqual(result["test_status"], RESULT_FAILED)
        self.assertEqual(result["target_file"], self.target_file)


class TestRollbackFailure(unittest.TestCase):
    """Requirement 9: focused test for a rollback failure - the
    rollback attempt itself cannot complete, and this is reported
    rather than raised."""

    def test_missing_versions_system_is_rollback_failed(self):
        result = build_code_change_rollback_decision(
            RESULT_FAILED, "/tmp/allowed/generated.py", {"id": 1}, None,
        )
        self.assertTrue(result["rollback_required"])
        self.assertEqual(result["change_status"], CHANGE_STATUS_ROLLBACK_FAILED)
        self.assertEqual(result["rollback_status"], ROLLBACK_STATUS_FAILED)

    def test_missing_version_is_rollback_failed(self):
        versions = _new_version_system()
        result = build_code_change_rollback_decision(
            RESULT_FAILED, "/tmp/allowed/generated.py", None, versions,
        )
        self.assertEqual(result["change_status"], CHANGE_STATUS_ROLLBACK_FAILED)
        self.assertEqual(result["rollback_status"], ROLLBACK_STATUS_FAILED)

    def test_unknown_version_id_is_rollback_failed(self):
        versions = _new_version_system()
        result = build_code_change_rollback_decision(
            RESULT_TIMEOUT, "/tmp/allowed/generated.py", {"id": 999999}, versions,
        )
        self.assertEqual(result["change_status"], CHANGE_STATUS_ROLLBACK_FAILED)
        self.assertEqual(result["rollback_status"], ROLLBACK_STATUS_FAILED)

    def test_non_dict_version_is_rollback_failed(self):
        versions = _new_version_system()
        result = build_code_change_rollback_decision(
            RESULT_FAILED, "/tmp/allowed/generated.py", "not a version", versions,
        )
        self.assertEqual(result["change_status"], CHANGE_STATUS_ROLLBACK_FAILED)
        self.assertEqual(result["rollback_status"], ROLLBACK_STATUS_FAILED)

    def test_never_raises(self):
        try:
            build_code_change_rollback_decision(None, None, None, None)
        except Exception as exc:  # pragma: no cover - defensive
            self.fail(f"build_code_change_rollback_decision raised: {exc!r}")


class TestNeverRetries(unittest.TestCase):
    """Requirement 6: a failed change is never automatically retried -
    this module never touches anything beyond the five-field result
    and one existing rollback_to call."""

    def test_rejected_test_status_never_reapplies_anything(self):
        versions = _new_version_system()
        version = versions.create_version(None, "v", snapshot={})
        result = build_code_change_rollback_decision(
            RESULT_FAILED, "/tmp/allowed/generated.py", version, versions,
        )
        self.assertNotIn("retry", result)
        self.assertNotIn("proposal", result)
        self.assertEqual(
            set(result.keys()),
            {"change_status", "test_status", "rollback_required", "rollback_status", "target_file"},
        )


class TestFixedVocabularies(unittest.TestCase):
    def test_all_change_statuses(self):
        self.assertEqual(
            ALL_CODE_CHANGE_STATUSES,
            (CHANGE_STATUS_KEPT, CHANGE_STATUS_ROLLED_BACK, CHANGE_STATUS_ROLLBACK_FAILED),
        )

    def test_all_rollback_statuses(self):
        self.assertEqual(
            ALL_ROLLBACK_STATUSES,
            (ROLLBACK_STATUS_NOT_REQUIRED, ROLLBACK_STATUS_SUCCEEDED, ROLLBACK_STATUS_FAILED),
        )

    def test_invalid_test_status_does_not_trigger_rollback(self):
        # Requirement 2 only names PASSED (keep) and FAILED/TIMEOUT
        # (rollback) - an unrelated classification is never treated
        # as requiring a rollback of its own accord.
        result = build_code_change_rollback_decision(
            RESULT_INVALID, "/tmp/allowed/generated.py", {"id": 1}, _new_version_system(),
        )
        self.assertFalse(result["rollback_required"])
        self.assertEqual(result["change_status"], CHANGE_STATUS_KEPT)


class TestAgentLoopDecideCodeChangeRollback(unittest.TestCase):
    """Requirement: make the rollback decision available on the
    existing AgentLoop, without creating a new rollback/version system
    and without retrying the change automatically."""

    def setUp(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        self.versions = _new_version_system()
        self.loop = AgentLoop(goals, plans, controller, version_system=self.versions)

    def test_passed_change_is_kept(self):
        version = self.versions.create_version(None, "v", snapshot={})
        result = self.loop.decide_code_change_rollback(
            RESULT_PASSED, "/tmp/allowed/generated.py", version,
        )
        self.assertEqual(result["change_status"], CHANGE_STATUS_KEPT)
        self.assertFalse(result["rollback_required"])

    def test_failed_change_is_rolled_back_using_loop_version_system(self):
        good_version = self.versions.create_version(None, "good", snapshot={})
        result = self.loop.decide_code_change_rollback(
            RESULT_FAILED, "/tmp/allowed/generated.py", good_version,
        )
        self.assertEqual(result["change_status"], CHANGE_STATUS_ROLLED_BACK)
        self.assertEqual(self.versions.current_version()["id"], good_version["id"])

    def test_explicit_versions_argument_overrides_constructor_one(self):
        other_versions = _new_version_system()
        good_version = other_versions.create_version(None, "good", snapshot={})
        result = self.loop.decide_code_change_rollback(
            RESULT_FAILED, "/tmp/allowed/generated.py", good_version, versions=other_versions,
        )
        self.assertEqual(result["change_status"], CHANGE_STATUS_ROLLED_BACK)
        self.assertEqual(other_versions.current_version()["id"], good_version["id"])

    def test_without_a_version_system_reports_rollback_failed(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        loop = AgentLoop(goals, plans, controller)
        result = loop.decide_code_change_rollback(
            RESULT_FAILED, "/tmp/allowed/generated.py", {"id": 1},
        )
        self.assertEqual(result["change_status"], CHANGE_STATUS_ROLLBACK_FAILED)

    def test_never_touches_a_second_upgrade_or_version_system(self):
        version = self.versions.create_version(None, "v", snapshot={})
        self.loop.decide_code_change_rollback(
            RESULT_FAILED, "/tmp/allowed/generated.py", version,
        )
        self.assertFalse(hasattr(self.loop, "upgrades"))
        # Exactly the one version_system this loop was constructed
        # with - never a second one.
        self.assertIs(self.loop.versions, self.versions)


if __name__ == "__main__":
    unittest.main()
