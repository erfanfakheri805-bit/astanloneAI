"""
Prompt 899 - Section 17 (Controlled Autonomy): approval authority scope boundary.

Deterministic, read-only tests of autonomy/approval_authority_scope.py. The module only
DESCRIBES the boundary (one authority, one capability, one operation) of what an approval
authority source could one day be asked to approve. "valid" is not approval, not
implementation permission and not execution permission.

Run (from app/src/main/python/):
    python -m unittest tests.test_approval_authority_scope_prompt899 -v
"""

import ast
import copy
import os
import socket
import subprocess
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autonomy import approval_authority_scope as mod
from autonomy.approval_authority_scope import (
    SCOPE_KEYS, STATUSES, build_approval_authority_scope as build,
    validate_approval_authority_scope as validate_structure,
    validate_approval_authority_scope_context as check)
from autonomy.approval_authority_source import build_approval_authority_source as build_authority

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(ROOT, "autonomy", "approval_authority_scope.py")
DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(ROOT)))),
                   "docs", "approval_authority_scope_prompt899.md")

RESULT_KEYS = ("status", "valid", "errors", "execution_allowed", "executed")
BUILD_KEYS = ("status", "scope_descriptor", "execution_allowed", "executed")


def authority(**over):
    """A valid Prompt 898 authority descriptor (built by the real Prompt 898 builder)."""
    params = {"authority_id": "user_001", "authority_type": "user",
              "scope": "controlled_implementation", "purpose": "implementation_approval",
              "trusted": True, "approval_capable": True}
    params.update(over)
    return build_authority(**params)["descriptor"]


def args(**over):
    base = {"scope_id": "scope_001", "capability_name": "image_editor", "operation": "create",
            "scope": "capability_boundary", "purpose": "implementation_approval"}
    base.update(over)
    return base


def sdesc(**over):
    """A valid scope descriptor dict, with optional overrides (never validated here)."""
    value = {"version": 1, "scope_id": "scope_001", "authority_id": "user_001",
             "capability_name": "image_editor", "operation": "create",
             "scope": "capability_boundary", "purpose": "implementation_approval",
             "approval_capable": True, "implementation_allowed": False,
             "execution_allowed": False}
    value.update(over)
    return value


_DEFAULT = object()


def status_of(scope, auth=_DEFAULT):
    return check(authority() if auth is _DEFAULT else auth, scope)["status"]


class ValidScopeTests(unittest.TestCase):
    def test_valid_create_scope(self):
        result = build(authority(), **args())
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["scope_descriptor"]["operation"], "create")
        self.assertEqual(status_of(result["scope_descriptor"]), "valid")

    def test_valid_improve_scope(self):
        result = build(authority(), **args(operation="improve"))
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["scope_descriptor"]["operation"], "improve")

    def test_valid_user_authority(self):
        result = build(authority(), **args())
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["scope_descriptor"]["authority_id"], "user_001")

    def test_valid_system_policy_authority(self):
        auth = authority(authority_id="policy_alpha", authority_type="system_policy")
        result = build(auth, **args())
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["scope_descriptor"]["authority_id"], "policy_alpha")

    def test_valid_trusted_internal_controller_authority(self):
        auth = authority(authority_id="controller_main",
                         authority_type="trusted_internal_controller")
        result = build(auth, **args())
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["scope_descriptor"]["authority_id"], "controller_main")

    def test_descriptor_has_exactly_the_ten_keys_and_primitive_values(self):
        descriptor = build(authority(), **args())["scope_descriptor"]
        self.assertEqual(tuple(descriptor), SCOPE_KEYS)
        self.assertEqual(len(descriptor), 10)
        self.assertIs(type(descriptor["version"]), int)
        self.assertEqual(descriptor["version"], 1)
        for value in descriptor.values():
            self.assertIn(type(value), (int, str, bool))

    def test_approval_capable_is_copied_from_the_authority(self):
        for capable in (True, False):
            descriptor = build(authority(approval_capable=capable), **args())["scope_descriptor"]
            self.assertIs(descriptor["approval_capable"], capable)

    def test_permissions_stay_false_for_every_operation(self):
        for operation in mod.SUPPORTED_OPERATIONS:
            descriptor = build(authority(), **args(operation=operation))["scope_descriptor"]
            self.assertIs(descriptor["implementation_allowed"], False)
            self.assertIs(descriptor["execution_allowed"], False)

    def test_valid_result_shape(self):
        for result in (check(authority(), sdesc()), validate_structure(sdesc())):
            self.assertEqual(tuple(result), RESULT_KEYS)
            self.assertIs(result["valid"], True)
            self.assertEqual(result["errors"], [])
            self.assertIs(result["execution_allowed"], False)
            self.assertIs(result["executed"], False)


class InvalidAuthorityTests(unittest.TestCase):
    def test_non_dict_authority_descriptors(self):
        for value in (None, "user", 5, True, [], [authority()], (authority(),), b"x", print):
            with self.subTest(value=repr(value)[:30]):
                self.assertEqual(status_of(sdesc(), value), "invalid_authority")
                self.assertEqual(build(value, **args())["status"], "invalid_authority")

    def test_malformed_authority_descriptors(self):
        cases = []
        for key in ("version", "authority_id", "trusted"):
            missing = authority()
            del missing[key]
            cases.append(missing)
        cases.append(dict(authority(), extra="x"))
        cases.append(authority() | {"authority_type": "admin"})
        cases.append(authority() | {"scope": "all"})
        cases.append(authority() | {"trusted": 1})
        cases.append({})
        for case in cases:
            with self.subTest(case=str(case)[:60]):
                self.assertEqual(status_of(sdesc(), case), "invalid_authority")

    def test_authority_with_permission_true_is_invalid(self):
        for key in ("implementation_allowed", "execution_allowed"):
            with self.subTest(key=key):
                self.assertEqual(status_of(sdesc(), authority() | {key: True}),
                                 "invalid_authority")

    def test_authority_id_in_scope_must_be_a_valid_label(self):
        for value in ("", "User", "user-001", "http://x", "a" * 65, None, 5, [], print,
                      "approved_user"):
            with self.subTest(value=value):
                self.assertEqual(status_of(sdesc(authority_id=value)), "invalid_authority")
                if value is not None:  # None means "copy from the authority" in the builder
                    self.assertEqual(build(authority(), **args(authority_id=value))["status"],
                                     "invalid_authority")

    def test_forged_authority_object_is_not_trusted(self):
        class Forged(dict):
            pass
        self.assertEqual(status_of(sdesc(), Forged(authority())), "invalid_authority")


class ScopeIdAndCapabilityTests(unittest.TestCase):
    BAD = ("", " ", "Scope", "1scope", "_scope", "scope-001", "scope 001", "scope__x",
           "scope\n", "s" * 65, "scope.001", None, 7, 1.5, True, [], {}, b"s", print,
           "https_scope", "api_key_scope", "eval_scope", "approved_scope")

    def test_invalid_scope_ids(self):
        for value in self.BAD:
            with self.subTest(value=value):
                self.assertEqual(status_of(sdesc(scope_id=value)), "invalid_scope_id")
                self.assertEqual(build(authority(), **args(scope_id=value))["status"],
                                 "invalid_scope_id")

    def test_invalid_capability_names(self):
        for value in self.BAD + ("all", "any_capability", "global_tools", "*"):
            with self.subTest(value=value):
                self.assertEqual(status_of(sdesc(capability_name=value)), "invalid_capability")
                self.assertEqual(build(authority(), **args(capability_name=value))["status"],
                                 "invalid_capability")


class OperationTests(unittest.TestCase):
    def test_invalid_operations(self):
        for value in ("delete", "Create", "CREATE", " create", "create ", "", "update",
                      "create_or_improve", None, 1, True, ["create"], print, "run"):
            with self.subTest(value=value):
                self.assertEqual(status_of(sdesc(operation=value)), "invalid_operation")
                self.assertEqual(build(authority(), **args(operation=value))["status"],
                                 "invalid_operation")

    def test_improve_or_conflict_is_rejected(self):
        self.assertEqual(status_of(sdesc(operation="improve_or_conflict")),
                         "unsupported_status")
        result = build(authority(), **args(operation="improve_or_conflict"))
        self.assertEqual(result["status"], "unsupported_status")
        self.assertIsNone(result["scope_descriptor"])
        self.assertNotIn("improve_or_conflict", mod.SUPPORTED_OPERATIONS)

    def test_approval_words_as_operation_are_unsupported_status(self):
        for value in ("approved", "Approved", "authorization", "granted", "pending_approval"):
            with self.subTest(value=value):
                self.assertEqual(status_of(sdesc(operation=value)), "unsupported_status")


class ScopeAndPurposeTests(unittest.TestCase):
    def test_invalid_scope_labels(self):
        for value in ("", "Scope", "scope-one", "all", "any_scope", "global_scope", "*", None,
                      1, [], "s" * 65, "scope\n", "https_scope", "approved_scope", print):
            with self.subTest(value=value):
                self.assertEqual(status_of(sdesc(scope=value)), "invalid_scope")

    def test_invalid_purposes(self):
        for value in ("", "Purpose", "purpose text", None, 1, False, [], {}, "p" * 65,
                      "run_command", "approved_purpose", "implementation_allowed", print):
            with self.subTest(value=value):
                result = check(authority(), sdesc(purpose=value))
                self.assertEqual(result["status"], "invalid_scope")
                self.assertIn({"code": "invalid_purpose", "where": "purpose"}, result["errors"])


class ContextMismatchTests(unittest.TestCase):
    def test_mismatched_authority_id(self):
        result = check(authority(), sdesc(authority_id="user_002"))
        self.assertEqual(result["status"], "context_mismatch")
        self.assertIn({"code": "context_mismatch", "where": "authority_id"}, result["errors"])

    def test_mismatched_authority_id_in_builder(self):
        result = build(authority(), **args(authority_id="user_002"))
        self.assertEqual(result["status"], "context_mismatch")
        self.assertIsNone(result["scope_descriptor"])

    def test_mismatched_capability_name_with_a_scope_for_another_capability(self):
        # The scope is tied to ONE capability; a scope built for another capability is a
        # different scope and must not be accepted as the first one.
        first = build(authority(), **args(capability_name="image_editor"))["scope_descriptor"]
        other = build(authority(), **args(capability_name="pdf_reader"))["scope_descriptor"]
        self.assertNotEqual(first, other)
        self.assertNotEqual(first["capability_name"], other["capability_name"])
        forged = dict(first, capability_name="pdf_reader")
        self.assertEqual(forged, other)
        self.assertEqual(status_of(forged), "valid")
        self.assertNotEqual(forged, first)

    def test_mismatched_approval_capable(self):
        for capable in (True, False):
            with self.subTest(capable=capable):
                auth = authority(approval_capable=capable)
                result = check(auth, sdesc(approval_capable=not capable))
                self.assertEqual(result["status"], "context_mismatch")
                self.assertIn({"code": "context_mismatch", "where": "approval_capable"},
                              result["errors"])
                self.assertEqual(
                    build(auth, **args(approval_capable=not capable))["status"],
                    "context_mismatch")

    def test_structural_validation_does_not_check_the_authority(self):
        self.assertEqual(validate_structure(sdesc(authority_id="other_id"))["status"], "valid")
        self.assertEqual(status_of(sdesc(authority_id="other_id")), "context_mismatch")


class FlagTests(unittest.TestCase):
    def test_non_boolean_flags_are_rejected(self):
        for key in mod.BOOL_FLAGS:
            for value in (1, 0, "True", "false", None, [], {}, 1.0, "", b"1", print):
                with self.subTest(key=key, value=value):
                    result = check(authority(), sdesc(**{key: value}))
                    self.assertEqual(result["status"], "invalid_scope")
                    self.assertIn({"code": "invalid_flag", "where": key}, result["errors"])

    def test_non_boolean_flags_in_builder(self):
        self.assertEqual(build(authority(), **args(approval_capable="yes"))["status"],
                         "invalid_scope")
        self.assertEqual(build(authority(), **args(implementation_allowed=0))["status"],
                         "invalid_scope")
        self.assertEqual(build(authority(), **args(execution_allowed=None))["status"],
                         "invalid_scope")


class ForbiddenPermissionTests(unittest.TestCase):
    def test_implementation_allowed_true_is_rejected(self):
        self.assertEqual(status_of(sdesc(implementation_allowed=True)), "forbidden_permission")
        result = build(authority(), **args(implementation_allowed=True))
        self.assertEqual(result["status"], "forbidden_permission")
        self.assertIsNone(result["scope_descriptor"])

    def test_execution_allowed_true_is_rejected(self):
        self.assertEqual(status_of(sdesc(execution_allowed=True)), "forbidden_permission")
        result = build(authority(), **args(execution_allowed=True))
        self.assertEqual(result["status"], "forbidden_permission")
        self.assertIsNone(result["scope_descriptor"])

    def test_every_operation_and_authority_type_rejects_permissions(self):
        for kind in ("user", "system_policy", "trusted_internal_controller"):
            for operation in mod.SUPPORTED_OPERATIONS:
                for key in mod.PERMISSION_FLAGS:
                    with self.subTest(kind=kind, operation=operation, key=key):
                        auth = authority(authority_type=kind)
                        self.assertEqual(
                            build(auth, **args(operation=operation, **{key: True}))["status"],
                            "forbidden_permission")


class ForgedFieldTests(unittest.TestCase):
    def test_unexpected_fields_are_rejected(self):
        for key in ("extra", "owner", "signature", "implementation_started", "executed",
                    "callback", "endpoint", "trusted", ""):
            with self.subTest(key=key):
                descriptor = sdesc()
                descriptor[key] = "x"
                self.assertEqual(status_of(descriptor), "invalid_authority")
                self.assertEqual(validate_structure(descriptor)["status"], "invalid_authority")

    def test_each_missing_key_is_rejected(self):
        for key in SCOPE_KEYS:
            with self.subTest(key=key):
                descriptor = sdesc()
                del descriptor[key]
                result = check(authority(), descriptor)
                self.assertEqual(result["status"], "invalid_authority")
                self.assertIn({"code": "missing_key", "where": key}, result["errors"])

    def test_approval_and_authorization_fields_are_unsupported_status(self):
        for key in ("approved", "Approved", "approval_status", "status", "granted",
                    "authorization", "authorized", "approved_by"):
            with self.subTest(key=key):
                descriptor = sdesc()
                descriptor[key] = True
                self.assertEqual(status_of(descriptor), "unsupported_status")

    def test_no_approved_or_authorization_status_in_vocabulary(self):
        for status in STATUSES:
            for word in ("approved", "authoriz", "granted", "permitted"):
                self.assertNotIn(word, status)
        self.assertFalse(hasattr(mod, "STATUS_APPROVED"))
        self.assertEqual(STATUSES, (
            "valid", "invalid_authority", "invalid_scope", "invalid_scope_id",
            "invalid_capability", "invalid_operation", "context_mismatch",
            "forbidden_permission", "unsupported_status", "validation_error"))

    def test_malformed_scope_descriptors(self):
        for value in (None, "scope", 5, True, [], [sdesc()], (sdesc(),), b"x", print, object()):
            with self.subTest(value=repr(value)[:30]):
                self.assertEqual(status_of(value), "invalid_authority")
        class Forged(dict):
            pass
        self.assertEqual(status_of(Forged(sdesc())), "invalid_authority")
        bad = sdesc()
        bad[5] = "x"
        self.assertEqual(status_of(bad), "invalid_authority")


class ExecutableValueTests(unittest.TestCase):
    def test_callables_in_any_label_field_are_rejected(self):
        def func():
            return "user"
        expected = {"scope_id": "invalid_scope_id", "authority_id": "invalid_authority",
                    "capability_name": "invalid_capability", "operation": "invalid_operation",
                    "scope": "invalid_scope", "purpose": "invalid_scope"}
        for key, status in expected.items():
            for value in (func, lambda: "x", print, str, type):
                with self.subTest(key=key):
                    self.assertEqual(status_of(sdesc(**{key: value})), status)

    def test_urls_commands_code_and_keys_are_rejected(self):
        bad = ["__import__('os')", "os.system('ls')", "eval('1')", "lambda: 1",
               "https://example.com/approve", "http://localhost:8080", "rm -rf /",
               "sk-live-123456", "curl http://x", "a;b", "a|b", "$(id)"]
        expected = {"scope_id": "invalid_scope_id", "authority_id": "invalid_authority",
                    "capability_name": "invalid_capability", "scope": "invalid_scope",
                    "purpose": "invalid_scope"}
        for value in bad:
            for key, status in expected.items():
                with self.subTest(value=value, key=key):
                    self.assertEqual(status_of(sdesc(**{key: value})), status)

    def test_a_supplied_callable_is_never_called(self):
        calls = []

        def spy():
            calls.append(1)
            return "x"
        for key in ("scope_id", "capability_name", "operation", "scope", "purpose",
                    "approval_capable"):
            check(authority(), sdesc(**{key: spy}))
        build(spy, **args(scope_id=spy, scope=spy))
        build(authority(), **args(capability_name=spy, approval_capable=spy))
        self.assertEqual(calls, [])


class DeterminismTests(unittest.TestCase):
    def test_repeated_validation_is_identical(self):
        auth, descriptor = authority(), sdesc()
        first = check(auth, descriptor)
        for _ in range(5):
            self.assertEqual(check(auth, descriptor), first)
        self.assertEqual(validate_structure(descriptor), validate_structure(descriptor))

    def test_repeated_builds_are_identical_and_fresh(self):
        auth = authority()
        first, second = build(auth, **args()), build(auth, **args())
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertIsNot(first["scope_descriptor"], second["scope_descriptor"])

    def test_rejections_are_deterministic_and_use_only_documented_statuses(self):
        cases = [sdesc(), sdesc(authority_id="x_other"), sdesc(scope_id=""),
                 sdesc(capability_name=""), sdesc(operation="delete"), sdesc(scope=""),
                 sdesc(approval_capable=False), sdesc(implementation_allowed=True),
                 sdesc(operation="improve_or_conflict"), sdesc(extra=1), None]
        seen = set()
        for case in cases:
            first = check(authority(), case)
            self.assertEqual(first, check(authority(), copy.deepcopy(case)))
            self.assertIn(first["status"], STATUSES)
            seen.add(first["status"])
        self.assertEqual(seen, set(STATUSES) - {"validation_error"})

    def test_internal_failure_maps_to_validation_error(self):
        with mock.patch.object(mod, "_structure", side_effect=RuntimeError("boom")):
            self.assertEqual(validate_structure(sdesc())["status"], "validation_error")
            self.assertEqual(check(authority(), sdesc())["status"], "validation_error")
            result = build(authority(), **args())
            self.assertEqual(result["status"], "validation_error")
            self.assertIsNone(result["scope_descriptor"])
            self.assertIs(check(authority(), sdesc())["execution_allowed"], False)


class NoMutationTests(unittest.TestCase):
    def test_validators_do_not_modify_their_inputs(self):
        for scope in (sdesc(), sdesc(scope_id=""), sdesc(extra=1), sdesc(execution_allowed=True)):
            auth = authority()
            auth_before, scope_before = copy.deepcopy(auth), copy.deepcopy(scope)
            check(auth, scope)
            validate_structure(scope)
            self.assertEqual(auth, auth_before)
            self.assertEqual(scope, scope_before)
            self.assertEqual(list(scope), list(scope_before))

    def test_builder_does_not_modify_the_authority_or_mutable_inputs(self):
        auth = authority()
        before = copy.deepcopy(auth)
        bad_scope = ["not", "a", "label"]
        bad_before = copy.deepcopy(bad_scope)
        build(auth, **args())
        build(auth, **args(scope=bad_scope))
        self.assertEqual(auth, before)
        self.assertEqual(bad_scope, bad_before)


class NoGrantTests(unittest.TestCase):
    def test_execution_flags_false_in_every_outcome(self):
        auth = authority()
        outcomes = [build(auth, **args()), build(auth, **args(execution_allowed=True)),
                    build(auth, **args(scope_id="")), build(), build(None, **args()),
                    check(auth, sdesc()), check(auth, sdesc(implementation_allowed=True)),
                    check(None, None), validate_structure(sdesc()), validate_structure(None)]
        for outcome in outcomes:
            self.assertIs(outcome["execution_allowed"], False)
            self.assertIs(outcome["executed"], False)

    def test_rejected_builds_never_carry_a_descriptor(self):
        auth = authority()
        for over in ({"scope_id": ""}, {"capability_name": ""}, {"operation": "x"},
                     {"authority_id": "other"}, {"approval_capable": False},
                     {"implementation_allowed": True}, {"execution_allowed": True},
                     {"operation": "approved"}):
            with self.subTest(over=over):
                result = build(auth, **args(**over))
                self.assertNotEqual(result["status"], "valid")
                self.assertIsNone(result["scope_descriptor"])


class SafetyScanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(MODULE_PATH, "r", encoding="utf-8") as handle:
            cls.source = handle.read()
        cls.tree = ast.parse(cls.source)

    def test_no_forbidden_imports(self):
        banned = {"os", "sys", "subprocess", "socket", "http", "urllib", "requests", "shutil",
                  "pathlib", "ctypes", "importlib", "threading", "multiprocessing", "asyncio",
                  "sqlite3", "pickle", "random", "time", "datetime", "json", "anthropic",
                  "openai", "tempfile", "glob", "io", "re"}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split(".")[0], banned, alias.name)
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn((node.module or "").split(".")[0], banned, node.module)

    def test_only_expected_imports(self):
        modules = sorted(node.module for node in ast.walk(self.tree)
                         if isinstance(node, ast.ImportFrom))
        self.assertEqual(modules, ["approval_authority_source",
                                   "capabilities.capability_registry"])
        self.assertFalse([n for n in ast.walk(self.tree) if isinstance(n, ast.Import)])

    def test_no_dynamic_or_io_calls(self):
        banned_calls = {"open", "exec", "eval", "compile", "__import__", "input", "system",
                        "popen", "run", "write", "remove", "mkdir", "getattr", "setattr",
                        "globals", "locals"}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else \
                    func.attr if isinstance(func, ast.Attribute) else None
                self.assertNotIn(name, banned_calls, name)

    def test_no_classes_and_exactly_three_entry_points(self):
        self.assertFalse([n for n in ast.walk(self.tree) if isinstance(n, ast.ClassDef)])
        public = [n.name for n in self.tree.body
                  if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]
        self.assertEqual(sorted(public), ["build_approval_authority_scope",
                                          "validate_approval_authority_scope",
                                          "validate_approval_authority_scope_context"])

    def test_no_filesystem_network_or_process_behavior(self):
        auth = authority()
        with mock.patch("builtins.open", side_effect=AssertionError("open")), \
                mock.patch.object(socket, "socket", side_effect=AssertionError("socket")), \
                mock.patch.object(socket, "create_connection",
                                  side_effect=AssertionError("network")), \
                mock.patch.object(subprocess, "Popen", side_effect=AssertionError("proc")), \
                mock.patch.object(subprocess, "run", side_effect=AssertionError("run")), \
                mock.patch.object(os, "system", side_effect=AssertionError("system")), \
                mock.patch.object(os, "remove", side_effect=AssertionError("remove")), \
                mock.patch.object(os, "mkdir", side_effect=AssertionError("mkdir")):
            self.assertEqual(build(auth, **args())["status"], "valid")
            self.assertEqual(check(auth, sdesc())["status"], "valid")
            self.assertEqual(status_of(sdesc(scope_id="http://x")), "invalid_scope_id")
            self.assertEqual(build(auth, **args(execution_allowed=True))["status"],
                             "forbidden_permission")

    def test_upstream_modules_do_not_reference_this_module(self):
        names = [n for n in os.listdir(os.path.join(ROOT, "autonomy"))
                 if n.endswith(".py") and n not in (
                     "approval_authority_scope.py", "approval_scope_context_validation.py",
                     "claude_exit_readiness.py")]  # Prompt 902 (Section 18) is downstream
        self.assertIn("approval_authority_source.py", names)
        for name in names:
            with open(os.path.join(ROOT, "autonomy", name), "r", encoding="utf-8") as handle:
                self.assertNotIn("approval_authority_scope", handle.read())

    def test_autonomy_package_contains_the_section17_modules(self):
        names = sorted(n for n in os.listdir(os.path.join(ROOT, "autonomy"))
                       if n != "__pycache__")
        for required in ("__init__.py", "implementation_permission_policy.py",
                         "implementation_approval_request.py",
                         "implementation_approval_decision.py",
                         "implementation_approval_decision_validation.py",
                         "approval_authority_source.py", "approval_authority_scope.py"):
            self.assertIn(required, names)


class DocumentationTests(unittest.TestCase):
    def test_doc_exists_and_states_the_invariants(self):
        self.assertTrue(os.path.isfile(DOC))
        with open(DOC, "r", encoding="utf-8") as handle:
            text = handle.read()
        for needle in ("scope_id", "authority_id", "capability_name", "operation", "scope",
                       "purpose", "approval_capable", "implementation_allowed",
                       "execution_allowed", "create", "improve", "improve_or_conflict",
                       "context_mismatch", "forbidden_permission", "unsupported_status",
                       "invalid_scope_id", "invalid_capability", "invalid_operation",
                       "validation_error", "boundary"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
