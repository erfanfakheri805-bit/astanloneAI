"""
Prompt 828 - normalized structured NLU output focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_nlu_structured_output_prompt828 -v
"""

import copy
import json
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from understanding.persian_nlu import PersianNLU, analyze_persian, INTENT_UNKNOWN
from understanding.nlu_pipeline import (
    NLUConversationContext, NLUAnalysis, NLUPipeline, NLURegistry, FunctionComponent,
    KIND_ANNOTATOR, build_default_registry, default_pipeline,
)
from understanding.nlu_structured_output import (
    normalize_nlu_analysis, SCHEMA_VERSION, BUILTIN_BLOCKS,
)

P = default_pipeline()

TOP_KEYS = ["schema_version", "intent", "recognized", "confidence", "matched_rule",
            "normalized_text", "entities", "facts", "decided_by", "question", "request",
            "negation", "correction", "context", "extras", "errors"]

CORPUS = ["من عرفان هستم", "اسم من چیه؟", "لطفا یه جوک بگو", "پایتون چیه؟", "و جاوا چی؟",
          "دوباره", "نه منظورم علی بود", "اشتباه گفتم", "من پیتزا رو دوست ندارم",
          "لطفا اینو نکن", "من خسته هستم", "What is the weather", "", "   ", "؟", "سلام"]


def shape(d, prefix=""):
    """Recursive key-shape of a normalized dict (values ignored, except
    that fixed sub-blocks are descended; entities/extras/refers_to are
    free-form or optional and are not)."""
    out = []
    for k, v in d.items():
        out.append(prefix + k)
        if isinstance(v, dict) and k not in ("entities", "extras", "refers_to"):
            out.extend(shape(v, prefix + k + "."))
    return out


class TestShape(unittest.TestCase):
    def test_top_level_keys_and_order_are_fixed(self):
        for t in CORPUS:
            self.assertEqual(list(P.analyze(t).normalized())[:len(TOP_KEYS)], TOP_KEYS, repr(t))  # Prompt 829 appends "slots"

    def test_shape_identical_for_every_input_and_context(self):
        ctx = NLUConversationContext()
        shapes = set()
        for t in CORPUS:
            a = P.analyze(t, ctx)
            ctx.record(a)
            shapes.add(tuple(shape(a.normalized())))
            shapes.add(tuple(shape(P.analyze(t).normalized())))
        self.assertEqual(len(shapes), 1)

    def test_all_builtin_blocks_present_with_present_flag(self):
        n = P.analyze("پایتون چیه؟").normalized()
        self.assertEqual(BUILTIN_BLOCKS, ("question", "request", "negation", "correction", "context"))
        self.assertTrue(n["question"]["present"])
        for name in ("request", "negation", "correction", "context"):
            self.assertFalse(n[name]["present"], name)

    def test_schema_version(self):
        self.assertEqual(P.analyze("سلام").normalized()["schema_version"], SCHEMA_VERSION)
        self.assertEqual(SCHEMA_VERSION, 1)

    def test_question_block_values(self):
        n = P.analyze("اسم من چیه؟").normalized()
        self.assertEqual((n["question"]["type"], n["question"]["topic"]), ("what", "user_name"))
        self.assertTrue(n["question"]["has_question_mark"])

    def test_request_block_values_and_prohibition(self):
        n = P.analyze("لطفا اینو نکن").normalized()
        self.assertTrue(n["request"]["present"])
        self.assertTrue(n["request"]["prohibition"])
        self.assertTrue(n["negation"]["present"])
        self.assertEqual(n["negation"]["count"], len(n["negation"]["markers"]))

    def test_correction_block_values(self):
        ctx = NLUConversationContext()
        ctx.record(P.analyze("پایتون چیه؟", ctx))
        n = P.analyze("نه منظورم جاوا بود", ctx).normalized()
        c = n["correction"]
        self.assertEqual((c["present"], c["kind"], c["explicit"]), (True, "replacement", True))
        self.assertEqual(c["corrected_text"], "جاوا")
        self.assertEqual(set(c["refers_to"]), {"turn_index", "intent", "normalized_text"})
        self.assertEqual(c["refers_to"]["turn_index"], 0)

    def test_context_block_values_and_reference(self):
        ctx = NLUConversationContext()
        ctx.record(P.analyze("یه جوک بگو", ctx))
        n = P.analyze("دوباره", ctx).normalized()
        c = n["context"]
        self.assertTrue(c["present"])
        self.assertEqual(c["turn_index"], 1)
        self.assertEqual(c["reference"]["inherited_intent"], "request")
        self.assertEqual(c["reference"]["effective_intent"], "request")
        self.assertEqual(n["intent"], INTENT_UNKNOWN)       # primary unchanged


class TestEmptyAndUnknown(unittest.TestCase):
    def test_empty_and_blank_inputs(self):
        for t in ("", "   ", "؟"):
            n = P.analyze(t).normalized()
            self.assertEqual(n["intent"], "unknown")
            self.assertFalse(n["recognized"])
            self.assertEqual(n["entities"], {})
            self.assertEqual(n["facts"], [])
            self.assertEqual(n["extras"], {})
            self.assertTrue(not any(n[b]["present"] for b in BUILTIN_BLOCKS))

    def test_no_context_gives_safe_context_defaults(self):
        n = P.analyze("سلام").normalized()
        c = n["context"]
        self.assertFalse(c["present"])
        self.assertIsNone(c["turn_index"])
        self.assertEqual(c["reference"]["effective_intent"], "unknown")   # = primary
        self.assertEqual(c["reference"]["repeat_count"], 0)

    def test_none_and_garbage_analysis_never_raise(self):
        base = normalize_nlu_analysis(None)
        self.assertEqual(list(base)[:len(TOP_KEYS)], TOP_KEYS)
        self.assertEqual(base["intent"], "unknown")
        for junk in (object(), 5, "x", [], {}):
            self.assertEqual(normalize_nlu_analysis(junk), base)

    def test_malformed_block_values_fall_back_to_safe_defaults(self):
        res = analyze_persian("پایتون چیه؟")
        a = NLUAnalysis(res, {
            "question": {"type": 5, "marker": ["x"], "has_question_mark": "yes", "topic": None},
            "negation": {"markers": "abc", "kinds": [1, "k", "k"], "count": -4},
            "correction": {"refers_to": "oops", "explicit": 1},
            "context": {"turn_index": True, "reference": 7},
        }, "q", ())
        n = normalize_nlu_analysis(a)
        self.assertIsNone(n["question"]["type"])
        self.assertFalse(n["question"]["has_question_mark"])
        self.assertEqual(n["negation"]["markers"], [])
        self.assertEqual(n["negation"]["kinds"], ["k"])
        self.assertEqual(n["negation"]["count"], 0)
        self.assertIsNone(n["correction"]["refers_to"])
        self.assertFalse(n["correction"]["explicit"])
        self.assertIsNone(n["context"]["turn_index"])
        self.assertEqual(n["context"]["reference"]["effective_intent"], "question")
        json.dumps(n)

    def test_unknown_blocks_are_kept_as_detached_extras_sorted(self):
        reg = build_default_registry()
        reg.register(FunctionComponent("zeta", KIND_ANNOTATOR, lambda inp: {"z": [1, 2]}, 200))
        reg.register(FunctionComponent("alpha", KIND_ANNOTATOR, lambda inp: {"a": {"b": 1}}, 210))
        a = NLUPipeline(reg).analyze("سلام")
        n = a.normalized()
        self.assertEqual(list(n["extras"]), ["alpha", "zeta"])
        n["extras"]["zeta"]["z"].append(3)
        self.assertEqual(a.structure["zeta"]["z"], [1, 2])

    def test_component_errors_are_reported_as_pairs(self):
        reg = build_default_registry()

        def boom(inp):
            raise RuntimeError("x")
        reg.register(FunctionComponent("boom", KIND_ANNOTATOR, boom, 300))
        n = NLUPipeline(reg).analyze("سلام").normalized()
        self.assertEqual(n["errors"], [["boom", "RuntimeError"]])


class TestDeterminismAndPurity(unittest.TestCase):
    def test_same_input_same_output_and_json_stable(self):
        for t in CORPUS:
            a, b = P.analyze(t), P.analyze(t)
            self.assertEqual(a.normalized(), b.normalized())
            self.assertEqual(json.dumps(a.normalized(), sort_keys=False, ensure_ascii=False),
                             json.dumps(b.normalized(), sort_keys=False, ensure_ascii=False))

    def test_normalizing_does_not_modify_analysis_or_context(self):
        ctx = NLUConversationContext()
        ctx.record(P.analyze("پایتون چیه؟", ctx))
        a = P.analyze("نه منظورم جاوا بود", ctx)
        before_a, before_c = copy.deepcopy(a.to_dict()), ctx.snapshot()
        n = a.normalized()
        n["intent"] = "changed"
        n["correction"]["corrected_text"] = "changed"
        n["entities"]["x"] = 1
        self.assertEqual(a.to_dict(), before_a)
        self.assertEqual(ctx.snapshot(), before_c)
        self.assertEqual(a.normalized()["intent"], "unknown")

    def test_output_is_json_serializable(self):
        for t in CORPUS:
            json.dumps(P.analyze(t).normalized(), ensure_ascii=False)

    def test_method_and_function_agree(self):
        a = P.analyze("من عرفان هستم")
        self.assertEqual(a.normalized(), normalize_nlu_analysis(a))


class TestCompatibility(unittest.TestCase):
    def test_primary_result_copied_verbatim(self):
        ctx = NLUConversationContext()
        for t in CORPUS:
            a = P.analyze(t, ctx)
            ctx.record(a)
            n = a.normalized()
            r = a.result
            self.assertEqual(n["intent"], r.intent, t)
            self.assertEqual(n["confidence"], r.confidence)
            self.assertEqual(n["matched_rule"], r.matched_rule)
            self.assertEqual(n["normalized_text"], r.normalized_text)
            self.assertEqual(n["entities"], r.entities)
            self.assertEqual(n["facts"], [dict(f) for f in r.facts])
            self.assertEqual(n["decided_by"], a.component)
            self.assertEqual(n["intent"], analyze_persian(t).intent)

    def test_normalized_presence_matches_structure_keys(self):
        ctx = NLUConversationContext()
        for t in CORPUS:
            a = P.analyze(t, ctx)
            ctx.record(a)
            n = a.normalized()
            for b in BUILTIN_BLOCKS:
                self.assertEqual(n[b]["present"], b in a.structure, (t, b))

    def test_existing_analysis_api_unchanged(self):
        a = P.analyze("پایتون چیه؟")
        self.assertEqual(set(a.to_dict()), {"result", "structure", "component", "errors"})
        self.assertTrue(a.is_question and not a.is_request)
        self.assertEqual(a.intent, "question")
        self.assertNotIn("present", a.structure["question"])   # raw blocks untouched

    def test_default_registry_and_pipeline_unchanged(self):
        self.assertEqual([c.name for c in build_default_registry().components("annotator")],
                         ["question", "request", "negation", "correction", "context"])
        self.assertIsInstance(PersianNLU().analyze_structured("سلام"), NLUAnalysis)


class TestCoreUnchanged(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.core = Core(os.path.join(self.tmp.name, "memory.db"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_core_behavior_and_memory_unchanged_and_normalized_available(self):
        self.core.process_input("من عرفان هستم")
        counts = self.core.memory.counts()
        self.core.process_input("پایتون چیه؟")
        self.core.process_input("و جاوا چی؟")
        n = self.core.last_nlu_analysis.normalized()
        self.assertEqual(list(n)[:len(TOP_KEYS)], TOP_KEYS)
        self.assertEqual(n["context"]["reference"]["referenced_turn"], 1)
        self.assertEqual(self.core.memory.counts()["knowledge_count"], counts["knowledge_count"])


if __name__ == "__main__":
    unittest.main()
