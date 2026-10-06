"""
Prompt 831 - semantic interpretation layer focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_nlu_semantic_view_prompt831 -v
"""

import copy
import json
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from understanding.persian_nlu import analyze_persian
from understanding.nlu_pipeline import NLUConversationContext, NLUAnalysis, default_pipeline
from understanding.nlu_structured_output import normalize_nlu_analysis
from understanding.nlu_slots import extract_slots_from_analysis
from understanding.nlu_relations import extract_relations_from_analysis
from understanding.nlu_semantic_view import (
    build_semantic_view, semantic_view_from_normalized, empty_semantic_view,
    SEMANTIC_VIEW_VERSION,
)

P = default_pipeline()
TOP = ["version", "intent", "context", "slots", "relations", "bounds"]
CTX = ["present", "turn_index", "continuation", "again", "refers_to_previous",
       "repeat_count", "repeat_of", "referenced_turn", "inherited_intent"]


def view(text, ctx=None):
    return build_semantic_view(P.analyze(text, ctx))


class TestCombination(unittest.TestCase):
    def test_shape_and_key_order(self):
        v = view("من عرفان هستم")
        self.assertEqual(list(v), TOP)
        self.assertEqual(list(v["intent"]), ["primary", "effective", "recognized"])
        self.assertEqual(list(v["context"]), CTX)
        self.assertEqual(list(v["bounds"]),
                         ["slots_truncated", "relations_truncated", "relations_ambiguous"])
        self.assertEqual(v["version"], SEMANTIC_VIEW_VERSION)

    def test_intent_slots_relations_combined(self):
        v = view("من عرفان هستم")
        self.assertEqual(v["intent"], {"primary": "introduce_name",
                                       "effective": "introduce_name", "recognized": True})
        self.assertEqual(v["slots"], [{"kind": "name", "key": None, "value": "عرفان"}])
        self.assertEqual(v["relations"], [{"kind": "name_ownership", "subject": "من",
                                           "relation": "has_name", "value": "عرفان", "slot": 0}])

    def test_request_with_quoted_target(self):
        v = view("لطفا «سلام دنیا» را بگو")
        self.assertEqual(v["intent"]["primary"], "request")
        self.assertEqual([r["kind"] for r in v["relations"]], ["request_target", "quoted_target"])
        self.assertEqual(v["slots"], [{"kind": "quoted", "key": None, "value": "سلام دنیا"}])
        self.assertEqual(v["relations"][1]["slot"], 0)

    def test_slots_and_relations_match_existing_layers(self):
        for t in ("نام: علی و age=30", "لطفا age=30 بگو", "من عرفان هستم"):
            a = P.analyze(t)
            v = build_semantic_view(a)
            s = extract_slots_from_analysis(a)["items"]
            r = extract_relations_from_analysis(a)["items"]
            self.assertEqual(v["slots"], [{k: x[k] for k in ("kind", "key", "value")} for x in s])
            self.assertEqual(v["relations"], [{k: x[k] for k in
                             ("kind", "subject", "relation", "value", "slot")} for x in r])

    def test_effective_intent_and_context_reference_from_context(self):
        ctx = NLUConversationContext()
        for t in ("پایتون چیه؟", "و جاوا چی؟"):
            a = P.analyze(t, ctx)
            ctx.record(a)
        a = P.analyze("دوباره", ctx)
        v = build_semantic_view(a)
        ref = a.normalized()["context"]["reference"]
        self.assertEqual(v["intent"]["effective"], ref["effective_intent"])
        self.assertTrue(v["context"]["present"])
        self.assertTrue(v["context"]["again"])
        self.assertEqual(v["context"]["referenced_turn"], ref["referenced_turn"])
        self.assertEqual(v["context"]["inherited_intent"], ref["inherited_intent"])
        self.assertEqual(v["context"]["turn_index"], 2)

    def test_continuation_marker_is_a_context_reference(self):
        ctx = NLUConversationContext()
        ctx.record(P.analyze("پایتون چیه؟", ctx))
        v = view("و جاوا چی؟", ctx)
        self.assertTrue(v["context"]["present"])
        self.assertEqual(v["context"]["continuation"], "و")

    def test_no_context_means_no_reference(self):
        for t in ("من عرفان هستم", "سلام", ""):
            c = view(t)["context"]
            self.assertFalse(c["present"], t)
            self.assertEqual((c["repeat_count"], c["referenced_turn"], c["inherited_intent"]),
                             (0, None, None))

    def test_first_turn_with_context_object_has_no_reference(self):
        v = view("پایتون چیه؟", NLUConversationContext())
        self.assertFalse(v["context"]["present"])
        self.assertEqual(v["context"]["turn_index"], 0)


class TestEmptyAndUnknown(unittest.TestCase):
    def test_unknown_and_empty_messages(self):
        for t in ("", "   ", "xyzzy", "Hello"):
            v = view(t)
            self.assertEqual(v["intent"]["primary"], "unknown", repr(t))
            self.assertFalse(v["intent"]["recognized"])
            self.assertEqual(v["intent"]["effective"], "unknown")
            self.assertEqual((v["slots"], v["relations"]), ([], []))

    def test_unknown_with_slots_keeps_unknown_intent(self):
        v = view("I have 3 cats")
        self.assertEqual(v["intent"]["primary"], "unknown")
        self.assertEqual(v["slots"], [{"kind": "number", "key": None, "value": "3"}])
        self.assertEqual(v["relations"], [])

    def test_bad_input_gives_empty_view_without_raising(self):
        for junk in (None, object(), 5, "x"):
            self.assertEqual(build_semantic_view(junk), empty_semantic_view())
        for junk in (None, 5, "x", [], {}, {"intent": 5, "context": [], "slots": "no",
                                            "relations": {"items": [None, 1]}}):
            self.assertEqual(semantic_view_from_normalized(junk), empty_semantic_view())

    def test_empty_view_is_fresh_each_call(self):
        a, b = empty_semantic_view(), empty_semantic_view()
        self.assertEqual(a, b)
        a["slots"].append(1)
        self.assertEqual(empty_semantic_view(), b)


class TestBoundsAndSafety(unittest.TestCase):
    def test_bounded_like_slots_and_relations(self):
        text = " ".join("%s=v" % (chr(97 + i) * 2) for i in range(20))
        v = view(text)
        self.assertLessEqual(len(v["slots"]), 16)
        self.assertLessEqual(len(v["relations"]), 16)
        self.assertTrue(v["bounds"]["slots_truncated"])

    def test_ambiguity_count_is_carried(self):
        self.assertEqual(view("age=30 و age=31")["bounds"]["relations_ambiguous"], 1)
        self.assertEqual(view("age=30")["bounds"]["relations_ambiguous"], 0)

    def test_json_safe(self):
        for t in ("من عرفان هستم و age=30", "لطفا «سلام» را بگو", ""):
            json.dumps(view(t), ensure_ascii=False)

    def test_deterministic_and_detached(self):
        a = P.analyze("لطفا «سلام» را بگو")
        v1, v2 = build_semantic_view(a), build_semantic_view(a)
        self.assertEqual(v1, v2)
        self.assertIsNot(v1, v2)
        v1["slots"].append("junk")
        v1["intent"]["primary"] = "changed"
        self.assertEqual(build_semantic_view(a), v2)
        self.assertEqual(a.semantic_view(), v2)

    def test_same_text_in_fresh_pipelines_gives_same_view(self):
        t = "نام: علی و 5"
        self.assertEqual(view(t), build_semantic_view(default_pipeline().analyze(t)))


class TestBackwardCompatibility(unittest.TestCase):
    CORPUS = ["من عرفان هستم", "اسم من چیه؟", "لطفا یه جوک بگو", "پایتون چیه؟", "و جاوا چی؟",
              "دوباره", "نه منظورم علی بود", "من پیتزا رو دوست ندارم", "What is the weather",
              "", "سن: ۲۵", 'او گفت "سلام" 5 بار', "لطفا «سلام» را بگو"]

    def test_raw_analysis_and_normalized_output_unchanged(self):
        ctx = NLUConversationContext()
        for t in self.CORPUS:
            a = P.analyze(t, ctx)
            ctx.record(a)
            before = (a.to_dict(), copy.deepcopy(a.normalized()))
            build_semantic_view(a)
            a.semantic_view()
            self.assertEqual((a.to_dict(), a.normalized()), before, t)
            self.assertEqual(a.result.to_dict(), analyze_persian(t).to_dict(), t)

    def test_normalized_output_keys_unchanged_by_this_prompt(self):
        n = P.analyze("پایتون چیه؟").normalized()
        self.assertEqual(list(n)[-2:], ["slots", "relations"])
        self.assertNotIn("semantic", n)
        self.assertNotIn("semantic_view", n)
        self.assertEqual(n["schema_version"], 1)

    def test_raw_analysis_has_no_semantic_data(self):
        a = P.analyze("لطفا «سلام» را بگو")
        self.assertNotIn("semantic", a.structure)
        self.assertEqual(set(a.to_dict()), {"result", "structure", "component", "errors"})
        self.assertIsInstance(a, NLUAnalysis)

    def test_primary_intent_is_copied_not_redetected(self):
        for t in self.CORPUS:
            a = P.analyze(t)
            self.assertEqual(build_semantic_view(a)["intent"]["primary"],
                             normalize_nlu_analysis(a)["intent"], t)


class TestCoreMemoryUnchanged(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.core = Core(os.path.join(self.tmp.name, "memory.db"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_view_available_and_memory_untouched(self):
        self.core.process_input("من عرفان هستم")
        counts = self.core.memory.counts()
        self.core.process_input("نام: علی و سن: 25")
        v = self.core.last_nlu_analysis.semantic_view()
        self.assertEqual([(s["key"], s["value"]) for s in v["slots"]],
                         [("نام", "علی"), ("سن", "25")])
        self.assertEqual(self.core.memory.counts()["knowledge_count"], counts["knowledge_count"])


if __name__ == "__main__":
    unittest.main()
