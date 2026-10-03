"""
Tests for ExecutableCapabilityRegistry (execution/executable_registry.py)
and its optional use from
CapabilityHandlerRegistry.check_execution_readiness
(execution/capability_handlers.py).

Covers: registering a Capability, duplicate registration, invalid
Capability, get, has, list_all, enable, disable, a disabled capability
being unavailable, a missing capability being unavailable, a
capability with an invalid handler being unavailable, describe(), no
automatic execution, and backward compatibility with the existing
CapabilityHandlerRegistry.

Run directly:
    python -m unittest tests.test_executable_registry -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execution.capability import Capability
from execution.capability_handlers import CapabilityHandlerRegistry
from execution.executable_registry import ExecutableCapabilityRegistry


def _make_capability(name="greet", handler=None):
    return Capability(name, handler or (lambda data: {"greeted": data}))


class _FakeStep:
    """Minimal stand-in for a PlanStep (planning/plan.py) - exposes
    only the `required_capabilities` attribute
    `check_execution_readiness` actually reads."""

    def __init__(self, required_capabilities):
        self.required_capabilities = list(required_capabilities)


# ----------------------------------------------------------------------
# Registration
# ----------------------------------------------------------------------
class TestRegisteringACapability(unittest.TestCase):
    def setUp(self):
        self.registry = ExecutableCapabilityRegistry()

    def test_register_stores_the_capability(self):
        capability = _make_capability()
        self.registry.register(capability)
        self.assertIs(self.registry.get("greet"), capability)

    def test_register_returns_the_capability(self):
        capability = _make_capability()
        returned = self.registry.register(capability)
        self.assertIs(returned, capability)

    def test_register_never_calls_the_handler(self):
        calls = []
        capability = _make_capability(handler=lambda data: calls.append(data))
        self.registry.register(capability)
        self.assertEqual(calls, [])

    def test_registered_capability_is_enabled_by_default(self):
        capability = _make_capability()
        self.registry.register(capability)
        self.assertTrue(self.registry.is_available("greet"))

    def test_register_can_start_disabled_when_explicitly_asked(self):
        capability = _make_capability()
        self.registry.register(capability, enabled=False)
        self.assertFalse(self.registry.is_available("greet"))


class TestDuplicateRegistration(unittest.TestCase):
    def setUp(self):
        self.registry = ExecutableCapabilityRegistry()
        self.original = _make_capability()
        self.registry.register(self.original)

    def test_registering_the_same_name_again_raises(self):
        duplicate = _make_capability()
        with self.assertRaises(ValueError):
            self.registry.register(duplicate)

    def test_duplicate_registration_leaves_the_original_in_place(self):
        duplicate = _make_capability()
        with self.assertRaises(ValueError):
            self.registry.register(duplicate)
        self.assertIs(self.registry.get("greet"), self.original)

    def test_after_unregistering_the_same_name_can_be_registered_again(self):
        self.registry.unregister("greet")
        replacement = _make_capability()
        self.registry.register(replacement)
        self.assertIs(self.registry.get("greet"), replacement)


class TestInvalidCapability(unittest.TestCase):
    def setUp(self):
        self.registry = ExecutableCapabilityRegistry()

    def test_rejects_a_plain_callable(self):
        with self.assertRaises(TypeError):
            self.registry.register(lambda data: data)

    def test_rejects_none(self):
        with self.assertRaises(TypeError):
            self.registry.register(None)

    def test_rejects_a_plain_dict_shaped_like_a_capability(self):
        with self.assertRaises(TypeError):
            self.registry.register({"name": "greet"})

    def test_a_rejected_registration_stores_nothing(self):
        with self.assertRaises(TypeError):
            self.registry.register(None)
        self.assertFalse(self.registry.has("greet"))


# ----------------------------------------------------------------------
# Lookup
# ----------------------------------------------------------------------
class TestGet(unittest.TestCase):
    def setUp(self):
        self.registry = ExecutableCapabilityRegistry()

    def test_get_returns_none_for_an_unregistered_name(self):
        self.assertIsNone(self.registry.get("greet"))

    def test_get_returns_the_capability_once_registered(self):
        capability = _make_capability()
        self.registry.register(capability)
        self.assertIs(self.registry.get("greet"), capability)

    def test_get_never_raises_for_a_non_string_name(self):
        try:
            self.assertIsNone(self.registry.get(None))
            self.assertIsNone(self.registry.get(123))
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"get raised for a non-string name: {exc}")


class TestHas(unittest.TestCase):
    def setUp(self):
        self.registry = ExecutableCapabilityRegistry()

    def test_has_returns_false_for_an_unregistered_name(self):
        self.assertFalse(self.registry.has("greet"))

    def test_has_returns_true_once_registered(self):
        self.registry.register(_make_capability())
        self.assertTrue(self.registry.has("greet"))

    def test_has_is_true_even_when_disabled(self):
        self.registry.register(_make_capability(), enabled=False)
        self.assertTrue(self.registry.has("greet"))


class TestListAll(unittest.TestCase):
    def setUp(self):
        self.registry = ExecutableCapabilityRegistry()

    def test_list_all_is_empty_for_a_fresh_registry(self):
        self.assertEqual(self.registry.list_all(), [])

    def test_list_all_reflects_registrations_in_order(self):
        self.registry.register(_make_capability("greet"))
        self.registry.register(_make_capability("farewell"))
        names = [entry["name"] for entry in self.registry.list_all()]
        self.assertEqual(names, ["greet", "farewell"])

    def test_list_all_entries_reflect_enabled_and_availability(self):
        self.registry.register(_make_capability("greet"))
        self.registry.register(_make_capability("farewell"), enabled=False)
        by_name = {entry["name"]: entry for entry in self.registry.list_all()}
        self.assertTrue(by_name["greet"]["enabled"])
        self.assertTrue(by_name["greet"]["available"])
        self.assertFalse(by_name["farewell"]["enabled"])
        self.assertFalse(by_name["farewell"]["available"])


# ----------------------------------------------------------------------
# Enable / disable
# ----------------------------------------------------------------------
class TestEnable(unittest.TestCase):
    def setUp(self):
        self.registry = ExecutableCapabilityRegistry()
        self.registry.register(_make_capability(), enabled=False)

    def test_enable_makes_the_capability_available(self):
        self.assertFalse(self.registry.is_available("greet"))
        self.registry.enable("greet")
        self.assertTrue(self.registry.is_available("greet"))

    def test_enable_returns_true_when_an_entry_was_found(self):
        self.assertTrue(self.registry.enable("greet"))

    def test_enable_returns_false_for_an_unknown_name(self):
        self.assertFalse(self.registry.enable("never_registered"))


class TestDisable(unittest.TestCase):
    def setUp(self):
        self.registry = ExecutableCapabilityRegistry()
        self.registry.register(_make_capability())

    def test_disable_makes_the_capability_unavailable(self):
        self.assertTrue(self.registry.is_available("greet"))
        self.registry.disable("greet")
        self.assertFalse(self.registry.is_available("greet"))

    def test_disable_returns_true_when_an_entry_was_found(self):
        self.assertTrue(self.registry.disable("greet"))

    def test_disable_returns_false_for_an_unknown_name(self):
        self.assertFalse(self.registry.disable("never_registered"))

    def test_disable_never_removes_the_registration(self):
        self.registry.disable("greet")
        self.assertTrue(self.registry.has("greet"))
        self.assertIsNotNone(self.registry.get("greet"))


# ----------------------------------------------------------------------
# is_available
# ----------------------------------------------------------------------
class TestDisabledCapabilityIsUnavailable(unittest.TestCase):
    def test_disabled_at_registration_time(self):
        registry = ExecutableCapabilityRegistry()
        registry.register(_make_capability(), enabled=False)
        self.assertFalse(registry.is_available("greet"))

    def test_disabled_after_registration(self):
        registry = ExecutableCapabilityRegistry()
        registry.register(_make_capability())
        registry.disable("greet")
        self.assertFalse(registry.is_available("greet"))


class TestMissingCapabilityIsUnavailable(unittest.TestCase):
    def test_never_registered(self):
        registry = ExecutableCapabilityRegistry()
        self.assertFalse(registry.is_available("greet"))

    def test_unregistered_after_being_registered(self):
        registry = ExecutableCapabilityRegistry()
        registry.register(_make_capability())
        registry.unregister("greet")
        self.assertFalse(registry.is_available("greet"))

    def test_never_raises_for_a_non_string_name(self):
        registry = ExecutableCapabilityRegistry()
        try:
            self.assertFalse(registry.is_available(None))
            self.assertFalse(registry.is_available(""))
        except Exception as exc:  # pragma: no cover - should never happen
            self.fail(f"is_available raised for a bad name: {exc}")


class TestCapabilityWithInvalidHandlerIsUnavailable(unittest.TestCase):
    def test_handler_mutated_to_non_callable_after_registration(self):
        registry = ExecutableCapabilityRegistry()
        capability = _make_capability()
        registry.register(capability)
        self.assertTrue(registry.is_available("greet"))

        # `handler` is a plain, mutable attribute - is_available must
        # check it fresh rather than trust construction-time validity.
        capability.handler = "not-callable-anymore"
        self.assertFalse(registry.is_available("greet"))

    def test_is_available_never_calls_the_handler(self):
        calls = []
        capability = _make_capability(handler=lambda data: calls.append(data))
        registry = ExecutableCapabilityRegistry()
        registry.register(capability)
        registry.is_available("greet")
        self.assertEqual(calls, [])


# ----------------------------------------------------------------------
# describe()
# ----------------------------------------------------------------------
class TestDescribe(unittest.TestCase):
    def setUp(self):
        self.registry = ExecutableCapabilityRegistry()

    def test_describe_returns_none_for_an_unregistered_name(self):
        self.assertIsNone(self.registry.describe("greet"))

    def test_describe_includes_capability_fields_and_registry_state(self):
        capability = Capability("greet", lambda data: data, description="Greets.", version="9.0.0")
        self.registry.register(capability)

        description = self.registry.describe("greet")

        self.assertEqual(description["name"], "greet")
        self.assertEqual(description["description"], "Greets.")
        self.assertEqual(description["version"], "9.0.0")
        self.assertTrue(description["enabled"])
        self.assertTrue(description["available"])

    def test_describe_reflects_disabled_state(self):
        self.registry.register(_make_capability(), enabled=False)
        description = self.registry.describe("greet")
        self.assertFalse(description["enabled"])
        self.assertFalse(description["available"])

    def test_describe_never_calls_the_handler(self):
        calls = []
        capability = _make_capability(handler=lambda data: calls.append(data))
        self.registry.register(capability)
        self.registry.describe("greet")
        self.assertEqual(calls, [])


# ----------------------------------------------------------------------
# No automatic execution
# ----------------------------------------------------------------------
class TestNoAutomaticExecution(unittest.TestCase):
    def test_nothing_in_this_module_ever_calls_the_handler(self):
        calls = []
        capability = _make_capability(handler=lambda data: calls.append(data))
        registry = ExecutableCapabilityRegistry()

        registry.register(capability)
        registry.get("greet")
        registry.has("greet")
        registry.list_all()
        registry.enable("greet")
        registry.disable("greet")
        registry.enable("greet")
        registry.is_available("greet")
        registry.describe("greet")
        registry.unregister("greet")

        self.assertEqual(calls, [])

    def test_registry_never_auto_discovers_capabilities(self):
        registry = ExecutableCapabilityRegistry()
        # A freshly constructed registry has nothing in it - nothing
        # is ever scanned, imported, or guessed into existence.
        self.assertEqual(registry.list_all(), [])
        self.assertEqual(len(registry), 0)


# ----------------------------------------------------------------------
# Backward compatibility
# ----------------------------------------------------------------------
class TestBackwardCompatibility(unittest.TestCase):
    def setUp(self):
        self.handler_registry = CapabilityHandlerRegistry()

    def test_check_execution_readiness_default_behavior_is_unchanged(self):
        step = _FakeStep(["send_email"])
        readiness = self.handler_registry.check_execution_readiness(step)
        self.assertFalse(readiness.ready)
        self.assertIn("send_email", readiness.missing_handlers)

    def test_plain_callable_handlers_still_satisfy_readiness_alone(self):
        step = _FakeStep(["send_email"])
        self.handler_registry.register("send_email", lambda plan_step: "sent")
        readiness = self.handler_registry.check_execution_readiness(step)
        self.assertTrue(readiness.ready)

    def test_executable_registry_can_satisfy_readiness_when_supplied(self):
        step = _FakeStep(["greet"])
        executable_registry = ExecutableCapabilityRegistry()
        executable_registry.register(_make_capability("greet"))

        readiness = self.handler_registry.check_execution_readiness(
            step, executable_registry=executable_registry
        )

        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.capabilities[0]["status"], "ready")
        self.assertTrue(readiness.capabilities[0]["handler_registered"])

    def test_disabled_executable_capability_does_not_satisfy_readiness(self):
        step = _FakeStep(["greet"])
        executable_registry = ExecutableCapabilityRegistry()
        executable_registry.register(_make_capability("greet"), enabled=False)

        readiness = self.handler_registry.check_execution_readiness(
            step, executable_registry=executable_registry
        )

        self.assertFalse(readiness.ready)
        self.assertIn("greet", readiness.missing_handlers)

    def test_omitting_executable_registry_does_not_consult_it(self):
        # Same readiness call, no executable_registry argument at all
        # - must behave exactly like it did before this registry
        # existed, even though an ExecutableCapabilityRegistry with a
        # matching, available capability exists elsewhere.
        step = _FakeStep(["greet"])
        executable_registry = ExecutableCapabilityRegistry()
        executable_registry.register(_make_capability("greet"))

        readiness = self.handler_registry.check_execution_readiness(step)

        self.assertFalse(readiness.ready)
        self.assertIn("greet", readiness.missing_handlers)

    def test_capability_handler_registry_takes_precedence_when_both_have_it(self):
        step = _FakeStep(["greet"])
        self.handler_registry.register("greet", lambda plan_step: "from plain registry")
        executable_registry = ExecutableCapabilityRegistry()
        executable_registry.register(_make_capability("greet"), enabled=False)

        # The plain CapabilityHandlerRegistry already has a handler,
        # so it's never even necessary to consult executable_registry
        # for this capability - readiness is still True even though
        # the executable registry's own entry is disabled.
        readiness = self.handler_registry.check_execution_readiness(
            step, executable_registry=executable_registry
        )
        self.assertTrue(readiness.ready)

    def test_mixed_required_capabilities_from_both_sources(self):
        step = _FakeStep(["plain_one", "executable_one"])
        self.handler_registry.register("plain_one", lambda plan_step: "ok")
        executable_registry = ExecutableCapabilityRegistry()
        executable_registry.register(_make_capability("executable_one"))

        readiness = self.handler_registry.check_execution_readiness(
            step, executable_registry=executable_registry
        )
        self.assertTrue(readiness.ready)


if __name__ == "__main__":
    unittest.main()
