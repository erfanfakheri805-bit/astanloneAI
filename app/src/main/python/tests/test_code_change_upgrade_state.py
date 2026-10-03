"""
Tests for agent/code_change_upgrade_state.py - a small, deterministic
IDLE/IN_PROGRESS/COMPLETED/FAILED/ROLLED_BACK/REJECTED state model
tracking one CODE_CHANGE self-upgrade at a time on top of the existing
Unified Code Upgrade Result (agent/code_change_upgrade_result.py,
Prompt 354, unchanged), made available on the existing AgentLoop via
`AgentLoop.get_upgrade_state()`/`AgentLoop.start_code_change_upgrade()`
(agent/agent_loop.py, Prompt 356).

Covers: the initial state is IDLE; starting an upgrade moves it to
IN_PROGRESS; a second start attempt while IN_PROGRESS is refused and
leaves the state unchanged; each of the four terminal states is
reached deterministically from the matching `final_status`
(SUCCESS -> COMPLETED, FAILED -> FAILED, ROLLED_BACK -> ROLLED_BACK,
REJECTED -> REJECTED) via `AgentLoop.build_code_change_upgrade_result`;
a new upgrade may start again from any terminal state; nothing here
automatically starts or retries an upgrade; never raises on malformed
input; and that no second AgentLoop/state system is created.

Run directly:
    python -m unittest tests.test_code_change_upgrade_state -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.code_change_upgrade_state import (
    STATE_IDLE,
    STATE_IN_PROGRESS,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_ROLLED_BACK,
    STATE_REJECTED,
    ALL_CODE_CHANGE_UPGRADE_STATES,
    can_start_upgrade,
    next_upgrade_state_from_result,
)
from agent.code_change_upgrade_result import (
    FINAL_STATUS_SUCCESS,
    FINAL_STATUS_FAILED,
    FINAL_STATUS_ROLLED_BACK,
    FINAL_STATUS_REJECTED,
    build_code_change_upgrade_result,
)
from agent.code_change_self_upgrade_validation import (
    build_code_change_self_upgrade_readiness,
)
from agent.code_change_version_snapshot import build_code_change_version_snapshot
from agent.code_change_rollback import build_code_change_rollback_decision
from agent.code_correction_proposal import STATUS_PROPOSED
from agent.code_error_analysis import ERROR_TYPE_NAME
from agent.code_correction_proposal_validation import (
    VALIDATION_STATUS_VALID,
    VALIDATION_STATUS_INVALID,
)
from agent.code_correction_application import STATUS_APPLIED
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


def _new_version_system():
    return VersionSystem(MemorySystem(tempfile.mktemp(suffix=".db")))


def _new_loop(versions=None):
    goals = GoalManager()
    plans = PlanManager(goals)
    controller = PlanExecutionController(plans)
    if versions is not None:
        return AgentLoop(goals, plans, controller, version_system=versions)
    return AgentLoop(goals, plans, controller)


class TestFixedVocabulary(unittest.TestCase):
    def test_all_states(self):
        self.assertEqual(
            ALL_CODE_CHANGE_UPGRADE_STATES,
            (STATE_IDLE, STATE_IN_PROGRESS, STATE_COMPLETED, STATE_FAILED, STATE_ROLLED_BACK, STATE_REJECTED),
        )


class TestCanStartUpgrade(unittest.TestCase):
    """Requirement 5: only IN_PROGRESS blocks a new upgrade."""

    def test_idle_can_start(self):
        self.assertTrue(can_start_upgrade(STATE_IDLE))

    def test_in_progress_cannot_start(self):
        self.assertFalse(can_start_upgrade(STATE_IN_PROGRESS))

    def test_each_terminal_state_can_start(self):
        for state in (STATE_COMPLETED, STATE_FAILED, STATE_ROLLED_BACK, STATE_REJECTED):
            self.assertTrue(can_start_upgrade(state), f"{state} should allow a new upgrade to start")


class TestNextUpgradeStateFromResult(unittest.TestCase):
    """Requirement 3: deterministic transition from a Unified Code
    Upgrade Result's own final_status."""

    def test_success_maps_to_completed(self):
        self.assertEqual(
            next_upgrade_state_from_result({"final_status": FINAL_STATUS_SUCCESS}), STATE_COMPLETED,
        )

    def test_failed_maps_to_failed(self):
        self.assertEqual(
            next_upgrade_state_from_result({"final_status": FINAL_STATUS_FAILED}), STATE_FAILED,
        )

    def test_rolled_back_maps_to_rolled_back(self):
        self.assertEqual(
            next_upgrade_state_from_result({"final_status": FINAL_STATUS_ROLLED_BACK}), STATE_ROLLED_BACK,
        )

    def test_rejected_maps_to_rejected(self):
        self.assertEqual(
            next_upgrade_state_from_result({"final_status": FINAL_STATUS_REJECTED}), STATE_REJECTED,
        )

    def test_malformed_result_leaves_current_state_unchanged(self):
        self.assertEqual(next_upgrade_state_from_result(None, STATE_IN_PROGRESS), STATE_IN_PROGRESS)
        self.assertEqual(next_upgrade_state_from_result({}, STATE_IN_PROGRESS), STATE_IN_PROGRESS)
        self.assertEqual(
            next_upgrade_state_from_result({"final_status": "NOT_A_REAL_STATUS"}, STATE_COMPLETED),
            STATE_COMPLETED,
        )

    def test_default_current_state_is_idle(self):
        self.assertEqual(next_upgrade_state_from_result({}), STATE_IDLE)

    def test_never_raises(self):
        try:
            next_upgrade_state_from_result(object(), STATE_IDLE)
        except Exception as exc:  # pragma: no cover - defensive
            self.fail(f"next_upgrade_state_from_result raised: {exc!r}")


class TestAgentLoopInitialState(unittest.TestCase):
    def test_initial_state_is_idle(self):
        loop = _new_loop()
        self.assertEqual(loop.get_upgrade_state(), STATE_IDLE)


class TestAgentLoopStartCodeChangeUpgrade(unittest.TestCase):
    """Requirement 5, 6: starting an upgrade moves IDLE -> IN_PROGRESS;
    a second start while IN_PROGRESS is refused; starting is always an
    explicit call, never triggered automatically."""

    def setUp(self):
        self.loop = _new_loop()

    def test_start_from_idle_succeeds(self):
        result = self.loop.start_code_change_upgrade()
        self.assertTrue(result["started"])
        self.assertEqual(result["state"], STATE_IN_PROGRESS)
        self.assertEqual(self.loop.get_upgrade_state(), STATE_IN_PROGRESS)

    def test_second_start_while_in_progress_is_refused(self):
        self.loop.start_code_change_upgrade()
        result = self.loop.start_code_change_upgrade()
        self.assertFalse(result["started"])
        self.assertEqual(result["state"], STATE_IN_PROGRESS)
        # State is unaffected by the refused attempt.
        self.assertEqual(self.loop.get_upgrade_state(), STATE_IN_PROGRESS)

    def test_start_never_calls_any_correction_or_upgrade_method(self):
        # A fresh loop with no correction machinery wired at all must
        # still be able to start - this method touches nothing beyond
        # its own state.
        self.loop.start_code_change_upgrade()
        self.assertEqual(self.loop.get_upgrade_state(), STATE_IN_PROGRESS)


class TestAgentLoopReceivesUpgradeResult(unittest.TestCase):
    """Requirement 3: receiving a Unified Code Upgrade Result via
    `build_code_change_upgrade_result` deterministically advances this
    loop's own upgrade state to the matching terminal state."""

    def setUp(self):
        self.target_file = "/tmp/allowed/generated.py"
        self.versions = _new_version_system()
        self.loop = _new_loop(self.versions)
        self.correction_result = _correction_result(
            _proposal(self.target_file), _validation_result(self.target_file), _application(self.target_file),
        )
        self.loop.start_code_change_upgrade()

    def test_success_result_moves_state_to_completed(self):
        readiness_result = self.loop.evaluate_self_upgrade_readiness(
            self.correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        snapshot_result = self.loop.snapshot_self_upgrade_version(
            self.correction_result, RESULT_PASSED, readiness_result,
        )
        rollback_result = self.loop.decide_code_change_rollback(
            RESULT_PASSED, self.target_file, snapshot_result["version"],
        )
        result = self.loop.build_code_change_upgrade_result(
            self.correction_result, readiness_result, snapshot_result, rollback_result,
        )
        self.assertEqual(result["final_status"], FINAL_STATUS_SUCCESS)
        self.assertEqual(self.loop.get_upgrade_state(), STATE_COMPLETED)

    def test_rolled_back_result_moves_state_to_rolled_back(self):
        good_version = self.versions.create_version(None, "good", snapshot={})
        readiness_result = self.loop.evaluate_self_upgrade_readiness(
            self.correction_result, "undefined_name", "42", RESULT_FAILED,
        )
        snapshot_result = self.loop.snapshot_self_upgrade_version(
            self.correction_result, RESULT_FAILED, readiness_result,
        )
        rollback_result = self.loop.decide_code_change_rollback(
            RESULT_FAILED, self.target_file, good_version,
        )
        result = self.loop.build_code_change_upgrade_result(
            self.correction_result, readiness_result, snapshot_result, rollback_result,
        )
        self.assertEqual(result["final_status"], FINAL_STATUS_ROLLED_BACK)
        self.assertEqual(self.loop.get_upgrade_state(), STATE_ROLLED_BACK)

    def test_failed_result_moves_state_to_failed(self):
        readiness_result = self.loop.evaluate_self_upgrade_readiness(
            self.correction_result, "undefined_name", "42", RESULT_FAILED,
        )
        snapshot_result = self.loop.snapshot_self_upgrade_version(
            self.correction_result, RESULT_FAILED, readiness_result,
        )
        # No version supplied for the rollback target -> the required
        # rollback cannot complete -> ROLLBACK_FAILED -> FAILED.
        rollback_result = self.loop.decide_code_change_rollback(
            RESULT_FAILED, self.target_file, None,
        )
        result = self.loop.build_code_change_upgrade_result(
            self.correction_result, readiness_result, snapshot_result, rollback_result,
        )
        self.assertEqual(result["final_status"], FINAL_STATUS_FAILED)
        self.assertEqual(self.loop.get_upgrade_state(), STATE_FAILED)

    def test_rejected_result_moves_state_to_rejected(self):
        rejected_correction_result = _correction_result(
            _proposal(self.target_file),
            _validation_result(
                self.target_file, status=VALIDATION_STATUS_INVALID, is_safe_to_apply=False, reason="unsafe",
            ),
            _application(self.target_file, status=STATUS_APPLIED, changed=False),
        )
        readiness_result = self.loop.evaluate_self_upgrade_readiness(
            rejected_correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        snapshot_result = self.loop.snapshot_self_upgrade_version(
            rejected_correction_result, RESULT_PASSED, readiness_result,
        )
        rollback_result = self.loop.decide_code_change_rollback(
            RESULT_PASSED, self.target_file, None,
        )
        result = self.loop.build_code_change_upgrade_result(
            rejected_correction_result, readiness_result, snapshot_result, rollback_result,
        )
        self.assertEqual(result["final_status"], FINAL_STATUS_REJECTED)
        self.assertEqual(self.loop.get_upgrade_state(), STATE_REJECTED)


class TestNewUpgradeCanStartAfterATerminalState(unittest.TestCase):
    """Requirement 5, 6, 7: once a terminal state is reached, a new
    upgrade may be started again - but only via a caller's own,
    separate, explicit call; nothing here does so automatically."""

    def test_start_succeeds_again_after_completed(self):
        target_file = "/tmp/allowed/generated.py"
        versions = _new_version_system()
        loop = _new_loop(versions)
        correction_result = _correction_result(
            _proposal(target_file), _validation_result(target_file), _application(target_file),
        )
        loop.start_code_change_upgrade()
        readiness_result = loop.evaluate_self_upgrade_readiness(
            correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        snapshot_result = loop.snapshot_self_upgrade_version(
            correction_result, RESULT_PASSED, readiness_result,
        )
        rollback_result = loop.decide_code_change_rollback(
            RESULT_PASSED, target_file, snapshot_result["version"],
        )
        loop.build_code_change_upgrade_result(
            correction_result, readiness_result, snapshot_result, rollback_result,
        )
        self.assertEqual(loop.get_upgrade_state(), STATE_COMPLETED)

        # Reaching COMPLETED never starts anything by itself.
        self.assertEqual(loop.get_upgrade_state(), STATE_COMPLETED)

        # A caller may now explicitly start a new upgrade.
        start_result = loop.start_code_change_upgrade()
        self.assertTrue(start_result["started"])
        self.assertEqual(loop.get_upgrade_state(), STATE_IN_PROGRESS)


class TestNoSecondAgentLoopOrStateSystem(unittest.TestCase):
    """Requirement 8: exactly one upgrade-state slot on this loop,
    never a second AgentLoop or a second, independent state store."""

    def test_single_private_state_slot(self):
        loop = _new_loop()
        self.assertTrue(hasattr(loop, "_upgrade_state"))
        self.assertFalse(hasattr(loop, "upgrade_state_machine"))
        self.assertFalse(hasattr(loop, "_second_agent_loop"))

    def test_state_is_per_instance_not_shared(self):
        loop_a = _new_loop()
        loop_b = _new_loop()
        loop_a.start_code_change_upgrade()
        self.assertEqual(loop_a.get_upgrade_state(), STATE_IN_PROGRESS)
        self.assertEqual(loop_b.get_upgrade_state(), STATE_IDLE)


class TestExistingApisPreserved(unittest.TestCase):
    """Requirement 10: build_code_change_upgrade_result's own return
    shape from Prompt 354 is completely unchanged by this addition."""

    def test_return_shape_unchanged(self):
        target_file = "/tmp/allowed/generated.py"
        versions = _new_version_system()
        loop = _new_loop(versions)
        correction_result = _correction_result(
            _proposal(target_file), _validation_result(target_file), _application(target_file),
        )
        readiness_result = loop.evaluate_self_upgrade_readiness(
            correction_result, "undefined_name", "42", RESULT_PASSED,
        )
        snapshot_result = loop.snapshot_self_upgrade_version(
            correction_result, RESULT_PASSED, readiness_result,
        )
        rollback_result = loop.decide_code_change_rollback(
            RESULT_PASSED, target_file, snapshot_result["version"],
        )
        result = loop.build_code_change_upgrade_result(
            correction_result, readiness_result, snapshot_result, rollback_result,
        )
        self.assertEqual(
            set(result.keys()),
            {
                "target_file", "validation_status", "change_status", "test_status",
                "version_status", "rollback_required", "rollback_status", "final_status",
            },
        )
        # The pure module-level builder still matches the method's own
        # output exactly - the method adds a state-tracking side
        # effect, never a change to the returned value.
        direct_result = build_code_change_upgrade_result(
            correction_result, readiness_result, snapshot_result, rollback_result,
        )
        self.assertEqual(result, direct_result)


if __name__ == "__main__":
    unittest.main()
