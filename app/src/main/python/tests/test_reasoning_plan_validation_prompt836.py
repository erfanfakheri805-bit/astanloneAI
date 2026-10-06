"""
Prompt 836 - reasoning plan validation focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_reasoning_plan_validation_prompt836 -v
"""

import copy
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from understanding.nlu_pipeline import NLUConversationContext, default_pipeline
from understanding.nlu_reasoning_input import build_reasoning_input
from reasoning.reasoning_foundation import build_reasoning_request
from reasoning.reasoning_plan import build_reasoning_plan, MAX_STEPS
from reasoning.reasoning_plan_validation import (
    validate_reasoning_plan, VALIDATION_VERSION, MAX_ERRORS,
)

P = default_pipeline()
KEYS = ["version", "valid", "status", "error_count", "errors", "truncated", "steps_checked"]


def feed(*texts):
    ctx = NLUConversationContext()
    a = None
    for i, t in enumerate(texts):
        a = P.analyze(t, ctx)
        if i < len(texts) - 1:
            ctx.record(a)
    return ctx, a


def plan_for(text, context_texts=()):
    ctx, a = feed(*context_texts, text) if context_texts else (None, P.analyze(text))
    return build_reasoning_plan(build_reasoning_request(build_reasoning_input(a, ctx)))


def full_plan():
    ctx, a = feed("پایتون چیه؟", "دوباره")
    r = build_reasoning_request(build_reasoning_input(a, ctx))
    r["known"]["slots"] = [{"kind": "k"}]
    r["known"]["relations"] = [{"kind": "r"}]
    return build_reasoning_plan(r)


def codes(plan):
    return [e["code"] for e in validate_reasoning_plan(plan)["errors"]]


def where(plan, code):
    return [e["where"] for e in validate_reasoning_plan(plan)["errors"] if e["code"] == code]


class TestValid(unittest.TestCase):
    PLANS = ("من عرفان هستم", "xqzv", "age=30 و age=31", "لطفا نام: علی را ذخیره کن", "age=30")

    def test_shape_and_key_order(self):
        r = validate_reasoning_plan(plan_for("من عرفان هستم"))
        self.assertEqual(list(r), KEYS)
        self.assertEqual(r["version"], VALIDATION_VERSION)
        self.assertEqual((r["valid"], r["status"], r["error_count"], r["errors"]),
                         (True, "valid", 0, []))
        self.assertEqual(r["steps_checked"], 3)

    def test_every_planner_output_is_valid(self):
        for t in self.PLANS:
            self.assertEqual(validate_reasoning_plan(plan_for(t))["errors"], [], t)

    def test_reference_plans_and_failure_plans_are_valid(self):
        self.assertTrue(validate_reasoning_plan(plan_for("دوباره", ("پایتون چیه؟",)))["valid"])
        self.assertTrue(validate_reasoning_plan(full_plan())["valid"])
        ctx, a = feed("دوباره")
        unresolved = build_reasoning_plan(build_reasoning_request(build_reasoning_input(a, ctx)))
        self.assertTrue(validate_reasoning_plan(unresolved)["valid"])
        for bad in (None, "x", {}, 5):
            self.assertTrue(validate_reasoning_plan(build_reasoning_plan(bad))["valid"])


class TestMalformed(unittest.TestCase):
    def test_not_a_dict(self):
        for bad in (None, "plan", 42, [], (), object()):
            r = validate_reasoning_plan(bad)
            self.assertEqual(list(r), KEYS)
            self.assertEqual((r["valid"], r["status"]), (False, "invalid"))
            self.assertEqual(r["errors"], [{"code": "plan_not_dict", "where": "plan"}])
            self.assertEqual(r["steps_checked"], 0)

    def test_empty_dict_reports_every_missing_field(self):
        r = validate_reasoning_plan({})
        self.assertEqual([e["code"] for e in r["errors"]], ["missing_field"] * 8)
        self.assertEqual(sorted(e["where"] for e in r["errors"]),
                         sorted(["version", "status", "request_status", "goal", "steps",
                                 "step_count", "truncated", "executed"]))

    def test_plan_field_errors(self):
        p = plan_for("من عرفان هستم")
        for field, value, code in (("version", 2, "invalid_version"),
                                   ("version", True, "invalid_version"),
                                   ("status", "bogus", "invalid_status"),
                                   ("request_status", 5, "invalid_request_status"),
                                   ("goal", {"intent": 1}, "invalid_goal"),
                                   ("goal", None, "invalid_goal"),
                                   ("steps", "no", "invalid_steps"),
                                   ("step_count", "3", "invalid_step_count"),
                                   ("step_count", 9, "step_count_mismatch"),
                                   ("truncated", 1, "invalid_truncated"),
                                   ("truncated", True, "contradictory_truncated"),
                                   ("executed", True, "executed_not_false"),
                                   ("executed", None, "executed_not_false")):
            q = copy.deepcopy(p)
            q[field] = value
            self.assertIn(code, codes(q), (field, value))

    def test_unexpected_plan_field(self):
        p = plan_for("من عرفان هستم")
        p["extra"] = 1
        self.assertEqual(where(p, "unexpected_field"), ["extra"])

    def test_empty_steps(self):
        p = plan_for("من عرفان هستم")
        p["steps"], p["step_count"] = [], 0
        self.assertIn("no_steps", codes(p))
        self.assertIn("address_goal_missing", codes(p))

    def test_step_field_errors(self):
        for mutate, code, w in (
                (lambda s: s.pop("detail"), "missing_step_field", "steps[0].detail"),
                (lambda s: s.update(extra=1), "unexpected_step_field", "steps[0].extra"),
                (lambda s: s.update(id=""), "invalid_step_id", "steps[0].id"),
                (lambda s: s.update(id=7), "invalid_step_id", "steps[0].id"),
                (lambda s: s.update(kind="run_tool"), "invalid_step_kind", "steps[0].kind"),
                (lambda s: s.update(ref="slotz"), "invalid_step_ref", "steps[0].ref"),
                (lambda s: s.update(detail=[1]), "invalid_step_detail", "steps[0].detail"),
                (lambda s: s.update(detail=True), "invalid_step_detail", "steps[0].detail"),
                (lambda s: s.update(depends_on="x"), "invalid_depends_on", "steps[0].depends_on"),
                (lambda s: s.update(depends_on=[1]), "invalid_depends_on", "steps[0].depends_on"),
                (lambda s: s.update(executed=True), "executed_not_false", "steps[0].executed"),
                (lambda s: s.update(executed=0), "executed_not_false", "steps[0].executed")):
            p = plan_for("من عرفان هستم")
            mutate(p["steps"][0])
            self.assertIn(w, where(p, code), (code, w))

    def test_malformed_step_entry(self):
        p = plan_for("من عرفان هستم")
        p["steps"][1] = "not a step"
        self.assertEqual(where(p, "malformed_step"), ["steps[1]"])
        p["steps"][1] = None
        self.assertIn("malformed_step", codes(p))

    def test_unstable_step_id(self):
        p = plan_for("xqzv")
        p["steps"][0]["id"] = "need.something_else"
        self.assertEqual(where(p, "unstable_step_id"), ["steps[0].id"])
        p = plan_for("من عرفان هستم")
        p["steps"][0]["id"] = "step-1"
        self.assertIn("unstable_step_id", codes(p))

    def test_duplicate_step_id(self):
        p = full_plan()
        p["steps"][1]["id"] = p["steps"][0]["id"]
        self.assertIn("duplicate_step_id", codes(p))


class TestDependencies(unittest.TestCase):
    def test_missing_dependency(self):
        p = plan_for("من عرفان هستم")
        p["steps"][-1]["depends_on"].append("ghost")
        self.assertEqual(where(p, "missing_dependency"), ["steps[2].depends_on[2]"])

    def test_self_dependency(self):
        p = plan_for("من عرفان هستم")
        p["steps"][0]["depends_on"] = ["consider_slots"]
        r = codes(p)
        self.assertIn("self_dependency", r)
        self.assertNotIn("dependency_cycle", r)

    def test_forward_dependency(self):
        p = plan_for("من عرفان هستم")
        p["steps"][0]["depends_on"] = ["address_goal"]
        r = codes(p)
        self.assertIn("forward_dependency", r)
        self.assertIn("unexpected_dependency", r)

    def test_duplicate_dependency(self):
        p = plan_for("من عرفان هستم")
        p["steps"][-1]["depends_on"] = ["consider_slots", "consider_slots", "consider_relations"]
        self.assertEqual(where(p, "duplicate_dependency"), ["steps[2].depends_on[1]"])

    def test_address_goal_must_depend_on_all_earlier_steps(self):
        p = plan_for("من عرفان هستم")
        p["steps"][-1]["depends_on"] = ["consider_slots"]
        self.assertEqual(where(p, "address_goal_dependencies"), ["steps[2].depends_on"])
        p["steps"][-1]["depends_on"] = []
        self.assertIn("address_goal_dependencies", codes(p))

    def test_only_address_goal_may_depend(self):
        p = plan_for("xqzv")
        p["steps"][0]["depends_on"] = []
        self.assertEqual(codes(p), [])
        q = full_plan()
        q["steps"][1]["depends_on"] = [q["steps"][0]["id"]]
        self.assertEqual(where(q, "unexpected_dependency"), ["steps[1].depends_on"])

    def test_too_many_dependencies(self):
        p = plan_for("من عرفان هستم")
        p["steps"][-1]["depends_on"] = ["consider_slots"] * (MAX_STEPS + 3)
        self.assertIn("too_many_dependencies", codes(p))


class TestCycles(unittest.TestCase):
    def test_two_step_cycle_reported_once(self):
        p = full_plan()
        a, b = p["steps"][0], p["steps"][1]
        a["depends_on"], b["depends_on"] = [b["id"]], [a["id"]]
        r = validate_reasoning_plan(p)
        self.assertEqual([e for e in r["errors"] if e["code"] == "dependency_cycle"],
                         [{"code": "dependency_cycle", "where": "steps[0]"}])
        self.assertIn("forward_dependency", codes(p))

    def test_three_step_cycle(self):
        p = full_plan()
        ids = [s["id"] for s in p["steps"]]
        p["steps"][0]["depends_on"] = [ids[2]]
        p["steps"][1]["depends_on"] = [ids[0]]
        p["steps"][2]["depends_on"] = [ids[1]]
        self.assertEqual(codes(p).count("dependency_cycle"), 1)

    def test_two_independent_cycles_reported_separately(self):
        p = full_plan()
        ids = [s["id"] for s in p["steps"]]
        p["steps"][0]["depends_on"] = [ids[1]]
        p["steps"][1]["depends_on"] = [ids[0]]
        p["steps"][2]["depends_on"] = [ids[3]]
        p["steps"][3]["depends_on"] = [ids[2]]
        self.assertEqual(where(p, "dependency_cycle"), ["steps[0]", "steps[2]"])

    def test_acyclic_plan_has_no_cycle_error(self):
        self.assertNotIn("dependency_cycle", codes(full_plan()))


class TestContradictions(unittest.TestCase):
    def test_ready_with_need_step(self):
        p = plan_for("من عرفان هستم")
        p["steps"].insert(0, {"id": "need.intent_unknown", "kind": "need", "ref": "intent_unknown",
                              "detail": None, "depends_on": [], "executed": False})
        p["step_count"] = len(p["steps"])
        self.assertIn("contradictory_status", codes(p))

    def test_not_ready_with_goal_step(self):
        p = plan_for("xqzv")
        p["steps"].append({"id": "address_goal", "kind": "address_goal", "ref": "x",
                           "detail": None, "depends_on": ["need.intent_unknown"], "executed": False})
        p["step_count"] = 2
        self.assertIn("contradictory_status", codes(p))

    def test_status_clarification_vs_clarify_steps(self):
        p = plan_for("age=30 و age=31")
        self.assertEqual(p["status"], "needs_clarification")
        p["status"] = "needs_information"
        self.assertIn("contradictory_status", codes(p))
        q = plan_for("xqzv")
        q["status"] = "needs_clarification"
        self.assertIn("contradictory_status", codes(q))

    def test_ready_without_known_goal(self):
        p = plan_for("من عرفان هستم")
        p["goal"] = {"intent": None, "source": None, "state": "unresolved"}
        self.assertIn("contradictory_goal", codes(p))

    def test_goal_mismatch(self):
        p = plan_for("من عرفان هستم")
        p["goal"]["intent"] = "other"
        self.assertEqual(where(p, "goal_mismatch"), ["steps[2]"])
        p = plan_for("من عرفان هستم")
        p["goal"]["source"] = "inherited"
        self.assertIn("goal_mismatch", codes(p))

    def test_address_goal_missing_and_misplaced(self):
        p = plan_for("من عرفان هستم")
        p["steps"].pop()
        p["step_count"] = 2
        self.assertIn("address_goal_missing", codes(p))
        q = plan_for("من عرفان هستم")
        q["steps"].reverse()
        self.assertIn("address_goal_misplaced", codes(q))
        r = plan_for("من عرفان هستم")
        r["steps"].append(copy.deepcopy(r["steps"][-1]))
        r["step_count"] = 4
        self.assertIn("address_goal_misplaced", codes(r))

    def test_consider_step_order(self):
        p = full_plan()
        p["steps"][1], p["steps"][2] = p["steps"][2], p["steps"][1]
        self.assertEqual(where(p, "step_order_violation"), ["steps[2]"])


class TestBounds(unittest.TestCase):
    def test_too_many_steps_examines_only_the_bound(self):
        p = plan_for("xqzv")
        step = p["steps"][0]
        p["steps"] = [copy.deepcopy(step) for _ in range(500)]
        p["step_count"] = 500
        r = validate_reasoning_plan(p)
        self.assertIn("too_many_steps", [e["code"] for e in r["errors"]])
        self.assertEqual(r["steps_checked"], MAX_STEPS)
        self.assertLessEqual(len(r["errors"]), MAX_ERRORS)

    def test_exactly_max_steps_is_allowed(self):
        p = plan_for("xqzv")
        base = p["steps"][0]
        p["steps"] = []
        for i in range(MAX_STEPS):
            s = copy.deepcopy(base)
            s["ref"] = "intent_unknown"
            s["id"] = "need.intent_unknown"
            p["steps"].append(s)
        p["step_count"] = MAX_STEPS
        self.assertNotIn("too_many_steps", codes(p))

    def test_errors_are_bounded_and_truncation_is_reported(self):
        p = {"version": "x", "status": 1, "request_status": 1, "goal": 1,
             "steps": [{"x%d" % k: 1 for k in range(8)} for _ in range(8)],
             "step_count": "x", "truncated": "x", "executed": 1, "extra1": 1, "extra2": 2}
        r = validate_reasoning_plan(p)
        self.assertEqual(len(r["errors"]), MAX_ERRORS)
        self.assertEqual(r["error_count"], MAX_ERRORS)
        self.assertTrue(r["truncated"])
        self.assertFalse(r["valid"])

    def test_no_duplicate_errors(self):
        p = {"steps": [{}] * 3}
        errs = [(e["code"], e["where"]) for e in validate_reasoning_plan(p)["errors"]]
        self.assertEqual(len(errs), len(set(errs)))

    def test_huge_dependency_list_is_bounded(self):
        p = plan_for("من عرفان هستم")
        p["steps"][-1]["depends_on"] = ["consider_slots"] * 100000
        r = validate_reasoning_plan(p)
        self.assertLessEqual(len(r["errors"]), MAX_ERRORS)
        self.assertIn("too_many_dependencies", [e["code"] for e in r["errors"]])


class TestGuarantees(unittest.TestCase):
    def test_deterministic_json_safe_fresh(self):
        p = full_plan()
        p["steps"][0]["depends_on"] = ["ghost"]
        r1, r2 = validate_reasoning_plan(p), validate_reasoning_plan(p)
        self.assertEqual(r1, r2)
        self.assertEqual(json.loads(json.dumps(r1)), r1)
        r1["errors"].append("x")
        r1["valid"] = True
        self.assertNotIn("x", validate_reasoning_plan(p)["errors"])
        self.assertFalse(validate_reasoning_plan(p)["valid"])

    def test_plan_is_never_modified_or_repaired(self):
        for mutate in (lambda p: p["steps"][0].update(executed=True),
                       lambda p: p["steps"][0].update(depends_on=["ghost"]),
                       lambda p: p.update(status="bogus"),
                       lambda p: p["steps"].reverse()):
            p = full_plan()
            mutate(p)
            before = copy.deepcopy(p)
            validate_reasoning_plan(p)
            self.assertEqual(p, before)

    def test_never_raises_on_hostile_input(self):
        class Boom(dict):
            def get(self, *a):
                raise RuntimeError("boom")

            def __iter__(self):
                raise RuntimeError("boom")

        cyclic = []
        cyclic.append(cyclic)
        for bad in (Boom(), {"steps": cyclic}, {"steps": [cyclic]}, {"steps": [{"depends_on": cyclic}]},
                    {"goal": cyclic, "steps": [None, 1, "x", [], {}]}, {1: 2, "steps": [{3: 4}]}):
            r = validate_reasoning_plan(bad)
            self.assertEqual(list(r), KEYS)
            self.assertFalse(r["valid"])

    def test_no_execution_or_other_layers(self):
        import reasoning.reasoning_plan_validation as m
        with open(m.__file__, encoding="utf-8") as fh:
            src = fh.read()
        for banned in ("import core", "from core", "memory", "ael", "urllib", "socket",
                       "requests", "open(", "import os", "subprocess", "exec(", "eval("):
            self.assertNotIn(banned, src, banned)


class TestBackwardCompatible(unittest.TestCase):
    def test_existing_apis_unchanged_by_validation(self):
        ctx, a = feed("پایتون چیه؟", "دوباره")
        ri = a.reasoning_input(ctx)
        req = build_reasoning_request(ri)
        plan = build_reasoning_plan(req)
        n, v, res = a.normalized(), a.semantic_view(), a.resolve_references(ctx)
        reqb, planb = copy.deepcopy(req), copy.deepcopy(plan)
        validate_reasoning_plan(plan)
        self.assertEqual((req, plan), (reqb, planb))
        self.assertEqual(build_reasoning_request(ri), req)
        self.assertEqual(build_reasoning_plan(req), plan)
        self.assertEqual((a.normalized(), a.semantic_view(), a.resolve_references(ctx),
                          a.reasoning_input(ctx)), (n, v, res, ri))

    def test_planner_output_shape_is_what_the_validator_expects(self):
        p = full_plan()
        self.assertEqual(set(p), {"version", "status", "request_status", "goal", "steps",
                                  "step_count", "truncated", "executed"})
        self.assertEqual(set(p["steps"][0]), {"id", "kind", "ref", "detail", "depends_on", "executed"})


if __name__ == "__main__":
    unittest.main()
