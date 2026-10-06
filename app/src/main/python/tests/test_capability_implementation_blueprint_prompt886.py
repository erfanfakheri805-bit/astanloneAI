"""
Prompt 886 - capability implementation blueprint focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_implementation_blueprint_prompt886 -v
"""

import ast
import copy
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities import capability_implementation_blueprint as bmod
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
    build_capability_implementation_blueprint as build,
    validate_capability_implementation_blueprint as validate)
from capabilities.capability_implementation_design import (
    build_capability_implementation_design as build_design,
    validate_capability_implementation_design as validate_design)
from capabilities.capability_implementation_design_validation import (
    validate_capability_implementation_design_context as check)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KEYS = ["version", "blueprint_id", "request_id", "operation", "capability_name", "purpose",
        "inputs", "outputs", "constraints", "existing_capability", "analysis_status",
        "plan_id", "proposal_id", "candidate_id", "design_id", "implementation_steps"]
CREATE_STEPS = ["define_interface", "define_validation", "define_behavior_boundary",
                "define_tests"]
IMPROVE_STEPS = ["inspect_existing_behavior", "define_interface_delta",
                 "define_behavior_boundary", "define_regression_tests"]


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


def nine(op="create", caps=None, plan_id="plan_001", proposal_id="prop_001",
         candidate_id="cand_001", design_id="design_001", **req_over):
    """[request, analysis, spec, plan, proposal, candidate, readiness, design, validation]."""
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
    return chain + [check(*chain)]


def swap(base, other, *indexes):
    out = list(base)
    for i in indexes:
        out[i] = other[i]
    return out


def run(chain, blueprint_id="bp_001"):
    return build(*chain, blueprint_id)


def ok(op="create"):
    return run(nine(op))


def codes(result):
    return [e["code"] for e in result["errors"]]


class IntegerVersionTests(unittest.TestCase):
    def test_prompt884_design_version_still_integer(self):
        for op in ("create", "improve"):
            d = nine(op)[7]
            self.assertEqual(d["version"], 1)
            self.assertIs(type(d["version"]), int)
            self.assertTrue(validate_design(d)["valid"])
            for bad in ("1", 2, True, 1.0, None):
                self.assertFalse(validate_design(dict(d, version=bad))["valid"], bad)

    def test_blueprint_version_is_integer_one(self):
        for op in ("create", "improve"):
            b = ok(op)["blueprint"]
            self.assertEqual(b["version"], 1)
            self.assertIs(type(b["version"]), int)
        self.assertEqual(bmod.BLUEPRINT_VERSION, 1)
        self.assertIs(type(bmod.BLUEPRINT_VERSION), int)

    def test_wrong_version_types_rejected(self):
        for bad in ("1", "2", 2, 0, True, False, 1.0, None, [1], {"v": 1}):
            b = ok()["blueprint"]
            b["version"] = bad
            r = validate(b)
            self.assertFalse(r["valid"], bad)
            self.assertIn("invalid_version", codes(r))


class ValidBlueprintTests(unittest.TestCase):
    def test_valid_create(self):
        r = ok("create")
        self.assertEqual(r["status"], "ready")
        b = r["blueprint"]
        self.assertEqual(b["operation"], "create")
        self.assertEqual(b["analysis_status"], "create_required")
        self.assertIsNone(b["existing_capability"])
        self.assertEqual(b["implementation_steps"], CREATE_STEPS)
        self.assertTrue(validate(b)["valid"])

    def test_valid_improve(self):
        r = ok("improve")
        self.assertEqual(r["status"], "ready")
        b = r["blueprint"]
        self.assertEqual((b["operation"], b["analysis_status"]), ("improve", "improve_required"))
        self.assertEqual(b["existing_capability"], desc())
        self.assertEqual(b["implementation_steps"], IMPROVE_STEPS)
        self.assertTrue(validate(b)["valid"])

    def test_exactly_sixteen_keys(self):
        for op in ("create", "improve"):
            self.assertEqual(sorted(ok(op)["blueprint"]), sorted(KEYS))
        self.assertEqual(len(KEYS), 16)
        self.assertEqual(list(bmod.FIELDS), KEYS)

    def test_builder_result_shape(self):
        for chain in (nine(), [None] * 9):
            r = run(chain)
            self.assertEqual(sorted(r), ["blueprint", "executed", "execution_allowed", "status"])
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)
        self.assertIsNone(run([None] * 9)["blueprint"])

    def test_values_preserved_exactly(self):
        b = ok()["blueprint"]
        self.assertEqual(b["purpose"], "Summarize short documents.")
        self.assertEqual(b["inputs"], ["z_input", "a_input"])
        self.assertEqual(b["outputs"], ["z_out", "a_out"])
        self.assertEqual(b["constraints"], ["Second.", "First.", "Second."])
        self.assertEqual((b["request_id"], b["capability_name"]), ("evo_001", "text_summarizer"))

    def test_ids_from_trusted_objects(self):
        chain = nine(plan_id="my_plan", proposal_id="my_prop", candidate_id="my_cand",
                     design_id="my_design")
        b = run(chain, "my_bp")["blueprint"]
        self.assertEqual((b["blueprint_id"], b["plan_id"], b["proposal_id"], b["candidate_id"],
                          b["design_id"]), ("my_bp", "my_plan", "my_prop", "my_cand", "my_design"))

    def test_caller_supplied_blueprint_id_kept(self):
        for bid in ("bp_1", "x", "Blueprint-42", "a" * 64):
            r = run(nine(), bid)
            self.assertEqual(r["status"], "ready", bid)
            self.assertEqual(r["blueprint"]["blueprint_id"], bid)

    def test_blueprint_never_claims_implementation(self):
        b = ok()["blueprint"]
        for flag in ("implementation_ready", "execution_allowed", "executed", "implemented"):
            self.assertNotIn(flag, b)


class InvalidBlueprintIdTests(unittest.TestCase):
    def test_missing_or_invalid_blueprint_id(self):
        for bad in (None, "", " ", "bad\nid", "x" * 65, 5, True, [], {}, b"x"):
            r = run(nine(), bad)
            self.assertEqual(r["status"], "invalid_blueprint_id", repr(bad))
            self.assertIsNone(r["blueprint"])

    def test_no_generated_id(self):
        self.assertEqual(build(*nine())["status"], "invalid_blueprint_id")

    def test_validator_rejects_bad_blueprint_id(self):
        for bad in (None, "", "bad\nid", "x" * 65, 5):
            b = ok()["blueprint"]
            b["blueprint_id"] = bad
            r = validate(b)
            self.assertFalse(r["valid"], repr(bad))
            self.assertIn("invalid_blueprint_id", codes(r))


class InvalidObjectTests(unittest.TestCase):
    def status(self, index, bad):
        chain = nine()
        chain[index] = bad
        return run(chain)

    def test_invalid_request(self):
        for bad in (None, {}, dict(req(), goal=5)):
            r = self.status(0, bad)
            self.assertEqual(r["status"], "invalid_request")
            self.assertIsNone(r["blueprint"])

    def test_invalid_analysis(self):
        self.assertEqual(self.status(1, {"status": "create_required"})["status"],
                         "invalid_analysis")

    def test_invalid_specification(self):
        self.assertEqual(self.status(2, dict(nine()[2], specification_id=""))["status"],
                         "invalid_specification")

    def test_invalid_validation_context(self):
        with mock.patch.object(bmod, "validate_capability_evolution", return_value={"x": 1}):
            r = run(nine())
        self.assertEqual(r["status"], "invalid_validation")
        self.assertIsNone(r["blueprint"])

    def test_invalid_plan(self):
        for bad in (None, dict(nine()[3], plan_id="bad\nid")):
            self.assertEqual(self.status(3, bad)["status"], "invalid_plan")

    def test_invalid_proposal(self):
        self.assertEqual(self.status(4, dict(nine()[4], proposal_type="x"))["status"],
                         "invalid_proposal")

    def test_invalid_candidate(self):
        chain = nine()
        for bad in (None, {"version": "1"}, dict(chain[5], extra=1),
                    dict(chain[5], implementation_ready=True),
                    dict(chain[5], execution_allowed=True)):
            self.assertEqual(self.status(5, bad)["status"], "invalid_candidate")

    def test_invalid_readiness(self):
        chain = nine()
        for bad in (None, {}, dict(chain[6], extra=1), dict(chain[6], ready=False),
                    dict(chain[6], execution_allowed=True)):
            self.assertEqual(self.status(6, bad)["status"], "invalid_readiness")
        invalid = evaluate_readiness(None, None, None, None, None, None)
        self.assertEqual(self.status(6, invalid)["status"], "invalid_readiness")

    def test_invalid_design(self):
        chain = nine()
        for bad in (None, {}, dict(chain[7], extra=1), dict(chain[7], version="1"),
                    dict(chain[7], design_type="nonsense"),
                    dict(chain[7], implementation_ready=True),
                    dict(chain[7], execution_allowed=True)):
            self.assertEqual(self.status(7, bad)["status"], "invalid_design")

    def test_invalid_design_validation_result(self):
        chain = nine()
        good = chain[8]
        for bad in (None, {}, "valid", dict(good, extra=1), dict(good, version="1"),
                    dict(good, valid=False), dict(good, reason="other"),
                    dict(good, status="nonsense")):
            self.assertEqual(self.status(8, bad)["status"], "invalid_design_validation",
                             repr(bad))

    def test_well_formed_but_not_valid_validation_result(self):
        failing = check(*swap(nine(), nine(request_id="other"), 7)[:8])
        self.assertEqual(failing["status"], "context_mismatch")
        r = self.status(8, failing)
        self.assertEqual(r["status"], "invalid_design_validation")
        self.assertIsNone(r["blueprint"])

    def test_order_first_failure_wins(self):
        chain = nine()
        chain[1], chain[4], chain[8] = None, None, None
        self.assertEqual(run(chain)["status"], "invalid_analysis")
        chain = nine()
        chain[7], chain[8] = None, None
        self.assertEqual(run(chain)["status"], "invalid_design")
        chain = nine()
        chain[8] = None
        self.assertEqual(run(chain, None)["status"], "invalid_design_validation")

    def test_no_arguments(self):
        self.assertEqual(build()["status"], "invalid_request")


class ContextMismatchTests(unittest.TestCase):
    def mismatch(self, chain):
        r = run(chain)
        self.assertEqual(r["status"], "context_mismatch")
        self.assertIsNone(r["blueprint"])
        return r

    def test_request_mismatch(self):
        other = nine(request_id="evo_002")
        for i in (0, 2, 3, 4, 5, 6, 7, 8):
            self.mismatch(swap(nine(), other, i))

    def test_capability_name_mismatch(self):
        other = nine(capability_name="other_cap")
        for i in (0, 3, 4, 5, 6, 7, 8):
            self.mismatch(swap(nine(), other, i))

    def test_candidate_mismatch(self):
        self.mismatch(swap(nine(), nine(candidate_id="cand_002"), 5))
        chain = nine()
        chain[5] = dict(chain[5], inputs=["a_input", "z_input"])
        self.mismatch(chain)

    def test_readiness_mismatch(self):
        for other in (nine(plan_id="plan_9"), nine(proposal_id="prop_9"),
                      nine(request_id="evo_9"), nine("improve")):
            self.mismatch(swap(nine(), other, 6))

    def test_design_mismatch(self):
        for other in (nine(design_id="design_9"), nine(goal="x"), nine("improve"),
                      nine(candidate_id="cand_9")):
            self.mismatch(swap(nine(), other, 7))

    def test_validation_result_mismatch(self):
        for other in (nine(design_id="design_9"), nine(plan_id="plan_9"),
                      nine(proposal_id="prop_9"), nine(candidate_id="cand_9"),
                      nine(request_id="evo_9"), nine(capability_name="other_cap"),
                      nine("improve")):
            self.assertEqual(other[8]["status"], "valid")
            self.mismatch(swap(nine(), other, 8))

    def test_forged_individually_valid_objects(self):
        base = nine()
        for i, other in ((2, nine(goal="Another goal.")), (3, nine(plan_id="plan_2")),
                         (4, nine(outputs=["x_out"])), (5, nine(request_id="evo_2")),
                         (6, nine(plan_id="plan_3")), (7, nine(proposal_id="prop_2")),
                         (8, nine(design_id="design_2"))):
            self.mismatch(swap(base, other, i))

    def test_forged_valid_result_for_forged_design(self):
        # a self-consistent forged design + the validation result issued for it still fails
        base, other = nine(), nine(design_id="design_other")
        forged = swap(base, other, 7, 8)
        self.assertEqual(forged[8]["status"], "valid")
        r = run(forged)
        self.assertEqual(r["status"], "ready")  # the design id is the caller's own
        self.assertEqual(r["blueprint"]["design_id"], "design_other")
        self.mismatch(swap(forged, nine(), 8))

    def test_hand_built_valid_looking_result(self):
        chain = nine()
        chain[8] = dict(chain[8], design_id="design_forged")
        self.mismatch(chain)
        chain = nine()
        chain[8] = dict(chain[8], plan_id="plan_forged")
        self.mismatch(chain)

    def test_existing_capability_mismatch(self):
        base = nine("improve")
        other = nine("improve", caps=[desc(purpose="A different purpose.")])
        for i in (2, 3, 4, 5, 7):
            self.mismatch(swap(base, other, i))
        # the Prompt 885 result carries no existing-capability data: identical in both chains
        self.assertEqual(base[8], other[8])


class UnsupportedAndInternalTests(unittest.TestCase):
    def test_improve_or_conflict_rejected(self):
        request = req(operation="create")
        analysis = analyze(request, [desc()])
        self.assertEqual(analysis["status"], "improve_or_conflict")
        for tail in (nine(), nine("improve")):
            chain = [request, analysis] + tail[2:]
            r = run(chain)
            self.assertNotEqual(r["status"], "ready")
            self.assertIsNone(r["blueprint"])

    def test_unsupported_combination_guard(self):
        with mock.patch.object(bmod, "SUPPORTED", (("improve", "improve_required",
                                                    "improve_implementation"),)):
            r = run(nine("create"))
        self.assertEqual(r["status"], "unsupported_status")
        self.assertIsNone(r["blueprint"])

    def test_unsupported_operations_rejected(self):
        for op in ("delete", "replace", "", None, 1):
            r = run(swap(nine(), nine(), 0))
            chain = nine()
            chain[0] = dict(chain[0], operation=op)
            self.assertNotEqual(run(chain)["status"], "ready", repr(op))
            b = ok()["blueprint"]
            b["operation"] = op
            self.assertFalse(validate(b)["valid"], repr(op))

    def test_internal_failure(self):
        with mock.patch.object(bmod, "_validation_result_mismatch",
                               side_effect=RuntimeError("x")):
            r = run(nine())
        self.assertEqual(r["status"], "validation_error")
        self.assertIsNone(r["blueprint"])
        self.assertIs(r["execution_allowed"], False)

    def test_blueprint_error_guard(self):
        with mock.patch.object(bmod, "_blueprint_errors", return_value=[{"code": "x"}]):
            self.assertEqual(run(nine())["status"], "blueprint_error")


class StepSequenceTests(unittest.TestCase):
    def test_create_steps(self):
        self.assertEqual(ok("create")["blueprint"]["implementation_steps"], CREATE_STEPS)
        self.assertEqual(list(bmod.CREATE_STEPS), CREATE_STEPS)

    def test_improve_steps(self):
        self.assertEqual(ok("improve")["blueprint"]["implementation_steps"], IMPROVE_STEPS)
        self.assertEqual(list(bmod.IMPROVE_STEPS), IMPROVE_STEPS)

    def test_steps_are_short_identifiers_only(self):
        for op in ("create", "improve"):
            for step in ok(op)["blueprint"]["implementation_steps"]:
                self.assertRegex(step, r"^[a-z_]+$")
                self.assertLessEqual(len(step), 30)

    def test_wrong_steps_rejected(self):
        for bad in (None, "define_interface", [], ["define_interface"], CREATE_STEPS[::-1],
                    CREATE_STEPS + ["extra"], [1, 2, 3, 4], ("define_interface",) * 4,
                    IMPROVE_STEPS, ["rm -rf /", "x", "y", "z"], ["import os", "a", "b", "c"]):
            b = ok("create")["blueprint"]
            b["implementation_steps"] = bad
            r = validate(b)
            self.assertFalse(r["valid"], repr(bad))
            self.assertIn("invalid_implementation_steps", codes(r))
        b = ok("improve")["blueprint"]
        b["implementation_steps"] = list(CREATE_STEPS)
        self.assertFalse(validate(b)["valid"])


class BlueprintValidatorTests(unittest.TestCase):
    def test_malformed_blueprint(self):
        for bad in (None, [], "x", 5, (), set()):
            r = validate(bad)
            self.assertFalse(r["valid"])
            self.assertEqual(codes(r), ["blueprint_not_dict"])
        self.assertFalse(validate()["valid"])

    def test_extra_keys(self):
        for extra in ("code", "execution_allowed", "implementation_ready", "executed", "path"):
            b = ok()["blueprint"]
            b[extra] = False
            r = validate(b)
            self.assertFalse(r["valid"], extra)
            self.assertIn("unexpected_key", codes(r))
        b = ok()["blueprint"]
        b[5] = 1
        self.assertFalse(validate(b)["valid"])

    def test_missing_keys(self):
        for key in KEYS:
            b = ok()["blueprint"]
            del b[key]
            r = validate(b)
            self.assertFalse(r["valid"], key)
            self.assertIn("missing_key", codes(r))

    def test_field_corruption_rejected(self):
        corruptions = {"request_id": "bad\nid", "operation": "delete", "capability_name": "",
                       "purpose": "", "inputs": "x", "outputs": [], "constraints": [1],
                       "analysis_status": "improve_required", "plan_id": None,
                       "proposal_id": "", "candidate_id": 5, "design_id": "bad\nid",
                       "existing_capability": desc()}
        for key, bad in corruptions.items():
            b = ok("create")["blueprint"]
            b[key] = bad
            self.assertFalse(validate(b)["valid"], key)

    def test_improve_requires_existing_capability(self):
        b = ok("improve")["blueprint"]
        b["existing_capability"] = None
        self.assertFalse(validate(b)["valid"])

    def test_validator_result_shape(self):
        for b in (ok()["blueprint"], None, {}):
            r = validate(b)
            self.assertEqual(sorted(r), ["errors", "executed", "execution_allowed", "valid"])
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)
            self.assertLessEqual(len(r["errors"]), 20)

    def test_validator_never_raises(self):
        b = ok()["blueprint"]
        b["inputs"] = object()
        self.assertFalse(validate(b)["valid"])
        with mock.patch.object(bmod, "_blueprint_errors", side_effect=RuntimeError("x")):
            r = validate(ok()["blueprint"])
        self.assertFalse(r["valid"])
        self.assertEqual(codes(r), ["validation_error"])


class SafetyTests(unittest.TestCase):
    def test_inputs_not_mutated(self):
        for op in ("create", "improve"):
            chain = nine(op)
            snap = copy.deepcopy(chain)
            run(chain)
            self.assertEqual(chain, snap)
        bad = swap(nine(), nine(request_id="b"), 7)
        snap = copy.deepcopy(bad)
        run(bad)
        self.assertEqual(bad, snap)

    def test_blueprint_detached_from_inputs(self):
        chain = nine("improve")
        b = run(chain)["blueprint"]
        b["inputs"].append("mutated")
        b["outputs"].clear()
        b["constraints"].append("mutated")
        b["existing_capability"]["name"] = "mutated"
        b["implementation_steps"].append("mutated")
        self.assertEqual(chain[0]["inputs"], ["z_input", "a_input"])
        self.assertEqual(chain[0]["outputs"], ["z_out", "a_out"])
        self.assertEqual(chain[1]["existing"]["name"], "text_summarizer")
        self.assertEqual(ok("improve")["blueprint"]["implementation_steps"], IMPROVE_STEPS)
        self.assertEqual(bmod.IMPROVE_STEPS, tuple(IMPROVE_STEPS))

    def test_fresh_results_each_call(self):
        chain = nine()
        a, b = run(chain), run(chain)
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIsNot(a["blueprint"], b["blueprint"])
        self.assertIsNot(a["blueprint"]["implementation_steps"],
                         b["blueprint"]["implementation_steps"])

    def test_deterministic_repeated_construction(self):
        for op in ("create", "improve"):
            chain = nine(op)
            results = [run(chain) for _ in range(5)]
            self.assertTrue(all(r == results[0] for r in results))
        bad = swap(nine(), nine(goal="Other."), 3)
        results = [run(bad) for _ in range(3)]
        self.assertTrue(all(r == results[0] for r in results))

    def test_execution_flags_stay_false(self):
        for chain in (nine(), nine("improve"), [None] * 9, swap(nine(), nine(goal="x"), 7)):
            r = run(chain)
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)

    def test_type_strict_comparison(self):
        self.assertFalse(bmod._same(True, 1))
        self.assertFalse(bmod._same([1], (1,)))
        self.assertTrue(bmod._same({"a": [1, "b"]}, {"a": [1, "b"]}))

    def test_module_has_no_forbidden_imports_or_calls(self):
        path = os.path.join(ROOT, "capabilities", "capability_implementation_blueprint.py")
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

    def test_constants(self):
        self.assertEqual(len(bmod.STATUSES), 16)
        self.assertIn("ready", bmod.STATUSES)
        self.assertIn("invalid_design_validation", bmod.STATUSES)


if __name__ == "__main__":
    unittest.main()
