"""
Tests for the local code-generation foundation (Prompt 335):
`code_generation/code_generation_result.py`'s `CodeGenerationResult`
and `code_generation/local_function_generator.py`'s
`generate_function`.

Covers: successful generation of a small Python function from a
structured spec, every reachable invalid-input case (non-dict spec,
bad/keyword function_name, bad/duplicate parameters, missing/empty
return_expression, non-string docstring, unrecognized field),
`target_file`/`request` always preserved unmodified, the generated
source actually parsing and containing the requested function (cross-
checked via the existing `python_inspector`), the generated code never
being executed or written to disk, and `CodeGenerationResult`'s own
small model contract (`to_dict`, `success`, constructor validation).

Run directly:
    python -m unittest tests.test_code_generation -v
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
    ALL_CODE_GENERATION_STATUSES,
)
from code_generation.local_function_generator import generate_function
from code_intelligence.python_inspector import inspect_source


def _spec(**overrides):
    spec = {
        "function_name": "add",
        "parameters": ["a", "b"],
        "return_expression": "a + b",
    }
    spec.update(overrides)
    return spec


# --------------------------------------------------------------------
# CodeGenerationResult - the small model itself.
# --------------------------------------------------------------------
class TestCodeGenerationResult(unittest.TestCase):
    def test_to_dict_shape(self):
        result = CodeGenerationResult(
            request={"function_name": "f"}, target_file="foo.py",
            generated_code="def f():\n    return 1\n", status=STATUS_GENERATED,
        )
        self.assertEqual(
            result.to_dict(),
            {
                "request": {"function_name": "f"},
                "target_file": "foo.py",
                "generated_code": "def f():\n    return 1\n",
                "status": STATUS_GENERATED,
                "error": None,
            },
        )

    def test_success_true_for_generated(self):
        result = CodeGenerationResult(
            request={}, target_file=None, generated_code="def f():\n    return 1\n",
            status=STATUS_GENERATED,
        )
        self.assertTrue(result.success)

    def test_success_false_for_invalid_request(self):
        result = CodeGenerationResult(
            request={}, target_file=None, generated_code=None,
            status=STATUS_INVALID_REQUEST, error="bad spec",
        )
        self.assertFalse(result.success)

    def test_rejects_unknown_status(self):
        with self.assertRaises(ValueError):
            CodeGenerationResult(
                request={}, target_file=None, generated_code=None, status="NOT_A_STATUS",
            )

    def test_all_statuses_constructible(self):
        for status in ALL_CODE_GENERATION_STATUSES:
            result = CodeGenerationResult(
                request={}, target_file=None, generated_code=None, status=status,
            )
            self.assertEqual(result.status, status)

    def test_error_defaults_to_none(self):
        result = CodeGenerationResult(
            request={}, target_file=None, generated_code="x", status=STATUS_GENERATED,
        )
        self.assertIsNone(result.error)


# --------------------------------------------------------------------
# generate_function - successful generation.
# --------------------------------------------------------------------
class TestGenerateFunctionSuccess(unittest.TestCase):
    def test_generates_a_valid_function(self):
        result = generate_function(_spec())

        self.assertIsInstance(result, CodeGenerationResult)
        self.assertEqual(result.status, STATUS_GENERATED)
        self.assertTrue(result.success)
        self.assertIsNone(result.error)
        self.assertIn("def add(a, b):", result.generated_code)
        self.assertIn("return a + b", result.generated_code)

    def test_generated_source_actually_parses_and_defines_the_function(self):
        result = generate_function(_spec())

        analysis = inspect_source(result.generated_code)
        self.assertTrue(analysis["valid"])
        self.assertEqual(len(analysis["functions"]), 1)
        self.assertEqual(analysis["functions"][0]["name"], "add")
        self.assertEqual(analysis["functions"][0]["args"], ["a", "b"])

    def test_no_parameters_generates_empty_parameter_list(self):
        result = generate_function(_spec(function_name="answer", parameters=[], return_expression="42"))

        self.assertEqual(result.status, STATUS_GENERATED)
        self.assertIn("def answer():", result.generated_code)

    def test_parameters_field_may_be_omitted_entirely(self):
        spec = {"function_name": "answer", "return_expression": "42"}
        result = generate_function(spec)

        self.assertEqual(result.status, STATUS_GENERATED)
        self.assertIn("def answer():", result.generated_code)

    def test_docstring_is_included_when_given(self):
        result = generate_function(_spec(docstring="Add two numbers."))

        self.assertEqual(result.status, STATUS_GENERATED)
        self.assertIn('"""Add two numbers."""', result.generated_code)

    def test_docstring_omitted_when_not_given(self):
        result = generate_function(_spec())
        self.assertNotIn('"""', result.generated_code)

    def test_request_preserved_unmodified(self):
        spec = _spec()
        result = generate_function(spec)
        self.assertEqual(result.request, spec)
        self.assertIs(result.request, spec)

    def test_target_file_carried_through_unmodified(self):
        result = generate_function(_spec(), target_file="generated/math_helpers.py")
        self.assertEqual(result.target_file, "generated/math_helpers.py")

    def test_target_file_defaults_to_none(self):
        result = generate_function(_spec())
        self.assertIsNone(result.target_file)

    def test_target_file_is_never_written(self):
        target = "definitely-does-not-exist-on-disk/generated_module.py"
        result = generate_function(_spec(), target_file=target)
        self.assertEqual(result.status, STATUS_GENERATED)
        self.assertFalse(os.path.exists(target))

    def test_generated_function_is_never_executed(self):
        # A return_expression that would raise if it were ever actually
        # run (NameError: 'undefined_name' is not defined) - generation
        # itself must still succeed, since the source is only ever
        # parsed, never executed.
        result = generate_function(_spec(
            function_name="broken_at_runtime", parameters=[], return_expression="undefined_name",
        ))
        self.assertEqual(result.status, STATUS_GENERATED)
        self.assertIn("return undefined_name", result.generated_code)


# --------------------------------------------------------------------
# generate_function - invalid input (never raises; always a
# structured STATUS_INVALID_REQUEST result).
# --------------------------------------------------------------------
class TestGenerateFunctionInvalidInput(unittest.TestCase):
    def test_non_dict_spec_never_raises(self):
        for bad_spec in (None, "not a spec", 42, [], object()):
            with self.subTest(bad_spec=bad_spec):
                result = generate_function(bad_spec)
                self.assertEqual(result.status, STATUS_INVALID_REQUEST)
                self.assertIsNone(result.generated_code)
                self.assertIsNotNone(result.error)

    def test_missing_function_name(self):
        spec = _spec()
        del spec["function_name"]
        result = generate_function(spec)
        self.assertEqual(result.status, STATUS_INVALID_REQUEST)
        self.assertIsNone(result.generated_code)
        self.assertIn("function_name", result.error)

    def test_function_name_not_an_identifier(self):
        result = generate_function(_spec(function_name="not a valid name"))
        self.assertEqual(result.status, STATUS_INVALID_REQUEST)
        self.assertIsNone(result.generated_code)

    def test_function_name_is_a_reserved_keyword(self):
        result = generate_function(_spec(function_name="return"))
        self.assertEqual(result.status, STATUS_INVALID_REQUEST)
        self.assertIsNone(result.generated_code)

    def test_function_name_wrong_type(self):
        result = generate_function(_spec(function_name=123))
        self.assertEqual(result.status, STATUS_INVALID_REQUEST)

    def test_parameters_not_a_list(self):
        result = generate_function(_spec(parameters="a, b"))
        self.assertEqual(result.status, STATUS_INVALID_REQUEST)
        self.assertIsNone(result.generated_code)

    def test_parameters_contains_non_identifier(self):
        result = generate_function(_spec(parameters=["a", "not valid"]))
        self.assertEqual(result.status, STATUS_INVALID_REQUEST)

    def test_parameters_contains_duplicates(self):
        result = generate_function(_spec(parameters=["a", "a"]))
        self.assertEqual(result.status, STATUS_INVALID_REQUEST)
        self.assertIn("duplicate", result.error)

    def test_missing_return_expression(self):
        spec = _spec()
        del spec["return_expression"]
        result = generate_function(spec)
        self.assertEqual(result.status, STATUS_INVALID_REQUEST)
        self.assertIsNone(result.generated_code)

    def test_empty_return_expression(self):
        result = generate_function(_spec(return_expression=""))
        self.assertEqual(result.status, STATUS_INVALID_REQUEST)

    def test_whitespace_only_return_expression(self):
        result = generate_function(_spec(return_expression="   "))
        self.assertEqual(result.status, STATUS_INVALID_REQUEST)

    def test_return_expression_wrong_type(self):
        result = generate_function(_spec(return_expression=123))
        self.assertEqual(result.status, STATUS_INVALID_REQUEST)

    def test_docstring_wrong_type(self):
        result = generate_function(_spec(docstring=123))
        self.assertEqual(result.status, STATUS_INVALID_REQUEST)
        self.assertIsNone(result.generated_code)

    def test_unrecognized_field_rejected(self):
        result = generate_function(_spec(unexpected_field="oops"))
        self.assertEqual(result.status, STATUS_INVALID_REQUEST)
        self.assertIn("unexpected_field", result.error)

    def test_request_preserved_even_for_invalid_spec(self):
        spec = _spec(function_name="not valid")
        result = generate_function(spec)
        self.assertEqual(result.request, spec)

    def test_target_file_preserved_even_for_invalid_spec(self):
        result = generate_function(_spec(function_name="not valid"), target_file="x.py")
        self.assertEqual(result.target_file, "x.py")

    def test_never_raises_for_any_malformed_spec(self):
        malformed_specs = [
            {},
            {"function_name": "f"},
            {"function_name": "f", "return_expression": None},
            {"function_name": None, "return_expression": "1"},
            {"function_name": "f", "return_expression": "1", "parameters": None},
            {"function_name": "f", "return_expression": "1", "parameters": [1, 2]},
        ]
        for spec in malformed_specs:
            with self.subTest(spec=spec):
                try:
                    result = generate_function(spec)
                except Exception as exc:  # pragma: no cover - failure path
                    self.fail(f"generate_function raised for {spec!r}: {exc!r}")
                self.assertEqual(result.status, STATUS_INVALID_REQUEST)


if __name__ == "__main__":
    unittest.main()
