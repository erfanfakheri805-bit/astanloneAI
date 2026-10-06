"""
Prompt 833 - NLU -> reasoning bridge focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_nlu_reasoning_input_prompt833 -v
"""

import copy
import json
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from understanding.nlu_pipeline import NLUConversationContext, default_pipeline
from understanding.nlu_semantic_view import build_semantic_view
from understanding.nlu_meaning_bridge import resolve_references
from understanding.nlu_reasoning_input import (
    build_reasoning_input, empty_reasoning_input, REASONING_INPUT_VERSION,
)

P = default_pipeline()
KEYS = ["version", "status", "intent", "known", "unresolved", "missing"]


def feed(*texts, max_turns=8):
    ctx = NLUConversationContext(max_turns=max_turns)
    a = None
    for i, t in enumerate(texts):
        a = P.analyze(t, ctx)
        if i < len(texts) - 1:
            ctx.record(a)
    return ctx, a


class TestNormal(unittest.TestCase):
    def test_shape_and_key_order(self):
        r = build_reasoning_input(P.analyze("من عرفان هستم"))
        self.assertEqual(list(r), KEYS)
        self.assertEqual(r["version"], REASONING_INPUT_VERSION)
        self.assertEqual(list(r["intent"]), ["primary", "effective", "inherited", "recognized"])
        self.assertEqual(list(r["known"]), ["slots", "relations", "reference"])
        self.assertEqual(list(r["unresolved"]), ["reference_status", "reference_reason",
                                                 "ambiguous_relations", "slots_truncated",
                                                 "relations_truncated"])

    def test_slots_and_relations_preserved(self):
        a = P.analyze("من عرفان هستم")
        r = build_reasoning_input(a)
        view = build_semantic_view(a)
        self.assertEqual(r["status"], "ready")
        self.assertEqual(r["intent"], {"primary": "introduce_name", "effective": "introduce_name",
                                       "inherited": None, "recognized": True})
        self.assertEqual(r["known"]["slots"], view["slots"])
        self.assertEqual(r["known"]["relations"], view["relations"])
        self.assertEqual(r["missing"], [])

    def test_key_value_slot(self):
        r = build_reasoning_input(P.analyze("لطفا نام: علی را ذخیره کن"))
        self.assertEqual(r["intent"]["effective"], "request")
        self.assertEqual(r["known"]["slots"], [{"kind": "key_value", "key": "نام", "value": "علی"}])
        self.assertEqual(len(r["known"]["relations"]), 2)

    def test_accepts_view_and_normalized_and_method(self):
        a = P.analyze("من عرفان هستم")
        base = build_reasoning_input(a)
        self.assertEqual(build_reasoning_input(a.semantic_view()), base)
        self.assertEqual(build_reasoning_input(a.normalized()), base)
        self.assertEqual(a.reasoning_input(), base)


class TestUnknownAndMissing(unittest.TestCase):
    def test_unknown_message(self):
        r = build_reasoning_input(P.analyze("xqzv"))
        self.assertEqual(r["status"], "unknown")
        self.assertEqual(r["intent"]["effective"], "unknown")
        self.assertEqual((r["known"]["slots"], r["known"]["relations"]), ([], []))
        self.assertEqual(r["missing"], ["intent_unknown"])

    def test_empty_text(self):
        r = build_reasoning_input(P.analyze(""))
        self.assertEqual(r["status"], "unknown")
        self.assertEqual(r["missing"], ["intent_unknown"])

    def test_missing_inputs_do_not_raise_and_match_empty(self):
        for bad in (None, 42, "text", [], {}, object(), {"intent": 1}):
            r = build_reasoning_input(bad)
            self.assertEqual(list(r), KEYS)
            self.assertEqual(r["status"], "unknown")
            self.assertEqual(r["missing"], ["intent_unknown"])
        self.assertEqual(build_reasoning_input(None), empty_reasoning_input())

    def test_nothing_is_invented_for_unknown(self):
        r = build_reasoning_input(P.analyze("xqzv"))
        self.assertIsNone(r["intent"]["inherited"])
        self.assertIsNone(r["known"]["reference"]["referenced"])


class TestReferenced(unittest.TestCase):
    def test_again_resolved(self):
        ctx, a = feed("پایتون چیه؟", "دوباره")
        r = build_reasoning_input(a, ctx)
        self.assertEqual(r["status"], "ready")
        self.assertEqual(r["intent"], {"primary": "unknown", "effective": "question",
                                       "inherited": "question", "recognized": False})
        ref = r["known"]["reference"]
        self.assertEqual((ref["status"], ref["cues"], ref["referenced_turn"]),
                         ("resolved", ["again"], 0))
        self.assertEqual(ref["referenced"]["intent"], "question")
        self.assertEqual(r["unresolved"]["reference_status"], None)
        self.assertEqual(r["missing"], [])

    def test_matches_meaning_bridge(self):
        ctx, a = feed("پایتون چیه؟", "و جاوا چی؟")
        res = resolve_references(a, ctx)
        ref = build_reasoning_input(a, ctx)["known"]["reference"]
        for k in ("status", "cues", "continuation", "referenced_turn", "referenced"):
            self.assertEqual(ref[k], res[k])

    def test_own_intent_not_overridden(self):
        ctx, a = feed("پایتون چیه؟", "لطفا همونو بگو")
        r = build_reasoning_input(a, ctx)
        self.assertEqual((r["intent"]["primary"], r["intent"]["effective"],
                          r["intent"]["inherited"]), ("request", "request", None))

    def test_without_context_cue_is_not_confirmed(self):
        ctx, a = feed("پایتون چیه؟", "دوباره")
        r = build_reasoning_input(a)  # no context given
        self.assertEqual(r["known"]["reference"]["status"], "resolved")
        self.assertIsNone(r["known"]["reference"]["referenced"])


class TestUnresolved(unittest.TestCase):
    def test_first_turn_cue(self):
        ctx, a = feed("دوباره")   # first turn: empty context
        r = build_reasoning_input(a, ctx)
        self.assertEqual(r["status"], "unresolved")
        self.assertEqual(r["unresolved"]["reference_status"], "unresolved")
        self.assertEqual(r["unresolved"]["reference_reason"], "no_previous_turn")
        self.assertEqual(r["missing"], ["intent_unknown", "reference_unresolved"])
        self.assertIsNone(r["intent"]["inherited"])
        self.assertIsNone(r["known"]["reference"]["referenced_turn"])

    def test_turn_dropped_from_bounded_context(self):
        # a reset context no longer retains the referenced turn
        ctx2, a2 = feed("پایتون چیه؟", "دوباره")
        ctx2.reset()
        r = build_reasoning_input(a2, ctx2)
        self.assertEqual(r["status"], "unresolved")
        self.assertEqual(r["unresolved"]["reference_reason"], "referenced_turn_unavailable")
        self.assertIsNone(r["intent"]["inherited"])
        self.assertEqual(r["intent"]["effective"], r["intent"]["primary"])


class TestAmbiguous(unittest.TestCase):
    def test_ambiguous_relations(self):
        r = build_reasoning_input(P.analyze("age=30 و age=31"))
        self.assertEqual(r["status"], "ambiguous")
        self.assertEqual(r["unresolved"]["ambiguous_relations"], 1)
        self.assertIn("relations_ambiguous", r["missing"])
        self.assertEqual(r["known"]["relations"], [])

    def test_ambiguous_does_not_hide_known_slots(self):
        r = build_reasoning_input(P.analyze("age=30 و age=31 و city=Tehran"))
        self.assertEqual(r["status"], "ambiguous")
        self.assertTrue(any(s["key"] == "city" for s in r["known"]["slots"]))

    def test_context_mismatch_ambiguous(self):
        ctx, a = feed("پایتون چیه؟", "دوباره")
        view = copy.deepcopy(a.semantic_view())
        view["context"]["inherited_intent"] = "request"   # contradicts turn 0
        r = build_reasoning_input(view, ctx)
        self.assertEqual(r["status"], "ambiguous")
        self.assertEqual(r["unresolved"]["reference_status"], "ambiguous")
        self.assertEqual(r["unresolved"]["reference_reason"], "context_mismatch")
        self.assertIn("reference_ambiguous", r["missing"])
        self.assertIsNone(r["intent"]["inherited"])
        self.assertIsNone(r["known"]["reference"]["referenced_turn"])

    def test_truncation_reported(self):
        view = copy.deepcopy(P.analyze("من عرفان هستم").semantic_view())
        view["bounds"]["slots_truncated"] = True
        view["bounds"]["relations_truncated"] = True
        r = build_reasoning_input(view)
        self.assertEqual(r["missing"], ["slots_truncated", "relations_truncated"])
        self.assertTrue(r["unresolved"]["slots_truncated"])
        self.assertEqual(r["status"], "ready")


class TestGuarantees(unittest.TestCase):
    TEXTS = ("من عرفان هستم", "xqzv", "دوباره", "age=30 و age=31", "لطفا نام: علی را ذخیره کن")

    def test_json_safe_and_deterministic(self):
        for t in self.TEXTS:
            a = P.analyze(t)
            r1, r2 = build_reasoning_input(a), build_reasoning_input(a)
            self.assertEqual(r1, r2)
            self.assertEqual(json.loads(json.dumps(r1, ensure_ascii=False)), r1)

    def test_fresh_dict_each_call(self):
        a = P.analyze("من عرفان هستم")
        r1 = build_reasoning_input(a)
        r1["known"]["slots"].append("x")
        r1["missing"].append("x")
        r2 = build_reasoning_input(a)
        self.assertEqual(len(r2["known"]["slots"]), 1)
        self.assertEqual(r2["missing"], [])

    def test_inputs_not_modified(self):
        ctx, a = feed("پایتون چیه؟", "دوباره")
        before_a, before_c = a.to_dict(), ctx.snapshot()
        view = a.semantic_view()
        before_v = copy.deepcopy(view)
        build_reasoning_input(a, ctx)
        build_reasoning_input(view, ctx)
        self.assertEqual(a.to_dict(), before_a)
        self.assertEqual(ctx.snapshot(), before_c)
        self.assertEqual(view, before_v)

    def test_broken_context_does_not_raise(self):
        class Bad:
            def turn_at(self, i):
                raise RuntimeError("boom")
        _ctx, a = feed("پایتون چیه؟", "دوباره")
        r = build_reasoning_input(a, Bad())
        self.assertEqual(list(r), KEYS)
        self.assertEqual(r["status"], "unresolved")

    def test_bounded(self):
        a = P.analyze("لطفا نام: علی را ذخیره کن")
        r = build_reasoning_input(a)
        self.assertLessEqual(len(r["known"]["slots"]), 16)
        self.assertLessEqual(len(r["known"]["relations"]), 16)
        self.assertLessEqual(len(r["missing"]), 6)


class TestBackwardCompatible(unittest.TestCase):
    def test_existing_apis_unchanged(self):
        ctx, a = feed("پایتون چیه؟", "دوباره")
        n_before, v_before = a.normalized(), a.semantic_view()
        r_before = a.resolve_references(ctx)
        a.reasoning_input(ctx)
        self.assertEqual(a.normalized(), n_before)
        self.assertEqual(a.semantic_view(), v_before)
        self.assertEqual(a.resolve_references(ctx), r_before)
        self.assertEqual(v_before, build_semantic_view(a))

    def test_analysis_to_dict_has_no_new_keys(self):
        a = P.analyze("من عرفان هستم")
        self.assertEqual(set(a.to_dict()), {"result", "structure", "component", "errors"})


if __name__ == "__main__":
    unittest.main()
