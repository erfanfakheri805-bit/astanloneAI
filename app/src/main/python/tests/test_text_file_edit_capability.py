"""
Tests for the built-in `text_file_edit` capability
(execution/text_file_edit_capability.py) - a real, standard-library-
only `Capability` that safely replaces exactly one occurrence of an
exact text fragment in an existing file.

Covers: exactly one matching fragment being replaced successfully; a
missing fragment failing without modifying the file; multiple matches
failing without modifying the file; unsafe paths being rejected;
successful edits returning structured metadata; and the capability
being registered and executable through the existing
`ExecutableCapabilityRegistry` / `ExecutionEngine` capability system.

Every test uses its own isolated temporary directory as the allowed
directory (via `allowed_dirs=`) - never the application's real
data/skills/temp directories - so this suite never touches, creates,
or depends on anything outside its own `tempfile.TemporaryDirectory`.

Run directly:
    python -m unittest tests.test_text_file_edit_capability -v
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
from execution.text_file_edit_capability import (
    CAPABILITY_NAME,
    create_text_file_edit_capability,
    register_text_file_edit_capability,
)
from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager


class TextFileEditCapabilityTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.allowed_dir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def _write(self, name, content):
        path = os.path.join(self.allowed_dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return path

    def _read(self, path):
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()

    def _capability(self, **kwargs):
        return create_text_file_edit_capability(
            allowed_dirs=[self.allowed_dir], **kwargs
        )


# ----------------------------------------------------------------------
# 1. Exactly one matching fragment is replaced successfully
# ----------------------------------------------------------------------
class TestExactlyOneMatchIsReplaced(TextFileEditCapabilityTestBase):
    def test_single_match_is_replaced_successfully(self):
        path = self._write("notes.txt", "hello world")
        capability = self._capability()

        result = capability.execute(
            {"path": path, "old_text": "world", "new_text": "there"}
        )

        self.assertTrue(result.success)
        self.assertEqual(self._read(path), "hello there")

    def test_replacement_can_change_length_of_file(self):
        path = self._write("notes.txt", "short")
        capability = self._capability()

        result = capability.execute(
            {"path": path, "old_text": "short", "new_text": "a much longer replacement"}
        )

        self.assertTrue(result.success)
        self.assertEqual(self._read(path), "a much longer replacement")

    def test_only_the_matched_occurrence_is_touched(self):
        path = self._write("notes.txt", "alpha beta gamma")
        capability = self._capability()

        result = capability.execute(
            {"path": path, "old_text": "beta", "new_text": "BETA"}
        )

        self.assertTrue(result.success)
        self.assertEqual(self._read(path), "alpha BETA gamma")


# ----------------------------------------------------------------------
# 2. Missing fragment fails without modifying the file
# ----------------------------------------------------------------------
class TestMissingFragmentFailsSafely(TextFileEditCapabilityTestBase):
    def test_missing_fragment_returns_failed_result(self):
        path = self._write("notes.txt", "hello world")
        capability = self._capability()

        result = capability.execute(
            {"path": path, "old_text": "not present", "new_text": "x"}
        )

        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)

    def test_missing_fragment_leaves_file_unmodified(self):
        original = "hello world"
        path = self._write("notes.txt", original)
        capability = self._capability()

        capability.execute({"path": path, "old_text": "not present", "new_text": "x"})

        self.assertEqual(self._read(path), original)

    def test_missing_fragment_never_raises(self):
        path = self._write("notes.txt", "hello world")
        capability = self._capability()

        try:
            capability.execute(
                {"path": path, "old_text": "not present", "new_text": "x"}
            )
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"execute() raised for a missing fragment: {exc}")


# ----------------------------------------------------------------------
# 3. Multiple matches fail without modifying the file
# ----------------------------------------------------------------------
class TestMultipleMatchesFailSafely(TextFileEditCapabilityTestBase):
    def test_multiple_matches_returns_failed_result(self):
        path = self._write("notes.txt", "repeat repeat repeat")
        capability = self._capability()

        result = capability.execute(
            {"path": path, "old_text": "repeat", "new_text": "once"}
        )

        self.assertFalse(result.success)

    def test_multiple_matches_leaves_file_unmodified(self):
        original = "repeat repeat repeat"
        path = self._write("notes.txt", original)
        capability = self._capability()

        capability.execute({"path": path, "old_text": "repeat", "new_text": "once"})

        self.assertEqual(self._read(path), original)

    def test_multiple_matches_error_mentions_the_ambiguity(self):
        path = self._write("notes.txt", "aa aa")
        capability = self._capability()

        result = capability.execute(
            {"path": path, "old_text": "aa", "new_text": "bb"}
        )

        self.assertIn("2", result.error)


# ----------------------------------------------------------------------
# 4. Unsafe paths are rejected
# ----------------------------------------------------------------------
class TestUnsafePathsAreRejected(TextFileEditCapabilityTestBase):
    def test_path_outside_allowed_dir_is_rejected(self):
        with tempfile.TemporaryDirectory() as other_dir:
            outside_path = os.path.join(other_dir, "secret.txt")
            with open(outside_path, "w", encoding="utf-8") as fh:
                fh.write("top secret value")

            capability = self._capability()
            result = capability.execute(
                {"path": outside_path, "old_text": "secret", "new_text": "public"}
            )

            self.assertFalse(result.success)
            self.assertIn("outside", result.error.lower())

    def test_outside_path_file_is_never_modified(self):
        with tempfile.TemporaryDirectory() as other_dir:
            outside_path = os.path.join(other_dir, "secret.txt")
            original = "top secret value"
            with open(outside_path, "w", encoding="utf-8") as fh:
                fh.write(original)

            capability = self._capability()
            capability.execute(
                {"path": outside_path, "old_text": "secret", "new_text": "public"}
            )

            self.assertEqual(self._read(outside_path), original)

    def test_traversal_out_of_allowed_dir_is_rejected(self):
        with tempfile.TemporaryDirectory() as other_dir:
            outside_path = os.path.join(other_dir, "secret.txt")
            with open(outside_path, "w", encoding="utf-8") as fh:
                fh.write("top secret value")

            traversal_path = os.path.join(
                self.allowed_dir, "..", os.path.basename(other_dir), "secret.txt"
            )
            capability = self._capability()
            result = capability.execute(
                {"path": traversal_path, "old_text": "secret", "new_text": "public"}
            )

            self.assertFalse(result.success)

    def test_missing_file_is_rejected_without_creating_it(self):
        missing_path = os.path.join(self.allowed_dir, "does_not_exist.txt")
        capability = self._capability()

        result = capability.execute(
            {"path": missing_path, "old_text": "a", "new_text": "b"}
        )

        self.assertFalse(result.success)
        self.assertFalse(os.path.exists(missing_path))


# ----------------------------------------------------------------------
# 5. Successful editing returns structured metadata
# ----------------------------------------------------------------------
class TestSuccessfulEditReturnsStructuredMetadata(TextFileEditCapabilityTestBase):
    def test_metadata_contains_success_and_path(self):
        path = self._write("notes.txt", "hello world")
        capability = self._capability()

        result = capability.execute(
            {"path": path, "old_text": "world", "new_text": "there"}
        )

        self.assertTrue(result.output["success"])
        self.assertEqual(result.output["path"], os.path.realpath(path))

    def test_metadata_reports_occurrences_replaced(self):
        path = self._write("notes.txt", "hello world")
        capability = self._capability()

        result = capability.execute(
            {"path": path, "old_text": "world", "new_text": "there"}
        )

        self.assertEqual(result.output["occurrences_replaced"], 1)

    def test_metadata_reports_character_counts(self):
        path = self._write("notes.txt", "short")
        capability = self._capability()

        result = capability.execute(
            {"path": path, "old_text": "short", "new_text": "much longer text"}
        )

        self.assertEqual(result.output["characters_removed"], len("short"))
        self.assertEqual(result.output["characters_added"], len("much longer text"))
        self.assertEqual(result.output["character_count_before"], len("short"))
        self.assertEqual(
            result.output["character_count_after"], len("much longer text")
        )


# ----------------------------------------------------------------------
# 6. Registered and executable through the existing capability system
# ----------------------------------------------------------------------
class TestRegisteredAndExecutableThroughCapabilitySystem(TextFileEditCapabilityTestBase):
    def test_capability_is_a_real_capability_instance(self):
        capability = self._capability()
        self.assertIsInstance(capability, Capability)
        self.assertEqual(capability.name, CAPABILITY_NAME)

    def test_registers_into_executable_capability_registry(self):
        registry = ExecutableCapabilityRegistry()
        register_text_file_edit_capability(registry, allowed_dirs=[self.allowed_dir])

        self.assertTrue(registry.has(CAPABILITY_NAME))
        self.assertTrue(registry.is_available(CAPABILITY_NAME))

    def test_registers_into_capability_handler_registry(self):
        registry = CapabilityHandlerRegistry()
        register_text_file_edit_capability(registry, allowed_dirs=[self.allowed_dir])

        self.assertTrue(registry.is_capability(CAPABILITY_NAME))

    def test_executable_via_executable_capability_registry_directly(self):
        registry = ExecutableCapabilityRegistry()
        register_text_file_edit_capability(registry, allowed_dirs=[self.allowed_dir])
        path = self._write("via_registry.txt", "before edit")

        capability = registry.get(CAPABILITY_NAME)
        result = capability.execute(
            {"path": path, "old_text": "before", "new_text": "after"}
        )

        self.assertTrue(result.success)
        self.assertEqual(self._read(path), "after edit")

    def test_executable_through_execution_engine(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        engine = ExecutionEngine(plans)
        register_text_file_edit_capability(
            engine.executable_capabilities, allowed_dirs=[self.allowed_dir]
        )
        path = self._write("via_engine.txt", "engine content")

        result = engine.execute_registered_capability(
            CAPABILITY_NAME, {"path": path, "old_text": "engine", "new_text": "motor"}
        )

        self.assertEqual(result.status, STATUS_COMPLETED)
        self.assertEqual(self._read(path), "motor content")

    def test_disabled_registration_is_not_executable_through_engine(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        engine = ExecutionEngine(plans)
        register_text_file_edit_capability(
            engine.executable_capabilities,
            allowed_dirs=[self.allowed_dir],
            enabled=False,
        )
        path = self._write("disabled.txt", "should not change")

        result = engine.execute_registered_capability(
            CAPABILITY_NAME, {"path": path, "old_text": "should", "new_text": "will"}
        )

        self.assertEqual(result.status, STATUS_FAILED)
        self.assertEqual(self._read(path), "should not change")


if __name__ == "__main__":
    unittest.main()
