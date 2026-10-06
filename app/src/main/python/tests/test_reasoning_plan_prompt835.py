"""
Prompt 835 - deterministic reasoning plan focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_reasoning_plan_prompt835 -v
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
from reasoning.reasoning_plan import (
    build_reasoning_plan, empty_reasoning_plan, PLAN_VERSION, MAX_STEPS,
)

P = default_pipeline()
KEYS = ["version", "status", "request_status", "goal", "steps", "step_count", "truncated", "executed"]
STEP_KEYS = ["id", "kind", "ref", "detail", "depends_on", "executed"]


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
        return build_reasoning_request(build_reasoning_input(a, ctx))
    return build_reasoning_request(build_reasoning_input(P.analyze(text)))


def ids(plan):
    return [s["id"] for s in plan["steps"]]


class TestReady(unittest.TestCase):
    def test_shape_and_key_order(self):
        p = build_reasoning_plan(request("من عرفان هستم"))
        self.assertEqual(list(p), KEYS)
        self.assertEqual(p["version"], PLAN_VERSION)
        for s in p["steps"]:
            self.assertEqual(list(s), STEP_KEYS)

    def test_single_step_ready_plan(self):
        view = {"intent": {"primary": "greeting", "effective": "greeting", "recognized": True},
                "context": {}}
        p = build_reasoning_plan(build_reasoning_request(build_reasoning_input(view)))
        self.assertEqual(p["status"], "ready")
        self.assertEqual(ids(p), ["address_goal"])
        self.assertEqual((p["steps"][0]["ref"], p["steps"][0]["depends_on"]), ("greeting", []))

    def test_ready_with_slots_and_relations_is_multi_step(self):
        p = build_reasoning_plan(request("من عرفان هستم"))
        self.assertEqual(p["status"], "ready")
        self.assertEqual(ids(p), ["consider_slots", "consider_relations", "address_goal"])
        self.assertEqual([s["detail"] for s in p["steps"][:2]], [1, 1])
        self.assertEqual(p["steps"][2]["ref"], "introduce_name")
        self.assertEqual(p["steps"][2]["depends_on"], ["consider_slots", "consider_relations"])
        self.assertEqual(p["step_count"], 3)

    def test_resolved_reference_adds_consider_reference_first(self):
        r = request("دوباره", ("پایتون چیه؟",))
        p = build_reasoning_plan(r)
        self.assertEqual(p["status"], "ready")
        self.assertEqual(ids(p), ["consider_reference", "address_goal"])
        self.assertEqual(p["steps"][0]["detail"], 0)
        self.assertEqual((p["steps"][1]["ref"], p["steps"][1]["detail"]), ("question", "inherited"))

    def test_all_blocks_give_full_ordered_plan(self):
        r = request("دوباره", ("پایتون چیه؟",))
        r["known"]["slots"] = [{"kind": "k"}, {"kind": "k2"}]
        r["known"]["relations"] = [{"kind": "r"}]
        p = build_reasoning_plan(r)
        self.assertEqual(ids(p), ["consider_reference", "consider_slots",
                                  "consider_relations", "address_goal"])
        self.assertEqual(p["steps"][1]["detail"], 2)
        self.assertEqual(p["steps"][3]["depends_on"], ids(p)[:3])

    def test_goal_and_request_status_copied(self):
        r = request("من عرفان هستم")
        p = build_reasoning_plan(r)
        self.assertEqual(p["goal"], r["goal"])
        self.assertEqual(p["request_status"], "ready")

    def test_no_execution_flags(self):
        p = build_reasoning_plan(request("من عرفان هستم"))
        self.assertIs(p["executed"], False)
        self.assertTrue(all(s["executed"] is False for s in p["steps"]))


class TestUnknown(unittest.TestCase):
    def test_unknown_request_asks_for_information(self):
        p = build_reasoning_plan(request("xqzv"))
        self.assertEqual(p["status"], "needs_information")
        self.assertEqual(ids(p), ["need.intent_unknown"])
        self.assertEqual(p["steps"][0]["kind"], "need")
        self.assertNotIn("address_goal", ids(p))
        self.assertIsNone(p["goal"]["intent"])

    def test_slots_alone_never_create_a_goal(self):
        p = build_reasoning_plan(request("age=30"))
        self.assertEqual(p["status"], "needs_information")
        self.assertEqual(ids(p), ["need.intent_unknown"])

    def test_none_request(self):
        p = build_reasoning_plan(None)
        self.assertEqual(p["status"], "needs_information")
        self.assertEqual(ids(p), ["need.reasoning_request_missing"])
        self.assertEqual(p, empty_reasoning_plan())
        self.assertIsNone(p["request_status"])

    def test_malformed_requests(self):
        good = request("من عرفان هستم")
        bad_code = copy.deepcopy(good)
        bad_code["missing"] = ["made_up_code"]
        bad_unres = copy.deepcopy(good)
        bad_unres["unresolved"] = [{"code": "made_up", "detail": None}]
        no_goal = {k: v for k, v in good.items() if k != "goal"}
        for bad in ("text", 42, [], {}, object(), no_goal, bad_code, bad_unres,
                    {"goal": 1, "known": 2, "unresolved": 3, "missing": 4}):
            p = build_reasoning_plan(bad)
            self.assertEqual(list(p), KEYS)
            self.assertEqual(p["status"], "needs_information")
            self.assertEqual(ids(p), ["need.reasoning_request_invalid"])


class TestAmbiguous(unittest.TestCase):
    def test_ambiguous_relations_clarify_not_guess(self):
        p = build_reasoning_plan(request("age=30 و age=31"))
        self.assertEqual(p["status"], "needs_clarification")
        self.assertEqual(ids(p), ["clarify.relations_ambiguous", "need.intent_unknown"])
        self.assertEqual(p["steps"][0]["kind"], "clarify")
        self.assertEqual(p["steps"][0]["detail"], 1)
        self.assertNotIn("address_goal", ids(p))
        self.assertNotIn("consider_slots", ids(p))

    def test_ambiguous_reference_with_known_goal(self):
        r = request("من عرفان هستم")
        r["unresolved"] = [{"code": "reference_ambiguous", "detail": "context_mismatch"}]
        r["status"] = "ambiguous"
        p = build_reasoning_plan(r)
        self.assertEqual(p["status"], "needs_clarification")
        self.assertEqual(ids(p), ["clarify.reference_ambiguous"])
        self.assertEqual(p["steps"][0]["detail"], "context_mismatch")

    def test_ambiguity_wins_over_unresolved_and_order_is_kept(self):
        r = request("من عرفان هستم")
        r["unresolved"] = [{"code": "reference_unresolved", "detail": "no_previous_turn"},
                           {"code": "relations_ambiguous", "detail": 2}]
        p = build_reasoning_plan(r)
        self.assertEqual(p["status"], "needs_clarification")
        self.assertEqual(ids(p), ["need.reference_unresolved", "clarify.relations_ambiguous"])


class TestMissingAndUnresolved(unittest.TestCase):
    def test_unresolved_reference_needs_information(self):
        ctx, a = feed("دوباره")
        r = build_reasoning_request(build_reasoning_input(a, ctx))
        p = build_reasoning_plan(r)
        self.assertEqual(p["status"], "needs_information")
        self.assertEqual(ids(p), ["need.reference_unresolved", "need.intent_unknown"])
        self.assertEqual(p["steps"][0]["detail"], "no_previous_turn")

    def test_truncated_information_is_missing(self):
        ri = build_reasoning_input(P.analyze("من عرفان هستم"))
        ri["unresolved"]["slots_truncated"] = True
        ri["unresolved"]["relations_truncated"] = True
        r = build_reasoning_request(ri)
        self.assertEqual(r["status"], "missing")
        p = build_reasoning_plan(r)
        self.assertEqual(p["status"], "needs_information")
        self.assertEqual(ids(p), ["need.slots_truncated", "need.relations_truncated"])
        self.assertEqual(p["goal"]["state"], "known")
        self.assertNotIn("address_goal", ids(p))

    def test_status_recomputed_not_copied(self):
        r = request("من عرفان هستم")
        self.assertEqual(r["status"], "ready")
        r["missing"] = ["slots_truncated"]
        p = build_reasoning_plan(r)
        self.assertEqual(p["request_status"], "ready")
        self.assertEqual(p["status"], "needs_information")

    def test_unknown_goal_is_added_as_missing_even_if_not_listed(self):
        r = request("من عرفان هستم")
        r["goal"] = {"intent": None, "source": None, "state": "unresolved"}
        p = build_reasoning_plan(r)
        self.assertEqual(ids(p), ["need.intent_unknown"])


class TestGuarantees(unittest.TestCase):
    TEXTS = ("من عرفان هستم", "xqzv", "age=30 و age=31", "لطفا نام: علی را ذخیره کن", "age=30")

    def test_json_safe_deterministic_stable_ids(self):
        for t in self.TEXTS:
            r = request(t)
            p1, p2 = build_reasoning_plan(r), build_reasoning_plan(r)
            self.assertEqual(p1, p2)
            self.assertEqual(json.loads(json.dumps(p1, ensure_ascii=False)), p1)
            self.assertEqual(len(ids(p1)), len(set(ids(p1))))
            self.assertEqual(p1["step_count"], len(p1["steps"]))

    def test_depends_on_only_earlier_steps(self):
        for t in self.TEXTS:
            p = build_reasoning_plan(request(t))
            seen = []
            for s in p["steps"]:
                self.assertTrue(set(s["depends_on"]) <= set(seen))
                seen.append(s["id"])

    def test_request_not_modified_and_plan_is_fresh(self):
        r = request("لطفا نام: علی را ذخیره کن")
        before = copy.deepcopy(r)
        p1 = build_reasoning_plan(r)
        self.assertEqual(r, before)
        p1["steps"].append("x")
        p1["goal"]["intent"] = "x"
        p2 = build_reasoning_plan(r)
        self.assertNotIn("x", p2["steps"])
        self.assertEqual(p2["goal"]["intent"], "request")
        p2["goal"]["intent"] = "changed"
        self.assertEqual(r, before)

    def test_bounded(self):
        r = request("دوباره", ("پایتون چیه؟",))
        r["known"]["slots"] = [{}] * 16
        p = build_reasoning_plan(r)
        self.assertLessEqual(len(p["steps"]), MAX_STEPS)
        self.assertLessEqual(len(json.dumps(p, ensure_ascii=False)), 3000)
        self.assertFalse(p["truncated"])

    def test_only_request_vocabulary_is_used(self):
        kinds = {"consider_reference", "consider_slots", "consider_relations",
                 "address_goal", "clarify", "need"}
        for t in self.TEXTS:
            for s in build_reasoning_plan(request(t))["steps"]:
                self.assertIn(s["kind"], kinds)


class TestBackwardCompatible(unittest.TestCase):
    def test_request_and_nlu_unchanged(self):
        ctx, a = feed("پایتون چیه؟", "دوباره")
        ri = a.reasoning_input(ctx)
        r = build_reasoning_request(ri)
        n, v, res = a.normalized(), a.semantic_view(), a.resolve_references(ctx)
        build_reasoning_plan(r)
        self.assertEqual(build_reasoning_request(ri), r)
        self.assertEqual((a.normalized(), a.semantic_view(), a.resolve_references(ctx),
                          a.reasoning_input(ctx)), (n, v, res, ri))

    def test_plan_module_imports_no_other_layer(self):
        import reasoning.reasoning_plan as m
        with open(m.__file__, encoding="utf-8") as fh:
            src = fh.read()
        for banned in ("import core", "from core", "memory", "ael", "urllib", "socket",
                       "requests", "open(", "import os", "subprocess"):
            self.assertNotIn(banned, src, banned)


if __name__ == "__main__":
    unittest.main()
