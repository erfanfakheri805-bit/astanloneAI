"""
Prompt 827 - context-aware Persian NLU focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_nlu_context_aware_prompt827 -v
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from understanding.persian_nlu import (
    PersianNLU, analyze_persian, INTENT_REQUEST, INTENT_QUESTION, INTENT_UNKNOWN,
)
from understanding.nlu_pipeline import (
    NLUConversationContext, build_default_registry, default_pipeline,
)

P = default_pipeline()


def run(texts, ctx=None):
    """Analyze + record each text; return the list of analyses."""
    ctx = ctx if ctx is not None else NLUConversationContext()
    out = []
    for t in texts:
        a = P.analyze(t, ctx)
        ctx.record(a)
        out.append(a)
    return out


def ref(a):
    return a.structure["context"]["reference"]


class TestRepetition(unittest.TestCase):
    def test_repeat_count_and_source_turn(self):
        a = run(["یه جوک بگو", "سلام", "یه جوک بگو", "یه جوک بگو"])
        self.assertEqual(ref(a[0])["repeat_count"], 0)
        self.assertIsNone(ref(a[0])["repeat_of"])
        self.assertEqual((ref(a[2])["repeat_count"], ref(a[2])["repeat_of"]), (1, 0))
        self.assertEqual((ref(a[3])["repeat_count"], ref(a[3])["repeat_of"]), (2, 2))

    def test_non_adjacent_repeat_found_while_is_repeat_stays_previous_only(self):
        a = run(["یه جوک بگو", "سلام", "یه جوک بگو"])
        c = a[2].structure["context"]
        self.assertFalse(c["is_repeat"])             # original meaning unchanged
        self.assertEqual(c["reference"]["repeat_of"], 0)

    def test_repeat_only_sees_retained_turns(self):
        ctx = NLUConversationContext(max_turns=2)
        a = run(["یه جوک بگو", "سلام", "خوبی", "یه جوک بگو"], ctx)
        self.assertEqual(ref(a[3])["repeat_count"], 0)   # turn 0 was dropped
        self.assertIsNone(ref(a[3])["repeat_of"])

    def test_blank_input_never_counts_as_repeat(self):
        # Blank input is skipped by the (persian_only) annotators, as before.
        a = run(["", "", "   "])
        self.assertTrue(all("context" not in x.structure for x in a))


class TestContinuationAndPreviousReference(unittest.TestCase):
    def test_again_inherits_previous_intent_when_unknown(self):
        a = run(["یه جوک بگو", "دوباره"])
        r = ref(a[1])
        self.assertTrue(r["again"])
        self.assertEqual(r["referenced_turn"], 0)
        self.assertEqual(r["inherited_intent"], INTENT_REQUEST)
        self.assertEqual(r["effective_intent"], INTENT_REQUEST)
        self.assertEqual(a[1].intent, INTENT_UNKNOWN)    # primary never changes

    def test_again_phrase(self):
        r = ref(run(["یه جوک بگو", "یه بار دیگه"])[1])
        self.assertTrue(r["again"])
        self.assertEqual(r["inherited_intent"], INTENT_REQUEST)

    def test_continuation_marker_points_at_previous_turn(self):
        a = run(["پایتون چیه؟", "و جاوا چی؟"])
        r = ref(a[1])
        self.assertEqual(a[1].structure["context"]["continuation"], "و")
        self.assertEqual(r["referenced_turn"], 0)
        self.assertIsNone(r["inherited_intent"])         # already has its own intent
        self.assertEqual(r["effective_intent"], INTENT_QUESTION)

    def test_reference_word(self):
        r = ref(run(["یه جوک بگو", "همونو بگو"])[1])
        self.assertTrue(r["refers_to_previous"])
        self.assertEqual(r["referenced_turn"], 0)

    def test_no_inheritance_from_unknown_previous_intent(self):
        r = ref(run(["امروز هوا خوبه", "دوباره"])[1])
        self.assertIsNone(r["inherited_intent"])
        self.assertEqual(r["effective_intent"], INTENT_UNKNOWN)

    def test_no_previous_turn_means_nothing_to_point_at(self):
        r = ref(run(["دوباره"])[0])
        self.assertTrue(r["again"])                      # the cue is still reported
        self.assertIsNone(r["referenced_turn"])
        self.assertIsNone(r["inherited_intent"])

    def test_plain_turn_has_no_reference(self):
        r = ref(run(["یه جوک بگو", "یه شعر بگو"])[1])
        self.assertFalse(r["again"] or r["refers_to_previous"])
        self.assertIsNone(r["referenced_turn"])
        self.assertEqual(r["effective_intent"], INTENT_REQUEST)

    def test_reference_turn_follows_reset(self):
        ctx = NLUConversationContext()
        run(["یه جوک بگو"], ctx)
        ctx.reset()
        r = ref(run(["دوباره"], ctx)[0])
        self.assertIsNone(r["referenced_turn"])
        self.assertIsNone(r["inherited_intent"])


class TestBoundariesAndDeterminism(unittest.TestCase):
    def test_analyze_stays_pure_and_deterministic(self):
        ctx = NLUConversationContext()
        run(["یه جوک بگو"], ctx)
        before = ctx.snapshot()
        a1, a2 = P.analyze("دوباره", ctx), P.analyze("دوباره", ctx)
        self.assertEqual(ctx.snapshot(), before)
        self.assertEqual(a1, a2)
        self.assertEqual(json.dumps(a1.to_dict(), sort_keys=True),
                         json.dumps(a2.to_dict(), sort_keys=True))

    def test_reference_block_is_plain_data_and_detached(self):
        a = run(["یه جوک بگو", "دوباره"])[1]
        json.dumps(a.to_dict())
        a.structure["context"]["reference"]["again"] = "x"
        self.assertEqual(a.to_dict()["structure"]["context"]["reference"]["again"], "x")
        self.assertTrue(ref(run(["یه جوک بگو", "دوباره"])[1])["again"] is True)

    def test_no_new_registry_components(self):
        self.assertEqual([c.name for c in build_default_registry().components("annotator")],
                         ["question", "request", "negation", "correction", "context"])


class TestBackwardCompatibility(unittest.TestCase):
    CORPUS = ["من عرفان هستم", "اسم من چیه؟", "لطفا یه جوک بگو", "پایتون چیه؟",
              "و جاوا چی؟", "دوباره", "نه منظورم علی بود", "من پیتزا رو دوست ندارم",
              "What is the weather", "", "سلام"]

    def test_primary_results_identical_with_and_without_context(self):
        ctx = NLUConversationContext()
        for t in self.CORPUS:
            with_ctx = P.analyze(t, ctx)
            ctx.record(with_ctx)
            self.assertEqual(with_ctx.result.to_dict(), analyze_persian(t).to_dict(), t)
            self.assertEqual(with_ctx.result, P.analyze(t).result, t)

    def test_other_blocks_unchanged_by_reference_block(self):
        ctx = NLUConversationContext()
        run(["پایتون چیه؟"], ctx)
        a = P.analyze("نه منظورم جاوا بود", ctx)
        self.assertIn("correction", a.structure)
        c = a.structure["context"]
        for k in ("turn_index", "previous_intent", "previous_text",
                  "same_intent_as_previous", "is_repeat", "follows_question", "continuation"):
            self.assertIn(k, c)

    def test_without_context_no_context_block(self):
        self.assertNotIn("context", P.analyze("دوباره").structure)

    def test_non_persian_input_gets_no_context_block(self):
        ctx = NLUConversationContext()
        run(["یه جوک بگو"], ctx)
        self.assertNotIn("context", P.analyze("again please", ctx).structure)

    def test_persian_nlu_wrapper_exposes_reference(self):
        nlu, ctx = PersianNLU(), NLUConversationContext()
        nlu.analyze_in_context("یه جوک بگو", ctx)
        a = nlu.analyze_in_context("دوباره", ctx)
        self.assertEqual(ref(a)["inherited_intent"], INTENT_REQUEST)


class TestCoreUnchanged(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.core = Core(os.path.join(self.tmp.name, "memory.db"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_core_reply_and_memory_unaffected_and_reference_available(self):
        script = ["من عرفان هستم", "یه جوک بگو", "دوباره", "و جاوا چی؟"]
        before = self.core.memory.counts()
        replies = [self.core.process_input(s) for s in script]
        self.assertTrue(all(isinstance(r, str) for r in replies))
        r = self.core.last_nlu_analysis.structure["context"]["reference"]
        self.assertEqual(r["referenced_turn"], 2)
        # only the introduced name could have been stored, as before
        after = self.core.memory.counts()
        self.assertLessEqual(after["knowledge_count"] - before["knowledge_count"], 1)
        self.core.reset_context()
        self.assertTrue(self.core.nlu_context.is_empty)


if __name__ == "__main__":
    unittest.main()
