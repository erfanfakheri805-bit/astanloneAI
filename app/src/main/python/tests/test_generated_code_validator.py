"""
Tests for `code_generation/generated_code_validator.py`'s
`validate_generated_code` (Prompt 336) - connects the Prompt 335
`CodeGenerationResult` to the existing
`code_intelligence.python_inspector.inspect_source` code-analysis/
validation logic, before any generated code is ever executed or
applied.

Covers: a VALID result for real generated code (both via
`local_function_generator.generate_function` and a hand-built
`CodeGenerationResult`), INVALID for bad Python syntax, INVALID for
empty generated code, INVALID for missing target information,
INVALID for a non-`CodeGenerationResult` input, the original
generated_code/target_file always being preserved unchanged, and
never executing/writing anything.

Run directly:
    python -m unittest tests.test_generated_code_validator -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from code_generation.code_generation_result import (
    CodeGenerationResult,
    STATUS_GENERATED,
    STATUS_INVALID_REQUEST,
)
from code_generation.generated_code_validator import (
    validate_generated_code,
    VALIDATION_VALID,
    VALIDATION_INVALID,
    ALL_VALIDATION_STATUSES,
)
from code_generation.local_function_generator import generate_function


def _generated_result(generated_code="def f():\n    return 1\n", target_file="module.py", **overrides):
    kwargs = {
        "request": {"function_name": "f"},
        "target_file": target_file,
        "generated_code": generated_code,
        "status": STATUS_GENERATED,
        "error": None,
    }
    kwargs.update(overrides)
    return CodeGenerationResult(**kwargs)


# --------------------------------------------------------------------
# Valid generated code.
# --------------------------------------------------------------------
class TestValidGeneratedCode(unittest.TestCase):
    def test_valid_result_from_generator(self):
        gen_result = generate_function(
            {"function_name": "add", "parameters": ["a", "b"], "return_expression": "a + b"},
            target_file="math_helpers.py",
        )
        self.assertEqual(gen_result.status, STATUS_GENERATED)

        validation = validate_generated_code(gen_result)

        self.assertEqual(validation["status"], VALIDATION_VALID)
        self.assertIsNone(validation["error"])
        self.assertEqual(validation["target_file"], "math_helpers.py")
        self.assertIn("def add(a, b):", validation["generated_code"])
        self.assertTrue(validation["analysis"]["valid"])

    def test_valid_hand_built_result(self):
        result = _generated_result()
        validation = validate_generated_code(result)
        self.assertEqual(validation["status"], VALIDATION_VALID)
        self.assertIsNone(validation["error"])

    def test_analysis_contains_the_function(self):
        result = _generated_result(generated_code="def add(a, b):\n    return a + b\n")
        validation = validate_generated_code(result)
        self.assertEqual(validation["status"], VALIDATION_VALID)
        self.assertEqual([f["name"] for f in validation["analysis"]["functions"]], ["add"])


# --------------------------------------------------------------------
# Invalid Python syntax.
# --------------------------------------------------------------------
class TestInvalidSyntax(unittest.TestCase):
    def test_bad_syntax_is_invalid(self):
        result = _generated_result(generated_code="def f(:\n    return 1\n")
        validation = validate_generated_code(result)

        self.assertEqual(validation["status"], VALIDATION_INVALID)
        self.assertIsNotNone(validation["error"])
        self.assertIn("failed to parse", validation["error"])
        self.assertIsNotNone(validation["analysis"])
        self.assertFalse(validation["analysis"]["valid"])

    def test_bad_syntax_preserves_generated_code_and_target(self):
        bad_code = "def f(:\n    return 1\n"
        result = _generated_result(generated_code=bad_code, target_file="broken.py")
        validation = validate_generated_code(result)

        self.assertEqual(validation["generated_code"], bad_code)
        self.assertEqual(validation["target_file"], "broken.py")


# --------------------------------------------------------------------
# Empty generated code.
# --------------------------------------------------------------------
class TestEmptyGeneratedCode(unittest.TestCase):
    def test_empty_string_is_invalid(self):
        result = _generated_result(generated_code="")
        validation = validate_generated_code(result)

        self.assertEqual(validation["status"], VALIDATION_INVALID)
        self.assertIn("empty", validation["error"])
        self.assertIsNone(validation["analysis"])

    def test_whitespace_only_is_invalid(self):
        result = _generated_result(generated_code="   \n\t  ")
        validation = validate_generated_code(result)
        self.assertEqual(validation["status"], VALIDATION_INVALID)
        self.assertIn("empty", validation["error"])

    def test_none_generated_code_is_invalid(self):
        # e.g. a STATUS_INVALID_REQUEST result reached before any
        # source text was ever assembled (see local_function_generator).
        result = CodeGenerationResult(
            request={"function_name": "bad name"}, target_file="x.py",
            generated_code=None, status=STATUS_INVALID_REQUEST, error="bad spec",
        )
        validation = validate_generated_code(result)
        self.assertEqual(validation["status"], VALIDATION_INVALID)
        self.assertIn("empty", validation["error"])


# --------------------------------------------------------------------
# Missing target information.
# --------------------------------------------------------------------
class TestMissingTargetInformation(unittest.TestCase):
    def test_none_target_file_is_invalid(self):
        result = _generated_result(target_file=None)
        validation = validate_generated_code(result)

        self.assertEqual(validation["status"], VALIDATION_INVALID)
        self.assertIn("target_file", validation["error"])
        self.assertIsNone(validation["analysis"])

    def test_empty_string_target_file_is_invalid(self):
        result = _generated_result(target_file="")
        validation = validate_generated_code(result)
        self.assertEqual(validation["status"], VALIDATION_INVALID)
        self.assertIn("target_file", validation["error"])

    def test_whitespace_only_target_file_is_invalid(self):
        result = _generated_result(target_file="   ")
        validation = validate_generated_code(result)
        self.assertEqual(validation["status"], VALIDATION_INVALID)

    def test_missing_target_still_preserves_generated_code(self):
        result = _generated_result(target_file=None, generated_code="def f():\n    return 1\n")
        validation = validate_generated_code(result)
        self.assertEqual(validation["generated_code"], "def f():\n    return 1\n")


# --------------------------------------------------------------------
# Malformed input to the validator itself.
# --------------------------------------------------------------------
class TestMalformedInput(unittest.TestCase):
    def test_non_code_generation_result_never_raises(self):
        for bad_input in (None, "not a result", 42, {}, [], object()):
            with self.subTest(bad_input=bad_input):
                validation = validate_generated_code(bad_input)
                self.assertEqual(validation["status"], VALIDATION_INVALID)
                self.assertIsNotNone(validation["error"])

    def test_status_is_always_one_of_the_controlled_vocabulary(self):
        for case in (
            _generated_result(),
            _generated_result(generated_code=""),
            _generated_result(target_file=None),
            _generated_result(generated_code="def f(:\n"),
            "not a result",
        ):
            with self.subTest(case=case):
                validation = validate_generated_code(case)
                self.assertIn(validation["status"], ALL_VALIDATION_STATUSES)


# --------------------------------------------------------------------
# Never executes, applies, or modifies anything.
# --------------------------------------------------------------------
class TestNeverExecutesOrApplies(unittest.TestCase):
    def test_generated_code_is_never_executed(self):
        # A syntactically valid function whose body would raise if it
        # were ever actually run - validation must still succeed,
        # since the code is only ever parsed, never executed.
        result = _generated_result(generated_code="def f():\n    return undefined_name\n")
        validation = validate_generated_code(result)
        self.assertEqual(validation["status"], VALIDATION_VALID)

    def test_target_file_is_never_written(self):
        target = "definitely-does-not-exist-on-disk/generated_module.py"
        result = _generated_result(target_file=target)
        validate_generated_code(result)
        self.assertFalse(os.path.exists(target))

    def test_original_generated_code_object_is_unchanged(self):
        code = "def f():\n    return 1\n"
        result = _generated_result(generated_code=code)
        validate_generated_code(result)
        # The CodeGenerationResult itself was never mutated.
        self.assertEqual(result.generated_code, code)
        self.assertEqual(result.status, STATUS_GENERATED)


if __name__ == "__main__":
    unittest.main()
