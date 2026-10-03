"""
Tests for `AgentLoop.request_code_change_correction_proposal`
(agent/agent_loop.py) - Prompt 334: connects the existing
code-change plan analysis (Prompt 333:
`request_code_change_correction_analysis`) to the existing
`AdaptivePlanProposal` system (planning/adaptive_plan_proposal.py),
reused exactly as `request_proposal`/`request_correction_proposal`
already reuse it - never a second, duplicate proposal system.

Covers: FAILED/TIMEOUT code-change results producing one correction
proposal, PASSED/INVALID/CHANGE_FAILED results never producing one, the
generated proposal never being applied and never touching a source
file, no additional test execution, and every previous result
(change_result, test_result, correction decision, plan analysis,
correction proposal) remaining available/unmodified.

Run directly:
    python -m unittest tests.test_code_change_correction_proposal -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.agent_loop import AgentLoop
from agent.test_result_evaluation import RESULT_PASSED, RESULT_FAILED, RESULT_TIMEOUT, RESULT_INVALID
from execution.code_change_apply_and_test_capability import (
    CHANGE_STATUS_APPLIED,
    CHANGE_STATUS_NOT_APPLIED,
)

from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from planning.plan import STATUS_FAILED as STEP_STATUS_FAILED
from planning.adaptive_plan_analyzer import AdaptivePlanAnalyzer, BLOCKER_FAILED_STEP
from planning.adaptive_plan_proposal import (
    AdaptivePlanProposal,
    PROPOSAL_NO_CHANGE_NEEDED,
    PROPOSAL_CHANGE_RECOMMENDED,
)
from execution.plan_execution_controller import PlanExecutionController


def _code_change_result(change_status, test_status=None, change_result=None, test_result=None):
    return {
        "change_status": change_status,
        "test_status": test_status,
        "test_output": None,
        "error": None,
        "change_result": change_result,
        "test_result": test_result,
    }


class AgentLoopCodeChangeCorrectionProposalTestBase(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.controller = PlanExecutionController(self.plans)
        self.goal = self.goals.create_goal("Ship a small feature")
        self.plan = self.plans.create_plan(self.goal.goal_id)

    def _add_step(self, description="Do the thing", **kwargs):
        return self.plans.add_step(self.plan.plan_id, description, **kwargs)

    def _fail_the_step(self):
        step = self._add_step()
        self.plans.update_step_status(self.plan.plan_id, step.step_id, STEP_STATUS_FAILED)
        return step

    def _wired_loop(self):
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        proposer = AdaptivePlanProposal(self.goals, self.plans, analyzer=analyzer)
        loop = AgentLoop(
            self.goals, self.plans, self.controller,
            analyzer=analyzer, proposal_generator=proposer,
        )
        return loop, analyzer, proposer


class TestRequestCodeChangeCorrectionProposal(AgentLoopCodeChangeCorrectionProposalTestBase):
    # ------------------------------------------------------------------
    # FAILED / TIMEOUT -> one correction proposal is generated.
    # ------------------------------------------------------------------
    def test_failed_test_status_triggers_a_proposal(self):
        self._fail_the_step()  # a real BLOCKER_FAILED_STEP
        loop, analyzer, proposer = self._wired_loop()
        code_change_result = _code_change_result(CHANGE_STATUS_APPLIED, RESULT_FAILED)

        analysis = loop.request_analysis(self.goal.goal_id, self.plan.plan_id)
        self.assertTrue(any(b["type"] == BLOCKER_FAILED_STEP for b in analysis["blockers"]))

        result = loop.request_code_change_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, code_change_result
        )

        self.assertTrue(result["proposal_performed"])
        self.assertIsNotNone(result["proposal"])
        self.assertEqual(result["proposal"]["status"], PROPOSAL_CHANGE_RECOMMENDED)

    def test_timeout_test_status_triggers_a_proposal(self):
        self._add_step()  # left pending -> incomplete, no explicit blocker
        loop, analyzer, proposer = self._wired_loop()
        code_change_result = _code_change_result(CHANGE_STATUS_APPLIED, RESULT_TIMEOUT)

        result = loop.request_code_change_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, code_change_result
        )

        self.assertTrue(result["proposal_performed"])
        self.assertEqual(result["proposal"]["status"], PROPOSAL_NO_CHANGE_NEEDED)

    def test_proposal_matches_direct_request_proposal(self):
        self._fail_the_step()
        loop, analyzer, proposer = self._wired_loop()
        code_change_result = _code_change_result(CHANGE_STATUS_APPLIED, RESULT_FAILED)

        result = loop.request_code_change_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, code_change_result
        )
        direct = loop.request_proposal(self.goal.goal_id, self.plan.plan_id)

        # Each call to the underlying AdaptivePlanProposal mints its own
        # proposal_id/created_at, and each ProposedChange its own
        # change_id - everything else about the two calls' own
        # structured content is identical.
        self.assertEqual(result["proposal"]["status"], direct["status"])
        self.assertEqual(result["proposal"]["goal_id"], direct["goal_id"])
        self.assertEqual(result["proposal"]["plan_id"], direct["plan_id"])
        self.assertEqual(
            [(c["change_type"], c["target_step_id"], c["reason"])
             for c in result["proposal"]["proposed_changes"]],
            [(c["change_type"], c["target_step_id"], c["reason"])
             for c in direct["proposed_changes"]],
        )

    # ------------------------------------------------------------------
    # PASSED -> no correction proposal.
    # ------------------------------------------------------------------
    def test_passed_test_status_never_triggers_a_proposal(self):
        self._fail_the_step()  # would produce a blocker if reached
        loop, analyzer, proposer = self._wired_loop()
        code_change_result = _code_change_result(CHANGE_STATUS_APPLIED, RESULT_PASSED)

        result = loop.request_code_change_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, code_change_result
        )

        self.assertFalse(result["proposal_performed"])
        self.assertIsNone(result["proposal"])

    def test_passed_test_status_needs_no_proposal_generator(self):
        loop = AgentLoop(self.goals, self.plans, self.controller)
        code_change_result = _code_change_result(CHANGE_STATUS_APPLIED, RESULT_PASSED)
        try:
            result = loop.request_code_change_correction_proposal(
                self.goal.goal_id, self.plan.plan_id, code_change_result
            )
        except ValueError as exc:  # pragma: no cover - failure path
            self.fail(f"request_code_change_correction_proposal required a "
                      f"proposal_generator for a passed result: {exc!r}")
        self.assertFalse(result["proposal_performed"])

    # ------------------------------------------------------------------
    # INVALID result -> no correction proposal.
    # ------------------------------------------------------------------
    def test_invalid_result_never_triggers_a_proposal(self):
        self._fail_the_step()
        loop, analyzer, proposer = self._wired_loop()

        result = loop.request_code_change_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, "not a result"
        )

        self.assertFalse(result["proposal_performed"])
        self.assertIsNone(result["proposal"])

    def test_invalid_test_status_within_applied_change_never_triggers_a_proposal(self):
        self._fail_the_step()
        loop, analyzer, proposer = self._wired_loop()
        code_change_result = _code_change_result(CHANGE_STATUS_APPLIED, RESULT_INVALID)

        result = loop.request_code_change_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, code_change_result
        )

        self.assertFalse(result["proposal_performed"])
        self.assertIsNone(result["proposal"])

    def test_change_failed_never_triggers_a_proposal(self):
        self._fail_the_step()
        loop, analyzer, proposer = self._wired_loop()
        code_change_result = _code_change_result(CHANGE_STATUS_NOT_APPLIED)

        result = loop.request_code_change_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, code_change_result
        )

        self.assertFalse(result["proposal_performed"])
        self.assertIsNone(result["proposal"])

    def test_blockers_without_a_proposal_generator_raises(self):
        analyzer = AdaptivePlanAnalyzer(self.goals, self.plans)
        loop = AgentLoop(self.goals, self.plans, self.controller, analyzer=analyzer)
        self._fail_the_step()
        code_change_result = _code_change_result(CHANGE_STATUS_APPLIED, RESULT_FAILED)
        with self.assertRaises(ValueError):
            loop.request_code_change_correction_proposal(
                self.goal.goal_id, self.plan.plan_id, code_change_result
            )

    # ------------------------------------------------------------------
    # The proposal is a proposal only - never applied, never touches a
    # source file, never runs another test.
    # ------------------------------------------------------------------
    def test_proposal_is_never_automatically_applied(self):
        self._fail_the_step()
        loop, analyzer, proposer = self._wired_loop()
        code_change_result = _code_change_result(CHANGE_STATUS_APPLIED, RESULT_FAILED)

        before = self.plans.describe_plan(self.plan.plan_id)
        result = loop.request_code_change_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, code_change_result
        )
        after = self.plans.describe_plan(self.plan.plan_id)

        self.assertTrue(result["proposal_performed"])
        # The Plan/step state is completely unchanged - nothing about
        # the proposal was ever applied.
        self.assertEqual(before, after)
        self.assertNotIn("application", result)
        self.assertNotIn("application_performed", result)

    def test_no_plan_modification_when_no_proposal_is_generated(self):
        loop, analyzer, proposer = self._wired_loop()
        code_change_result = _code_change_result(CHANGE_STATUS_APPLIED, RESULT_PASSED)

        before = self.plans.describe_plan(self.plan.plan_id)
        loop.request_code_change_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, code_change_result
        )
        after = self.plans.describe_plan(self.plan.plan_id)

        self.assertEqual(before, after)

    def test_no_step_is_executed(self):
        step = self._fail_the_step()
        loop, analyzer, proposer = self._wired_loop()
        code_change_result = _code_change_result(CHANGE_STATUS_APPLIED, RESULT_FAILED)

        loop.request_code_change_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, code_change_result
        )

        # The only step present is still exactly as _fail_the_step left
        # it - nothing was (re-)executed by generating the proposal.
        refreshed = self.plans.get_step(self.plan.plan_id, step.step_id)
        self.assertEqual(refreshed.status, STEP_STATUS_FAILED)

    # ------------------------------------------------------------------
    # All previous results remain available/unmodified (requirement 5).
    # ------------------------------------------------------------------
    def test_all_previous_results_preserved(self):
        loop, analyzer, proposer = self._wired_loop()
        self._fail_the_step()
        change_result_marker = {"file": "app.py", "applied": True}
        test_result_marker = {"success": False, "timed_out": False, "failures": 3}
        code_change_result = _code_change_result(
            CHANGE_STATUS_APPLIED, RESULT_FAILED,
            change_result=change_result_marker, test_result=test_result_marker,
        )

        result = loop.request_code_change_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, code_change_result
        )
        correction_analysis = result["correction_analysis"]

        # change result
        self.assertEqual(correction_analysis["change_result"], change_result_marker)
        # test result
        self.assertEqual(correction_analysis["test_result"], test_result_marker)
        # correction decision
        self.assertTrue(correction_analysis["correction"]["correction_required"])
        self.assertEqual(correction_analysis["correction"]["reason"], "FAILED")
        # plan analysis
        self.assertIsNotNone(correction_analysis["analysis"])
        self.assertTrue(correction_analysis["analysis_performed"])
        # correction proposal
        self.assertTrue(result["proposal_performed"])
        self.assertIsNotNone(result["proposal"])

    def test_correction_analysis_matches_direct_call(self):
        self._fail_the_step()
        loop, analyzer, proposer = self._wired_loop()
        code_change_result = _code_change_result(CHANGE_STATUS_APPLIED, RESULT_FAILED)

        result = loop.request_code_change_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, code_change_result
        )

        self.assertEqual(
            result["correction_analysis"],
            loop.request_code_change_correction_analysis(
                self.goal.goal_id, self.plan.plan_id, code_change_result
            ),
        )

    def test_preserved_results_present_even_when_no_proposal(self):
        loop, analyzer, proposer = self._wired_loop()
        change_result_marker = {"file": "app.py", "applied": True}
        test_result_marker = {"success": True, "timed_out": False}
        code_change_result = _code_change_result(
            CHANGE_STATUS_APPLIED, RESULT_PASSED,
            change_result=change_result_marker, test_result=test_result_marker,
        )

        result = loop.request_code_change_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, code_change_result
        )

        self.assertEqual(result["correction_analysis"]["change_result"], change_result_marker)
        self.assertEqual(result["correction_analysis"]["test_result"], test_result_marker)
        self.assertFalse(result["proposal_performed"])
        self.assertIsNone(result["proposal"])

    # ------------------------------------------------------------------
    # Missing Plan/Goal data is handled safely.
    # ------------------------------------------------------------------
    def test_unknown_plan_id_is_handled_safely(self):
        loop, analyzer, proposer = self._wired_loop()
        code_change_result = _code_change_result(CHANGE_STATUS_APPLIED, RESULT_FAILED)

        try:
            result = loop.request_code_change_correction_proposal(
                self.goal.goal_id, "no-such-plan", code_change_result
            )
        except Exception as exc:  # pragma: no cover - failure path
            self.fail(f"request_code_change_correction_proposal raised for an "
                      f"unknown plan_id: {exc!r}")

        self.assertFalse(result["proposal_performed"])
        self.assertIsNone(result["proposal"])

    # ------------------------------------------------------------------
    # Never auto-invoked by run().
    # ------------------------------------------------------------------
    def test_run_never_calls_this_automatically(self):
        self._fail_the_step()
        loop, analyzer, proposer = self._wired_loop()

        result = loop.run(self.goal.goal_id, self.plan.plan_id)

        self.assertNotIn("proposal_performed", result)
        self.assertNotIn("proposal", result)
        self.assertNotIn("correction_analysis", result)

    def test_existing_request_correction_proposal_unaffected(self):
        # The pre-existing, bare-test_result correction-proposal
        # connection (Prompt 323) must keep working unchanged.
        self._fail_the_step()
        loop, analyzer, proposer = self._wired_loop()

        result = loop.request_correction_proposal(
            self.goal.goal_id, self.plan.plan_id, {"success": False, "timed_out": False}
        )
        self.assertTrue(result["proposal_performed"])


if __name__ == "__main__":
    unittest.main()
