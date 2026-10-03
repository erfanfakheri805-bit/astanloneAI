"""
Tests for the built-in `code_change_plan` capability
(execution/code_change_plan_capability.py) - a read-only planning
capability that validates and analyzes one proposed exact-fragment
text change to an existing Python (.py) file, without ever applying
it, by reusing the existing `code_analysis` (AST-based analysis) and
`text_file_read` (safe file reading) capabilities - never a second,
duplicate implementation of either.

Covers: a valid Python change producing a ready change plan; a missing
target fragment being rejected; multiple target matches being
rejected; non-Python files being rejected; unsafe paths being
rejected; the target file never being modified by planning a change;
registration through the existing `ExecutableCapabilityRegistry`/
`CapabilityHandlerRegistry`; and this addition never touching or
breaking the existing `code_analysis`/`text_file_read`/
`text_file_edit` capability test suites.

Every test uses its own isolated temporary directory as the allowed
directory (via `allowed_dirs=`) - never the application's real
data/skills/temp directories.

Run directly:
    python -m unittest tests.test_code_change_plan_capability -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execution.capability import Capability
from execution.capability_handlers import CapabilityHandlerRegistry
from execution.executable_registry import ExecutableCapabilityRegistry
from execution.execution_engine import ExecutionEngine
from execution.execution_result import STATUS_COMPLETED, STATUS_FAILED
from execution.code_change_plan_capability import (
    CAPABILITY_NAME,
    create_code_change_plan_capability,
    register_code_change_plan_capability,
)
from execution.text_file_edit_capability import CAPABILITY_NAME as TEXT_FILE_EDIT_CAPABILITY_NAME
from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager

VALID_SOURCE = (
    "import os\n\n"
    "def greet(name):\n"
    "    return 'hi ' + name\n"
)

INVALID_SOURCE = "def broken(:\n    pass\n"


class CodeChangePlanCapabilityTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.allowed_dir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def _write(self, *relative_parts, content=""):
        path = os.path.join(self.allowed_dir, *relative_parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return path

    def _capability(self, **kwargs):
        return create_code_change_plan_capability(allowed_dirs=[self.allowed_dir], **kwargs)


# ----------------------------------------------------------------------
# Registration / execution path
# ----------------------------------------------------------------------
class TestAgentCanInvokeCodeChangePlanCapability(CodeChangePlanCapabilityTestBase):
    def test_capability_is_a_real_capability_instance(self):
        capability = self._capability()
        self.assertIsInstance(capability, Capability)
        self.assertEqual(capability.name, CAPABILITY_NAME)

    def test_registers_into_executable_capability_registry(self):
        registry = ExecutableCapabilityRegistry()
        register_code_change_plan_capability(registry, allowed_dirs=[self.allowed_dir])

        self.assertTrue(registry.has(CAPABILITY_NAME))
        self.assertTrue(registry.is_available(CAPABILITY_NAME))

    def test_registers_into_capability_handler_registry(self):
        registry = CapabilityHandlerRegistry()
        register_code_change_plan_capability(registry, allowed_dirs=[self.allowed_dir])

        self.assertTrue(registry.is_capability(CAPABILITY_NAME))

    def test_executable_through_execution_engine(self):
        """The exact same execution path AgentLoop's own execution
        stack (PlanExecutionController -> StepExecutionController ->
        ExecutionEngine) already runs every other registered
        capability through - `ExecutionEngine.execute_registered_capability`,
        out of `engine.executable_capabilities`."""
        path = self._write("thing.py", content=VALID_SOURCE)
        goals = GoalManager()
        plans = PlanManager(goals)
        engine = ExecutionEngine(plans)
        register_code_change_plan_capability(
            engine.executable_capabilities, allowed_dirs=[self.allowed_dir]
        )

        result = engine.execute_registered_capability(
            CAPABILITY_NAME,
            {"path": path, "old_text": "return 'hi ' + name", "new_text": "return 'hello ' + name"},
        )

        self.assertEqual(result.status, STATUS_COMPLETED)
        self.assertTrue(result.output["ready_to_apply"])

    def test_disabled_registration_is_not_executable_through_engine(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        goals = GoalManager()
        plans = PlanManager(goals)
        engine = ExecutionEngine(plans)
        register_code_change_plan_capability(
            engine.executable_capabilities, allowed_dirs=[self.allowed_dir], enabled=False,
        )

        result = engine.execute_registered_capability(
            CAPABILITY_NAME,
            {"path": path, "old_text": "return 'hi ' + name", "new_text": "return 'hello ' + name"},
        )

        self.assertEqual(result.status, STATUS_FAILED)


# ----------------------------------------------------------------------
# 1. A valid Python change produces a ready change plan.
# ----------------------------------------------------------------------
class TestValidPythonChangeProducesReadyPlan(CodeChangePlanCapabilityTestBase):
    def test_result_is_successful(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        capability = self._capability()

        result = capability.execute({
            "path": path, "old_text": "return 'hi ' + name", "new_text": "return 'hello ' + name",
        })

        self.assertTrue(result.success)
        self.assertIsNone(result.error)

    def test_ready_to_apply_is_true(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        capability = self._capability()

        result = capability.execute({
            "path": path, "old_text": "return 'hi ' + name", "new_text": "return 'hello ' + name",
        })

        self.assertTrue(result.output["ready_to_apply"])
        self.assertTrue(result.output["validation_status"]["valid"])
        self.assertEqual(result.output["validation_status"]["occurrences"], 1)

    def test_plan_reports_file_path_fragment_and_replacement(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        capability = self._capability()

        result = capability.execute({
            "path": path, "old_text": "return 'hi ' + name", "new_text": "return 'hello ' + name",
        })

        self.assertEqual(result.output["path"], os.path.realpath(path))
        self.assertEqual(result.output["target_fragment"], "return 'hi ' + name")
        self.assertEqual(result.output["replacement"], "return 'hello ' + name")

    def test_plan_includes_analysis_summary_from_code_analysis(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        capability = self._capability()

        result = capability.execute({
            "path": path, "old_text": "return 'hi ' + name", "new_text": "return 'hello ' + name",
        })

        summary = result.output["analysis_summary"]
        self.assertTrue(summary["valid"])
        self.assertIsNone(summary["syntax_error"])
        self.assertEqual(summary["function_count"], 1)
        self.assertEqual(summary["import_count"], 1)

    def test_plan_names_text_file_edit_as_the_apply_capability(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        capability = self._capability()

        result = capability.execute({
            "path": path, "old_text": "return 'hi ' + name", "new_text": "return 'hello ' + name",
        })

        self.assertEqual(result.output["apply_capability"], TEXT_FILE_EDIT_CAPABILITY_NAME)


# ----------------------------------------------------------------------
# 2. Missing target fragment is rejected.
# ----------------------------------------------------------------------
class TestMissingTargetFragmentIsRejected(CodeChangePlanCapabilityTestBase):
    def test_capability_still_succeeds_but_plan_is_not_ready(self):
        """A missing fragment is a substantive planning judgement, not
        a broken precondition - same "report, don't crash" convention
        code_analysis already follows for a syntax error."""
        path = self._write("thing.py", content=VALID_SOURCE)
        capability = self._capability()

        result = capability.execute({
            "path": path, "old_text": "this text is not in the file", "new_text": "anything",
        })

        self.assertTrue(result.success)
        self.assertFalse(result.output["ready_to_apply"])
        self.assertFalse(result.output["validation_status"]["valid"])
        self.assertEqual(result.output["validation_status"]["occurrences"], 0)
        self.assertTrue(result.output["validation_status"]["errors"])


# ----------------------------------------------------------------------
# 3. Multiple target matches are rejected.
# ----------------------------------------------------------------------
class TestMultipleTargetMatchesAreRejected(CodeChangePlanCapabilityTestBase):
    def test_ambiguous_fragment_is_not_ready(self):
        source = "x = 1\nx = 1\n"
        path = self._write("thing.py", content=source)
        capability = self._capability()

        result = capability.execute({"path": path, "old_text": "x = 1", "new_text": "x = 2"})

        self.assertTrue(result.success)
        self.assertFalse(result.output["ready_to_apply"])
        self.assertFalse(result.output["validation_status"]["valid"])
        self.assertEqual(result.output["validation_status"]["occurrences"], 2)


# ----------------------------------------------------------------------
# 4. Non-Python files are rejected.
# ----------------------------------------------------------------------
class TestNonPythonFilesAreRejected(CodeChangePlanCapabilityTestBase):
    def test_txt_file_is_rejected(self):
        path = self._write("notes.txt", content="just some text")
        capability = self._capability()

        result = capability.execute({"path": path, "old_text": "some", "new_text": "other"})

        self.assertFalse(result.success)
        self.assertIn(".py", result.error)


# ----------------------------------------------------------------------
# 5. Unsafe paths are rejected.
# ----------------------------------------------------------------------
class TestUnsafePathsAreRejected(CodeChangePlanCapabilityTestBase):
    def test_path_outside_allowed_dir_is_rejected(self):
        with tempfile.TemporaryDirectory() as other_dir:
            other_file = os.path.join(other_dir, "outside.py")
            with open(other_file, "w", encoding="utf-8") as fh:
                fh.write(VALID_SOURCE)
            capability = self._capability()

            result = capability.execute({
                "path": other_file, "old_text": "hi", "new_text": "hello",
            })

            self.assertFalse(result.success)
            self.assertIn("outside", result.error.lower())

    def test_traversal_out_of_allowed_dir_is_rejected(self):
        with tempfile.TemporaryDirectory() as other_dir:
            other_file = os.path.join(other_dir, "outside.py")
            with open(other_file, "w", encoding="utf-8") as fh:
                fh.write(VALID_SOURCE)
            traversal_path = os.path.join(
                self.allowed_dir, "..", os.path.basename(other_dir), "outside.py"
            )
            capability = self._capability()

            result = capability.execute({
                "path": traversal_path, "old_text": "hi", "new_text": "hello",
            })

            self.assertFalse(result.success)

    def test_missing_file_is_rejected(self):
        missing_path = os.path.join(self.allowed_dir, "does_not_exist.py")
        capability = self._capability()

        result = capability.execute({
            "path": missing_path, "old_text": "hi", "new_text": "hello",
        })

        self.assertFalse(result.success)

    def test_missing_old_text_field_is_rejected_by_input_validation(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        capability = self._capability()

        result = capability.execute({"path": path, "new_text": "hello"})

        self.assertFalse(result.success)
        self.assertFalse(result.validation.valid)

    def test_empty_old_text_is_rejected(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        capability = self._capability()

        result = capability.execute({"path": path, "old_text": "", "new_text": "hello"})

        self.assertFalse(result.success)


# ----------------------------------------------------------------------
# 6. Creating the plan does not modify the file.
# ----------------------------------------------------------------------
class TestPlanningDoesNotModifyFile(CodeChangePlanCapabilityTestBase):
    def test_file_contents_are_unchanged_after_a_ready_plan(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        capability = self._capability()

        capability.execute({
            "path": path, "old_text": "return 'hi ' + name", "new_text": "return 'hello ' + name",
        })

        with open(path, "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), VALID_SOURCE)

    def test_file_mtime_and_size_are_unchanged(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        stat_before = os.stat(path)
        capability = self._capability()

        capability.execute({
            "path": path, "old_text": "return 'hi ' + name", "new_text": "return 'hello ' + name",
        })

        stat_after = os.stat(path)
        self.assertEqual(stat_before.st_mtime_ns, stat_after.st_mtime_ns)
        self.assertEqual(stat_before.st_size, stat_after.st_size)

    def test_file_unchanged_even_for_a_missing_fragment_plan(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        capability = self._capability()

        capability.execute({
            "path": path, "old_text": "not present anywhere", "new_text": "hello",
        })

        with open(path, "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), VALID_SOURCE)

    def test_no_new_files_are_created_in_the_directory(self):
        self._write("thing.py", content=VALID_SOURCE)
        before = set(os.listdir(self.allowed_dir))
        capability = self._capability()

        capability.execute({
            "path": os.path.join(self.allowed_dir, "thing.py"),
            "old_text": "return 'hi ' + name",
            "new_text": "return 'hello ' + name",
        })

        after = set(os.listdir(self.allowed_dir))
        self.assertEqual(before, after)


# ----------------------------------------------------------------------
# Analysis of already-invalid (syntactically broken) Python source.
# ----------------------------------------------------------------------
class TestInvalidPythonSourceIsReportedSafely(CodeChangePlanCapabilityTestBase):
    def test_broken_source_is_reported_as_not_ready_never_raised(self):
        path = self._write("broken.py", content=INVALID_SOURCE)
        capability = self._capability()

        try:
            result = capability.execute({"path": path, "old_text": "pass", "new_text": "return"})
        except Exception as exc:  # pragma: no cover - failure path
            self.fail(f"execute() raised for invalid Python source: {exc!r}")

        self.assertTrue(result.success)
        self.assertFalse(result.output["ready_to_apply"])
        self.assertFalse(result.output["analysis_summary"]["valid"])
        self.assertIsNotNone(result.output["analysis_summary"]["syntax_error"])
        # The fragment itself matched fine - it's the file's own
        # syntax that blocks readiness, reported separately.
        self.assertTrue(result.output["validation_status"]["valid"])

    def test_broken_source_file_is_left_untouched(self):
        path = self._write("broken.py", content=INVALID_SOURCE)
        stat_before = os.stat(path)
        capability = self._capability()

        capability.execute({"path": path, "old_text": "pass", "new_text": "return"})

        stat_after = os.stat(path)
        self.assertEqual(stat_before.st_mtime_ns, stat_after.st_mtime_ns)


# ----------------------------------------------------------------------
# Existing tests remain compatible.
# ----------------------------------------------------------------------
class TestExistingBehaviorRemainsCompatible(CodeChangePlanCapabilityTestBase):
    def test_code_analysis_capability_is_unaffected(self):
        from execution.code_analysis_capability import create_code_analysis_capability

        path = self._write("thing.py", content=VALID_SOURCE)
        analysis_capability = create_code_analysis_capability(allowed_dirs=[self.allowed_dir])

        result = analysis_capability.execute({"path": path})

        self.assertTrue(result.success)
        self.assertTrue(result.output["analysis"]["valid"])

    def test_text_file_read_capability_is_unaffected(self):
        from execution.text_file_read_capability import create_text_file_read_capability

        path = self._write("notes.txt", content="hello world")
        read_capability = create_text_file_read_capability(allowed_dirs=[self.allowed_dir])

        result = read_capability.execute({"path": path})

        self.assertTrue(result.success)
        self.assertEqual(result.output["text"], "hello world")

    def test_text_file_edit_capability_still_actually_writes(self):
        """`text_file_edit` itself is completely unmodified: unlike
        `code_change_plan`, it still really writes the file."""
        from execution.text_file_edit_capability import create_text_file_edit_capability

        path = self._write("thing.py", content=VALID_SOURCE)
        edit_capability = create_text_file_edit_capability(allowed_dirs=[self.allowed_dir])

        result = edit_capability.execute({
            "path": path, "old_text": "return 'hi ' + name", "new_text": "return 'hello ' + name",
        })

        self.assertTrue(result.success)
        with open(path, "r", encoding="utf-8") as fh:
            self.assertIn("return 'hello ' + name", fh.read())

    def test_capability_output_schema_is_json_shaped(self):
        capability = self._capability()
        description = capability.describe()

        self.assertEqual(description["name"], CAPABILITY_NAME)
        self.assertIn("path", description["output_schema"]["properties"])
        self.assertIn("ready_to_apply", description["output_schema"]["properties"])


if __name__ == "__main__":
    unittest.main()
