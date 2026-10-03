"""
Tests for the built-in `code_change_apply` capability
(execution/code_change_apply_capability.py) - connects the existing
`code_change_plan` capability to the existing `text_file_edit`
capability: re-plans the same one-fragment text change, then applies
it (by calling `text_file_edit`'s own, unmodified handler) only when
the plan reports `ready_to_apply`, exactly once per call.

Covers: a valid change plan applying exactly one change; an invalid
change plan being rejected without modifying the file; the original
target fragment needing to still exist before applying; unsafe paths
being rejected; the result correctly reporting whether the change was
applied; and registration/compatibility with the existing
`code_change_plan`/`text_file_edit` capability test suites (this
module never touches or breaks either).

Every test uses its own isolated temporary directory as the allowed
directory (via `allowed_dirs=`) - never the application's real
data/skills/temp directories.

Run directly:
    python -m unittest tests.test_code_change_apply_capability -v
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
from execution.code_change_apply_capability import (
    CAPABILITY_NAME,
    create_code_change_apply_capability,
    register_code_change_apply_capability,
)
from execution.code_change_plan_capability import CAPABILITY_NAME as CODE_CHANGE_PLAN_CAPABILITY_NAME
from execution.text_file_edit_capability import CAPABILITY_NAME as TEXT_FILE_EDIT_CAPABILITY_NAME
from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager

VALID_SOURCE = (
    "import os\n\n"
    "def greet(name):\n"
    "    return 'hi ' + name\n"
)

INVALID_SOURCE = "def broken(:\n    pass\n"


class CodeChangeApplyCapabilityTestBase(unittest.TestCase):
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
        return create_code_change_apply_capability(allowed_dirs=[self.allowed_dir], **kwargs)


# ----------------------------------------------------------------------
# Registration / execution path
# ----------------------------------------------------------------------
class TestAgentCanInvokeCodeChangeApplyCapability(CodeChangeApplyCapabilityTestBase):
    def test_capability_is_a_real_capability_instance(self):
        capability = self._capability()
        self.assertIsInstance(capability, Capability)
        self.assertEqual(capability.name, CAPABILITY_NAME)

    def test_registers_into_executable_capability_registry(self):
        registry = ExecutableCapabilityRegistry()
        register_code_change_apply_capability(registry, allowed_dirs=[self.allowed_dir])

        self.assertTrue(registry.has(CAPABILITY_NAME))
        self.assertTrue(registry.is_available(CAPABILITY_NAME))

    def test_registers_into_capability_handler_registry(self):
        registry = CapabilityHandlerRegistry()
        register_code_change_apply_capability(registry, allowed_dirs=[self.allowed_dir])

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
        register_code_change_apply_capability(
            engine.executable_capabilities, allowed_dirs=[self.allowed_dir]
        )

        result = engine.execute_registered_capability(
            CAPABILITY_NAME,
            {"path": path, "old_text": "return 'hi ' + name", "new_text": "return 'hello ' + name"},
        )

        self.assertEqual(result.status, STATUS_COMPLETED)
        self.assertTrue(result.output["change_applied"])

    def test_disabled_registration_is_not_executable_through_engine(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        goals = GoalManager()
        plans = PlanManager(goals)
        engine = ExecutionEngine(plans)
        register_code_change_apply_capability(
            engine.executable_capabilities, allowed_dirs=[self.allowed_dir], enabled=False,
        )

        result = engine.execute_registered_capability(
            CAPABILITY_NAME,
            {"path": path, "old_text": "return 'hi ' + name", "new_text": "return 'hello ' + name"},
        )

        self.assertEqual(result.status, STATUS_FAILED)


# ----------------------------------------------------------------------
# 1. A valid change plan applies exactly one change.
# ----------------------------------------------------------------------
class TestValidChangePlanAppliesExactlyOneChange(CodeChangeApplyCapabilityTestBase):
    def test_result_is_successful_and_change_applied(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        capability = self._capability()

        result = capability.execute({
            "path": path, "old_text": "return 'hi ' + name", "new_text": "return 'hello ' + name",
        })

        self.assertTrue(result.success)
        self.assertIsNone(result.error)
        self.assertTrue(result.output["success"])
        self.assertTrue(result.output["change_applied"])

    def test_file_is_actually_modified_with_exactly_one_replacement(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        capability = self._capability()

        result = capability.execute({
            "path": path, "old_text": "return 'hi ' + name", "new_text": "return 'hello ' + name",
        })

        with open(path, "r", encoding="utf-8") as fh:
            updated = fh.read()
        self.assertIn("return 'hello ' + name", updated)
        self.assertNotIn("return 'hi ' + name", updated)
        self.assertEqual(result.output["change_metadata"]["occurrences_replaced"], 1)

    def test_change_metadata_reports_basic_change_facts(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        capability = self._capability()

        result = capability.execute({
            "path": path, "old_text": "return 'hi ' + name", "new_text": "return 'hello ' + name",
        })

        metadata = result.output["change_metadata"]
        self.assertEqual(metadata["target_fragment"], "return 'hi ' + name")
        self.assertEqual(metadata["replacement"], "return 'hello ' + name")
        self.assertIn("characters_removed", metadata)
        self.assertIn("characters_added", metadata)
        self.assertIn("character_count_before", metadata)
        self.assertIn("character_count_after", metadata)
        self.assertIn("byte_size", metadata)

    def test_result_reports_file_path(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        capability = self._capability()

        result = capability.execute({
            "path": path, "old_text": "return 'hi ' + name", "new_text": "return 'hello ' + name",
        })

        self.assertEqual(result.output["path"], os.path.realpath(path))
        self.assertEqual(result.output["requested_path"], path)

    def test_calling_twice_with_the_same_fragment_only_ever_applies_one_change_each_time(self):
        """Each call applies exactly one validated change - a second,
        independent call after the fragment has already been changed
        finds the *new* text, not the old one, so it correctly reports
        a not-ready plan rather than silently reapplying anything."""
        path = self._write("thing.py", content=VALID_SOURCE)
        capability = self._capability()

        first = capability.execute({
            "path": path, "old_text": "return 'hi ' + name", "new_text": "return 'hello ' + name",
        })
        second = capability.execute({
            "path": path, "old_text": "return 'hi ' + name", "new_text": "return 'hello ' + name",
        })

        self.assertTrue(first.output["change_applied"])
        self.assertFalse(second.output["change_applied"])


# ----------------------------------------------------------------------
# 2. An invalid change plan is rejected without modifying the file.
# ----------------------------------------------------------------------
class TestInvalidChangePlanIsRejectedWithoutModifyingFile(CodeChangeApplyCapabilityTestBase):
    def test_missing_fragment_is_not_applied(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        capability = self._capability()

        result = capability.execute({
            "path": path, "old_text": "this text is not in the file", "new_text": "anything",
        })

        self.assertTrue(result.success)
        self.assertFalse(result.output["success"])
        self.assertFalse(result.output["change_applied"])
        with open(path, "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), VALID_SOURCE)

    def test_ambiguous_fragment_is_not_applied(self):
        source = "x = 1\nx = 1\n"
        path = self._write("thing.py", content=source)
        capability = self._capability()

        result = capability.execute({"path": path, "old_text": "x = 1", "new_text": "x = 2"})

        self.assertFalse(result.output["change_applied"])
        with open(path, "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), source)

    def test_syntactically_broken_python_source_is_not_applied(self):
        """`ready_to_apply` requires both a matched fragment *and*
        currently-valid Python source - a fragment that matches inside
        an already-broken file must still not be applied."""
        path = self._write("broken.py", content=INVALID_SOURCE)
        stat_before = os.stat(path)
        capability = self._capability()

        result = capability.execute({"path": path, "old_text": "pass", "new_text": "return"})

        self.assertFalse(result.output["change_applied"])
        stat_after = os.stat(path)
        self.assertEqual(stat_before.st_mtime_ns, stat_after.st_mtime_ns)

    def test_not_ready_result_still_reports_plan_metadata(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        capability = self._capability()

        result = capability.execute({
            "path": path, "old_text": "not present anywhere", "new_text": "anything",
        })

        metadata = result.output["change_metadata"]
        self.assertIn("validation_status", metadata)
        self.assertIn("analysis_summary", metadata)
        self.assertFalse(metadata["validation_status"]["valid"])


# ----------------------------------------------------------------------
# 3. The original target fragment must still exist before applying.
# ----------------------------------------------------------------------
class TestTargetFragmentMustStillExistBeforeApplying(CodeChangeApplyCapabilityTestBase):
    def test_fragment_already_replaced_elsewhere_is_not_reapplied(self):
        """If the file no longer contains the exact fragment (e.g. it
        was already changed by something else), the change must not
        be applied even though the *replacement* text is perfectly
        valid Python."""
        source = "def greet(name):\n    return 'hello ' + name\n"
        path = self._write("thing.py", content=source)
        capability = self._capability()

        result = capability.execute({
            "path": path, "old_text": "return 'hi ' + name", "new_text": "return 'hello ' + name",
        })

        self.assertFalse(result.output["change_applied"])
        self.assertEqual(result.output["change_metadata"]["validation_status"]["occurrences"], 0)
        with open(path, "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), source)

    def test_fragment_present_exactly_once_is_applied(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        capability = self._capability()

        result = capability.execute({
            "path": path, "old_text": "return 'hi ' + name", "new_text": "return 'hello ' + name",
        })

        self.assertTrue(result.output["change_applied"])


# ----------------------------------------------------------------------
# 4. Unsafe paths are rejected.
# ----------------------------------------------------------------------
class TestUnsafePathsAreRejected(CodeChangeApplyCapabilityTestBase):
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
            with open(other_file, "r", encoding="utf-8") as fh:
                self.assertEqual(fh.read(), VALID_SOURCE)

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

    def test_non_python_file_is_rejected(self):
        path = self._write("notes.txt", content="just some text")
        capability = self._capability()

        result = capability.execute({"path": path, "old_text": "some", "new_text": "other"})

        self.assertFalse(result.success)
        self.assertIn(".py", result.error)

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
# 5. The result correctly reports whether the change was applied.
# ----------------------------------------------------------------------
class TestResultReportsWhetherChangeWasApplied(CodeChangeApplyCapabilityTestBase):
    def test_ready_plan_reports_change_applied_true(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        capability = self._capability()

        result = capability.execute({
            "path": path, "old_text": "return 'hi ' + name", "new_text": "return 'hello ' + name",
        })

        self.assertIn("change_applied", result.output)
        self.assertTrue(result.output["change_applied"])
        self.assertTrue(result.output["success"])

    def test_not_ready_plan_reports_change_applied_false(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        capability = self._capability()

        result = capability.execute({
            "path": path, "old_text": "not present anywhere", "new_text": "anything",
        })

        self.assertIn("change_applied", result.output)
        self.assertFalse(result.output["change_applied"])
        self.assertFalse(result.output["success"])

    def test_change_applied_matches_actual_file_state(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        capability = self._capability()

        applied_result = capability.execute({
            "path": path, "old_text": "return 'hi ' + name", "new_text": "return 'hello ' + name",
        })
        with open(path, "r", encoding="utf-8") as fh:
            after_applied = fh.read()

        not_applied_result = capability.execute({
            "path": path, "old_text": "not present anywhere", "new_text": "anything",
        })
        with open(path, "r", encoding="utf-8") as fh:
            after_not_applied = fh.read()

        self.assertTrue(applied_result.output["change_applied"])
        self.assertNotEqual(after_applied, VALID_SOURCE)
        self.assertFalse(not_applied_result.output["change_applied"])
        self.assertEqual(after_not_applied, after_applied)


# ----------------------------------------------------------------------
# 6. Existing tests remain compatible.
# ----------------------------------------------------------------------
class TestExistingBehaviorRemainsCompatible(CodeChangeApplyCapabilityTestBase):
    def test_code_change_plan_capability_is_unaffected(self):
        from execution.code_change_plan_capability import create_code_change_plan_capability

        path = self._write("thing.py", content=VALID_SOURCE)
        plan_capability = create_code_change_plan_capability(allowed_dirs=[self.allowed_dir])

        result = plan_capability.execute({
            "path": path, "old_text": "return 'hi ' + name", "new_text": "return 'hello ' + name",
        })

        self.assertTrue(result.success)
        self.assertTrue(result.output["ready_to_apply"])
        self.assertEqual(result.output["apply_capability"], TEXT_FILE_EDIT_CAPABILITY_NAME)
        # code_change_plan on its own still never writes the file.
        with open(path, "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), VALID_SOURCE)

    def test_text_file_edit_capability_still_actually_writes_on_its_own(self):
        from execution.text_file_edit_capability import create_text_file_edit_capability

        path = self._write("thing.py", content=VALID_SOURCE)
        edit_capability = create_text_file_edit_capability(allowed_dirs=[self.allowed_dir])

        result = edit_capability.execute({
            "path": path, "old_text": "return 'hi ' + name", "new_text": "return 'hello ' + name",
        })

        self.assertTrue(result.success)
        with open(path, "r", encoding="utf-8") as fh:
            self.assertIn("return 'hello ' + name", fh.read())

    def test_no_duplicate_capability_name_registered(self):
        """code_change_apply, code_change_plan, and text_file_edit are
        three distinct, independently-registerable capability names -
        not aliases of one another."""
        self.assertNotEqual(CAPABILITY_NAME, CODE_CHANGE_PLAN_CAPABILITY_NAME)
        self.assertNotEqual(CAPABILITY_NAME, TEXT_FILE_EDIT_CAPABILITY_NAME)

        registry = ExecutableCapabilityRegistry()
        register_code_change_apply_capability(registry, allowed_dirs=[self.allowed_dir])
        from execution.code_change_plan_capability import register_code_change_plan_capability
        from execution.text_file_edit_capability import register_text_file_edit_capability

        register_code_change_plan_capability(registry, allowed_dirs=[self.allowed_dir])
        register_text_file_edit_capability(registry, allowed_dirs=[self.allowed_dir])

        self.assertTrue(registry.has(CAPABILITY_NAME))
        self.assertTrue(registry.has(CODE_CHANGE_PLAN_CAPABILITY_NAME))
        self.assertTrue(registry.has(TEXT_FILE_EDIT_CAPABILITY_NAME))

    def test_capability_output_schema_is_json_shaped(self):
        capability = self._capability()
        description = capability.describe()

        self.assertEqual(description["name"], CAPABILITY_NAME)
        self.assertIn("path", description["output_schema"]["properties"])
        self.assertIn("change_applied", description["output_schema"]["properties"])
        self.assertIn("success", description["output_schema"]["properties"])


if __name__ == "__main__":
    unittest.main()
