"""
Tests for `code_generation/generated_code_applier.py`'s
`apply_generated_code` (Prompt 337) - connects a validated Prompt
335/336 `CodeGenerationResult` to the existing, unmodified
`text_file_write` capability so valid generated Python code can be
safely written to a brand-new file.

Covers: valid generated code successfully creating a new file; invalid
generated code never creating a file; an already-existing target file
never being overwritten; a path outside the allowed directory being
rejected; the written content matching the generated code exactly; and
the generated code never being executed.

Every test uses its own isolated `tempfile.TemporaryDirectory` as the
allowed directory (via `allowed_dirs=`) - never the application's real
data/skills/temp directories.

Run directly:
    python -m unittest tests.test_generated_code_applier -v
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
from code_generation.generated_code_applier import (
    apply_generated_code,
    STATUS_APPLIED,
    STATUS_REJECTED,
    ALL_APPLY_STATUSES,
)
from code_generation.local_function_generator import generate_function


class GeneratedCodeApplierTestBase(unittest.TestCase):
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
# Valid generated code -> successfully creates a new file.
# --------------------------------------------------------------------
class TestValidGeneratedCodeCreatesFile(GeneratedCodeApplierTestBase):
    def test_valid_result_is_applied(self):
        target = self._path("math_helpers.py")
        result = self._generated_result(target_file=target)
        self.assertEqual(result.status, STATUS_GENERATED)

        application = apply_generated_code(result, allowed_dirs=[self.allowed_dir])

        self.assertEqual(application["status"], STATUS_APPLIED)
        self.assertIsNone(application["error"])
        self.assertTrue(os.path.exists(target))

    def test_bytes_written_matches_file_size(self):
        target = self._path("math_helpers.py")
        result = self._generated_result(target_file=target)

        application = apply_generated_code(result, allowed_dirs=[self.allowed_dir])

        self.assertEqual(application["bytes_written"], os.path.getsize(target))
        self.assertGreater(application["bytes_written"], 0)

    def test_target_file_reflects_resolved_path(self):
        target = self._path("math_helpers.py")
        result = self._generated_result(target_file=target)

        application = apply_generated_code(result, allowed_dirs=[self.allowed_dir])

        self.assertEqual(application["target_file"], os.path.realpath(target))

    def test_status_is_always_in_controlled_vocabulary(self):
        target = self._path("math_helpers.py")
        result = self._generated_result(target_file=target)
        application = apply_generated_code(result, allowed_dirs=[self.allowed_dir])
        self.assertIn(application["status"], ALL_APPLY_STATUSES)


# --------------------------------------------------------------------
# Invalid generated code -> file is not created.
# --------------------------------------------------------------------
class TestInvalidGeneratedCodeNeverWrites(GeneratedCodeApplierTestBase):
    def test_invalid_request_result_is_rejected(self):
        target = self._path("broken.py")
        # An invalid function_name means generate_function never even
        # produces generated_code - the classic STATUS_INVALID_REQUEST
        # path from Prompt 335.
        result = self._generated_result(target_file=target, function_name="not a valid name")

        application = apply_generated_code(result, allowed_dirs=[self.allowed_dir])

        self.assertEqual(application["status"], STATUS_REJECTED)
        self.assertIsNotNone(application["error"])
        self.assertFalse(os.path.exists(target))
        self.assertEqual(application["bytes_written"], 0)

    def test_hand_built_bad_syntax_result_is_rejected(self):
        target = self._path("broken.py")
        result = CodeGenerationResult(
            request={"function_name": "f"}, target_file=target,
            generated_code="def f(:\n    return 1\n", status=STATUS_GENERATED,
        )

        application = apply_generated_code(result, allowed_dirs=[self.allowed_dir])

        self.assertEqual(application["status"], STATUS_REJECTED)
        self.assertFalse(os.path.exists(target))

    def test_empty_generated_code_is_rejected(self):
        target = self._path("empty.py")
        result = CodeGenerationResult(
            request={}, target_file=target, generated_code="", status=STATUS_GENERATED,
        )

        application = apply_generated_code(result, allowed_dirs=[self.allowed_dir])

        self.assertEqual(application["status"], STATUS_REJECTED)
        self.assertFalse(os.path.exists(target))

    def test_non_code_generation_result_never_raises(self):
        for bad_input in (None, "not a result", 42, {}, []):
            with self.subTest(bad_input=bad_input):
                application = apply_generated_code(bad_input, allowed_dirs=[self.allowed_dir])
                self.assertEqual(application["status"], STATUS_REJECTED)
                self.assertIsNotNone(application["error"])


# --------------------------------------------------------------------
# Existing target file -> no overwrite.
# --------------------------------------------------------------------
class TestExistingTargetFileNeverOverwritten(GeneratedCodeApplierTestBase):
    def test_existing_file_is_rejected_and_left_untouched(self):
        target = self._path("existing.py")
        original_content = "# already here\n"
        with open(target, "w", encoding="utf-8") as f:
            f.write(original_content)

        result = self._generated_result(target_file=target)
        application = apply_generated_code(result, allowed_dirs=[self.allowed_dir])

        self.assertEqual(application["status"], STATUS_REJECTED)
        self.assertIsNotNone(application["error"])
        self.assertEqual(application["bytes_written"], 0)

        with open(target, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), original_content)

    def test_no_overwrite_flag_is_ever_exposed_or_honored(self):
        # Even if a caller tried to sneak "overwrite" onto the
        # generation request itself, apply_generated_code has no
        # parameter for it at all - it always writes with
        # overwrite=False.
        target = self._path("existing2.py")
        with open(target, "w", encoding="utf-8") as f:
            f.write("original\n")

        result = self._generated_result(target_file=target)
        apply_generated_code(result, allowed_dirs=[self.allowed_dir])

        with open(target, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "original\n")


# --------------------------------------------------------------------
# Unsafe/outside path -> rejected.
# --------------------------------------------------------------------
class TestUnsafePathRejected(GeneratedCodeApplierTestBase):
    def test_path_outside_allowed_dir_is_rejected(self):
        with tempfile.TemporaryDirectory() as other_dir:
            target = os.path.join(other_dir, "escape.py")
            result = self._generated_result(target_file=target)

            application = apply_generated_code(result, allowed_dirs=[self.allowed_dir])

            self.assertEqual(application["status"], STATUS_REJECTED)
            self.assertIsNotNone(application["error"])
            self.assertFalse(os.path.exists(target))

    def test_path_traversal_outside_allowed_dir_is_rejected(self):
        target = os.path.join(self.allowed_dir, "..", "escape.py")
        result = self._generated_result(target_file=target)

        application = apply_generated_code(result, allowed_dirs=[self.allowed_dir])

        self.assertEqual(application["status"], STATUS_REJECTED)
        self.assertFalse(os.path.exists(os.path.realpath(target)))


# --------------------------------------------------------------------
# Generated content is preserved exactly.
# --------------------------------------------------------------------
class TestContentPreservedExactly(GeneratedCodeApplierTestBase):
    def test_written_file_matches_generated_code_exactly(self):
        target = self._path("math_helpers.py")
        result = self._generated_result(target_file=target, docstring="Add two numbers.")

        apply_generated_code(result, allowed_dirs=[self.allowed_dir])

        with open(target, "r", encoding="utf-8") as f:
            written = f.read()
        self.assertEqual(written, result.generated_code)

    def test_original_generated_code_object_unchanged_after_applying(self):
        target = self._path("math_helpers.py")
        result = self._generated_result(target_file=target)
        original_code = result.generated_code

        apply_generated_code(result, allowed_dirs=[self.allowed_dir])

        self.assertEqual(result.generated_code, original_code)
        self.assertEqual(result.status, STATUS_GENERATED)


# --------------------------------------------------------------------
# Never executes the generated code.
# --------------------------------------------------------------------
class TestNeverExecutesGeneratedCode(GeneratedCodeApplierTestBase):
    def test_generated_function_body_is_never_run(self):
        # A syntactically valid function whose body would raise if it
        # were ever actually called - applying it must still succeed,
        # since the code is only ever validated (parsed) and written,
        # never executed.
        target = self._path("would_raise.py")
        result = self._generated_result(
            target_file=target, function_name="would_raise", parameters=[],
            return_expression="undefined_name",
        )

        application = apply_generated_code(result, allowed_dirs=[self.allowed_dir])

        self.assertEqual(application["status"], STATUS_APPLIED)
        with open(target, "r", encoding="utf-8") as f:
            self.assertIn("return undefined_name", f.read())


if __name__ == "__main__":
    unittest.main()
