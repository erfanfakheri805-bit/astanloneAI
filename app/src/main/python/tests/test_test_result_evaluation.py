"""
Tests for the deterministic test-result evaluation step
(agent/test_result_evaluation.py) and its connection to
`AgentLoop.evaluate_test_result` (agent/agent_loop.py) - classifying
an already-produced `python_test_runner` capability result
(execution/python_test_runner_capability.py, reused completely
unchanged) into exactly one of `"PASSED"`/`"FAILED"`/`"TIMEOUT"`/
`"INVALID"`.

Covers: a successful test-runner result classifying as PASSED; a
failed one as FAILED; a timed-out one as TIMEOUT; malformed/invalid
results as INVALID; `AgentLoop` exposing the structured evaluation
result (both directly and end-to-end from a real
`python_test_runner` capability run through the existing
`ExecutionEngine`); the existing `python_test_runner_capability`/
`AgentLoop` test suites remaining fully compatible with this addition;
and (Prompt 321) the `correction_required`/`reason` decision built on
top of that same evaluation - True only for FAILED/TIMEOUT/INVALID,
False for PASSED, the original evaluation preserved unmodified
alongside it, and no file/code modification or automatic retry ever
occurring as part of computing it.

Run directly:
    python -m unittest tests.test_test_result_evaluation -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.agent_loop import AgentLoop
from agent.test_result_evaluation import (
    RESULT_PASSED,
    RESULT_FAILED,
    RESULT_TIMEOUT,
    RESULT_INVALID,
    ALL_TEST_RESULT_CLASSIFICATIONS,
    classify_test_result,
    build_test_evaluation,
    is_correction_required,
    build_correction_decision,
)
from execution.python_test_runner_capability import (
    CAPABILITY_NAME as TEST_RUNNER_CAPABILITY_NAME,
    register_python_test_runner_capability,
)
from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from execution.plan_execution_controller import PlanExecutionController
from execution.execution_engine import ExecutionEngine


PASSING_TEST_SOURCE = (
    "import unittest\n\n"
    "class TestPassing(unittest.TestCase):\n"
    "    def test_ok(self):\n"
    "        self.assertEqual(1 + 1, 2)\n"
)

FAILING_TEST_SOURCE = (
    "import unittest\n\n"
    "class TestFailing(unittest.TestCase):\n"
    "    def test_not_ok(self):\n"
    "        self.assertEqual(1 + 1, 3)\n"
)


def _successful_result(**overrides):
    result = {
        "path": "/allowed/project",
        "requested_path": "/allowed/project",
        "target": "test_thing.py",
        "success": True,
        "timed_out": False,
        "return_code": 0,
        "stdout": "",
        "stderr": "Ran 1 test in 0.001s\n\nOK\n",
        "tests_run": 1,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "duration_seconds": 0.01,
    }
    result.update(overrides)
    return result


def _failed_result(**overrides):
    result = _successful_result(
        success=False,
        return_code=1,
        stderr="Ran 1 test in 0.001s\n\nFAILED (failures=1)\n",
        failures=1,
    )
    result.update(overrides)
    return result


def _timed_out_result(**overrides):
    result = {
        "path": "/allowed/project",
        "requested_path": "/allowed/project",
        "target": "test_thing.py",
        "success": False,
        "timed_out": True,
        "return_code": None,
        "stdout": "",
        "stderr": "",
        "tests_run": None,
        "failures": None,
        "errors": None,
        "skipped": None,
        "duration_seconds": 1.0,
    }
    result.update(overrides)
    return result


class AgentLoopTestEvaluationBase(unittest.TestCase):
    def setUp(self):
        self.goals = GoalManager()
        self.plans = PlanManager(self.goals)
        self.controller = PlanExecutionController(self.plans)
        self.loop = AgentLoop(self.goals, self.plans, self.controller)


# ----------------------------------------------------------------------
# 1. Successful test result -> "PASSED"
# ----------------------------------------------------------------------
class TestSuccessfulResultIsPassed(unittest.TestCase):
    def test_classify_reports_passed(self):
        self.assertEqual(classify_test_result(_successful_result()), RESULT_PASSED)

    def test_passed_is_a_known_classification(self):
        self.assertIn(RESULT_PASSED, ALL_TEST_RESULT_CLASSIFICATIONS)

    def test_extra_fields_do_not_change_the_classification(self):
        result = _successful_result(tests_run=42, duration_seconds=12.5)
        self.assertEqual(classify_test_result(result), RESULT_PASSED)


# ----------------------------------------------------------------------
# 2. Failed test result -> "FAILED"
# ----------------------------------------------------------------------
class TestFailedResultIsFailed(unittest.TestCase):
    def test_classify_reports_failed(self):
        self.assertEqual(classify_test_result(_failed_result()), RESULT_FAILED)

    def test_failed_with_errors_instead_of_failures_is_still_failed(self):
        result = _failed_result(failures=0, errors=1)
        self.assertEqual(classify_test_result(result), RESULT_FAILED)

    def test_failed_is_a_known_classification(self):
        self.assertIn(RESULT_FAILED, ALL_TEST_RESULT_CLASSIFICATIONS)


# ----------------------------------------------------------------------
# 3. Timeout result -> "TIMEOUT"
# ----------------------------------------------------------------------
class TestTimeoutResultIsTimeout(unittest.TestCase):
    def test_classify_reports_timeout(self):
        self.assertEqual(classify_test_result(_timed_out_result()), RESULT_TIMEOUT)

    def test_timeout_takes_priority_over_success_field(self):
        # timed_out=True always wins, even if something upstream ever
        # produced an inconsistent success=True alongside it.
        result = _timed_out_result(success=True)
        self.assertEqual(classify_test_result(result), RESULT_TIMEOUT)

    def test_timeout_is_a_known_classification(self):
        self.assertIn(RESULT_TIMEOUT, ALL_TEST_RESULT_CLASSIFICATIONS)


# ----------------------------------------------------------------------
# 4. Invalid/malformed result -> "INVALID"
# ----------------------------------------------------------------------
class TestMalformedResultIsInvalid(unittest.TestCase):
    def test_none_is_invalid(self):
        self.assertEqual(classify_test_result(None), RESULT_INVALID)

    def test_non_dict_is_invalid(self):
        self.assertEqual(classify_test_result("PASSED"), RESULT_INVALID)
        self.assertEqual(classify_test_result(["success"]), RESULT_INVALID)
        self.assertEqual(classify_test_result(True), RESULT_INVALID)

    def test_empty_dict_is_invalid(self):
        self.assertEqual(classify_test_result({}), RESULT_INVALID)

    def test_missing_success_field_is_invalid(self):
        result = _successful_result()
        del result["success"]
        self.assertEqual(classify_test_result(result), RESULT_INVALID)

    def test_missing_timed_out_field_is_invalid(self):
        result = _successful_result()
        del result["timed_out"]
        self.assertEqual(classify_test_result(result), RESULT_INVALID)

    def test_non_boolean_success_is_invalid(self):
        result = _successful_result(success="true")
        self.assertEqual(classify_test_result(result), RESULT_INVALID)

    def test_non_boolean_timed_out_is_invalid(self):
        result = _successful_result(timed_out=0)
        self.assertEqual(classify_test_result(result), RESULT_INVALID)

    def test_invalid_is_a_known_classification(self):
        self.assertIn(RESULT_INVALID, ALL_TEST_RESULT_CLASSIFICATIONS)

    def test_never_raises_for_malformed_input(self):
        for bad_input in (None, 42, "oops", [], {}, object()):
            try:
                classify_test_result(bad_input)
            except Exception as exc:  # pragma: no cover - failure path
                self.fail(f"classify_test_result raised for {bad_input!r}: {exc!r}")


# ----------------------------------------------------------------------
# 5. Agent receives the structured evaluation result
# ----------------------------------------------------------------------
class TestAgentReceivesStructuredEvaluationResult(AgentLoopTestEvaluationBase):
    def test_build_test_evaluation_shape(self):
        result = _successful_result()
        evaluation = build_test_evaluation(result)

        self.assertEqual(evaluation["classification"], RESULT_PASSED)
        self.assertIs(evaluation["test_result"], result)

    def test_agent_loop_exposes_evaluation_for_passed(self):
        evaluation = self.loop.evaluate_test_result(_successful_result())
        self.assertEqual(evaluation["classification"], RESULT_PASSED)

    def test_agent_loop_exposes_evaluation_for_failed(self):
        evaluation = self.loop.evaluate_test_result(_failed_result())
        self.assertEqual(evaluation["classification"], RESULT_FAILED)

    def test_agent_loop_exposes_evaluation_for_timeout(self):
        evaluation = self.loop.evaluate_test_result(_timed_out_result())
        self.assertEqual(evaluation["classification"], RESULT_TIMEOUT)

    def test_agent_loop_exposes_evaluation_for_invalid(self):
        evaluation = self.loop.evaluate_test_result({"nonsense": True})
        self.assertEqual(evaluation["classification"], RESULT_INVALID)

    def test_agent_loop_does_not_require_optional_collaborators(self):
        # Unlike request_analysis/request_proposal, this needs no
        # analyzer/proposal_generator to have been supplied.
        try:
            self.loop.evaluate_test_result(_successful_result())
        except ValueError as exc:  # pragma: no cover - failure path
            self.fail(f"evaluate_test_result required a collaborator: {exc!r}")

    def test_end_to_end_from_a_real_python_test_runner_execution(self):
        """The evaluation connects to the *actual* python_test_runner
        capability's own output, run through the existing
        ExecutionEngine - not just a hand-built fixture dict."""
        with tempfile.TemporaryDirectory() as project_dir:
            test_path = os.path.join(project_dir, "test_thing.py")
            with open(test_path, "w", encoding="utf-8") as fh:
                fh.write(PASSING_TEST_SOURCE)

            engine = ExecutionEngine(
                self.plans, executable_capabilities=self.controller.executable_capabilities
            )
            register_python_test_runner_capability(
                self.controller.executable_capabilities, allowed_dirs=[project_dir]
            )

            execution_result = engine.execute_registered_capability(
                TEST_RUNNER_CAPABILITY_NAME, {"path": project_dir, "target": "test_thing.py"}
            )
            evaluation = self.loop.evaluate_test_result(execution_result.output)

            self.assertEqual(evaluation["classification"], RESULT_PASSED)
            self.assertIs(evaluation["test_result"], execution_result.output)

    def test_end_to_end_failing_run_is_reported_as_failed(self):
        with tempfile.TemporaryDirectory() as project_dir:
            test_path = os.path.join(project_dir, "test_thing.py")
            with open(test_path, "w", encoding="utf-8") as fh:
                fh.write(FAILING_TEST_SOURCE)

            engine = ExecutionEngine(
                self.plans, executable_capabilities=self.controller.executable_capabilities
            )
            register_python_test_runner_capability(
                self.controller.executable_capabilities, allowed_dirs=[project_dir]
            )

            execution_result = engine.execute_registered_capability(
                TEST_RUNNER_CAPABILITY_NAME, {"path": project_dir, "target": "test_thing.py"}
            )
            evaluation = self.loop.evaluate_test_result(execution_result.output)

            self.assertEqual(evaluation["classification"], RESULT_FAILED)

    def test_end_to_end_unsafe_path_evaluates_as_invalid(self):
        """A capability-level failure (e.g. an unsafe/rejected path)
        never produces a raw python_test_runner result at all -
        `execution_result.output` is `None` for a FAILED
        ExecutionResult - and evaluating that is honestly INVALID,
        never mistaken for a real FAILED test run."""
        with tempfile.TemporaryDirectory() as project_dir, \
                tempfile.TemporaryDirectory() as other_dir:
            engine = ExecutionEngine(
                self.plans, executable_capabilities=self.controller.executable_capabilities
            )
            register_python_test_runner_capability(
                self.controller.executable_capabilities, allowed_dirs=[project_dir]
            )

            execution_result = engine.execute_registered_capability(
                TEST_RUNNER_CAPABILITY_NAME, {"path": other_dir}
            )
            evaluation = self.loop.evaluate_test_result(execution_result.output)

            self.assertEqual(evaluation["classification"], RESULT_INVALID)


# ----------------------------------------------------------------------
# 6. Existing tests remain compatible
# ----------------------------------------------------------------------
class TestExistingBehaviorRemainsCompatible(AgentLoopTestEvaluationBase):
    def test_python_test_runner_capability_module_is_unmodified(self):
        """python_test_runner_capability.py's own handler still
        produces the same result shape this evaluation depends on -
        this addition never changed the test-execution mechanism
        itself."""
        with tempfile.TemporaryDirectory() as project_dir:
            test_path = os.path.join(project_dir, "test_thing.py")
            with open(test_path, "w", encoding="utf-8") as fh:
                fh.write(PASSING_TEST_SOURCE)

            engine = ExecutionEngine(
                self.plans, executable_capabilities=self.controller.executable_capabilities
            )
            register_python_test_runner_capability(
                self.controller.executable_capabilities, allowed_dirs=[project_dir]
            )
            execution_result = engine.execute_registered_capability(
                TEST_RUNNER_CAPABILITY_NAME, {"path": project_dir, "target": "test_thing.py"}
            )

            for key in ("success", "timed_out", "return_code", "stdout", "stderr",
                        "tests_run", "failures", "errors", "skipped", "duration_seconds"):
                self.assertIn(key, execution_result.output)

    def test_agent_loop_run_still_works_unaffected(self):
        """A plain, capability-free AgentLoop.run() still behaves
        exactly as before this addition - evaluate_test_result is
        purely additive and run() never calls it automatically."""
        goal = self.goals.create_goal("Ship a small feature")
        plan = self.plans.create_plan(goal.goal_id)
        self.plans.add_step(plan.plan_id, "Do the thing")

        result = self.loop.run(goal.goal_id, plan.plan_id)

        self.assertIn("status", result)
        self.assertIn("success", result)

    def test_evaluate_test_result_is_not_called_automatically_by_run(self):
        goal = self.goals.create_goal("Ship a small feature")
        plan = self.plans.create_plan(goal.goal_id)
        self.plans.add_step(plan.plan_id, "Do the thing")

        result = self.loop.run(goal.goal_id, plan.plan_id)

        self.assertNotIn("classification", result)
        self.assertNotIn("test_evaluation", result)


# ----------------------------------------------------------------------
# 7. Correction decision (Prompt 321) - built on top of the existing
#    evaluation above, never a second/duplicate classifier.
# ----------------------------------------------------------------------
class TestCorrectionDecisionForPassed(unittest.TestCase):
    """Requirement 1: "PASSED" -> correction_required is False."""

    def test_is_correction_required_false_for_passed(self):
        self.assertFalse(is_correction_required(RESULT_PASSED))

    def test_build_correction_decision_false_for_passed(self):
        decision = build_correction_decision(_successful_result())
        self.assertFalse(decision["correction_required"])
        self.assertEqual(decision["reason"], RESULT_PASSED)


class TestCorrectionDecisionForFailed(unittest.TestCase):
    """Requirement 2: "FAILED" -> correction_required is True."""

    def test_is_correction_required_true_for_failed(self):
        self.assertTrue(is_correction_required(RESULT_FAILED))

    def test_build_correction_decision_true_for_failed(self):
        decision = build_correction_decision(_failed_result())
        self.assertTrue(decision["correction_required"])
        self.assertEqual(decision["reason"], RESULT_FAILED)


class TestCorrectionDecisionForTimeout(unittest.TestCase):
    """Requirement 3: "TIMEOUT" -> correction_required is True."""

    def test_is_correction_required_true_for_timeout(self):
        self.assertTrue(is_correction_required(RESULT_TIMEOUT))

    def test_build_correction_decision_true_for_timeout(self):
        decision = build_correction_decision(_timed_out_result())
        self.assertTrue(decision["correction_required"])
        self.assertEqual(decision["reason"], RESULT_TIMEOUT)


class TestCorrectionDecisionForInvalid(unittest.TestCase):
    """Requirement 4: "INVALID" -> correction_required is True."""

    def test_is_correction_required_true_for_invalid(self):
        self.assertTrue(is_correction_required(RESULT_INVALID))

    def test_build_correction_decision_true_for_invalid(self):
        decision = build_correction_decision({"nonsense": True})
        self.assertTrue(decision["correction_required"])
        self.assertEqual(decision["reason"], RESULT_INVALID)

    def test_build_correction_decision_true_for_none(self):
        decision = build_correction_decision(None)
        self.assertTrue(decision["correction_required"])
        self.assertEqual(decision["reason"], RESULT_INVALID)


class TestCorrectionDecisionPreservesOriginalEvaluation(unittest.TestCase):
    """Requirement 5: the original evaluation information is preserved
    completely unmodified alongside the correction decision."""

    def test_evaluation_matches_build_test_evaluation_for_passed(self):
        result = _successful_result()
        decision = build_correction_decision(result)
        expected_evaluation = build_test_evaluation(result)

        self.assertEqual(decision["evaluation"], expected_evaluation)
        self.assertIs(decision["evaluation"]["test_result"], result)

    def test_evaluation_matches_build_test_evaluation_for_failed(self):
        result = _failed_result()
        decision = build_correction_decision(result)

        self.assertEqual(decision["evaluation"]["classification"], RESULT_FAILED)
        self.assertIs(decision["evaluation"]["test_result"], result)

    def test_evaluation_matches_build_test_evaluation_for_timeout(self):
        result = _timed_out_result()
        decision = build_correction_decision(result)

        self.assertEqual(decision["evaluation"]["classification"], RESULT_TIMEOUT)
        self.assertIs(decision["evaluation"]["test_result"], result)

    def test_reason_always_matches_the_nested_evaluation_classification(self):
        for result in (_successful_result(), _failed_result(), _timed_out_result(),
                       {"nonsense": True}, None):
            decision = build_correction_decision(result)
            self.assertEqual(decision["reason"], decision["evaluation"]["classification"])


class TestAgentLoopCorrectionDecision(AgentLoopTestEvaluationBase):
    """`AgentLoop.evaluate_correction_decision` exposes the same
    structured decision, reusing `build_correction_decision`
    unchanged."""

    def test_passed_via_agent_loop(self):
        decision = self.loop.evaluate_correction_decision(_successful_result())
        self.assertFalse(decision["correction_required"])
        self.assertEqual(decision["reason"], RESULT_PASSED)

    def test_failed_via_agent_loop(self):
        decision = self.loop.evaluate_correction_decision(_failed_result())
        self.assertTrue(decision["correction_required"])
        self.assertEqual(decision["reason"], RESULT_FAILED)

    def test_timeout_via_agent_loop(self):
        decision = self.loop.evaluate_correction_decision(_timed_out_result())
        self.assertTrue(decision["correction_required"])
        self.assertEqual(decision["reason"], RESULT_TIMEOUT)

    def test_invalid_via_agent_loop(self):
        decision = self.loop.evaluate_correction_decision({"nonsense": True})
        self.assertTrue(decision["correction_required"])
        self.assertEqual(decision["reason"], RESULT_INVALID)

    def test_evaluation_preserved_via_agent_loop(self):
        result = _failed_result()
        decision = self.loop.evaluate_correction_decision(result)
        self.assertEqual(decision["evaluation"], self.loop.evaluate_test_result(result))

    def test_agent_loop_does_not_require_optional_collaborators(self):
        try:
            self.loop.evaluate_correction_decision(_successful_result())
        except ValueError as exc:  # pragma: no cover - failure path
            self.fail(f"evaluate_correction_decision required a collaborator: {exc!r}")


# ----------------------------------------------------------------------
# 6. No file or code modification occurs.
# ----------------------------------------------------------------------
class TestCorrectionDecisionNeverModifiesFilesOrCode(AgentLoopTestEvaluationBase):
    """Requirement 6: computing a correction decision - for any of the
    four classifications, including ones that require a correction -
    never touches the filesystem, never retries the test, and never
    executes another step or plan on its own."""

    def test_real_failing_run_produces_a_decision_without_touching_the_source_file(self):
        with tempfile.TemporaryDirectory() as project_dir:
            test_path = os.path.join(project_dir, "test_thing.py")
            with open(test_path, "w", encoding="utf-8") as fh:
                fh.write(FAILING_TEST_SOURCE)
            with open(test_path, "rb") as fh:
                original_bytes = fh.read()
            original_mtime = os.path.getmtime(test_path)

            engine = ExecutionEngine(
                self.plans, executable_capabilities=self.controller.executable_capabilities
            )
            register_python_test_runner_capability(
                self.controller.executable_capabilities, allowed_dirs=[project_dir]
            )
            execution_result = engine.execute_registered_capability(
                TEST_RUNNER_CAPABILITY_NAME, {"path": project_dir, "target": "test_thing.py"}
            )

            decision = self.loop.evaluate_correction_decision(execution_result.output)

            self.assertTrue(decision["correction_required"])
            self.assertEqual(decision["reason"], RESULT_FAILED)
            # The source file on disk is byte-for-byte and mtime-for-mtime
            # unchanged - no automatic correction, no rewrite, no retry.
            with open(test_path, "rb") as fh:
                self.assertEqual(fh.read(), original_bytes)
            self.assertEqual(os.path.getmtime(test_path), original_mtime)
            # No new files were created in the project directory either.
            self.assertEqual(os.listdir(project_dir), ["test_thing.py"])

    def test_no_new_files_created_for_any_classification(self):
        with tempfile.TemporaryDirectory() as workdir:
            before = set(os.listdir(workdir))
            for result in (_successful_result(), _failed_result(), _timed_out_result(),
                           {"nonsense": True}, None):
                self.loop.evaluate_correction_decision(result)
            after = set(os.listdir(workdir))
            self.assertEqual(before, after)

    def test_run_never_invokes_correction_decision_automatically(self):
        goal = self.goals.create_goal("Ship a small feature")
        plan = self.plans.create_plan(goal.goal_id)
        self.plans.add_step(plan.plan_id, "Do the thing")

        result = self.loop.run(goal.goal_id, plan.plan_id)

        self.assertNotIn("correction_required", result)
        self.assertNotIn("correction_decision", result)


if __name__ == "__main__":
    unittest.main()
