"""
Tests for the built-in `text_file_read` capability
(execution/text_file_read_capability.py) - a real, standard-library-
only `Capability` that safely reads a text file from an allowed
directory.

Covers: reading an allowed text file successfully; the returned output
containing the text and basic metadata; missing files failing safely;
paths outside the allowed directories being rejected; binary/
unsupported files being rejected safely; and the capability being
registered and executable through the existing
`ExecutableCapabilityRegistry` / `ExecutionEngine` capability system.

Every test uses its own isolated temporary directory as the allowed
directory (via `allowed_dirs=`) - never the application's real
data/skills/temp directories - so this suite never touches, creates,
or depends on anything outside its own `tempfile.TemporaryDirectory`.

Run directly:
    python -m unittest tests.test_text_file_read_capability -v
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
from execution.text_file_read_capability import (
    CAPABILITY_NAME,
    create_text_file_read_capability,
    register_text_file_read_capability,
)
from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager


class TextFileReadCapabilityTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.allowed_dir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def _write(self, name, content, binary=False):
        path = os.path.join(self.allowed_dir, name)
        if binary:
            with open(path, "wb") as fh:
                fh.write(content)
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
        return path

    def _capability(self, **kwargs):
        return create_text_file_read_capability(
            allowed_dirs=[self.allowed_dir], **kwargs
        )


# ----------------------------------------------------------------------
# 1. Reading an allowed text file succeeds
# ----------------------------------------------------------------------
class TestAllowedFileReadSucceeds(TextFileReadCapabilityTestBase):
    def test_reading_an_allowed_text_file_succeeds(self):
        path = self._write("notes.txt", "hello world")
        capability = self._capability()

        result = capability.execute({"path": path})

        self.assertTrue(result.success)
        self.assertIsNone(result.error)


# ----------------------------------------------------------------------
# 2. Returned output contains the text and metadata
# ----------------------------------------------------------------------
class TestOutputContainsTextAndMetadata(TextFileReadCapabilityTestBase):
    def test_output_contains_the_full_text(self):
        content = "line one\nline two\n"
        path = self._write("data.txt", content)
        capability = self._capability()

        result = capability.execute({"path": path})

        self.assertEqual(result.output["text"], content)

    def test_output_contains_path_and_character_count(self):
        content = "abcde"
        path = self._write("small.txt", content)
        capability = self._capability()

        result = capability.execute({"path": path})

        self.assertEqual(result.output["path"], os.path.realpath(path))
        self.assertEqual(result.output["character_count"], len(content))

    def test_output_contains_byte_size_and_line_count(self):
        content = "a\nb\nc"
        path = self._write("lines.txt", content)
        capability = self._capability()

        result = capability.execute({"path": path})

        self.assertEqual(result.output["byte_size"], os.path.getsize(path))
        self.assertEqual(result.output["line_count"], 3)


# ----------------------------------------------------------------------
# 3. Missing files fail safely
# ----------------------------------------------------------------------
class TestMissingFilesFailSafely(TextFileReadCapabilityTestBase):
    def test_missing_file_returns_failed_result(self):
        missing_path = os.path.join(self.allowed_dir, "does_not_exist.txt")
        capability = self._capability()

        result = capability.execute({"path": missing_path})

        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)

    def test_missing_file_never_raises(self):
        missing_path = os.path.join(self.allowed_dir, "nope.txt")
        capability = self._capability()

        try:
            capability.execute({"path": missing_path})
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"execute() raised for a missing file: {exc}")

    def test_directory_path_is_rejected_as_not_a_file(self):
        subdir = os.path.join(self.allowed_dir, "a_directory")
        os.makedirs(subdir)
        capability = self._capability()

        result = capability.execute({"path": subdir})

        self.assertFalse(result.success)


# ----------------------------------------------------------------------
# 4. Paths outside allowed directories are rejected
# ----------------------------------------------------------------------
class TestPathsOutsideAllowedDirectoriesAreRejected(TextFileReadCapabilityTestBase):
    def test_path_outside_allowed_dir_is_rejected(self):
        with tempfile.TemporaryDirectory() as other_dir:
            outside_path = os.path.join(other_dir, "secret.txt")
            with open(outside_path, "w", encoding="utf-8") as fh:
                fh.write("top secret")

            capability = self._capability()
            result = capability.execute({"path": outside_path})

            self.assertFalse(result.success)
            self.assertIn("outside", result.error.lower())

    def test_traversal_out_of_allowed_dir_is_rejected(self):
        with tempfile.TemporaryDirectory() as other_dir:
            outside_path = os.path.join(other_dir, "secret.txt")
            with open(outside_path, "w", encoding="utf-8") as fh:
                fh.write("top secret")

            traversal_path = os.path.join(
                self.allowed_dir, "..", os.path.basename(other_dir), "secret.txt"
            )
            capability = self._capability()
            result = capability.execute({"path": traversal_path})

            self.assertFalse(result.success)

    def test_outside_path_never_leaks_file_contents(self):
        with tempfile.TemporaryDirectory() as other_dir:
            outside_path = os.path.join(other_dir, "secret.txt")
            with open(outside_path, "w", encoding="utf-8") as fh:
                fh.write("top secret")

            capability = self._capability()
            result = capability.execute({"path": outside_path})

            self.assertIsNone(result.output)


# ----------------------------------------------------------------------
# 5. Binary/unsupported files are rejected safely
# ----------------------------------------------------------------------
class TestBinaryAndUnsupportedFilesAreRejected(TextFileReadCapabilityTestBase):
    def test_binary_file_with_recognized_extension_is_rejected(self):
        path = self._write("fake.txt", b"\x00\x01\x02binarydata", binary=True)
        capability = self._capability()

        result = capability.execute({"path": path})

        self.assertFalse(result.success)

    def test_unrecognized_extension_is_rejected(self):
        path = self._write("archive.bin", "not actually checked for content")
        capability = self._capability()

        result = capability.execute({"path": path})

        self.assertFalse(result.success)

    def test_rejected_file_never_raises(self):
        path = self._write("image.png", b"\x89PNG\r\n\x1a\nrestofdata", binary=True)
        capability = self._capability()

        try:
            result = capability.execute({"path": path})
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"execute() raised for a binary file: {exc}")
        self.assertFalse(result.success)


# ----------------------------------------------------------------------
# 6. Registered and executable through the existing capability system
# ----------------------------------------------------------------------
class TestRegisteredAndExecutableThroughCapabilitySystem(TextFileReadCapabilityTestBase):
    def test_capability_is_a_real_capability_instance(self):
        capability = self._capability()
        self.assertIsInstance(capability, Capability)
        self.assertEqual(capability.name, CAPABILITY_NAME)

    def test_registers_into_executable_capability_registry(self):
        registry = ExecutableCapabilityRegistry()
        register_text_file_read_capability(registry, allowed_dirs=[self.allowed_dir])

        self.assertTrue(registry.has(CAPABILITY_NAME))
        self.assertTrue(registry.is_available(CAPABILITY_NAME))

    def test_registers_into_capability_handler_registry(self):
        registry = CapabilityHandlerRegistry()
        register_text_file_read_capability(registry, allowed_dirs=[self.allowed_dir])

        self.assertTrue(registry.is_capability(CAPABILITY_NAME))

    def test_executable_via_executable_capability_registry_directly(self):
        registry = ExecutableCapabilityRegistry()
        register_text_file_read_capability(registry, allowed_dirs=[self.allowed_dir])
        path = self._write("via_registry.txt", "registered and readable")

        capability = registry.get(CAPABILITY_NAME)
        result = capability.execute({"path": path})

        self.assertTrue(result.success)
        self.assertEqual(result.output["text"], "registered and readable")

    def test_executable_through_execution_engine(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        engine = ExecutionEngine(plans)
        register_text_file_read_capability(
            engine.executable_capabilities, allowed_dirs=[self.allowed_dir]
        )
        path = self._write("via_engine.txt", "engine can read this")

        result = engine.execute_registered_capability(CAPABILITY_NAME, {"path": path})

        self.assertEqual(result.status, STATUS_COMPLETED)
        self.assertEqual(result.output["text"], "engine can read this")

    def test_disabled_registration_is_not_executable_through_engine(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        engine = ExecutionEngine(plans)
        register_text_file_read_capability(
            engine.executable_capabilities,
            allowed_dirs=[self.allowed_dir],
            enabled=False,
        )
        path = self._write("disabled.txt", "should not be read")

        result = engine.execute_registered_capability(CAPABILITY_NAME, {"path": path})

        self.assertEqual(result.status, STATUS_FAILED)


if __name__ == "__main__":
    unittest.main()
