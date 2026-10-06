"""
Prompt 894 - Section 17 (Controlled Autonomy): implementation permission policy.

Deterministic, read-only tests of autonomy/implementation_permission_policy.py. The policy only
states whether a validated implementation request MAY BE CONSIDERED for a future controlled
approval step. "eligible" is not implementation permission and not execution permission.

Run (from app/src/main/python/):
    python -m unittest tests.test_implementation_permission_policy_prompt894 -v
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

from autonomy import implementation_permission_policy as pmod
from autonomy.implementation_permission_policy import (
    FLAGS, POLICY_KEYS, STATUSES, build_implementation_permission_policy as build,
    validate_implementation_permission_policy as validate)
from capabilities.capability_definition_candidate import (
    build_capability_definition_candidate as build_candidate)
from capabilities.capability_definition_readiness import (
    evaluate_capability_definition_readiness as evaluate_readiness)
from capabilities.capability_evolution_analysis import analyze_capability_evolution as analyze
from capabilities.capability_evolution_plan import build_capability_evolution_plan as build_plan
from capabilities.capability_evolution_proposal import (
    build_capability_evolution_proposal as build_proposal)
from capabilities.capability_evolution_request import (
    build_capability_evolution_request as build_request)
from capabilities.capability_evolution_specification import (
    build_capability_evolution_specification as build_spec)
from capabilities.capability_implementation_blueprint import (
    build_capability_implementation_blueprint as build_blueprint)
from capabilities.capability_implementation_blueprint_validation import (
    validate_capability_implementation_blueprint_context as check887)
from capabilities.capability_implementation_boundary import (
    evaluate_capability_implementation_boundary as evaluate890)
from capabilities.capability_implementation_contract import (
    build_capability_implementation_contract as build_contract,
    validate_capability_implementation_contract as validate_contract)
from capabilities.capability_implementation_contract_readiness import (
    evaluate_capability_implementation_contract_readiness as evaluate889)
from capabilities.capability_implementation_design import (
    build_capability_implementation_design as build_design)
from capabilities.capability_implementation_design_validation import (
    validate_capability_implementation_design_context as check885)
from capabilities.capability_implementation_request import (
    build_capability_implementation_request as build_impl_request)
from capabilities.capability_implementation_request_validation import (
    validate_capability_implementation_request_context as check892)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_PATH = os.path.join(ROOT, "autonomy", "implementation_permission_policy.py")
DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(ROOT)))),
                   "docs", "section17_implementation_permission_policy_prompt894.md")

(REQUEST, ANALYSIS, SPEC, PLAN, PROPOSAL, CANDIDATE, READINESS, DESIGN, V885, BLUEPRINT, B887,
 CONTRACT, CREPORT, R889, BOUNDARY, IMPL) = range(16)
NAMES = ["request", "analysis", "spec", "plan", "proposal", "candidate", "readiness", "design",
         "v885", "blueprint", "b887", "contract", "creport", "r889", "boundary", "impl_request"]

# index of a broken chain object -> policy status expected from the policy
EXPECTED_INVALID = {
    REQUEST: "invalid_request", ANALYSIS: "invalid_definition_readiness",
    SPEC: "invalid_definition_readiness", PLAN: "invalid_definition_readiness",
    PROPOSAL: "invalid_definition_readiness", CANDIDATE: "invalid_definition_readiness",
    READINESS: "invalid_definition_readiness", DESIGN: "invalid_contract",
    V885: "invalid_contract", BLUEPRINT: "invalid_contract", B887: "invalid_contract",
    CONTRACT: "invalid_contract", CREPORT: "invalid_contract",
    R889: "invalid_contract_readiness", BOUNDARY: "invalid_boundary",
    IMPL: "invalid_request"}


def req(**over):
    d = {"version": "1", "request_id": "evo_001", "operation": "create",
         "capability_name": "text_summarizer", "goal": "Summarize short documents.",
         "inputs": ["z_input", "a_input"], "outputs": ["z_out", "a_out"],
         "constraints": ["Second.", "First.", "Second."], "requested_by": "developer",
         "execution_allowed": False}
    d.update(over)
    return d


def desc(name="text_summarizer", **over):
    d = {"name": name, "version": 1, "purpose": "Summarize text.", "inputs": ["document_text"],
         "outputs": ["summary_text"], "constraints": ["Pure Python only."], "enabled": True}
    d.update(over)
    return d


def full(op="create", caps=None):
    """The 16 chain objects: request .. boundary (890), implementation request (891)."""
    if caps is None:
        caps = [desc()] if op == "improve" else []
    request = build_request(req(operation=op))["evolution_request"]
    analysis = analyze(request, caps)
    spec = build_spec(request, analysis, specification_id="spec_001")["specification"]
    plan = build_plan(request, analysis, spec, "plan_001")["plan"]
    proposal = build_proposal(request, analysis, spec, plan, "prop_001")["proposal"]
    candidate = build_candidate(request, analysis, spec, plan, proposal, "cand_001")["candidate"]
    readiness = evaluate_readiness(request, analysis, spec, plan, proposal, candidate)
    design = build_design(request, analysis, spec, plan, proposal, candidate, readiness,
                          "design_001")["design"]
    chain = [request, analysis, spec, plan, proposal, candidate, readiness, design]
    vresult = check885(*chain)
    blueprint = build_blueprint(*chain, vresult, "bp_001")["blueprint"]
    bresult = check887(*chain, vresult, blueprint)
    contract = build_contract(*chain, vresult, blueprint, bresult, "ct_001")["contract"]
    creport = validate_contract(contract)
    r889 = evaluate889(*chain, vresult, blueprint, bresult, contract, creport)
    base = chain + [vresult, blueprint, bresult, contract, creport, r889]
    boundary = evaluate890(*base)
    base = base + [boundary]
    return base + [build_impl_request(*base, "ir_001")["request"]]


_BASE = {}


def base_chain(op="create"):
    if op not in _BASE:
        _BASE[op] = full(op)
    return copy.deepcopy(_BASE[op])


def derive(chain):
    return check892(*chain)


_DERIVE = object()


def policy_of(chain, vres=_DERIVE, pid="pol_001", state=None):
    if vres is _DERIVE:
        vres = derive(chain)
    return build(*chain, vres, pid, state)


def ok(op="create"):
    chain = base_chain(op)
    return policy_of(chain)


def codes(report):
    return [e["code"] for e in report["errors"]]


def conflict_chain(tail):
    request = req(operation="create")
    analysis = analyze(request, [desc()])
    spec = build_spec(request, analysis, specification_id="spec_001")["specification"]
    return [request, analysis, spec] + tail


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
    raise AssertionError("forbidden operation attempted while building the policy")


class EligibleTests(unittest.TestCase):
    def test_valid_create_is_eligible(self):
        p = ok("create")
        self.assertEqual(p["status"], "eligible")
        self.assertIs(p["eligible"], True)
        self.assertEqual(p["operation"], "create")

    def test_valid_improve_is_eligible(self):
        p = ok("improve")
        self.assertEqual(p["status"], "eligible")
        self.assertIs(p["eligible"], True)
        self.assertEqual(p["operation"], "improve")

    def test_exact_keys_and_order(self):
        for op in ("create", "improve"):
            self.assertEqual(list(ok(op)), list(POLICY_KEYS))
        self.assertEqual(len(POLICY_KEYS), 13)

    def test_identity_comes_from_trusted_chain(self):
        p = ok()
        self.assertEqual(p["policy_id"], "pol_001")
        self.assertEqual(p["request_id"], "evo_001")
        self.assertEqual(p["implementation_request_id"], "ir_001")
        self.assertEqual(p["capability_name"], "text_summarizer")

    def test_eligible_policy_validates(self):
        for op in ("create", "improve"):
            report = validate(ok(op))
            self.assertTrue(report["valid"], report)
            self.assertIs(report["execution_allowed"], False)
            self.assertIs(report["executed"], False)

    def test_status_list_is_exactly_the_specified_twelve(self):
        self.assertEqual(set(STATUSES), {
            "eligible", "ineligible", "blocked", "unsupported", "invalid_request",
            "invalid_request_validation", "invalid_boundary", "invalid_contract",
            "invalid_contract_readiness", "invalid_definition_readiness", "context_mismatch",
            "validation_error"})
        self.assertEqual(len(STATUSES), 12)

    def test_supported_operations_are_create_and_improve_only(self):
        self.assertEqual(pmod.SUPPORTED_OPERATIONS, ("create", "improve"))
        self.assertNotIn("improve_or_conflict", pmod.SUPPORTED_OPERATIONS)
        self.assertNotIn("improve_or_conflict", [a for _, a in pmod.SUPPORTED])


class NoPermissionTests(unittest.TestCase):
    def test_eligible_is_not_implementation_permission(self):
        for op in ("create", "improve"):
            p = ok(op)
            self.assertIs(p["eligible"], True)
            self.assertIs(p["implementation_allowed"], False)
            self.assertIs(p["implementation_started"], False)
            self.assertNotEqual(p["eligible"], p["implementation_allowed"])

    def test_eligible_is_not_execution_permission(self):
        for op in ("create", "improve"):
            p = ok(op)
            self.assertIs(p["eligible"], True)
            self.assertIs(p["execution_allowed"], False)
            self.assertIs(p["executed"], False)
            self.assertNotEqual(p["eligible"], p["execution_allowed"])

    def test_eligible_with_implementation_allowed_true_fails(self):
        p = dict(ok(), implementation_allowed=True)
        report = validate(p)
        self.assertFalse(report["valid"])
        self.assertIn("invalid_flag", codes(report))

    def test_eligible_with_execution_allowed_true_fails(self):
        report = validate(dict(ok(), execution_allowed=True))
        self.assertFalse(report["valid"])
        self.assertIn("invalid_flag", codes(report))

    def test_eligible_with_implementation_started_true_fails(self):
        report = validate(dict(ok(), implementation_started=True))
        self.assertFalse(report["valid"])
        self.assertIn("invalid_flag", codes(report))

    def test_eligible_with_executed_true_fails(self):
        report = validate(dict(ok(), executed=True))
        self.assertFalse(report["valid"])
        self.assertIn("invalid_flag", codes(report))

    def test_every_status_keeps_all_flags_false(self):
        cases = [ok("create"), ok("improve"), build(), build(policy_id="p_1")]
        for i in range(16):
            chain = base_chain()
            chain[i] = None
            cases.append(policy_of(chain))
        cases.append(policy_of(conflict_chain(base_chain()[3:])))
        cases.append(policy_of(base_chain(), state=dict.fromkeys(FLAGS, True)))
        for p in cases:
            for flag in FLAGS:
                self.assertIs(p[flag], False, (p["status"], flag))
            self.assertTrue(validate(p)["valid"], (p["status"], validate(p)))

    def test_eligible_flag_must_match_status(self):
        self.assertFalse(validate(dict(ok(), eligible=False))["valid"])
        self.assertFalse(validate(dict(ok(), status="blocked", reason="blocked"))["valid"])


class UnsupportedTests(unittest.TestCase):
    def test_improve_or_conflict_is_unsupported(self):
        for tail in (base_chain()[3:], base_chain("improve")[3:], [None] * 13):
            chain = conflict_chain(tail)
            self.assertEqual(derive(chain)["analysis_status"], "improve_or_conflict")
            p = policy_of(chain, vres=derive(chain))
            self.assertEqual(p["status"], "unsupported")
            self.assertIs(p["eligible"], False)
            self.assertIsNone(p["implementation_request_id"])
            self.assertEqual(p["request_id"], "evo_001")
            self.assertTrue(validate(p)["valid"], validate(p))

class InvalidChainTests(unittest.TestCase):
    def test_each_broken_object_maps_to_its_status(self):
        for i in range(16):
            for bad in (None, {}, [], "x"):
                chain = base_chain()
                chain[i] = bad
                p = policy_of(chain, vres=derive(base_chain()))
                self.assertEqual(p["status"], EXPECTED_INVALID[i], (NAMES[i], bad))
                self.assertIs(p["eligible"], False)
                self.assertTrue(validate(p)["valid"], (NAMES[i], validate(p)))

    def test_invalid_implementation_request(self):
        chain = base_chain()
        chain[IMPL] = dict(chain[IMPL], version="1")
        p = policy_of(chain, vres=derive(base_chain()))
        self.assertEqual(p["status"], "invalid_request")
        self.assertIsNone(p["request_id"])

    def test_invalid_boundary(self):
        chain = base_chain()
        chain[BOUNDARY] = dict(chain[BOUNDARY], implementation_allowed=True)
        self.assertEqual(policy_of(chain, vres=derive(base_chain()))["status"],
                         "invalid_boundary")

    def test_invalid_contract(self):
        chain = base_chain()
        chain[CONTRACT] = dict(chain[CONTRACT], version="1")
        self.assertEqual(policy_of(chain, vres=derive(base_chain()))["status"],
                         "invalid_contract")

    def test_invalid_contract_readiness(self):
        chain = base_chain()
        chain[R889] = dict(chain[R889], ready=False)
        self.assertEqual(policy_of(chain, vres=derive(base_chain()))["status"],
                         "invalid_contract_readiness")

    def test_invalid_definition_readiness(self):
        chain = base_chain()
        chain[READINESS] = dict(chain[READINESS], ready=False)
        self.assertEqual(policy_of(chain, vres=derive(base_chain()))["status"],
                         "invalid_definition_readiness")

class ForgedTests(unittest.TestCase):
    def test_forged_implementation_request(self):
        chain = base_chain()
        chain[IMPL] = dict(chain[IMPL], purpose="A different purpose.")
        p = policy_of(chain, vres=derive(base_chain()))
        self.assertEqual(p["status"], "context_mismatch")
        self.assertIs(p["eligible"], False)

    def test_forged_validation_result(self):
        chain = base_chain()
        good = derive(chain)
        forged = dict(good, plan_id="plan_999")
        p = policy_of(chain, vres=forged)
        self.assertEqual(p["status"], "context_mismatch")
        self.assertIs(p["eligible"], False)
        self.assertTrue(validate(p)["valid"])

    def test_forged_boundary(self):
        chain = base_chain()
        chain[BOUNDARY] = dict(chain[BOUNDARY], plan_id="plan_999")
        p = policy_of(chain, vres=derive(base_chain()))
        self.assertEqual(p["status"], "context_mismatch")

    def test_forged_contract_readiness(self):
        chain = base_chain()
        chain[R889] = dict(chain[R889], plan_id="plan_999")
        p = policy_of(chain, vres=derive(base_chain()))
        self.assertEqual(p["status"], "context_mismatch")

class MismatchTests(unittest.TestCase):
    def test_request_id_mismatch(self):
        chain = base_chain()
        p = policy_of(chain, vres=dict(derive(chain), request_id="evo_999"))
        self.assertEqual(p["status"], "context_mismatch")

    def test_capability_name_mismatch(self):
        chain = base_chain()
        p = policy_of(chain, vres=dict(derive(chain), capability_name="other_capability"))
        self.assertEqual(p["status"], "context_mismatch")

    def test_operation_mismatch(self):
        chain = base_chain()
        p = policy_of(chain, vres=dict(derive(chain), operation="improve"))
        self.assertIn(p["status"], ("invalid_request_validation", "context_mismatch"))
        self.assertIs(p["eligible"], False)

    def test_implementation_request_id_mismatch(self):
        chain = base_chain()
        p = policy_of(chain, vres=dict(derive(chain), implementation_request_id="ir_999"))
        self.assertEqual(p["status"], "context_mismatch")

    def test_validation_result_from_other_operation_chain(self):
        chain = base_chain("create")
        p = policy_of(chain, vres=derive(base_chain("improve")))
        self.assertEqual(p["status"], "context_mismatch")
        self.assertIs(p["eligible"], False)

    def test_invalid_validation_results(self):
        chain = base_chain()
        good = derive(chain)
        bad_values = [None, {}, [], "valid", dict(good, valid=False),
                      dict(good, status="context_mismatch", valid=False, reason="context_mismatch"),
                      dict(good, version="1"), dict(good, extra=1)]
        missing = dict(good)
        del missing["plan_id"]
        bad_values.append(missing)
        for bad in bad_values:
            p = policy_of(chain, vres=bad)
            self.assertEqual(p["status"], "invalid_request_validation", bad)
            self.assertIs(p["eligible"], False)
            self.assertTrue(validate(p)["valid"], validate(p))

class BlockedTests(unittest.TestCase):
    def test_each_existing_grant_blocks(self):
        for flag in FLAGS:
            state = dict.fromkeys(FLAGS, False)
            state[flag] = True
            p = policy_of(base_chain(), state=state)
            self.assertEqual(p["status"], "blocked", flag)
            self.assertIs(p["eligible"], False)
            self.assertEqual(p["implementation_request_id"], "ir_001")
            for f in FLAGS:
                self.assertIs(p[f], False)
            self.assertTrue(validate(p)["valid"], validate(p))

    def test_all_false_state_is_still_eligible(self):
        p = policy_of(base_chain(), state=dict.fromkeys(FLAGS, False))
        self.assertEqual(p["status"], "eligible")

    def test_malformed_permission_state_is_validation_error(self):
        bad_states = ["x", [], {}, dict.fromkeys(FLAGS, 0), dict.fromkeys(FLAGS, None),
                      dict(dict.fromkeys(FLAGS, False), extra=False),
                      {k: False for k in FLAGS[:3]}]
        for bad in bad_states:
            p = policy_of(base_chain(), state=bad)
            self.assertEqual(p["status"], "validation_error", bad)
            self.assertIs(p["eligible"], False)
            self.assertTrue(validate(p)["valid"])

    def test_permission_state_is_not_modified(self):
        state = dict.fromkeys(FLAGS, True)
        before = copy.deepcopy(state)
        policy_of(base_chain(), state=state)
        self.assertEqual(state, before)

class IneligibleTests(unittest.TestCase):
    def test_outside_boundary_fails_closed(self):
        with mock.patch.object(pmod, "SUPPORTED", ()):
            p = ok("create")
        self.assertEqual(p["status"], "ineligible")
        self.assertIs(p["eligible"], False)
        self.assertEqual(p["implementation_request_id"], "ir_001")
        self.assertTrue(validate(p)["valid"], validate(p))
        for f in FLAGS:
            self.assertIs(p[f], False)


class PolicyIdTests(unittest.TestCase):
    def test_invalid_policy_ids_are_rejected(self):
        for bad in (None, "", " ", 1, True, [], {}, "x" * 65, "bad\nid"):
            chain = base_chain()
            p = build(*chain, derive(chain), bad)
            self.assertEqual(p["status"], "validation_error", repr(bad))
            self.assertIsNone(p["policy_id"])
            self.assertIs(p["eligible"], False)
            self.assertTrue(validate(p)["valid"])

    def test_valid_policy_ids_are_carried(self):
        for good in ("p", "pol_001", "x" * 64):
            self.assertEqual(policy_of(base_chain(), pid=good)["policy_id"], good)

    def test_validator_rejects_bad_policy_id(self):
        for bad in (None, "", 5, "x" * 65):
            report = validate(dict(ok(), policy_id=bad))
            self.assertFalse(report["valid"], bad)
            self.assertIn("invalid_policy_id", codes(report))

class ValidatorShapeTests(unittest.TestCase):
    def test_wrong_version_type(self):
        for bad in (True, "1", 1.0, 2, 0, None):
            report = validate(dict(ok(), version=bad))
            self.assertFalse(report["valid"], bad)
            self.assertIn("invalid_version", codes(report))

    def test_missing_key(self):
        for key in POLICY_KEYS:
            p = ok()
            del p[key]
            report = validate(p)
            self.assertFalse(report["valid"], key)
            self.assertIn("missing_key", codes(report))

    def test_extra_key(self):
        report = validate(dict(ok(), extra="x"))
        self.assertFalse(report["valid"])
        self.assertIn("unexpected_key", codes(report))

    def test_wrong_status(self):
        for bad in ("valid", "ready", "ELIGIBLE", "", None, 1, "improve_or_conflict"):
            report = validate(dict(ok(), status=bad))
            self.assertFalse(report["valid"], bad)

    def test_non_dict_policy(self):
        for bad in (None, [], "x", 1, ()):
            self.assertIn("policy_not_dict", codes(validate(bad)))
        self.assertFalse(validate()["valid"])

    def test_reason_must_equal_status(self):
        self.assertIn("invalid_reason", codes(validate(dict(ok(), reason="other"))))

    def test_identity_rules(self):
        self.assertIn("invalid_identity", codes(validate(dict(ok(), request_id=None))))
        self.assertIn("invalid_identity", codes(validate(dict(ok(), operation="improve_or_conflict"))))
        self.assertIn("invalid_identity", codes(validate(dict(ok(), implementation_request_id=None))))
        p = build()
        self.assertFalse(validate(dict(p, request_id="evo_001"))["valid"])

    def test_validator_report_is_fresh_and_never_grants(self):
        a, b = validate(ok()), validate(ok())
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIs(a["execution_allowed"], False)
        self.assertIs(a["executed"], False)

class DeterminismTests(unittest.TestCase):
    def test_repeated_evaluation_is_identical(self):
        for op in ("create", "improve"):
            runs = [json.dumps(policy_of(base_chain(op)), sort_keys=False) for _ in range(5)]
            self.assertEqual(len(set(runs)), 1)

    def test_fresh_object_every_call(self):
        chain = base_chain()
        vres = derive(chain)
        a, b = build(*chain, vres, "pol_001"), build(*chain, vres, "pol_001")
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        a["status"] = "tampered"
        self.assertEqual(build(*chain, vres, "pol_001")["status"], "eligible")

    def test_independent_of_time_and_randomness(self):
        with mock.patch("time.time", forbidden), mock.patch("random.random", forbidden):
            self.assertEqual(ok()["status"], "eligible")

class SafetyTests(unittest.TestCase):
    def test_inputs_are_not_mutated(self):
        chain = base_chain()
        vres = derive(chain)
        snapshot = copy.deepcopy((chain, vres))
        build(*chain, vres, "pol_001")
        self.assertEqual((chain, vres), snapshot)

    def test_mutation_attempts_on_result_do_not_leak(self):
        p = ok()
        p["implementation_allowed"] = True
        self.assertFalse(validate(p)["valid"])
        self.assertIs(ok()["implementation_allowed"], False)

    def test_no_filesystem_network_or_process_activity(self):
        chain = base_chain()
        vres = derive(chain)
        before = tree_fingerprint()
        with mock.patch("builtins.open", forbidden), \
                mock.patch.object(socket, "socket", forbidden), \
                mock.patch.object(socket, "create_connection", forbidden), \
                mock.patch.object(subprocess, "Popen", forbidden), \
                mock.patch.object(os, "system", forbidden), \
                mock.patch("builtins.exec", forbidden), \
                mock.patch("builtins.eval", forbidden), \
                mock.patch("builtins.compile", forbidden):
            self.assertEqual(build(*chain, vres, "pol_001")["status"], "eligible")
            self.assertTrue(validate(ok())["valid"])
        self.assertEqual(before, tree_fingerprint())

    def test_module_level_state_is_unchanged(self):
        def state():
            return {k: repr(v) for k, v in vars(pmod).items()
                    if isinstance(v, (list, dict, set, bytearray)) and not k.startswith("__")}
        before = state()
        ok()
        validate(ok())
        self.assertEqual(before, state())

    def test_never_raises_on_garbage(self):
        junk = [None, 1, "x", [], {}, object(), float("nan"), {"a": {"b": []}}]
        for value in junk:
            p = build(*([value] * 17), value)
            self.assertTrue(validate(p)["valid"], validate(p))
            self.assertIs(p["eligible"], False)
        self.assertTrue(validate(build(*([None] * 19)))["valid"])


class ForbiddenApiScanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(MODULE_PATH, "r", encoding="utf-8") as handle:
            cls.source = handle.read()
        cls.tree = ast.parse(cls.source)

    def test_imports_are_limited_to_capability_modules(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                self.fail("plain import statement: %r" % [a.name for a in node.names])
            if isinstance(node, ast.ImportFrom):
                self.assertTrue(node.module.startswith("capabilities."), node.module)
                self.assertEqual(node.level, 0)

    def test_no_forbidden_calls(self):
        banned = {"open", "exec", "eval", "compile", "__import__", "input", "print", "system",
                  "popen", "Popen", "run", "call", "urlopen", "setattr", "delattr", "getattr",
                  "globals", "locals", "vars"}
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
        self.assertEqual(public, ["build_implementation_permission_policy",
                                  "validate_implementation_permission_policy"])

    def test_section16_modules_are_not_modified_by_policy_module(self):
        for name in ("capability_implementation_request_validation",
                     "capability_implementation_boundary", "capability_implementation_request"):
            path = os.path.join(ROOT, "capabilities", name + ".py")
            with open(path, "r", encoding="utf-8") as handle:
                self.assertNotIn("implementation_permission_policy", handle.read())

    def test_autonomy_package_contains_the_policy_module(self):
        # Relaxed in Prompt 895: later Section 17 modules may join the package; the
        # Prompt 894 policy module and package marker must still be present.
        names = sorted(n for n in os.listdir(os.path.join(ROOT, "autonomy"))
                       if n != "__pycache__")
        for required in ("__init__.py", "implementation_permission_policy.py"):
            self.assertIn(required, names)
        self.assertTrue(all(n.endswith(".py") for n in names), names)


class DocumentationTests(unittest.TestCase):
    def test_doc_exists_and_states_the_invariants(self):
        self.assertTrue(os.path.isfile(DOC))
        with open(DOC, "r", encoding="utf-8") as handle:
            text = handle.read()
        for needle in ("eligible", "implementation_allowed", "execution_allowed",
                       "implementation_started", "executed", "improve_or_conflict",
                       "blocked", "unsupported", "create", "improve"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
