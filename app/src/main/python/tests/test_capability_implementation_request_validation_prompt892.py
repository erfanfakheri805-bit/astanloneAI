"""
Prompt 892 - capability implementation request validation focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_implementation_request_validation_prompt892 -v
"""

import ast
import copy
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities import capability_implementation_boundary as m890
from capabilities import capability_implementation_request as rmod
from capabilities.capability_definition_candidate import (
    build_capability_definition_candidate as build_candidate)
from capabilities.capability_definition_readiness import (
    evaluate_capability_definition_readiness as evaluate_readiness)
from capabilities.capability_evolution_analysis import analyze_capability_evolution as analyze
from capabilities.capability_evolution_plan import build_capability_evolution_plan as build_plan
from capabilities.capability_evolution_proposal import (
    build_capability_evolution_proposal as build_proposal)
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
    build_capability_implementation_request as build,
    validate_capability_implementation_request as validate891)
from capabilities import capability_implementation_request as m891
from capabilities import capability_implementation_request_validation as rmod
from capabilities.capability_implementation_request_validation import (
    validate_capability_implementation_request_context as check,
    validate_capability_implementation_request_validation_result as validate)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KEYS = ["version", "status", "valid", "implementation_request_id", "request_id",
        "capability_name", "operation", "analysis_status", "plan_id", "contract_id",
        "boundary_status", "reason"]
NAMES = ["request", "analysis", "spec", "plan", "proposal", "candidate", "readiness", "design",
         "v885", "blueprint", "b887", "contract", "creport", "r889", "boundary", "impl_request"]
EXPECTED_NONE = ["invalid_request", "invalid_analysis", "invalid_specification", "invalid_plan",
                 "invalid_proposal", "invalid_candidate", "invalid_readiness", "invalid_design",
                 "invalid_design_validation", "invalid_blueprint",
                 "invalid_blueprint_validation", "invalid_contract",
                 "invalid_contract_validation", "invalid_contract_readiness",
                 "invalid_boundary", "invalid_implementation_request"]


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


def full(op="create", caps=None, plan_id="plan_001", proposal_id="prop_001",
         candidate_id="cand_001", design_id="design_001", blueprint_id="bp_001",
         contract_id="ct_001", iid="ir_001", **req_over):
    """[request .. boundary result (890), implementation request (891)] - 16 objects."""
    if caps is None:
        caps = [desc()] if op == "improve" else []
    request = req(operation=op, **req_over)
    analysis = analyze(request, caps)
    spec = build_spec(request, analysis, specification_id="spec_001")["specification"]
    plan = build_plan(request, analysis, spec, plan_id)["plan"]
    proposal = build_proposal(request, analysis, spec, plan, proposal_id)["proposal"]
    candidate = build_candidate(request, analysis, spec, plan, proposal, candidate_id)["candidate"]
    readiness = evaluate_readiness(request, analysis, spec, plan, proposal, candidate)
    design = build_design(request, analysis, spec, plan, proposal, candidate, readiness,
                          design_id)["design"]
    chain = [request, analysis, spec, plan, proposal, candidate, readiness, design]
    vresult = check885(*chain)
    blueprint = build_blueprint(*chain, vresult, blueprint_id)["blueprint"]
    bresult = check887(*chain, vresult, blueprint)
    contract = build_contract(*chain, vresult, blueprint, bresult, contract_id)["contract"]
    creport = validate_contract(contract)
    r889 = evaluate889(*chain, vresult, blueprint, bresult, contract, creport)
    base = chain + [vresult, blueprint, bresult, contract, creport, r889]
    boundary = evaluate890(*base)
    base = base + [boundary]
    return base + [build(*base, iid)["request"]]


def swap(base, other, *indexes):
    out = list(base)
    for i in indexes:
        out[i] = other[i]
    return out


def run(chain):
    return check(*chain)


def ok(op="create"):
    return run(full(op))


def codes(result):
    return [e["code"] for e in result["errors"]]


def with_request(op="create", **changes):
    chain = full(op)
    chain[15] = dict(chain[15], **changes)
    return chain


class IntegerVersionTests(unittest.TestCase):
    def test_prompt884_design_version_still_integer(self):
        for op in ("create", "improve"):
            self.assertIs(type(full(op)[7]["version"]), int)

    def test_result_version_is_integer_one(self):
        for op in ("create", "improve"):
            r = ok(op)
            self.assertIs(type(r["version"]), int)
            self.assertEqual(r["version"], 1)

    def test_wrong_result_version_types_rejected(self):
        for bad in ("1", 1.0, True, None, 2, 0, [1], b"1"):
            r = ok()
            r["version"] = bad
            v = validate(r)
            self.assertFalse(v["valid"], repr(bad))
            self.assertIn("invalid_version", codes(v))

    def test_wrong_implementation_request_version_rejected(self):
        for bad in ("1", 1.0, True, None, 2):
            r = run(with_request(version=bad))
            self.assertEqual(r["status"], "invalid_implementation_request", repr(bad))


class HappyPathTests(unittest.TestCase):
    def test_valid_create(self):
        r = ok("create")
        self.assertEqual(r["status"], "valid")
        self.assertIs(r["valid"], True)
        self.assertEqual(r["operation"], "create")
        self.assertEqual(r["analysis_status"], "create_required")

    def test_valid_improve(self):
        r = ok("improve")
        self.assertEqual(r["status"], "valid")
        self.assertIs(r["valid"], True)
        self.assertEqual(r["operation"], "improve")
        self.assertEqual(r["analysis_status"], "improve_required")

    def test_result_keys_exact_and_ordered(self):
        for op in ("create", "improve"):
            r = ok(op)
            self.assertEqual(list(r), KEYS)
            self.assertEqual(len(r), 12)

    def test_valid_identity_populated(self):
        r = ok()
        self.assertEqual(r["implementation_request_id"], "ir_001")
        self.assertEqual(r["request_id"], "evo_001")
        self.assertEqual(r["capability_name"], "text_summarizer")
        self.assertEqual(r["plan_id"], "plan_001")
        self.assertEqual(r["contract_id"], "ct_001")
        self.assertEqual(r["boundary_status"], "ready")
        self.assertEqual(r["reason"], "valid")

    def test_caller_supplied_request_id_is_reported(self):
        r = run(full(iid="my.request-7"))
        self.assertEqual(r["status"], "valid")
        self.assertEqual(r["implementation_request_id"], "my.request-7")

    def test_valid_result_validates(self):
        for op in ("create", "improve"):
            v = validate(ok(op))
            self.assertTrue(v["valid"], v)
            self.assertIs(v["execution_allowed"], False)
            self.assertIs(v["executed"], False)

    def test_result_has_no_permission_fields(self):
        r = ok()
        for key in ("implementation_allowed", "execution_allowed", "executed",
                    "implementation_started"):
            self.assertNotIn(key, r)


class UpstreamTests(unittest.TestCase):
    def test_each_invalid_object_has_its_status(self):
        base = full()
        for i, expected in enumerate(EXPECTED_NONE):
            for bad in (None, {}, [], "x"):
                broken = list(base)
                broken[i] = bad
                r = run(broken)
                self.assertEqual(r["status"], expected, (NAMES[i], bad))
                self.assertIs(r["valid"], False)
                self.assertTrue(validate(r)["valid"], (NAMES[i], validate(r)))

    def test_invalid_validation_context(self):
        from capabilities import capability_implementation_boundary as m890
        with mock.patch.object(m890, "validate_capability_evolution_result",
                               return_value={"valid": False}):
            self.assertEqual(run(full())["status"], "invalid_validation")

    def test_invalid_boundary_not_ready_or_flags(self):
        from capabilities import capability_implementation_boundary as m890
        base = full()
        bad = m890._result("context_mismatch", base[0], "create_required")
        self.assertEqual(run(swap(base, [None] * 14 + [bad], 14))["status"],
                         "invalid_boundary")
        for key in ("implementation_allowed", "implementation_started", "execution_allowed",
                    "executed"):
            bad = dict(base[14], **{key: True})
            self.assertEqual(run(swap(base, [None] * 14 + [bad], 14))["status"],
                             "invalid_boundary", key)

    def test_invalid_contract_readiness_not_ready(self):
        from capabilities import capability_implementation_contract_readiness as m889
        base = full()
        bad = m889._result("not_ready", base[0], "create_required")
        self.assertEqual(run(swap(base, [None] * 13 + [bad], 13))["status"],
                         "invalid_contract_readiness")

    def test_invalid_contract_validation_shape(self):
        base = full()
        bad = {"valid": True, "errors": [], "execution_allowed": True, "executed": False}
        self.assertEqual(run(swap(base, [None] * 12 + [bad], 12))["status"],
                         "invalid_contract_validation")

    def test_upstream_results_carry_trusted_identity_only(self):
        base = full()
        broken = list(base)
        broken[3] = None
        r = run(broken)
        self.assertEqual(r["status"], "invalid_plan")
        self.assertEqual(r["request_id"], "evo_001")
        self.assertEqual(r["analysis_status"], "create_required")
        for key in ("implementation_request_id", "plan_id", "contract_id", "boundary_status"):
            self.assertIsNone(r[key])
        broken = list(base)
        broken[0] = None
        r = run(broken)
        for key in KEYS[3:11]:
            self.assertIsNone(r[key])
        broken = list(base)
        broken[1] = None
        r = run(broken)
        self.assertEqual(r["request_id"], "evo_001")
        self.assertIsNone(r["analysis_status"])

    def test_valid_only_when_whole_chain_valid(self):
        base = full()
        self.assertEqual(run(base)["status"], "valid")
        for i in range(16):
            broken = list(base)
            broken[i] = None
            self.assertNotEqual(run(broken)["status"], "valid", NAMES[i])


class ImplementationRequestTests(unittest.TestCase):
    def test_malformed_requests(self):
        for bad in (None, [], "x", 1, (), set()):
            r = run(swap(full(), [None] * 15 + [bad], 15))
            self.assertEqual(r["status"], "invalid_implementation_request", repr(bad))

    def test_missing_keys(self):
        for key in m891.FIELDS:
            chain = full()
            req891 = dict(chain[15])
            del req891[key]
            chain[15] = req891
            self.assertEqual(run(chain)["status"], "invalid_implementation_request", key)

    def test_extra_keys(self):
        for extra in ("status", "executed", "code"):
            chain = with_request(**{extra: True})
            self.assertEqual(run(chain)["status"], "invalid_implementation_request", extra)

    def test_invalid_ids(self):
        for bad in (None, "", 5, True, "x" * 65, "\n"):
            self.assertEqual(run(with_request(implementation_request_id=bad))["status"],
                             "invalid_implementation_request", repr(bad))

    def test_wrong_types(self):
        for key, bad in (("inputs", ("z_input",)), ("outputs", "x"), ("constraints", None),
                         ("purpose", 5), ("boundary_status", True), ("request_id", 7)):
            self.assertEqual(run(with_request(**{key: bad}))["status"],
                             "invalid_implementation_request", key)

    def test_invalid_boundary_status_in_request(self):
        for bad in ("not_ready", "", None, "Ready"):
            self.assertEqual(run(with_request(boundary_status=bad))["status"],
                             "invalid_implementation_request", repr(bad))

    def test_implementation_allowed_true_rejected(self):
        for bad in (True, 1, None, "False", 0):
            for op in ("create", "improve"):
                r = run(with_request(op, implementation_allowed=bad))
                self.assertEqual(r["status"], "invalid_implementation_request", (bad, op))
                self.assertIs(r["valid"], False)

    def test_execution_allowed_true_rejected(self):
        for bad in (True, 1, None, "False", 0):
            for op in ("create", "improve"):
                r = run(with_request(op, execution_allowed=bad))
                self.assertEqual(r["status"], "invalid_implementation_request", (bad, op))
                self.assertIs(r["valid"], False)

    def test_operation_status_inconsistency_in_request(self):
        self.assertEqual(run(with_request("create", analysis_status="improve_required"))[
            "status"], "invalid_implementation_request")
        self.assertEqual(run(with_request("improve", operation="create"))["status"],
                         "invalid_implementation_request")


class ContextMismatchTests(unittest.TestCase):
    def test_forged_request_from_other_chain(self):
        base = full()
        for kw in (dict(request_id="evo_002"), dict(capability_name="other_cap"),
                   dict(goal="Other goal."), dict(inputs=["q"]), dict(outputs=["q"]),
                   dict(constraints=["Other."]), dict(plan_id="plan_002"),
                   dict(contract_id="ct_002")):
            forged = full(**kw)[15]
            self.assertTrue(validate891(forged)["valid"], kw)
            r = run(swap(base, [None] * 15 + [forged], 15))
            self.assertEqual(r["status"], "context_mismatch", kw)
            self.assertIs(r["valid"], False)
            self.assertIsNone(r["implementation_request_id"])

    def test_each_edited_field_is_context_mismatch(self):
        edits = (("request_id", "evo_zzz"), ("capability_name", "zzz"), ("plan_id", "plan_zzz"),
                 ("contract_id", "ct_zzz"), ("purpose", "Another purpose."),
                 ("inputs", ["other"]), ("outputs", ["other"]), ("constraints", ["other"]))
        for key, value in edits:
            for op in ("create", "improve"):
                if key == "capability_name" and op == "improve":
                    continue  # the existing capability name must match: invalid request
                r = run(with_request(op, **{key: value}))
                self.assertEqual(r["status"], "context_mismatch", (key, op))
                self.assertTrue(validate(r)["valid"], (key, op))

    def test_input_order_is_type_strict(self):
        r = run(with_request(inputs=["a_input", "z_input"]))
        self.assertEqual(r["status"], "context_mismatch")
        r = run(with_request(constraints=["First.", "Second.", "Second."]))
        self.assertEqual(r["status"], "context_mismatch")

    def test_existing_capability_mismatch(self):
        chain = with_request("improve", existing_capability=desc(purpose="Changed purpose."))
        self.assertEqual(run(chain)["status"], "context_mismatch")
        chain = with_request("improve", existing_capability=desc(version=2))
        self.assertEqual(run(chain)["status"], "context_mismatch")

    def test_forged_boundary_result(self):
        base = full()
        for kw in (dict(request_id="evo_002"), dict(plan_id="plan_002"),
                   dict(contract_id="ct_002")):
            forged = full(**kw)[14]
            r = run(swap(base, [None] * 14 + [forged], 14))
            self.assertEqual(r["status"], "context_mismatch", kw)
        forged = dict(base[14], plan_id="plan_zzz")
        self.assertEqual(run(swap(base, [None] * 14 + [forged], 14))["status"],
                         "context_mismatch")

    def test_swapped_chain_objects_from_other_request(self):
        base, other = full(), full(request_id="evo_002")
        for i, name in enumerate(NAMES):
            r = run(swap(base, other, i))
            if name in ("creport", "analysis"):
                continue  # carry no request_id: identical for both chains
            self.assertEqual(r["status"], "context_mismatch", name)

    def test_swapped_chain_objects_from_other_operation(self):
        base, other = full("create"), full("improve")
        for i, name in enumerate(NAMES):
            if name == "creport":
                continue
            self.assertEqual(run(swap(base, other, i))["status"], "context_mismatch", name)

    def test_each_trusted_id_mismatch(self):
        base = full()
        for key in ("plan_id", "proposal_id", "candidate_id", "design_id", "blueprint_id",
                    "contract_id"):
            other = full(**{key: key[:-3] + "_002"})
            statuses = {run(swap(base, other, i))["status"] for i in range(16)}
            self.assertEqual(statuses - {"valid"}, {"context_mismatch"}, key)

    def test_mismatch_result_carries_request_identity_only(self):
        r = run(with_request(plan_id="plan_zzz"))
        self.assertEqual(r["request_id"], "evo_001")
        self.assertEqual(r["analysis_status"], "create_required")
        for key in ("implementation_request_id", "plan_id", "contract_id", "boundary_status"):
            self.assertIsNone(r[key])

    def test_derived_request_internal_failure_is_context_mismatch(self):
        with mock.patch.object(rmod, "build_capability_implementation_request",
                               return_value={"status": "context_mismatch", "request": None}):
            self.assertEqual(run(full())["status"], "context_mismatch")


class UnsupportedTests(unittest.TestCase):
    def _conflict_chain(self, tail):
        request = req(operation="create")
        analysis = analyze(request, [desc()])
        self.assertEqual(analysis["status"], "improve_or_conflict")
        spec = build_spec(request, analysis, specification_id="spec_001")["specification"]
        return [request, analysis, spec] + tail

    def test_improve_or_conflict_unsupported(self):
        for tail in (full()[3:], full("improve")[3:], [None] * 13):
            r = run(self._conflict_chain(tail))
            self.assertEqual(r["status"], "unsupported_status")
            self.assertIs(r["valid"], False)
            self.assertEqual(r["analysis_status"], "improve_or_conflict")
            for key in ("implementation_request_id", "plan_id", "contract_id",
                        "boundary_status"):
                self.assertIsNone(r[key])
            self.assertTrue(validate(r)["valid"])

    def test_unsupported_combination_guard(self):
        with mock.patch.object(rmod, "SUPPORTED", (("improve", "improve_required"),)):
            r = run(full("create"))
        self.assertEqual(r["status"], "unsupported_status")
        self.assertIs(r["valid"], False)

    def test_internal_failure_is_validation_error(self):
        with mock.patch.object(rmod, "evaluate_capability_implementation_boundary",
                               side_effect=RuntimeError("x")):
            r = run(full())
        self.assertEqual(r["status"], "validation_error")
        self.assertTrue(validate(r)["valid"])


class ResultValidatorTests(unittest.TestCase):
    def test_wrong_type(self):
        for bad in (None, [], "x", 1, ()):
            v = validate(bad)
            self.assertFalse(v["valid"])
            self.assertEqual(codes(v), ["result_not_dict"])

    def test_missing_key(self):
        for key in KEYS:
            r = ok()
            del r[key]
            v = validate(r)
            self.assertFalse(v["valid"], key)
            self.assertEqual(codes(v), ["missing_key"])

    def test_extra_key(self):
        for extra in ("implementation_allowed", "execution_allowed", "executed", "x"):
            r = ok()
            r[extra] = False
            v = validate(r)
            self.assertFalse(v["valid"], extra)
            self.assertIn("unexpected_key", codes(v))

    def test_invalid_status(self):
        for bad in ("ready", "", None, 1, "VALID", "invalid", object()):
            r = ok()
            r["status"] = bad
            v = validate(r)
            self.assertFalse(v["valid"], repr(bad))
            self.assertIn("invalid_status", codes(v))

    def test_valid_flag_must_match_status(self):
        r = ok()
        r["valid"] = False
        self.assertFalse(validate(r)["valid"])
        r = run(with_request(plan_id="plan_zzz"))
        r["valid"] = True
        self.assertFalse(validate(r)["valid"])
        for bad in (1, None, "True"):
            r = ok()
            r["valid"] = bad
            self.assertFalse(validate(r)["valid"], repr(bad))

    def test_reason_must_equal_status(self):
        r = ok()
        r["reason"] = "other"
        self.assertIn("invalid_reason", codes(validate(r)))

    def test_valid_result_identity_checks(self):
        for key, bad in (("implementation_request_id", None), ("plan_id", None),
                         ("contract_id", ""), ("boundary_status", "not_ready"),
                         ("boundary_status", None), ("request_id", ""),
                         ("capability_name", None), ("operation", "delete"),
                         ("analysis_status", "improve_or_conflict")):
            r = ok()
            r[key] = bad
            self.assertFalse(validate(r)["valid"], (key, bad))
        r = ok()
        r["analysis_status"] = "improve_required"
        self.assertFalse(validate(r)["valid"])

    def test_non_valid_result_cannot_leak_identity(self):
        for status in rmod.STATUSES:
            if status == "valid":
                continue
            for key in ("implementation_request_id", "plan_id", "contract_id",
                        "boundary_status"):
                r = rmod._result(status, req(), "create_required")
                r[key] = "ready" if key == "boundary_status" else "leaked"
                self.assertFalse(validate(r)["valid"], (status, key))
        for status in ("invalid_request", "validation_error"):
            r = rmod._result(status)
            r["request_id"] = "leaked"
            self.assertFalse(validate(r)["valid"], status)
        self.assertFalse(validate(rmod._result("invalid_analysis", req(),
                                               "create_required"))["valid"])

    def test_every_status_result_validates(self):
        for status in rmod.STATUSES:
            if status in ("valid", "invalid_analysis"):
                continue
            r = rmod._result(status) if status in ("invalid_request", "validation_error") \
                else rmod._result(status, req(), "create_required")
            self.assertTrue(validate(r)["valid"], (status, validate(r)))

    def test_validator_shape_and_never_raises(self):
        for r in (ok(), None, {}):
            v = validate(r)
            self.assertEqual(sorted(v), ["errors", "executed", "execution_allowed", "valid"])
            self.assertIs(v["execution_allowed"], False)
            self.assertIs(v["executed"], False)
            self.assertLessEqual(len(v["errors"]), 20)
        with mock.patch.object(rmod, "_result_errors", side_effect=RuntimeError("x")):
            self.assertEqual(codes(validate(ok())), ["validation_error"])


class SafetyTests(unittest.TestCase):
    def test_inputs_not_mutated(self):
        for op in ("create", "improve"):
            chain = full(op)
            snap = copy.deepcopy(chain)
            run(chain)
            self.assertEqual(chain, snap)
        bad = with_request(plan_id="plan_zzz")
        snap = copy.deepcopy(bad)
        run(bad)
        self.assertEqual(bad, snap)

    def test_fresh_results_and_determinism(self):
        for op in ("create", "improve"):
            chain = full(op)
            results = [run(chain) for _ in range(5)]
            self.assertTrue(all(r == results[0] for r in results))
            self.assertIsNot(results[0], results[1])
        bad = with_request(inputs=["other"])
        results = [run(bad) for _ in range(3)]
        self.assertTrue(all(r == results[0] for r in results))

    def test_result_validator_does_not_mutate(self):
        r = ok()
        snap = copy.deepcopy(r)
        validate(r)
        self.assertEqual(r, snap)

    def test_permission_flags_stay_false_in_validated_request(self):
        for op in ("create", "improve"):
            chain = full(op)
            self.assertEqual(run(chain)["status"], "valid")
            self.assertIs(chain[15]["implementation_allowed"], False)
            self.assertIs(chain[15]["execution_allowed"], False)
            self.assertIs(chain[14]["implementation_allowed"], False)
            self.assertIs(chain[14]["implementation_started"], False)

    def test_constants(self):
        self.assertEqual(rmod.VALIDATION_VERSION, 1)
        self.assertEqual(len(rmod.STATUSES), 21)
        self.assertEqual(len(rmod.RESULT_KEYS), 12)
        for status in ("valid", "invalid_boundary", "invalid_implementation_request",
                       "context_mismatch", "unsupported_status", "validation_error"):
            self.assertIn(status, rmod.STATUSES)

    def test_module_has_no_forbidden_imports_or_calls(self):
        path = os.path.join(ROOT, "capabilities",
                            "capability_implementation_request_validation.py")
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        banned = {"os", "sys", "socket", "http", "urllib", "requests", "subprocess", "shutil",
                  "pathlib", "importlib", "sqlite3", "pickle", "json", "random", "time",
                  "datetime", "threading", "ctypes", "builtins", "ael", "memory", "research"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split(".")[0], banned)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 1:
                    self.assertTrue(node.module.startswith("capability_"))
                else:
                    self.assertNotIn((node.module or "").split(".")[0], banned)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"open", "exec", "eval", "compile", "__import__"})


if __name__ == "__main__":
    unittest.main()
