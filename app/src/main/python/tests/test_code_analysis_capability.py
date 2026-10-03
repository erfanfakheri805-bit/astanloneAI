"""
Tests for the built-in `code_analysis` capability
(execution/code_analysis_capability.py) - connecting the project's
*existing* AST-based analysis implementation
(code_intelligence/python_inspector.py's `inspect_source`, unchanged)
to the Capability Registry / Agent execution path
(`ExecutableCapabilityRegistry` / `ExecutionEngine.execute_registered_capability`)
that the other built-in capabilities already run through.

Covers: the capability being invocable the same way `AgentLoop`'s own
execution stack invokes any other registered capability (through
`ExecutionEngine.execute_registered_capability`, out of an
`ExecutableCapabilityRegistry`); valid Python source producing a
structured analysis result; invalid (syntactically broken) Python
being reported safely, never raised; the analyzed source file never
being modified; unsafe paths being rejected; and this addition never
touching or breaking anything the existing `python_inspector`/
`text_file_read_capability` test suites already cover.

Every test uses its own isolated temporary directory as the allowed
directory (via `allowed_dirs=`) - never the application's real
data/skills/temp directories - so this suite never touches, creates,
or depends on anything outside its own `tempfile.TemporaryDirectory`.

Run directly:
    python -m unittest tests.test_code_analysis_capability -v
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
from execution.code_analysis_capability import (
    CAPABILITY_NAME,
    create_code_analysis_capability,
    register_code_analysis_capability,
)
from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager

VALID_SOURCE = (
    "import os\n\n"
    "class Greeter:\n"
    "    def greet(self, name):\n"
    "        return 'hi ' + name\n"
)

INVALID_SOURCE = "def broken(:\n    pass\n"


class CodeAnalysisCapabilityTestBase(unittest.TestCase):
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
        return create_code_analysis_capability(allowed_dirs=[self.allowed_dir], **kwargs)


# ----------------------------------------------------------------------
# 1. Agent can invoke the existing code_analysis capability
# ----------------------------------------------------------------------
class TestAgentCanInvokeCodeAnalysisCapability(CodeAnalysisCapabilityTestBase):
    def test_capability_is_a_real_capability_instance(self):
        capability = self._capability()
        self.assertIsInstance(capability, Capability)
        self.assertEqual(capability.name, CAPABILITY_NAME)

    def test_registers_into_executable_capability_registry(self):
        registry = ExecutableCapabilityRegistry()
        register_code_analysis_capability(registry, allowed_dirs=[self.allowed_dir])

        self.assertTrue(registry.has(CAPABILITY_NAME))
        self.assertTrue(registry.is_available(CAPABILITY_NAME))

    def test_registers_into_capability_handler_registry(self):
        registry = CapabilityHandlerRegistry()
        register_code_analysis_capability(registry, allowed_dirs=[self.allowed_dir])

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
        register_code_analysis_capability(
            engine.executable_capabilities, allowed_dirs=[self.allowed_dir]
        )

        result = engine.execute_registered_capability(CAPABILITY_NAME, {"path": path})

        self.assertEqual(result.status, STATUS_COMPLETED)
        self.assertTrue(result.output["analysis"]["valid"])

    def test_disabled_registration_is_not_executable_through_engine(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        goals = GoalManager()
        plans = PlanManager(goals)
        engine = ExecutionEngine(plans)
        register_code_analysis_capability(
            engine.executable_capabilities,
            allowed_dirs=[self.allowed_dir],
            enabled=False,
        )

        result = engine.execute_registered_capability(CAPABILITY_NAME, {"path": path})

        self.assertEqual(result.status, STATUS_FAILED)


# ----------------------------------------------------------------------
# 2. Valid Python code returns a structured analysis result
# ----------------------------------------------------------------------
class TestValidPythonCodeReturnsStructuredResult(CodeAnalysisCapabilityTestBase):
    def test_result_is_successful(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        capability = self._capability()

        result = capability.execute({"path": path})

        self.assertTrue(result.success)
        self.assertIsNone(result.error)

    def test_analysis_reports_valid_true(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        capability = self._capability()

        result = capability.execute({"path": path})

        self.assertTrue(result.output["analysis"]["valid"])
        self.assertIsNone(result.output["analysis"]["syntax_error"])

    def test_analysis_reports_functions_classes_and_imports(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        capability = self._capability()

        result = capability.execute({"path": path})

        analysis = result.output["analysis"]
        class_names = {c["name"] for c in analysis["classes"]}
        function_names = {f["name"] for f in analysis["functions"]}
        import_modules = {i["module"] for i in analysis["imports"]}
        self.assertIn("Greeter", class_names)
        self.assertIn("greet", function_names)
        self.assertIn("os", import_modules)

    def test_result_matches_calling_inspect_source_directly(self):
        """Same result the already-existing `inspect_source` produces
        for identical source - proof this is a connection, not a
        second, differently-behaving analysis implementation."""
        from code_intelligence.python_inspector import inspect_source

        path = self._write("thing.py", content=VALID_SOURCE)
        capability = self._capability()

        result = capability.execute({"path": path})
        direct = inspect_source(VALID_SOURCE, filename=path)

        self.assertEqual(result.output["analysis"], direct)


# ----------------------------------------------------------------------
# 3. Invalid Python code is reported safely
# ----------------------------------------------------------------------
class TestInvalidPythonCodeIsReportedSafely(CodeAnalysisCapabilityTestBase):
    def test_result_is_still_a_successful_capability_execution(self):
        path = self._write("broken.py", content=INVALID_SOURCE)
        capability = self._capability()

        result = capability.execute({"path": path})

        # Analyzing broken source is not a capability-level failure -
        # the capability ran fine; it's the *analysis* that reports
        # the syntax problem.
        self.assertTrue(result.success)

    def test_analysis_reports_valid_false_with_syntax_error(self):
        path = self._write("broken.py", content=INVALID_SOURCE)
        capability = self._capability()

        result = capability.execute({"path": path})

        analysis = result.output["analysis"]
        self.assertFalse(analysis["valid"])
        self.assertIsNotNone(analysis["syntax_error"])
        self.assertIn("line", analysis["syntax_error"])

    def test_never_raises_for_broken_source(self):
        path = self._write("broken.py", content=INVALID_SOURCE)
        capability = self._capability()

        try:
            capability.execute({"path": path})
        except Exception as exc:  # pragma: no cover - failure path
            self.fail(f"execute() raised for invalid Python source: {exc!r}")


# ----------------------------------------------------------------------
# 4. Analysis does not modify the source file
# ----------------------------------------------------------------------
class TestAnalysisDoesNotModifySourceFile(CodeAnalysisCapabilityTestBase):
    def test_file_contents_are_unchanged_after_analysis(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        capability = self._capability()

        capability.execute({"path": path})

        with open(path, "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read(), VALID_SOURCE)

    def test_file_mtime_and_size_are_unchanged(self):
        path = self._write("thing.py", content=VALID_SOURCE)
        stat_before = os.stat(path)
        capability = self._capability()

        capability.execute({"path": path})

        stat_after = os.stat(path)
        self.assertEqual(stat_before.st_mtime_ns, stat_after.st_mtime_ns)
        self.assertEqual(stat_before.st_size, stat_after.st_size)

    def test_no_new_files_are_created_in_the_directory(self):
        self._write("thing.py", content=VALID_SOURCE)
        before = set(os.listdir(self.allowed_dir))
        capability = self._capability()

        capability.execute({"path": os.path.join(self.allowed_dir, "thing.py")})

        after = set(os.listdir(self.allowed_dir))
        self.assertEqual(before, after)

    def test_analyzing_broken_source_also_leaves_file_untouched(self):
        path = self._write("broken.py", content=INVALID_SOURCE)
        stat_before = os.stat(path)
        capability = self._capability()

        capability.execute({"path": path})

        stat_after = os.stat(path)
        self.assertEqual(stat_before.st_mtime_ns, stat_after.st_mtime_ns)


# ----------------------------------------------------------------------
# 5. Unsafe paths are rejected
# ----------------------------------------------------------------------
class TestUnsafePathsAreRejected(CodeAnalysisCapabilityTestBase):
    def test_path_outside_allowed_dir_is_rejected(self):
        with tempfile.TemporaryDirectory() as other_dir:
            other_file = os.path.join(other_dir, "outside.py")
            with open(other_file, "w", encoding="utf-8") as fh:
                fh.write(VALID_SOURCE)
            capability = self._capability()

            result = capability.execute({"path": other_file})

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

            result = capability.execute({"path": traversal_path})

            self.assertFalse(result.success)

    def test_missing_file_is_rejected(self):
        missing_path = os.path.join(self.allowed_dir, "does_not_exist.py")
        capability = self._capability()

        result = capability.execute({"path": missing_path})

        self.assertFalse(result.success)

    def test_directory_path_is_rejected(self):
        capability = self._capability()

        result = capability.execute({"path": self.allowed_dir})

        self.assertFalse(result.success)

    def test_non_python_extension_is_rejected(self):
        path = self._write("notes.txt", content="just some text")
        capability = self._capability()

        result = capability.execute({"path": path})

        self.assertFalse(result.success)
        self.assertIn(".py", result.error)

    def test_missing_path_field_is_rejected_by_input_validation(self):
        capability = self._capability()

        result = capability.execute({})

        self.assertFalse(result.success)
        self.assertFalse(result.validation.valid)


# ----------------------------------------------------------------------
# 6. Existing tests remain compatible
# ----------------------------------------------------------------------
class TestExistingBehaviorRemainsCompatible(CodeAnalysisCapabilityTestBase):
    def test_python_inspector_module_is_unmodified_and_importable(self):
        from code_intelligence.python_inspector import inspect_source

        result = inspect_source(VALID_SOURCE)
        self.assertTrue(result["valid"])

    def test_text_file_read_capability_is_unaffected(self):
        """`text_file_read_capability.py` is reused, not modified -
        its own capability keeps working exactly as before, including
        for non-.py text files that `code_analysis` itself refuses."""
        from execution.text_file_read_capability import create_text_file_read_capability

        path = self._write("notes.txt", content="hello world")
        read_capability = create_text_file_read_capability(allowed_dirs=[self.allowed_dir])

        result = read_capability.execute({"path": path})

        self.assertTrue(result.success)
        self.assertEqual(result.output["text"], "hello world")

    def test_capability_output_schema_is_json_shaped(self):
        capability = self._capability()
        description = capability.describe()

        self.assertEqual(description["name"], CAPABILITY_NAME)
        self.assertIn("path", description["output_schema"]["properties"])
        self.assertIn("analysis", description["output_schema"]["properties"])


if __name__ == "__main__":
    unittest.main()
