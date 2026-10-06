"""
Prompt 901 - Section 17 Final Controlled Autonomy Checkpoint.

A lightweight, deterministic checkpoint over the COMPLETE Controlled Autonomy chain, from the
Section 16 capability chain through Prompt 900. It composes the real, existing builders and
validators (nothing is re-implemented here) and proves that the chain stays descriptive,
validated and non-executing:

  * no valid state is approved / authorized / implementation_allowed / execution_allowed /
    implementation_started / executed;
  * "pending_approval" is the terminal approval-decision state;
  * approval_capable=True on an authority or scope grants nothing;
  * "improve_or_conflict" never becomes executable or approval-ready;
  * invalid, forged, mismatched, malformed, unsupported or altered objects are rejected;
  * the Section 17 production modules contain no I/O, network, subprocess, exec / eval,
    dynamic attribute loading, external AI API, persistence, code generation, self-modification,
    implementation or execution path, and no hidden approval / grant path.

Run (from app/src/main/python/):
    python -m unittest tests.test_section17_final_checkpoint_prompt901 -v
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

from autonomy import approval_authority_scope as m899
from autonomy import approval_authority_source as m898
from autonomy import approval_scope_context_validation as m900
from autonomy import implementation_approval_decision as m896
from autonomy import implementation_approval_decision_validation as m897
from autonomy import implementation_approval_request as m895
from autonomy import implementation_permission_policy as m894
from autonomy.approval_authority_scope import validate_approval_authority_scope
from autonomy.approval_authority_source import validate_approval_authority_source
from autonomy.approval_scope_context_validation import (
    RESULT_KEYS, STATUSES, validate_approval_scope_context as check900,
    validate_approval_scope_context_result as validate900)
from autonomy.implementation_approval_decision import validate_implementation_approval_decision
from autonomy.implementation_approval_decision_validation import (
    validate_implementation_approval_decision_validation_result as validate897)
from autonomy.implementation_approval_request import validate_implementation_approval_request
from autonomy.implementation_permission_policy import validate_implementation_permission_policy
from capabilities.capability_implementation_request_validation import (
    validate_capability_implementation_request_validation_result as validate892)
from tests.test_approval_scope_context_validation_prompt900 import (
    authority as make_authority, fx as fx900, scope_for)
from tests.test_implementation_permission_policy_prompt894 import (
    base_chain, conflict_chain, derive)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(ROOT))))
DOC = os.path.join(PROJECT, "docs", "section17_final_checkpoint_prompt901.md")
MANIFEST_900 = os.path.join(PROJECT, "PROJECT_PARTS_MANIFEST_Prompt900.json")
SECTION17_MODULES = (m894, m895, m896, m897, m898, m899, m900)
SECTION18_FILES = ("claude_exit_readiness.py", "internal_next_stage.py",
                   "internal_stage_decision.py", "internal_evolution_input.py",
                   "internal_evolution_result.py", "internal_evolution_result_validation.py",
                   "final_internal_evolution_gate.py")  # Prompt 902+: Section 18, not Section 17
SECTION17_FILES = tuple(sorted(
    os.path.join(ROOT, "autonomy", name) for name in os.listdir(os.path.join(ROOT, "autonomy"))
    if name.endswith(".py") and name not in SECTION18_FILES))

IDENTITY = m900.IDENTITY_KEYS
FALSE_FLAGS = ("implementation_allowed", "execution_allowed", "executed")
PERMISSION_FLAGS = ("implementation_allowed", "execution_allowed", "implementation_started",
                    "executed")
APPROVAL_WORDS = ("approved", "approval", "approval_status", "approved_by", "authorization",
                  "authorisation", "authorized", "authorised", "granted", "allowed",
                  "permitted", "permission")
OPS = ("create", "improve")
(REQUEST, ANALYSIS, SPEC, PLAN, PROPOSAL, CANDIDATE, READINESS, DESIGN, V885, BLUEPRINT, B887,
 CONTRACT, CREPORT, R889, BOUNDARY, IMPL) = range(16)
STAGE_NAMES = ("request", "analysis", "specification", "plan", "proposal", "candidate",
               "readiness", "design", "design_validation", "blueprint", "blueprint_validation",
               "contract", "contract_validation", "contract_readiness", "boundary",
               "implementation_request")


def ctx(op="create"):
    """Fresh copy of the full real chain: dict of every stage object."""
    auth, scope, chain, vres, policy, approval, avres, decision, dres = fx900(op)
    return {"auth": auth, "scope": scope, "chain": chain, "vres": vres, "policy": policy,
            "approval": approval, "avres": avres, "decision": decision, "dres": dres}


def run(op="create", **over):
    """Run Prompt 900 on the (possibly altered) context. Override: value or f(ctx)->value."""
    c = ctx(op)
    for key, value in over.items():
        c[key] = value(c) if callable(value) else value
    return check900(c["auth"], c["scope"], *c["chain"], c["vres"], c["policy"], c["approval"],
                    c["avres"], c["decision"], c["dres"])


def change(key, **fields):
    return lambda c: dict(c[key], **fields)


def chain_edit(index, **fields):
    def edit(c):
        chain = list(c["chain"])
        chain[index] = dict(chain[index], **fields)
        return chain
    return edit


def without(mapping, key):
    value = dict(mapping)
    del value[key]
    return value


def walk_keys(value):
    """Every dict key found anywhere inside a nested value."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            for sub in walk_keys(item):
                yield sub
    elif isinstance(value, (list, tuple)):
        for item in value:
            for sub in walk_keys(item):
                yield sub


def walk_items(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item
            for pair in walk_items(item):
                yield pair
    elif isinstance(value, (list, tuple)):
        for item in value:
            for pair in walk_items(item):
                yield pair


def trap(*_a, **_k):
    raise AssertionError("dynamic value was called")


class FullChainConsistencyTests(unittest.TestCase):
    def test_create_and_improve_chains_are_valid_end_to_end(self):
        self._create_chain_is_valid_end_to_end()
        self._improve_chain_is_valid_end_to_end()

    def _create_chain_is_valid_end_to_end(self):
        r = run("create")
        self.assertEqual(r["status"], "valid")
        self.assertIs(r["valid"], True)
        self.assertEqual(r["operation"], "create")

    def _improve_chain_is_valid_end_to_end(self):
        r = run("improve")
        self.assertEqual(r["status"], "valid")
        self.assertIs(r["valid"], True)
        self.assertEqual(r["operation"], "improve")

    def test_section16_chain_has_the_sixteen_stages_and_is_valid(self):
        for op in OPS:
            c = ctx(op)
            self.assertEqual(len(c["chain"]), 16)
            self.assertEqual(len(STAGE_NAMES), 16)
            self.assertEqual(c["vres"]["status"], "valid")
            self.assertTrue(validate892(c["vres"])["valid"], op)
            self.assertEqual(derive(c["chain"]), c["vres"])
            self.assertEqual(c["chain"][BOUNDARY]["status"], "ready")

    def test_section16_identity_is_consistent_across_stages(self):
        for op in OPS:
            chain = ctx(op)["chain"]
            request, plan, impl = chain[REQUEST], chain[PLAN], chain[IMPL]
            self.assertEqual(request["operation"], op)
            for stage in (impl, chain[PROPOSAL], chain[CANDIDATE], chain[CONTRACT]):
                self.assertEqual(stage["request_id"], request["request_id"])
                self.assertEqual(stage["capability_name"], request["capability_name"])
            self.assertEqual(impl["operation"], op)
            self.assertEqual(impl["plan_id"], plan["plan_id"])
            self.assertEqual(impl["contract_id"], chain[CONTRACT]["contract_id"])
            self.assertEqual(impl["boundary_status"], chain[BOUNDARY]["status"])

    def test_section17_identity_is_consistent_from_policy_to_prompt900(self):
        for op in OPS:
            c = ctx(op)
            request, impl = c["chain"][REQUEST], c["chain"][IMPL]
            for obj in (c["policy"], c["approval"], c["decision"], c["dres"], c["vres"]):
                self.assertEqual(obj["request_id"], request["request_id"])
                self.assertEqual(obj["capability_name"], request["capability_name"])
                self.assertEqual(obj["operation"], op)
                self.assertEqual(obj["implementation_request_id"],
                                 impl["implementation_request_id"])
            self.assertEqual(c["decision"]["approval_request_id"],
                             c["approval"]["approval_request_id"])
            self.assertEqual(c["dres"]["decision_id"], c["decision"]["decision_id"])
            self.assertEqual(c["scope"]["authority_id"], c["auth"]["authority_id"])
            self.assertEqual(c["scope"]["capability_name"], request["capability_name"])
            self.assertEqual(c["scope"]["operation"], op)

    def test_prompt900_identity_is_taken_from_the_trusted_chain(self):
        for op in OPS:
            c = ctx(op)
            r = run(op)
            self.assertEqual({k: r[k] for k in IDENTITY}, {
                "authority_id": c["auth"]["authority_id"], "scope_id": c["scope"]["scope_id"],
                "capability_name": c["chain"][REQUEST]["capability_name"], "operation": op,
                "request_id": c["chain"][REQUEST]["request_id"],
                "implementation_request_id": c["chain"][IMPL]["implementation_request_id"],
                "approval_request_id": c["approval"]["approval_request_id"],
                "decision_id": c["decision"]["decision_id"]})

    def test_every_section17_object_passes_its_own_validator(self):
        for op in OPS:
            c = ctx(op)
            self.assertEqual(validate_approval_authority_source(c["auth"])["status"], "valid")
            self.assertEqual(validate_approval_authority_scope(c["scope"])["status"], "valid")
            self.assertTrue(validate_implementation_permission_policy(c["policy"])["valid"])
            self.assertTrue(validate_implementation_approval_request(c["approval"])["valid"])
            self.assertTrue(validate_implementation_approval_decision(c["decision"])["valid"])
            self.assertTrue(validate897(c["dres"])["valid"])
            self.assertTrue(validate900(run(op))["valid"])

    def test_policy_and_approval_request_are_descriptive_records(self):
        self._policy_is_eligible_and_not_a_permission()
        self._approval_request_is_a_request_not_an_approval()

    def _policy_is_eligible_and_not_a_permission(self):
        for op in OPS:
            policy = ctx(op)["policy"]
            self.assertEqual(policy["status"], "eligible")
            self.assertIs(policy["eligible"], True)
            for key in PERMISSION_FLAGS:
                self.assertIs(policy[key], False, key)

    def _approval_request_is_a_request_not_an_approval(self):
        for op in OPS:
            approval = ctx(op)["approval"]
            self.assertIs(approval["approval_required"], True)
            self.assertEqual(approval["policy_status"], "eligible")
            for key in PERMISSION_FLAGS:
                self.assertIs(approval[key], False, key)
            self.assertFalse(set(walk_keys(approval)) & set(APPROVAL_WORDS[:1] + ("approved_by",)))

    def test_repeated_runs_are_identical_and_inputs_untouched(self):
        for op in OPS:
            c = ctx(op)
            snapshot = copy.deepcopy(c)
            first = check900(c["auth"], c["scope"], *c["chain"], c["vres"], c["policy"],
                             c["approval"], c["avres"], c["decision"], c["dres"])
            second = check900(c["auth"], c["scope"], *c["chain"], c["vres"], c["policy"],
                              c["approval"], c["avres"], c["decision"], c["dres"])
            self.assertEqual(first, second)
            self.assertIsNot(first, second)
            self.assertEqual(c, snapshot)


class DescriptiveOnlyTests(unittest.TestCase):
    def test_no_valid_state_is_approved_or_authorized(self):
        for op in OPS:
            c = ctx(op)
            for name in ("auth", "scope", "policy", "approval", "decision", "dres", "vres"):
                keys = set(walk_keys(c[name]))
                for word in ("approved", "authorized", "authorised", "granted", "approved_by",
                             "authorization"):
                    self.assertNotIn(word, keys, (op, name, word))
            for stage in c["chain"]:
                self.assertFalse(set(walk_keys(stage)) & {"approved", "authorized", "granted"})
            r = run(op)
            self.assertNotIn(r["status"], ("approved", "authorized"))

    def test_permission_flags_are_false_in_every_valid_object(self):
        for op in OPS:
            c = ctx(op)
            objects = [c["auth"], c["scope"], c["policy"], c["approval"], c["decision"],
                       c["dres"], c["vres"], run(op)] + list(c["chain"])
            for obj in objects:
                for key, value in walk_items(obj):
                    if key in PERMISSION_FLAGS:
                        self.assertIs(value, False, (op, key))

    def test_prompt900_result_is_descriptive_and_never_approved(self):
        self._prompt900_result_flags_are_always_false()
        self._valid_does_not_mean_approved_or_allowed()
        self._prompt900_result_has_no_approval_or_permission_field()

    def _prompt900_result_flags_are_always_false(self):
        for op in OPS:
            r = run(op)
            for key in FALSE_FLAGS:
                self.assertIs(r[key], False, key)
        for edit in (dict(auth=None), dict(scope=None), dict(approval=None),
                     dict(decision=None), dict(dres=None), dict(policy=None),
                     dict(scope=change("scope", operation="improve")),
                     dict(decision=change("decision", approval_status="approved"))):
            r = run("create", **edit)
            for key in FALSE_FLAGS:
                self.assertIs(r[key], False, (list(edit), key))

    def test_no_status_vocabulary_contains_an_approval_state(self):
        vocabularies = {"900": m900.STATUSES, "897": m897.STATUSES,
                        "894": m894.STATUSES, "898": m898.STATUSES, "899": m899.STATUSES}
        for name, statuses in vocabularies.items():
            for status in statuses:
                for word in ("approved", "authorized", "authorised", "granted", "permitted",
                             "executed", "allowed"):
                    self.assertNotIn(word, status, (name, status))
        self.assertEqual(len(STATUSES), 10)
        self.assertIn("valid", STATUSES)

    def _prompt900_result_has_no_approval_or_permission_field(self):
        r = run()
        self.assertEqual(list(r), list(RESULT_KEYS))
        self.assertEqual(len(RESULT_KEYS), 15)
        for word in ("approved", "approval_status", "authorization", "granted", "permission",
                     "implementation_started"):
            self.assertNotIn(word, r)

    def _valid_does_not_mean_approved_or_allowed(self):
        for op in OPS:
            r = run(op)
            self.assertEqual(r["status"], "valid")
            self.assertIs(r["implementation_allowed"], False)
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)
            self.assertEqual(r["reason"], "valid")


class PendingApprovalBoundaryTests(unittest.TestCase):
    def test_decision_is_pending_approval_for_both_operations(self):
        for op in OPS:
            decision = ctx(op)["decision"]
            self.assertEqual(decision["approval_status"], "pending_approval")
            self.assertEqual(decision["reason"], "approval_decision_not_made")
            self.assertIs(decision["approval_required"], True)

    def test_only_pending_approval_is_accepted_and_approved_styles_are_unsupported(self):
        self._pending_approval_is_the_only_accepted_decision_status()
        self._approved_style_statuses_are_unsupported()

    def _pending_approval_is_the_only_accepted_decision_status(self):
        for value in ("rejected", "", None, 7, "Pending_Approval", "pending", "complete",
                      "done", "ready", "in_progress"):
            r = run(decision=change("decision", approval_status=value))
            self.assertIs(r["valid"], False, value)
            self.assertIn(r["status"], ("invalid_approval_decision", "unsupported_status"))

    def _approved_style_statuses_are_unsupported(self):
        for value in ("approved", "authorized", "authorization", "granted", "allowed",
                      "permitted"):
            r = run(decision=change("decision", approval_status=value))
            self.assertEqual(r["status"], "unsupported_status", value)
            self.assertIs(r["valid"], False)

    def test_approval_decision_validation_never_reports_an_approved_state(self):
        for op in OPS:
            dres = ctx(op)["dres"]
            self.assertEqual(dres["status"], "valid")
            self.assertNotIn("approval_status", dres)
            self.assertIs(dres["execution_allowed"], False)
            self.assertIs(dres["executed"], False)

    def test_approval_fields_and_flipped_approval_required_are_rejected(self):
        self._approval_fields_cannot_be_attached_to_any_section17_object()
        self._decision_with_flipped_approval_required_is_rejected()

    def _approval_fields_cannot_be_attached_to_any_section17_object(self):
        for target in ("auth", "scope", "approval", "decision", "dres"):
            for key in ("approved", "authorization", "granted", "approved_by"):
                r = run(**{target: change(target, **{key: True})})
                self.assertEqual(r["status"], "unsupported_status", (target, key))

    def _decision_with_flipped_approval_required_is_rejected(self):
        r = run(decision=change("decision", approval_required=False))
        self.assertEqual(r["status"], "invalid_approval_decision")
        r = run(approval=change("approval", approval_required=False))
        self.assertEqual(r["status"], "invalid_approval_request")


class ApprovalCapableIsNotAGrantTests(unittest.TestCase):
    def test_approval_capable_true_or_false_grants_no_permission(self):
        self._approval_capable_true_grants_no_permission()
        self._approval_capable_false_is_equally_non_executing()

    def _approval_capable_true_grants_no_permission(self):
        c = ctx()
        self.assertIs(c["auth"]["approval_capable"], True)
        self.assertIs(c["scope"]["approval_capable"], True)
        for obj in (c["auth"], c["scope"]):
            self.assertIs(obj["implementation_allowed"], False)
            self.assertIs(obj["execution_allowed"], False)
        r = run()
        self.assertEqual(r["status"], "valid")
        self.assertIs(r["implementation_allowed"], False)
        self.assertIs(r["execution_allowed"], False)
        self.assertIs(r["executed"], False)

    def _approval_capable_false_is_equally_non_executing(self):
        c = ctx()
        auth = make_authority(approval_capable=False)
        scope = scope_for(auth)
        self.assertIs(scope["approval_capable"], False)
        r = check900(auth, scope, *c["chain"], c["vres"], c["policy"], c["approval"],
                     c["avres"], c["decision"], c["dres"])
        self.assertEqual(r["status"], "valid")
        for key in FALSE_FLAGS:
            self.assertIs(r[key], False)

    def test_every_authority_type_is_descriptive_only(self):
        c = ctx()
        for authority_type in ("user", "system_policy", "trusted_internal_controller"):
            auth = make_authority(authority_type)
            scope = scope_for(auth)
            r = check900(auth, scope, *c["chain"], c["vres"], c["policy"], c["approval"],
                         c["avres"], c["decision"], c["dres"])
            self.assertEqual(r["status"], "valid", authority_type)
            self.assertEqual(c["decision"]["approval_status"], "pending_approval")
            for key in FALSE_FLAGS:
                self.assertIs(r[key], False, (authority_type, key))

    def test_approval_capable_cannot_carry_permission_and_must_agree(self):
        self._approval_capable_cannot_be_combined_with_a_permission_flag()
        self._scope_and_authority_approval_capable_must_agree()

    def _approval_capable_cannot_be_combined_with_a_permission_flag(self):
        for key in ("implementation_allowed", "execution_allowed"):
            r = run(auth=change("auth", **{key: True}))
            self.assertEqual(r["status"], "invalid_authority", key)
            r = run(scope=change("scope", **{key: True}))
            self.assertEqual(r["status"], "invalid_scope", key)

    def _scope_and_authority_approval_capable_must_agree(self):
        r = run(scope=change("scope", approval_capable=False))
        self.assertEqual(r["status"], "context_mismatch")
        r = run(auth=change("auth", approval_capable=False))
        self.assertEqual(r["status"], "context_mismatch")

    def test_untrusted_or_malformed_authority_is_rejected(self):
        for bad in (None, {}, [], "user", 7,
                    change("auth", authority_type="superuser"),
                    lambda c: without(c["auth"], "trusted")):
            r = run(auth=bad)
            self.assertIs(r["valid"], False)
            self.assertIn(r["status"], ("invalid_authority", "unsupported_status"))


class ImproveOrConflictBoundaryTests(unittest.TestCase):
    def _conflict_chains(self):
        for tail in (base_chain()[3:], base_chain("improve")[3:]):
            yield conflict_chain(tail)

    def test_conflict_chain_is_improve_or_conflict_and_never_validates(self):
        self._conflict_analysis_is_improve_or_conflict()
        self._conflict_chain_never_validates_in_section16()

    def _conflict_analysis_is_improve_or_conflict(self):
        for chain in self._conflict_chains():
            self.assertEqual(chain[ANALYSIS]["status"], "improve_or_conflict")

    def _conflict_chain_never_validates_in_section16(self):
        for chain in self._conflict_chains():
            self.assertEqual(derive(chain)["status"], "unsupported_status")
            self.assertIs(derive(chain)["valid"], False)

    def test_conflict_chain_yields_an_ineligible_policy_without_permission(self):
        for chain in self._conflict_chains():
            policy = m894.build_implementation_permission_policy(*chain, derive(chain),
                                                                  "pol_001")
            self.assertEqual(policy["status"], "unsupported")
            self.assertIs(policy["eligible"], False)
            for key in PERMISSION_FLAGS:
                self.assertIs(policy[key], False, key)

    def test_conflict_chain_never_produces_an_approval_request(self):
        for chain in self._conflict_chains():
            vres = derive(chain)
            policy = m894.build_implementation_permission_policy(*chain, vres, "pol_001")
            built = m895.build_implementation_approval_request(*chain, vres, policy, "apr_x")
            self.assertEqual(built["status"], "unsupported_status")
            self.assertIsNone(built["approval_request"])
            self.assertIs(built["execution_allowed"], False)
            self.assertIs(built["executed"], False)

    def test_conflict_chain_is_unsupported_in_prompt900(self):
        decision = ctx()["decision"]
        for chain in self._conflict_chains():
            r = run(chain=chain, vres=derive(chain), decision=decision)
            self.assertEqual(r["status"], "unsupported_status")
            self.assertIs(r["valid"], False)
            self.assertTrue(all(r[k] is None for k in IDENTITY))

    def test_improve_or_conflict_is_unsupported_everywhere_and_not_vocabulary(self):
        self._improve_or_conflict_operation_is_unsupported_everywhere()
        self._improve_or_conflict_is_never_in_the_result_vocabulary()

    def _improve_or_conflict_operation_is_unsupported_everywhere(self):
        for target in ("scope", "approval", "decision"):
            r = run(**{target: change(target, operation="improve_or_conflict")})
            self.assertEqual(r["status"], "unsupported_status", target)
            self.assertIs(r["valid"], False)
        for op in OPS:
            self.assertNotEqual(op, "improve_or_conflict")

    def _improve_or_conflict_is_never_in_the_result_vocabulary(self):
        self.assertNotIn("improve_or_conflict", STATUSES)
        self.assertNotIn("improve_or_conflict", m900.SUPPORTED_OPERATIONS)
        self.assertNotIn("improve_or_conflict", run().values())


class InvalidAndMismatchedContextTests(unittest.TestCase):
    def test_every_argument_set_to_none_is_rejected(self):
        for op in OPS:
            base = ctx(op)
            args = [base["auth"], base["scope"]] + list(base["chain"]) + [
                base["vres"], base["policy"], base["approval"], base["avres"],
                base["decision"], base["dres"]]
            self.assertEqual(len(args), 24)
            for index in range(len(args)):
                altered = list(args)
                altered[index] = None
                r = check900(*altered)
                self.assertIs(r["valid"], False, (op, index))
                self.assertTrue(all(r[k] is None for k in IDENTITY), (op, index))
                self.assertTrue(validate900(r)["valid"], (op, index))

    def test_every_section16_object_must_be_present_and_valid(self):
        for index in range(16):
            for bad in (None, {}, [], "x", 7):
                r = run(chain=lambda c, i=index, b=bad: c["chain"][:i] + [b] + c["chain"][i + 1:])
                self.assertIs(r["valid"], False, (STAGE_NAMES[index], bad))

    def test_identity_changes_between_stages_are_a_context_mismatch(self):
        self._changing_identity_between_stages_is_a_context_mismatch()
        self._identity_edits_are_rejected_in_the_improve_flow_too()

    def _changing_identity_between_stages_is_a_context_mismatch(self):
        edits = {
            "scope.authority_id": dict(scope=change("scope", authority_id="other_auth")),
            "scope.capability_name": dict(scope=change("scope", capability_name="other_cap")),
            "scope.operation": dict(scope=change("scope", operation="improve")),
            "decision.capability_name": dict(
                decision=change("decision", capability_name="other_cap")),
            "decision.operation": dict(decision=change("decision", operation="improve")),
            "decision.request_id": dict(decision=change("decision", request_id="other_id")),
            "decision.implementation_request_id": dict(
                decision=change("decision", implementation_request_id="other_id")),
            "decision.approval_request_id": dict(
                decision=change("decision", approval_request_id="other_id")),
            "decision.decision_id": dict(decision=change("decision", decision_id="other_id")),
            "approval.implementation_request_id": dict(
                approval=change("approval", implementation_request_id="other_id")),
            "approval.approval_request_id": dict(
                approval=change("approval", approval_request_id="other_id")),
            "dres.request_id": dict(dres=change("dres", request_id="other_id")),
            "dres.decision_id": dict(dres=change("dres", decision_id="other_id")),
            "dres.approval_request_id": dict(
                dres=change("dres", approval_request_id="other_id")),
            "chain.request.capability_name": dict(
                chain=chain_edit(REQUEST, capability_name="other_cap")),
            "chain.request.request_id": dict(chain=chain_edit(REQUEST, request_id="other_id")),
            "chain.impl.request_id": dict(chain=chain_edit(IMPL, request_id="other_id")),
            "chain.impl.plan_id": dict(chain=chain_edit(IMPL, plan_id="other_plan")),
            "chain.impl.contract_id": dict(chain=chain_edit(IMPL, contract_id="other_ct")),
            "vres.plan_id": dict(vres=change("vres", plan_id="other_plan")),
        }
        for name, edit in edits.items():
            r = run(**edit)
            self.assertEqual(r["status"], "context_mismatch", name)
            self.assertIs(r["valid"], False, name)
            self.assertTrue(all(r[k] is None for k in IDENTITY), name)

    def _identity_edits_are_rejected_in_the_improve_flow_too(self):
        for edit in (dict(scope=change("scope", operation="create")),
                     dict(decision=change("decision", request_id="other_id")),
                     dict(dres=change("dres", decision_id="other_id")),
                     dict(chain=chain_edit(IMPL, implementation_request_id="other_id"))):
            r = run("improve", **edit)
            self.assertEqual(r["status"], "context_mismatch", list(edit))

    def test_objects_mixed_between_create_and_improve_chains_are_rejected(self):
        improve = ctx("improve")
        for key in ("scope", "decision", "dres", "approval", "policy", "vres"):
            r = run("create", **{key: improve[key]})
            self.assertIs(r["valid"], False, key)
        r = run("create", chain=improve["chain"])
        self.assertIs(r["valid"], False)

    def test_forged_prompt897_result_is_rejected(self):
        for key in ("decision_id", "request_id", "implementation_request_id",
                    "approval_request_id", "capability_name"):
            r = run(dres=change("dres", **{key: "forged_id"}))
            self.assertEqual(r["status"], "context_mismatch", key)
        r = run(dres=change("dres", operation="improve"))
        self.assertEqual(r["status"], "context_mismatch")
        for flag in ("execution_allowed", "executed"):
            r = run(dres=change("dres", **{flag: True}))
            self.assertEqual(r["status"], "invalid_decision_validation", flag)
        self.assertEqual(run(dres=change("dres", valid=False))["status"],
                         "invalid_decision_validation")

    def test_forged_upstream_results_policy_and_scope_are_rejected(self):
        self._forged_prompt892_result_and_policy_are_rejected()
        self._forged_approval_request_validation_result_is_rejected()
        self._forged_valid_scope_with_wrong_authority_is_rejected()

    def _forged_prompt892_result_and_policy_are_rejected(self):
        self.assertEqual(run(vres=change("vres", plan_id="forged"))["status"],
                         "context_mismatch")
        self.assertEqual(run(vres=change("vres", contract_id="forged"))["status"],
                         "context_mismatch")
        self.assertEqual(run(vres=None)["status"], "invalid_context")
        self.assertEqual(run(policy=change("policy", status="blocked"))["status"],
                         "invalid_context")
        self.assertEqual(run(policy=change("policy", eligible=False))["status"],
                         "invalid_context")
        self.assertEqual(run(policy=None)["status"], "invalid_context")

    def _forged_approval_request_validation_result_is_rejected(self):
        for bad in (None, {}, [], "valid", 7):
            self.assertEqual(run(avres=bad)["status"], "invalid_approval_request", bad)
        self.assertEqual(run(avres=change("avres", valid=False))["status"],
                         "invalid_approval_request")

    def _forged_valid_scope_with_wrong_authority_is_rejected(self):
        c = ctx()
        other = make_authority(authority_id="auth_other")
        forged = scope_for(other)
        r = check900(c["auth"], forged, *c["chain"], c["vres"], c["policy"], c["approval"],
                     c["avres"], c["decision"], c["dres"])
        self.assertEqual(r["status"], "context_mismatch")


class ForbiddenFlagTests(unittest.TestCase):
    def test_permission_flags_true_on_section17_objects_and_results_are_rejected(self):
        self._permission_flags_true_on_section17_objects_are_rejected()
        self._permission_flags_true_on_the_policy_are_rejected()
        self._permission_flags_true_on_prompt897_result_are_rejected()

    def _permission_flags_true_on_section17_objects_are_rejected(self):
        expected = {"auth": "invalid_authority", "scope": "invalid_scope",
                    "approval": "invalid_approval_request",
                    "decision": "invalid_approval_decision"}
        for key, status in expected.items():
            for flag in PERMISSION_FLAGS:
                if flag not in ctx()[key]:
                    continue
                r = run(**{key: change(key, **{flag: True})})
                self.assertEqual(r["status"], status, (key, flag))
                self.assertIs(r["valid"], False)

    def _permission_flags_true_on_the_policy_are_rejected(self):
        for flag in PERMISSION_FLAGS:
            r = run(policy=change("policy", **{flag: True}))
            self.assertEqual(r["status"], "invalid_context", flag)

    def _permission_flags_true_on_prompt897_result_are_rejected(self):
        for flag in ("execution_allowed", "executed"):
            r = run(dres=change("dres", **{flag: True}))
            self.assertIs(r["valid"], False, flag)
        for flag in ("implementation_allowed", "implementation_started"):
            r = run(dres=change("dres", **{flag: True}))
            self.assertIs(r["valid"], False, flag)

    def test_permission_flags_true_on_any_section16_object_are_rejected(self):
        checked = 0
        for op in OPS:
            chain = ctx(op)["chain"]
            for index, stage in enumerate(chain):
                for flag in PERMISSION_FLAGS:
                    if flag in stage:
                        checked += 1
                        r = run(op, chain=chain_edit(index, **{flag: True}))
                        self.assertIs(r["valid"], False, (op, STAGE_NAMES[index], flag))
        self.assertGreater(checked, 10)

    def test_truthy_non_bool_flag_values_are_rejected(self):
        for value in (1, "True", "true", [True], {"x": 1}, 1.0):
            for key, flag in (("scope", "implementation_allowed"),
                              ("scope", "execution_allowed"),
                              ("auth", "execution_allowed"),
                              ("decision", "executed"),
                              ("approval", "implementation_started")):
                r = run(**{key: change(key, **{flag: value})})
                self.assertIs(r["valid"], False, (key, flag, value))

    def test_unexpected_or_approval_fields_are_rejected(self):
        for target in ("auth", "scope", "approval", "decision", "dres"):
            r = run(**{target: change(target, extra_field="x")})
            self.assertIs(r["valid"], False, target)
            self.assertNotEqual(r["status"], "valid")

    def test_dynamic_and_executable_looking_values_are_rejected_and_never_called(self):
        for value in (trap, "http://example.com", "__import__('os')", "lambda: 1",
                      "rm -rf /", "$(whoami)"):
            for edit in (dict(scope=change("scope", scope_id=value)),
                         dict(scope=change("scope", capability_name=value)),
                         dict(auth=change("auth", authority_id=value)),
                         dict(decision=change("decision", decision_id=value)),
                         dict(approval=change("approval", approval_request_id=value)),
                         dict(chain=chain_edit(IMPL, plan_id=value))):
                r = run(**edit)
                self.assertIs(r["valid"], False, (list(edit), value))
                self.assertTrue(all(r[k] is None for k in IDENTITY))

    def test_garbage_inputs_never_raise(self):
        for bad in (None, 0, "x", [], {}, object(), b"x", 3.5, ()):
            r = check900(bad, bad, bad, bad, bad)
            self.assertEqual(r["status"], "invalid_authority")
            self.assertIs(r["valid"], False)
        self.assertEqual(check900()["status"], "invalid_authority")


class Prompt900ResultValidationTests(unittest.TestCase):
    def test_valid_and_rejected_results_validate(self):
        results = [run("create"), run("improve"), run(auth=None), run(scope=None),
                   run(decision=None), run(dres=None),
                   run(decision=change("decision", approval_status="approved"))]
        for r in results:
            report = validate900(r)
            self.assertTrue(report["valid"], (r["status"], report))
            self.assertIs(report["execution_allowed"], False)
            self.assertIs(report["executed"], False)
            self.assertEqual(sorted(report), ["errors", "executed", "execution_allowed",
                                              "valid"])

    def test_malformed_results_and_missing_or_unexpected_keys_are_rejected(self):
        self._malformed_results_are_rejected()
        self._missing_and_unexpected_keys_are_rejected()

    def _malformed_results_are_rejected(self):
        for bad in (None, [], "valid", 7, {}, {"status": object()},
                    {k: object() for k in RESULT_KEYS}):
            self.assertFalse(validate900(bad)["valid"], bad)
        self.assertFalse(validate900()["valid"])

    def test_altered_flags_status_reason_and_version_are_rejected(self):
        good = run()
        for key in FALSE_FLAGS:
            self.assertFalse(validate900(dict(good, **{key: True}))["valid"], key)
        self.assertFalse(validate900(dict(good, status="approved"))["valid"])
        self.assertFalse(validate900(dict(good, valid=False))["valid"])
        self.assertFalse(validate900(dict(good, reason="approved"))["valid"])
        self.assertFalse(validate900(dict(good, version=2))["valid"])
        self.assertFalse(validate900(dict(good, version=True))["valid"])

    def _missing_and_unexpected_keys_are_rejected(self):
        good = run()
        for key in RESULT_KEYS:
            self.assertFalse(validate900(without(good, key))["valid"], key)
        for key in ("approved", "authorization", "implementation_started", "extra"):
            self.assertFalse(validate900(dict(good, **{key: True}))["valid"], key)

    def test_rejected_result_must_not_carry_identity_and_valid_one_must(self):
        rejected = run(auth=None)
        for key in IDENTITY:
            self.assertFalse(validate900(dict(rejected, **{key: "x_id"}))["valid"], key)
        good = run()
        for key in IDENTITY:
            self.assertFalse(validate900(dict(good, **{key: None}))["valid"], key)
        self.assertFalse(validate900(dict(good, operation="improve_or_conflict"))["valid"])

    def test_results_are_fresh_and_internal_failure_maps_to_validation_error(self):
        self._results_are_fresh_primitive_dicts()
        self._internal_failure_maps_to_validation_error_without_permission()

    def _results_are_fresh_primitive_dicts(self):
        a, b = run(), run()
        self.assertIsNot(a, b)
        a["status"] = "tampered"
        self.assertEqual(run()["status"], "valid")
        for value in b.values():
            self.assertIn(type(value), (int, str, bool, type(None)))

    def _internal_failure_maps_to_validation_error_without_permission(self):
        with mock.patch.object(m900, "validate_approval_authority_source",
                               side_effect=RuntimeError("boom")):
            r = run()
        self.assertEqual(r["status"], "validation_error")
        self.assertIs(r["valid"], False)
        for key in FALSE_FLAGS:
            self.assertIs(r[key], False)
        self.assertTrue(validate900(r)["valid"])


class NoExecutionOrImplementationPathTests(unittest.TestCase):
    FORBIDDEN_PREFIXES = ("grant", "approve", "authorize", "authorise", "execute", "exec_",
                          "run_", "implement", "apply", "generate", "write", "save", "persist",
                          "modify", "patch", "install", "deploy", "start", "launch", "commit")

    def test_public_api_is_only_build_and_validate_without_grant_or_class(self):
        self._public_api_is_only_build_and_validate()
        self._no_function_or_attribute_names_a_grant_or_execution_path()
        self._section17_modules_define_no_classes()

    def _public_api_is_only_build_and_validate(self):
        for module in SECTION17_MODULES:
            tree = ast.parse(open(module.__file__.replace(".pyc", ".py"),
                                  encoding="utf-8").read())
            public = [n.name for n in tree.body
                      if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]
            self.assertTrue(public, module.__name__)
            for name in public:
                self.assertTrue(name.startswith(("build_", "validate_")), name)

    def _no_function_or_attribute_names_a_grant_or_execution_path(self):
        for module in SECTION17_MODULES:
            for name in dir(module):
                if name.startswith("__") or name.isupper():
                    continue
                lowered = name.lower().lstrip("_")
                if name.startswith("_") or lowered.startswith(("validate", "build")):
                    continue
                self.assertFalse(lowered.startswith(self.FORBIDDEN_PREFIXES),
                                 (module.__name__, name))

    def _section17_modules_define_no_classes(self):
        for path in SECTION17_FILES:
            tree = ast.parse(open(path, encoding="utf-8").read())
            self.assertFalse([n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)], path)

    def test_the_whole_chain_runs_without_io_network_or_processes(self):
        c = ctx()
        c2 = ctx("improve")
        patches = [mock.patch("builtins.open", side_effect=AssertionError("open")),
                   mock.patch.object(socket, "socket", side_effect=AssertionError("socket")),
                   mock.patch.object(socket, "create_connection",
                                     side_effect=AssertionError("network")),
                   mock.patch.object(subprocess, "Popen", side_effect=AssertionError("proc")),
                   mock.patch.object(subprocess, "run", side_effect=AssertionError("run")),
                   mock.patch.object(os, "system", side_effect=AssertionError("system")),
                   mock.patch.object(os, "remove", side_effect=AssertionError("remove")),
                   mock.patch.object(os, "mkdir", side_effect=AssertionError("mkdir")),
                   mock.patch.object(os, "listdir", side_effect=AssertionError("listdir"))]
        for p in patches:
            p.start()
        try:
            for cc in (c, c2):
                r = check900(cc["auth"], cc["scope"], *cc["chain"], cc["vres"], cc["policy"],
                             cc["approval"], cc["avres"], cc["decision"], cc["dres"])
                self.assertEqual(r["status"], "valid")
                self.assertTrue(validate900(r)["valid"])
                self.assertTrue(validate897(cc["dres"])["valid"])
        finally:
            for p in patches:
                p.stop()

    def test_running_the_chain_does_not_change_the_working_tree(self):
        def fingerprint():
            entries = []
            for base, dirs, files in os.walk(os.path.join(ROOT, "autonomy")):
                dirs[:] = sorted(d for d in dirs if d != "__pycache__")
                for name in sorted(files):
                    if not name.endswith(".pyc"):
                        entries.append((name, os.stat(os.path.join(base, name)).st_mtime_ns))
            return entries
        before = fingerprint()
        for op in OPS:
            run(op)
        self.assertEqual(fingerprint(), before)


class Section17StaticSafetyTests(unittest.TestCase):
    BANNED_IMPORTS = {
        "os", "sys", "subprocess", "socket", "http", "urllib", "requests", "shutil", "pathlib",
        "ctypes", "importlib", "threading", "multiprocessing", "asyncio", "sqlite3", "pickle",
        "shelve", "marshal", "random", "time", "datetime", "json", "anthropic", "openai",
        "tempfile", "glob", "io", "ast", "types", "inspect", "builtins",
        "runpy", "code", "codeop", "zipfile", "tarfile", "ssl", "smtplib", "ftplib"}
    # "re" and "copy" are deliberately allowed: pure in-memory helpers (re.compile of a label
    # regex in Prompt 898 / 899, copy.deepcopy in Prompt 895). A bare compile() stays banned.
    BANNED_CALLS = {"open", "exec", "eval", "compile", "__import__", "input", "system", "popen",
                    "run", "Popen", "write", "writelines", "remove", "unlink", "rmdir", "mkdir",
                    "makedirs", "rename", "getattr", "setattr", "delattr", "globals", "locals",
                    "vars", "dump", "dumps", "load", "loads", "import_module", "urlopen",
                    "connect", "send", "post", "print"}

    @classmethod
    def setUpClass(cls):
        cls.sources = {}
        cls.trees = {}
        for path in SECTION17_FILES:
            with open(path, "r", encoding="utf-8") as handle:
                cls.sources[path] = handle.read()
            cls.trees[path] = ast.parse(cls.sources[path])

    def each(self):
        for path in SECTION17_FILES:
            yield os.path.basename(path), self.trees[path], self.sources[path]

    def test_section17_file_set_is_the_expected_eight(self):
        self.assertEqual(sorted(os.path.basename(p) for p in SECTION17_FILES), [
            "__init__.py", "approval_authority_scope.py", "approval_authority_source.py",
            "approval_scope_context_validation.py", "implementation_approval_decision.py",
            "implementation_approval_decision_validation.py",
            "implementation_approval_request.py", "implementation_permission_policy.py"])

    def test_no_filesystem_network_process_or_ai_imports(self):
        for name, tree, _ in self.each():
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(alias.name.split(".")[0], self.BANNED_IMPORTS,
                                         (name, alias.name))
                if isinstance(node, ast.ImportFrom):
                    self.assertNotIn((node.module or "").split(".")[0], self.BANNED_IMPORTS,
                                     (name, node.module))

    def test_imports_are_only_re_copy_or_package_capabilities_or_autonomy(self):
        for name, tree, _ in self.each():
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertIn(alias.name, ("re", "copy"), name)
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    self.assertTrue(node.level == 1 or module.startswith("capabilities."),
                                    (name, module, node.level))

    def test_no_exec_eval_compile_or_dynamic_calls(self):
        for name, tree, _ in self.each():
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    called = func.id if isinstance(func, ast.Name) else \
                        func.attr if isinstance(func, ast.Attribute) else None
                    if (called == "compile" and isinstance(func, ast.Attribute)
                            and isinstance(func.value, ast.Name) and func.value.id == "re"):
                        continue
                    self.assertNotIn(called, self.BANNED_CALLS, (name, called))

    def test_no_dynamic_attribute_loading(self):
        for name, tree, source in self.each():
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    self.assertNotIn(node.attr, ("__dict__", "__class__", "__globals__",
                                                 "__code__", "__builtins__", "__getattr__",
                                                 "__getattribute__", "__subclasses__"),
                                     (name, node.attr))
                if isinstance(node, ast.FunctionDef):
                    self.assertNotIn(node.name, ("__getattr__", "__getattribute__"), name)
            self.assertNotIn("importlib", source, name)
            self.assertNotIn("__import__", source, name)

    def test_no_external_ai_network_or_persistence(self):
        self._no_external_ai_api_or_network_references()
        self._no_persistence_or_file_writing()

    def _no_external_ai_api_or_network_references(self):
        for name, _, source in self.each():
            lowered = source.lower()
            for needle in ("anthropic", "openai", "import requests", "urllib", "http.client",
                           "socket.", "api_key", "bearer ", "https://", "http://"):
                self.assertNotIn(needle, lowered, (name, needle))

    def _no_persistence_or_file_writing(self):
        for name, tree, source in self.each():
            for needle in ("pickle", "sqlite3", "shelve", "json.dump", ".write(", "open(",
                           "os.remove", "shutil", "tempfile", "memory_write"):
                self.assertNotIn(needle, source, (name, needle))
            for node in ast.walk(tree):
                self.assertNotIsInstance(node, (ast.Global, ast.Nonlocal), name)

    def test_no_code_generation_self_modification_or_automatic_implementation(self):
        self._no_code_generation_or_self_modification()
        self._no_automatic_implementation_or_execution_calls()

    def _no_code_generation_or_self_modification(self):
        for name, tree, source in self.each():
            for needle in ("exec(", "eval(", "types.FunctionType", "__code__",
                           "setattr(", "sys.modules", "importlib", "ast.parse", "inspect.",
                           "monkeypatch", "reload("):
                self.assertNotIn(needle, source, (name, needle))
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        self.assertNotIsInstance(target, ast.Attribute, name)

    def _no_automatic_implementation_or_execution_calls(self):
        for name, tree, _ in self.each():
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    called = func.id if isinstance(func, ast.Name) else \
                        func.attr if isinstance(func, ast.Attribute) else ""
                    self.assertFalse(called.lower().startswith(
                        ("execute", "implement", "apply", "deploy", "install", "launch",
                         "generate", "patch", "commit")), (name, called))

    def test_no_permission_flag_is_ever_set_to_true(self):
        flags = set(PERMISSION_FLAGS) | {"approved", "authorized", "approval_granted"}
        for name, tree, _ in self.each():
            for node in ast.walk(tree):
                if isinstance(node, ast.Dict):
                    for key, value in zip(node.keys, node.values):
                        if isinstance(key, ast.Constant) and key.value in flags:
                            self.assertFalse(isinstance(value, ast.Constant)
                                             and value.value is True, (name, key.value))
                if isinstance(node, ast.keyword) and node.arg in flags:
                    self.assertFalse(isinstance(node.value, ast.Constant)
                                     and node.value.value is True, (name, node.arg))
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Subscript) and isinstance(
                                target.slice, ast.Constant) and target.slice.value in flags:
                            self.assertFalse(isinstance(node.value, ast.Constant)
                                             and node.value.value is True, name)
                        if isinstance(target, ast.Name) and target.id in flags:
                            self.assertFalse(isinstance(node.value, ast.Constant)
                                             and node.value.value is True, name)

    def test_no_hidden_approval_or_grant_path_and_approval_words_are_only_rejected_vocabulary(self):
        self._no_hidden_approval_or_grant_path()
        self._approval_words_appear_only_as_rejected_vocabulary()

    def _no_hidden_approval_or_grant_path(self):
        for name, tree, _ in self.each():
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    lowered = node.name.lower().lstrip("_")
                    for word in ("grant", "approve", "authorize", "authorise", "permit",
                                 "allow", "execute", "enable"):
                        self.assertNotIn(word, lowered, (name, node.name))
        for module in SECTION17_MODULES:
            for attr in dir(module):
                if attr.startswith("STATUS_") or attr.endswith("STATUSES"):
                    value = getattr(module, attr)
                    values = value if isinstance(value, tuple) else (value,)
                    for status in values:
                        for word in ("approved", "authorized", "granted", "allowed",
                                     "permitted"):
                            self.assertNotIn(word, str(status), (module.__name__, attr))

    def _approval_words_appear_only_as_rejected_vocabulary(self):
        # 'approved' may appear only in Prompt 897 / 900 and as a REJECTED label, never as a
        # produced status or value.
        for path in SECTION17_FILES:
            tree = self.trees[path]
            for node in ast.walk(tree):
                if isinstance(node, ast.Dict):
                    for key, value in zip(node.keys, node.values):
                        if isinstance(value, ast.Constant) and isinstance(value.value, str):
                            self.assertNotIn(value.value, ("approved", "authorized",
                                                           "granted"), path)
                if isinstance(node, ast.Return) and isinstance(node.value, ast.Constant):
                    self.assertNotIn(node.value.value, ("approved", "authorized", "granted"))

    def test_module_dependencies_only_point_upstream(self):
        order = ["implementation_permission_policy", "implementation_approval_request",
                 "implementation_approval_decision",
                 "implementation_approval_decision_validation", "approval_authority_source",
                 "approval_authority_scope", "approval_scope_context_validation"]
        for path in SECTION17_FILES:
            name = os.path.basename(path)[:-3]
            if name not in order:
                continue
            for node in ast.walk(self.trees[path]):
                if isinstance(node, ast.ImportFrom) and node.level == 1:
                    dependency = node.module
                    self.assertLess(order.index(dependency), order.index(name),
                                    (name, dependency))

    def test_no_section17_module_is_referenced_by_section16_or_other_packages(self):
        names = [os.path.basename(p)[:-3] for p in SECTION17_FILES
                 if not p.endswith("__init__.py")]
        for package in ("capabilities",):
            folder = os.path.join(ROOT, package)
            for fname in sorted(os.listdir(folder)):
                if fname.endswith(".py"):
                    with open(os.path.join(folder, fname), encoding="utf-8") as handle:
                        text = handle.read()
                    self.assertNotIn("autonomy", text, fname)
                    for module_name in names:
                        self.assertNotIn(module_name, text, (fname, module_name))


class FrozenProductionTreeTests(unittest.TestCase):
    """Section 16 and Prompt 894-900 production modules equal the Prompt 900 manifest."""

    @classmethod
    def setUpClass(cls):
        with open(MANIFEST_900, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        cls.entries = {e["path"]: e for e in manifest["files"]}

    def _sha(self, rel):
        with open(os.path.join(PROJECT, rel), "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()

    def test_manifest_900_exists_and_prompt900_artifacts_are_unchanged(self):
        self._manifest_900_exists_and_lists_the_modules()
        self._prompt900_checkpoint_and_doc_are_unchanged()

    def _manifest_900_exists_and_lists_the_modules(self):
        self.assertTrue(os.path.isfile(MANIFEST_900))
        self.assertIn("app/src/main/python/autonomy/approval_scope_context_validation.py",
                      self.entries)

    def test_section17_production_modules_are_unchanged_since_prompt900(self):
        for path in SECTION17_FILES:
            rel = os.path.relpath(path, PROJECT).replace(os.sep, "/")
            self.assertIn(rel, self.entries, rel)
            self.assertEqual(self._sha(rel), self.entries[rel]["sha256"], rel)

    def test_section16_production_modules_are_unchanged_since_prompt900(self):
        prefix = "app/src/main/python/capabilities/"
        checked = [rel for rel in self.entries if rel.startswith(prefix)
                   and rel.endswith(".py")]
        self.assertGreaterEqual(len(checked), 17)
        for rel in checked:
            self.assertEqual(self._sha(rel), self.entries[rel]["sha256"], rel)

    def _prompt900_checkpoint_and_doc_are_unchanged(self):
        for rel in ("app/src/main/python/tests/test_approval_scope_context_validation_prompt900.py",
                    "docs/approval_scope_context_validation_prompt900.md",
                    "docs/section16_final_checkpoint_prompt893.md"):
            self.assertEqual(self._sha(rel), self.entries[rel]["sha256"], rel)


class DocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(DOC, "r", encoding="utf-8") as handle:
            cls.text = handle.read()

    def test_doc_exists_and_states_the_controlled_autonomy_invariants(self):
        self._doc_exists()
        self._doc_states_the_controlled_autonomy_invariants()

    def _doc_exists(self):
        self.assertTrue(os.path.isfile(DOC))

    def _doc_states_the_controlled_autonomy_invariants(self):
        lowered = self.text.lower()
        for needle in (
                "controlled-autonomy foundation", "not autonomous execution",
                "approval authority is descriptive", "approval request is a request",
                "pending_approval", "implementation permission remains false",
                "execution permission remains false", "implementation never starts",
                "execution never occurs", "section 16 remains unchanged",
                "prompt 900 remains unchanged",
                "no automatic self-modification or execution mechanism"):
            self.assertIn(needle, lowered, needle)

    def test_doc_names_the_chain_and_fields(self):
        for needle in ("Prompt 894", "Prompt 895", "Prompt 896", "Prompt 897", "Prompt 898",
                       "Prompt 899", "Prompt 900", "approval_capable", "improve_or_conflict",
                       "implementation_allowed", "execution_allowed", "implementation_started",
                       "executed", "context_mismatch", "unsupported_status"):
            self.assertIn(needle, self.text, needle)


if __name__ == "__main__":
    unittest.main()
