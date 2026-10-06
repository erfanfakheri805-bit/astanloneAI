"""
Prompt 839 - capability contract integration checkpoint focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_integration_prompt839 -v
"""

import copy
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from understanding.nlu_pipeline import default_pipeline
from understanding.nlu_reasoning_input import build_reasoning_input
from reasoning.reasoning_foundation import build_reasoning_request
from reasoning.reasoning_decision import decide_reasoning
from reasoning.capability_contract import (
    build_capability_contract, validate_capability_contract,
)
from reasoning import capability_integration as ci
from reasoning.capability_integration import (
    integrate_capability_contract, classify_capability_result,
)

P = default_pipeline()
BUILD_KEYS = ["version", "status", "reason", "contract", "validation", "executed"]
CONTRACT_KEYS = ["version", "name", "purpose", "required_inputs", "expected_outputs",
                 "constraints", "execution_allowed"]


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


def outcome(decision, s=None):
    return classify_capability_result(integrate_capability_contract(decision, s))


class TestReadyAndValid(unittest.TestCase):
    def test_valid_contract(self):
        r = integrate_capability_contract(ready(), spec())
        self.assertEqual(list(r), BUILD_KEYS)
        self.assertEqual((r["status"], r["reason"], r["executed"]), ("built", "built", False))
        self.assertEqual(list(r["contract"]), CONTRACT_KEYS)
        self.assertIs(r["contract"]["execution_allowed"], False)
        self.assertEqual(classify_capability_result(r), "contract_valid")
        self.assertTrue(validate_capability_contract(r["contract"])["valid"])

    def test_identical_to_prompt838_builder(self):
        d = ready()
        cases = [spec(), spec(required_inputs=[]), {}, spec(name="Bad"), None, "x",
                 spec(tool="t"), spec(execution_allowed=True), spec(expected_outputs=[])]
        for s in cases:
            self.assertEqual(integrate_capability_contract(d, s), build_capability_contract(d, s))
        for d2 in (None, {}, dict(d, decision="needs_information"), decision_for("asdf qwer")):
            self.assertEqual(integrate_capability_contract(d2, spec()),
                             build_capability_contract(d2, spec()))

    def test_contract_is_only_supplied_information(self):
        s = spec()
        c = integrate_capability_contract(ready(), s)["contract"]
        for k in ("name", "purpose", "required_inputs", "expected_outputs", "constraints"):
            self.assertEqual(c[k], s[k])


class TestDecisionNotReady(unittest.TestCase):
    def test_clarification(self):
        d = dict(ready(), decision="needs_clarification")
        r = integrate_capability_contract(d, spec())
        self.assertEqual((r["status"], r["reason"], r["contract"]),
                         ("insufficient", "needs_clarification", None))
        self.assertEqual(classify_capability_result(r), "decision_not_ready")

    def test_information_needed(self):
        d = dict(ready(), decision="needs_information")
        r = integrate_capability_contract(d, spec())
        self.assertEqual((r["status"], r["reason"], r["contract"]),
                         ("insufficient", "needs_information", None))
        self.assertEqual(classify_capability_result(r), "decision_not_ready")

    def test_real_not_ready_decision(self):
        d = decision_for("asdf qwer zxcv")
        self.assertNotEqual(d["decision"], "ready")
        self.assertEqual(outcome(d, spec()), "decision_not_ready")

    def test_invalid_plan_and_unusable_decisions(self):
        base = ready()
        bad = [None, 1, "ready", [], {}, dict(base, decision="invalid_plan"),
               dict(base, executed=True), dict(base, validation={"valid": False})]
        for d in bad:
            r = integrate_capability_contract(d, spec())
            self.assertEqual((r["status"], r["reason"], r["contract"]),
                             ("unknown", "decision_invalid", None))
            self.assertEqual(classify_capability_result(r), "decision_not_ready")

    def test_not_ready_wins_over_bad_spec(self):
        d = dict(ready(), decision="needs_information")
        self.assertEqual(outcome(d, {"junk": 1}), "decision_not_ready")
        self.assertEqual(outcome(d, None), "decision_not_ready")


class TestMissingSpec(unittest.TestCase):
    def test_no_spec(self):
        for r in (integrate_capability_contract(ready()),
                  integrate_capability_contract(ready(), None)):
            self.assertEqual((r["status"], r["reason"], r["contract"]),
                             ("unknown", "capability_unspecified", None))
            self.assertEqual(classify_capability_result(r), "spec_missing")

    def test_incomplete_spec(self):
        for field in ("name", "purpose", "required_inputs", "expected_outputs", "constraints"):
            s = spec()
            del s[field]
            r = integrate_capability_contract(ready(), s)
            self.assertEqual((r["status"], r["reason"]), ("incomplete", "missing_field"))
            self.assertEqual(classify_capability_result(r), "spec_missing")
        self.assertEqual(outcome(ready(), {}), "spec_missing")

    def test_nothing_invented(self):
        r = integrate_capability_contract(ready(), {})
        self.assertIsNone(r["contract"])


class TestInvalidSpec(unittest.TestCase):
    def test_not_dict(self):
        for s in ("x", 5, [], True):
            r = integrate_capability_contract(ready(), s)
            self.assertEqual((r["status"], r["reason"]), ("invalid", "spec_not_dict"))
            self.assertEqual(classify_capability_result(r), "spec_invalid")

    def test_malformed_fields(self):
        bad = [spec(name="Bad Name"), spec(purpose=""), spec(required_inputs="x"),
               spec(expected_outputs=[]), spec(constraints=[1]), spec(expected_outputs=["a", "a"]),
               spec(tool="t"), spec(handler="h"), spec(implementation="i"),
               spec(execution_allowed=True), spec(version=2)]
        for s in bad:
            r = integrate_capability_contract(ready(), s)
            self.assertEqual(r["status"], "invalid", s)
            self.assertIsNone(r["contract"])
            self.assertEqual(classify_capability_result(r), "spec_invalid")

    def test_execution_cannot_be_enabled(self):
        for v in (True, 1, "False", None):
            r = integrate_capability_contract(ready(), spec(execution_allowed=v))
            self.assertEqual(r["reason"], "execution_allowed_not_false")
            self.assertIsNone(r["contract"])


class TestOutcomesAreDistinct(unittest.TestCase):
    def test_four_situations(self):
        r = ready()
        got = [outcome(dict(r, decision="needs_clarification"), spec()),
               outcome(r, None), outcome(r, spec(name="")), outcome(r, spec())]
        self.assertEqual(got, ["decision_not_ready", "spec_missing",
                               "spec_invalid", "contract_valid"])
        self.assertEqual(len(set(got)), 4)

    def test_classify_unrecognised(self):
        for x in (None, 1, "x", [], {}, {"status": "built"}):
            self.assertEqual(classify_capability_result(x), "integration_error")


class TestFaultyBuilder(unittest.TestCase):
    FALLBACK = {"version": 1, "status": "invalid", "reason": "integration_result_invalid",
                "contract": None, "validation": None, "executed": False}

    def run_with(self, mutate):
        def builder(d, s):
            r = build_capability_contract(d, s)
            return mutate(r)
        return integrate_capability_contract(ready(), spec(), builder=builder)

    def test_builder_raises(self):
        def builder(d, s):
            raise RuntimeError("boom")
        self.assertEqual(integrate_capability_contract(ready(), spec(), builder=builder),
                         self.FALLBACK)

    def test_builder_returns_garbage(self):
        for junk in (None, 5, "x", [], {}, {"status": "built"}):
            self.assertEqual(self.run_with(lambda r, j=junk: j), self.FALLBACK)

    def test_execution_never_passed_on(self):
        def m1(r):
            r["contract"]["execution_allowed"] = True
            return r
        def m2(r):
            r["executed"] = True
            return r
        self.assertEqual(self.run_with(m1), self.FALLBACK)
        self.assertEqual(self.run_with(m2), self.FALLBACK)

    def test_invalid_built_contract_not_passed_on(self):
        def m(r):
            r["contract"]["name"] = "Bad Name"
            return r
        self.assertEqual(self.run_with(m), self.FALLBACK)

    def test_contract_on_non_built_status(self):
        def m(r):
            r["status"] = "invalid"
            return r
        self.assertEqual(self.run_with(m), self.FALLBACK)

    def test_extra_key_rejected(self):
        def m(r):
            r["handler"] = "run"
            return r
        self.assertEqual(self.run_with(m), self.FALLBACK)

    def test_fallback_classified_as_error(self):
        self.assertEqual(classify_capability_result(self.FALLBACK), "integration_error")

    def test_hostile_decision_and_spec_never_raise(self):
        class Boom(dict):
            def get(self, *a):
                raise RuntimeError("boom")
            def __getitem__(self, k):
                raise RuntimeError("boom")
        for d in (Boom(), object(), ready()):
            for s in (Boom(), object(), spec()):
                r = integrate_capability_contract(d, s)
                self.assertEqual(list(r), BUILD_KEYS)
                self.assertIs(r["executed"], False)


class TestFreshReadOnlyDeterministic(unittest.TestCase):
    def test_inputs_not_modified(self):
        d, s = ready(), spec()
        d0, s0 = copy.deepcopy(d), copy.deepcopy(s)
        integrate_capability_contract(d, s)
        self.assertEqual((d, s), (d0, s0))

    def test_fresh_and_unaliased(self):
        d, s = ready(), spec()
        a, b = integrate_capability_contract(d, s), integrate_capability_contract(d, s)
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        self.assertIsNot(a["contract"], b["contract"])
        a["contract"]["required_inputs"].append("x")
        self.assertEqual(s["required_inputs"], ["source_text"])
        self.assertEqual(integrate_capability_contract(d, s)["contract"]["required_inputs"],
                         ["source_text"])

    def test_json_safe(self):
        for r in (integrate_capability_contract(ready(), spec()),
                  integrate_capability_contract(ready(), {}),
                  integrate_capability_contract(None, None)):
            self.assertEqual(json.loads(json.dumps(r)), r)

    def test_bounded_on_huge_spec(self):
        s = spec(required_inputs=["i%d" % i for i in range(10000)])
        r = integrate_capability_contract(ready(), s)
        self.assertEqual((r["status"], r["reason"]), ("invalid", "too_many_items"))
        self.assertLessEqual(r["validation"]["error_count"], 16)
        big = spec()
        for i in range(5000):
            big["k%d" % i] = i
        self.assertEqual(integrate_capability_contract(ready(), big)["status"], "invalid")


class TestBackwardCompatible(unittest.TestCase):
    def test_prompt838_api_unchanged(self):
        d = ready()
        self.assertEqual(build_capability_contract(d, spec())["status"], "built")
        self.assertEqual(build_capability_contract(d)["reason"], "capability_unspecified")
        self.assertEqual(list(build_capability_contract(d, spec())), BUILD_KEYS)

    def test_prompt837_decision_unchanged(self):
        d = ready()
        integrate_capability_contract(d, spec())
        self.assertEqual(list(d), ["version", "decision", "reason", "request_status",
                                   "plan_status", "validation", "next_step", "executed"])
        self.assertEqual(decision_for("من عرفان هستم"), d)
        self.assertIs(d["executed"], False)

    def test_existing_modules_importable(self):
        import reasoning.reasoning_plan, reasoning.reasoning_plan_validation
        import reasoning.reasoning_engine
        self.assertTrue(callable(reasoning.reasoning_plan.build_reasoning_plan))

    def test_no_forbidden_imports_or_registration(self):
        with open(ci.__file__.replace(".pyc", ".py"), encoding="utf-8") as fh:
            src = fh.read()
        code = "\n".join(l for l in src.splitlines() if l.startswith(("import ", "from ")))
        for word in ("socket", "urllib", "requests", "subprocess", "random", "time",
                     "core", "memory", "ael", "execution", "tools"):
            self.assertNotIn(word, code, word)
        for name in ("register", "install", "execute", "exec(", "eval("):
            self.assertNotIn(name + "_capability", src)
        self.assertNotIn("exec(", src)
        self.assertNotIn("eval(", src)


if __name__ == "__main__":
    unittest.main()
