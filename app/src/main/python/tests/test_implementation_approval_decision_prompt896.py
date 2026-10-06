"""
Prompt 896 - Section 17 (Controlled Autonomy): implementation approval decision contract.

Deterministic, read-only tests of autonomy/implementation_approval_decision.py. The contract
represents an approval request whose approval decision has NOT been made ("pending_approval").
It is a decision state, not an approval mechanism: "pending_approval" is not "approved", not
implementation permission and not execution permission.

Run (from app/src/main/python/):
    python -m unittest tests.test_implementation_approval_decision_prompt896 -v
"""

import ast
import copy
import json
import os
import socket
import subprocess
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autonomy import implementation_approval_decision as dmod
from autonomy import implementation_permission_policy as pmod
from autonomy.implementation_approval_decision import (
    FIELDS, RESULT_KEYS, STATUSES, build_implementation_approval_decision as build,
    validate_implementation_approval_decision as validate)
from autonomy.implementation_approval_request import (
    build_implementation_approval_request as build_approval,
    validate_implementation_approval_request as validate_approval)
from autonomy.implementation_permission_policy import (
    build_implementation_permission_policy as build_policy)
from tests.test_implementation_permission_policy_prompt894 import (
    BOUNDARY, IMPL, R889, SPEC, base_chain, conflict_chain, derive)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(ROOT, "autonomy", "implementation_approval_decision.py")
DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(ROOT)))),
                   "docs", "implementation_approval_decision_prompt896.md")
FLAGS = ("implementation_allowed", "execution_allowed", "implementation_started", "executed")

_CACHE = {}


def fx(op="create"):
    """(chain, Prompt 892 result, Prompt 894 policy, Prompt 895 request, 895 validation)."""
    if op not in _CACHE:
        chain = base_chain(op)
        vres = derive(chain)
        policy = build_policy(*chain, vres, "pol_001")
        approval = build_approval(*chain, vres, policy, "apr_001")["approval_request"]
        _CACHE[op] = (chain, vres, policy, approval, validate_approval(approval))
    return copy.deepcopy(_CACHE[op])


def make(op="create", did="dec_001", **over):
    chain, vres, policy, approval, avres = fx(op)
    chain = over.pop("chain", chain)
    vres = over.pop("vres", vres)
    policy = over.pop("policy", policy)
    approval = over.pop("approval", approval)
    avres = over.pop("avres", avres)
    return build(*chain, vres, policy, approval, avres, did)


def ok(op="create"):
    return make(op)["decision"]


def codes(report):
    return [e["code"] for e in report["errors"]]


def tree_fingerprint():
    entries = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            if name.endswith(".pyc"):
                continue
            stat = os.stat(os.path.join(base, name))
            entries.append((os.path.relpath(os.path.join(base, name), ROOT), stat.st_size,
                            stat.st_mtime_ns))
    return entries


def forbidden(*_a, **_k):
    raise AssertionError("forbidden operation attempted")


class HappyPathTests(unittest.TestCase):
    def test_create_is_pending_approval(self):
        r = make("create")
        self.assertEqual(r["status"], "pending_approval")
        self.assertEqual(r["decision"]["operation"], "create")

    def test_improve_is_pending_approval(self):
        r = make("improve")
        self.assertEqual(r["status"], "pending_approval")
        self.assertEqual(r["decision"]["operation"], "improve")

    def test_builder_result_shape(self):
        for op in ("create", "improve"):
            r = make(op)
            self.assertEqual(list(r), list(RESULT_KEYS))
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)

    def test_exact_fourteen_keys_in_order(self):
        self.assertEqual(len(FIELDS), 14)
        for op in ("create", "improve"):
            self.assertEqual(list(ok(op)), list(FIELDS))

    def test_version_is_integer_one(self):
        self.assertIs(type(ok()["version"]), int)
        self.assertEqual(ok()["version"], 1)

    def test_fields_come_from_trusted_chain(self):
        d = ok()
        self.assertEqual(d["decision_id"], "dec_001")
        self.assertEqual(d["request_id"], "evo_001")
        self.assertEqual(d["implementation_request_id"], "ir_001")
        self.assertEqual(d["approval_request_id"], "apr_001")
        self.assertEqual(d["capability_name"], "text_summarizer")
        self.assertEqual(d["reason"], "approval_decision_not_made")

    def test_valid_decision_validates(self):
        for op in ("create", "improve"):
            report = validate(ok(op))
            self.assertTrue(report["valid"], report)
            self.assertIs(report["execution_allowed"], False)
            self.assertIs(report["executed"], False)

    def test_status_list_is_exactly_the_specified_eleven(self):
        self.assertEqual(set(STATUSES), {
            "pending_approval", "invalid_request", "invalid_request_validation",
            "invalid_policy", "invalid_approval_request",
            "invalid_approval_request_validation", "context_mismatch", "unsupported_status",
            "invalid_decision_id", "decision_error", "validation_error"})
        self.assertEqual(len(STATUSES), 11)

    def test_only_pending_approval_is_successful_and_nothing_means_approved(self):
        for status in STATUSES:
            for word in ("approved", "allowed", "granted", "permitted", "started", "executed"):
                self.assertNotIn(word, status)
        self.assertNotIn("approved", STATUSES)
        self.assertEqual([s for s in STATUSES if make()["status"] == s], ["pending_approval"])


class NoApprovalTests(unittest.TestCase):
    def test_pending_approval_is_not_approved(self):
        for op in ("create", "improve"):
            r = make(op)
            self.assertEqual(r["decision"]["approval_status"], "pending_approval")
            self.assertNotEqual(r["decision"]["approval_status"], "approved")
            self.assertNotEqual(r["status"], "approved")
            self.assertNotIn("approved", r["decision"])
            self.assertIs(r["decision"]["approval_required"], True)

    def test_pending_approval_is_not_implementation_allowed(self):
        for op in ("create", "improve"):
            d = make(op)["decision"]
            self.assertEqual(d["approval_status"], "pending_approval")
            self.assertNotEqual(d["approval_status"], "implementation_allowed")
            self.assertIs(d["implementation_allowed"], False)
            self.assertIs(d["implementation_started"], False)

    def test_pending_approval_is_not_execution_allowed(self):
        for op in ("create", "improve"):
            d = make(op)["decision"]
            self.assertNotEqual(d["approval_status"], "execution_allowed")
            self.assertIs(d["execution_allowed"], False)
            self.assertIs(d["executed"], False)
            self.assertIs(make(op)["execution_allowed"], False)

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

    def test_validator_rejects_non_bool_flags(self):
        for flag in FLAGS:
            for bad in (0, None, "False"):
                self.assertFalse(validate(dict(ok(), **{flag: bad}))["valid"], (flag, bad))

    def test_validator_rejects_approved_and_permission_statuses(self):
        for bad in ("approved", "implementation_allowed", "execution_allowed", "granted",
                    "ready_for_approval", "rejected", "", None, 1, "PENDING_APPROVAL"):
            report = validate(dict(ok(), approval_status=bad))
            self.assertFalse(report["valid"], bad)
            self.assertIn("invalid_approval_status", codes(report))

    def test_extra_permission_like_keys_rejected(self):
        for key in ("approved", "approved_by", "approval_granted", "permission", "status"):
            report = validate(dict(ok(), **{key: False}))
            self.assertFalse(report["valid"], key)
            self.assertIn("unexpected_key", codes(report))


class UpstreamRejectionTests(unittest.TestCase):
    def _rejected(self, r, status):
        self.assertEqual(r["status"], status)
        self.assertIsNone(r["decision"])
        self.assertIs(r["execution_allowed"], False)
        self.assertIs(r["executed"], False)

    def test_invalid_implementation_request(self):
        chain, vres, policy, approval, avres = fx()
        for bad in (None, dict(chain[IMPL], version="1")):
            chain[IMPL] = bad
            self._rejected(make(chain=chain, vres=vres), "invalid_request")

    def test_invalid_prompt892_validation(self):
        chain = fx()[0]
        for bad in (None, {}, [], "valid", dict(derive(chain), valid=False),
                    dict(derive(chain), extra=1), derive([None] + chain[1:])):
            self._rejected(make(vres=bad), "invalid_request_validation")

    def test_broken_boundary_and_readiness_are_invalid_request_validation(self):
        for index in (BOUNDARY, R889, SPEC):
            chain = fx()[0]
            chain[index] = None
            self._rejected(make(chain=chain), "invalid_request_validation")

    def test_invalid_policies(self):
        policy = fx()[2]
        for bad in (None, {}, [], "eligible", dict(policy, eligible=False),
                    dict(policy, implementation_allowed=True), dict(policy, version="1"),
                    dict(policy, extra=1)):
            self._rejected(make(policy=bad), "invalid_policy")

    def test_ineligible_policy(self):
        chain, vres, _, _, _ = fx()
        with mock.patch.object(pmod, "SUPPORTED", ()):
            policy = build_policy(*chain, vres, "pol_001")
        self.assertEqual(policy["status"], "ineligible")
        self._rejected(make(policy=policy), "invalid_policy")

    def test_blocked_policy(self):
        chain, vres, _, _, _ = fx()
        policy = build_policy(*chain, vres, "pol_001", dict.fromkeys(FLAGS, True))
        self.assertEqual(policy["status"], "blocked")
        self._rejected(make(policy=policy), "invalid_policy")

    def test_unsupported_policy_and_improve_or_conflict(self):
        for tail in (base_chain()[3:], base_chain("improve")[3:], [None] * 13):
            chain = conflict_chain(tail)
            vres = derive(chain)
            policy = build_policy(*chain, vres, "pol_001")
            self.assertEqual(policy["status"], "unsupported")
            _, _, _, approval, avres = fx()
            self._rejected(make(chain=chain, vres=vres, policy=policy, approval=approval,
                                avres=avres), "unsupported_status")

    def test_invalid_approval_request(self):
        approval = fx()[3]
        for bad in (None, {}, [], "ready_for_approval", dict(approval, version="1"),
                    dict(approval, extra=1), dict(approval, policy_status="blocked")):
            self._rejected(make(approval=bad), "invalid_approval_request")

    def test_invalid_approval_request_validation(self):
        avres = fx()[4]
        for bad in (None, {}, [], "valid", dict(avres, valid=False),
                    dict(avres, errors=[{"code": "x", "where": "y"}]),
                    dict(avres, extra=1), dict(avres, execution_allowed=True),
                    dict(avres, executed=True)):
            self._rejected(make(avres=bad), "invalid_approval_request_validation")

    def test_nothing_supplied_never_raises(self):
        r = build()
        self.assertIsNone(r["decision"])
        self.assertIn(r["status"], STATUSES)


class ForgeryTests(unittest.TestCase):
    def _forged_approval(self, **over):
        approval = fx()[3]
        return make(approval=dict(approval, **over))

    def test_forged_approval_request_fields_are_context_mismatch(self):
        for key, value in (("request_id", "evo_999"), ("implementation_request_id", "ir_999"),
                           ("capability_name", "other_capability"), ("purpose", "Other."),
                           ("inputs", ["x"]), ("outputs", ["y"]), ("constraints", ["z"])):
            r = self._forged_approval(**{key: value})
            self.assertEqual(r["status"], "context_mismatch", key)
            self.assertIsNone(r["decision"])

    def test_forged_existing_capability_and_operation(self):
        for op, over in (("improve", {"existing_capability": None}),
                         ("create", {"operation": "improve"}),
                         ("improve", {"operation": "create"})):
            approval = fx(op)[3]
            r = make(op, approval=dict(approval, **over))
            self.assertIn(r["status"], ("context_mismatch", "invalid_approval_request"), over)
            self.assertIsNone(r["decision"])

    def test_forged_approval_request_flags(self):
        for flag in FLAGS + ("approval_required",):
            value = False if flag == "approval_required" else True
            r = self._forged_approval(**{flag: value})
            self.assertEqual(r["status"], "invalid_approval_request", flag)
            self.assertIsNone(r["decision"])

    def test_approval_status_mismatch(self):
        for status in ("blocked", "ineligible", "unsupported", "approved"):
            r = self._forged_approval(policy_status=status)
            self.assertEqual(r["status"], "invalid_approval_request", status)

    def test_approval_request_from_other_chain(self):
        other = fx("improve")[3]
        r = make("create", approval=other, avres=validate_approval(other))
        self.assertEqual(r["status"], "context_mismatch")
        self.assertIsNone(r["decision"])

    def test_forged_approval_request_validation(self):
        avres = fx()[4]
        for bad in (dict(avres, valid=False), dict(avres, errors=["x"]),
                    validate_approval(dict(fx()[3], version="1"))):
            r = make(avres=bad)
            self.assertEqual(r["status"], "invalid_approval_request_validation")

    def test_forged_policy(self):
        policy = fx()[2]
        for key, value in (("request_id", "evo_999"), ("implementation_request_id", "ir_999"),
                           ("capability_name", "other_capability"), ("operation", "improve")):
            r = make(policy=dict(policy, **{key: value}))
            self.assertEqual(r["status"], "context_mismatch", key)
            self.assertIsNone(r["decision"])

    def test_policy_from_other_chain(self):
        r = make("create", policy=fx("improve")[2])
        self.assertEqual(r["status"], "context_mismatch")

    def test_forged_prompt892_result_and_implementation_request(self):
        chain, vres = fx()[0], fx()[1]
        for key, value in (("plan_id", "plan_999"), ("request_id", "evo_999"),
                           ("capability_name", "other_one"), ("implementation_request_id", "ir_999")):
            self.assertEqual(make(vres=dict(vres, **{key: value}))["status"],
                             "context_mismatch", key)
        chain[IMPL] = dict(chain[IMPL], purpose="A different purpose.")
        self.assertEqual(make(chain=chain)["status"], "context_mismatch")

    def test_forged_boundary_and_readiness(self):
        for index in (BOUNDARY, R889):
            chain = fx()[0]
            chain[index] = dict(chain[index], plan_id="plan_999")
            self.assertEqual(make(chain=chain)["status"], "context_mismatch")


class IdTests(unittest.TestCase):
    def test_invalid_decision_ids(self):
        for bad in (None, "", " ", 1, True, [], {}, "x" * 65, "bad\nid"):
            r = make(did=bad)
            self.assertEqual(r["status"], "invalid_decision_id", repr(bad))
            self.assertIsNone(r["decision"])

    def test_valid_decision_ids_are_carried(self):
        for good in ("d", "dec_001", "x" * 64):
            self.assertEqual(make(did=good)["decision"]["decision_id"], good)

    def test_decision_id_is_never_generated(self):
        chain, vres, policy, approval, avres = fx()
        self.assertEqual(build(*chain, vres, policy, approval, avres)["status"],
                         "invalid_decision_id")

    def test_validator_rejects_invalid_ids(self):
        for key in ("decision_id", "request_id", "implementation_request_id",
                    "approval_request_id", "capability_name"):
            for bad in (None, "", 5, "x" * 65):
                self.assertFalse(validate(dict(ok(), **{key: bad}))["valid"], (key, bad))


class ValidatorSchemaTests(unittest.TestCase):
    def test_wrong_version_type(self):
        for bad in (True, "1", 1.0, 2, 0, None):
            report = validate(dict(ok(), version=bad))
            self.assertFalse(report["valid"], bad)
            self.assertIn("invalid_version", codes(report))

    def test_missing_key(self):
        for key in FIELDS:
            d = ok()
            del d[key]
            report = validate(d)
            self.assertFalse(report["valid"], key)
            self.assertIn("missing_key", codes(report))

    def test_extra_key(self):
        report = validate(dict(ok(), extra="x"))
        self.assertFalse(report["valid"])
        self.assertIn("unexpected_key", codes(report))

    def test_operation_must_be_create_or_improve(self):
        for bad in ("improve_or_conflict", "delete", "", None, 1, "Create"):
            self.assertFalse(validate(dict(ok(), operation=bad))["valid"], bad)

    def test_reason_is_fixed(self):
        for bad in ("pending_approval", "", None, 1, "approved"):
            self.assertIn("invalid_reason", codes(validate(dict(ok(), reason=bad))))

    def test_non_dict_decision(self):
        for bad in (None, [], "x", 1, ()):
            self.assertIn("decision_not_dict", codes(validate(bad)))
        self.assertFalse(validate()["valid"])

    def test_validator_report_is_fresh_and_never_grants(self):
        a, b = validate(ok()), validate(ok())
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIs(a["execution_allowed"], False)
        self.assertIs(a["executed"], False)


class DeterminismAndSafetyTests(unittest.TestCase):
    def test_repeated_build_is_identical(self):
        for op in ("create", "improve"):
            self.assertEqual(len({json.dumps(make(op)) for _ in range(5)}), 1)

    def test_fresh_objects_every_call(self):
        a, b = make(), make()
        self.assertEqual(a, b)
        self.assertIsNot(a["decision"], b["decision"])
        a["decision"]["approval_status"] = "approved"
        self.assertEqual(make()["decision"]["approval_status"], "pending_approval")

    def test_independent_of_time_and_randomness(self):
        with mock.patch("time.time", forbidden), mock.patch("random.random", forbidden):
            self.assertEqual(make()["status"], "pending_approval")

    def test_inputs_are_not_mutated(self):
        chain, vres, policy, approval, avres = fx()
        snapshot = copy.deepcopy((chain, vres, policy, approval, avres))
        build(*chain, vres, policy, approval, avres, "dec_001")
        self.assertEqual((chain, vres, policy, approval, avres), snapshot)

    def test_mutation_of_result_does_not_leak(self):
        r = make()
        r["decision"]["implementation_allowed"] = True
        self.assertFalse(validate(r["decision"])["valid"])
        self.assertIs(make()["decision"]["implementation_allowed"], False)

    def test_no_filesystem_network_or_process_activity(self):
        chain, vres, policy, approval, avres = fx()
        before = tree_fingerprint()
        with mock.patch("builtins.open", forbidden), \
                mock.patch.object(socket, "socket", forbidden), \
                mock.patch.object(socket, "create_connection", forbidden), \
                mock.patch.object(subprocess, "Popen", forbidden), \
                mock.patch.object(os, "system", forbidden), \
                mock.patch("builtins.exec", forbidden), \
                mock.patch("builtins.eval", forbidden), \
                mock.patch("builtins.compile", forbidden):
            r = build(*chain, vres, policy, approval, avres, "dec_001")
            self.assertEqual(r["status"], "pending_approval")
            self.assertTrue(validate(r["decision"])["valid"])
        self.assertEqual(before, tree_fingerprint())

    def test_never_raises_on_garbage(self):
        for value in (None, 1, "x", [], {}, object(), float("nan"), {"a": {"b": []}}):
            r = build(*([value] * 20), value)
            self.assertIsNone(r["decision"])
            self.assertIn(r["status"], STATUSES)
            self.assertFalse(validate(value)["valid"])

    def test_unexpected_internal_failure_is_validation_error(self):
        with mock.patch.object(dmod, "build_implementation_approval_request",
                               side_effect=RuntimeError("boom")):
            r = make()
        self.assertEqual(r["status"], "validation_error")
        self.assertIsNone(r["decision"])

    def test_built_decision_failing_validator_is_decision_error(self):
        bad = {"valid": False, "errors": [], "execution_allowed": False, "executed": False}
        with mock.patch.object(dmod, "validate_implementation_approval_decision",
                               return_value=bad):
            r = make()
        self.assertEqual(r["status"], "decision_error")
        self.assertIsNone(r["decision"])


class ForbiddenApiScanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(MODULE_PATH, "r", encoding="utf-8") as handle:
            cls.tree = ast.parse(handle.read())

    def test_imports_are_limited(self):
        for node in ast.walk(self.tree):
            self.assertNotIsInstance(node, ast.Import)
            if isinstance(node, ast.ImportFrom):
                if node.level == 0:
                    self.assertTrue(node.module.startswith("capabilities."), node.module)
                else:
                    self.assertIn(node.module, ("implementation_approval_request",
                                                "implementation_permission_policy"))

    def test_no_forbidden_calls_names_or_attributes(self):
        banned_calls = {"open", "exec", "eval", "compile", "__import__", "input", "print",
                        "system", "popen", "Popen", "run", "call", "urlopen", "setattr",
                        "delattr", "getattr", "globals", "locals", "vars"}
        banned_names = {"os", "sys", "subprocess", "socket", "http", "urllib", "requests",
                        "shutil", "pathlib", "time", "datetime", "random", "uuid", "secrets",
                        "importlib", "ctypes", "pickle", "anthropic", "openai", "memory",
                        "ael", "registry", "copy"}
        banned_attrs = {"write", "write_text", "write_bytes", "mkdir", "remove", "unlink",
                        "rename", "now", "utcnow", "urandom", "uuid4"}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else \
                    func.attr if isinstance(func, ast.Attribute) else None
                self.assertNotIn(name, banned_calls, name)
            if isinstance(node, ast.Name):
                self.assertNotIn(node.id, banned_names, node.id)
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, banned_attrs, node.attr)

    def test_no_classes_and_only_build_and_validate_entry_points(self):
        self.assertFalse([n for n in ast.walk(self.tree) if isinstance(n, ast.ClassDef)])
        public = [n.name for n in self.tree.body
                  if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]
        self.assertEqual(public, ["build_implementation_approval_decision",
                                  "validate_implementation_approval_decision"])

    def test_upstream_modules_do_not_reference_the_decision_module(self):
        paths = [os.path.join(ROOT, "autonomy", n) for n in
                 ("implementation_permission_policy.py", "implementation_approval_request.py")]
        paths += [os.path.join(ROOT, "capabilities", n + ".py") for n in
                  ("capability_implementation_request_validation",
                   "capability_implementation_boundary", "capability_implementation_request")]
        for path in paths:
            with open(path, "r", encoding="utf-8") as handle:
                self.assertNotIn("approval_decision", handle.read())

    def test_autonomy_package_contains_the_section17_modules(self):
        names = sorted(n for n in os.listdir(os.path.join(ROOT, "autonomy"))
                       if n != "__pycache__")
        for required in ("__init__.py", "implementation_permission_policy.py",
                         "implementation_approval_request.py",
                         "implementation_approval_decision.py"):
            self.assertIn(required, names)


class DocumentationTests(unittest.TestCase):
    def test_doc_exists_and_states_the_invariants(self):
        self.assertTrue(os.path.isfile(DOC))
        with open(DOC, "r", encoding="utf-8") as handle:
            text = handle.read()
        for needle in ("pending_approval", "approval_required", "implementation_allowed",
                       "execution_allowed", "implementation_started", "executed",
                       "improve_or_conflict", "eligib", "approval request",
                       "Prompt 896 creates an approval-decision state, not an approval mechanism."):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
