"""
Prompt 830 - semantic slot relations focused tests.

Run (from app/src/main/python/):
    python -m unittest tests.test_nlu_relations_prompt830 -v
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
from understanding.nlu_pipeline import NLUConversationContext, default_pipeline
from understanding.nlu_structured_output import normalize_nlu_analysis
from understanding.nlu_slots import extract_slots_from_analysis
from understanding.nlu_relations import (
    extract_relations, extract_relations_from_analysis, empty_relations,
    RELATIONS_VERSION, MAX_RELATIONS,
)

P = default_pipeline()
REL_KEYS = ["kind", "subject", "relation", "value", "slot", "start", "end"]


def rels(text):
    return extract_relations_from_analysis(P.analyze(text))


def tuples(text):
    return [(r["kind"], r["subject"], r["relation"], r["value"]) for r in rels(text)["items"]]


class TestValidRelations(unittest.TestCase):
    def test_name_ownership_man_hastam(self):
        self.assertEqual(tuples("من عرفان هستم"),
                         [("name_ownership", "من", "has_name", "عرفان")])

    def test_name_ownership_esm_man_forms(self):
        self.assertEqual(tuples("اسم من علی"), [("name_ownership", "اسم من", "has_name", "علی")])
        self.assertEqual(tuples("اسمم علی است"), [("name_ownership", "اسمم", "has_name", "علی")])

    def test_name_relation_points_at_name_slot_and_offsets(self):
        a = P.analyze("من عرفان هستم")
        r = extract_relations_from_analysis(a)["items"][0]
        self.assertEqual(a.normalized()["slots"]["items"][r["slot"]]["kind"], "name")
        t = a.result.normalized_text
        self.assertEqual(t[r["start"]:r["end"]], "عرفان")

    def test_key_value_assignment(self):
        self.assertEqual(tuples("سن: ۲۵ و age=30"),
                         [("key_value", "سن", "assigned", "25"),
                          ("key_value", "age", "assigned", "30")])
        a = P.analyze("نام: علی")
        r = extract_relations_from_analysis(a)["items"][0]
        self.assertEqual(a.result.normalized_text[r["start"]:r["end"]], "علی")

    def test_request_target(self):
        self.assertEqual(tuples("لطفا یه جوک بگو"),
                         [("request_target", "بگو", "targets", "یه جوک")])

    def test_quoted_text_target(self):
        self.assertEqual(tuples("لطفا «سلام دنیا» را بگو"),
                         [("request_target", "بگو", "targets", "«سلام دنیا» را"),
                          ("quoted_target", "بگو", "targets", "سلام دنیا")])
        self.assertEqual(tuples('لطفا "سلام" رو بگو')[1],
                         ("quoted_target", "بگو", "targets", "سلام"))

    def test_quoted_target_offsets_and_slot_link(self):
        a = P.analyze("لطفا «سلام دنیا» را بگو")
        r = [x for x in extract_relations_from_analysis(a)["items"]
             if x["kind"] == "quoted_target"][0]
        slot = a.normalized()["slots"]["items"][r["slot"]]
        self.assertEqual((slot["kind"], slot["value"]), ("quoted", "سلام دنیا"))
        self.assertEqual(a.result.normalized_text[r["start"]:r["end"]], "سلام دنیا")

    def test_key_value_inside_request_is_reported_too(self):
        self.assertEqual([k for k, *_ in tuples("لطفا age=30 بگو")],
                         ["request_target", "key_value"])

    def test_every_relation_has_the_same_keys(self):
        for t in ("من عرفان هستم", "نام: علی", "لطفا «x» را بگو", "لطفا یه جوک بگو"):
            for r in rels(t)["items"]:
                self.assertEqual(list(r), REL_KEYS)

    def test_text_order_name_first_then_by_position(self):
        a = P.analyze("لطفا نام: علی را ذخیره کن")
        kinds = [r["kind"] for r in extract_relations_from_analysis(a)["items"]]
        self.assertEqual(kinds, ["request_target", "key_value"])


class TestMissingRelations(unittest.TestCase):
    def test_nothing_to_relate(self):
        for t in ("", "سلام", "پایتون چیه؟", "Hello", "I have 3 cats", "5", 'او گفت "سلام"'):
            self.assertEqual(rels(t), empty_relations(), repr(t))

    def test_lone_quote_without_request_has_no_relation(self):
        self.assertEqual(rels("او گفت «سلام»")["items"], [])

    def test_request_without_action_has_no_target(self):
        self.assertEqual(rels("میشه یه داستان بنویسی؟")["items"], [])
        self.assertEqual(rels("لطفا «سلام» نگو")["items"], [])

    def test_name_without_owner_phrase_is_not_related(self):
        slots = {"items": [{"kind": "name", "key": None, "value": "علی",
                            "start": None, "end": None, "source": "entity"}]}
        self.assertEqual(extract_relations("علی آمد", slots)["items"], [])
        self.assertEqual(extract_relations("من کسی هستم", slots)["items"], [])

    def test_bad_input_never_raises(self):
        for junk in (None, object(), 5, "x"):
            self.assertEqual(extract_relations_from_analysis(junk), empty_relations())
        for text, slots, req in ((None, None, None), ("", {}, {}), ("x", 5, "y"),
                                 ("x", {"items": "no"}, {"action": 1, "argument": 2}),
                                 ("x", {"items": [None, 3]}, [])):
            self.assertEqual(extract_relations(text, slots, req)["items"], [])


class TestAmbiguousRelations(unittest.TestCase):
    def test_conflicting_key_values_are_skipped_and_counted(self):
        r = rels("age=30 و age=31")
        self.assertEqual((r["items"], r["count"], r["ambiguous"]), ([], 0, 1))

    def test_same_key_same_value_is_not_a_conflict(self):
        r = rels("age=30 و age=30")
        self.assertEqual((r["count"], r["ambiguous"]), (2, 0))

    def test_conflict_does_not_hide_other_keys(self):
        self.assertEqual(tuples("age=30 و age=31 و city=Tehran"),
                         [("key_value", "city", "assigned", "Tehran")])

    def test_several_quotes_none_the_whole_argument(self):
        r = rels("لطفا «a» و «b» را بگو")
        self.assertEqual([x["kind"] for x in r["items"]], ["request_target"])
        self.assertEqual(r["ambiguous"], 1)

    def test_prohibition_is_not_reported_as_plain_target(self):
        a = P.analyze("لطفا یه جوک نگو")
        req = a.structure.get("request")
        r = extract_relations_from_analysis(a)
        if req and req.get("prohibition") and req.get("action") and req.get("argument"):
            self.assertEqual((r["items"], r["ambiguous"]), ([], 1))
        r2 = extract_relations("لطفا x بگو", {"items": []},
                               {"action": "بگو", "argument": "x", "marker": "لطفا",
                                "prohibition": True})
        self.assertEqual((r2["items"], r2["ambiguous"]), ([], 1))

    def test_unlocatable_name_is_not_guessed(self):
        # name text differs from what is literally after the owner phrase
        slots = {"items": [{"kind": "name", "key": None, "value": "عرفان",
                            "start": None, "end": None, "source": "entity"}]}
        self.assertEqual(extract_relations("من عرفانه هستم", slots)["items"][0]["value"], "عرفان")
        self.assertEqual(extract_relations("من X عرفان هستم", slots)["items"], [])


class TestBoundsDeterminismSafety(unittest.TestCase):
    def test_bounded_with_truncated_flag(self):
        text = " ".join("%s=v" % (chr(97 + i) * 2) for i in range(20))
        r = rels(text)
        self.assertLessEqual(r["count"], MAX_RELATIONS)
        self.assertEqual(r["count"], len(r["items"]))

    def test_truncation_flag_when_over_limit(self):
        slots = {"items": [{"kind": "key_value", "key": "k%d" % i, "value": "v",
                            "start": 0, "end": 1, "source": "text"} for i in range(MAX_RELATIONS + 4)]}
        r = extract_relations("k0:v", slots)
        self.assertEqual((r["count"], r["truncated"]), (MAX_RELATIONS, True))

    def test_deterministic_and_json_safe(self):
        for t in ("من عرفان هستم", "لطفا «سلام» را بگو", "age=30 و age=31", ""):
            a = P.analyze(t)
            first, second = extract_relations_from_analysis(a), extract_relations_from_analysis(a)
            self.assertEqual(first, second)
            self.assertIsNot(first, second)
            json.dumps(first, ensure_ascii=False)
            self.assertEqual(first["version"], RELATIONS_VERSION)

    def test_inputs_are_not_modified(self):
        a = P.analyze("لطفا «سلام» را بگو و age=30")
        slots = extract_slots_from_analysis(a)
        req = copy.deepcopy(a.structure.get("request"))
        before = (copy.deepcopy(slots), copy.deepcopy(a.structure), a.result.to_dict())
        extract_relations_from_analysis(a, slots)
        self.assertEqual((slots, a.structure, a.result.to_dict()), before)
        self.assertEqual(a.structure.get("request"), req)

    def test_values_are_exactly_the_slot_values(self):
        for t in ("نام: علی و age=30", "لطفا «سلام دنیا» را بگو", "من عرفان هستم"):
            a = P.analyze(t)
            items = a.normalized()["slots"]["items"]
            for r in extract_relations_from_analysis(a)["items"]:
                if r["slot"] is not None:
                    self.assertEqual(r["value"], items[r["slot"]]["value"])


class TestNormalizedOutputExposure(unittest.TestCase):
    def test_relations_appended_after_slots(self):
        n = P.analyze("من عرفان هستم و age=30").normalized()
        self.assertEqual(list(n)[-2:], ["slots", "relations"])
        self.assertEqual(set(n["relations"]),
                         {"version", "items", "count", "truncated", "ambiguous"})
        self.assertEqual(n["relations"], rels("من عرفان هستم و age=30"))

    def test_relations_always_present_with_stable_shape(self):
        for t in ("", "سلام", "من عرفان هستم", "لطفا «x» را بگو"):
            n = P.analyze(t).normalized()
            self.assertEqual(set(n["relations"]),
                             {"version", "items", "count", "truncated", "ambiguous"})
            self.assertEqual(n["relations"]["count"], len(n["relations"]["items"]))
        self.assertEqual(normalize_nlu_analysis(None)["relations"], empty_relations())

    def test_schema_version_and_earlier_keys_unchanged(self):
        n = P.analyze("پایتون چیه؟").normalized()
        self.assertEqual(n["schema_version"], 1)
        self.assertEqual(list(n)[:17], [
            "schema_version", "intent", "recognized", "confidence", "matched_rule",
            "normalized_text", "entities", "facts", "decided_by", "question", "request",
            "negation", "correction", "context", "extras", "errors", "slots"])

    def test_slots_identical_with_and_without_relations(self):
        for t in ("من عرفان هستم و age=30", 'او گفت "سلام" 5 بار', ""):
            a = P.analyze(t)
            self.assertEqual(a.normalized()["slots"], extract_slots_from_analysis(a))

    def test_normalized_is_deterministic_and_detached(self):
        a = P.analyze("لطفا «سلام» را بگو")
        n1, n2 = a.normalized(), a.normalized()
        self.assertEqual(n1, n2)
        n1["relations"]["items"].append("junk")
        self.assertEqual(a.normalized(), n2)


class TestBackwardCompatibility(unittest.TestCase):
    CORPUS = ["من عرفان هستم", "اسم من چیه؟", "لطفا یه جوک بگو", "پایتون چیه؟", "و جاوا چی؟",
              "دوباره", "نه منظورم علی بود", "من پیتزا رو دوست ندارم", "What is the weather",
              "", "سن: ۲۵", 'او گفت "سلام" 5 بار', "لطفا «سلام» را بگو"]

    def test_primary_result_entities_facts_slots_unchanged(self):
        ctx = NLUConversationContext()
        for t in self.CORPUS:
            a = P.analyze(t, ctx)
            ctx.record(a)
            n = a.normalized()
            self.assertEqual(a.result.to_dict(), analyze_persian(t).to_dict(), t)
            self.assertEqual(n["intent"], a.result.intent)
            self.assertEqual(n["entities"], a.result.entities)
            self.assertEqual(n["facts"], [dict(f) for f in a.result.facts])
            self.assertEqual(n["slots"], extract_slots_from_analysis(a))

    def test_raw_analysis_has_no_relations(self):
        a = P.analyze("لطفا «سلام» را بگو")
        self.assertNotIn("relations", a.structure)
        self.assertEqual(set(a.to_dict()), {"result", "structure", "component", "errors"})


class TestCoreMemoryUnchanged(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.core = Core(os.path.join(self.tmp.name, "memory.db"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_relations_available_and_memory_untouched(self):
        self.core.process_input("من عرفان هستم")
        counts = self.core.memory.counts()
        self.core.process_input("نام: علی و سن: 25")
        n = self.core.last_nlu_analysis.normalized()
        self.assertEqual([(r["kind"], r["subject"], r["value"]) for r in n["relations"]["items"]],
                         [("key_value", "نام", "علی"), ("key_value", "سن", "25")])
        self.assertEqual(self.core.memory.counts()["knowledge_count"], counts["knowledge_count"])


if __name__ == "__main__":
    unittest.main()
