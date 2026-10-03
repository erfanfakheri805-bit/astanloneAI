"""
Tests for the built-in `text_file_write` capability
(execution/text_file_write_capability.py) - a real, standard-library-
only `Capability` that safely writes text content to a file inside an
allowed directory.

Covers: writing a new text file successfully; the returned metadata
being correct; an existing file being protected when `overwrite` isn't
explicitly enabled; explicit overwrite working; paths outside the
allowed directories being rejected; and the capability being
registered and executable through the existing
`ExecutableCapabilityRegistry` / `ExecutionEngine` capability system.

Every test uses its own isolated temporary directory as the allowed
directory (via `allowed_dirs=`) - never the application's real
data/skills/temp directories - so this suite never touches, creates,
or depends on anything outside its own `tempfile.TemporaryDirectory`.

Run directly:
    python -m unittest tests.test_text_file_write_capability -v
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
from execution.text_file_write_capability import (
    CAPABILITY_NAME,
    create_text_file_write_capability,
    register_text_file_write_capability,
)
from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager


class TextFileWriteCapabilityTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.allowed_dir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def _path(self, name):
        return os.path.join(self.allowed_dir, name)

    def _capability(self, **kwargs):
        return create_text_file_write_capability(
            allowed_dirs=[self.allowed_dir], **kwargs
        )


# ----------------------------------------------------------------------
# 1. Writing a new text file succeeds
# ----------------------------------------------------------------------
class TestWritingNewFileSucceeds(TextFileWriteCapabilityTestBase):
    def test_writing_a_new_text_file_succeeds(self):
        path = self._path("notes.txt")
        capability = self._capability()

        result = capability.execute({"path": path, "text": "hello world"})

        self.assertTrue(result.success)
        self.assertIsNone(result.error)

    def test_file_actually_exists_on_disk_with_the_right_content(self):
        path = self._path("notes.txt")
        capability = self._capability()

        capability.execute({"path": path, "text": "hello world"})

        with open(path, "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "hello world")

    def test_parent_directories_inside_allowed_dir_are_created(self):
        path = self._path(os.path.join("nested", "deeper", "notes.txt"))
        capability = self._capability()

        result = capability.execute({"path": path, "text": "deep"})

        self.assertTrue(result.success)
        self.assertTrue(os.path.isfile(path))


# ----------------------------------------------------------------------
# 2. Returned metadata is correct
# ----------------------------------------------------------------------
class TestReturnedMetadataIsCorrect(TextFileWriteCapabilityTestBase):
    def test_metadata_contains_path_and_character_count(self):
        path = self._path("data.txt")
        content = "abcde"
        capability = self._capability()

        result = capability.execute({"path": path, "text": content})

        self.assertEqual(result.output["path"], os.path.realpath(path))
        self.assertEqual(result.output["character_count"], len(content))

    def test_metadata_byte_size_matches_file_on_disk(self):
        path = self._path("data.txt")
        content = "hello\nworld\n"
        capability = self._capability()

        result = capability.execute({"path": path, "text": content})

        self.assertEqual(result.output["byte_size"], os.path.getsize(path))

    def test_metadata_reports_created_true_for_a_new_file(self):
        path = self._path("new_file.txt")
        capability = self._capability()

        result = capability.execute({"path": path, "text": "x"})

        self.assertTrue(result.output["created"])
        self.assertFalse(result.output["overwritten"])


# ----------------------------------------------------------------------
# 3. Existing files are protected when overwrite is not explicitly enabled
# ----------------------------------------------------------------------
class TestExistingFilesAreProtected(TextFileWriteCapabilityTestBase):
    def test_existing_file_is_not_overwritten_by_default(self):
        path = self._path("protected.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("original content")
        capability = self._capability()

        result = capability.execute({"path": path, "text": "new content"})

        self.assertFalse(result.success)
        with open(path, "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "original content")

    def test_existing_file_default_rejection_mentions_overwrite(self):
        path = self._path("protected.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("original content")
        capability = self._capability()

        result = capability.execute({"path": path, "text": "new content"})

        self.assertIn("overwrite", result.error.lower())

    def test_overwrite_false_explicitly_still_protects_existing_file(self):
        path = self._path("protected.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("original content")
        capability = self._capability()

        result = capability.execute(
            {"path": path, "text": "new content", "overwrite": False}
        )

        self.assertFalse(result.success)


# ----------------------------------------------------------------------
# 4. Explicit overwrite works
# ----------------------------------------------------------------------
class TestExplicitOverwriteWorks(TextFileWriteCapabilityTestBase):
    def test_explicit_overwrite_succeeds(self):
        path = self._path("protected.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("original content")
        capability = self._capability()

        result = capability.execute(
            {"path": path, "text": "new content", "overwrite": True}
        )

        self.assertTrue(result.success)
        with open(path, "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "new content")

    def test_explicit_overwrite_reports_overwritten_true(self):
        path = self._path("protected.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("original content")
        capability = self._capability()

        result = capability.execute(
            {"path": path, "text": "new content", "overwrite": True}
        )

        self.assertTrue(result.output["overwritten"])
        self.assertFalse(result.output["created"])


# ----------------------------------------------------------------------
# 5. Paths outside allowed directories are rejected
# ----------------------------------------------------------------------
class TestPathsOutsideAllowedDirectoriesAreRejected(TextFileWriteCapabilityTestBase):
    def test_path_outside_allowed_dir_is_rejected(self):
        with tempfile.TemporaryDirectory() as other_dir:
            outside_path = os.path.join(other_dir, "sneaky.txt")
            capability = self._capability()

            result = capability.execute({"path": outside_path, "text": "nope"})

            self.assertFalse(result.success)
            self.assertIn("outside", result.error.lower())
            self.assertFalse(os.path.exists(outside_path))

    def test_traversal_out_of_allowed_dir_is_rejected(self):
        with tempfile.TemporaryDirectory() as other_dir:
            traversal_path = os.path.join(
                self.allowed_dir, "..", os.path.basename(other_dir), "sneaky.txt"
            )
            capability = self._capability()

            result = capability.execute({"path": traversal_path, "text": "nope"})

            self.assertFalse(result.success)

    def test_parent_directory_is_never_created_outside_allowed_dir(self):
        with tempfile.TemporaryDirectory() as other_dir:
            outside_nested_path = os.path.join(other_dir, "nested", "sneaky.txt")
            capability = self._capability()

            capability.execute({"path": outside_nested_path, "text": "nope"})

            self.assertFalse(os.path.isdir(os.path.join(other_dir, "nested")))


# ----------------------------------------------------------------------
# 6. Registered and executable through the existing capability system
# ----------------------------------------------------------------------
class TestRegisteredAndExecutableThroughCapabilitySystem(TextFileWriteCapabilityTestBase):
    def test_capability_is_a_real_capability_instance(self):
        capability = self._capability()
        self.assertIsInstance(capability, Capability)
        self.assertEqual(capability.name, CAPABILITY_NAME)

    def test_registers_into_executable_capability_registry(self):
        registry = ExecutableCapabilityRegistry()
        register_text_file_write_capability(registry, allowed_dirs=[self.allowed_dir])

        self.assertTrue(registry.has(CAPABILITY_NAME))
        self.assertTrue(registry.is_available(CAPABILITY_NAME))

    def test_registers_into_capability_handler_registry(self):
        registry = CapabilityHandlerRegistry()
        register_text_file_write_capability(registry, allowed_dirs=[self.allowed_dir])

        self.assertTrue(registry.is_capability(CAPABILITY_NAME))

    def test_executable_via_executable_capability_registry_directly(self):
        registry = ExecutableCapabilityRegistry()
        register_text_file_write_capability(registry, allowed_dirs=[self.allowed_dir])
        path = self._path("via_registry.txt")

        capability = registry.get(CAPABILITY_NAME)
        result = capability.execute({"path": path, "text": "registered and writable"})

        self.assertTrue(result.success)
        with open(path, "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "registered and writable")

    def test_executable_through_execution_engine(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        engine = ExecutionEngine(plans)
        register_text_file_write_capability(
            engine.executable_capabilities, allowed_dirs=[self.allowed_dir]
        )
        path = self._path("via_engine.txt")

        result = engine.execute_registered_capability(
            CAPABILITY_NAME, {"path": path, "text": "engine can write this"}
        )

        self.assertEqual(result.status, STATUS_COMPLETED)
        self.assertTrue(os.path.isfile(path))

    def test_disabled_registration_is_not_executable_through_engine(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        engine = ExecutionEngine(plans)
        register_text_file_write_capability(
            engine.executable_capabilities,
            allowed_dirs=[self.allowed_dir],
            enabled=False,
        )
        path = self._path("disabled.txt")

        result = engine.execute_registered_capability(
            CAPABILITY_NAME, {"path": path, "text": "should not be written"}
        )

        self.assertEqual(result.status, STATUS_FAILED)
        self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
