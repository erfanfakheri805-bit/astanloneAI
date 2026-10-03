"""Prompt 674 - Section 3: current-knowledge safety of the variation matcher and pattern-meaning binder.

Audit result (docs/section3_variation_pattern_current_knowledge_prompt674.md): NO genuine defect, no production change.

  * LearnedExpressionVariationMatcher follows explicit language_item_relationships between LANGUAGE ITEMS only
    (a concept endpoint is skipped by construction) and never touches KnowledgeSystem.
  * LearnedPatternMeaningBinder reads only pattern -> "meaning"-typed LANGUAGE ITEM bindings (concept endpoints
    are excluded by construction); its candidates carry `related: []`; it never touches KnowledgeSystem.
  * Language items and language relationships have no lifecycle status, so "inactive" cannot arise inside either.
  * The only place where knowledge status matters downstream is MeaningResolver._collect_related (Prompt 673),
    reached AFTER a variation match; the current-use path (resolve_current) already filters inactive concepts.

These tests pin that reasoning on the real production paths only.
"""
import os
import tempfile
import unittest

from core.core import Core

TABLES = ("knowledge", "relationships", "learning_events", "language_learning_items",
          "language_item_relationships")


def ref(key, item_type="word", language="en"):
    return {"language": language, "item_type": item_type, "key": key}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "c.db")
        self._open()

    def _open(self):
        self.core = Core(memory_db_path=self.db, skill_definitions_dir=os.path.join(self.tmp, "s"))
        self.k, self.ls, self.m = self.core.knowledge, self.core.learning, self.core.memory

    def reopen(self):
        self.m._conn.close()
        self._open()

    def tearDown(self):
        try:
            self.m._conn.close()
        except Exception:
            pass

    def snap(self):
        return {t: self.m.query(f"SELECT * FROM {t} ORDER BY id") for t in TABLES}

    def set_raw_status(self, name, status):
        self.m._conn.execute("UPDATE knowledge SET status = ? WHERE name = ?", (status, name))
        self.m._conn.commit()

    def translation(self, source="salam", target="hello", meaning="a greeting"):
        """fa `source` --translation--> en `target` (the only shape a variation match takes)."""
        self.core.learn_language_item("fa", "word", source)
        self.core.learn_language_item("en", "word", target, meaning=meaning)
        self.core.relate_language_items(ref(source, language="fa"), ref(target), "translation")

    def variation(self, expression="salam"):
        return self.core.match_learned_expression_variation(expression, language="en")

    @staticmethod
    def concepts(result):
        return [(e["related"].get("concept"), e["related"].get("description"), e["related"].get("status"))
                for m in result.to_dict()["meanings"] for e in m["related"]
                if e["related"].get("kind") == "concept"]


class VariationMatcherIgnoresKnowledge(Base):
    def test_variation_match_is_identical_for_every_concept_lifecycle_state(self):
        self.ls.teach("Snake", "a reptile", source="user")
        self.translation()
        self.core.relate_language_items(ref("hello"), {"concept": "Snake"}, "means")
        self.core.relate_language_items(ref("salam", language="fa"), {"concept": "Snake"}, "means")
        seen = []
        for status in ("active", "inactive", "stub", "legacy", "active"):
            self.set_raw_status("Snake", status)
            r = self.variation()
            seen.append((r.status, [c["matched_expression"] for c in r.candidates]))
        self.assertEqual(set(map(str, seen)), {str(("MATCHED", ["hello"]))})

    def test_concept_endpoint_is_never_a_variation_candidate(self):
        self.ls.teach("Snake", "a reptile", source="user")
        self.core.learn_language_item("fa", "word", "mar")
        self.core.relate_language_items(ref("mar", language="fa"), {"concept": "Snake"}, "means")
        r = self.core.match_learned_expression_variation("mar", language="en")
        self.assertEqual((r.status, r.candidates), ("NOT_FOUND", []))

    def test_case_variant_concept_names_do_not_create_ambiguity(self):
        self.ls.teach("Ada", "one", source="user")
        self.ls.teach("ADA", "two", source="user")
        self.translation()
        self.core.relate_language_items(ref("hello"), {"concept": "Ada"}, "means")
        self.assertEqual(self.variation().status, "MATCHED")

    def test_ambiguity_only_comes_from_language_items(self):
        self.translation()
        self.core.learn_language_item("en", "word", "greetings", meaning="also")
        self.core.relate_language_items(ref("salam", language="fa"), ref("greetings"), "translation")
        r = self.variation()
        self.assertEqual(r.status, "AMBIGUOUS")
        self.assertEqual(sorted(c["matched_expression"] for c in r.candidates), ["greetings", "hello"])

    def test_directed_relationship_honoured_only_in_stated_direction(self):
        self.core.learn_language_item("fa", "word", "salam")
        self.core.learn_language_item("en", "word", "hello", meaning="a greeting")
        self.core.relate_language_items(ref("salam", language="fa"), ref("hello"), "rewrites_to",
                                        symmetric=False)
        self.assertEqual(self.variation().status, "MATCHED")
        self.assertEqual(self.core.match_learned_expression_variation("hello", language="fa").status,
                         "NOT_FOUND")


class ResolverAfterVariationMatch(Base):
    """Variation result -> MeaningResolver -> related concepts: this is where status matters (Prompt 673)."""

    def setUp(self):
        super().setUp()
        self.ls.teach("Snake", "a reptile", source="user")
        self.translation(target="viper", meaning=None)
        self.core.relate_language_items(ref("viper"), {"concept": "Snake"}, "means")

    def related(self, resolver_call):
        return [c[2] for c in self.concepts(resolver_call("salam", language="en"))]

    def test_active_source_active_target(self):
        r = self.core.meaning_resolver.resolve_current("salam", language="en")
        self.assertEqual((r.status, self.concepts(r)), ("RESOLVED", [("Snake", "a reptile", "active")]))
        self.assertTrue(r.to_dict()["meanings"][0]["matched_via_variation"])

    def test_inactive_concept_via_variation_raw_labelled_current_filtered(self):
        self.ls.set_status("Snake", "inactive")
        raw = self.core.meaning_resolver.resolve("salam", language="en")
        cur = self.core.meaning_resolver.resolve_current("salam", language="en")
        self.assertEqual(self.concepts(raw), [("Snake", "a reptile", "inactive")])
        # still RESOLVED - but only because of the explicit language-item (translation) link that produced the
        # variation match, never because of the inactive concept: no concept entry survives.
        self.assertEqual((cur.status, self.concepts(cur)), ("RESOLVED", []))
        kinds = {e["related"]["kind"] for m in cur.to_dict()["meanings"] for e in m["related"]}
        self.assertEqual(kinds, {"item"})

    def test_conversation_understanding_uses_current_view(self):
        self.ls.set_status("Snake", "inactive")
        got = {x["expression"]: x for x in self.core.understand_language("salam").learned_meanings}
        self.assertNotIn("reptile", str(got))

    def test_inactive_case_variant_does_not_redirect(self):
        self.ls.teach("snake", "active lower", source="user")
        self.ls.set_status("Snake", "inactive")
        cur = self.core.meaning_resolver.resolve_current("salam", language="en")
        self.assertEqual(self.concepts(cur), [])

    def test_stub_and_legacy_concepts_stay_current(self):
        self.set_raw_status("Snake", "legacy")
        cur = self.core.meaning_resolver.resolve_current("salam", language="en")
        self.assertEqual(self.concepts(cur), [("Snake", "a reptile", "legacy")])
        self.k.relate("A", "Ghost", "related_to")
        self.core.relate_language_items(ref("viper"), {"concept": "Ghost"}, "means")
        cur = self.core.meaning_resolver.resolve_current("salam", language="en")
        self.assertIn(("Ghost", None, "stub"), self.concepts(cur))

    def test_multi_hop_inactive_endpoint_not_traversed(self):
        self.ls.teach("Beyond", "further", source="user")
        self.core.relate_language_items({"concept": "Snake"}, {"concept": "Beyond"}, "related")
        self.ls.set_status("Snake", "inactive")
        cur = self.core.meaning_resolver.resolve_current("salam", language="en", max_depth=3)
        self.assertEqual(self.concepts(cur), [])

    def test_transitions_and_persistence(self):
        self.ls.set_status("Snake", "inactive")
        self.reopen()
        res = self.core.meaning_resolver
        self.assertEqual(self.concepts(res.resolve_current("salam", language="en")), [])
        self.ls.set_status("Snake", "active")
        self.reopen()
        self.assertEqual(self.related(self.core.meaning_resolver.resolve_current), ["active"])
        self.assertEqual(self.related(self.core.meaning_resolver.resolve), ["active"])


class PatternMeaningBinderIgnoresKnowledge(Base):
    def setUp(self):
        super().setUp()
        self.core.teach_sentence_pattern("en", "good morning")
        self.bound = self.core.bind_pattern_meaning("en", "good morning", "greet")

    def test_binding_created_through_explicit_api(self):
        self.assertEqual(self.bound.status, "BOUND")

    def test_resolution_is_independent_of_concept_status_and_carries_no_related(self):
        self.ls.teach("Greet", "hello concept", source="user")
        self.core.relate_language_items(ref("greet", item_type="meaning"), {"concept": "Greet"}, "means")
        results = []
        for status in ("active", "inactive", "stub", "legacy", "active"):
            self.set_raw_status("Greet", status)
            r = self.core.resolve_pattern_meaning("good morning", language="en")
            d = r.to_dict()
            results.append((d["status"], d["meaning"]["meaning_name"] if d["meaning"] else None,
                            [c["related"] for c in d["candidates"]]))
        self.assertEqual(set(map(str, results)), {str(("RESOLVED", "greet", [[]]))})

    def test_concept_binding_is_not_a_pattern_meaning(self):
        self.core.learn_language_item("en", "pattern", "bye")
        self.ls.teach("Farewell", "leaving", source="user")
        self.core.relate_language_items(ref("bye", item_type="pattern"), {"concept": "Farewell"},
                                        "pattern_meaning")
        r = self.core.resolve_pattern_meaning("bye", language="en")
        self.assertEqual(r.status, "NOT_FOUND")

    def test_ambiguity_only_from_several_bound_meaning_items(self):
        self.core.bind_pattern_meaning("en", "good morning", "wish")
        r = self.core.resolve_pattern_meaning("good morning", language="en")
        self.assertIn(r.status, ("AMBIGUOUS", "RESOLVED"))
        self.assertEqual(sorted(c["meaning_name"] for c in r.to_dict()["candidates"]), ["greet", "wish"])

    def test_conversation_plan_and_guidance_carry_no_concept_evidence(self):
        self.ls.teach("Greet", "hello concept", source="user")
        self.core.relate_language_items(ref("greet", item_type="meaning"), {"concept": "Greet"}, "means")
        self.ls.set_status("Greet", "inactive")
        u = self.core.understand_language("good morning")
        self.assertEqual(u.learned_pattern_meaning["status"], "RESOLVED")
        self.assertNotIn("hello concept", str(u.to_dict()))
        self.assertNotIn("hello concept", str(self.core.plan_language_response(u)))


class PatternMatcherVariationPath(Base):
    def test_variation_to_pattern_then_binder_is_status_independent(self):
        self.core.teach_sentence_pattern("en", "good morning")
        self.core.bind_pattern_meaning("en", "good morning", "greet")
        self.core.learn_language_item("en", "word", "gm")
        self.core.relate_language_items(ref("gm"), ref("good morning", item_type="pattern"), "variation")
        self.ls.teach("Greet", "hello concept", source="user")
        for status in ("inactive", "active"):
            self.set_raw_status("Greet", status)
            m = self.core.match_learned_pattern("gm", language="en")
            self.assertEqual(m.status, "MATCHED")
            self.assertEqual(self.core.resolve_pattern_meaning("gm", language="en").status, "RESOLVED")


class ReadOnlyGuarantees(Base):
    def test_no_writes_and_no_learning_events_from_read_paths(self):
        self.ls.teach("Snake", "a reptile", source="user")
        self.translation(target="viper", meaning=None)
        self.core.relate_language_items(ref("viper"), {"concept": "Snake"}, "means")
        self.core.teach_sentence_pattern("en", "good morning")
        self.core.bind_pattern_meaning("en", "good morning", "greet")
        self.ls.set_status("Snake", "inactive")
        before = self.snap()
        self.variation()
        self.core.match_learned_pattern("good morning", language="en")
        self.core.resolve_pattern_meaning("good morning", language="en")
        self.core.meaning_resolver.resolve_current("salam", language="en")
        self.core.understand_language("salam")
        self.core.understand_language("good morning")
        self.assertEqual(self.snap(), before)


if __name__ == "__main__":
    unittest.main()
