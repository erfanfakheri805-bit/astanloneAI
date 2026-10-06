"""
Prompt 832 - meaning resolution bridge focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_nlu_meaning_bridge_prompt832 -v
"""

import copy
import json
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from understanding.nlu_pipeline import NLUConversationContext, NLUAnalysis, default_pipeline
from understanding.nlu_semantic_view import build_semantic_view
from understanding.nlu_meaning_bridge import (
    resolve_references, empty_resolution, RESOLUTION_VERSION, MAX_TEXT_CHARS,
)

P = default_pipeline()
KEYS = ["version", "status", "reason", "cues", "continuation", "primary_intent",
        "effective_intent", "inherited_intent", "referenced_turn", "referenced"]


def feed(*texts, max_turns=8):
    """Analyze texts in order against one context; returns (context, last_analysis)."""
    ctx = NLUConversationContext(max_turns=max_turns)
    a = None
    for i, t in enumerate(texts):
        a = P.analyze(t, ctx)
        if i < len(texts) - 1:
            ctx.record(a)
    return ctx, a


class TestValidResolution(unittest.TestCase):
    def test_shape_and_key_order(self):
        ctx, a = feed("پایتون چیه؟", "دوباره")
        r = resolve_references(a, ctx)
        self.assertEqual(list(r), KEYS)
        self.assertEqual(r["version"], RESOLUTION_VERSION)

    def test_again_inherits_intent_and_points_at_previous_turn(self):
        ctx, a = feed("پایتون چیه؟", "دوباره")
        r = resolve_references(a, ctx)
        self.assertEqual((r["status"], r["reason"], r["cues"]), ("resolved", None, ["again"]))
        self.assertEqual((r["primary_intent"], r["inherited_intent"], r["effective_intent"]),
                         ("unknown", "question", "question"))
        self.assertEqual(r["referenced_turn"], 0)
        self.assertEqual(r["referenced"], {"turn_index": 0, "intent": "question",
                                           "text": "پایتون چیه?"})

    def test_pointer_words_resolve(self):
        for word in ("همونو", "قبلی", "همون", "مثل قبل"):
            ctx, a = feed("پایتون چیه؟", word)
            r = resolve_references(a, ctx)
            self.assertEqual(r["status"], "resolved", word)
            self.assertEqual(r["cues"], ["reference"], word)
            self.assertEqual(r["referenced_turn"], 0, word)
            self.assertEqual(r["effective_intent"], "question", word)

    def test_continuation_reference(self):
        ctx, a = feed("پایتون چیه؟", "و جاوا چی؟")
        r = resolve_references(a, ctx)
        self.assertEqual((r["status"], r["cues"], r["continuation"]),
                         ("resolved", ["continuation"], "و"))
        self.assertEqual(r["referenced_turn"], 0)
        self.assertEqual(r["referenced"]["intent"], "question")

    def test_own_explicit_intent_is_never_overridden(self):
        ctx, a = feed("پایتون چیه؟", "لطفا همونو بگو")
        r = resolve_references(a, ctx)
        self.assertEqual(r["status"], "resolved")
        self.assertEqual((r["primary_intent"], r["effective_intent"], r["inherited_intent"]),
                         ("request", "request", None))

    def test_resolves_without_a_context_object(self):
        _ctx, a = feed("پایتون چیه؟", "دوباره")
        r = resolve_references(a)
        self.assertEqual((r["status"], r["referenced_turn"], r["inherited_intent"]),
                         ("resolved", 0, "question"))
        self.assertIsNone(r["referenced"])

    def test_accepts_a_semantic_view_and_a_normalized_dict(self):
        ctx, a = feed("پایتون چیه؟", "دوباره")
        expected = resolve_references(a, ctx)
        self.assertEqual(resolve_references(build_semantic_view(a), ctx), expected)
        self.assertEqual(resolve_references(a.normalized(), ctx), expected)

    def test_method_matches_function(self):
        ctx, a = feed("پایتون چیه؟", "دوباره")
        self.assertEqual(a.resolve_references(ctx), resolve_references(a, ctx))
        self.assertEqual(a.resolve_references(), resolve_references(a))

    def test_chain_is_not_followed(self):
        # "قبلی" after "دوباره": points at the previous turn only (unknown intent),
        # never guesses what that turn itself referred to.
        ctx, a = feed("پایتون چیه؟", "دوباره", "قبلی")
        r = resolve_references(a, ctx)
        self.assertEqual((r["status"], r["referenced_turn"], r["referenced"]["intent"]),
                         ("resolved", 1, "unknown"))
        self.assertIsNone(r["inherited_intent"])


class TestMissingAndNone(unittest.TestCase):
    def test_message_without_cues(self):
        for t in ("پایتون چیه؟", "من عرفان هستم", "سلام", ""):
            ctx, a = feed("پایتون چیه؟", t)
            r = resolve_references(a, ctx)
            self.assertEqual((r["status"], r["cues"], r["referenced_turn"]), ("none", [], None), t)

    def test_first_turn_cue_has_nothing_to_point_at(self):
        for t in ("دوباره", "همونو", "قبلی"):
            a = P.analyze(t, NLUConversationContext())
            r = resolve_references(a, NLUConversationContext())
            self.assertEqual((r["status"], r["reason"]), ("unresolved", "no_previous_turn"), t)
            self.assertIsNone(r["referenced_turn"])
            self.assertIsNone(r["inherited_intent"])

    def test_continuation_marker_without_previous_turn_is_not_a_cue(self):
        r = resolve_references(P.analyze("و جاوا چی؟", NLUConversationContext()))
        self.assertEqual((r["status"], r["cues"]), ("none", []))

    def test_cue_without_any_context_object_at_analysis_time(self):
        r = resolve_references(P.analyze("دوباره"))
        self.assertIn(r["status"], ("none", "unresolved"))
        self.assertIsNone(r["referenced_turn"])
        self.assertIsNone(r["inherited_intent"])

    def test_referenced_turn_dropped_by_context_bound(self):
        ctx, a = feed("پایتون چیه؟", "دوباره", max_turns=1)
        small = NLUConversationContext(max_turns=1)
        for t in ("سلام", "چطوری", "خوبی"):
            small.record(P.analyze(t, small))        # turn 0 dropped
        r = resolve_references(a, small)
        self.assertEqual((r["status"], r["reason"]), ("unresolved", "referenced_turn_unavailable"))
        self.assertIsNone(r["referenced_turn"])
        self.assertEqual(r["effective_intent"], r["primary_intent"])

    def test_bad_input_never_raises(self):
        for junk in (None, object(), 5, "x", [], {}, {"intent": 5}, {"intent": {}, "context": 3}):
            self.assertEqual(resolve_references(junk), empty_resolution())
            self.assertEqual(resolve_references(junk, object()), empty_resolution())

    def test_bad_context_object_is_unresolved_not_an_error(self):
        _ctx, a = feed("پایتون چیه؟", "دوباره")
        r = resolve_references(a, object())
        self.assertEqual((r["status"], r["reason"]), ("unresolved", "referenced_turn_unavailable"))


class TestAmbiguous(unittest.TestCase):
    def test_context_disagrees_with_the_view(self):
        _c1, a = feed("پایتون چیه؟", "دوباره")        # inherited "question"
        other = NLUConversationContext()
        other.record(P.analyze("من عرفان هستم", other))  # turn 0 is introduce_name
        r = resolve_references(a, other)
        self.assertEqual((r["status"], r["reason"]), ("ambiguous", "context_mismatch"))
        self.assertEqual((r["inherited_intent"], r["referenced_turn"], r["referenced"]),
                         (None, None, None))
        self.assertEqual(r["effective_intent"], r["primary_intent"])

    def test_impossible_reference_in_a_view(self):
        v = build_semantic_view(feed("پایتون چیه؟", "دوباره")[1])
        v["context"]["referenced_turn"] = v["context"]["turn_index"]       # points at itself
        r = resolve_references(v)
        self.assertEqual((r["status"], r["reason"]), ("ambiguous", "invalid_reference"))
        v["context"]["referenced_turn"] = -1
        self.assertEqual(resolve_references(v)["reason"], "invalid_reference")
        v["context"]["referenced_turn"] = 0
        v["context"]["inherited_intent"] = 7
        self.assertEqual(resolve_references(v)["reason"], "invalid_reference")

    def test_ambiguous_never_carries_unsupported_values(self):
        _c1, a = feed("پایتون چیه؟", "دوباره")
        other = NLUConversationContext()
        other.record(P.analyze("من عرفان هستم", other))
        r = resolve_references(a, other)
        self.assertEqual((r["inherited_intent"], r["referenced_turn"]), (None, None))


class TestReset(unittest.TestCase):
    def test_reset_makes_old_references_unresolvable(self):
        ctx, a = feed("پایتون چیه؟", "دوباره")
        self.assertEqual(resolve_references(a, ctx)["status"], "resolved")
        ctx.reset()
        r = resolve_references(a, ctx)
        self.assertEqual((r["status"], r["reason"]), ("unresolved", "referenced_turn_unavailable"))

    def test_cue_right_after_reset_has_no_previous_turn(self):
        ctx, _a = feed("پایتون چیه؟", "سلام")
        ctx.reset()
        a = P.analyze("همونو", ctx)
        r = resolve_references(a, ctx)
        self.assertEqual((r["status"], r["reason"]), ("unresolved", "no_previous_turn"))

    def test_conversation_works_again_after_reset(self):
        ctx, _a = feed("پایتون چیه؟", "سلام")
        ctx.reset()
        ctx.record(P.analyze("من عرفان هستم", ctx))
        a = P.analyze("دوباره", ctx)
        r = resolve_references(a, ctx)
        self.assertEqual((r["status"], r["referenced_turn"], r["inherited_intent"]),
                         ("resolved", 0, "introduce_name"))


class TestBoundsDeterminismSafety(unittest.TestCase):
    def test_referenced_text_is_bounded(self):
        class Turn:
            intent, normalized_text = "question", "x" * 5000

        class Ctx:
            def turn_at(self, i):
                return Turn()
        v = build_semantic_view(feed("پایتون چیه؟", "دوباره")[1])
        r = resolve_references(v, Ctx())
        self.assertEqual(len(r["referenced"]["text"]), MAX_TEXT_CHARS)

    def test_json_safe_and_deterministic(self):
        ctx, a = feed("پایتون چیه؟", "دوباره")
        r1, r2 = resolve_references(a, ctx), resolve_references(a, ctx)
        self.assertEqual(r1, r2)
        self.assertIsNot(r1, r2)
        json.dumps(r1, ensure_ascii=False)
        for junk in (None, 5):
            json.dumps(resolve_references(junk), ensure_ascii=False)

    def test_result_is_detached(self):
        ctx, a = feed("پایتون چیه؟", "دوباره")
        r = resolve_references(a, ctx)
        r["cues"].append("junk")
        r["referenced"]["text"] = "changed"
        self.assertEqual(resolve_references(a, ctx)["cues"], ["again"])
        self.assertEqual(ctx.turn_at(0).normalized_text, "پایتون چیه?")

    def test_empty_resolution_is_fresh(self):
        a, b = empty_resolution(), empty_resolution()
        a["cues"].append(1)
        self.assertEqual(b, empty_resolution())


class TestBackwardCompatibility(unittest.TestCase):
    CORPUS = ["پایتون چیه؟", "و جاوا چی؟", "دوباره", "همونو بگو", "قبلی", "من عرفان هستم",
              "اسم من چیه؟", "لطفا «سلام» را بگو", "سن: ۲۵", "", "What is the weather"]

    def test_analysis_view_normalized_and_context_unchanged(self):
        ctx = NLUConversationContext()
        for t in self.CORPUS:
            a = P.analyze(t, ctx)
            before = (a.to_dict(), copy.deepcopy(a.normalized()),
                      copy.deepcopy(a.semantic_view()), copy.deepcopy(ctx.snapshot()))
            resolve_references(a, ctx)
            a.resolve_references(ctx)
            after = (a.to_dict(), a.normalized(), a.semantic_view(), ctx.snapshot())
            self.assertEqual(after, before, t)
            ctx.record(a)

    def test_normalized_keys_and_semantic_view_keys_unchanged(self):
        a = P.analyze("پایتون چیه؟")
        self.assertEqual(list(a.normalized())[-2:], ["slots", "relations"])
        self.assertEqual(list(a.semantic_view()),
                         ["version", "intent", "context", "slots", "relations", "bounds"])
        self.assertNotIn("resolution", a.normalized())
        self.assertNotIn("resolved", a.semantic_view())
        self.assertEqual(set(a.to_dict()), {"result", "structure", "component", "errors"})
        self.assertIsInstance(a, NLUAnalysis)

    def test_intent_is_copied_not_redetected(self):
        ctx = NLUConversationContext()
        for t in self.CORPUS:
            a = P.analyze(t, ctx)
            ctx.record(a)
            r = resolve_references(a, ctx)
            self.assertEqual(r["primary_intent"], a.normalized()["intent"], t)
            self.assertEqual(r["effective_intent"],
                             a.normalized()["context"]["reference"]["effective_intent"]
                             if r["status"] != "none" and a.normalized()["context"]["reference"]["referenced_turn"] is not None
                             else r["primary_intent"], t)


class TestCoreMemoryUnchanged(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.core = Core(os.path.join(self.tmp.name, "memory.db"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_resolution_available_and_memory_untouched(self):
        self.core.process_input("پایتون چیه؟")
        counts = self.core.memory.counts()
        self.core.process_input("دوباره")
        a = self.core.last_nlu_analysis
        r = resolve_references(a)
        self.assertEqual((r["status"], r["cues"]), ("resolved", ["again"]))
        self.assertEqual(self.core.memory.counts()["knowledge_count"], counts["knowledge_count"])


if __name__ == "__main__":
    unittest.main()
