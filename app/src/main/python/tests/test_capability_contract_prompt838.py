"""
Prompt 838 - capability contract foundation focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_capability_contract_prompt838 -v
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
from reasoning import capability_contract as cc
from reasoning.capability_contract import (
    build_capability_contract, validate_capability_contract,
)

P = default_pipeline()
CONTRACT_KEYS = ["version", "name", "purpose", "required_inputs", "expected_outputs",
                 "constraints", "execution_allowed"]
BUILD_KEYS = ["version", "status", "reason", "contract", "validation", "executed"]
VALIDATION_KEYS = ["version", "valid", "status", "error_count", "errors", "truncated"]


def decision_for(text):
    return decide_reasoning(build_reasoning_request(build_reasoning_input(P.analyze(text), None)))


def ready_decision():
    d = decision_for("من عرفان هستم")
    assert d["decision"] == "ready"
    return d


def spec(**over):
    s = {"name": "text_summary", "purpose": "Summarise a supplied text",
         "required_inputs": ["source_text"], "expected_outputs": ["summary_text"],
         "constraints": ["read only", "no network"]}
    s.update(over)
    return s


def codes(result):
    return [e["code"] for e in result["errors"]]


def valid_contract():
    return build_capability_contract(ready_decision(), spec())["contract"]


class TestValid(unittest.TestCase):
    def test_built_shape(self):
        r = build_capability_contract(ready_decision(), spec())
        self.assertEqual(list(r), BUILD_KEYS)
        self.assertEqual((r["status"], r["reason"], r["executed"]), ("built", "built", False))
        self.assertEqual(list(r["contract"]), CONTRACT_KEYS)
        self.assertIs(r["contract"]["execution_allowed"], False)
        self.assertEqual(r["contract"]["name"], "text_summary")
        self.assertTrue(r["validation"]["valid"])
        self.assertEqual(list(r["validation"]), VALIDATION_KEYS)

    def test_contract_is_exactly_the_supplied_information(self):
        s = spec()
        c = build_capability_contract(ready_decision(), s)["contract"]
        for key in ("name", "purpose", "required_inputs", "expected_outputs", "constraints"):
            self.assertEqual(c[key], s[key])

    def test_empty_inputs_and_constraints_allowed(self):
        r = build_capability_contract(ready_decision(),
                                      spec(required_inputs=[], constraints=[]))
        self.assertEqual(r["status"], "built")

    def test_validator_accepts_built_contract(self):
        v = validate_capability_contract(valid_contract())
        self.assertEqual((v["valid"], v["status"], v["error_count"]), (True, "valid", 0))

    def test_json_safe_and_deterministic(self):
        d, s = ready_decision(), spec()
        a, b = build_capability_contract(d, s), build_capability_contract(d, s)
        self.assertEqual(a, b)
        self.assertEqual(json.loads(json.dumps(a)), a)

    def test_tolerated_optional_spec_fields(self):
        r = build_capability_contract(ready_decision(),
                                      spec(version=1, execution_allowed=False))
        self.assertEqual(r["status"], "built")

    def test_boundary_sizes(self):
        r = build_capability_contract(ready_decision(), spec(
            name="a" * cc.MAX_NAME_LENGTH, purpose="p" * cc.MAX_TEXT_LENGTH,
            required_inputs=["i%d" % i for i in range(cc.MAX_ITEMS)],
            constraints=["c" * cc.MAX_CONSTRAINT_LENGTH]))
        self.assertEqual(r["status"], "built")


class TestFreshAndReadOnly(unittest.TestCase):
    def test_inputs_not_modified(self):
        d, s = ready_decision(), spec()
        d0, s0 = copy.deepcopy(d), copy.deepcopy(s)
        build_capability_contract(d, s)
        self.assertEqual((d, s), (d0, s0))

    def test_result_does_not_alias_spec(self):
        s = spec()
        r = build_capability_contract(ready_decision(), s)
        r["contract"]["required_inputs"].append("x")
        self.assertEqual(s["required_inputs"], ["source_text"])
        r2 = build_capability_contract(ready_decision(), s)
        self.assertEqual(r2["contract"]["required_inputs"], ["source_text"])

    def test_results_are_fresh(self):
        d, s = ready_decision(), spec()
        a, b = build_capability_contract(d, s), build_capability_contract(d, s)
        self.assertIsNot(a, b)
        self.assertIsNot(a["contract"], b["contract"])

    def test_validator_does_not_modify_contract(self):
        c = valid_contract()
        c0 = copy.deepcopy(c)
        validate_capability_contract(c)
        self.assertEqual(c, c0)


class TestUnknownAndInsufficient(unittest.TestCase):
    def assert_nothing_created(self, r, status, reason):
        self.assertEqual(list(r), BUILD_KEYS)
        self.assertEqual((r["status"], r["reason"]), (status, reason))
        self.assertIsNone(r["contract"])
        self.assertIs(r["executed"], False)

    def test_no_spec_creates_no_capability(self):
        self.assert_nothing_created(build_capability_contract(ready_decision()),
                                    "unknown", "capability_unspecified")
        self.assert_nothing_created(build_capability_contract(ready_decision(), None),
                                    "unknown", "capability_unspecified")

    def test_unknown_request_decision(self):
        d = decision_for("asdf qwer zxcv")
        self.assertNotEqual(d["decision"], "ready")
        r = build_capability_contract(d, spec())
        self.assertEqual(r["status"], "insufficient")
        self.assertIsNone(r["contract"])

    def test_needs_clarification_and_information(self):
        base = ready_decision()
        for name in ("needs_clarification", "needs_information"):
            d = dict(base, decision=name)
            self.assert_nothing_created(build_capability_contract(d, spec()),
                                        "insufficient", name)

    def test_invalid_plan_decision(self):
        d = dict(ready_decision(), decision="invalid_plan")
        self.assert_nothing_created(build_capability_contract(d, spec()),
                                    "unknown", "decision_invalid")

    def test_unusable_decisions(self):
        base = ready_decision()
        bad = [None, 5, "ready", [], {}, dict(base, decision="bogus"),
               dict(base, decision=None), dict(base, executed=True),
               dict(base, executed=None), dict(base, validation=None),
               dict(base, validation={"valid": False}),
               {k: v for k, v in base.items() if k != "validation"}]
        for d in bad:
            self.assert_nothing_created(build_capability_contract(d, spec()),
                                        "unknown", "decision_invalid")

    def test_spec_never_invented_from_decision(self):
        r = build_capability_contract(ready_decision(), {})
        self.assertEqual(r["status"], "incomplete")
        self.assertIsNone(r["contract"])


class TestIncomplete(unittest.TestCase):
    def test_each_missing_field(self):
        for field in ("name", "purpose", "required_inputs", "expected_outputs", "constraints"):
            s = spec()
            del s[field]
            r = build_capability_contract(ready_decision(), s)
            self.assertEqual((r["status"], r["reason"]), ("incomplete", "missing_field"), field)
            self.assertIsNone(r["contract"])
            self.assertEqual(r["validation"]["errors"], [{"code": "missing_field", "where": field}])

    def test_all_missing(self):
        r = build_capability_contract(ready_decision(), {})
        self.assertEqual(r["status"], "incomplete")
        self.assertEqual(r["validation"]["error_count"], 5)


class TestMalformedSpec(unittest.TestCase):
    def build(self, **over):
        return build_capability_contract(ready_decision(), spec(**over))

    def test_spec_not_dict(self):
        for s in ("x", 5, [], (), True):
            r = build_capability_contract(ready_decision(), s)
            self.assertEqual((r["status"], r["reason"]), ("invalid", "spec_not_dict"))
            self.assertIsNone(r["contract"])

    def test_invalid_name(self):
        for n in ("", "Text", "text summary", "1abc", None, 5, "a" * 65, "x-y", " a"):
            r = self.build(name=n)
            self.assertEqual((r["status"], r["reason"]), ("invalid", "invalid_name"), repr(n))

    def test_invalid_purpose(self):
        for p in ("", " x", "x ", "a\nb", None, 3, "p" * 201):
            r = self.build(purpose=p)
            self.assertEqual(r["reason"], "invalid_purpose", repr(p))
            self.assertEqual(r["status"], "invalid")

    def test_invalid_list_types(self):
        for field, code in (("required_inputs", "invalid_required_inputs"),
                            ("expected_outputs", "invalid_expected_outputs"),
                            ("constraints", "invalid_constraints")):
            for bad in ("x", None, ("a",), {"a": 1}, 4):
                r = self.build(**{field: bad})
                self.assertEqual((r["status"], r["reason"]), ("invalid", code), (field, bad))

    def test_invalid_items(self):
        r = self.build(required_inputs=["ok", "Bad Name"])
        self.assertEqual(r["validation"]["errors"],
                         [{"code": "invalid_item", "where": "required_inputs[1]"}])
        r = self.build(expected_outputs=[5])
        self.assertEqual(r["reason"], "invalid_item")
        r = self.build(constraints=[""])
        self.assertEqual(r["reason"], "invalid_item")

    def test_duplicates(self):
        r = self.build(expected_outputs=["a", "a"])
        self.assertEqual(r["validation"]["errors"],
                         [{"code": "duplicate_item", "where": "expected_outputs[1]"}])

    def test_no_expected_outputs(self):
        r = self.build(expected_outputs=[])
        self.assertEqual((r["status"], r["reason"]), ("invalid", "no_expected_outputs"))

    def test_too_many_items_bounded(self):
        r = self.build(required_inputs=["i%d" % i for i in range(10000)])
        self.assertEqual((r["status"], r["reason"]), ("invalid", "too_many_items"))
        self.assertLessEqual(r["validation"]["error_count"], cc.MAX_ERRORS)

    def test_implementation_details_rejected_not_kept(self):
        for extra in ("tool", "implementation", "handler", "registry"):
            r = self.build(**{extra: "anything"})
            self.assertEqual((r["status"], r["reason"]), ("invalid", "unexpected_field"), extra)
            self.assertIsNone(r["contract"])

    def test_execution_cannot_be_enabled(self):
        for v in (True, 1, "False", None):
            r = self.build(execution_allowed=v)
            self.assertEqual((r["status"], r["reason"]),
                             ("invalid", "execution_allowed_not_false"), repr(v))

    def test_bad_version(self):
        for v in (2, "1", True, None, 1.0):
            self.assertEqual(self.build(version=v)["reason"], "invalid_version", repr(v))

    def test_huge_spec_is_bounded(self):
        s = spec()
        for i in range(5000):
            s["junk%d" % i] = i
        r = build_capability_contract(ready_decision(), s)
        self.assertEqual((r["status"], r["reason"]), ("invalid", "unexpected_field"))

    def test_non_string_keys(self):
        s = spec()
        s[5] = "x"
        r = build_capability_contract(ready_decision(), s)
        self.assertEqual(r["status"], "invalid")
        self.assertEqual(r["validation"]["errors"][0], {"code": "unexpected_field", "where": "<field>"})


class TestValidator(unittest.TestCase):
    def test_shape(self):
        v = validate_capability_contract(valid_contract())
        self.assertEqual(list(v), VALIDATION_KEYS)

    def test_not_dict(self):
        for c in (None, 1, "x", [], ()):
            v = validate_capability_contract(c)
            self.assertEqual((v["valid"], codes(v)), (False, ["contract_not_dict"]))

    def test_missing_and_unexpected(self):
        c = valid_contract()
        del c["constraints"]
        c["extra"] = 1
        self.assertEqual(codes(validate_capability_contract(c)),
                         ["missing_field", "unexpected_field"])

    def test_execution_allowed_must_be_false(self):
        for v in (True, 0, None, "no"):
            c = valid_contract()
            c["execution_allowed"] = v
            self.assertEqual(codes(validate_capability_contract(c)),
                             ["execution_allowed_not_false"])

    def test_collects_all_errors_in_order(self):
        c = valid_contract()
        c["name"] = "Bad"
        c["purpose"] = ""
        c["expected_outputs"] = []
        self.assertEqual(codes(validate_capability_contract(c)),
                         ["invalid_name", "invalid_purpose", "no_expected_outputs"])

    def test_errors_bounded_and_truncated(self):
        c = valid_contract()
        c["required_inputs"] = [1] * cc.MAX_ITEMS
        c["constraints"] = [1] * cc.MAX_ITEMS
        v = validate_capability_contract(c)
        self.assertEqual(v["error_count"], cc.MAX_ERRORS)
        self.assertTrue(v["truncated"])

    def test_tuple_in_contract_is_malformed(self):
        c = valid_contract()
        c["expected_outputs"] = ("a",)
        self.assertEqual(codes(validate_capability_contract(c)), ["invalid_expected_outputs"])

    def test_never_raises_on_hostile_input(self):
        class Boom(dict):
            def __iter__(self):
                raise RuntimeError("boom")
            def __contains__(self, k):
                raise RuntimeError("boom")
        v = validate_capability_contract(Boom())
        self.assertFalse(v["valid"])
        self.assertEqual(codes(v), ["validator_error"])

    def test_deterministic(self):
        c = valid_contract()
        c["name"] = "X"
        self.assertEqual(validate_capability_contract(c), validate_capability_contract(c))


class TestNonRaising(unittest.TestCase):
    def test_hostile_inputs(self):
        class Boom(dict):
            def get(self, *a):
                raise RuntimeError("boom")
            def __getitem__(self, k):
                raise RuntimeError("boom")
        for d in (Boom(), object(), ready_decision()):
            for s in (Boom(), object(), 7, spec()):
                r = build_capability_contract(d, s)
                self.assertEqual(list(r), BUILD_KEYS)
                self.assertIs(r["executed"], False)

    def test_no_second_argument(self):
        self.assertEqual(build_capability_contract(None)["status"], "unknown")


class TestBackwardCompatible(unittest.TestCase):
    def test_decision_pipeline_unchanged(self):
        d = ready_decision()
        self.assertEqual(list(d), ["version", "decision", "reason", "request_status",
                                   "plan_status", "validation", "next_step", "executed"])
        self.assertIs(d["executed"], False)

    def test_building_does_not_change_later_decisions(self):
        before = decision_for("من عرفان هستم")
        build_capability_contract(before, spec())
        self.assertEqual(decision_for("من عرفان هستم"), before)

    def test_existing_reasoning_modules_still_importable(self):
        import reasoning.reasoning_plan, reasoning.reasoning_plan_validation
        import reasoning.reasoning_engine, reasoning.reasoning_foundation
        self.assertTrue(callable(reasoning.reasoning_plan.build_reasoning_plan))

    def test_module_has_no_forbidden_imports(self):
        with open(cc.__file__.replace(".pyc", ".py"), encoding="utf-8") as fh:
            src = fh.read()
        for word in ("import socket", "import urllib", "import requests", "import subprocess",
                     "import random", "import time", "core.", "memory", "ael"):
            self.assertNotIn(word, src.replace("Memory, AEL, Core", ""), word)


if __name__ == "__main__":
    unittest.main()
