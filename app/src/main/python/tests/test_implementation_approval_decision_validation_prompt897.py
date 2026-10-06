"""
Prompt 897 - Section 17 (Controlled Autonomy): approval decision validation boundary.

Deterministic, read-only tests of autonomy/implementation_approval_decision_validation.py. The
validator checks that a "pending_approval" decision is structurally valid and consistent with
the complete trusted chain. It never approves anything: "valid" is not approval, not
implementation permission and not execution permission.

Run (from app/src/main/python/):
    python -m unittest tests.test_implementation_approval_decision_validation_prompt897 -v
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

from autonomy import implementation_approval_decision_validation as vmod
from autonomy import implementation_permission_policy as pmod
from autonomy.implementation_approval_decision import (
    build_implementation_approval_decision as build_decision)
from autonomy.implementation_approval_decision_validation import (
    RESULT_KEYS, STATUSES, validate_implementation_approval_decision_context as check,
    validate_implementation_approval_decision_validation_result as validate_result)
from autonomy.implementation_approval_request import (
    validate_implementation_approval_request as validate_approval)
from autonomy.implementation_permission_policy import (
    build_implementation_permission_policy as build_policy)
from tests.test_implementation_approval_decision_prompt896 import fx as fx896
from tests.test_implementation_permission_policy_prompt894 import (
    BOUNDARY, IMPL, R889, SPEC, base_chain, conflict_chain, derive)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(ROOT, "autonomy", "implementation_approval_decision_validation.py")
DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(ROOT)))),
                   "docs", "implementation_approval_decision_validation_prompt897.md")
FLAGS = ("implementation_allowed", "execution_allowed", "implementation_started", "executed")
IDS = ("decision_id", "request_id", "implementation_request_id", "approval_request_id",
       "capability_name", "operation")

_CACHE = {}


def fx(op="create"):
    """(chain, 892 result, 894 policy, 895 request, 895 validation, 896 decision)."""
    if op not in _CACHE:
        chain, vres, policy, approval, avres = fx896(op)
        decision = build_decision(*chain, vres, policy, approval, avres, "dec_001")["decision"]
        _CACHE[op] = (chain, vres, policy, approval, avres, decision)
    return copy.deepcopy(_CACHE[op])


def make(op="create", **over):
    chain, vres, policy, approval, avres, decision = fx(op)
    chain = over.pop("chain", chain)
    vres = over.pop("vres", vres)
    policy = over.pop("policy", policy)
    approval = over.pop("approval", approval)
    avres = over.pop("avres", avres)
    decision = over.pop("decision", decision)
    return check(*chain, vres, policy, approval, avres, decision)


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
    def test_valid_create_chain(self):
        r = make("create")
        self.assertEqual(r["status"], "valid")
        self.assertIs(r["valid"], True)
        self.assertEqual(r["operation"], "create")

    def test_valid_improve_chain(self):
        r = make("improve")
        self.assertEqual(r["status"], "valid")
        self.assertIs(r["valid"], True)
        self.assertEqual(r["operation"], "improve")

    def test_exact_twelve_keys_in_order(self):
        self.assertEqual(len(RESULT_KEYS), 12)
        for op in ("create", "improve"):
            self.assertEqual(list(make(op)), list(RESULT_KEYS))

    def test_version_is_integer_one(self):
        self.assertIs(type(make()["version"]), int)
        self.assertEqual(make()["version"], 1)

    def test_identity_comes_from_trusted_chain(self):
        r = make()
        self.assertEqual(r["decision_id"], "dec_001")
        self.assertEqual(r["request_id"], "evo_001")
        self.assertEqual(r["implementation_request_id"], "ir_001")
        self.assertEqual(r["approval_request_id"], "apr_001")
        self.assertEqual(r["capability_name"], "text_summarizer")
        self.assertEqual(r["reason"], "valid")

    def test_execution_flags_always_false(self):
        for op in ("create", "improve"):
            r = make(op)
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)

    def test_valid_result_validates(self):
        for op in ("create", "improve"):
            report = validate_result(make(op))
            self.assertTrue(report["valid"], report)
            self.assertIs(report["execution_allowed"], False)
            self.assertIs(report["executed"], False)

    def test_status_vocabulary_is_exactly_the_documented_eight(self):
        self.assertEqual(set(STATUSES), {
            "valid", "invalid_decision", "invalid_decision_id", "invalid_request_validation",
            "invalid_approval_request_validation", "context_mismatch", "unsupported_status",
            "validation_error"})
        self.assertEqual(len(STATUSES), 8)

    def test_decision_id_is_caller_supplied_and_carried(self):
        chain, vres, policy, approval, avres, _ = fx()
        for did in ("d", "dec_other", "x" * 64):
            decision = build_decision(*chain, vres, policy, approval, avres, did)["decision"]
            r = check(*chain, vres, policy, approval, avres, decision)
            self.assertEqual(r["status"], "valid", did)
            self.assertEqual(r["decision_id"], did)


class NoApprovalTests(unittest.TestCase):
    def test_valid_is_not_approval(self):
        for op in ("create", "improve"):
            r = make(op)
            self.assertEqual(r["status"], "valid")
            self.assertNotEqual(r["status"], "approved")
            self.assertNotIn("approval_status", r)
            self.assertNotIn("approved", r)

    def test_vocabulary_has_no_approval_or_permission_status(self):
        for status in STATUSES:
            for word in ("approved", "allowed", "granted", "authorized", "started", "executed"):
                self.assertNotIn(word, status)

    def test_pending_approval_is_never_converted(self):
        decision = fx()[5]
        before = copy.deepcopy(decision)
        r = make(decision=decision)
        self.assertEqual(r["status"], "valid")
        self.assertEqual(decision, before)
        self.assertEqual(decision["approval_status"], "pending_approval")
        self.assertIs(decision["implementation_allowed"], False)
        self.assertIs(decision["execution_allowed"], False)

    def test_non_pending_statuses_are_rejected(self):
        decision = fx()[5]
        for bad in ("approved", "implementation_allowed", "execution_allowed", "granted",
                    "ready_for_approval", "rejected", "", None, 1, "PENDING_APPROVAL"):
            r = make(decision=dict(decision, approval_status=bad))
            self.assertEqual(r["status"], "invalid_decision", bad)
            self.assertFalse(r["valid"])


class DecisionShapeTests(unittest.TestCase):
    def _rejected(self, r, status):
        self.assertEqual(r["status"], status)
        self.assertIs(r["valid"], False)
        for key in IDS:
            self.assertIsNone(r[key])
        self.assertIs(r["execution_allowed"], False)
        self.assertIs(r["executed"], False)

    def test_malformed_decisions(self):
        decision = fx()[5]
        for bad in (None, {}, [], "pending_approval", 1, dict(decision, extra=1),
                    dict(decision, version="1"), dict(decision, version=True),
                    dict(decision, reason="other")):
            self._rejected(make(decision=bad), "invalid_decision")

    def test_missing_key(self):
        decision = fx()[5]
        for key in decision:
            bad = dict(decision)
            del bad[key]
            self._rejected(make(decision=bad), "invalid_decision")

    def test_invalid_decision_ids(self):
        decision = fx()[5]
        for bad in (None, "", " ", 1, True, [], "x" * 65, "bad\nid"):
            self._rejected(make(decision=dict(decision, decision_id=bad)),
                           "invalid_decision_id")

    def test_altered_approval_flags(self):
        decision = fx()[5]
        for bad in (False, 0, None, "True", 1):
            self._rejected(make(decision=dict(decision, approval_required=bad)),
                           "invalid_decision")

    def test_altered_implementation_and_execution_flags(self):
        decision = fx()[5]
        for flag in FLAGS:
            for bad in (True, 0, 1, None, "False"):
                self._rejected(make(decision=dict(decision, **{flag: bad})),
                               "invalid_decision")

    def test_decision_shape_is_checked_before_the_chain(self):
        chain = fx()[0]
        chain[SPEC] = None
        self._rejected(make(chain=chain, decision=None), "invalid_decision")


class ForgedDecisionTests(unittest.TestCase):
    def test_mismatched_identifiers_and_names(self):
        decision = fx()[5]
        for key, value in (("request_id", "evo_999"), ("implementation_request_id", "ir_999"),
                           ("approval_request_id", "apr_999"),
                           ("capability_name", "other_capability")):
            r = make(decision=dict(decision, **{key: value}))
            self.assertEqual(r["status"], "context_mismatch", key)
            self.assertFalse(r["valid"])

    def test_mismatched_operation(self):
        for op, other in (("create", "improve"), ("improve", "create")):
            r = make(op, decision=dict(fx(op)[5], operation=other))
            self.assertEqual(r["status"], "context_mismatch", op)

    def test_decision_of_other_chain(self):
        r = make("create", decision=fx("improve")[5])
        self.assertEqual(r["status"], "context_mismatch")
        r = make("improve", decision=fx("create")[5])
        self.assertEqual(r["status"], "context_mismatch")

    def test_forged_decision_never_valid(self):
        decision = fx()[5]
        for key in ("request_id", "implementation_request_id", "approval_request_id",
                    "capability_name", "operation"):
            forged = dict(decision, **{key: "evo_999" if key != "operation" else "improve"})
            self.assertFalse(make(decision=forged)["valid"], key)

    def test_rejected_results_carry_no_forged_identity(self):
        r = make(decision=dict(fx()[5], request_id="evo_999"))
        for key in IDS:
            self.assertIsNone(r[key])


class UpstreamTests(unittest.TestCase):
    def test_invalid_prompt892_validation_results(self):
        chain, vres = fx()[0], fx()[1]
        for bad in (None, {}, [], "valid", dict(vres, valid=False), dict(vres, extra=1),
                    derive([None] + chain[1:])):
            self.assertEqual(make(vres=bad)["status"], "invalid_request_validation")

    def test_forged_prompt892_validation_result(self):
        vres = fx()[1]
        for key, value in (("plan_id", "plan_999"), ("contract_id", "ct_999"),
                           ("request_id", "evo_999"), ("capability_name", "other_one"),
                           ("implementation_request_id", "ir_999")):
            self.assertEqual(make(vres=dict(vres, **{key: value}))["status"],
                             "context_mismatch", key)

    def test_broken_chain_objects(self):
        for index in (IMPL, SPEC, BOUNDARY, R889):
            chain = fx()[0]
            chain[index] = None
            self.assertEqual(make(chain=chain)["status"], "invalid_request_validation", index)

    def test_forged_chain_objects_are_context_mismatch(self):
        chain = fx()[0]
        chain[IMPL] = dict(chain[IMPL], purpose="A different purpose.")
        self.assertEqual(make(chain=chain)["status"], "context_mismatch")
        for index in (BOUNDARY, R889):
            chain = fx()[0]
            chain[index] = dict(chain[index], plan_id="plan_999")
            self.assertEqual(make(chain=chain)["status"], "context_mismatch")

    def test_improve_or_conflict_is_unsupported(self):
        decision = fx()[5]
        for tail in (base_chain()[3:], base_chain("improve")[3:], [None] * 13):
            chain = conflict_chain(tail)
            r = make(chain=chain, vres=derive(chain), decision=decision)
            self.assertEqual(r["status"], "unsupported_status")
            self.assertFalse(r["valid"])

    def test_invalid_policies(self):
        policy = fx()[2]
        for bad in (None, {}, [], "eligible", dict(policy, eligible=False),
                    dict(policy, implementation_allowed=True), dict(policy, extra=1)):
            self.assertEqual(make(policy=bad)["status"], "invalid_request_validation")

    def test_ineligible_blocked_and_unsupported_policies_are_unsupported_status(self):
        chain, vres = fx()[0], fx()[1]
        with mock.patch.object(pmod, "SUPPORTED", ()):
            ineligible = build_policy(*chain, vres, "pol_001")
        blocked = build_policy(*chain, vres, "pol_001", dict.fromkeys(FLAGS, True))
        conflict = conflict_chain(base_chain()[3:])
        unsupported = build_policy(*conflict, derive(conflict), "pol_001")
        for policy, status in ((ineligible, "ineligible"), (blocked, "blocked"),
                               (unsupported, "unsupported")):
            self.assertEqual(policy["status"], status)
            self.assertEqual(make(policy=policy)["status"], "unsupported_status", status)

    def test_forged_policy(self):
        policy = fx()[2]
        for key, value in (("request_id", "evo_999"), ("implementation_request_id", "ir_999"),
                           ("capability_name", "other_capability"), ("operation", "improve")):
            self.assertEqual(make(policy=dict(policy, **{key: value}))["status"],
                             "context_mismatch", key)
        self.assertEqual(make("create", policy=fx("improve")[2])["status"], "context_mismatch")


class ApprovalRequestTests(unittest.TestCase):
    def test_invalid_approval_requests(self):
        approval = fx()[3]
        for bad in (None, {}, [], dict(approval, version="1"), dict(approval, extra=1),
                    dict(approval, policy_status="blocked"),
                    dict(approval, approval_required=False),
                    dict(approval, implementation_allowed=True)):
            self.assertEqual(make(approval=bad)["status"],
                             "invalid_approval_request_validation")

    def test_invalid_prompt895_validation_results(self):
        avres = fx()[4]
        for bad in (None, {}, [], "valid", dict(avres, valid=False),
                    dict(avres, errors=[{"code": "x", "where": "y"}]), dict(avres, extra=1),
                    dict(avres, execution_allowed=True), dict(avres, executed=True),
                    validate_approval(dict(fx()[3], version="1"))):
            r = make(avres=bad)
            self.assertEqual(r["status"], "invalid_approval_request_validation")
            self.assertFalse(r["valid"])

    def test_forged_approval_request_fields(self):
        approval = fx()[3]
        for key, value in (("request_id", "evo_999"), ("implementation_request_id", "ir_999"),
                           ("capability_name", "other_capability"), ("purpose", "Other."),
                           ("inputs", ["x"]), ("outputs", ["y"]), ("constraints", ["z"])):
            self.assertEqual(make(approval=dict(approval, **{key: value}))["status"],
                             "context_mismatch", key)

    def test_approval_request_of_other_chain(self):
        other = fx("improve")
        r = make("create", approval=other[3], avres=other[4])
        self.assertEqual(r["status"], "context_mismatch")

    def test_decision_from_invalid_approval_validation_cannot_be_valid(self):
        bad = dict(fx()[4], valid=False)
        self.assertFalse(make(avres=bad)["valid"])


class ResultValidatorTests(unittest.TestCase):
    def test_wrong_version_type(self):
        for bad in (True, "1", 1.0, 2, None):
            report = validate_result(dict(make(), version=bad))
            self.assertFalse(report["valid"], bad)
            self.assertIn("invalid_version", codes(report))

    def test_missing_and_extra_keys(self):
        for key in RESULT_KEYS:
            r = make()
            del r[key]
            self.assertIn("missing_key", codes(validate_result(r)))
        self.assertIn("unexpected_key", codes(validate_result(dict(make(), approved=False))))

    def test_status_valid_and_reason_must_agree(self):
        r = make()
        self.assertIn("invalid_status", codes(validate_result(dict(r, status="approved"))))
        self.assertIn("invalid_valid", codes(validate_result(dict(r, valid=False))))
        self.assertIn("invalid_reason", codes(validate_result(dict(r, reason="other"))))
        rejected = make(decision=None)
        self.assertIn("invalid_valid", codes(validate_result(dict(rejected, valid=True))))

    def test_execution_flags_must_be_false(self):
        for flag in ("execution_allowed", "executed"):
            for bad in (True, 0, None):
                self.assertFalse(validate_result(dict(make(), **{flag: bad}))["valid"])

    def test_identity_rules(self):
        r = make()
        for key in IDS:
            self.assertIn("invalid_identity", codes(validate_result(dict(r, **{key: None}))))
        self.assertIn("invalid_identity",
                      codes(validate_result(dict(r, operation="improve_or_conflict"))))
        rejected = make(decision=None)
        self.assertTrue(validate_result(rejected)["valid"])
        self.assertIn("invalid_identity",
                      codes(validate_result(dict(rejected, request_id="evo_001"))))

    def test_every_status_result_validates(self):
        decision = fx()[5]
        results = [make(), make(decision=None), make(decision=dict(decision, decision_id="")),
                   make(vres=None), make(avres=None), make(policy=None),
                   make(decision=dict(decision, request_id="evo_999"))]
        conflict = conflict_chain(base_chain()[3:])
        results.append(make(chain=conflict, vres=derive(conflict)))
        seen = {r["status"] for r in results}
        self.assertEqual(seen, {"valid", "invalid_decision", "invalid_decision_id",
                                "invalid_request_validation",
                                "invalid_approval_request_validation", "context_mismatch",
                                "unsupported_status"})
        for r in results:
            self.assertTrue(validate_result(r)["valid"], (r["status"], validate_result(r)))

    def test_non_dict_result(self):
        for bad in (None, [], "x", 1, ()):
            self.assertIn("result_not_dict", codes(validate_result(bad)))
        self.assertFalse(validate_result()["valid"])


class DeterminismAndSafetyTests(unittest.TestCase):
    def test_repeated_validation_is_identical(self):
        for op in ("create", "improve"):
            self.assertEqual(len({json.dumps(make(op)) for _ in range(5)}), 1)

    def test_fresh_result_every_call(self):
        a, b = make(), make()
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        a["status"] = "tampered"
        self.assertEqual(make()["status"], "valid")

    def test_independent_of_time_and_randomness(self):
        with mock.patch("time.time", forbidden), mock.patch("random.random", forbidden):
            self.assertEqual(make()["status"], "valid")

    def test_inputs_are_not_mutated(self):
        chain, vres, policy, approval, avres, decision = fx()
        snapshot = copy.deepcopy((chain, vres, policy, approval, avres, decision))
        check(*chain, vres, policy, approval, avres, decision)
        self.assertEqual((chain, vres, policy, approval, avres, decision), snapshot)

    def test_mutation_attempt_on_result_does_not_leak(self):
        r = make()
        r["executed"] = True
        self.assertFalse(validate_result(r)["valid"])
        self.assertIs(make()["executed"], False)

    def test_no_filesystem_network_or_process_activity(self):
        chain, vres, policy, approval, avres, decision = fx()
        before = tree_fingerprint()
        with mock.patch("builtins.open", forbidden), \
                mock.patch.object(socket, "socket", forbidden), \
                mock.patch.object(socket, "create_connection", forbidden), \
                mock.patch.object(subprocess, "Popen", forbidden), \
                mock.patch.object(os, "system", forbidden), \
                mock.patch("builtins.exec", forbidden), \
                mock.patch("builtins.eval", forbidden), \
                mock.patch("builtins.compile", forbidden):
            r = check(*chain, vres, policy, approval, avres, decision)
            self.assertEqual(r["status"], "valid")
            self.assertTrue(validate_result(r)["valid"])
        self.assertEqual(before, tree_fingerprint())

    def test_never_raises_on_garbage(self):
        for value in (None, 1, "x", [], {}, object(), float("nan"), {"a": {"b": []}}):
            r = check(*([value] * 21))
            self.assertIs(r["valid"], False)
            self.assertIn(r["status"], STATUSES)
            self.assertTrue(validate_result(r)["valid"])
        self.assertEqual(check()["status"], "invalid_decision")

    def test_unexpected_internal_failure_is_validation_error(self):
        with mock.patch.object(vmod, "build_implementation_approval_decision",
                               side_effect=RuntimeError("boom")):
            r = make()
        self.assertEqual(r["status"], "validation_error")
        self.assertFalse(r["valid"])
        self.assertTrue(validate_result(r)["valid"])


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
                    self.assertIn(node.module, ("implementation_approval_decision",
                                                "implementation_approval_request",
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

    def test_no_classes_and_only_two_entry_points(self):
        self.assertFalse([n for n in ast.walk(self.tree) if isinstance(n, ast.ClassDef)])
        public = [n.name for n in self.tree.body
                  if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]
        self.assertEqual(public, ["validate_implementation_approval_decision_context",
                                  "validate_implementation_approval_decision_validation_result"])

    def test_upstream_modules_do_not_reference_this_module(self):
        paths = [os.path.join(ROOT, "autonomy", n) for n in
                 ("implementation_permission_policy.py", "implementation_approval_request.py",
                  "implementation_approval_decision.py")]
        paths += [os.path.join(ROOT, "capabilities", n + ".py") for n in
                  ("capability_implementation_request_validation",
                   "capability_implementation_boundary", "capability_implementation_request")]
        for path in paths:
            with open(path, "r", encoding="utf-8") as handle:
                self.assertNotIn("approval_decision_validation", handle.read())

    def test_autonomy_package_contains_the_section17_modules(self):
        names = sorted(n for n in os.listdir(os.path.join(ROOT, "autonomy"))
                       if n != "__pycache__")
        for required in ("__init__.py", "implementation_permission_policy.py",
                         "implementation_approval_request.py",
                         "implementation_approval_decision.py",
                         "implementation_approval_decision_validation.py"):
            self.assertIn(required, names)


class DocumentationTests(unittest.TestCase):
    def test_doc_exists_and_states_the_invariants(self):
        self.assertTrue(os.path.isfile(DOC))
        with open(DOC, "r", encoding="utf-8") as handle:
            text = handle.read()
        for needle in ("pending_approval", "approval_required", "implementation_allowed",
                       "execution_allowed", "implementation_started", "executed",
                       "improve_or_conflict", "context_mismatch", "unsupported_status",
                       "invalid_decision_id", "validation_error"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
