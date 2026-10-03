"""
Tests for the standard Capability interface (execution/capability.py)
and its optional, backward-compatible storage in
CapabilityHandlerRegistry (execution/capability_handlers.py).

Covers: valid construction, invalid name, invalid handler, input
validation success/failure, successful execution, handler failure,
describe(), to_dict(), and backward compatibility with existing plain
callable handlers.

Run directly:
    python -m unittest tests.test_capability -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execution.capability import (
    Capability, CapabilityValidationResult, CapabilityExecutionResult,
)
from execution.capability_handlers import CapabilityHandlerRegistry


def _echo_handler(data):
    return {"received": data}


SIMPLE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "required": True},
        "count": {"type": "integer"},
    },
}


class TestValidConstruction(unittest.TestCase):
    def test_minimal_construction(self):
        capability = Capability("greet", _echo_handler)
        self.assertEqual(capability.name, "greet")
        self.assertIs(capability.handler, _echo_handler)
        self.assertEqual(capability.description, "")
        self.assertEqual(capability.version, "1.0.0")
        self.assertEqual(capability.input_schema, {})
        self.assertEqual(capability.output_schema, {})
        self.assertEqual(capability.metadata, {})

    def test_full_construction(self):
        capability = Capability(
            "greet",
            _echo_handler,
            description="Greets someone.",
            version="2.1.0",
            input_schema=SIMPLE_SCHEMA,
            output_schema={"type": "object"},
            metadata={"author": "erfan"},
        )
        self.assertEqual(capability.description, "Greets someone.")
        self.assertEqual(capability.version, "2.1.0")
        self.assertEqual(capability.input_schema, SIMPLE_SCHEMA)
        self.assertEqual(capability.metadata, {"author": "erfan"})

    def test_name_is_stripped(self):
        capability = Capability("  greet  ", _echo_handler)
        self.assertEqual(capability.name, "greet")

    def test_schemas_are_copied_not_aliased(self):
        schema = dict(SIMPLE_SCHEMA)
        capability = Capability("greet", _echo_handler, input_schema=schema)
        schema["properties"] = {}
        self.assertEqual(capability.input_schema, SIMPLE_SCHEMA)

    def test_construction_never_calls_the_handler(self):
        calls = []

        def handler(data):
            calls.append(data)
            return data

        Capability("greet", handler)
        self.assertEqual(calls, [])


class TestInvalidName(unittest.TestCase):
    def test_empty_name_raises(self):
        with self.assertRaises(ValueError):
            Capability("", _echo_handler)

    def test_whitespace_only_name_raises(self):
        with self.assertRaises(ValueError):
            Capability("   ", _echo_handler)

    def test_none_name_raises(self):
        with self.assertRaises(ValueError):
            Capability(None, _echo_handler)

    def test_non_string_name_raises(self):
        with self.assertRaises(ValueError):
            Capability(123, _echo_handler)


class TestInvalidHandler(unittest.TestCase):
    def test_none_handler_raises(self):
        with self.assertRaises(TypeError):
            Capability("greet", None)

    def test_non_callable_handler_raises(self):
        with self.assertRaises(TypeError):
            Capability("greet", "not-callable")

    def test_a_rejected_construction_is_not_partially_built(self):
        # No Capability instance should exist to inspect after a
        # rejected construction - this just documents that the
        # constructor raises before assigning anything durable.
        with self.assertRaises(TypeError):
            Capability("greet", None)


class TestInputValidationSuccess(unittest.TestCase):
    def setUp(self):
        self.capability = Capability("greet", _echo_handler, input_schema=SIMPLE_SCHEMA)

    def test_valid_data_passes(self):
        result = self.capability.validate_input({"name": "Erfan", "count": 3})
        self.assertIsInstance(result, CapabilityValidationResult)
        self.assertTrue(result.valid)
        self.assertEqual(result.errors, [])

    def test_optional_field_may_be_omitted(self):
        result = self.capability.validate_input({"name": "Erfan"})
        self.assertTrue(result.valid)

    def test_no_schema_always_validates(self):
        capability = Capability("greet", _echo_handler)
        result = capability.validate_input({"anything": object()})
        self.assertTrue(result.valid)
        result = capability.validate_input(None)
        self.assertTrue(result.valid)


class TestInputValidationFailure(unittest.TestCase):
    def setUp(self):
        self.capability = Capability("greet", _echo_handler, input_schema=SIMPLE_SCHEMA)

    def test_missing_required_field_fails(self):
        result = self.capability.validate_input({"count": 3})
        self.assertFalse(result.valid)
        self.assertTrue(any(err["field"] == "name" for err in result.errors))

    def test_wrong_type_fails(self):
        result = self.capability.validate_input({"name": "Erfan", "count": "three"})
        self.assertFalse(result.valid)
        self.assertTrue(any(err["field"] == "count" for err in result.errors))

    def test_non_dict_data_fails_for_object_schema(self):
        result = self.capability.validate_input(["not", "a", "dict"])
        self.assertFalse(result.valid)

    def test_disallowed_additional_property_fails(self):
        strict_capability = Capability(
            "greet", _echo_handler,
            input_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "additionalProperties": False,
            },
        )
        result = strict_capability.validate_input({"name": "Erfan", "extra": 1})
        self.assertFalse(result.valid)
        self.assertTrue(any(err["field"] == "extra" for err in result.errors))


class TestSuccessfulExecution(unittest.TestCase):
    def test_execute_calls_handler_and_wraps_output(self):
        capability = Capability("greet", _echo_handler, input_schema=SIMPLE_SCHEMA)
        result = capability.execute({"name": "Erfan"})
        self.assertIsInstance(result, CapabilityExecutionResult)
        self.assertTrue(result.success)
        self.assertEqual(result.output, {"received": {"name": "Erfan"}})
        self.assertIsNone(result.error)
        self.assertTrue(result.validation.valid)

    def test_execute_with_no_schema_still_calls_handler(self):
        capability = Capability("greet", _echo_handler)
        result = capability.execute({"anything": 1})
        self.assertTrue(result.success)
        self.assertEqual(result.output, {"received": {"anything": 1}})

    def test_invalid_input_never_calls_the_handler(self):
        calls = []

        def handler(data):
            calls.append(data)
            return data

        capability = Capability("greet", handler, input_schema=SIMPLE_SCHEMA)
        result = capability.execute({"count": "not-an-int"})
        self.assertFalse(result.success)
        self.assertEqual(calls, [])
        self.assertFalse(result.validation.valid)


class TestHandlerFailure(unittest.TestCase):
    def test_handler_exception_is_caught_and_reported(self):
        def failing_handler(data):
            raise RuntimeError("boom")

        capability = Capability("greet", failing_handler)
        result = capability.execute({"anything": 1})
        self.assertFalse(result.success)
        self.assertIsNone(result.output)
        self.assertIn("RuntimeError", result.error)
        self.assertIn("boom", result.error)

    def test_handler_exception_does_not_propagate(self):
        def failing_handler(data):
            raise ValueError("nope")

        capability = Capability("greet", failing_handler)
        try:
            result = capability.execute({})
        except ValueError:
            self.fail("execute() must not let a handler's exception propagate.")
        self.assertFalse(result.success)


class TestDescribe(unittest.TestCase):
    def test_describe_contains_expected_fields(self):
        capability = Capability(
            "greet", _echo_handler, description="Greets someone.",
            version="2.0.0", input_schema=SIMPLE_SCHEMA, metadata={"author": "erfan"},
        )
        description = capability.describe()
        self.assertEqual(description["name"], "greet")
        self.assertEqual(description["description"], "Greets someone.")
        self.assertEqual(description["version"], "2.0.0")
        self.assertEqual(description["input_schema"], SIMPLE_SCHEMA)
        self.assertEqual(description["metadata"], {"author": "erfan"})
        self.assertEqual(description["handler"], "_echo_handler")

    def test_describe_never_calls_the_handler(self):
        calls = []

        def handler(data):
            calls.append(data)
            return data

        capability = Capability("greet", handler)
        capability.describe()
        self.assertEqual(calls, [])


class TestToDict(unittest.TestCase):
    def test_to_dict_is_json_shaped(self):
        capability = Capability("greet", _echo_handler, version="3.0.0")
        as_dict = capability.to_dict()
        self.assertEqual(
            set(as_dict.keys()),
            {
                "name", "description", "version", "input_schema",
                "output_schema", "metadata", "handler",
            },
        )
        self.assertEqual(as_dict["version"], "3.0.0")

    def test_to_dict_returns_independent_copies(self):
        capability = Capability("greet", _echo_handler, input_schema=SIMPLE_SCHEMA)
        as_dict = capability.to_dict()
        as_dict["input_schema"]["properties"] = {}
        self.assertEqual(capability.input_schema, SIMPLE_SCHEMA)


class TestBackwardCompatibility(unittest.TestCase):
    """Existing simple callable handlers must continue to work exactly
    as before, and a Capability object can now optionally be stored in
    the same registry alongside them."""

    def setUp(self):
        self.registry = CapabilityHandlerRegistry()

    def test_plain_callable_handler_still_registers_and_runs(self):
        def plain_handler(step):
            return f"handled {step}"

        self.registry.register("send_email", plain_handler)
        self.assertIs(self.registry.get("send_email"), plain_handler)
        self.assertEqual(self.registry.get("send_email")("step-1"), "handled step-1")

    def test_capability_is_itself_callable_like_a_plain_handler(self):
        capability = Capability("send_email", lambda step: f"handled {step}")
        self.registry.register("send_email", capability)
        handler = self.registry.get("send_email")
        self.assertEqual(handler("step-1"), "handled step-1")

    def test_register_capability_uses_the_capability_name(self):
        capability = Capability("greet", _echo_handler)
        self.registry.register_capability(capability)
        self.assertTrue(self.registry.has("greet"))
        self.assertIs(self.registry.get_capability("greet"), capability)

    def test_get_capability_returns_none_for_a_plain_callable(self):
        self.registry.register("send_email", lambda step: "ok")
        self.assertIsNone(self.registry.get_capability("send_email"))
        self.assertFalse(self.registry.is_capability("send_email"))

    def test_register_capability_rejects_non_capability_objects(self):
        with self.assertRaises(TypeError):
            self.registry.register_capability(lambda step: "ok")

    def test_replace_capability_overwrites_explicitly(self):
        original = Capability("greet", _echo_handler)
        updated = Capability("greet", lambda data: "updated")
        self.registry.register_capability(original)
        self.registry.replace_capability(updated)
        self.assertIs(self.registry.get_capability("greet"), updated)

    def test_mixed_registry_keeps_both_kinds_working(self):
        def plain_handler(step):
            return "plain"

        capability = Capability("greet", lambda data: "capability")
        self.registry.register("plain", plain_handler)
        self.registry.register_capability(capability)

        self.assertEqual(self.registry.list_registered(), ["plain", "greet"])
        self.assertEqual(self.registry.get("plain")("step"), "plain")
        self.assertEqual(self.registry.get("greet")("data"), "capability")


if __name__ == "__main__":
    unittest.main()
