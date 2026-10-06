"""
Prompt 837 - reasoning decision pipeline focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_reasoning_decision_prompt837 -v
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
from reasoning.reasoning_plan import build_reasoning_plan
from reasoning.reasoning_plan_validation import validate_reasoning_plan
from reasoning.reasoning_decision import decide_reasoning, DECISION_VERSION

P = default_pipeline()
KEYS = ["version", "decision", "reason", "request_status", "plan_status",
        "validation", "next_step", "executed"]
VALIDATION_KEYS = ["version", "valid", "status", "error_count", "errors", "truncated", "steps_checked"]


def feed(*texts):
    ctx = NLUConversationContext()
    a = None
    for i, t in enumerate(texts):
        a = P.analyze(t, ctx)
        if i < len(texts) - 1:
            ctx.record(a)
    return ctx, a


def request(text, context_texts=()):
    if context_texts:
        ctx, a = feed(*context_texts, text)
    else:
        ctx, a = None, P.analyze(text)
    return build_reasoning_request(build_reasoning_input(a, ctx))


def broken(mutate):
    """A planner that returns the real plan after `mutate` damaged it."""
    def builder(req):
        plan = build_reasoning_plan(req)
        mutate(plan)
        return plan
    return builder


class TestReady(unittest.TestCase):
    def test_shape_and_key_order(self):
        r = decide_reasoning(request("من عرفان هستم"))
        self.assertEqual(list(r), KEYS)
        self.assertEqual(list(r["validation"]), VALIDATION_KEYS)
        self.assertEqual(r["version"], DECISION_VERSION)

    def test_ready_decision(self):
        r = decide_reasoning(request("من عرفان هستم"))
        self.assertEqual((r["decision"], r["reason"]), ("ready", "ready"))
        self.assertEqual((r["request_status"], r["plan_status"]), ("ready", "ready"))
        self.assertTrue(r["validation"]["valid"])
        self.assertEqual(r["next_step"], {"id": "consider_slots", "kind": "consider_slots",
                                          "ref": "slots", "detail": 1, "remaining": 2})
        self.assertIs(r["executed"], False)

    def test_single_step_ready(self):
        view = {"intent": {"primary": "greeting", "effective": "greeting", "recognized": True},
                "context": {}}
        r = decide_reasoning(build_reasoning_request(build_reasoning_input(view)))
        self.assertEqual(r["decision"], "ready")
        self.assertEqual(r["next_step"], {"id": "address_goal", "kind": "address_goal",
                                          "ref": "greeting", "detail": "primary", "remaining": 0})

    def test_ready_with_resolved_reference(self):
        r = decide_reasoning(request("دوباره", ("پایتون چیه؟",)))
        self.assertEqual(r["decision"], "ready")
        self.assertEqual(r["next_step"]["id"], "consider_reference")
        self.assertEqual(r["next_step"]["remaining"], 1)

    def test_matches_existing_layers(self):
        req = request("لطفا نام: علی را ذخیره کن")
        plan = build_reasoning_plan(req)
        r = decide_reasoning(req)
        self.assertEqual(r["validation"], validate_reasoning_plan(plan))
        self.assertEqual(r["plan_status"], plan["status"])
        self.assertEqual(r["request_status"], req["status"])
        self.assertEqual(r["next_step"]["id"], plan["steps"][0]["id"])
        self.assertEqual(r["next_step"]["remaining"], len(plan["steps"]) - 1)


class TestClarification(unittest.TestCase):
    def test_ambiguous_relations(self):
        r = decide_reasoning(request("age=30 و age=31"))
        self.assertEqual(r["decision"], "needs_clarification")
        self.assertEqual(r["reason"], "relations_ambiguous")
        self.assertEqual((r["request_status"], r["plan_status"]), ("ambiguous", "needs_clarification"))
        self.assertTrue(r["validation"]["valid"])
        self.assertEqual(r["next_step"]["kind"], "clarify")
        self.assertEqual(r["next_step"]["detail"], 1)

    def test_ambiguous_reference(self):
        req = request("من عرفان هستم")
        req["status"] = "ambiguous"
        req["unresolved"] = [{"code": "reference_ambiguous", "detail": "context_mismatch"}]
        r = decide_reasoning(req)
        self.assertEqual(r["decision"], "needs_clarification")
        self.assertEqual(r["next_step"]["id"], "clarify.reference_ambiguous")
        self.assertNotEqual(r["decision"], "ready")


class TestNeedsInformation(unittest.TestCase):
    def test_unknown_request(self):
        r = decide_reasoning(request("xqzv"))
        self.assertEqual((r["decision"], r["reason"]), ("needs_information", "intent_unknown"))
        self.assertEqual((r["request_status"], r["plan_status"]), ("unknown", "needs_information"))
        self.assertEqual(r["next_step"]["id"], "need.intent_unknown")

    def test_unresolved_reference(self):
        ctx, a = feed("دوباره")
        r = decide_reasoning(build_reasoning_request(build_reasoning_input(a, ctx)))
        self.assertEqual(r["decision"], "needs_information")
        self.assertEqual(r["request_status"], "unresolved")
        self.assertEqual(r["next_step"]["id"], "need.reference_unresolved")
        self.assertEqual(r["next_step"]["detail"], "no_previous_turn")

    def test_missing_information(self):
        ri = build_reasoning_input(P.analyze("من عرفان هستم"))
        ri["unresolved"]["slots_truncated"] = True
        req = build_reasoning_request(ri)
        self.assertEqual(req["status"], "missing")
        r = decide_reasoning(req)
        self.assertEqual((r["decision"], r["reason"]), ("needs_information", "slots_truncated"))
        self.assertEqual(r["request_status"], "missing")

    def test_slots_alone_never_ready(self):
        self.assertNotEqual(decide_reasoning(request("age=30"))["decision"], "ready")


class TestInvalidPlan(unittest.TestCase):
    def test_plan_marked_executed(self):
        r = decide_reasoning(request("من عرفان هستم"),
                             broken(lambda p: p["steps"][0].update(executed=True)))
        self.assertEqual((r["decision"], r["reason"]), ("invalid_plan", "executed_not_false"))
        self.assertFalse(r["validation"]["valid"])
        self.assertEqual(r["plan_status"], "ready")
        self.assertIsNone(r["next_step"])
        self.assertIs(r["executed"], False)

    def test_cyclic_plan(self):
        def cycle(p):
            a, b = p["steps"][0], p["steps"][1]
            a["depends_on"], b["depends_on"] = [b["id"]], [a["id"]]
        r = decide_reasoning(request("من عرفان هستم"), broken(cycle))
        self.assertEqual(r["decision"], "invalid_plan")
        self.assertIn("dependency_cycle", [e["code"] for e in r["validation"]["errors"]])
        self.assertIsNone(r["next_step"])

    def test_missing_dependency_and_bad_ids(self):
        for mutate, code in ((lambda p: p["steps"][-1]["depends_on"].append("ghost"), "missing_dependency"),
                             (lambda p: p["steps"][0].update(id="step-1"), "unstable_step_id"),
                             (lambda p: p.update(status="bogus"), "invalid_status")):
            r = decide_reasoning(request("من عرفان هستم"), broken(mutate))
            self.assertEqual(r["decision"], "invalid_plan", code)
            self.assertIn(code, [e["code"] for e in r["validation"]["errors"]])

    def test_contradictory_ready_plan_is_never_ready(self):
        def contradict(p):
            p["steps"].insert(0, {"id": "need.intent_unknown", "kind": "need", "ref": "intent_unknown",
                                  "detail": None, "depends_on": [], "executed": False})
            p["step_count"] = len(p["steps"])
        r = decide_reasoning(request("من عرفان هستم"), broken(contradict))
        self.assertEqual(r["decision"], "invalid_plan")

    def test_planner_returns_nothing_usable(self):
        for builder in (lambda req: None, lambda req: "plan", lambda req: [], lambda req: {}):
            r = decide_reasoning(request("من عرفان هستم"), builder)
            self.assertEqual(r["decision"], "invalid_plan")
            self.assertIsNone(r["plan_status"])
            self.assertIsNone(r["next_step"])

    def test_planner_raises(self):
        def boom(req):
            raise RuntimeError("boom")
        r = decide_reasoning(request("من عرفان هستم"), boom)
        self.assertEqual((r["decision"], r["reason"]), ("invalid_plan", "plan_not_dict"))
        self.assertEqual(list(r), KEYS)

    def test_invalid_plan_is_not_repaired(self):
        holder = {}

        def builder(req):
            plan = build_reasoning_plan(req)
            plan["steps"][0]["executed"] = True
            holder["plan"] = plan
            return plan
        r = decide_reasoning(request("من عرفان هستم"), builder)
        before = copy.deepcopy(holder["plan"])
        self.assertEqual(r["decision"], "invalid_plan")
        self.assertIs(holder["plan"]["steps"][0]["executed"], True)
        self.assertEqual(holder["plan"], before)


class TestMalformedInput(unittest.TestCase):
    def test_none_request(self):
        r = decide_reasoning(None)
        self.assertEqual((r["decision"], r["reason"]), ("needs_information", "reasoning_request_missing"))
        self.assertIsNone(r["request_status"])
        self.assertTrue(r["validation"]["valid"])

    def test_malformed_requests(self):
        good = request("من عرفان هستم")
        bad_code = copy.deepcopy(good)
        bad_code["missing"] = ["made_up"]
        for bad in ("text", 42, [], {}, object(), bad_code,
                    {"goal": 1, "known": 2, "unresolved": 3, "missing": 4}):
            r = decide_reasoning(bad)
            self.assertEqual(list(r), KEYS)
            self.assertEqual(r["decision"], "needs_information")
            self.assertEqual(r["reason"], "reasoning_request_invalid")
            self.assertNotEqual(r["decision"], "ready")
            self.assertIs(r["executed"], False)

    def test_request_status_conflict_is_never_ready(self):
        req = request("من عرفان هستم")
        req["status"] = "unknown"
        r = decide_reasoning(req)
        self.assertEqual((r["decision"], r["reason"]), ("needs_information", "request_status_conflict"))
        self.assertEqual((r["request_status"], r["plan_status"]), ("unknown", "ready"))
        self.assertIsNone(r["next_step"])
        req["status"] = "ambiguous"
        r = decide_reasoning(req)
        self.assertEqual((r["decision"], r["reason"]), ("needs_clarification", "request_status_conflict"))
        req["status"] = "bogus"
        r = decide_reasoning(req)
        self.assertEqual(r["decision"], "needs_information")
        self.assertIsNone(r["request_status"])

    def test_hostile_request_never_raises(self):
        class Boom(dict):
            def get(self, *a):
                raise RuntimeError("boom")

            def __getitem__(self, k):
                raise RuntimeError("boom")

            def __iter__(self):
                raise RuntimeError("boom")
        cyc = []
        cyc.append(cyc)
        for bad in (Boom(), {"goal": cyc, "known": cyc, "unresolved": cyc, "missing": cyc}):
            r = decide_reasoning(bad)
            self.assertEqual(list(r), KEYS)
            self.assertNotEqual(r["decision"], "ready")


class TestGuarantees(unittest.TestCase):
    TEXTS = ("من عرفان هستم", "xqzv", "age=30 و age=31", "لطفا نام: علی را ذخیره کن", "age=30")

    def test_json_safe_deterministic_fixed_shape(self):
        for t in self.TEXTS:
            req = request(t)
            r1, r2 = decide_reasoning(req), decide_reasoning(req)
            self.assertEqual(r1, r2)
            self.assertEqual(list(r1), KEYS)
            self.assertEqual(json.loads(json.dumps(r1, ensure_ascii=False)), r1)
            self.assertIs(r1["executed"], False)

    def test_decision_vocabulary_and_ready_conditions(self):
        for t in self.TEXTS:
            r = decide_reasoning(request(t))
            self.assertIn(r["decision"], ("ready", "needs_clarification",
                                          "needs_information", "invalid_plan"))
            if r["decision"] == "ready":
                self.assertEqual((r["request_status"], r["plan_status"]), ("ready", "ready"))
                self.assertTrue(r["validation"]["valid"])
                self.assertIsNotNone(r["next_step"])
            elif r["decision"] != "invalid_plan":
                self.assertNotEqual(r["plan_status"], "ready")

    def test_request_not_modified_and_result_is_fresh(self):
        req = request("لطفا نام: علی را ذخیره کن")
        before = copy.deepcopy(req)
        r1 = decide_reasoning(req)
        self.assertEqual(req, before)
        r1["validation"]["errors"].append("x")
        r1["next_step"]["id"] = "changed"
        r1["decision"] = "changed"
        r2 = decide_reasoning(req)
        self.assertEqual(r2["validation"]["errors"], [])
        self.assertNotEqual(r2["next_step"]["id"], "changed")
        self.assertEqual(r2["decision"], "ready")

    def test_bounded_result(self):
        r = decide_reasoning(request("من عرفان هستم"),
                             broken(lambda p: p.update(**{"x%d" % i: 1 for i in range(100)})))
        self.assertEqual(r["decision"], "invalid_plan")
        self.assertLessEqual(len(r["validation"]["errors"]), 16)
        self.assertLessEqual(len(json.dumps(r)), 3000)

    def test_next_step_is_only_a_description(self):
        r = decide_reasoning(request("من عرفان هستم"))
        self.assertEqual(set(r["next_step"]), {"id", "kind", "ref", "detail", "remaining"})

    def test_no_execution_or_other_layers(self):
        import reasoning.reasoning_decision as m
        with open(m.__file__, encoding="utf-8") as fh:
            src = fh.read()
        for banned in ("import core", "from core", "memory", "ael", "urllib", "socket",
                       "requests", "open(", "import os", "subprocess", "exec(", "eval("):
            self.assertNotIn(banned, src, banned)


class TestBackwardCompatible(unittest.TestCase):
    def test_existing_layers_unchanged_by_the_pipeline(self):
        ctx, a = feed("پایتون چیه؟", "دوباره")
        ri = a.reasoning_input(ctx)
        req = build_reasoning_request(ri)
        plan = build_reasoning_plan(req)
        val = validate_reasoning_plan(plan)
        n, v, res = a.normalized(), a.semantic_view(), a.resolve_references(ctx)
        reqb, planb = copy.deepcopy(req), copy.deepcopy(plan)
        decide_reasoning(req)
        self.assertEqual((req, plan), (reqb, planb))
        self.assertEqual(build_reasoning_request(ri), req)
        self.assertEqual(build_reasoning_plan(req), plan)
        self.assertEqual(validate_reasoning_plan(plan), val)
        self.assertEqual((a.normalized(), a.semantic_view(), a.resolve_references(ctx),
                          a.reasoning_input(ctx)), (n, v, res, ri))

    def test_default_planner_is_the_existing_planner(self):
        import inspect
        sig = inspect.signature(decide_reasoning)
        self.assertIs(sig.parameters["plan_builder"].default, build_reasoning_plan)


if __name__ == "__main__":
    unittest.main()
