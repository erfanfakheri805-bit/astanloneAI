"""
Prompt 895 - Section 17 (Controlled Autonomy): implementation approval request.

Deterministic, read-only tests of autonomy/implementation_approval_request.py. An approval
request only states that an eligible implementation request may be SUBMITTED for controlled
approval. "ready_for_approval" is not an approval, not implementation permission and not
execution permission.

Run (from app/src/main/python/):
    python -m unittest tests.test_implementation_approval_request_prompt895 -v
"""

import ast
import copy
import hashlib
import json
import os
import socket
import subprocess
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autonomy import implementation_approval_request as amod
from autonomy import implementation_permission_policy as pmod
from autonomy.implementation_approval_request import (
    FIELDS, RESULT_KEYS, STATUSES, build_implementation_approval_request as build,
    validate_implementation_approval_request as validate)
from autonomy.implementation_permission_policy import (
    build_implementation_permission_policy as build_policy)
from tests.test_implementation_permission_policy_prompt894 import (
    BOUNDARY, CONTRACT, CREPORT, IMPL, NAMES, R889, READINESS, REQUEST, SPEC, base_chain,
    conflict_chain, derive)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(ROOT, "autonomy", "implementation_approval_request.py")
DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(ROOT)))),
                   "docs", "implementation_approval_request_prompt895.md")
FLAGS = ("implementation_allowed", "execution_allowed", "implementation_started", "executed")


def full(op="create", pid="pol_001", state=None, vres=None, chain=None):
    """(chain objects, Prompt 892 result, Prompt 894 policy)."""
    chain = chain if chain is not None else base_chain(op)
    vres = derive(chain) if vres is None else vres
    return chain, vres, build_policy(*chain, vres, pid, state)


def make(op="create", aid="apr_001", **over):
    chain, vres, policy = full(op)
    chain = over.pop("chain", chain)
    vres = over.pop("vres", vres)
    policy = over.pop("policy", policy)
    return build(*chain, vres, policy, aid)


def ok(op="create"):
    return make(op)["approval_request"]


def codes(report):
    return [e["code"] for e in report["errors"]]


def tree_fingerprint():
    entries = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            if name.endswith(".pyc"):
                continue
            path = os.path.join(base, name)
            stat = os.stat(path)
            entries.append((os.path.relpath(path, ROOT), stat.st_size, stat.st_mtime_ns))
    return entries


def forbidden(*_a, **_k):
    raise AssertionError("forbidden operation attempted")


class HappyPathTests(unittest.TestCase):
    def test_create_is_ready_for_approval(self):
        r = make("create")
        self.assertEqual(r["status"], "ready_for_approval")
        self.assertEqual(r["approval_request"]["operation"], "create")
        self.assertIsNone(r["approval_request"]["existing_capability"])

    def test_improve_is_ready_for_approval(self):
        r = make("improve")
        self.assertEqual(r["status"], "ready_for_approval")
        self.assertEqual(r["approval_request"]["operation"], "improve")
        self.assertIsInstance(r["approval_request"]["existing_capability"], dict)

    def test_builder_result_shape(self):
        for op in ("create", "improve"):
            r = make(op)
            self.assertEqual(list(r), list(RESULT_KEYS))
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)

    def test_exact_seventeen_keys_in_order(self):
        self.assertEqual(len(FIELDS), 17)
        for op in ("create", "improve"):
            self.assertEqual(list(ok(op)), list(FIELDS))

    def test_version_is_integer_one(self):
        self.assertIs(type(ok()["version"]), int)
        self.assertEqual(ok()["version"], 1)

    def test_fields_come_from_trusted_chain(self):
        chain = base_chain()
        a = ok()
        impl = chain[IMPL]
        self.assertEqual(a["approval_request_id"], "apr_001")
        self.assertEqual(a["request_id"], impl["request_id"])
        self.assertEqual(a["implementation_request_id"], "ir_001")
        self.assertEqual(a["capability_name"], impl["capability_name"])
        self.assertEqual(a["policy_status"], "eligible")
        for key in ("purpose", "inputs", "outputs", "constraints", "existing_capability"):
            self.assertEqual(a[key], impl[key])

    def test_inputs_outputs_constraints_order_is_kept(self):
        a = ok()
        self.assertEqual(a["inputs"], ["z_input", "a_input"])
        self.assertEqual(a["outputs"], ["z_out", "a_out"])
        self.assertEqual(a["constraints"], ["Second.", "First.", "Second."])

    def test_valid_request_validates(self):
        for op in ("create", "improve"):
            report = validate(ok(op))
            self.assertTrue(report["valid"], report)
            self.assertIs(report["execution_allowed"], False)
            self.assertIs(report["executed"], False)

    def test_status_list_is_exactly_the_specified_eleven(self):
        self.assertEqual(set(STATUSES), {
            "ready_for_approval", "invalid_request", "invalid_request_validation",
            "invalid_boundary", "invalid_contract_readiness", "invalid_policy",
            "context_mismatch", "unsupported_status", "invalid_approval_request_id",
            "approval_request_error", "validation_error"})
        self.assertEqual(len(STATUSES), 11)

class NoPermissionTests(unittest.TestCase):
    def test_ready_for_approval_is_not_approved(self):
        for op in ("create", "improve"):
            r = make(op)
            self.assertEqual(r["status"], "ready_for_approval")
            self.assertNotEqual(r["status"], "approved")
            self.assertNotIn("approved", r["approval_request"])
            self.assertNotIn("approved", r)
            self.assertIs(r["approval_request"]["approval_required"], True)

    def test_ready_for_approval_is_not_implementation_allowed(self):
        for op in ("create", "improve"):
            r = make(op)
            self.assertEqual(r["status"], "ready_for_approval")
            self.assertIs(r["approval_request"]["implementation_allowed"], False)
            self.assertIs(r["approval_request"]["implementation_started"], False)
            self.assertNotIn("implementation_allowed", r)

    def test_ready_for_approval_is_not_execution_allowed(self):
        for op in ("create", "improve"):
            r = make(op)
            self.assertEqual(r["status"], "ready_for_approval")
            self.assertIs(r["approval_request"]["execution_allowed"], False)
            self.assertIs(r["approval_request"]["executed"], False)
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)

    def test_approval_required_is_true_and_flags_false(self):
        a = ok()
        self.assertIs(a["approval_required"], True)
        for flag in FLAGS:
            self.assertIs(a[flag], False)

    def test_validator_rejects_each_true_flag(self):
        for flag in FLAGS:
            report = validate(dict(ok(), **{flag: True}))
            self.assertFalse(report["valid"], flag)
            self.assertIn("invalid_flag", codes(report))

    def test_validator_rejects_approval_required_false(self):
        for bad in (False, 0, None, "True", 1):
            report = validate(dict(ok(), approval_required=bad))
            self.assertFalse(report["valid"], bad)
            self.assertIn("invalid_flag", codes(report))

    def test_extra_permission_like_keys_rejected(self):
        for key in ("approved", "approval_granted", "permission", "implementation_ready",
                    "status", "allowed", "approved_by"):
            report = validate(dict(ok(), **{key: False}))
            self.assertFalse(report["valid"], key)
            self.assertIn("unexpected_key", codes(report))


class RejectionTests(unittest.TestCase):
    def _assert_rejected(self, r, status):
        self.assertEqual(r["status"], status)
        self.assertIsNone(r["approval_request"])
        self.assertIs(r["execution_allowed"], False)
        self.assertIs(r["executed"], False)

    def test_ineligible_policy(self):
        with mock.patch.object(pmod, "SUPPORTED", ()):
            chain, vres, policy = full()
        self.assertEqual(policy["status"], "ineligible")
        self._assert_rejected(build(*chain, vres, policy, "apr_001"), "invalid_policy")

    def test_blocked_policy(self):
        state = dict.fromkeys(FLAGS, True)
        chain, vres, policy = full(state=state)
        self.assertEqual(policy["status"], "blocked")
        self._assert_rejected(build(*chain, vres, policy, "apr_001"), "invalid_policy")

    def test_unsupported_policy(self):
        chain = conflict_chain(base_chain()[3:])
        vres = derive(chain)
        policy = build_policy(*chain, vres, "pol_001")
        self.assertEqual(policy["status"], "unsupported")
        self._assert_rejected(build(*chain, vres, policy, "apr_001"), "unsupported_status")

    def test_invalid_policies(self):
        chain, vres, policy = full()
        bad = [None, {}, [], "eligible", dict(policy, eligible=False),
               dict(policy, status="validation_error", reason="validation_error"),
               dict(policy, implementation_allowed=True), dict(policy, version="1"),
               dict(policy, extra=1), build_policy(policy_id="pol_001")]
        for item in bad:
            self._assert_rejected(build(*chain, vres, item, "apr_001"), "invalid_policy")

    def test_invalid_prompt892_validation(self):
        chain, vres, policy = full()
        bad = [None, {}, [], "valid", dict(vres, valid=False), dict(vres, version="1"),
               dict(vres, extra=1), derive([None] + chain[1:])]
        for item in bad:
            self._assert_rejected(build(*chain, item, policy, "apr_001"),
                                  "invalid_request_validation")

    def test_invalid_boundary(self):
        chain, vres, policy = full()
        chain[BOUNDARY] = dict(chain[BOUNDARY], implementation_allowed=True)
        self._assert_rejected(build(*chain, vres, policy, "apr_001"), "invalid_boundary")
        chain[BOUNDARY] = None
        self._assert_rejected(build(*chain, vres, policy, "apr_001"), "invalid_boundary")

    def test_invalid_contract_readiness(self):
        chain, vres, policy = full()
        chain[R889] = dict(chain[R889], ready=False)
        self._assert_rejected(build(*chain, vres, policy, "apr_001"),
                              "invalid_contract_readiness")

    def test_invalid_implementation_request(self):
        chain, vres, policy = full()
        chain[IMPL] = dict(chain[IMPL], version="1")
        self._assert_rejected(build(*chain, vres, policy, "apr_001"), "invalid_request")
        chain[IMPL] = None
        self._assert_rejected(build(*chain, vres, policy, "apr_001"), "invalid_request")

    def test_invalid_evolution_request(self):
        chain, vres, policy = full()
        chain[REQUEST] = None
        self._assert_rejected(build(*chain, vres, policy, "apr_001"), "invalid_request")

    def test_other_broken_chain_objects_are_invalid_request_validation(self):
        for index in (SPEC, READINESS, CONTRACT, CREPORT):
            chain, vres, policy = full()
            chain[index] = None
            self._assert_rejected(build(*chain, vres, policy, "apr_001"),
                                  "invalid_request_validation")

    def test_improve_or_conflict_is_unsupported(self):
        for tail in (base_chain()[3:], base_chain("improve")[3:], [None] * 13):
            chain = conflict_chain(tail)
            policy = build_policy(*chain, derive(chain), "pol_001")
            for pol in (policy, None, {}):
                self._assert_rejected(build(*chain, derive(chain), pol, "apr_001"),
                                      "unsupported_status")

class ForgeryTests(unittest.TestCase):
    def _forged_policy(self, **over):
        chain, vres, policy = full()
        return build(*chain, vres, dict(policy, **over), "apr_001")

    def test_forged_policy_result_is_context_mismatch(self):
        for over in ({"request_id": "evo_999"}, {"implementation_request_id": "ir_999"},
                     {"capability_name": "other_capability"}, {"operation": "improve"},
                     {"policy_id": "pol_other"}):
            r = self._forged_policy(**over)
            if "policy_id" in over:
                continue  # a different but valid policy_id is a different, re-derivable policy
            self.assertEqual(r["status"], "context_mismatch", over)
            self.assertIsNone(r["approval_request"])

    def test_policy_from_other_chain_is_context_mismatch(self):
        chain, vres, _ = full("create")
        _, _, other = full("improve")
        r = build(*chain, vres, other, "apr_001")
        self.assertEqual(r["status"], "context_mismatch")
        self.assertIsNone(r["approval_request"])

    def test_forged_implementation_request(self):
        for key, value in (("purpose", "Other."), ("inputs", ["x"]), ("outputs", ["y"]),
                           ("constraints", ["z"]), ("capability_name", "other_capability"),
                           ("request_id", "evo_999"), ("implementation_request_id", "ir_999")):
            chain, vres, policy = full()
            chain[IMPL] = dict(chain[IMPL], **{key: value})
            r = build(*chain, vres, policy, "apr_001")
            self.assertIn(r["status"], ("context_mismatch", "invalid_request"), key)
            self.assertIsNone(r["approval_request"])

    def test_forged_existing_capability(self):
        chain, vres, policy = full("improve")
        chain[IMPL] = dict(chain[IMPL], existing_capability=None)
        r = build(*chain, vres, policy, "apr_001")
        self.assertNotEqual(r["status"], "ready_for_approval")
        self.assertIsNone(r["approval_request"])

    def test_forged_validation_result(self):
        chain, vres, policy = full()
        for key, value in (("plan_id", "plan_999"), ("contract_id", "ct_999"),
                           ("request_id", "evo_999"), ("capability_name", "other_one"),
                           ("implementation_request_id", "ir_999")):
            r = build(*chain, dict(vres, **{key: value}), policy, "apr_001")
            self.assertEqual(r["status"], "context_mismatch", key)

    def test_forged_boundary_and_readiness(self):
        for index in (BOUNDARY, R889):
            chain, vres, policy = full()
            chain[index] = dict(chain[index], plan_id="plan_999")
            r = build(*chain, vres, policy, "apr_001")
            self.assertEqual(r["status"], "context_mismatch", NAMES[index])

    def test_validation_result_of_other_operation_chain(self):
        chain, _, policy = full("create")
        r = build(*chain, derive(base_chain("improve")), policy, "apr_001")
        self.assertEqual(r["status"], "context_mismatch")

    def test_policy_status_mismatch(self):
        chain, vres, policy = full()
        for status in ("blocked", "ineligible", "unsupported", "validation_error"):
            forged = dict(policy, status=status, reason=status, eligible=False)
            r = build(*chain, vres, forged, "apr_001")
            self.assertEqual(r["status"], "invalid_policy", status)

class IdTests(unittest.TestCase):
    def test_invalid_approval_request_ids(self):
        for bad in (None, "", " ", 1, True, [], {}, "x" * 65, "bad\nid"):
            r = make(aid=bad)
            self.assertEqual(r["status"], "invalid_approval_request_id", repr(bad))
            self.assertIsNone(r["approval_request"])

    def test_valid_approval_request_ids_are_carried(self):
        for good in ("a", "apr_001", "x" * 64):
            self.assertEqual(make(aid=good)["approval_request"]["approval_request_id"], good)

    def test_id_is_never_generated(self):
        chain, vres, policy = full()
        self.assertEqual(build(*chain, vres, policy)["status"], "invalid_approval_request_id")

    def test_validator_rejects_invalid_ids(self):
        for key in ("approval_request_id", "request_id", "implementation_request_id",
                    "capability_name"):
            for bad in (None, "", 5, "x" * 65):
                report = validate(dict(ok(), **{key: bad}))
                self.assertFalse(report["valid"], (key, bad))

class ValidatorSchemaTests(unittest.TestCase):
    def test_wrong_version_type(self):
        for bad in (True, "1", 1.0, 2, 0, None):
            report = validate(dict(ok(), version=bad))
            self.assertFalse(report["valid"], bad)
            self.assertIn("invalid_version", codes(report))

    def test_missing_key(self):
        for key in FIELDS:
            a = ok()
            del a[key]
            report = validate(a)
            self.assertFalse(report["valid"], key)
            self.assertIn("missing_key", codes(report))

    def test_extra_key(self):
        report = validate(dict(ok(), extra="x"))
        self.assertFalse(report["valid"])
        self.assertIn("unexpected_key", codes(report))

    def test_policy_status_must_be_eligible(self):
        for bad in ("blocked", "ineligible", "unsupported", "ready", "", None, 1, "ELIGIBLE"):
            report = validate(dict(ok(), policy_status=bad))
            self.assertFalse(report["valid"], bad)
            self.assertIn("invalid_policy_status", codes(report))

    def test_operation_must_be_create_or_improve(self):
        for bad in ("improve_or_conflict", "delete", "", None, 1, "Create"):
            self.assertFalse(validate(dict(ok(), operation=bad))["valid"], bad)

    def test_field_types(self):
        cases = (("purpose", 5), ("purpose", ""), ("inputs", "x"), ("inputs", None),
                 ("outputs", "x"), ("outputs", []), ("constraints", "x"),
                 ("existing_capability", "x"), ("existing_capability", []))
        for key, bad in cases:
            self.assertFalse(validate(dict(ok(), **{key: bad}))["valid"], (key, bad))

    def test_non_dict_request(self):
        for bad in (None, [], "x", 1, ()):
            self.assertIn("request_not_dict", codes(validate(bad)))
        self.assertFalse(validate()["valid"])

    def test_validator_report_is_fresh_and_never_grants(self):
        a, b = validate(ok()), validate(ok())
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIs(a["execution_allowed"], False)
        self.assertIs(a["executed"], False)


class DeterminismTests(unittest.TestCase):
    def test_repeated_build_is_identical(self):
        for op in ("create", "improve"):
            runs = [json.dumps(make(op)) for _ in range(5)]
            self.assertEqual(len(set(runs)), 1)

    def test_fresh_objects_every_call(self):
        chain, vres, policy = full()
        a, b = build(*chain, vres, policy, "apr_001"), build(*chain, vres, policy, "apr_001")
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIsNot(a["approval_request"], b["approval_request"])
        a["approval_request"]["status"] = "tampered"
        self.assertNotIn("status", build(*chain, vres, policy, "apr_001")["approval_request"])

    def test_independent_of_time_and_randomness(self):
        with mock.patch("time.time", forbidden), mock.patch("random.random", forbidden):
            self.assertEqual(make()["status"], "ready_for_approval")


class SafetyTests(unittest.TestCase):
    def test_inputs_are_not_mutated(self):
        chain, vres, policy = full()
        snapshot = copy.deepcopy((chain, vres, policy))
        build(*chain, vres, policy, "apr_001")
        self.assertEqual((chain, vres, policy), snapshot)

    def test_result_shares_no_containers_with_inputs(self):
        chain, vres, policy = full()
        a = build(*chain, vres, policy, "apr_001")["approval_request"]
        a["inputs"].append("tampered")
        a["constraints"].append("tampered")
        self.assertEqual(chain[IMPL]["inputs"], ["z_input", "a_input"])
        self.assertEqual(chain[IMPL]["constraints"], ["Second.", "First.", "Second."])
        chain, vres, policy = full("improve")
        b = build(*chain, vres, policy, "apr_001")["approval_request"]
        b["existing_capability"]["name"] = "tampered"
        self.assertEqual(chain[IMPL]["existing_capability"]["name"], "text_summarizer")

    def test_mutation_of_result_does_not_leak(self):
        r = make()
        r["approval_request"]["implementation_allowed"] = True
        self.assertFalse(validate(r["approval_request"])["valid"])
        self.assertIs(make()["approval_request"]["implementation_allowed"], False)

    def test_no_filesystem_network_or_process_activity(self):
        chain, vres, policy = full()
        before = tree_fingerprint()
        with mock.patch("builtins.open", forbidden), \
                mock.patch.object(socket, "socket", forbidden), \
                mock.patch.object(socket, "create_connection", forbidden), \
                mock.patch.object(subprocess, "Popen", forbidden), \
                mock.patch.object(os, "system", forbidden), \
                mock.patch("builtins.exec", forbidden), \
                mock.patch("builtins.eval", forbidden), \
                mock.patch("builtins.compile", forbidden):
            r = build(*chain, vres, policy, "apr_001")
            self.assertEqual(r["status"], "ready_for_approval")
            self.assertTrue(validate(r["approval_request"])["valid"])
        self.assertEqual(before, tree_fingerprint())

    def test_module_level_state_is_unchanged(self):
        def state():
            return {k: repr(v) for k, v in vars(amod).items()
                    if isinstance(v, (list, dict, set, bytearray)) and not k.startswith("__")}
        before = state()
        make()
        validate(ok())
        self.assertEqual(before, state())

    def test_never_raises_on_garbage(self):
        junk = [None, 1, "x", [], {}, object(), float("nan"), {"a": {"b": []}}]
        for value in junk:
            r = build(*([value] * 18), value)
            self.assertIsNone(r["approval_request"])
            self.assertIn(r["status"], STATUSES)
            self.assertFalse(validate(value)["valid"])

    def test_unexpected_internal_failure_is_validation_error(self):
        chain, vres, policy = full()
        with mock.patch.object(amod, "build_implementation_permission_policy",
                               side_effect=RuntimeError("boom")):
            r = build(*chain, vres, policy, "apr_001")
        self.assertEqual(r["status"], "validation_error")
        self.assertIsNone(r["approval_request"])

    def test_built_request_failing_validator_is_approval_request_error(self):
        chain, vres, policy = full()
        bad = {"valid": False, "errors": [], "execution_allowed": False, "executed": False}
        with mock.patch.object(amod, "validate_implementation_approval_request",
                               return_value=bad):
            r = build(*chain, vres, policy, "apr_001")
        self.assertEqual(r["status"], "approval_request_error")
        self.assertIsNone(r["approval_request"])


class ForbiddenApiScanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(MODULE_PATH, "r", encoding="utf-8") as handle:
            cls.tree = ast.parse(handle.read())

    def test_imports_are_limited(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                self.assertEqual([a.name for a in node.names], ["copy"])
            if isinstance(node, ast.ImportFrom):
                if node.level == 0:
                    self.assertTrue(node.module.startswith("capabilities."), node.module)
                else:
                    self.assertEqual(node.module, "implementation_permission_policy")

    def test_no_forbidden_calls(self):
        banned = {"open", "exec", "eval", "compile", "__import__", "input", "print", "system",
                  "popen", "Popen", "run", "call", "urlopen", "setattr", "delattr",
                  "getattr", "globals", "locals", "vars"}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else \
                    func.attr if isinstance(func, ast.Attribute) else None
                self.assertNotIn(name, banned, name)

    def test_no_forbidden_names_or_attributes(self):
        banned = {"os", "sys", "subprocess", "socket", "http", "urllib", "requests", "shutil",
                  "pathlib", "time", "datetime", "random", "uuid", "secrets", "importlib",
                  "ctypes", "pickle", "anthropic", "openai", "memory", "ael", "registry"}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Name):
                self.assertNotIn(node.id, banned, node.id)
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, {"write", "write_text", "write_bytes", "mkdir",
                                             "remove", "unlink", "rename", "now", "utcnow",
                                             "urandom", "uuid4"}, node.attr)

    def test_no_classes_and_only_build_and_validate_entry_points(self):
        self.assertFalse([n for n in ast.walk(self.tree) if isinstance(n, ast.ClassDef)])
        public = [n.name for n in self.tree.body
                  if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]
        self.assertEqual(public, ["build_implementation_approval_request",
                                  "validate_implementation_approval_request"])

    def test_upstream_modules_do_not_reference_approval_request(self):
        paths = [os.path.join(ROOT, "autonomy", "implementation_permission_policy.py")]
        for name in ("capability_implementation_request_validation",
                     "capability_implementation_boundary", "capability_implementation_request"):
            paths.append(os.path.join(ROOT, "capabilities", name + ".py"))
        for path in paths:
            with open(path, "r", encoding="utf-8") as handle:
                self.assertNotIn("approval_request", handle.read())

    def test_autonomy_package_contents(self):
        names = sorted(n for n in os.listdir(os.path.join(ROOT, "autonomy"))
                       if n != "__pycache__")
        # Relaxed in Prompt 896: later Section 17 modules may join the package.
        for required in ("__init__.py", "implementation_approval_request.py",
                         "implementation_permission_policy.py"):
            self.assertIn(required, names)
        self.assertTrue(all(n.endswith(".py") for n in names), names)


class DocumentationTests(unittest.TestCase):
    def test_doc_exists_and_states_the_invariants(self):
        self.assertTrue(os.path.isfile(DOC))
        with open(DOC, "r", encoding="utf-8") as handle:
            text = handle.read()
        for needle in ("approval_required", "implementation_allowed", "execution_allowed",
                       "implementation_started", "executed", "ready_for_approval",
                       "improve_or_conflict", "eligib", "approval", "create", "improve"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
