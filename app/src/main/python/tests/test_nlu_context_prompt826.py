"""
Prompt 826 - NLU conversation-context foundation focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_nlu_context_prompt826 -v
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from understanding.persian_nlu import PersianNLU, INTENT_INTRODUCE_NAME
from understanding.nlu_pipeline import (
    NLUConversationContext, TurnRecord, DEFAULT_MAX_TURNS, default_pipeline,
)


def _fill(ctx, texts, pipeline=None):
    p = pipeline or default_pipeline()
    for t in texts:
        ctx.record(p.analyze(t, ctx))
    return ctx


class TestContextPersistence(unittest.TestCase):
    def test_turns_persist_in_order_across_records(self):
        ctx = _fill(NLUConversationContext(), ["سلام", "من عرفان هستم", "پایتون چیه؟"])
        self.assertEqual([t.index for t in ctx.turns()], [0, 1, 2])
        self.assertEqual(ctx.previous.normalized_text, ctx.turns()[-1].normalized_text)
        self.assertEqual(ctx.turns()[1].intent, INTENT_INTRODUCE_NAME)
        self.assertEqual(ctx.size, 3)
        self.assertFalse(ctx.is_empty)

    def test_analyze_alone_never_persists(self):
        ctx = NLUConversationContext()
        default_pipeline().analyze("سلام", ctx)
        self.assertTrue(ctx.is_empty)
        self.assertEqual(ctx.size, 0)
        self.assertEqual(ctx.turn_count, 0)

    def test_stored_entities_are_a_copy_of_the_analysis(self):
        ctx = NLUConversationContext()
        a = default_pipeline().analyze("من عرفان هستم", ctx)
        ctx.record(a)
        a.result.entities["name"] = "changed"
        self.assertEqual(ctx.previous.entities, {"name": "عرفان"})

    def test_recent_returns_last_n_oldest_first(self):
        ctx = _fill(NLUConversationContext(), [f"جمله {i}" for i in range(5)])
        self.assertEqual([t.index for t in ctx.recent(2)], [3, 4])
        self.assertEqual([t.index for t in ctx.recent()], [0, 1, 2, 3, 4])
        self.assertEqual([t.index for t in ctx.recent(99)], [0, 1, 2, 3, 4])
        self.assertEqual(ctx.recent(0), ())
        self.assertEqual(NLUConversationContext().recent(3), ())

    def test_recent_rejects_bad_n(self):
        ctx = NLUConversationContext()
        for bad in (-1, True, "2", 1.5):
            with self.assertRaises(ValueError):
                ctx.recent(bad)

    def test_turn_at_uses_absolute_index(self):
        ctx = _fill(NLUConversationContext(max_turns=3), [f"جمله {i}" for i in range(6)])
        self.assertIsNone(ctx.turn_at(0))      # dropped by the bound
        self.assertIsNone(ctx.turn_at(2))
        self.assertEqual(ctx.turn_at(3).index, 3)
        self.assertEqual(ctx.turn_at(5).index, 5)
        self.assertIsNone(ctx.turn_at(6))      # not recorded yet
        self.assertIsNone(ctx.turn_at(-1))
        self.assertIsNone(NLUConversationContext().turn_at(0))
        for bad in (True, "1", None, 1.0):
            with self.assertRaises(ValueError):
                ctx.turn_at(bad)

    def test_snapshot_is_plain_deterministic_and_detached(self):
        ctx = _fill(NLUConversationContext(max_turns=2), ["من عرفان هستم", "سلام", "پایتون چیه؟"])
        snap = ctx.snapshot()
        self.assertEqual(snap["max_turns"], 2)
        self.assertEqual(snap["turn_count"], 3)
        self.assertEqual([t["index"] for t in snap["turns"]], [1, 2])
        self.assertEqual(json.dumps(snap, sort_keys=True), json.dumps(ctx.snapshot(), sort_keys=True))
        snap["turns"].append("x")
        snap["turns"][0]["entities"]["x"] = 1
        self.assertEqual(ctx.size, 2)
        self.assertNotIn("x", ctx.turns()[0].entities)

    def test_snapshot_of_empty_context(self):
        self.assertEqual(NLUConversationContext().snapshot(),
                         {"max_turns": DEFAULT_MAX_TURNS, "turn_count": 0, "turns": []})


class TestContextReset(unittest.TestCase):
    def test_reset_clears_turns_counter_and_keeps_bound(self):
        ctx = _fill(NLUConversationContext(max_turns=4), ["سلام", "پایتون چیه؟"])
        ctx.reset()
        self.assertTrue(ctx.is_empty)
        self.assertEqual((ctx.size, ctx.turn_count), (0, 0))
        self.assertIsNone(ctx.previous)
        self.assertEqual(ctx.turns(), ())
        self.assertIsNone(ctx.turn_at(0))
        self.assertEqual(ctx.max_turns, 4)

    def test_reset_is_idempotent_and_allows_reuse(self):
        ctx = NLUConversationContext()
        ctx.reset()
        ctx.reset()
        _fill(ctx, ["سلام"])
        self.assertEqual(ctx.turns()[0].index, 0)   # numbering restarts
        ctx.reset()
        _fill(ctx, ["سلام", "سلام"])
        self.assertEqual([t.index for t in ctx.turns()], [0, 1])

    def test_reset_does_not_affect_other_contexts(self):
        a, b = NLUConversationContext(), NLUConversationContext()
        _fill(a, ["سلام"])
        _fill(b, ["سلام"])
        a.reset()
        self.assertEqual(b.size, 1)


class TestContextBounds(unittest.TestCase):
    def test_default_bound(self):
        ctx = _fill(NLUConversationContext(), [f"جمله {i}" for i in range(DEFAULT_MAX_TURNS + 5)])
        self.assertEqual(ctx.max_turns, DEFAULT_MAX_TURNS)
        self.assertEqual(ctx.size, DEFAULT_MAX_TURNS)
        self.assertEqual(ctx.turn_count, DEFAULT_MAX_TURNS + 5)

    def test_bound_of_one_keeps_only_the_latest(self):
        ctx = _fill(NLUConversationContext(max_turns=1), ["الف", "ب", "ج"])
        self.assertEqual(ctx.size, 1)
        self.assertEqual(ctx.previous.index, 2)
        self.assertEqual(ctx.recent(5)[0].index, 2)

    def test_size_never_exceeds_bound_through_helpers(self):
        ctx = _fill(NLUConversationContext(max_turns=3), [f"جمله {i}" for i in range(20)])
        self.assertLessEqual(len(ctx.recent()), 3)
        self.assertLessEqual(len(ctx.snapshot()["turns"]), 3)

    def test_invalid_bound_rejected(self):
        for bad in (0, -1, True, "3", None, 2.0):
            with self.assertRaises(ValueError):
                NLUConversationContext(max_turns=bad)

    def test_deterministic_for_same_inputs(self):
        texts = ["من عرفان هستم", "اسم من چیه؟", "نه منظورم علی بود", "سلام"]
        a = _fill(NLUConversationContext(), texts)
        b = _fill(NLUConversationContext(), texts)
        self.assertEqual(a.snapshot(), b.snapshot())


class TestBackwardCompatibility(unittest.TestCase):
    def test_original_api_surface_unchanged(self):
        ctx = NLUConversationContext(max_turns=3)
        self.assertEqual(ctx.max_turns, 3)
        self.assertEqual(ctx.turn_count, 0)
        self.assertIsNone(ctx.previous)
        self.assertEqual(ctx.turns(), ())
        turn = ctx.record(default_pipeline().analyze("من عرفان هستم", ctx))
        self.assertIsInstance(turn, TurnRecord)
        self.assertEqual(turn.to_dict()["entities"], {"name": "عرفان"})
        self.assertEqual(sorted(turn.to_dict()),
                         ["entities", "index", "intent", "normalized_text", "structure_keys"])

    def test_default_constructor_and_truthiness_unchanged(self):
        ctx = NLUConversationContext()
        self.assertTrue(bool(ctx))   # an empty context must stay truthy

    def test_context_annotator_output_unchanged(self):
        ctx = _fill(NLUConversationContext(), ["پایتون چیه؟"])
        c = default_pipeline().analyze("و جاوا چی؟", ctx).structure["context"]
        # Prompt 827 added the "reference" key; the original seven are unchanged.
        self.assertTrue({
            "turn_index", "previous_intent", "previous_text",
            "same_intent_as_previous", "is_repeat", "follows_question",
            "continuation"} <= set(c))
        self.assertEqual(c["turn_index"], 1)
        self.assertTrue(c["follows_question"])

    def test_persian_nlu_wrappers_unchanged(self):
        nlu, ctx = PersianNLU(), NLUConversationContext()
        nlu.analyze_structured("سلام", ctx)
        self.assertTrue(ctx.is_empty)
        nlu.analyze_in_context("سلام", ctx)
        self.assertEqual(ctx.size, 1)


class TestCoreIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.core = Core(os.path.join(self.tmp.name, "memory.db"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_core_context_is_the_shared_type_and_bounded(self):
        self.assertIsInstance(self.core.nlu_context, NLUConversationContext)
        self.assertTrue(self.core.nlu_context.is_empty)

    def test_core_turns_flow_into_context_and_reset_clears_them(self):
        self.core.process_input("من عرفان هستم")
        self.core.process_input("سلام")
        self.assertEqual(self.core.nlu_context.size, 2)
        self.assertEqual(self.core.nlu_context.snapshot()["turn_count"], 2)
        self.core.reset_context()
        self.assertTrue(self.core.nlu_context.is_empty)
        self.assertEqual(self.core.nlu_context.turn_count, 0)


if __name__ == "__main__":
    unittest.main()
