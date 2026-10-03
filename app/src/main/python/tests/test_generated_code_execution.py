"""
Tests for `code_generation/generated_code_execution.py`'s
`execute_generated_code` (Prompt 338) - connects an already-generated,
validated, and safely-written `CodeGenerationResult` to the existing
`self_upgrade.sandbox.Sandbox` static gate and the existing
`python_test_runner` capability so a newly generated Python file can
actually be run, under the same allowed-directory/timeout safety rules
those two already enforce.

Covers: a valid generated file executing successfully; invalid
(unparseable) generated code being rejected before any execution is
attempted; a target path outside the allowed directory being rejected;
a long-running generated file being handled by the existing timeout
mechanism; and a generated file that raises while being imported
producing a structured (not exception-raising) failure.

Every test uses its own isolated `tempfile.TemporaryDirectory` as the
allowed directory (via `allowed_dirs=`) - never the application's real
data/skills/temp directories.

Run directly:
    python -m unittest tests.test_generated_code_execution -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from code_generation.code_generation_result import CodeGenerationResult, STATUS_GENERATED
from code_generation.generated_code_execution import (
    execute_generated_code,
    STATUS_EXECUTED,
    STATUS_FAILED,
    STATUS_TIMEOUT,
    STATUS_REJECTED,
    ALL_EXECUTION_STATUSES,
)
from code_generation.local_function_generator import generate_function


class GeneratedCodeExecutionTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.allowed_dir = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def _path(self, name):
        return os.path.join(self.allowed_dir, name)

    def _generated_result(self, target_file=None, **spec_overrides):
        spec = {"function_name": "add", "parameters": ["a", "b"], "return_expression": "a + b"}
        spec.update(spec_overrides)
        return generate_function(spec, target_file=target_file)


# --------------------------------------------------------------------
# Valid generated file -> executes successfully.
# --------------------------------------------------------------------
class TestValidGeneratedFileExecutesSuccessfully(GeneratedCodeExecutionTestBase):
    def test_valid_result_executes(self):
        target = self._path("math_helpers.py")
        result = self._generated_result(target_file=target)
        self.assertEqual(result.status, STATUS_GENERATED)

        execution = execute_generated_code(result, allowed_dirs=[self.allowed_dir])

        self.assertEqual(execution["status"], STATUS_EXECUTED)
        self.assertIsNone(execution["error"])
        self.assertEqual(execution["target_file"], os.path.realpath(target))
        self.assertTrue(os.path.exists(target))

    def test_status_is_always_in_controlled_vocabulary(self):
        target = self._path("math_helpers.py")
        result = self._generated_result(target_file=target)
        execution = execute_generated_code(result, allowed_dirs=[self.allowed_dir])
        self.assertIn(execution["status"], ALL_EXECUTION_STATUSES)

    def test_generated_code_file_is_not_modified_by_execution(self):
        target = self._path("math_helpers.py")
        result = self._generated_result(target_file=target)
        execute_generated_code(result, allowed_dirs=[self.allowed_dir])

        with open(target, "r", encoding="utf-8") as f:
            written = f.read()
        self.assertEqual(written, result.generated_code)


# --------------------------------------------------------------------
# Invalid generated code -> rejected before any execution.
# --------------------------------------------------------------------
class TestInvalidGeneratedCodeIsRejected(GeneratedCodeExecutionTestBase):
    def test_invalid_request_result_is_rejected(self):
        target = self._path("broken.py")
        # An invalid function_name means generate_function never even
        # produces generated_code - the classic STATUS_INVALID_REQUEST
        # path; execution must never even be attempted.
        result = self._generated_result(target_file=target, function_name="not a valid name")

        execution = execute_generated_code(result, allowed_dirs=[self.allowed_dir])

        self.assertEqual(execution["status"], STATUS_REJECTED)
        self.assertIsNotNone(execution["error"])
        self.assertIsNone(execution["stdout"])
        self.assertIsNone(execution["stderr"])
        self.assertFalse(os.path.exists(target))

    def test_hand_built_bad_syntax_result_is_rejected(self):
        target = self._path("broken.py")
        result = CodeGenerationResult(
            request={"function_name": "f"}, target_file=target,
            generated_code="def f(:\n    return 1\n", status=STATUS_GENERATED,
        )

        execution = execute_generated_code(result, allowed_dirs=[self.allowed_dir])

        self.assertEqual(execution["status"], STATUS_REJECTED)
        self.assertFalse(os.path.exists(target))

    def test_non_code_generation_result_never_raises(self):
        for bad_input in (None, "not a result", 42, {}, []):
            with self.subTest(bad_input=bad_input):
                execution = execute_generated_code(bad_input, allowed_dirs=[self.allowed_dir])
                self.assertEqual(execution["status"], STATUS_REJECTED)
                self.assertIsNotNone(execution["error"])


# --------------------------------------------------------------------
# Unsafe/outside path -> rejected.
# --------------------------------------------------------------------
class TestUnsafePathIsRejected(GeneratedCodeExecutionTestBase):
    def test_path_outside_allowed_dir_is_rejected(self):
        with tempfile.TemporaryDirectory() as other_dir:
            target = os.path.join(other_dir, "escape.py")
            result = self._generated_result(target_file=target)

            execution = execute_generated_code(result, allowed_dirs=[self.allowed_dir])

            self.assertEqual(execution["status"], STATUS_REJECTED)
            self.assertIsNotNone(execution["error"])
            self.assertFalse(os.path.exists(target))

    def test_path_traversal_outside_allowed_dir_is_rejected(self):
        target = os.path.join(self.allowed_dir, "..", "escape.py")
        result = self._generated_result(target_file=target)

        execution = execute_generated_code(result, allowed_dirs=[self.allowed_dir])

        self.assertEqual(execution["status"], STATUS_REJECTED)
        self.assertFalse(os.path.exists(os.path.realpath(target)))


# --------------------------------------------------------------------
# Timeout is handled via the existing timeout mechanism.
# --------------------------------------------------------------------
class TestTimeoutIsHandled(GeneratedCodeExecutionTestBase):
    def test_long_running_generated_file_times_out(self):
        target = self._path("slow.py")
        # Syntactically valid, non-empty, has a target - passes
        # validation; hangs once actually executed.
        result = CodeGenerationResult(
            request={"function_name": "slow"}, target_file=target,
            generated_code="import time\ntime.sleep(5)\n", status=STATUS_GENERATED,
        )

        execution = execute_generated_code(
            result, allowed_dirs=[self.allowed_dir], timeout_seconds=1,
        )

        self.assertEqual(execution["status"], STATUS_TIMEOUT)
        self.assertIsNotNone(execution["error"])
        self.assertTrue(os.path.exists(target))


# --------------------------------------------------------------------
# Failed execution -> structured error, never an exception.
# --------------------------------------------------------------------
class TestFailedExecutionReturnsStructuredError(GeneratedCodeExecutionTestBase):
    def test_generated_file_that_raises_on_import_fails_cleanly(self):
        target = self._path("raises.py")
        result = CodeGenerationResult(
            request={"function_name": "boom"}, target_file=target,
            generated_code="raise RuntimeError('boom')\n", status=STATUS_GENERATED,
        )

        execution = execute_generated_code(result, allowed_dirs=[self.allowed_dir])

        self.assertEqual(execution["status"], STATUS_FAILED)
        self.assertIsNotNone(execution["error"])
        self.assertIsNotNone(execution["stderr"])
        self.assertTrue(os.path.exists(target))


if __name__ == "__main__":
    unittest.main()
