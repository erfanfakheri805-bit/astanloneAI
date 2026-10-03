"""
Tests for ToolDefinition (tools/tool_definition.py) - a plain data
record describing the shape of one not-yet-executable tool.

Run directly:
    python -m unittest tests.test_tool_definition -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.tool_definition import (
    DEFAULT_ACCESS_LEVEL,
    SUPPORTED_ACCESS_LEVELS,
    SUPPORTED_PERMISSIONS,
    ToolDefinition,
)


class TestConstruction(unittest.TestCase):
    def test_defaults(self):
        tool = ToolDefinition(name="web_search")

        self.assertEqual(tool.name, "web_search")
        self.assertEqual(tool.description, "")
        self.assertEqual(tool.version, "1.0.0")
        self.assertEqual(tool.input_schema, {})
        self.assertEqual(tool.output_schema, {})
        self.assertTrue(tool.enabled)
        self.assertEqual(tool.metadata, {})
        self.assertEqual(tool.requirements, {})
        self.assertEqual(tool.permissions, [])
        self.assertEqual(tool.access_level, "local")
        self.assertEqual(tool.access_level, DEFAULT_ACCESS_LEVEL)
        self.assertEqual(tool.capabilities, [])

    def test_construction_never_raises_for_bad_values(self):
        # Same "construction never raises" convention as LearningRecord
        # - is_valid() is the fitness check, not the constructor.
        tool = ToolDefinition(name="", description=123, version="", enabled="yes")

        self.assertFalse(tool.is_valid())


class TestIsValid(unittest.TestCase):
    def test_valid_tool(self):
        tool = ToolDefinition(
            name="file_operations",
            description="Read and write local files.",
            version="1.0.0",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            enabled=True,
            metadata={"category": "filesystem"},
        )

        self.assertTrue(tool.is_valid())

    def test_empty_name_is_invalid(self):
        self.assertFalse(ToolDefinition(name="").is_valid())
        self.assertFalse(ToolDefinition(name="   ").is_valid())
        self.assertFalse(ToolDefinition(name=None).is_valid())
        self.assertFalse(ToolDefinition(name=123).is_valid())

    def test_non_string_description_is_invalid(self):
        self.assertFalse(ToolDefinition(name="tool", description=123).is_valid())

    def test_empty_version_is_invalid(self):
        self.assertFalse(ToolDefinition(name="tool", version="").is_valid())
        self.assertFalse(ToolDefinition(name="tool", version="   ").is_valid())
        self.assertFalse(ToolDefinition(name="tool", version=None).is_valid())

    def test_non_dict_schema_is_invalid(self):
        self.assertFalse(ToolDefinition(name="tool", input_schema="bad").is_valid())
        self.assertFalse(ToolDefinition(name="tool", output_schema="bad").is_valid())

    def test_non_bool_enabled_is_invalid(self):
        self.assertFalse(ToolDefinition(name="tool", enabled="true").is_valid())
        self.assertFalse(ToolDefinition(name="tool", enabled=1).is_valid())

    def test_non_dict_metadata_is_invalid(self):
        self.assertFalse(ToolDefinition(name="tool", metadata="bad").is_valid())

    def test_valid_tool_with_requirements(self):
        tool = ToolDefinition(
            name="file_operations",
            requirements={
                "network": False,
                "filesystem": True,
                "external_application": False,
                "user_permission": True,
            },
        )

        self.assertTrue(tool.is_valid())

    def test_no_requirements_is_valid(self):
        # Backward compatibility: a tool built without ever mentioning
        # requirements must still be valid (requirements defaults to {}).
        self.assertTrue(ToolDefinition(name="tool").is_valid())

    def test_non_dict_requirements_is_invalid(self):
        self.assertFalse(
            ToolDefinition(name="tool", requirements="bad").is_valid()
        )
        self.assertFalse(
            ToolDefinition(name="tool", requirements=["network"]).is_valid()
        )
        self.assertFalse(
            ToolDefinition(name="tool", requirements=123).is_valid()
        )

    def test_valid_tool_with_permissions(self):
        tool = ToolDefinition(
            name="file_operations",
            permissions=["filesystem", "user_confirmation"],
        )

        self.assertTrue(tool.is_valid())

    def test_all_supported_permissions_are_valid(self):
        tool = ToolDefinition(name="tool", permissions=list(SUPPORTED_PERMISSIONS))

        self.assertTrue(tool.is_valid())

    def test_no_permissions_is_valid(self):
        # Backward compatibility: a tool built without ever mentioning
        # permissions must still be valid (permissions defaults to []).
        self.assertTrue(ToolDefinition(name="tool").is_valid())

    def test_duplicate_permissions_are_still_valid(self):
        # Duplicates are not a validity problem - only get_permissions()
        # is responsible for removing them.
        tool = ToolDefinition(
            name="tool", permissions=["network", "network", "filesystem"]
        )

        self.assertTrue(tool.is_valid())

    def test_unsupported_permission_is_invalid(self):
        self.assertFalse(
            ToolDefinition(name="tool", permissions=["network", "root_access"]).is_valid()
        )
        self.assertFalse(
            ToolDefinition(name="tool", permissions=["send_email"]).is_valid()
        )

    def test_non_list_permissions_is_invalid(self):
        self.assertFalse(
            ToolDefinition(name="tool", permissions="network").is_valid()
        )
        self.assertFalse(
            ToolDefinition(name="tool", permissions={"network": True}).is_valid()
        )
        self.assertFalse(
            ToolDefinition(name="tool", permissions=123).is_valid()
        )

    def test_non_string_or_empty_permission_entries_are_invalid(self):
        self.assertFalse(
            ToolDefinition(name="tool", permissions=["network", 123]).is_valid()
        )
        self.assertFalse(
            ToolDefinition(name="tool", permissions=["", "network"]).is_valid()
        )
        self.assertFalse(
            ToolDefinition(name="tool", permissions=["   "]).is_valid()
        )
        self.assertFalse(
            ToolDefinition(name="tool", permissions=[None]).is_valid()
        )

    def test_default_access_level_is_valid(self):
        # Backward compatibility: a tool built without ever mentioning
        # access_level must still be valid (defaults to "local").
        tool = ToolDefinition(name="tool")

        self.assertTrue(tool.is_valid())

    def test_each_supported_access_level_is_valid(self):
        for level in SUPPORTED_ACCESS_LEVELS:
            with self.subTest(access_level=level):
                tool = ToolDefinition(name="tool", access_level=level)
                self.assertTrue(tool.is_valid())

    def test_unsupported_access_level_is_invalid(self):
        self.assertFalse(
            ToolDefinition(name="tool", access_level="global").is_valid()
        )
        self.assertFalse(
            ToolDefinition(name="tool", access_level="root").is_valid()
        )
        self.assertFalse(
            ToolDefinition(name="tool", access_level="").is_valid()
        )

    def test_non_string_access_level_is_invalid(self):
        self.assertFalse(
            ToolDefinition(name="tool", access_level=123).is_valid()
        )
        self.assertFalse(
            ToolDefinition(name="tool", access_level=["local"]).is_valid()
        )

    def test_explicit_none_access_level_falls_back_to_default(self):
        # access_level=None is treated the same as omitting it entirely
        # (same convention as metadata=None/requirements=None/
        # permissions=None) - it becomes DEFAULT_ACCESS_LEVEL, not an
        # invalid None value.
        tool = ToolDefinition(name="tool", access_level=None)

        self.assertEqual(tool.access_level, DEFAULT_ACCESS_LEVEL)
        self.assertTrue(tool.is_valid())

    def test_empty_capabilities_is_valid(self):
        # Backward compatibility: a tool built without ever mentioning
        # capabilities must still be valid (capabilities defaults to []).
        self.assertTrue(ToolDefinition(name="tool").is_valid())

    def test_one_capability_is_valid(self):
        tool = ToolDefinition(name="tool", capabilities=["web_search"])

        self.assertTrue(tool.is_valid())

    def test_multiple_capabilities_are_valid(self):
        tool = ToolDefinition(
            name="tool",
            capabilities=["web_search", "file_access", "image_processing"],
        )

        self.assertTrue(tool.is_valid())

    def test_capability_names_are_not_restricted_to_a_fixed_vocabulary(self):
        # Unlike permissions, capabilities have no closed vocabulary -
        # any non-empty string name is accepted for this stage.
        tool = ToolDefinition(name="tool", capabilities=["some_future_capability"])

        self.assertTrue(tool.is_valid())

    def test_duplicate_capabilities_are_still_valid(self):
        # Duplicates are not a validity problem - only
        # get_capabilities() is responsible for removing them.
        tool = ToolDefinition(
            name="tool", capabilities=["web_search", "web_search", "file_access"]
        )

        self.assertTrue(tool.is_valid())

    def test_non_list_capabilities_is_invalid(self):
        self.assertFalse(
            ToolDefinition(name="tool", capabilities="web_search").is_valid()
        )
        self.assertFalse(
            ToolDefinition(
                name="tool", capabilities={"web_search": True}
            ).is_valid()
        )
        self.assertFalse(
            ToolDefinition(name="tool", capabilities=123).is_valid()
        )

    def test_non_string_or_empty_capability_entries_are_invalid(self):
        self.assertFalse(
            ToolDefinition(name="tool", capabilities=["web_search", 123]).is_valid()
        )
        self.assertFalse(
            ToolDefinition(name="tool", capabilities=["", "web_search"]).is_valid()
        )
        self.assertFalse(
            ToolDefinition(name="tool", capabilities=["   "]).is_valid()
        )
        self.assertFalse(
            ToolDefinition(name="tool", capabilities=[None]).is_valid()
        )


class TestGetRequirements(unittest.TestCase):
    def test_get_requirements_default(self):
        tool = ToolDefinition(name="tool")

        self.assertEqual(tool.get_requirements(), {})

    def test_get_requirements_with_values(self):
        tool = ToolDefinition(
            name="tool",
            requirements={
                "network": True,
                "filesystem": False,
                "external_application": False,
                "user_permission": True,
            },
        )

        self.assertEqual(tool.get_requirements(), {
            "network": True,
            "filesystem": False,
            "external_application": False,
            "user_permission": True,
        })

    def test_get_requirements_returns_safe_copy(self):
        tool = ToolDefinition(name="tool", requirements={"network": False})

        snapshot = tool.get_requirements()
        snapshot["network"] = True
        snapshot["extra"] = "mutated"

        self.assertEqual(tool.requirements, {"network": False})

    def test_get_requirements_never_executes_or_mutates_enabled(self):
        # Calling get_requirements() is purely a read - it must never
        # flip enabled, register anything, or otherwise act.
        tool = ToolDefinition(
            name="tool", enabled=True, requirements={"network": True}
        )

        tool.get_requirements()

        self.assertTrue(tool.enabled)


class TestGetPermissions(unittest.TestCase):
    def test_get_permissions_default(self):
        tool = ToolDefinition(name="tool")

        self.assertEqual(tool.get_permissions(), [])

    def test_get_permissions_with_values(self):
        tool = ToolDefinition(
            name="tool", permissions=["network", "user_confirmation"]
        )

        self.assertEqual(
            tool.get_permissions(), ["network", "user_confirmation"]
        )

    def test_get_permissions_removes_duplicates_preserving_order(self):
        tool = ToolDefinition(
            name="tool",
            permissions=[
                "user_confirmation", "network", "network",
                "filesystem", "user_confirmation",
            ],
        )

        # First-occurrence order preserved, duplicates removed.
        self.assertEqual(
            tool.get_permissions(),
            ["user_confirmation", "network", "filesystem"],
        )

    def test_get_permissions_returns_safe_copy(self):
        tool = ToolDefinition(name="tool", permissions=["network"])

        snapshot = tool.get_permissions()
        snapshot.append("filesystem")
        snapshot[0] = "mutated"

        self.assertEqual(tool.permissions, ["network"])

    def test_get_permissions_never_executes_or_grants_anything(self):
        # Calling get_permissions() is purely a read - it must never
        # flip enabled, register anything, or otherwise act.
        tool = ToolDefinition(
            name="tool", enabled=True, permissions=["network", "user_account"]
        )

        tool.get_permissions()

        self.assertTrue(tool.enabled)
        self.assertEqual(tool.permissions, ["network", "user_account"])


class TestRequiresPermission(unittest.TestCase):
    def test_tool_with_one_permission(self):
        tool = ToolDefinition(name="tool", permissions=["network"])

        self.assertTrue(tool.requires_permission("network"))
        self.assertFalse(tool.requires_permission("filesystem"))

    def test_tool_with_multiple_permissions(self):
        tool = ToolDefinition(
            name="tool",
            permissions=["network", "filesystem", "user_confirmation"],
        )

        self.assertTrue(tool.requires_permission("network"))
        self.assertTrue(tool.requires_permission("filesystem"))
        self.assertTrue(tool.requires_permission("user_confirmation"))
        self.assertFalse(tool.requires_permission("user_account"))
        self.assertFalse(tool.requires_permission("external_application"))

    def test_existing_permission_returns_true(self):
        tool = ToolDefinition(name="tool", permissions=["external_application"])

        self.assertTrue(tool.requires_permission("external_application"))

    def test_missing_permission_returns_false(self):
        tool = ToolDefinition(name="tool", permissions=["network"])

        self.assertFalse(tool.requires_permission("user_account"))

    def test_no_permissions_returns_false_for_anything(self):
        tool = ToolDefinition(name="tool")

        self.assertFalse(tool.requires_permission("network"))
        self.assertFalse(tool.requires_permission("filesystem"))

    def test_duplicate_permissions_behave_correctly(self):
        tool = ToolDefinition(
            name="tool", permissions=["network", "network", "network"]
        )

        self.assertTrue(tool.requires_permission("network"))
        self.assertFalse(tool.requires_permission("filesystem"))

    def test_empty_permission_name_returns_false(self):
        tool = ToolDefinition(name="tool", permissions=["network"])

        self.assertFalse(tool.requires_permission(""))
        self.assertFalse(tool.requires_permission("   "))

    def test_invalid_permission_type_returns_false(self):
        tool = ToolDefinition(name="tool", permissions=["network"])

        self.assertFalse(tool.requires_permission(None))
        self.assertFalse(tool.requires_permission(123))
        self.assertFalse(tool.requires_permission(["network"]))
        self.assertFalse(tool.requires_permission({"network": True}))

    def test_requires_permission_never_mutates_or_executes(self):
        # Purely a metadata query - must never flip enabled, register
        # anything, or otherwise act.
        tool = ToolDefinition(
            name="tool", enabled=True, permissions=["network"]
        )

        tool.requires_permission("network")
        tool.requires_permission("filesystem")

        self.assertTrue(tool.enabled)
        self.assertEqual(tool.permissions, ["network"])


class TestGetAccessLevel(unittest.TestCase):
    def test_get_access_level_default(self):
        tool = ToolDefinition(name="tool")

        self.assertEqual(tool.get_access_level(), "local")
        self.assertEqual(tool.get_access_level(), DEFAULT_ACCESS_LEVEL)

    def test_get_access_level_for_each_supported_level(self):
        for level in SUPPORTED_ACCESS_LEVELS:
            with self.subTest(access_level=level):
                tool = ToolDefinition(name="tool", access_level=level)
                self.assertEqual(tool.get_access_level(), level)

    def test_get_access_level_never_grants_access_or_executes(self):
        # Calling get_access_level() is purely a read - it must never
        # flip enabled, register anything, request permissions, or
        # otherwise act.
        tool = ToolDefinition(
            name="tool", enabled=True, access_level="external"
        )

        tool.get_access_level()

        self.assertTrue(tool.enabled)
        self.assertEqual(tool.access_level, "external")


class TestGetCapabilities(unittest.TestCase):
    def test_get_capabilities_default_is_empty(self):
        tool = ToolDefinition(name="tool")

        self.assertEqual(tool.get_capabilities(), [])

    def test_get_capabilities_with_one_capability(self):
        tool = ToolDefinition(name="tool", capabilities=["web_search"])

        self.assertEqual(tool.get_capabilities(), ["web_search"])

    def test_get_capabilities_with_multiple_capabilities(self):
        tool = ToolDefinition(
            name="tool",
            capabilities=["web_search", "file_access", "image_processing"],
        )

        self.assertEqual(
            tool.get_capabilities(),
            ["web_search", "file_access", "image_processing"],
        )

    def test_get_capabilities_removes_duplicates_preserving_order(self):
        tool = ToolDefinition(
            name="tool",
            capabilities=[
                "file_access", "web_search", "web_search",
                "image_processing", "file_access",
            ],
        )

        # First-occurrence order preserved, duplicates removed.
        self.assertEqual(
            tool.get_capabilities(),
            ["file_access", "web_search", "image_processing"],
        )

    def test_get_capabilities_returns_safe_copy(self):
        tool = ToolDefinition(name="tool", capabilities=["web_search"])

        snapshot = tool.get_capabilities()
        snapshot.append("file_access")
        snapshot[0] = "mutated"

        self.assertEqual(tool.capabilities, ["web_search"])

    def test_get_capabilities_never_executes_or_accesses_anything(self):
        # Calling get_capabilities() is purely a read - it must never
        # flip enabled, register anything, or otherwise act.
        tool = ToolDefinition(
            name="tool", enabled=True, capabilities=["web_search", "device_control"]
        )

        tool.get_capabilities()

        self.assertTrue(tool.enabled)
        self.assertEqual(tool.capabilities, ["web_search", "device_control"])


class TestHasCapability(unittest.TestCase):
    def test_tool_with_one_capability(self):
        tool = ToolDefinition(name="tool", capabilities=["web_search"])

        self.assertTrue(tool.has_capability("web_search"))
        self.assertFalse(tool.has_capability("file_access"))

    def test_tool_with_multiple_capabilities(self):
        tool = ToolDefinition(
            name="tool",
            capabilities=["web_search", "file_access", "code_generation"],
        )

        self.assertTrue(tool.has_capability("web_search"))
        self.assertTrue(tool.has_capability("file_access"))
        self.assertTrue(tool.has_capability("code_generation"))
        self.assertFalse(tool.has_capability("video_processing"))

    def test_existing_capability_returns_true(self):
        tool = ToolDefinition(name="tool", capabilities=["automation"])

        self.assertTrue(tool.has_capability("automation"))

    def test_missing_capability_returns_false(self):
        tool = ToolDefinition(name="tool", capabilities=["web_search"])

        self.assertFalse(tool.has_capability("publishing"))

    def test_no_capabilities_returns_false_for_anything(self):
        tool = ToolDefinition(name="tool")

        self.assertFalse(tool.has_capability("web_search"))

    def test_duplicate_capabilities_behave_correctly(self):
        tool = ToolDefinition(
            name="tool", capabilities=["web_search", "web_search"]
        )

        self.assertTrue(tool.has_capability("web_search"))
        self.assertFalse(tool.has_capability("file_access"))

    def test_empty_capability_name_returns_false(self):
        tool = ToolDefinition(name="tool", capabilities=["web_search"])

        self.assertFalse(tool.has_capability(""))
        self.assertFalse(tool.has_capability("   "))

    def test_invalid_capability_type_returns_false(self):
        tool = ToolDefinition(name="tool", capabilities=["web_search"])

        self.assertFalse(tool.has_capability(None))
        self.assertFalse(tool.has_capability(123))
        self.assertFalse(tool.has_capability(["web_search"]))
        self.assertFalse(tool.has_capability({"web_search": True}))

    def test_has_capability_never_mutates_or_executes(self):
        # Purely a metadata query - must never flip enabled, register
        # anything, or otherwise act.
        tool = ToolDefinition(
            name="tool", enabled=True, capabilities=["web_search"]
        )

        tool.has_capability("web_search")
        tool.has_capability("file_access")

        self.assertTrue(tool.enabled)
        self.assertEqual(tool.capabilities, ["web_search"])


class TestToDict(unittest.TestCase):
    def test_to_dict_shape(self):
        tool = ToolDefinition(
            name="image_generation",
            description="Generate images from a prompt.",
            version="2.0.0",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            enabled=False,
            metadata={"category": "media"},
            requirements={"network": True, "user_permission": True},
            permissions=["network", "user_confirmation"],
            access_level="network",
            capabilities=["web_search", "file_access"],
        )

        self.assertEqual(tool.to_dict(), {
            "name": "image_generation",
            "description": "Generate images from a prompt.",
            "version": "2.0.0",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "enabled": False,
            "metadata": {"category": "media"},
            "requirements": {"network": True, "user_permission": True},
            "permissions": ["network", "user_confirmation"],
            "access_level": "network",
            "capabilities": ["web_search", "file_access"],
        })

    def test_to_dict_default_requirements(self):
        # Backward compatibility: a tool built without requirements
        # still gets an explicit (empty) "requirements" key in to_dict().
        tool = ToolDefinition(name="tool")

        self.assertEqual(tool.to_dict()["requirements"], {})

    def test_to_dict_default_permissions(self):
        # Backward compatibility: a tool built without permissions
        # still gets an explicit (empty) "permissions" key in to_dict().
        tool = ToolDefinition(name="tool")

        self.assertEqual(tool.to_dict()["permissions"], [])

    def test_to_dict_default_access_level(self):
        # Backward compatibility: a tool built without access_level
        # still gets an explicit "access_level": "local" in to_dict().
        tool = ToolDefinition(name="tool")

        self.assertEqual(tool.to_dict()["access_level"], "local")

    def test_to_dict_default_capabilities(self):
        # Backward compatibility: a tool built without capabilities
        # still gets an explicit (empty) "capabilities" key in to_dict().
        tool = ToolDefinition(name="tool")

        self.assertEqual(tool.to_dict()["capabilities"], [])

    def test_to_dict_returns_safe_copies(self):
        tool = ToolDefinition(
            name="tool",
            input_schema={"a": 1},
            output_schema={"b": 2},
            metadata={"c": 3},
            requirements={"network": False},
            permissions=["network"],
            capabilities=["web_search"],
        )

        snapshot = tool.to_dict()
        snapshot["input_schema"]["a"] = "mutated"
        snapshot["output_schema"]["b"] = "mutated"
        snapshot["metadata"]["c"] = "mutated"
        snapshot["requirements"]["network"] = True
        snapshot["permissions"].append("filesystem")
        snapshot["capabilities"].append("file_access")

        self.assertEqual(tool.input_schema, {"a": 1})
        self.assertEqual(tool.output_schema, {"b": 2})
        self.assertEqual(tool.metadata, {"c": 3})
        self.assertEqual(tool.requirements, {"network": False})
        self.assertEqual(tool.permissions, ["network"])
        self.assertEqual(tool.capabilities, ["web_search"])


class TestBackwardCompatibility(unittest.TestCase):
    def test_existing_positional_and_keyword_construction_unaffected(self):
        # Tools built exactly the way earlier stages built them (no
        # mention of requirements at all) must keep working unchanged.
        tool = ToolDefinition(
            name="web_search",
            description="Search the web.",
            version="1.0.0",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            enabled=True,
            metadata={"category": "search"},
        )

        self.assertTrue(tool.is_valid())
        self.assertEqual(tool.requirements, {})
        self.assertEqual(tool.get_requirements(), {})
        self.assertIn("requirements", tool.to_dict())
        self.assertEqual(tool.permissions, [])
        self.assertEqual(tool.get_permissions(), [])
        self.assertIn("permissions", tool.to_dict())
        self.assertEqual(tool.access_level, "local")
        self.assertEqual(tool.get_access_level(), "local")
        self.assertIn("access_level", tool.to_dict())
        self.assertFalse(tool.requires_permission("network"))
        self.assertEqual(tool.capabilities, [])
        self.assertEqual(tool.get_capabilities(), [])
        self.assertIn("capabilities", tool.to_dict())
        self.assertFalse(tool.has_capability("web_search"))


if __name__ == "__main__":
    unittest.main()
