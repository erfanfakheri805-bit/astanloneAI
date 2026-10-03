"""
Tests for the built-in `project_structure_inspect` capability
(execution/project_structure_inspect_capability.py) - a real,
standard-library-only, read-only `Capability` that lists the files and
directories inside an allowed project/data directory.

Covers: a valid project directory returning its structure; files and
directories being identified correctly; unsafe paths being rejected;
the capability never modifying the project; the result respecting the
configured entry limit; and the capability being registered and
executable through the existing `ExecutableCapabilityRegistry` /
`ExecutionEngine` capability system.

Every test uses its own isolated temporary directory as the allowed
directory (via `allowed_dirs=`) - never the application's real
data/skills/temp directories - so this suite never touches, creates,
or depends on anything outside its own `tempfile.TemporaryDirectory`.

Run directly:
    python -m unittest tests.test_project_structure_inspect_capability -v
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
from execution.project_structure_inspect_capability import (
    CAPABILITY_NAME,
    create_project_structure_inspect_capability,
    register_project_structure_inspect_capability,
)
from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager


class ProjectStructureInspectCapabilityTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.allowed_dir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def _touch(self, *relative_parts, content=""):
        path = os.path.join(self.allowed_dir, *relative_parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return path

    def _mkdir(self, *relative_parts):
        path = os.path.join(self.allowed_dir, *relative_parts)
        os.makedirs(path, exist_ok=True)
        return path

    def _capability(self, **kwargs):
        return create_project_structure_inspect_capability(
            allowed_dirs=[self.allowed_dir], **kwargs
        )

    def _snapshot(self):
        """A plain (path -> mtime/size) fingerprint of everything under
        the allowed dir, used to assert the capability never modifies
        the project it inspects."""
        fingerprint = {}
        for current_dir, dir_names, file_names in os.walk(self.allowed_dir):
            for name in dir_names + file_names:
                full_path = os.path.join(current_dir, name)
                stat = os.stat(full_path)
                fingerprint[full_path] = (stat.st_mtime_ns, stat.st_size)
        return fingerprint


# ----------------------------------------------------------------------
# 1. A valid project directory returns its structure
# ----------------------------------------------------------------------
class TestValidProjectDirectoryReturnsStructure(ProjectStructureInspectCapabilityTestBase):
    def test_returns_a_successful_result_for_an_allowed_directory(self):
        self._touch("readme.txt", content="hello")
        self._mkdir("src")
        capability = self._capability()

        result = capability.execute({"path": self.allowed_dir})

        self.assertTrue(result.success)
        self.assertIsNone(result.error)

    def test_structure_includes_every_top_level_entry(self):
        self._touch("readme.txt", content="hello")
        self._mkdir("src")
        capability = self._capability()

        result = capability.execute({"path": self.allowed_dir})

        paths = {entry["path"] for entry in result.output["entries"]}
        self.assertIn("readme.txt", paths)
        self.assertIn("src", paths)

    def test_structure_includes_nested_entries_with_relative_paths(self):
        self._touch("src", "main.py", content="print('hi')")
        capability = self._capability()

        result = capability.execute({"path": self.allowed_dir})

        paths = {entry["path"] for entry in result.output["entries"]}
        self.assertIn(os.path.join("src", "main.py"), paths)


# ----------------------------------------------------------------------
# 2. Files and directories are identified correctly
# ----------------------------------------------------------------------
class TestFilesAndDirectoriesAreIdentifiedCorrectly(ProjectStructureInspectCapabilityTestBase):
    def test_a_file_is_reported_as_type_file(self):
        self._touch("readme.txt", content="hello")
        capability = self._capability()

        result = capability.execute({"path": self.allowed_dir})

        entry = next(e for e in result.output["entries"] if e["path"] == "readme.txt")
        self.assertEqual(entry["type"], "file")

    def test_a_directory_is_reported_as_type_directory(self):
        self._mkdir("src")
        capability = self._capability()

        result = capability.execute({"path": self.allowed_dir})

        entry = next(e for e in result.output["entries"] if e["path"] == "src")
        self.assertEqual(entry["type"], "directory")

    def test_mixed_tree_reports_each_entry_with_the_right_type(self):
        self._mkdir("src")
        self._touch("src", "main.py", content="x")
        self._touch("notes.md", content="y")
        capability = self._capability()

        result = capability.execute({"path": self.allowed_dir})

        by_path = {entry["path"]: entry["type"] for entry in result.output["entries"]}
        self.assertEqual(by_path["src"], "directory")
        self.assertEqual(by_path[os.path.join("src", "main.py")], "file")
        self.assertEqual(by_path["notes.md"], "file")


# ----------------------------------------------------------------------
# 3. Unsafe paths are rejected
# ----------------------------------------------------------------------
class TestUnsafePathsAreRejected(ProjectStructureInspectCapabilityTestBase):
    def test_path_outside_allowed_dir_is_rejected(self):
        with tempfile.TemporaryDirectory() as other_dir:
            capability = self._capability()

            result = capability.execute({"path": other_dir})

            self.assertFalse(result.success)
            self.assertIn("outside", result.error.lower())

    def test_traversal_out_of_allowed_dir_is_rejected(self):
        with tempfile.TemporaryDirectory() as other_dir:
            traversal_path = os.path.join(
                self.allowed_dir, "..", os.path.basename(other_dir)
            )
            capability = self._capability()

            result = capability.execute({"path": traversal_path})

            self.assertFalse(result.success)

    def test_missing_directory_is_rejected(self):
        missing_path = os.path.join(self.allowed_dir, "does_not_exist")
        capability = self._capability()

        result = capability.execute({"path": missing_path})

        self.assertFalse(result.success)

    def test_file_path_is_rejected_as_not_a_directory(self):
        path = self._touch("readme.txt", content="hello")
        capability = self._capability()

        result = capability.execute({"path": path})

        self.assertFalse(result.success)


# ----------------------------------------------------------------------
# 4. The capability does not modify the project
# ----------------------------------------------------------------------
class TestCapabilityDoesNotModifyProject(ProjectStructureInspectCapabilityTestBase):
    def test_no_new_files_or_directories_are_created(self):
        self._touch("readme.txt", content="hello")
        self._mkdir("src")
        before = set(os.listdir(self.allowed_dir))
        capability = self._capability()

        capability.execute({"path": self.allowed_dir})

        after = set(os.listdir(self.allowed_dir))
        self.assertEqual(before, after)

    def test_existing_file_contents_are_unchanged(self):
        path = self._touch("readme.txt", content="original content")
        fingerprint_before = self._snapshot()
        capability = self._capability()

        capability.execute({"path": self.allowed_dir})

        with open(path, "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "original content")
        self.assertEqual(self._snapshot(), fingerprint_before)

    def test_repeated_inspection_never_changes_the_tree(self):
        self._touch("a.txt", content="a")
        self._mkdir("b")
        capability = self._capability()

        capability.execute({"path": self.allowed_dir})
        fingerprint_after_first = self._snapshot()
        capability.execute({"path": self.allowed_dir})
        fingerprint_after_second = self._snapshot()

        self.assertEqual(fingerprint_after_first, fingerprint_after_second)


# ----------------------------------------------------------------------
# 5. The result respects the configured limit
# ----------------------------------------------------------------------
class TestResultRespectsConfiguredLimit(ProjectStructureInspectCapabilityTestBase):
    def test_entry_count_never_exceeds_the_limit(self):
        for index in range(10):
            self._touch(f"file_{index}.txt", content="x")
        capability = self._capability(max_entries=3)

        result = capability.execute({"path": self.allowed_dir})

        self.assertLessEqual(len(result.output["entries"]), 3)
        self.assertEqual(result.output["entry_count"], len(result.output["entries"]))

    def test_truncated_flag_is_true_when_limit_is_exceeded(self):
        for index in range(10):
            self._touch(f"file_{index}.txt", content="x")
        capability = self._capability(max_entries=3)

        result = capability.execute({"path": self.allowed_dir})

        self.assertTrue(result.output["truncated"])
        self.assertEqual(result.output["limit"], 3)

    def test_truncated_flag_is_false_when_under_the_limit(self):
        self._touch("only_file.txt", content="x")
        capability = self._capability(max_entries=100)

        result = capability.execute({"path": self.allowed_dir})

        self.assertFalse(result.output["truncated"])


# ----------------------------------------------------------------------
# 6. Registered and executable through the existing capability system
# ----------------------------------------------------------------------
class TestRegisteredAndExecutableThroughCapabilitySystem(ProjectStructureInspectCapabilityTestBase):
    def test_capability_is_a_real_capability_instance(self):
        capability = self._capability()
        self.assertIsInstance(capability, Capability)
        self.assertEqual(capability.name, CAPABILITY_NAME)

    def test_registers_into_executable_capability_registry(self):
        registry = ExecutableCapabilityRegistry()
        register_project_structure_inspect_capability(
            registry, allowed_dirs=[self.allowed_dir]
        )

        self.assertTrue(registry.has(CAPABILITY_NAME))
        self.assertTrue(registry.is_available(CAPABILITY_NAME))

    def test_registers_into_capability_handler_registry(self):
        registry = CapabilityHandlerRegistry()
        register_project_structure_inspect_capability(
            registry, allowed_dirs=[self.allowed_dir]
        )

        self.assertTrue(registry.is_capability(CAPABILITY_NAME))

    def test_executable_via_executable_capability_registry_directly(self):
        self._touch("a.txt", content="x")
        registry = ExecutableCapabilityRegistry()
        register_project_structure_inspect_capability(
            registry, allowed_dirs=[self.allowed_dir]
        )

        capability = registry.get(CAPABILITY_NAME)
        result = capability.execute({"path": self.allowed_dir})

        self.assertTrue(result.success)
        paths = {entry["path"] for entry in result.output["entries"]}
        self.assertIn("a.txt", paths)

    def test_executable_through_execution_engine(self):
        self._touch("a.txt", content="x")
        goals = GoalManager()
        plans = PlanManager(goals)
        engine = ExecutionEngine(plans)
        register_project_structure_inspect_capability(
            engine.executable_capabilities, allowed_dirs=[self.allowed_dir]
        )

        result = engine.execute_registered_capability(
            CAPABILITY_NAME, {"path": self.allowed_dir}
        )

        self.assertEqual(result.status, STATUS_COMPLETED)
        paths = {entry["path"] for entry in result.output["entries"]}
        self.assertIn("a.txt", paths)

    def test_disabled_registration_is_not_executable_through_engine(self):
        goals = GoalManager()
        plans = PlanManager(goals)
        engine = ExecutionEngine(plans)
        register_project_structure_inspect_capability(
            engine.executable_capabilities,
            allowed_dirs=[self.allowed_dir],
            enabled=False,
        )

        result = engine.execute_registered_capability(
            CAPABILITY_NAME, {"path": self.allowed_dir}
        )

        self.assertEqual(result.status, STATUS_FAILED)


if __name__ == "__main__":
    unittest.main()
