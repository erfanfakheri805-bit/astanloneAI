"""
Prompt 900 - Section 17 (Controlled Autonomy): approval scope context validation.

Deterministic, read-only tests of autonomy/approval_scope_context_validation.py. The module only
VALIDATES that the Prompt 899 approval authority scope is consistent with the Prompt 895
approval request and the Prompt 896 / 897 approval-decision chain. "valid" is not approval, not
authorization, not implementation permission and not execution permission.

Run (from app/src/main/python/):
    python -m unittest tests.test_approval_scope_context_validation_prompt900 -v
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

from autonomy import approval_scope_context_validation as mod
from autonomy.approval_authority_scope import build_approval_authority_scope as build_scope
from autonomy.approval_authority_source import build_approval_authority_source as build_authority
from autonomy.approval_scope_context_validation import (
    RESULT_KEYS, STATUSES, validate_approval_scope_context as check,
    validate_approval_scope_context_result as validate_result)
from tests.test_implementation_approval_decision_validation_prompt897 import (
    check as check897, fx as fx897)
from tests.test_implementation_permission_policy_prompt894 import (
    base_chain, conflict_chain, derive)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(ROOT, "autonomy", "approval_scope_context_validation.py")
DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(ROOT)))),
                   "docs", "approval_scope_context_validation_prompt900.md")
IDENTITY = ("authority_id", "scope_id", "capability_name", "operation", "request_id",
            "implementation_request_id", "approval_request_id", "decision_id")
FALSE_FLAGS = ("implementation_allowed", "execution_allowed", "executed")
AUTHORITY_TYPES = ("user", "system_policy", "trusted_internal_controller")

_CACHE = {}


def authority(authority_type="user", **over):
    params = {"authority_id": "auth_001", "authority_type": authority_type,
              "scope": "controlled_implementation", "purpose": "implementation_approval",
              "trusted": True, "approval_capable": True}
    params.update(over)
    return build_authority(**params)["descriptor"]


def scope_for(auth, op="create", **over):
    params = {"scope_id": "scope_001", "capability_name": "text_summarizer", "operation": op,
              "scope": "capability_boundary", "purpose": "implementation_approval"}
    params.update(over)
    return build_scope(auth, **params)["scope_descriptor"]


def fx(op="create"):
    """(authority, scope, chain, 892 result, policy, request, 895 result, decision, 897 result)."""
    if op not in _CACHE:
        chain, vres, policy, approval, avres, decision = fx897(op)
        dres = check897(*chain, vres, policy, approval, avres, decision)
        auth = authority()
        _CACHE[op] = (auth, scope_for(auth, op), chain, vres, policy, approval, avres,
                      decision, dres)
    return copy.deepcopy(_CACHE[op])


def run(op="create", **over):
    """Validate a (possibly altered) context. An override may be a value or f(context)->value."""
    auth, scope, chain, vres, policy, approval, avres, decision, dres = fx(op)
    ctx = {"auth": auth, "scope": scope, "chain": chain, "vres": vres, "policy": policy,
           "approval": approval, "avres": avres, "decision": decision, "dres": dres}
    for key, value in over.items():
        ctx[key] = value(ctx) if callable(value) else value
    return check(ctx["auth"], ctx["scope"], *ctx["chain"], ctx["vres"], ctx["policy"],
                 ctx["approval"], ctx["avres"], ctx["decision"], ctx["dres"])


def chain_edit(index, **fields):
    def edit(ctx):
        chain = list(ctx["chain"])
        chain[index] = dict(chain[index], **fields)
        return chain
    return edit


def change(key, **fields):
    return lambda ctx: dict(ctx[key], **fields)


def forbidden(*_a, **_k):
    raise AssertionError("forbidden operation attempted")


class ValidPathTests(unittest.TestCase):
    def test_valid_create_chain(self):
        r = run("create")
        self.assertEqual(r["status"], "valid")
        self.assertIs(r["valid"], True)
        self.assertEqual(r["operation"], "create")

    def test_valid_improve_chain(self):
        r = run("improve")
        self.assertEqual(r["status"], "valid")
        self.assertIs(r["valid"], True)
        self.assertEqual(r["operation"], "improve")

    def test_valid_for_every_authority_type(self):
        chain, vres, policy, approval, avres, decision = fx897("create")
        dres = check897(*chain, vres, policy, approval, avres, decision)
        for authority_type in AUTHORITY_TYPES:
            auth = authority(authority_type)
            r = check(auth, scope_for(auth), *chain, vres, policy, approval, avres, decision,
                      dres)
            self.assertEqual(r["status"], "valid", authority_type)
            self.assertEqual(r["authority_id"], "auth_001")

    def test_exact_fifteen_keys_in_order_and_integer_version(self):
        self.assertEqual(len(RESULT_KEYS), 15)
        for op in ("create", "improve"):
            self.assertEqual(list(run(op)), list(RESULT_KEYS))
        self.assertIs(type(run()["version"]), int)
        self.assertEqual(run()["version"], 1)

    def test_identity_comes_from_the_trusted_objects(self):
        r = run()
        self.assertEqual({k: r[k] for k in IDENTITY}, {
            "authority_id": "auth_001", "scope_id": "scope_001",
            "capability_name": "text_summarizer", "operation": "create",
            "request_id": "evo_001", "implementation_request_id": "ir_001",
            "approval_request_id": "apr_001", "decision_id": "dec_001"})
        self.assertEqual(r["reason"], "valid")

    def test_permission_flags_false_for_every_valid_result(self):
        for op in ("create", "improve"):
            r = run(op)
            for key in FALSE_FLAGS:
                self.assertIs(r[key], False, key)

    def test_scope_is_not_a_grant_approval_capable_or_not(self):
        auth, scope = fx()[0], fx()[1]
        self.assertIs(auth["approval_capable"], True)
        self.assertIs(scope["approval_capable"], True)
        self.assertIs(scope["implementation_allowed"], False)
        self.assertIs(scope["execution_allowed"], False)
        r = run()
        self.assertEqual(r["status"], "valid")
        self.assertIs(r["implementation_allowed"], False)
        self.assertIs(r["execution_allowed"], False)
        chain, vres, policy, approval, avres, decision = fx897("create")
        dres = check897(*chain, vres, policy, approval, avres, decision)
        auth = authority(approval_capable=False)
        scope = scope_for(auth)
        self.assertIs(scope["approval_capable"], False)
        r = check(auth, scope, *chain, vres, policy, approval, avres, decision, dres)
        self.assertEqual(r["status"], "valid")
        self.assertIs(r["implementation_allowed"], False)

    def test_status_vocabulary_is_exactly_the_documented_ten(self):
        self.assertEqual(set(STATUSES), {
            "valid", "invalid_authority", "invalid_scope", "invalid_approval_request",
            "invalid_approval_decision", "invalid_decision_validation", "invalid_context",
            "context_mismatch", "unsupported_status", "validation_error"})
        self.assertEqual(len(STATUSES), 10)
        for status in STATUSES:
            for word in ("approved", "authorized", "authorization", "granted", "allowed",
                         "permitted", "executed", "ready"):
                self.assertNotIn(word, status)

    def test_valid_result_validates(self):
        for op in ("create", "improve"):
            report = validate_result(run(op))
            self.assertTrue(report["valid"], report)
            self.assertIs(report["execution_allowed"], False)
            self.assertIs(report["executed"], False)


class RejectedObjectTests(unittest.TestCase):
    def test_malformed_authority(self):
        for bad in (None, {}, [], "user", 7, authority_without("trusted")):
            self.assertEqual(run(auth=bad)["status"], "invalid_authority", bad)
        for key in ("implementation_allowed", "execution_allowed"):
            bad = dict(fx()[0], **{key: True})
            self.assertEqual(run(auth=bad)["status"], "invalid_authority", key)

    def test_authority_naming_an_approval_concept_is_unsupported(self):
        for key in ("approved", "authorization", "granted", "status"):
            bad = dict(fx()[0], **{key: True})
            self.assertEqual(run(auth=bad)["status"], "unsupported_status", key)
        self.assertEqual(run(auth=dict(fx()[0], authority_type="approved"))["status"],
                         "unsupported_status")

    def test_malformed_scope(self):
        for bad in (None, {}, [], "scope", 7):
            self.assertEqual(run(scope=bad)["status"], "invalid_scope", bad)
        scope = fx()[1]
        for key in tuple(scope):
            self.assertEqual(run(scope=lambda c, k=key: without(c["scope"], k))["status"],
                             "invalid_scope", key)

    def test_scope_with_invalid_labels_is_invalid(self):
        for key in ("scope_id", "capability_name", "operation", "scope", "purpose"):
            for bad in ("http://x", "has space", "", None, 3):
                r = run(scope=change("scope", **{key: bad}))
                self.assertEqual(r["status"], "invalid_scope", (key, bad))

    def test_scope_altered_permission_flags_are_invalid(self):
        for key in ("implementation_allowed", "execution_allowed"):
            for value in (True, 1, "False", None):
                r = run(scope=change("scope", **{key: value}))
                self.assertEqual(r["status"], "invalid_scope", (key, value))

    def test_scope_unexpected_fields_and_approval_concepts(self):
        r = run(scope=change("scope", extra="x"))
        self.assertEqual(r["status"], "invalid_scope")
        for key in ("approved", "authorization", "granted", "approval_status"):
            r = run(scope=change("scope", **{key: True}))
            self.assertEqual(r["status"], "unsupported_status", key)

    def test_scope_improve_or_conflict_is_unsupported(self):
        r = run(scope=change("scope", operation="improve_or_conflict"))
        self.assertEqual(r["status"], "unsupported_status")
        for word in ("approved", "authorization"):
            self.assertEqual(run(scope=change("scope", operation=word))["status"],
                             "unsupported_status", word)

    def test_malformed_approval_request(self):
        for bad in (None, {}, [], "request", 7):
            self.assertEqual(run(approval=bad)["status"], "invalid_approval_request", bad)
        for key in tuple(fx()[5]):
            r = run(approval=lambda c, k=key: without(c["approval"], k))
            self.assertEqual(r["status"], "invalid_approval_request", key)

    def test_approval_request_altered_flags_and_policy_status(self):
        for key, value in (("implementation_allowed", True), ("execution_allowed", True),
                           ("implementation_started", True), ("executed", True),
                           ("approval_required", False), ("policy_status", "blocked")):
            r = run(approval=change("approval", **{key: value}))
            self.assertEqual(r["status"], "invalid_approval_request", key)
        self.assertEqual(run(approval=change("approval", extra=1))["status"],
                         "invalid_approval_request")
        for key in ("approved", "authorization"):
            self.assertEqual(run(approval=change("approval", **{key: True}))["status"],
                             "unsupported_status", key)

    def test_malformed_approval_decision(self):
        for bad in (None, {}, [], "decision", 7):
            self.assertEqual(run(decision=bad)["status"], "invalid_approval_decision", bad)
        for key in tuple(fx()[7]):
            r = run(decision=lambda c, k=key: without(c["decision"], k))
            self.assertEqual(r["status"], "invalid_approval_decision", key)

    def test_non_pending_approval_status_is_rejected_as_a_mismatch(self):
        for value in ("rejected", "", None, 7, "Pending_Approval", "pending"):
            r = run(decision=change("decision", approval_status=value))
            self.assertEqual(r["status"], "invalid_approval_decision", value)
            self.assertIs(r["valid"], False)

    def test_approved_and_authorization_attempts_are_unsupported(self):
        for value in ("approved", "authorized", "authorization", "granted", "allowed"):
            r = run(decision=change("decision", approval_status=value))
            self.assertEqual(r["status"], "unsupported_status", value)
            self.assertIs(r["valid"], False)
        for key in ("approved", "authorization", "approved_by", "granted"):
            r = run(decision=change("decision", **{key: True}))
            self.assertEqual(r["status"], "unsupported_status", key)

    def test_decision_altered_flags_and_reason(self):
        for key, value in (("implementation_allowed", True), ("execution_allowed", True),
                           ("implementation_started", True), ("executed", True),
                           ("approval_required", False), ("reason", "approved")):
            r = run(decision=change("decision", **{key: value}))
            self.assertEqual(r["status"], "invalid_approval_decision", key)
        self.assertEqual(run(decision=change("decision", extra=1))["status"],
                         "invalid_approval_decision")
        r = run(decision=change("decision", operation="improve_or_conflict"))
        self.assertEqual(r["status"], "unsupported_status")

    def test_invalid_prompt897_result(self):
        for bad in (None, {}, [], "valid", 7):
            self.assertEqual(run(dres=bad)["status"], "invalid_decision_validation", bad)
        for key in tuple(fx()[8]):
            r = run(dres=lambda c, k=key: without(c["dres"], k))
            self.assertEqual(r["status"], "invalid_decision_validation", key)
        r = run(dres=change("dres", extra=1))
        self.assertEqual(r["status"], "invalid_decision_validation")

    def test_prompt897_result_that_is_not_valid_is_rejected(self):
        chain, vres, policy, approval, avres, decision = fx897("create")
        bad = check897(*chain, vres, policy, approval, avres,
                       dict(decision, approval_status="rejected"))
        self.assertEqual(bad["status"], "invalid_decision")
        self.assertEqual(run(dres=bad)["status"], "invalid_decision_validation")

    def test_prompt897_result_altered_flags_and_approved_status(self):
        for key in ("execution_allowed", "executed"):
            r = run(dres=change("dres", **{key: True}))
            self.assertEqual(r["status"], "invalid_decision_validation", key)
        r = run(dres=change("dres", valid=False))
        self.assertEqual(r["status"], "invalid_decision_validation")
        self.assertEqual(run(dres=change("dres", status="approved"))["status"],
                         "unsupported_status")
        self.assertEqual(run(dres=change("dres", approved=True))["status"],
                         "unsupported_status")


def without(mapping, key):
    value = dict(mapping)
    del value[key]
    return value


def authority_without(key):
    return without(authority(), key)


class MismatchTests(unittest.TestCase):
    def test_authority_id_mismatch(self):
        r = run(scope=change("scope", authority_id="other_auth"))
        self.assertEqual(r["status"], "context_mismatch")

    def test_authority_approval_capable_mismatch(self):
        r = run(scope=change("scope", approval_capable=False))
        self.assertEqual(r["status"], "context_mismatch")

    def test_scope_id_must_be_a_valid_label_and_is_copied_exactly(self):
        for bad in ("http://x", "", None, "Scope One"):
            self.assertEqual(run(scope=change("scope", scope_id=bad))["status"],
                             "invalid_scope", bad)
        r = run(scope=change("scope", scope_id="scope_xyz"))
        self.assertEqual(r["status"], "valid")
        self.assertEqual(r["scope_id"], "scope_xyz")

    def test_capability_mismatch(self):
        r = run(scope=change("scope", capability_name="other_capability"))
        self.assertEqual(r["status"], "context_mismatch")
        r = run(chain=chain_edit(0, capability_name="other_capability"))
        self.assertEqual(r["status"], "context_mismatch")
        r = run(decision=change("decision", capability_name="other_capability"))
        self.assertEqual(r["status"], "context_mismatch")

    def test_operation_mismatch(self):
        self.assertEqual(run("create", scope=change("scope", operation="improve"))["status"],
                         "context_mismatch")
        self.assertEqual(run("improve", scope=change("scope", operation="create"))["status"],
                         "context_mismatch")
        self.assertEqual(run(decision=change("decision", operation="improve"))["status"],
                         "context_mismatch")

    def test_request_id_mismatch(self):
        for edit in (dict(decision=change("decision", request_id="other_id")),
                     dict(dres=change("dres", request_id="other_id")),
                     dict(chain=chain_edit(0, request_id="other_id")),
                     dict(chain=chain_edit(15, request_id="other_id"))):
            self.assertEqual(run(**edit)["status"], "context_mismatch", list(edit))

    def test_implementation_request_id_mismatch(self):
        for edit in (dict(decision=change("decision", implementation_request_id="other_id")),
                     dict(approval=change("approval", implementation_request_id="other_id")),
                     dict(dres=change("dres", implementation_request_id="other_id")),
                     dict(chain=chain_edit(15, implementation_request_id="other_id"))):
            self.assertEqual(run(**edit)["status"], "context_mismatch", list(edit))

    def test_approval_request_id_mismatch(self):
        for edit in (dict(decision=change("decision", approval_request_id="other_id")),
                     dict(approval=change("approval", approval_request_id="other_id")),
                     dict(dres=change("dres", approval_request_id="other_id"))):
            self.assertEqual(run(**edit)["status"], "context_mismatch", list(edit))

    def test_decision_id_mismatch(self):
        for edit in (dict(decision=change("decision", decision_id="other_id")),
                     dict(dres=change("dres", decision_id="other_id"))):
            self.assertEqual(run(**edit)["status"], "context_mismatch", list(edit))

    def test_plan_id_and_contract_id_mismatch(self):
        self.assertEqual(run(chain=chain_edit(15, plan_id="other_plan"))["status"],
                         "context_mismatch")
        self.assertEqual(run(chain=chain_edit(15, contract_id="other_contract"))["status"],
                         "context_mismatch")

    def test_boundary_status_mismatch_is_rejected(self):
        for edit in (chain_edit(15, boundary_status="other_status"),
                     chain_edit(14, status="other_status")):
            r = run(chain=edit)
            self.assertIn(r["status"], ("invalid_context", "context_mismatch"))
            self.assertIs(r["valid"], False)

    def test_forged_prompt897_result_identity(self):
        for key in ("decision_id", "request_id", "implementation_request_id",
                    "approval_request_id", "capability_name", "operation"):
            value = "improve" if key == "operation" else "forged_id"
            r = run(dres=change("dres", **{key: value}))
            self.assertEqual(r["status"], "context_mismatch", key)
            self.assertTrue(all(r[k] is None for k in IDENTITY), key)

    def test_forged_policy_and_request_validation_result(self):
        self.assertEqual(run(vres=change("vres", plan_id="forged_plan"))["status"],
                         "context_mismatch")
        self.assertEqual(run(policy=change("policy", status="blocked"))["status"],
                         "invalid_context")
        self.assertEqual(run(policy=change("policy", implementation_allowed=True))["status"],
                         "invalid_context")
        self.assertEqual(run(policy=None)["status"], "invalid_context")
        for bad in (None, {}, [], "valid"):
            self.assertEqual(run(avres=bad)["status"], "invalid_approval_request", bad)
        self.assertEqual(run(avres=change("avres", valid=False))["status"],
                         "invalid_approval_request")

    def test_invalid_section16_context(self):
        for index in (0, 3, 11, 14, 15):
            r = run(chain=lambda c, i=index: c["chain"][:i] + [None] + c["chain"][i + 1:])
            self.assertEqual(r["status"], "invalid_context", index)
        self.assertEqual(run(vres=None)["status"], "invalid_context")

    def test_improve_or_conflict_chain_is_unsupported(self):
        decision = fx()[7]
        for tail in (base_chain()[3:], base_chain("improve")[3:]):
            chain = conflict_chain(tail)
            r = run(chain=chain, vres=derive(chain), decision=decision)
            self.assertEqual(r["status"], "unsupported_status")
            self.assertIs(r["valid"], False)


class ContractTests(unittest.TestCase):
    def test_rejected_results_never_carry_identity(self):
        rejected = [
            run(auth=None), run(scope=None), run(approval=None), run(decision=None),
            run(dres=None), run(chain=chain_edit(0, request_id="x")),
            run(scope=change("scope", authority_id="other_auth")),
            run(decision=change("decision", approval_status="approved"))]
        self.assertEqual(len({r["status"] for r in rejected}), 7)
        for r in rejected:
            self.assertIs(r["valid"], False)
            self.assertTrue(all(r[k] is None for k in IDENTITY), r)
            self.assertEqual(r["reason"], r["status"])
            self.assertTrue(validate_result(r)["valid"], r)

    def test_flags_false_in_every_outcome(self):
        results = [run(), run("improve"), run(auth=None), run(scope=None),
                   run(approval=None), run(decision=None), run(dres=None),
                   run(scope=change("scope", operation="improve")),
                   run(scope=change("scope", operation="improve_or_conflict"))]
        for r in results:
            for key in FALSE_FLAGS:
                self.assertIs(r[key], False, (r["status"], key))

    def test_callables_and_dynamic_values_are_rejected_and_never_called(self):
        calls = []

        def trap(*_a, **_k):
            calls.append(1)
            return "x"

        for edit in (dict(scope=change("scope", scope_id=trap)),
                     dict(scope=change("scope", capability_name=trap)),
                     dict(scope=change("scope", operation=trap)),
                     dict(auth=change("auth", authority_id=trap)),
                     dict(decision=change("decision", decision_id=trap)),
                     dict(decision=change("decision", approval_status=trap)),
                     dict(approval=change("approval", approval_request_id=trap)),
                     dict(dres=change("dres", decision_id=trap)),
                     dict(dres=change("dres", reason=trap)),
                     dict(chain=chain_edit(15, plan_id=trap))):
            r = run(**edit)
            self.assertIs(r["valid"], False, list(edit))
            self.assertTrue(all(r[k] is None for k in IDENTITY))
        self.assertEqual(calls, [])

    def test_executable_looking_values_are_rejected(self):
        for value in ("http://example.com", "__import__('os')", "lambda: 1", "rm -rf /",
                      "api_key_value", "exec_this", "$(whoami)"):
            self.assertEqual(run(scope=change("scope", scope_id=value))["status"],
                             "invalid_scope", value)
            self.assertEqual(run(scope=change("scope", capability_name=value))["status"],
                             "invalid_scope", value)
            self.assertIs(run(decision=change("decision", decision_id=value))["valid"], False)

    def test_repeated_validation_is_identical_and_results_are_fresh(self):
        first = run()
        for _ in range(3):
            self.assertEqual(run(), first)
        self.assertEqual(run(auth=None), run(auth=None))
        a, b = run(), run()
        self.assertIsNot(a, b)
        a["status"] = "tampered"
        self.assertEqual(run()["status"], "valid")
        self.assertEqual(b["status"], "valid")
        for value in b.values():
            self.assertIn(type(value), (int, str, bool, type(None)))

    def test_validation_does_not_modify_inputs(self):
        auth, scope, chain, vres, policy, approval, avres, decision, dres = fx()
        snapshot = copy.deepcopy((auth, scope, chain, vres, policy, approval, avres, decision,
                                  dres))
        for _ in range(2):
            check(auth, scope, *chain, vres, policy, approval, avres, decision, dres)
        self.assertEqual((auth, scope, chain, vres, policy, approval, avres, decision, dres),
                         snapshot)
        bad = copy.deepcopy(decision)
        bad["approval_status"] = "approved"
        before = copy.deepcopy(bad)
        check(auth, scope, *chain, vres, policy, approval, avres, bad, dres)
        self.assertEqual(bad, before)

    def test_internal_failure_maps_to_validation_error(self):
        with mock.patch.object(mod, "validate_approval_authority_source",
                               side_effect=RuntimeError("boom")):
            r = run()
        self.assertEqual(r["status"], "validation_error")
        self.assertIs(r["valid"], False)
        for key in FALSE_FLAGS:
            self.assertIs(r[key], False)
        self.assertTrue(all(r[k] is None for k in IDENTITY))

    def test_garbage_inputs_never_raise(self):
        for bad in (None, 0, "x", [], {}, object(), b"x", 3.5, ()):
            self.assertEqual(check(bad, bad, bad, bad, bad)["status"], "invalid_authority")
        self.assertEqual(check()["status"], "invalid_authority")


class ResultValidatorTests(unittest.TestCase):
    def test_malformed_results_and_report_shape(self):
        for bad in (None, [], "valid", 7, {}, {"status": object()},
                    {k: object() for k in RESULT_KEYS}):
            report = validate_result(bad)
            self.assertFalse(report["valid"], bad)
            self.assertIs(report["execution_allowed"], False)
            self.assertIs(report["executed"], False)
            self.assertEqual(sorted(report), ["errors", "executed", "execution_allowed",
                                              "valid"])
        self.assertFalse(validate_result()["valid"])

    def test_missing_and_unexpected_keys(self):
        good = run()
        for key in RESULT_KEYS:
            self.assertFalse(validate_result(without(good, key))["valid"], key)
        for key in ("approved", "authorization", "extra"):
            self.assertFalse(validate_result(dict(good, **{key: True}))["valid"], key)

    def test_altered_flags_status_and_reason(self):
        good = run()
        for key in FALSE_FLAGS:
            self.assertFalse(validate_result(dict(good, **{key: True}))["valid"], key)
        self.assertFalse(validate_result(dict(good, status="approved"))["valid"])
        self.assertFalse(validate_result(dict(good, valid=False))["valid"])
        self.assertFalse(validate_result(dict(good, reason="approved"))["valid"])
        self.assertFalse(validate_result(dict(good, version=2))["valid"])
        self.assertFalse(validate_result(dict(good, version=True))["valid"])

    def test_identity_rules(self):
        good = run()
        for key in IDENTITY:
            self.assertFalse(validate_result(dict(good, **{key: None}))["valid"], key)
            bad = "http://x" if key in ("authority_id", "scope_id", "capability_name",
                                        "operation") else 7
            self.assertFalse(validate_result(dict(good, **{key: bad}))["valid"], key)
        self.assertFalse(validate_result(dict(good, operation="improve_or_conflict"))["valid"])
        rejected = run(auth=None)
        self.assertFalse(validate_result(dict(rejected, decision_id="dec_001"))["valid"])


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
                  "openai", "tempfile", "glob", "io", "re", "copy"}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split(".")[0], banned, alias.name)
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn((node.module or "").split(".")[0], banned, node.module)

    def test_only_expected_imports(self):
        modules = sorted(node.module for node in ast.walk(self.tree)
                         if isinstance(node, ast.ImportFrom))
        self.assertEqual(modules, [
            "approval_authority_scope", "approval_authority_source",
            "capabilities.capability_evolution_proposal",
            "capabilities.capability_evolution_request",
            "capabilities.capability_implementation_request_validation",
            "capabilities.capability_registry", "implementation_approval_decision",
            "implementation_approval_decision_validation", "implementation_approval_request"])
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

    def test_no_classes_and_exactly_two_entry_points(self):
        self.assertFalse([n for n in ast.walk(self.tree) if isinstance(n, ast.ClassDef)])
        public = [n.name for n in self.tree.body
                  if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]
        self.assertEqual(sorted(public), ["validate_approval_scope_context",
                                          "validate_approval_scope_context_result"])
        for name in dir(mod):
            self.assertFalse(name.lower().startswith(("grant", "approve", "authorize")), name)

    def test_no_filesystem_network_or_process_behavior(self):
        context = fx()
        with mock.patch("builtins.open", side_effect=AssertionError("open")), \
                mock.patch.object(socket, "socket", side_effect=AssertionError("socket")), \
                mock.patch.object(socket, "create_connection",
                                  side_effect=AssertionError("network")), \
                mock.patch.object(subprocess, "Popen", side_effect=AssertionError("proc")), \
                mock.patch.object(subprocess, "run", side_effect=AssertionError("run")), \
                mock.patch.object(os, "system", side_effect=AssertionError("system")), \
                mock.patch.object(os, "remove", side_effect=AssertionError("remove")), \
                mock.patch.object(os, "mkdir", side_effect=AssertionError("mkdir")), \
                mock.patch.object(os, "listdir", side_effect=AssertionError("listdir")):
            auth, scope, chain, vres, policy, approval, avres, decision, dres = context
            self.assertEqual(check(auth, scope, *chain, vres, policy, approval, avres,
                                   decision, dres)["status"], "valid")
            self.assertEqual(check(None)["status"], "invalid_authority")
            self.assertTrue(validate_result(run())["valid"])

    def test_upstream_modules_do_not_reference_this_module(self):
        names = [n for n in os.listdir(os.path.join(ROOT, "autonomy"))
                 if n.endswith(".py") and n != "approval_scope_context_validation.py"]
        self.assertIn("approval_authority_scope.py", names)
        for name in names:
            with open(os.path.join(ROOT, "autonomy", name), "r", encoding="utf-8") as handle:
                self.assertNotIn("approval_scope_context_validation", handle.read())

    def test_autonomy_package_contains_the_section17_modules(self):
        names = sorted(n for n in os.listdir(os.path.join(ROOT, "autonomy"))
                       if n != "__pycache__")
        for required in ("__init__.py", "implementation_permission_policy.py",
                         "implementation_approval_request.py",
                         "implementation_approval_decision.py",
                         "implementation_approval_decision_validation.py",
                         "approval_authority_source.py", "approval_authority_scope.py",
                         "approval_scope_context_validation.py"):
            self.assertIn(required, names)


class DocumentationTests(unittest.TestCase):
    def test_doc_exists_and_states_the_invariants(self):
        self.assertTrue(os.path.isfile(DOC))
        with open(DOC, "r", encoding="utf-8") as handle:
            text = handle.read()
        for needle in ("authority_id", "scope_id", "capability_name", "operation",
                       "request_id", "implementation_request_id", "approval_request_id",
                       "decision_id", "plan_id", "contract_id", "boundary_status",
                       "approval_status", "pending_approval", "implementation_allowed",
                       "execution_allowed", "executed", "improve_or_conflict",
                       "invalid_authority", "invalid_scope", "invalid_approval_request",
                       "invalid_approval_decision", "invalid_decision_validation",
                       "invalid_context", "context_mismatch", "unsupported_status",
                       "validation_error", "validate_approval_scope_context",
                       "validate_approval_scope_context_result"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
