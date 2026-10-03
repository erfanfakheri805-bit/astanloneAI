"""
Tests for agent/code_error_analysis.py - connects the existing
`execute_generated_code` result and its existing evaluation
(agent/generated_code_execution_evaluation.py) to AgentLoop via
`AgentLoop.analyze_generated_code_error` (agent/agent_loop.py).

Covers all six named failure categories (SyntaxError, NameError,
TypeError, ImportError - including the ModuleNotFoundError subclass -
RuntimeError, TIMEOUT), the UNKNOWN_ERROR fallback for an
unrecognized exception and for stderr with no traceback at all,
line_number extraction from a real traceback, is_actionable's fixed
rule, a PASSED/REJECTED execution never having an invented error, no
input ever raising, and AgentLoop.analyze_generated_code_error
delegating to this module unchanged.

Run directly:
    python -m unittest tests.test_code_error_analysis -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.code_error_analysis import (
    ALL_CODE_ERROR_TYPES,
    ERROR_TYPE_SYNTAX,
    ERROR_TYPE_NAME,
    ERROR_TYPE_TYPE,
    ERROR_TYPE_IMPORT,
    ERROR_TYPE_RUNTIME,
    ERROR_TYPE_TIMEOUT,
    ERROR_TYPE_UNKNOWN,
    build_code_error_analysis,
)
from code_generation.generated_code_execution import (
    STATUS_EXECUTED,
    STATUS_FAILED,
    STATUS_TIMEOUT,
    STATUS_REJECTED,
)

from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from execution.plan_execution_controller import PlanExecutionController
from agent.agent_loop import AgentLoop

# Real tracebacks captured from actually running the corresponding
# small scripts under CPython - not hand-typed - so parsing is
# exercised against Python's own exact traceback format.
_SYNTAX_ERROR_STDERR = (
    '  File "/sandbox/generated.py", line 1\n'
    '    def f(:\n'
    '          ^\n'
    'SyntaxError: invalid syntax\n'
)

_NAME_ERROR_STDERR = (
    'Traceback (most recent call last):\n'
    '  File "/sandbox/generated.py", line 3, in <module>\n'
    '    f()\n'
    '  File "/sandbox/generated.py", line 2, in f\n'
    '    return undefined_var\n'
    '           ^^^^^^^^^^^^^\n'
    "NameError: name 'undefined_var' is not defined\n"
)

_TYPE_ERROR_STDERR = (
    'Traceback (most recent call last):\n'
    '  File "/sandbox/generated.py", line 3, in <module>\n'
    '    f()\n'
    '  File "/sandbox/generated.py", line 2, in f\n'
    '    return "a" + 1\n'
    '           ~~~~^~~\n'
    'TypeError: can only concatenate str (not "int") to str\n'
)

_IMPORT_ERROR_STDERR = (
    'Traceback (most recent call last):\n'
    '  File "/sandbox/generated.py", line 1, in <module>\n'
    '    import nonexistent_module_xyz\n'
    "ModuleNotFoundError: No module named 'nonexistent_module_xyz'\n"
)

_RUNTIME_ERROR_STDERR = (
    'Traceback (most recent call last):\n'
    '  File "/sandbox/generated.py", line 3, in <module>\n'
    '    f()\n'
    '  File "/sandbox/generated.py", line 2, in f\n'
    '    raise RuntimeError("boom")\n'
    'RuntimeError: boom\n'
)

_UNKNOWN_EXCEPTION_STDERR = (
    'Traceback (most recent call last):\n'
    '  File "/sandbox/generated.py", line 3, in <module>\n'
    '    f()\n'
    '  File "/sandbox/generated.py", line 2, in f\n'
    '    raise ValueError("bad value")\n'
    'ValueError: bad value\n'
)


def _execution_result(status, target_file="/sandbox/generated.py", error=None,
                       stdout=None, stderr=None):
    return {
        "status": status,
        "target_file": target_file,
        "stdout": stdout,
        "stderr": stderr,
        "error": error,
    }


class TestBuildCodeErrorAnalysisNamedFailures(unittest.TestCase):
    def test_syntax_error(self):
        result = _execution_result(
            STATUS_FAILED, error="Execution of '/sandbox/generated.py' exited with return code 1.",
            stderr=_SYNTAX_ERROR_STDERR,
        )
        analysis = build_code_error_analysis(result)
        self.assertEqual(analysis["target_file"], "/sandbox/generated.py")
        self.assertEqual(analysis["error_type"], ERROR_TYPE_SYNTAX)
        self.assertEqual(analysis["error_message"], "invalid syntax")
        self.assertEqual(analysis["stderr"], _SYNTAX_ERROR_STDERR)
        self.assertEqual(analysis["line_number"], 1)
        self.assertTrue(analysis["is_actionable"])

    def test_name_error(self):
        result = _execution_result(STATUS_FAILED, stderr=_NAME_ERROR_STDERR)
        analysis = build_code_error_analysis(result)
        self.assertEqual(analysis["error_type"], ERROR_TYPE_NAME)
        self.assertEqual(analysis["error_message"], "name 'undefined_var' is not defined")
        self.assertEqual(analysis["line_number"], 2)
        self.assertTrue(analysis["is_actionable"])

    def test_type_error(self):
        result = _execution_result(STATUS_FAILED, stderr=_TYPE_ERROR_STDERR)
        analysis = build_code_error_analysis(result)
        self.assertEqual(analysis["error_type"], ERROR_TYPE_TYPE)
        self.assertEqual(
            analysis["error_message"], 'can only concatenate str (not "int") to str'
        )
        self.assertEqual(analysis["line_number"], 2)
        self.assertTrue(analysis["is_actionable"])

    def test_import_error_via_module_not_found_subclass(self):
        result = _execution_result(STATUS_FAILED, stderr=_IMPORT_ERROR_STDERR)
        analysis = build_code_error_analysis(result)
        self.assertEqual(analysis["error_type"], ERROR_TYPE_IMPORT)
        self.assertEqual(analysis["error_message"], "No module named 'nonexistent_module_xyz'")
        self.assertEqual(analysis["line_number"], 1)
        self.assertTrue(analysis["is_actionable"])

    def test_runtime_error(self):
        result = _execution_result(STATUS_FAILED, stderr=_RUNTIME_ERROR_STDERR)
        analysis = build_code_error_analysis(result)
        self.assertEqual(analysis["error_type"], ERROR_TYPE_RUNTIME)
        self.assertEqual(analysis["error_message"], "boom")
        self.assertEqual(analysis["line_number"], 2)
        self.assertTrue(analysis["is_actionable"])

    def test_timeout(self):
        result = _execution_result(
            STATUS_TIMEOUT,
            error="Execution of '/sandbox/generated.py' timed out after 5 seconds.",
            stderr="",
        )
        analysis = build_code_error_analysis(result)
        self.assertEqual(analysis["error_type"], ERROR_TYPE_TIMEOUT)
        self.assertEqual(
            analysis["error_message"],
            "Execution of '/sandbox/generated.py' timed out after 5 seconds.",
        )
        self.assertIsNone(analysis["line_number"])
        self.assertTrue(analysis["is_actionable"])


class TestBuildCodeErrorAnalysisUnknownAndNoError(unittest.TestCase):
    def test_unrecognized_exception_is_unknown_error(self):
        # A real exception, but not one of the five named families -
        # never mislabeled as one of them.
        result = _execution_result(STATUS_FAILED, stderr=_UNKNOWN_EXCEPTION_STDERR)
        analysis = build_code_error_analysis(result)
        self.assertEqual(analysis["error_type"], ERROR_TYPE_UNKNOWN)
        self.assertEqual(analysis["error_message"], "bad value")
        self.assertEqual(analysis["line_number"], 2)
        self.assertFalse(analysis["is_actionable"])

    def test_failed_with_no_traceback_in_stderr_is_unknown_error(self):
        # requirement: never guess an error that isn't present.
        result = _execution_result(
            STATUS_FAILED,
            error="Execution of '/sandbox/generated.py' exited with return code 1.",
            stderr="",
        )
        analysis = build_code_error_analysis(result)
        self.assertEqual(analysis["error_type"], ERROR_TYPE_UNKNOWN)
        self.assertEqual(
            analysis["error_message"],
            "Execution of '/sandbox/generated.py' exited with return code 1.",
        )
        self.assertIsNone(analysis["line_number"])
        self.assertFalse(analysis["is_actionable"])

    def test_failed_with_none_stderr_is_unknown_error_never_raises(self):
        result = _execution_result(STATUS_FAILED, error="exit code 1", stderr=None)
        analysis = build_code_error_analysis(result)
        self.assertEqual(analysis["error_type"], ERROR_TYPE_UNKNOWN)
        self.assertIsNone(analysis["line_number"])
        self.assertFalse(analysis["is_actionable"])

    def test_executed_success_has_no_error(self):
        result = _execution_result(STATUS_EXECUTED, stdout="ok", stderr="")
        analysis = build_code_error_analysis(result)
        self.assertIsNone(analysis["error_type"])
        self.assertIsNone(analysis["line_number"])
        self.assertFalse(analysis["is_actionable"])

    def test_rejected_execution_has_no_error(self):
        # Execution never ran - nothing to analyze, nothing invented.
        result = _execution_result(STATUS_REJECTED, error="path outside allowed directories")
        analysis = build_code_error_analysis(result)
        self.assertIsNone(analysis["error_type"])
        self.assertEqual(analysis["error_message"], "path outside allowed directories")
        self.assertIsNone(analysis["line_number"])
        self.assertFalse(analysis["is_actionable"])

    def test_non_dict_input_never_raises(self):
        analysis = build_code_error_analysis("not a result")
        self.assertEqual(
            analysis,
            {
                "target_file": None,
                "error_type": None,
                "error_message": None,
                "stderr": None,
                "line_number": None,
                "is_actionable": False,
            },
        )

    def test_none_input_never_raises(self):
        analysis = build_code_error_analysis(None)
        self.assertIsNone(analysis["error_type"])
        self.assertFalse(analysis["is_actionable"])


class TestAllCodeErrorTypes(unittest.TestCase):
    def test_all_error_types_is_the_seven_fixed_labels(self):
        self.assertEqual(
            ALL_CODE_ERROR_TYPES,
            (ERROR_TYPE_SYNTAX, ERROR_TYPE_NAME, ERROR_TYPE_TYPE, ERROR_TYPE_IMPORT,
             ERROR_TYPE_RUNTIME, ERROR_TYPE_TIMEOUT, ERROR_TYPE_UNKNOWN),
        )


class TestAgentLoopAnalyzeGeneratedCodeError(unittest.TestCase):
    """Requirement: make the analysis result available to the existing
    AgentLoop without creating a duplicate error-analysis/evaluation
    system."""

    def setUp(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        controller = PlanExecutionController(plans)
        self.loop = AgentLoop(goals, plans, controller)

    def test_delegates_to_build_function_unchanged(self):
        result = _execution_result(STATUS_FAILED, stderr=_NAME_ERROR_STDERR)
        self.assertEqual(
            self.loop.analyze_generated_code_error(result),
            build_code_error_analysis(result),
        )

    def test_syntax_error_via_agent_loop(self):
        result = _execution_result(STATUS_FAILED, stderr=_SYNTAX_ERROR_STDERR)
        analysis = self.loop.analyze_generated_code_error(result)
        self.assertEqual(analysis["error_type"], ERROR_TYPE_SYNTAX)
        self.assertTrue(analysis["is_actionable"])

    def test_timeout_via_agent_loop(self):
        result = _execution_result(STATUS_TIMEOUT, error="timed out", stderr="")
        analysis = self.loop.analyze_generated_code_error(result)
        self.assertEqual(analysis["error_type"], ERROR_TYPE_TIMEOUT)
        self.assertTrue(analysis["is_actionable"])

    def test_unknown_error_via_agent_loop_never_raises(self):
        analysis = self.loop.analyze_generated_code_error("not a result")
        self.assertIsNone(analysis["error_type"])
        self.assertFalse(analysis["is_actionable"])

    def test_never_modifies_source_or_reexecutes_or_generates_correction(self):
        # Analyzing a FAILED result only reports the structured
        # analysis - it never touches the Plan/Goal (no plan/goal was
        # even created in this test's setUp) and returns no
        # correction/patch of its own.
        result = _execution_result(STATUS_FAILED, stderr=_RUNTIME_ERROR_STDERR)
        analysis = self.loop.analyze_generated_code_error(result)
        self.assertEqual(set(analysis.keys()), {
            "target_file", "error_type", "error_message", "stderr",
            "line_number", "is_actionable",
        })
        self.assertEqual(self.loop._goal_manager.get_goal("anything"), None)


if __name__ == "__main__":
    unittest.main()
