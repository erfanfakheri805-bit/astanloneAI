"""
Prompt 840 - reasoning-to-capability boundary checkpoint focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_boundary_prompt840 -v
"""

import copy
import itertools
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from understanding.nlu_pipeline import default_pipeline
from understanding.nlu_reasoning_input import build_reasoning_input
from reasoning.reasoning_foundation import build_reasoning_request
from reasoning.reasoning_decision import decide_reasoning
from reasoning.capability_contract import build_capability_contract
from reasoning.capability_integration import (
    integrate_capability_contract, classify_capability_result,
)
from reasoning import capability_boundary as cb
from reasoning.capability_boundary import evaluate_reasoning_capability_boundary as boundary

P = default_pipeline()
KEYS = ["version", "decision_state", "capability_classification", "contract_valid",
        "execution_allowed", "next_stage", "reason", "executed"]
STAGES = {"clarify", "request_information", "capability_definition", "capability_system"}
SAFE = {"version": 1, "decision_state": "unknown",
        "capability_classification": "integration_error", "contract_valid": False,
        "execution_allowed": False, "next_stage": "capability_definition",
        "reason": "boundary_error", "executed": False}


def decision_for(text):
    return decide_reasoning(build_reasoning_request(build_reasoning_input(P.analyze(text), None)))


def ready():
    d = decision_for("من عرفان هستم")
    assert d["decision"] == "ready"
    return d


def spec(**over):
    s = {"name": "text_summary", "purpose": "Summarise a supplied text",
         "required_inputs": ["source_text"], "expected_outputs": ["summary_text"],
         "constraints": ["read only"]}
    s.update(over)
    return s


def check(result, state, classification, valid, stage, reason):
    assert list(result) == KEYS, list(result)
    assert (result["decision_state"], result["capability_classification"],
            result["contract_valid"], result["next_stage"], result["reason"]) == \
        (state, classification, valid, stage, reason), result
    assert result["version"] == 1 and result["execution_allowed"] is False
    assert result["executed"] is False


class TestEveryBoundaryState(unittest.TestCase):
    def test_needs_clarification(self):
        d = dict(ready(), decision="needs_clarification")
        check(boundary(d, spec()), "needs_clarification", "decision_not_ready", False,
              "clarify", "needs_clarification")

    def test_needs_information(self):
        d = dict(ready(), decision="needs_information")
        check(boundary(d, spec()), "needs_information", "decision_not_ready", False,
              "request_information", "needs_information")

    def test_real_not_ready_decision(self):
        d = decision_for("asdf qwer zxcv")
        self.assertNotEqual(d["decision"], "ready")
        r = boundary(d, spec())
        self.assertIn(r["next_stage"], ("clarify", "request_information"))
        self.assertEqual(r["capability_classification"], "decision_not_ready")
        self.assertFalse(r["contract_valid"])

    def test_invalid_plan_and_unusable_decisions(self):
        base = ready()
        for d in (None, 1, "ready", [], {}, dict(base, decision="invalid_plan"),
                  dict(base, executed=True), dict(base, validation={"valid": False})):
            check(boundary(d, spec()), "invalid", "decision_not_ready", False,
                  "request_information", "decision_invalid")

    def test_ready_missing_spec(self):
        check(boundary(ready()), "ready", "spec_missing", False,
              "capability_definition", "capability_unspecified")
        check(boundary(ready(), None), "ready", "spec_missing", False,
              "capability_definition", "capability_unspecified")

    def test_ready_incomplete_spec(self):
        check(boundary(ready(), {}), "ready", "spec_missing", False,
              "capability_definition", "missing_field")
        s = spec()
        del s["purpose"]
        check(boundary(ready(), s), "ready", "spec_missing", False,
              "capability_definition", "missing_field")

    def test_ready_invalid_spec(self):
        check(boundary(ready(), "x"), "ready", "spec_invalid", False,
              "capability_definition", "spec_not_dict")
        check(boundary(ready(), spec(name="Bad Name")), "ready", "spec_invalid", False,
              "capability_definition", "invalid_name")
        check(boundary(ready(), spec(tool="t")), "ready", "spec_invalid", False,
              "capability_definition", "unexpected_field")
        check(boundary(ready(), spec(execution_allowed=True)), "ready", "spec_invalid",
              False, "capability_definition", "execution_allowed_not_false")

    def test_valid_contract(self):
        check(boundary(ready(), spec()), "ready", "contract_valid", True,
              "capability_system", "built")

    def test_integration_error_via_faulty_integrator(self):
        def raises(d, s):
            raise RuntimeError("boom")
        for integ in (raises, lambda d, s: None, lambda d, s: {"status": "built"},
                      lambda d, s: {"version": 1, "status": "invalid",
                                    "reason": "integration_result_invalid",
                                    "contract": None, "validation": None, "executed": False}):
            self.assertEqual(boundary(ready(), spec(), integrator=integ), SAFE)

    def test_not_ready_wins_over_spec(self):
        d = dict(ready(), decision="needs_clarification")
        for s in (None, {}, "x", spec(), {"junk": 1}):
            self.assertEqual(boundary(d, s)["next_stage"], "clarify")


class TestStageRules(unittest.TestCase):
    def all_results(self):
        base = ready()
        decisions = [None, {}, base, dict(base, decision="needs_clarification"),
                     dict(base, decision="needs_information"),
                     dict(base, decision="invalid_plan"), dict(base, executed=True)]
        specs = [None, {}, "x", 5, spec(), spec(name=""), spec(tool="t"),
                 spec(execution_allowed=True), spec(expected_outputs=[]),
                 {k: v for k, v in spec().items() if k != "name"}]
        for d, s in itertools.product(decisions, specs):
            yield d, s, boundary(d, s)

    def test_next_stage_only_allowed_values(self):
        for d, s, r in self.all_results():
            self.assertIn(r["next_stage"], STAGES)

    def test_capability_system_only_with_valid_contract(self):
        seen = set()
        for d, s, r in self.all_results():
            seen.add(r["next_stage"])
            built = build_capability_contract(d, s)
            if r["next_stage"] == "capability_system":
                self.assertTrue(r["contract_valid"])
                self.assertEqual(built["status"], "built")
            else:
                self.assertFalse(r["contract_valid"])
                self.assertNotEqual(built["status"], "built")
            self.assertEqual(r["contract_valid"], built["status"] == "built")
        self.assertEqual(seen, STAGES)

    def test_execution_never_allowed(self):
        for d, s, r in self.all_results():
            self.assertIs(r["execution_allowed"], False)
            self.assertIs(r["executed"], False)

    def test_constants(self):
        self.assertEqual(set(cb.NEXT_STAGES), STAGES)
        self.assertEqual(len(cb.NEXT_STAGES), 4)

    def test_capability_system_not_reachable_through_faulty_integrator(self):
        def lying(d, s):
            return {"version": 1, "status": "built", "reason": "built", "contract": None,
                    "validation": None, "executed": False}
        self.assertEqual(boundary(ready(), spec(), integrator=lying), SAFE)


class TestReuse(unittest.TestCase):
    def test_uses_prompt839_integration_and_classifier(self):
        self.assertIs(cb.integrate_capability_contract, integrate_capability_contract)
        self.assertIs(cb.classify_capability_result, classify_capability_result)
        self.assertIs(boundary.__defaults__[1], integrate_capability_contract)

    def test_matches_integration_and_classifier(self):
        d = ready()
        for s in (None, {}, "x", spec(), spec(name="")):
            r = boundary(d, s)
            self.assertEqual(r["capability_classification"],
                             classify_capability_result(integrate_capability_contract(d, s)))
            self.assertEqual(r["reason"], integrate_capability_contract(d, s)["reason"])

    def test_integrator_receives_inputs_unchanged(self):
        seen = []
        def integ(d, s):
            seen.append((d, s))
            return integrate_capability_contract(d, s)
        d, s = ready(), spec()
        boundary(d, s, integrator=integ)
        self.assertIs(seen[0][0], d)
        self.assertIs(seen[0][1], s)


class TestNoInventionOrCarrying(unittest.TestCase):
    def test_no_contract_or_capability_data_in_result(self):
        r = boundary(ready(), spec())
        text = json.dumps(r)
        for word in ("text_summary", "source_text", "summary_text", "Summarise", "contract\""):
            self.assertNotIn(word, text)
        for k in ("contract", "name", "tool", "handler", "implementation"):
            self.assertNotIn(k, r)

    def test_values_are_fixed_vocabulary(self):
        for d in (ready(), None):
            for s in (None, {}, spec()):
                r = boundary(d, s)
                self.assertIn(r["decision_state"], cb.DECISION_STATES)
                self.assertIn(r["capability_classification"], cb.CLASSIFICATIONS)


class TestFreshReadOnlyDeterministic(unittest.TestCase):
    def test_inputs_not_modified(self):
        d, s = ready(), spec()
        d0, s0 = copy.deepcopy(d), copy.deepcopy(s)
        boundary(d, s)
        self.assertEqual((d, s), (d0, s0))

    def test_deterministic_and_fresh(self):
        d, s = ready(), spec()
        a, b = boundary(d, s), boundary(d, s)
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        a["next_stage"] = "tampered"
        self.assertEqual(boundary(d, s)["next_stage"], "capability_system")
        s1, s2 = boundary(None), boundary(None)
        s1["reason"] = "x"
        self.assertEqual(s2["reason"], "decision_invalid")

    def test_safe_result_is_fresh(self):
        def raises(d, s):
            raise RuntimeError
        a, b = boundary(None, None, integrator=raises), boundary(None, None, integrator=raises)
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        a["reason"] = "x"
        self.assertEqual(b, SAFE)

    def test_json_safe(self):
        for d in (ready(), None, {}):
            for s in (None, spec(), "x"):
                r = boundary(d, s)
                self.assertEqual(json.loads(json.dumps(r)), r)

    def test_bounded_on_huge_inputs(self):
        s = spec(required_inputs=["i%d" % i for i in range(20000)])
        r = boundary(ready(), s)
        self.assertEqual(r["next_stage"], "capability_definition")
        big = spec()
        for i in range(5000):
            big["k%d" % i] = i
        self.assertEqual(boundary(ready(), big)["capability_classification"], "spec_invalid")
        self.assertLess(len(json.dumps(r)), 400)

    def test_never_raises_on_hostile_inputs(self):
        class Boom(dict):
            def get(self, *a):
                raise RuntimeError("boom")
            def __getitem__(self, k):
                raise RuntimeError("boom")
            def __iter__(self):
                raise RuntimeError("boom")
        for d in (Boom(), object(), ready()):
            for s in (Boom(), object(), spec()):
                r = boundary(d, s)
                self.assertEqual(list(r), KEYS)
                self.assertIn(r["next_stage"], STAGES)


class TestBackwardCompatible(unittest.TestCase):
    def test_prompt838_and_839_results_unchanged_by_boundary(self):
        d, s = ready(), spec()
        b838, i839 = build_capability_contract(d, s), integrate_capability_contract(d, s)
        boundary(d, s)
        self.assertEqual(build_capability_contract(d, s), b838)
        self.assertEqual(integrate_capability_contract(d, s), i839)
        self.assertEqual(b838, i839)
        self.assertEqual(list(i839), ["version", "status", "reason", "contract",
                                      "validation", "executed"])
        self.assertEqual(classify_capability_result(i839), "contract_valid")

    def test_prompt837_decision_unchanged(self):
        d = ready()
        boundary(d, spec())
        self.assertEqual(list(d), ["version", "decision", "reason", "request_status",
                                   "plan_status", "validation", "next_step", "executed"])
        self.assertEqual(decision_for("من عرفان هستم"), d)

    def test_existing_apis_importable(self):
        import reasoning.reasoning_plan, reasoning.reasoning_plan_validation
        import reasoning.reasoning_engine
        self.assertTrue(callable(reasoning.reasoning_plan.build_reasoning_plan))
        self.assertTrue(callable(integrate_capability_contract))

    def test_no_forbidden_imports_or_execution(self):
        with open(cb.__file__.replace(".pyc", ".py"), encoding="utf-8") as fh:
            src = fh.read()
        code = "\n".join(l for l in src.splitlines() if l.startswith(("import ", "from ")))
        for word in ("socket", "urllib", "requests", "subprocess", "random", "time",
                     "core", "memory", "ael", "execution", "tools"):
            self.assertNotIn(word, code, word)
        self.assertNotIn("exec(", src)
        self.assertNotIn("eval(", src)


if __name__ == "__main__":
    unittest.main()
