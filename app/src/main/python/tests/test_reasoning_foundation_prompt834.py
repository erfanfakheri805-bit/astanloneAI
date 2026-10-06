"""
Prompt 834 - reasoning foundation focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_reasoning_foundation_prompt834 -v
"""

import copy
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from understanding.nlu_pipeline import NLUConversationContext, default_pipeline
from understanding.nlu_reasoning_input import build_reasoning_input
from reasoning.reasoning_foundation import (
    build_reasoning_request, empty_reasoning_request, FOUNDATION_VERSION, MAX_ITEMS,
)

P = default_pipeline()
KEYS = ["version", "status", "goal", "known", "unresolved", "missing", "next_action"]


def feed(*texts):
    ctx = NLUConversationContext()
    a = None
    for i, t in enumerate(texts):
        a = P.analyze(t, ctx)
        if i < len(texts) - 1:
            ctx.record(a)
    return ctx, a


def req(text):
    return build_reasoning_request(build_reasoning_input(P.analyze(text)))


class TestReady(unittest.TestCase):
    def test_shape_and_key_order(self):
        r = req("من عرفان هستم")
        self.assertEqual(list(r), KEYS)
        self.assertEqual(r["version"], FOUNDATION_VERSION)
        self.assertEqual(list(r["goal"]), ["intent", "source", "state"])
        self.assertEqual(list(r["known"]), ["slots", "relations", "reference"])
        self.assertEqual(list(r["next_action"]), ["action", "reason", "executed"])

    def test_ready_request(self):
        a = P.analyze("من عرفان هستم")
        ri = build_reasoning_input(a)
        r = build_reasoning_request(ri)
        self.assertEqual(r["status"], "ready")
        self.assertEqual(r["goal"], {"intent": "introduce_name", "source": "primary", "state": "known"})
        self.assertEqual(r["known"]["slots"], ri["known"]["slots"])
        self.assertEqual(r["known"]["relations"], ri["known"]["relations"])
        self.assertIsNone(r["known"]["reference"])
        self.assertEqual((r["unresolved"], r["missing"]), ([], []))
        self.assertEqual(r["next_action"], {"action": "proceed", "reason": "goal_known",
                                            "executed": False})

    def test_resolved_reference_is_known_and_goal_inherited(self):
        ctx, a = feed("پایتون چیه؟", "دوباره")
        r = build_reasoning_request(build_reasoning_input(a, ctx))
        self.assertEqual(r["status"], "ready")
        self.assertEqual(r["goal"], {"intent": "question", "source": "inherited", "state": "known"})
        ref = r["known"]["reference"]
        self.assertEqual((ref["cues"], ref["referenced_turn"]), (["again"], 0))
        self.assertEqual(ref["referenced"]["intent"], "question")

    def test_own_intent_is_primary_not_inherited(self):
        ctx, a = feed("پایتون چیه؟", "لطفا همونو بگو")
        r = build_reasoning_request(build_reasoning_input(a, ctx))
        self.assertEqual(r["goal"]["intent"], "request")
        self.assertEqual(r["goal"]["source"], "primary")


class TestUnknown(unittest.TestCase):
    def test_unknown_message(self):
        r = req("xqzv")
        self.assertEqual(r["status"], "unknown")
        self.assertEqual(r["goal"], {"intent": None, "source": None, "state": "unresolved"})
        self.assertEqual((r["known"]["slots"], r["known"]["relations"]), ([], []))
        self.assertEqual(r["missing"], ["intent_unknown"])
        self.assertEqual(r["next_action"]["action"], "request_information")
        self.assertEqual(r["next_action"]["reason"], "intent_unknown")

    def test_no_goal_is_invented_from_slots(self):
        r = req("age=30")
        self.assertIsNone(r["goal"]["intent"])
        self.assertEqual(r["goal"]["state"], "unresolved")
        self.assertIn("intent_unknown", r["missing"])
        self.assertNotEqual(r["status"], "ready")

    def test_unknown_input_never_proceeds(self):
        self.assertNotEqual(req("xqzv")["next_action"]["action"], "proceed")


class TestAmbiguous(unittest.TestCase):
    def test_ambiguous_relations_stay_unresolved(self):
        r = req("age=30 و age=31")
        self.assertEqual(r["status"], "ambiguous")
        self.assertEqual(r["unresolved"], [{"code": "relations_ambiguous", "detail": 1}])
        self.assertEqual(r["known"]["relations"], [])
        self.assertEqual(r["next_action"]["action"], "clarify")
        self.assertEqual(r["next_action"]["reason"], "relations_ambiguous")

    def test_ambiguous_reference_not_trusted(self):
        ctx, a = feed("پایتون چیه؟", "دوباره")
        view = copy.deepcopy(a.semantic_view())
        view["context"]["inherited_intent"] = "request"       # contradicts turn 0
        r = build_reasoning_request(build_reasoning_input(view, ctx))
        self.assertEqual(r["status"], "ambiguous")
        self.assertEqual(r["unresolved"], [{"code": "reference_ambiguous", "detail": "context_mismatch"}])
        self.assertIsNone(r["known"]["reference"])
        self.assertNotEqual(r["goal"]["source"], "inherited")
        self.assertEqual(r["next_action"]["action"], "clarify")


class TestUnresolved(unittest.TestCase):
    def test_reference_without_previous_turn(self):
        ctx, a = feed("دوباره")
        r = build_reasoning_request(build_reasoning_input(a, ctx))
        self.assertEqual(r["status"], "unresolved")
        self.assertEqual(r["unresolved"], [{"code": "reference_unresolved", "detail": "no_previous_turn"}])
        self.assertIsNone(r["known"]["reference"])
        self.assertIsNone(r["goal"]["intent"])
        self.assertEqual(r["next_action"], {"action": "request_information",
                                            "reason": "reference_unresolved", "executed": False})

    def test_turn_no_longer_available(self):
        ctx, a = feed("پایتون چیه؟", "دوباره")
        ctx.reset()
        r = build_reasoning_request(build_reasoning_input(a, ctx))
        self.assertEqual(r["status"], "unresolved")
        self.assertEqual(r["unresolved"][0]["detail"], "referenced_turn_unavailable")

    def test_ambiguous_wins_over_unresolved(self):
        ri = build_reasoning_input(P.analyze("من عرفان هستم"))
        ri["unresolved"]["reference_status"] = "unresolved"
        ri["unresolved"]["ambiguous_relations"] = 2
        r = build_reasoning_request(ri)
        self.assertEqual(r["status"], "ambiguous")
        self.assertEqual([u["code"] for u in r["unresolved"]],
                         ["reference_unresolved", "relations_ambiguous"])


class TestMissing(unittest.TestCase):
    def test_none_input(self):
        r = build_reasoning_request(None)
        self.assertEqual(r["status"], "unknown")
        self.assertEqual(r["missing"], ["reasoning_input_missing"])
        self.assertEqual(r, empty_reasoning_request())

    def test_malformed_inputs(self):
        for bad in ("text", 42, [], {}, object(), {"intent": 1, "known": 2},
                    {"intent": {}, "known": {}, "unresolved": {}}):
            r = build_reasoning_request(bad)
            self.assertEqual(list(r), KEYS)
            self.assertEqual(r["status"], "unknown")
            self.assertEqual(r["missing"], ["reasoning_input_invalid"])
            self.assertEqual(r["next_action"]["action"], "request_information")
            self.assertFalse(r["next_action"]["executed"])

    def test_truncated_information_is_missing(self):
        ri = build_reasoning_input(P.analyze("من عرفان هستم"))
        ri["unresolved"]["slots_truncated"] = True
        ri["unresolved"]["relations_truncated"] = True
        r = build_reasoning_request(ri)
        self.assertEqual(r["status"], "missing")
        self.assertEqual(r["missing"], ["slots_truncated", "relations_truncated"])
        self.assertEqual(r["goal"]["state"], "known")
        self.assertEqual(r["next_action"], {"action": "request_information",
                                            "reason": "slots_truncated", "executed": False})

    def test_oversized_lists_are_bounded_and_reported(self):
        ri = build_reasoning_input(P.analyze("من عرفان هستم"))
        ri["known"]["slots"] = [{"kind": "k", "key": str(i), "value": "v"} for i in range(40)]
        ri["known"]["relations"] = [{"kind": "r"}] * 30
        r = build_reasoning_request(ri)
        self.assertEqual(len(r["known"]["slots"]), MAX_ITEMS)
        self.assertEqual(len(r["known"]["relations"]), MAX_ITEMS)
        self.assertEqual(r["missing"], ["slots_truncated", "relations_truncated"])

    def test_non_json_items_are_dropped(self):
        ri = build_reasoning_input(P.analyze("من عرفان هستم"))
        ri["known"]["slots"] = [{"kind": object()}, {"kind": "ok"}, "nope", None]
        r = build_reasoning_request(ri)
        self.assertEqual(r["known"]["slots"], [{"kind": "ok"}])
        json.dumps(r)


class TestGuarantees(unittest.TestCase):
    TEXTS = ("من عرفان هستم", "xqzv", "age=30 و age=31", "لطفا نام: علی را ذخیره کن")

    def test_json_safe_deterministic_and_never_executed(self):
        for t in self.TEXTS:
            ri = build_reasoning_input(P.analyze(t))
            r1, r2 = build_reasoning_request(ri), build_reasoning_request(ri)
            self.assertEqual(r1, r2)
            self.assertEqual(json.loads(json.dumps(r1, ensure_ascii=False)), r1)
            self.assertIs(r1["next_action"]["executed"], False)

    def test_status_recomputed_from_fields_not_copied(self):
        ri = build_reasoning_input(P.analyze("من عرفان هستم"))
        self.assertEqual(ri["status"], "ready")
        ri["unresolved"]["ambiguous_relations"] = 1
        self.assertEqual(build_reasoning_request(ri)["status"], "ambiguous")

    def test_fresh_and_input_not_modified(self):
        ri = build_reasoning_input(P.analyze("لطفا نام: علی را ذخیره کن"))
        before = copy.deepcopy(ri)
        r1 = build_reasoning_request(ri)
        self.assertEqual(ri, before)
        r1["known"]["slots"].append("x")
        r1["missing"].append("x")
        r1["goal"]["intent"] = "x"
        r2 = build_reasoning_request(ri)
        self.assertNotIn("x", r2["missing"])
        self.assertEqual(len(r2["known"]["slots"]), 1)
        self.assertEqual(r2["goal"]["intent"], "request")
        r2["known"]["slots"][0]["value"] = "changed"
        self.assertEqual(ri, before)

    def test_bounded_output_size(self):
        r = req("لطفا نام: علی را ذخیره کن")
        self.assertLessEqual(len(json.dumps(r, ensure_ascii=False)), 4000)


class TestBackwardCompatible(unittest.TestCase):
    def test_nlu_apis_unchanged_and_not_affected(self):
        ctx, a = feed("پایتون چیه؟", "دوباره")
        n, v = a.normalized(), a.semantic_view()
        ri, res = a.reasoning_input(ctx), a.resolve_references(ctx)
        build_reasoning_request(ri)
        self.assertEqual((a.normalized(), a.semantic_view()), (n, v))
        self.assertEqual((a.reasoning_input(ctx), a.resolve_references(ctx)), (ri, res))

    def test_foundation_imports_no_other_layer(self):
        import reasoning.reasoning_foundation as m
        with open(m.__file__, encoding="utf-8") as fh:
            src = fh.read()
        for banned in ("import core", "from core", "memory", "ael", "urllib", "socket",
                       "requests", "open("):
            self.assertNotIn(banned, src.replace("Memory, AEL, Core", ""), banned)


if __name__ == "__main__":
    unittest.main()
