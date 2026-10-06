"""
Prompt 898 - Section 17 (Controlled Autonomy): approval authority source contract.

Deterministic, read-only tests of autonomy/approval_authority_source.py. The module only
DESCRIBES what kind of authority could provide a future approval. "valid" is not approval, not
implementation permission and not execution permission.

Run (from app/src/main/python/):
    python -m unittest tests.test_approval_authority_source_prompt898 -v
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

from autonomy import approval_authority_source as mod
from autonomy.approval_authority_source import (
    AUTHORITY_TYPES, DESCRIPTOR_KEYS, STATUSES, build_approval_authority_source as build,
    validate_approval_authority_source as validate)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(ROOT, "autonomy", "approval_authority_source.py")
DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(ROOT)))),
                   "docs", "approval_authority_source_prompt898.md")

RESULT_KEYS = ("status", "valid", "errors", "execution_allowed", "executed")
BUILD_KEYS = ("status", "descriptor", "execution_allowed", "executed")


def args(**over):
    base = {"authority_id": "user_001", "authority_type": "user",
            "scope": "controlled_implementation", "purpose": "implementation_approval",
            "trusted": True, "approval_capable": True}
    base.update(over)
    return base


def desc(**over):
    """A valid descriptor dict, with optional overrides (never validated here)."""
    value = {"version": 1, "authority_id": "user_001", "authority_type": "user",
             "scope": "controlled_implementation", "purpose": "implementation_approval",
             "trusted": True, "approval_capable": True, "implementation_allowed": False,
             "execution_allowed": False}
    value.update(over)
    return value


def status_of(descriptor):
    return validate(descriptor)["status"]


class ValidDescriptorTests(unittest.TestCase):
    def test_valid_user_authority(self):
        result = build(**args())
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["descriptor"]["authority_type"], "user")
        self.assertEqual(status_of(result["descriptor"]), "valid")

    def test_valid_system_policy_authority(self):
        result = build(**args(authority_id="policy_alpha", authority_type="system_policy"))
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["descriptor"]["authority_type"], "system_policy")

    def test_valid_trusted_internal_controller_authority(self):
        result = build(**args(authority_id="controller_main",
                              authority_type="trusted_internal_controller"))
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["descriptor"]["authority_type"], "trusted_internal_controller")

    def test_descriptor_has_exactly_the_nine_keys(self):
        descriptor = build(**args())["descriptor"]
        self.assertEqual(tuple(descriptor), DESCRIPTOR_KEYS)
        self.assertEqual(len(descriptor), 9)
        self.assertIs(type(descriptor["version"]), int)
        self.assertEqual(descriptor["version"], 1)
        for value in descriptor.values():
            self.assertIn(type(value), (int, str, bool))

    def test_descriptive_flags_are_independent(self):
        for trusted in (True, False):
            for capable in (True, False):
                result = build(**args(trusted=trusted, approval_capable=capable))
                self.assertEqual(result["status"], "valid")
                self.assertIs(result["descriptor"]["trusted"], trusted)
                self.assertIs(result["descriptor"]["approval_capable"], capable)

    def test_permissions_stay_false_for_every_valid_type(self):
        for kind in AUTHORITY_TYPES:
            descriptor = build(**args(authority_type=kind))["descriptor"]
            self.assertIs(descriptor["implementation_allowed"], False)
            self.assertIs(descriptor["execution_allowed"], False)

    def test_valid_result_shape(self):
        result = validate(desc())
        self.assertEqual(tuple(result), RESULT_KEYS)
        self.assertIs(result["valid"], True)
        self.assertEqual(result["errors"], [])
        self.assertIs(result["execution_allowed"], False)
        self.assertIs(result["executed"], False)


class AuthorityIdTests(unittest.TestCase):
    def test_invalid_authority_ids(self):
        bad = ["", " ", "User", "1user", "_user", "user-001", "user 001", "user__", "user\n",
               "a" * 65, "user.001", "اکو", None, 7, 1.5, True, [], {}, ("user",), b"user"]
        for value in bad:
            with self.subTest(value=value):
                self.assertEqual(status_of(desc(authority_id=value)), "invalid_authority_id")
                self.assertEqual(build(**args(authority_id=value))["status"],
                                 "invalid_authority_id")

    def test_maximum_length_id_is_accepted(self):
        self.assertEqual(status_of(desc(authority_id="a" * 64)), "valid")

    def test_id_cannot_be_an_endpoint_command_or_key(self):
        for value in ("https_example", "api_key_one", "eval_source", "exec_shell",
                      "lambda_authority", "secret_holder", "apikey123", "callback_user",
                      "curl_remote", "approved_user", "sudo_user"):
            with self.subTest(value=value):
                self.assertEqual(status_of(desc(authority_id=value)), "invalid_authority_id")


class AuthorityTypeTests(unittest.TestCase):
    def test_unsupported_authority_types(self):
        for value in ("admin", "root", "User", "USER", " user", "user ", "", "system",
                      "external_service", "human", None, 3, ["user"], {"t": "user"}):
            with self.subTest(value=value):
                self.assertEqual(status_of(desc(authority_type=value)),
                                 "unsupported_authority_type")

    def test_approval_words_as_type_are_unsupported_status(self):
        for value in ("approved", "Approved", "granted", "authorized", "allowed",
                      "pending_approval", " approved "):
            with self.subTest(value=value):
                self.assertEqual(status_of(desc(authority_type=value)), "unsupported_status")


class ScopeAndPurposeTests(unittest.TestCase):
    def test_invalid_scopes(self):
        for value in ("", "Scope", "scope-one", "scope one", "all", "any_scope",
                      "global_scope", "unrestricted", "wildcard_scope", "*", None, 1, [],
                      "s" * 65, "scope\n", "https_scope"):
            with self.subTest(value=value):
                self.assertEqual(status_of(desc(scope=value)), "invalid_scope")

    def test_invalid_purposes(self):
        for value in ("", "Purpose", "purpose text", "purpose-one", None, 1, False, [], {},
                      "p" * 65, "purpose\n", "run_command", "approved_purpose",
                      "implementation_allowed"):
            with self.subTest(value=value):
                self.assertEqual(status_of(desc(purpose=value)), "invalid_purpose")

    def test_valid_scope_and_purpose_labels(self):
        for scope, purpose in (("controlled_implementation", "implementation_approval"),
                               ("capability_review", "review_gate"), ("s1", "p1")):
            with self.subTest(scope=scope):
                self.assertEqual(status_of(desc(scope=scope, purpose=purpose)), "valid")


class MalformedDescriptorTests(unittest.TestCase):
    def test_non_dict_descriptors(self):
        for value in (None, "descriptor", 5, 1.5, True, [], [desc()], (desc(),), set(),
                      b"x", object(), print):
            with self.subTest(value=repr(value)[:30]):
                self.assertEqual(status_of(value), "invalid_authority")

    def test_each_missing_key_is_rejected(self):
        for key in DESCRIPTOR_KEYS:
            with self.subTest(key=key):
                descriptor = desc()
                del descriptor[key]
                result = validate(descriptor)
                self.assertEqual(result["status"], "invalid_authority")
                self.assertIn({"code": "missing_key", "where": key}, result["errors"])

    def test_wrong_version(self):
        for value in (0, 2, -1, "1", 1.0, True, None, [1]):
            with self.subTest(value=value):
                self.assertEqual(status_of(desc(version=value)), "invalid_authority")

    def test_dict_subclass_is_rejected(self):
        class Forged(dict):
            pass
        self.assertEqual(status_of(Forged(desc())), "invalid_authority")

    def test_non_string_key_is_rejected(self):
        descriptor = desc()
        descriptor[5] = "x"
        self.assertEqual(status_of(descriptor), "invalid_authority")

    def test_errors_are_bounded(self):
        result = validate({str(n): n for n in range(100)})
        self.assertLessEqual(len(result["errors"]), mod.MAX_ERRORS)


class FlagTests(unittest.TestCase):
    def test_non_boolean_flags_are_rejected(self):
        for key in mod.FLAGS:
            for value in (1, 0, "True", "false", None, [], {}, 1.0, "", b"1"):
                with self.subTest(key=key, value=value):
                    self.assertEqual(status_of(desc(**{key: value})), "invalid_flags")

    def test_non_boolean_flags_in_builder(self):
        self.assertEqual(build(**args(trusted="yes"))["status"], "invalid_flags")
        self.assertEqual(build(**args(approval_capable=1))["status"], "invalid_flags")
        self.assertEqual(build(**args(implementation_allowed=0))["status"], "invalid_flags")
        self.assertEqual(build(**args(execution_allowed=None))["status"], "invalid_flags")
        self.assertEqual(build("user_001", "user", "scope_one", "purpose_one")["status"],
                         "invalid_flags")


class ForbiddenPermissionTests(unittest.TestCase):
    def test_implementation_allowed_true_is_rejected(self):
        self.assertEqual(status_of(desc(implementation_allowed=True)), "forbidden_permission")
        result = build(**args(implementation_allowed=True))
        self.assertEqual(result["status"], "forbidden_permission")
        self.assertIsNone(result["descriptor"])

    def test_execution_allowed_true_is_rejected(self):
        self.assertEqual(status_of(desc(execution_allowed=True)), "forbidden_permission")
        result = build(**args(execution_allowed=True))
        self.assertEqual(result["status"], "forbidden_permission")
        self.assertIsNone(result["descriptor"])

    def test_both_permissions_true_is_rejected(self):
        result = validate(desc(implementation_allowed=True, execution_allowed=True))
        self.assertEqual(result["status"], "forbidden_permission")
        self.assertEqual(len(result["errors"]), 2)

    def test_every_type_rejects_permissions(self):
        for kind in AUTHORITY_TYPES:
            for key in mod.PERMISSION_FLAGS:
                with self.subTest(kind=kind, key=key):
                    self.assertEqual(status_of(desc(authority_type=kind, **{key: True})),
                                     "forbidden_permission")


class ForgedFieldTests(unittest.TestCase):
    def test_extra_unexpected_fields_are_rejected(self):
        for key in ("extra", "owner", "signature", "implementation_started", "executed",
                    "callback", "endpoint", ""):
            with self.subTest(key=key):
                descriptor = desc()
                descriptor[key] = "x"
                self.assertEqual(status_of(descriptor), "invalid_authority")

    def test_approval_concept_fields_are_unsupported_status(self):
        for key in ("approved", "Approved", "approval_status", "status", "granted",
                    "authorized", "approved_by"):
            with self.subTest(key=key):
                descriptor = desc()
                descriptor[key] = True
                self.assertEqual(status_of(descriptor), "unsupported_status")

    def test_approved_status_value_is_never_a_valid_descriptor(self):
        descriptor = desc(authority_type="approved")
        self.assertEqual(status_of(descriptor), "unsupported_status")
        self.assertNotEqual(status_of(descriptor), "valid")

    def test_no_approved_status_in_vocabulary(self):
        for status in STATUSES:
            self.assertNotIn("approved", status)
        self.assertFalse(hasattr(mod, "STATUS_APPROVED"))


class ExecutableAuthorityTests(unittest.TestCase):
    def test_callable_authority_values_are_rejected(self):
        def func():
            return "user"
        for key, expected in (("authority_id", "invalid_authority_id"),
                              ("authority_type", "unsupported_authority_type"),
                              ("scope", "invalid_scope"), ("purpose", "invalid_purpose")):
            for value in (func, lambda: "user", print, str, type):
                with self.subTest(key=key):
                    self.assertEqual(status_of(desc(**{key: value})), expected)

    def test_string_commands_code_urls_and_keys_are_rejected(self):
        bad = ["__import__('os')", "os.system('ls')", "eval('1')", "lambda: 1",
               "https://example.com/approve", "http://localhost:8080", "rm -rf /",
               "sk-live-123456", "AKIA1234567890", "curl http://x", "a;b", "a|b", "$(id)"]
        for value in bad:
            for key, expected in (("authority_id", "invalid_authority_id"),
                                  ("scope", "invalid_scope"),
                                  ("purpose", "invalid_purpose")):
                with self.subTest(value=value, key=key):
                    self.assertEqual(status_of(desc(**{key: value})), expected)

    def test_executable_value_in_type_is_unsupported(self):
        for value in ("lambda: 'user'", "https://auth.example.com", "exec", "sk-123"):
            with self.subTest(value=value):
                self.assertEqual(status_of(desc(authority_type=value)),
                                 "unsupported_authority_type")

    def test_validation_never_calls_a_supplied_callable(self):
        calls = []

        def spy():
            calls.append(1)
            return "user"
        for key in ("authority_id", "authority_type", "scope", "purpose", "trusted"):
            validate(desc(**{key: spy}))
        build(**args(authority_id=spy, scope=spy))
        self.assertEqual(calls, [])


class DeterminismTests(unittest.TestCase):
    def test_repeated_validation_is_identical(self):
        descriptor = desc()
        first = validate(descriptor)
        for _ in range(5):
            self.assertEqual(validate(descriptor), first)

    def test_repeated_builds_are_identical_and_fresh(self):
        first = build(**args())
        second = build(**args())
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertIsNot(first["descriptor"], second["descriptor"])

    def test_mutating_a_result_does_not_affect_later_calls(self):
        result = build(**args())
        result["descriptor"]["implementation_allowed"] = True
        result["status"] = "approved"
        again = build(**args())
        self.assertEqual(again["status"], "valid")
        self.assertIs(again["descriptor"]["implementation_allowed"], False)

    def test_only_documented_statuses_are_returned(self):
        cases = [desc(), desc(authority_id=""), desc(authority_type="x"), desc(scope=""),
                 desc(purpose=""), desc(trusted=1), desc(execution_allowed=True),
                 desc(authority_type="approved"), None, {}]
        seen = {status_of(case) for case in cases}
        self.assertEqual(seen, set(STATUSES) - {"validation_error"})

    def test_status_vocabulary_is_exact(self):
        self.assertEqual(STATUSES, (
            "valid", "invalid_authority", "invalid_authority_id", "unsupported_authority_type",
            "invalid_scope", "invalid_purpose", "invalid_flags", "forbidden_permission",
            "unsupported_status", "validation_error"))

    def test_internal_failure_maps_to_validation_error(self):
        with mock.patch.object(mod, "_check", side_effect=RuntimeError("boom")):
            self.assertEqual(validate(desc())["status"], "validation_error")
            self.assertEqual(build(**args())["status"], "validation_error")
            self.assertIsNone(build(**args())["descriptor"])
            self.assertIs(validate(desc())["execution_allowed"], False)


class NoMutationTests(unittest.TestCase):
    def test_validate_does_not_modify_the_descriptor(self):
        for descriptor in (desc(), desc(authority_id=""), desc(extra=1),
                           desc(execution_allowed=True)):
            before = copy.deepcopy(descriptor)
            validate(descriptor)
            self.assertEqual(descriptor, before)
            self.assertEqual(list(descriptor), list(before))

    def test_build_does_not_modify_mutable_inputs(self):
        scope = ["not", "a", "label"]
        before = copy.deepcopy(scope)
        build(**args(scope=scope))
        self.assertEqual(scope, before)

    def test_built_descriptor_is_not_shared_with_inputs(self):
        descriptor = build(**args())["descriptor"]
        descriptor["scope"] = "changed"
        self.assertEqual(build(**args())["descriptor"]["scope"], "controlled_implementation")


class NoGrantTests(unittest.TestCase):
    def test_execution_flags_always_false_in_every_outcome(self):
        outcomes = [build(**args()), build(**args(execution_allowed=True)),
                    build(**args(authority_id="")), build(), validate(desc()),
                    validate(desc(implementation_allowed=True)), validate(None)]
        for outcome in outcomes:
            self.assertIs(outcome["execution_allowed"], False)
            self.assertIs(outcome["executed"], False)

    def test_builder_result_shape(self):
        for result in (build(**args()), build()):
            self.assertEqual(tuple(result), BUILD_KEYS)


class SafetyScanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(MODULE_PATH, "r", encoding="utf-8") as handle:
            cls.source = handle.read()
        cls.tree = ast.parse(cls.source)

    def test_no_forbidden_imports(self):
        banned = {"os", "sys", "subprocess", "socket", "http", "urllib", "requests", "shutil",
                  "pathlib", "ctypes", "importlib", "threading", "multiprocessing",
                  "asyncio", "sqlite3", "pickle", "random", "time", "datetime", "json",
                  "anthropic", "openai", "tempfile", "glob", "io"}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split(".")[0], banned, alias.name)
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn((node.module or "").split(".")[0], banned, node.module)

    def test_only_expected_imports(self):
        modules = sorted((node.module if isinstance(node, ast.ImportFrom) else
                          node.names[0].name)
                         for node in ast.walk(self.tree)
                         if isinstance(node, (ast.Import, ast.ImportFrom)))
        self.assertEqual(modules, ["capabilities.capability_registry", "re"])

    def test_no_dynamic_or_io_calls(self):
        banned_calls = {"open", "exec", "eval", "compile", "__import__", "input", "system",
                        "popen", "run", "write", "remove", "mkdir", "getattr", "setattr",
                        "globals", "locals"}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "compile":
                    self.assertEqual(func.value.id, "re")  # only the regex compile
                    continue
                name = func.id if isinstance(func, ast.Name) else \
                    func.attr if isinstance(func, ast.Attribute) else None
                self.assertNotIn(name, banned_calls, name)

    def test_no_classes_and_exactly_two_entry_points(self):
        self.assertFalse([n for n in ast.walk(self.tree) if isinstance(n, ast.ClassDef)])
        public = [n.name for n in self.tree.body
                  if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]
        self.assertEqual(sorted(public), ["build_approval_authority_source",
                                          "validate_approval_authority_source"])

    def test_no_filesystem_network_or_process_behavior(self):
        with mock.patch("builtins.open", side_effect=AssertionError("open")), \
                mock.patch.object(socket, "socket", side_effect=AssertionError("socket")), \
                mock.patch.object(socket, "create_connection",
                                  side_effect=AssertionError("network")), \
                mock.patch.object(subprocess, "Popen", side_effect=AssertionError("proc")), \
                mock.patch.object(subprocess, "run", side_effect=AssertionError("run")), \
                mock.patch.object(os, "system", side_effect=AssertionError("system")), \
                mock.patch.object(os, "remove", side_effect=AssertionError("remove")), \
                mock.patch.object(os, "mkdir", side_effect=AssertionError("mkdir")):
            self.assertEqual(build(**args())["status"], "valid")
            self.assertEqual(validate(desc())["status"], "valid")
            self.assertEqual(status_of(desc(authority_id="http://x")), "invalid_authority_id")
            self.assertEqual(build(**args(implementation_allowed=True))["status"],
                             "forbidden_permission")

    def test_upstream_modules_do_not_reference_this_module(self):
        paths = [os.path.join(ROOT, "autonomy", n) for n in os.listdir(
            os.path.join(ROOT, "autonomy")) if n.endswith(".py")
            # Relaxed in Prompt 899/900/902: the downstream scope / readiness modules import it.
            and n not in ("approval_authority_source.py", "approval_authority_scope.py",
                          "approval_scope_context_validation.py", "claude_exit_readiness.py")]
        self.assertTrue(paths)
        for path in paths:
            with open(path, "r", encoding="utf-8") as handle:
                self.assertNotIn("approval_authority_source", handle.read())

    def test_autonomy_package_contains_the_section17_modules(self):
        names = sorted(n for n in os.listdir(os.path.join(ROOT, "autonomy"))
                       if n != "__pycache__")
        for required in ("__init__.py", "implementation_permission_policy.py",
                         "implementation_approval_request.py",
                         "implementation_approval_decision.py",
                         "implementation_approval_decision_validation.py",
                         "approval_authority_source.py"):
            self.assertIn(required, names)


class DocumentationTests(unittest.TestCase):
    def test_doc_exists_and_states_the_invariants(self):
        self.assertTrue(os.path.isfile(DOC))
        with open(DOC, "r", encoding="utf-8") as handle:
            text = handle.read()
        for needle in ("authority_id", "authority_type", "scope", "purpose", "trusted",
                       "approval_capable", "implementation_allowed", "execution_allowed",
                       "user", "system_policy", "trusted_internal_controller",
                       "forbidden_permission", "unsupported_status", "invalid_flags",
                       "validation_error", "descriptive"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
