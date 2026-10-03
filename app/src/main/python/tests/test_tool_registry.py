"""
Tests for ToolRegistry (tools/tool_registry.py) - a small, in-memory
registry of ToolDefinition objects.

Covers: registering a valid tool, duplicate registration, get, has,
unregister, enable, disable, availability, list_all, an invalid tool,
and safe returned data.

Run directly:
    python -m unittest tests.test_tool_registry -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.tool_definition import ToolDefinition
from tools.tool_registry import ToolRegistry


def _make_tool(name="web_search", **kwargs):
    return ToolDefinition(name=name, **kwargs)


class TestRegisteringAValidTool(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()

    def test_register_stores_the_tool(self):
        tool = _make_tool()
        self.registry.register(tool)
        self.assertIs(self.registry.get("web_search"), tool)

    def test_register_returns_the_tool(self):
        tool = _make_tool()
        returned = self.registry.register(tool)
        self.assertIs(returned, tool)

    def test_register_strips_surrounding_whitespace_from_name(self):
        tool = _make_tool(name="  web_search  ")
        self.registry.register(tool)
        self.assertTrue(self.registry.has("web_search"))

    def test_registration_is_deterministic(self):
        registry_a = ToolRegistry()
        registry_b = ToolRegistry()
        registry_a.register(_make_tool())
        registry_b.register(_make_tool())

        self.assertEqual(registry_a.list_all(), registry_b.list_all())


class TestDuplicateRegistration(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.registry.register(_make_tool())

    def test_duplicate_name_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.registry.register(_make_tool())

    def test_duplicate_registration_does_not_overwrite(self):
        original = self.registry.get("web_search")
        try:
            self.registry.register(_make_tool(description="a different tool"))
        except ValueError:
            pass

        self.assertIs(self.registry.get("web_search"), original)
        self.assertEqual(self.registry.get("web_search").description, "")


class TestGet(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()

    def test_get_registered_tool(self):
        tool = _make_tool()
        self.registry.register(tool)
        self.assertIs(self.registry.get("web_search"), tool)

    def test_get_unknown_tool_returns_none(self):
        self.assertIsNone(self.registry.get("unknown"))

    def test_get_invalid_name_returns_none(self):
        self.assertIsNone(self.registry.get(""))
        self.assertIsNone(self.registry.get(None))
        self.assertIsNone(self.registry.get(123))


class TestHas(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.registry.register(_make_tool())

    def test_has_registered_tool(self):
        self.assertTrue(self.registry.has("web_search"))

    def test_has_unknown_tool(self):
        self.assertFalse(self.registry.has("unknown"))

    def test_has_disabled_tool_is_still_true(self):
        self.registry.disable("web_search")
        self.assertTrue(self.registry.has("web_search"))


class TestUnregister(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.registry.register(_make_tool())

    def test_unregister_existing_tool(self):
        result = self.registry.unregister("web_search")
        self.assertTrue(result)
        self.assertFalse(self.registry.has("web_search"))

    def test_unregister_unknown_tool_returns_false(self):
        self.assertFalse(self.registry.unregister("unknown"))

    def test_unregister_allows_reregistration(self):
        self.registry.unregister("web_search")
        new_tool = _make_tool(description="rebuilt")
        self.registry.register(new_tool)
        self.assertIs(self.registry.get("web_search"), new_tool)


class TestEnable(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.registry.register(_make_tool(enabled=False))

    def test_enable_existing_tool(self):
        result = self.registry.enable("web_search")
        self.assertTrue(result)
        self.assertTrue(self.registry.get("web_search").enabled)

    def test_enable_unknown_tool_returns_false(self):
        self.assertFalse(self.registry.enable("unknown"))


class TestDisable(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.registry.register(_make_tool(enabled=True))

    def test_disable_existing_tool(self):
        result = self.registry.disable("web_search")
        self.assertTrue(result)
        self.assertFalse(self.registry.get("web_search").enabled)

    def test_disable_unknown_tool_returns_false(self):
        self.assertFalse(self.registry.disable("unknown"))


class TestAvailability(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()

    def test_enabled_tool_is_available(self):
        self.registry.register(_make_tool(enabled=True))
        self.assertTrue(self.registry.is_available("web_search"))

    def test_disabled_tool_is_unavailable(self):
        self.registry.register(_make_tool(enabled=True))
        self.registry.disable("web_search")
        self.assertFalse(self.registry.is_available("web_search"))

    def test_unregistered_tool_is_unavailable(self):
        self.assertFalse(self.registry.is_available("unknown"))

    def test_reenabled_tool_is_available_again(self):
        self.registry.register(_make_tool(enabled=True))
        self.registry.disable("web_search")
        self.registry.enable("web_search")
        self.assertTrue(self.registry.is_available("web_search"))


class TestListAll(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()

    def test_empty_registry_returns_empty_list(self):
        self.assertEqual(self.registry.list_all(), [])

    def test_list_all_returns_registration_order(self):
        self.registry.register(_make_tool(name="web_search"))
        self.registry.register(_make_tool(name="file_operations"))
        self.registry.register(_make_tool(name="code_execution"))

        names = [entry["name"] for entry in self.registry.list_all()]
        self.assertEqual(names, ["web_search", "file_operations", "code_execution"])

    def test_list_all_reflects_current_enabled_state(self):
        self.registry.register(_make_tool(enabled=True))
        self.registry.disable("web_search")

        entries = self.registry.list_all()
        self.assertEqual(entries[0]["enabled"], False)


class TestInvalidTool(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()

    def test_non_tool_definition_raises_type_error(self):
        with self.assertRaises(TypeError):
            self.registry.register({"name": "web_search"})
        with self.assertRaises(TypeError):
            self.registry.register("web_search")
        with self.assertRaises(TypeError):
            self.registry.register(None)

    def test_invalid_tool_definition_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.registry.register(ToolDefinition(name=""))
        with self.assertRaises(ValueError):
            self.registry.register(ToolDefinition(name="tool", version=""))
        with self.assertRaises(ValueError):
            self.registry.register(ToolDefinition(name="tool", metadata="bad"))

    def test_invalid_tool_is_not_stored(self):
        try:
            self.registry.register(ToolDefinition(name=""))
        except ValueError:
            pass
        self.assertEqual(self.registry.list_all(), [])


class TestSafeReturnedData(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.registry.register(_make_tool(metadata={"a": 1}))

    def test_list_all_entries_are_independent_copies(self):
        entries_a = self.registry.list_all()
        entries_a[0]["metadata"]["a"] = "mutated"
        entries_a[0]["name"] = "mutated"

        entries_b = self.registry.list_all()
        self.assertEqual(entries_b[0]["name"], "web_search")
        self.assertEqual(entries_b[0]["metadata"], {"a": 1})

    def test_list_all_mutation_does_not_affect_registered_tool(self):
        entries = self.registry.list_all()
        entries[0]["metadata"]["a"] = "mutated"

        tool = self.registry.get("web_search")
        self.assertEqual(tool.metadata, {"a": 1})

    def test_appending_to_list_all_does_not_affect_registry(self):
        entries = self.registry.list_all()
        entries.append("extra")

        self.assertEqual(len(self.registry.list_all()), 1)


if __name__ == "__main__":
    unittest.main()
