"""Prompt 673 - Section 3: current-knowledge semantics of meaning_resolution._describe.

Audit (docs/section3_meaning_resolution_current_knowledge_prompt673.md): `_describe` has ONE call site
(`MeaningResolver._entry`, reached only from `_collect_related`). Its result travels, unchanged, through
MeaningResolver.resolve() to:
  * Core.resolve_language_meaning / Core.disambiguate_learned_meaning - explicit lookups (raw, labelled);
  * DeterministicFallbackBackend._resolve_learned_meanings -> LanguageUnderstandingResult.learned_meanings
    -> ResponsePlan.expression_meanings / concept references -> language guidance -> generation context
    (CURRENT conversational understanding and generated-answer evidence).

Genuine defect: the conversational path carried an INACTIVE concept's description (and made an item
RESOLVED because of a link to it). Fix: MeaningResolver.resolve_current() (inactive concept endpoints are
not followed) used by the fallback backend; resolve() stays raw/labelled.
"""
import os
import tempfile
import unittest

from core.core import Core
from language_intelligence.deterministic_fallback_backend import DeterministicFallbackBackend

TABLES = ("knowledge", "relationships", "learning_events", "language_learning_items", "language_item_relationships")
EN = "en"


def item(key):
    return {"language": EN, "item_type": "word", "key": key}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "c.db")
        self._open()

    def _open(self):
        self.core = Core(memory_db_path=self.db, skill_definitions_dir=os.path.join(self.tmp, "s"))
        self.k, self.ls, self.m = self.core.knowledge, self.core.learning, self.core.memory
        self.res = self.core.meaning_resolver

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

    def link(self, word, concept, meaning=None, relation="means"):
        self.core.learn_language_item(EN, "word", word, meaning=meaning)
        self.core.relate_language_items(item(word), {"concept": concept}, relation)

    def set_raw_status(self, name, status):
        self.m._conn.execute("UPDATE knowledge SET status = ? WHERE name = ?", (status, name))
        self.m._conn.commit()

    @staticmethod
    def related(result):
        return [(e["related"].get("concept"), e["related"].get("description"), e["related"].get("status"))
                for m in result.to_dict()["meanings"] for e in m["related"]]

    def raw(self, word):
        return self.res.resolve(word, language=EN)

    def cur(self, word, **kw):
        return self.res.resolve_current(word, language=EN, **kw)

    def understood(self, message):
        u = self.core.understand_language(message)
        return {x["expression"]: x for x in u.learned_meanings}


class ActiveConcept(Base):
    def test_active_concept_description_is_identical_raw_and_current(self):
        self.ls.teach("Snake", "a reptile", source="user")
        self.link("viper", "Snake")
        self.assertEqual(self.related(self.raw("viper")), [("Snake", "a reptile", "active")])
        self.assertEqual(self.raw("viper").to_dict(), self.cur("viper").to_dict())

    def test_active_reaches_current_conversation(self):
        self.ls.teach("Snake", "a reptile", source="user")
        self.link("viper", "Snake")
        got = self.understood("Tell me about the viper please")["viper"]
        self.assertEqual(got["status"], "RESOLVED")
        self.assertEqual(got["meanings"][0]["related"][0]["related"]["description"], "a reptile")


class InactiveConcept(Base):
    def setUp(self):
        super().setUp()
        self.ls.teach("Snake", "a reptile", source="user")
        self.link("viper", "Snake")
        self.link("adder", "Snake", meaning="a small snake")
        self.ls.set_status("Snake", "inactive")

    def test_raw_resolve_keeps_labelled_view(self):
        self.assertEqual(self.raw("viper").status, "RESOLVED")
        self.assertEqual(self.related(self.raw("viper")), [("Snake", "a reptile", "inactive")])

    def test_current_resolve_does_not_follow_inactive_concept(self):
        r = self.cur("viper")
        self.assertEqual((r.status, r.reason), ("NOT_FOUND", "no_learned_meaning"))
        self.assertEqual(self.related(r), [])
        self.assertFalse(r.truncated)

    def test_stored_item_meaning_survives_without_the_inactive_link(self):
        r = self.cur("adder")
        self.assertEqual(r.status, "RESOLVED")
        m = r.to_dict()["meanings"][0]
        self.assertEqual((m["meaning"], m["related"]), ("a small snake", []))

    def test_current_conversation_excludes_inactive_description(self):
        got = self.understood("Tell me about the viper please")["viper"]
        self.assertEqual((got["status"], got["meanings"]), ("NOT_FOUND", []))
        self.assertNotIn("reptile", str(self.core.understand_language("Tell me about the viper please").to_dict()))

    def test_response_plan_does_not_reference_inactive_concept(self):
        u = self.core.understand_language("Tell me about the viper please")
        self.assertNotIn("'concept': 'Snake'", str(u.response_plan))

    def test_explicit_lookups_are_raw(self):
        self.assertEqual(self.core.resolve_language_meaning("viper", language=EN).status, "RESOLVED")
        self.assertEqual(self.core.disambiguate_learned_meaning("viper", language=EN).status, "RESOLVED")


class CaseVariantsAndAmbiguity(Base):
    def test_inactive_endpoint_is_not_redirected_to_active_case_variant(self):
        self.ls.teach("Snake", "inactive reptile", source="user")
        self.ls.teach("snake", "active reptile", source="user")
        self.ls.set_status("Snake", "inactive")
        self.link("viper", "Snake")
        self.assertEqual(self.related(self.cur("viper")), [])
        self.assertEqual(self.related(self.raw("viper")), [("Snake", "inactive reptile", "inactive")])

    def test_inactive_case_variant_does_not_hide_active_endpoint(self):
        self.ls.teach("Python", "a language", source="user")
        self.ls.teach("python", "old", source="user")
        self.ls.set_status("python", "inactive")
        self.link("py", "Python")
        self.assertEqual(self.related(self.cur("py")), [("Python", "a language", "active")])

    def test_ambiguous_active_variants_each_endpoint_is_exact(self):
        self.ls.teach("Ada", "one", source="user")
        self.ls.teach("ADA", "two", source="user")
        self.link("first", "Ada")
        self.link("second", "ADA")
        self.assertEqual(self.related(self.cur("first")), [("Ada", "one", "active")])
        self.assertEqual(self.related(self.cur("second")), [("ADA", "two", "active")])
        self.assertIsNone(self.k.resolve_current_name("ada")["record"])  # name ambiguity untouched


class InactiveRelationshipEndpoints(Base):
    def test_inactive_endpoint_neither_reported_nor_traversed_nor_budgeted(self):
        for n in ("Dead", "Beyond", "Live"):
            self.ls.teach(n, n.lower() + " desc", source="user")
        self.link("w", "Dead")
        self.core.relate_language_items(item("w"), {"concept": "Live"}, "related")
        self.core.relate_language_items({"concept": "Dead"}, {"concept": "Beyond"}, "related")
        self.ls.set_status("Dead", "inactive")
        r = self.cur("w", max_depth=2, max_related=1)
        self.assertEqual([c for c, _, _ in self.related(r)], ["Live"])
        self.assertFalse(r.truncated)
        raw = self.res.resolve("w", language=EN, max_depth=2)
        self.assertIn("Dead", [c for c, _, _ in self.related(raw)])


class NoWritesAndPersistence(Base):
    def setUp(self):
        super().setUp()
        self.ls.teach("Snake", "a reptile", source="user")
        self.link("viper", "Snake")
        self.ls.set_status("Snake", "inactive")

    def test_read_only_operations_write_nothing(self):
        before = self.snap()
        self.raw("viper"); self.cur("viper")
        self.core.resolve_language_meaning("viper", language=EN)
        self.core.disambiguate_learned_meaning("viper", language=EN)
        self.core.understand_language("Tell me about the viper please")
        self.assertEqual(self.snap(), before)

    def test_close_reopen_persistence(self):
        self.reopen()
        self.assertEqual(self.cur("viper").status, "NOT_FOUND")
        self.assertEqual(self.raw("viper").status, "RESOLVED")

    def test_active_inactive_active_transitions(self):
        self.ls.set_status("Snake", "active")
        self.assertEqual(self.related(self.cur("viper")), [("Snake", "a reptile", "active")])
        self.ls.set_status("Snake", "inactive")
        self.assertEqual(self.cur("viper").status, "NOT_FOUND")
        self.ls.set_status("Snake", "active")
        self.reopen()
        self.assertEqual(self.related(self.cur("viper")), [("Snake", "a reptile", "active")])
        self.assertEqual(self.understood("Tell me about the viper please")["viper"]["status"], "RESOLVED")


class StubLegacyAndStubResolver(Base):
    def test_stub_concept_is_still_current(self):
        self.ls.teach("A", "x", source="user")
        self.k.relate("A", "Ghost", "related_to")  # auto-creates stub knowledge entry
        self.assertEqual(self.k.get("Ghost")["status"], "stub")
        self.link("boo", "Ghost")
        self.assertEqual(self.related(self.cur("boo")), [("Ghost", None, "stub")])

    def test_legacy_status_concept_is_still_current(self):
        self.ls.teach("Old", "legacy desc", source="user")
        self.set_raw_status("Old", "legacy")
        self.link("oldie", "Old")
        self.assertEqual(self.related(self.cur("oldie")), [("Old", "legacy desc", "legacy")])

    def test_resolver_without_resolve_current_still_works_in_backend(self):
        class Stub:
            def resolve(self, expression, language=None):
                return self.result

        stub = Stub()
        stub.result = self.raw("nothing-here")
        backend = DeterministicFallbackBackend(self.core.understanding, meaning_resolver=stub)
        meanings, warnings = backend._resolve_learned_meanings([{"text": "nothing-here"}], EN, [])
        self.assertEqual((len(meanings), warnings), (1, []))


if __name__ == "__main__":
    unittest.main()
