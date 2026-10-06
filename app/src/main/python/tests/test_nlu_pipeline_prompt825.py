"""
Prompt 825 - extensible Persian NLU pipeline / registry focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_nlu_pipeline_prompt825 -v
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from understanding.persian_nlu import (
    PersianNLU, PersianNLUResult, analyze_persian, V1_RULES,
    INTENT_INTRODUCE_NAME, INTENT_LIKE, INTENT_DISLIKE, INTENT_ASK_USER_NAME,
    INTENT_QUESTION, INTENT_REQUEST, INTENT_UNKNOWN,
)
from understanding.nlu_pipeline import (
    NLUComponent, FunctionComponent, NLURegistry, NLUPipeline, NLUAnalysis,
    NLUConversationContext, build_default_registry, default_pipeline,
    KIND_INTENT, KIND_ANNOTATOR,
)

FALLBACK_MARKER = "I don't have enough information"

# Every sentence shape the v1 stage knows about, plus near-misses.
CORPUS = [
    "من عرفان هستم", "اسم من عرفانه", "اسمم عرفان است", "نام من عرفان هست",
    "  من   علي   هستم ", "من خسته هستم", "من پیتزا رو دوست دارم",
    "من قهوه را دوست دارم", "من خیلی شکلات رو دوست دارم", "من پیتزا رو دوست ندارم",
    "اسم من چیه؟", "نام من چیست", "لطفا یه جوک بگو", "میشه کمک کنی؟",
    "نشون بده", "پایتون چیه؟", "چرا آسمون آبیه", "آیا میای؟", "امروز هوا خوبه",
    "What is the weather", "", "   ", "؟", "TEACH sun IS a star", "۱۲۳", "سلام خوبی",
    "من فرزانه هستم", "اسم من فرزانه", "من عرفان هستم؟", "لطفا",
]


class _Boom(NLUComponent):
    name = "boom"
    kind = KIND_INTENT
    priority = 1

    def analyze(self, inp):
        raise RuntimeError("broken")


# --------------------------------------------------------------------
class TestRegistry(unittest.TestCase):
    def _fc(self, name, kind=KIND_ANNOTATOR, priority=1000):
        return FunctionComponent(name, kind, lambda inp: None, priority)

    def test_register_get_names_len_contains(self):
        r = NLURegistry()
        a = self._fc("a")
        self.assertIs(r.register(a), a)
        self.assertIs(r.get("a"), a)
        self.assertIn("a", r)
        self.assertEqual(len(r), 1)
        self.assertIsNone(r.get("zzz"))

    def test_duplicate_rejected_unless_replace(self):
        r = NLURegistry()
        r.register(self._fc("a"))
        with self.assertRaises(ValueError):
            r.register(self._fc("a"))
        b = self._fc("a", priority=5)
        r.register(b, replace=True)
        self.assertIs(r.get("a"), b)
        self.assertEqual(len(r), 1)

    def test_validation(self):
        r = NLURegistry()
        for bad in (
            FunctionComponent("", KIND_INTENT, lambda i: None),
            FunctionComponent("  ", KIND_INTENT, lambda i: None),
            FunctionComponent("x", "bogus", lambda i: None),
            FunctionComponent("x", KIND_INTENT, lambda i: None, priority="1"),
            FunctionComponent("x", KIND_INTENT, lambda i: None, priority=True),
            object(),
        ):
            with self.assertRaises(ValueError):
                r.register(bad)
        self.assertEqual(len(r), 0)

    def test_order_by_priority_then_registration(self):
        r = NLURegistry()
        r.register(self._fc("late", priority=50))
        r.register(self._fc("first_tie", priority=10))
        r.register(self._fc("second_tie", priority=10))
        r.register(self._fc("early", priority=1))
        self.assertEqual(r.names(), ["early", "first_tie", "second_tie", "late"])

    def test_names_filtered_by_kind(self):
        r = NLURegistry()
        r.register(self._fc("i", KIND_INTENT))
        r.register(self._fc("a", KIND_ANNOTATOR))
        self.assertEqual(r.names(KIND_INTENT), ["i"])
        self.assertEqual(r.names(KIND_ANNOTATOR), ["a"])

    def test_unregister(self):
        r = NLURegistry()
        r.register(self._fc("a"))
        self.assertTrue(r.unregister("a"))
        self.assertFalse(r.unregister("a"))
        self.assertEqual(len(r), 0)

    def test_copy_is_independent(self):
        r = build_default_registry()
        c = r.copy()
        self.assertEqual(r.names(), c.names())
        c.unregister("question")
        self.assertIn("question", r)

    def test_default_registry_contents_and_order(self):
        r = build_default_registry()
        self.assertEqual(r.names(KIND_INTENT), ["v1." + n for n, _ in V1_RULES])
        self.assertEqual(r.names(KIND_ANNOTATOR),
                         ["question", "request", "negation", "correction", "context"])
        self.assertEqual(len(V1_RULES), 7)

    def test_default_registries_are_fresh(self):
        a, b = build_default_registry(), build_default_registry()
        a.unregister("negation")
        self.assertIn("negation", b)


# --------------------------------------------------------------------
class TestV1Equivalence(unittest.TestCase):
    """The pipeline's primary result must be exactly the v1 result."""

    def test_pipeline_primary_equals_analyze_persian(self):
        p = default_pipeline()
        for s in CORPUS:
            with self.subTest(s=s):
                self.assertEqual(p.analyze(s).result.to_dict(), analyze_persian(s).to_dict())
                self.assertEqual(p.analyze_intent(s).to_dict(), analyze_persian(s).to_dict())

    def test_persian_nlu_analyze_still_returns_v1_result(self):
        nlu = PersianNLU()
        for s in CORPUS:
            with self.subTest(s=s):
                got = nlu.analyze(s)
                self.assertIsInstance(got, PersianNLUResult)
                self.assertEqual(got, analyze_persian(s))

    def test_matched_rule_and_deciding_component(self):
        a = default_pipeline().analyze("من عرفان هستم")
        self.assertEqual(a.result.matched_rule, "name_hastam")
        self.assertEqual(a.component, "v1.name_hastam")
        self.assertIsNone(default_pipeline().analyze("امروز هوا خوبه").component)

    def test_english_and_empty_never_claimed(self):
        p = default_pipeline()
        for s in ("What is x?", "", "   ", None):
            a = p.analyze(s)
            self.assertEqual(a.intent, INTENT_UNKNOWN)
            self.assertEqual(a.structure, {})
            self.assertEqual(a.errors, ())

    def test_deterministic(self):
        p = default_pipeline()
        ctx = NLUConversationContext()
        for s in CORPUS:
            self.assertEqual(p.analyze(s, ctx), p.analyze(s, ctx))


# --------------------------------------------------------------------
class TestExtensibility(unittest.TestCase):
    def test_custom_intent_after_v1_only_fires_when_v1_has_nothing(self):
        p = default_pipeline()

        def greet(inp):
            if inp.tokens and inp.tokens[0] == "سلام":
                return PersianNLUResult("greeting", {}, [], 0.8, inp.text, "greet")
            return None
        p.registry.register(FunctionComponent("greet", KIND_INTENT, greet, 500, True))
        self.assertEqual(p.analyze("سلام دوست من").intent, "greeting")
        self.assertEqual(p.analyze("سلام دوست من").component, "greet")
        # v1 still wins where it matches
        self.assertEqual(p.analyze("من عرفان هستم").intent, INTENT_INTRODUCE_NAME)

    def test_custom_intent_before_v1_can_take_precedence(self):
        p = default_pipeline()
        p.registry.register(FunctionComponent(
            "early", KIND_INTENT,
            lambda inp: PersianNLUResult("custom", {}, [], 1.0, inp.text, "early"), 1, True))
        self.assertEqual(p.analyze("من عرفان هستم").intent, "custom")

    def test_removing_a_v1_rule_changes_behavior_only_for_that_rule(self):
        p = default_pipeline()
        p.registry.unregister("v1.like_dislike")
        self.assertEqual(p.analyze("من پیتزا رو دوست دارم").intent, INTENT_UNKNOWN)
        self.assertEqual(p.analyze("من عرفان هستم").intent, INTENT_INTRODUCE_NAME)

    def test_custom_annotator_adds_block(self):
        p = default_pipeline()
        p.registry.register(FunctionComponent(
            "length", KIND_ANNOTATOR, lambda inp: {"tokens": len(inp.tokens)}, 900, True))
        a = p.analyze("یه جوک بگو")
        self.assertEqual(a.structure["length"], {"tokens": 3})

    def test_annotator_sees_primary_and_earlier_blocks(self):
        p = default_pipeline()
        seen = {}

        def probe(inp):
            seen["intent"] = inp.primary.intent
            seen["keys"] = sorted(inp.structure)
            return None
        p.registry.register(FunctionComponent("probe", KIND_ANNOTATOR, probe, 10_000, True))
        p.analyze("پایتون چیه؟")
        self.assertEqual(seen["intent"], INTENT_QUESTION)
        self.assertIn("question", seen["keys"])

    def test_non_persian_component_can_run_on_english(self):
        p = default_pipeline()
        p.registry.register(FunctionComponent(
            "en", KIND_INTENT,
            lambda inp: PersianNLUResult("en_hello", {}, [], 0.5, inp.text, "en")
            if inp.text.lower() == "hello" else None, 900, persian_only=False))
        self.assertEqual(p.analyze("hello").intent, "en_hello")
        self.assertEqual(p.analyze("What is x").intent, INTENT_UNKNOWN)

    def test_persian_only_component_skipped_for_english(self):
        p = default_pipeline()
        calls = []
        p.registry.register(FunctionComponent(
            "po", KIND_ANNOTATOR, lambda inp: calls.append(1), 900, persian_only=True))
        p.analyze("hello there")
        self.assertEqual(calls, [])

    def test_instances_do_not_share_registries(self):
        a, b = PersianNLU(), PersianNLU()
        a.registry.unregister("v1.question")
        self.assertIn("v1.question", b.registry)


class TestFailureIsolation(unittest.TestCase):
    def test_raising_intent_component_is_skipped_and_reported(self):
        p = default_pipeline()
        p.registry.register(_Boom())
        a = p.analyze("من عرفان هستم")
        self.assertEqual(a.intent, INTENT_INTRODUCE_NAME)
        self.assertEqual(a.errors, (("boom", "RuntimeError"),))
        # the v1 contract path also survives
        self.assertEqual(PersianNLU(p).analyze("من عرفان هستم").intent, INTENT_INTRODUCE_NAME)

    def test_wrong_return_types_reported(self):
        p = default_pipeline()
        p.registry.register(FunctionComponent("bad_i", KIND_INTENT, lambda i: "x", 1, True))
        p.registry.register(FunctionComponent("bad_a", KIND_ANNOTATOR, lambda i: [1], 1, True))
        a = p.analyze("یه جوک بگو")
        self.assertEqual(a.intent, INTENT_REQUEST)
        self.assertEqual(sorted(n for n, _ in a.errors), ["bad_a", "bad_i"])
        self.assertNotIn("bad_a", a.structure)

    def test_raising_annotator_does_not_drop_other_blocks(self):
        p = default_pipeline()

        def boom(inp):
            raise ValueError("x")
        p.registry.register(FunctionComponent("bad", KIND_ANNOTATOR, boom, 1, True))
        a = p.analyze("پایتون چیه؟")
        self.assertIn("question", a.structure)
        self.assertEqual(a.errors, (("bad", "ValueError"),))

    def test_empty_registry_returns_unknown(self):
        a = NLUPipeline().analyze("من عرفان هستم")
        self.assertEqual(a.intent, INTENT_UNKNOWN)
        self.assertEqual(a.structure, {})

    def test_structure_is_a_copy(self):
        p = default_pipeline()
        shared = {"k": [1]}
        p.registry.register(FunctionComponent("sh", KIND_ANNOTATOR, lambda i: shared, 900, True))
        a = p.analyze("یه جوک بگو")
        a.structure["sh"]["k"].append(2)
        self.assertEqual(shared, {"k": [1]})


# --------------------------------------------------------------------
class TestQuestions(unittest.TestCase):
    def setUp(self):
        self.p = default_pipeline()

    def _q(self, s):
        return self.p.analyze(s).structure.get("question")

    def test_types(self):
        cases = {
            "پایتون چیه؟": "what", "چرا آسمون آبیه": "why", "چطوری کار می کنه": "how",
            "کجا میری": "where", "کدوم بهتره": "which", "چقدر طول می کشه": "quantity",
            "آیا میای": "yes_no", "کیست": "who", "کی میای": "who_or_when",
        }
        for text, qtype in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self._q(text)["type"], qtype)

    def test_question_mark_without_word_is_yes_no(self):
        q = self._q("تو خوبی؟")
        self.assertEqual(q["type"], "yes_no")
        self.assertIsNone(q["marker"])
        self.assertTrue(q["has_question_mark"])

    def test_ask_user_name(self):
        q = self._q("اسم من چیه؟")
        self.assertEqual(q["topic"], "user_name")
        self.assertEqual(q["type"], "what")

    def test_agrees_with_primary_intent(self):
        for s in CORPUS:
            a = self.p.analyze(s)
            self.assertEqual(a.is_question,
                             a.intent in (INTENT_QUESTION, INTENT_ASK_USER_NAME), s)

    def test_statements_have_no_question_block(self):
        self.assertIsNone(self._q("من عرفان هستم"))
        self.assertIsNone(self._q("امروز هوا خوبه"))


class TestRequests(unittest.TestCase):
    def setUp(self):
        self.p = default_pipeline()

    def _r(self, s):
        return self.p.analyze(s).structure.get("request")

    def test_imperative(self):
        r = self._r("یه جوک بگو")
        self.assertEqual(r["form"], "imperative")
        self.assertEqual(r["action"], "بگو")
        self.assertEqual(r["argument"], "یه جوک")
        self.assertFalse(r["prohibition"])

    def test_polite_prefix(self):
        r = self._r("لطفا یه جوک بگو")
        self.assertEqual(r["form"], "polite")
        self.assertEqual(r["marker"], "لطفا")
        self.assertEqual(r["action"], "بگو")
        self.assertEqual(r["argument"], "یه جوک")

    def test_modal(self):
        r = self._r("میشه کمک کنی؟")
        self.assertEqual(r["form"], "modal")
        self.assertEqual(r["marker"], "میشه")

    def test_longest_action_wins(self):
        r = self._r("اینو نشون بده")
        self.assertEqual(r["action"], "نشون بده")
        self.assertEqual(r["argument"], "اینو")

    def test_bare_prefix_has_no_argument(self):
        r = self._r("لطفا")
        self.assertIsNone(r["argument"])
        self.assertIsNone(r["action"])

    def test_prohibition_flag(self):
        self.assertTrue(self._r("لطفا اینو نکن")["prohibition"])

    def test_agrees_with_primary_intent(self):
        for s in CORPUS:
            a = self.p.analyze(s)
            self.assertEqual(a.is_request, a.intent == INTENT_REQUEST, s)


class TestNegation(unittest.TestCase):
    def setUp(self):
        self.p = default_pipeline()

    def _n(self, s):
        return self.p.analyze(s).structure.get("negation")

    def test_kinds(self):
        cases = {
            "من خسته نیستم": "copula", "نمی خوام برم": "verb", "نمیخوام برم": "verb",
            "من وقت ندارم": "have", "اینو نکن": "prohibition", "نه": "particle",
            "نخواهم رفت": "future",
        }
        for text, kind in cases.items():
            with self.subTest(text=text):
                n = self._n(text)
                self.assertIsNotNone(n)
                self.assertIn(kind, n["kinds"])

    def test_zwnj_form_is_recognized(self):
        self.assertIsNotNone(self._n("نمی\u200cخوام"))

    def test_no_negation(self):
        for s in ("من عرفان هستم", "پایتون چیه؟", "یه جوک بگو", "نمک بده", "نشون بده"):
            self.assertIsNone(self._n(s), s)

    def test_dislike_is_folded_into_intent(self):
        a = self.p.analyze("من پیتزا رو دوست ندارم")
        self.assertEqual(a.intent, INTENT_DISLIKE)
        self.assertTrue(a.is_negated)
        self.assertTrue(a.structure["negation"]["folded_into_intent"])
        self.assertEqual(a.structure["negation"]["markers"], ["ندارم"])

    def test_negation_on_unknown_intent_does_not_change_intent(self):
        a = self.p.analyze("من خسته نیستم")
        self.assertEqual(a.intent, INTENT_UNKNOWN)
        self.assertTrue(a.is_negated)
        self.assertFalse(a.structure["negation"]["folded_into_intent"])

    def test_multiple_markers_counted(self):
        n = self._n("نه نمی خوام")
        self.assertEqual(n["count"], 2)
        self.assertEqual(n["kinds"], ["particle", "verb"])

    def test_negated_request(self):
        a = self.p.analyze("لطفا نرو")
        self.assertEqual(a.intent, INTENT_REQUEST)
        self.assertTrue(a.is_negated)
        self.assertTrue(a.structure["request"]["prohibition"])


class TestCorrections(unittest.TestCase):
    def setUp(self):
        self.p = default_pipeline()

    def _feed(self, *texts):
        ctx = NLUConversationContext()
        for t in texts:
            ctx.record(self.p.analyze(t, ctx))
        return ctx

    def test_explicit_replacement_without_context(self):
        c = self.p.analyze("نه، منظورم علی بود").structure["correction"]
        self.assertEqual(c["kind"], "replacement")
        self.assertEqual(c["corrected_text"], "علی")
        self.assertTrue(c["explicit"])
        self.assertIsNone(c["refers_to"])

    def test_explicit_replacement_links_previous_turn(self):
        ctx = self._feed("من عرفان هستم")
        c = self.p.analyze("منظور من علی بود", ctx).structure["correction"]
        self.assertEqual(c["refers_to"], {
            "turn_index": 0, "intent": INTENT_INTRODUCE_NAME, "normalized_text": "من عرفان هستم"})

    def test_retraction_and_retraction_with_replacement(self):
        c = self.p.analyze("اشتباه گفتم").structure["correction"]
        self.assertEqual((c["kind"], c["corrected_text"]), ("retraction", None))
        c = self.p.analyze("ببخشید اشتباه گفتم، اسمم علی است").structure["correction"]
        self.assertEqual(c["kind"], "replacement")
        self.assertEqual(c["corrected_text"], "اسمم علی است")

    def test_rejection(self):
        c = self.p.analyze("این اشتباهه").structure["correction"]
        self.assertEqual(c["kind"], "rejection")
        self.assertIsNone(c["corrected_text"])

    def test_leading_no_needs_previous_turn(self):
        self.assertFalse(self.p.analyze("نه، من علی هستم").is_correction)
        ctx = self._feed("من عرفان هستم")
        a = self.p.analyze("نه، من علی هستم", ctx)
        c = a.structure["correction"]
        self.assertEqual(c["corrected_text"], "من علی هستم")
        self.assertFalse(c["explicit"])
        self.assertEqual(c["refers_to"]["intent"], INTENT_INTRODUCE_NAME)

    def test_no_after_a_question_is_an_answer_not_a_correction(self):
        ctx = self._feed("اسم من چیه؟")
        self.assertFalse(self.p.analyze("نه، علی", ctx).is_correction)
        ctx = self._feed("پایتون چیه؟")
        self.assertFalse(self.p.analyze("نه، نمی دونم", ctx).is_correction)

    def test_bare_no_is_not_a_correction(self):
        ctx = self._feed("من عرفان هستم")
        a = self.p.analyze("نه", ctx)
        self.assertFalse(a.is_correction)
        self.assertTrue(a.is_negated)

    def test_clarification_without_past_marker_is_not_a_correction(self):
        self.assertFalse(self.p.analyze("منظورم اینه که بیای").is_correction)

    def test_primary_intent_untouched_by_correction(self):
        ctx = self._feed("من عرفان هستم")
        self.assertEqual(self.p.analyze("نه، منظورم علی بود", ctx).intent, INTENT_UNKNOWN)


class TestConversationContext(unittest.TestCase):
    def setUp(self):
        self.p = default_pipeline()

    def test_no_context_means_no_context_block(self):
        self.assertNotIn("context", self.p.analyze("سلام").structure)

    def test_first_turn(self):
        ctx = NLUConversationContext()
        c = self.p.analyze("سلام", ctx).structure["context"]
        self.assertEqual(c["turn_index"], 0)
        self.assertIsNone(c["previous_intent"])
        self.assertFalse(c["is_repeat"])

    def test_analyze_is_pure_and_record_stores(self):
        ctx = NLUConversationContext()
        self.p.analyze("من عرفان هستم", ctx)
        self.assertEqual(ctx.turn_count, 0)
        self.assertIsNone(ctx.previous)
        ctx.record(self.p.analyze("من عرفان هستم", ctx))
        self.assertEqual(ctx.turn_count, 1)
        self.assertEqual(ctx.previous.intent, INTENT_INTRODUCE_NAME)
        self.assertEqual(ctx.previous.entities, {"name": "عرفان"})

    def test_follow_ups(self):
        ctx = NLUConversationContext()
        ctx.record(self.p.analyze("پایتون چیه؟", ctx))
        c = self.p.analyze("و جاوا چی؟", ctx).structure["context"]
        self.assertEqual(c["turn_index"], 1)
        self.assertEqual(c["previous_intent"], INTENT_QUESTION)
        self.assertTrue(c["follows_question"])
        self.assertTrue(c["same_intent_as_previous"])
        self.assertEqual(c["continuation"], "و")

    def test_repeat_detection(self):
        ctx = NLUConversationContext()
        ctx.record(self.p.analyze("یه جوک بگو", ctx))
        self.assertTrue(self.p.analyze("یه جوک بگو", ctx).structure["context"]["is_repeat"])
        self.assertFalse(self.p.analyze("یه شعر بگو", ctx).structure["context"]["is_repeat"])

    def test_unknown_intents_are_not_the_same_intent(self):
        ctx = NLUConversationContext()
        ctx.record(self.p.analyze("امروز هوا خوبه", ctx))
        c = self.p.analyze("فردا هم خوبه", ctx).structure["context"]
        self.assertFalse(c["same_intent_as_previous"])

    def test_bounded(self):
        ctx = NLUConversationContext(max_turns=3)
        for i in range(10):
            ctx.record(self.p.analyze(f"جمله {i}", ctx))
        self.assertEqual(len(ctx.turns()), 3)
        self.assertEqual(ctx.turn_count, 10)
        self.assertEqual([t.index for t in ctx.turns()], [7, 8, 9])

    def test_reset(self):
        ctx = NLUConversationContext()
        ctx.record(self.p.analyze("سلام", ctx))
        ctx.reset()
        self.assertEqual(ctx.turn_count, 0)
        self.assertIsNone(ctx.previous)

    def test_invalid_size(self):
        for bad in (0, -1, True, "3", None):
            with self.assertRaises(ValueError):
                NLUConversationContext(max_turns=bad)

    def test_contexts_are_independent(self):
        a, b = NLUConversationContext(), NLUConversationContext()
        a.record(self.p.analyze("سلام", a))
        self.assertEqual(b.turn_count, 0)


class TestPersianNLUWrapper(unittest.TestCase):
    def test_analyze_in_context_records(self):
        nlu, ctx = PersianNLU(), NLUConversationContext()
        a = nlu.analyze_in_context("من عرفان هستم", ctx)
        self.assertIsInstance(a, NLUAnalysis)
        self.assertEqual(ctx.turn_count, 1)

    def test_analyze_structured_does_not_record(self):
        nlu, ctx = PersianNLU(), NLUConversationContext()
        nlu.analyze_structured("من عرفان هستم", ctx)
        self.assertEqual(ctx.turn_count, 0)

    def test_analyze_in_context_without_context(self):
        self.assertEqual(PersianNLU().analyze_in_context("سلام", None).intent, INTENT_UNKNOWN)

    def test_custom_pipeline_is_used_by_analyze(self):
        p = NLUPipeline()
        p.registry.register(FunctionComponent(
            "only", KIND_INTENT,
            lambda inp: PersianNLUResult("custom", {}, [], 1.0, inp.text, "only"), 1, True))
        self.assertEqual(PersianNLU(p).analyze("سلام").intent, "custom")


# --------------------------------------------------------------------
def _make_core():
    tmp = tempfile.TemporaryDirectory()
    core = Core(memory_db_path=os.path.join(tmp.name, "m.sqlite3"),
                skill_definitions_dir=os.path.join(tmp.name, "skills"))
    return core, tmp


class TestCoreIntegration(unittest.TestCase):
    def setUp(self):
        self.core, self._tmp = _make_core()

    def tearDown(self):
        self._tmp.cleanup()

    def test_analysis_exposed_and_matches_last_persian_nlu(self):
        self.core.process_input("پایتون چیه؟")
        a = self.core.last_nlu_analysis
        self.assertIsInstance(a, NLUAnalysis)
        self.assertIs(a.result, self.core.last_persian_nlu)
        self.assertEqual(a.structure["question"]["type"], "what")

    def test_replies_unchanged_for_v1_inputs(self):
        # Same assertions as the v1 stage: nothing about replies moved.
        self.assertIn("عرفان", self.core.process_input("من عرفان هستم"))
        self.assertIn("عرفان", self.core.process_input("اسم من چیه؟"))
        self.assertIn("پیتزا", self.core.process_input("من پیتزا رو دوست دارم"))
        q = self.core.process_input("پایتون چیه؟")
        r = self.core.process_input("یه جوک بگو")
        self.assertNotIn(FALLBACK_MARKER, q)
        self.assertNotIn(FALLBACK_MARKER, r)
        self.assertNotEqual(q, r)
        self.assertIn(FALLBACK_MARKER, self.core.process_input("امروز هوا خوبه"))
        self.assertIn(FALLBACK_MARKER, self.core.process_input("What is the weather"))

    def test_replies_identical_to_pre_pipeline_wiring(self):
        script = ["من عرفان هستم", "اسم من چیه؟", "من چای رو دوست دارم", "من چای رو دوست ندارم",
                  "یه جوک بگو", "پایتون چیه؟", "نه، منظورم علی بود", "سلام خوبی", "لطفا نکن"]
        new_core, t1 = _make_core()
        old_core, t2 = _make_core()
        try:
            # Reference: a Core whose NLU is the original stateless v1 function.
            class V1Only:
                def analyze(self, text):
                    return analyze_persian(text)

                def analyze_in_context(self, text, context):
                    class _A:
                        pass
                    a = _A()
                    a.result = analyze_persian(text)
                    return a
            old_core.persian_nlu = V1Only()
            self.assertEqual([new_core.process_input(s) for s in script],
                             [old_core.process_input(s) for s in script])
            self.assertEqual(new_core.memory.counts(), old_core.memory.counts())
        finally:
            t1.cleanup()
            t2.cleanup()

    def test_context_accumulates_across_turns(self):
        self.core.process_input("من عرفان هستم")
        self.core.process_input("پایتون چیه؟")
        self.assertEqual(self.core.nlu_context.turn_count, 2)
        ctx_block = self.core.last_nlu_analysis.structure["context"]
        self.assertEqual(ctx_block["previous_intent"], INTENT_INTRODUCE_NAME)
        self.assertEqual(ctx_block["turn_index"], 1)

    def test_correction_is_linked_but_not_applied(self):
        self.core.process_input("من عرفان هستم")
        reply = self.core.process_input("نه، منظورم علی بود")
        a = self.core.last_nlu_analysis
        self.assertTrue(a.is_correction)
        self.assertEqual(a.structure["correction"]["corrected_text"], "علی")
        self.assertEqual(a.structure["correction"]["refers_to"]["intent"], INTENT_INTRODUCE_NAME)
        # This stage only detects: reply is the existing fallback, name untouched.
        self.assertIn(FALLBACK_MARKER, reply)
        self.assertEqual(self.core.knowledge.get("کاربر.نام")["description"], "عرفان")

    def test_negation_structure_on_dislike_and_memory_unchanged(self):
        self.core.process_input("من پیتزا رو دوست ندارم")
        self.assertTrue(self.core.last_nlu_analysis.is_negated)
        self.assertEqual(self.core.knowledge.get("کاربر.دوست_ندارد.پیتزا")["status"], "active")

    def test_structure_blocks_store_nothing(self):
        before = self.core.memory.counts()["knowledge_count"]
        for s in ("پایتون چیه؟", "لطفا اینو نکن", "اشتباه گفتم", "من خسته نیستم"):
            self.core.process_input(s)
        self.assertEqual(self.core.memory.counts()["knowledge_count"], before)

    def test_reset_context_clears_nlu_context(self):
        self.core.process_input("من عرفان هستم")
        self.core.reset_context()
        self.assertEqual(self.core.nlu_context.turn_count, 0)
        self.assertIsNone(self.core.last_nlu_analysis)
        # memory is untouched by the reset
        self.assertEqual(self.core.knowledge.get("کاربر.نام")["description"], "عرفان")

    def test_registered_component_reaches_core_without_changing_replies(self):
        self.core.persian_nlu.registry.register(FunctionComponent(
            "greet", KIND_INTENT,
            lambda inp: PersianNLUResult("greeting", {}, [], 0.8, inp.text, "greet")
            if inp.tokens and inp.tokens[0] == "سلام" else None, 500, True))
        reply = self.core.process_input("سلام دوست من")
        self.assertEqual(self.core.last_persian_nlu.intent, "greeting")
        # Core has no handler for the new intent yet: existing fallback.
        self.assertIn(FALLBACK_MARKER, reply)

    def test_cores_do_not_share_nlu_state(self):
        other, tmp = _make_core()
        try:
            self.core.process_input("من عرفان هستم")
            self.assertEqual(other.nlu_context.turn_count, 0)
            self.core.persian_nlu.registry.unregister("v1.question")
            self.assertIn("v1.question", other.persian_nlu.registry)
        finally:
            tmp.cleanup()

    def test_deterministic_across_cores(self):
        runs = []
        for _ in range(2):
            core, tmp = _make_core()
            try:
                seq = []
                for s in ("من عرفان هستم", "نه، منظورم علی بود", "پایتون چیه؟", "و جاوا؟"):
                    core.process_input(s)
                    seq.append(core.last_nlu_analysis.to_dict())
                runs.append(seq)
            finally:
                tmp.cleanup()
        self.assertEqual(runs[0], runs[1])


class TestAELAndMemoryCompatibility(unittest.TestCase):
    def setUp(self):
        self.core, self._tmp = _make_core()

    def tearDown(self):
        self._tmp.cleanup()

    def test_ael_command_unchanged_and_not_recorded_as_nlu_turn(self):
        reply = self.core.process_input("TEACH sun IS a star")
        self.assertIn("[AEL OK]", reply)
        self.assertEqual(self.core.nlu_context.turn_count, 0)
        self.assertIsNone(self.core.last_nlu_analysis)
        self.assertIn("star", self.core.knowledge.get("sun")["description"])

    def test_ael_and_persian_facts_coexist(self):
        self.core.process_input("TEACH sun IS a star")
        self.core.process_input("من عرفان هستم")
        self.assertIn("star", self.core.process_input("What is sun?"))
        self.assertEqual(self.core.knowledge.get("کاربر.نام")["source"], "persian_nlu_v1")

    def test_memory_persists_across_cores(self):
        self.core.process_input("من عرفان هستم")
        db = os.path.join(self._tmp.name, "m.sqlite3")
        core2 = Core(memory_db_path=db,
                     skill_definitions_dir=os.path.join(self._tmp.name, "skills"))
        self.assertIn("عرفان", core2.process_input("اسم من چیه؟"))
        # the RAM-only NLU context is not persisted
        self.assertEqual(core2.nlu_context.turn_count, 1)


if __name__ == "__main__":
    unittest.main()
