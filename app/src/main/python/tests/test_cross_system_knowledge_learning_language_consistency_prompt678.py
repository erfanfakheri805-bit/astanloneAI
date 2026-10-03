"""Prompt 678 - Section 3: cross-system consistency of KnowledgeSystem / LearningSystem / Language Intelligence.

Audit result (docs/section3_cross_system_knowledge_learning_language_consistency_prompt678.md): every traced
cross-system transition already hands state over consistently, so NO production change was made. These tests
pin the verified invariants through REAL production APIs (Core.learn_from_text, LearningSystem, AEL via
Core.process_input, conversational correction, MeaningResolver current path, learned-knowledge context,
ReasoningEngine, Core fallback):

  * KnowledgeSystem rows are the single source of truth for current consumers; learning events and language
    items are history / references and never override or resurrect them.
  * Inactive state is respected on every crossing; explicit teach / correct (and AEL TEACH) reactivate.
  * Ambiguity among current case variants is never silently resolved; exact case wins; unique CI resolves.
  * Provenance (source / source_text / learning_method) crosses with the documented None-keeps semantics and
    events log the PERSISTED target and source.
  * Reads and true no-ops write nothing; failed / ambiguous operations leave every store unchanged; a failing
    event write rolls the knowledge mutation back.
"""
import os
import tempfile
import unittest

from core.core import Core
from language_intelligence.learned_knowledge_context import select_learned_knowledge

TABLES = ("knowledge", "relationships", "learning_events", "language_learning_items",
          "language_item_relationships")
LANG_TABLES = ("language_learning_items", "language_item_relationships")
KNOWLEDGE_EVENTS = ("teach", "correct", "status", "relate")
NOT_KNOWN = "I don't have enough information to answer that yet."
EN = "en"
NL = "understanding_engine"


def item(key):
    return {"language": EN, "item_type": "word", "key": key}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "c.db")
        self._open()

    def _open(self):
        self.core = Core(memory_db_path=self.db, skill_definitions_dir=os.path.join(self.tmp, "s"))
        self.k, self.ls, self.m, self.r = (self.core.knowledge, self.core.learning,
                                            self.core.memory, self.core.reasoning)

    def reopen(self):
        self.m._conn.close()
        self._open()

    def tearDown(self):
        try:
            self.m._conn.close()
        except Exception:
            pass

    # -- helpers -------------------------------------------------------------------------------------------
    def snap(self, tables=TABLES):
        """Table snapshots. `learning_events` is the KNOWLEDGE-learning history (teach/correct/status/relate);
        the language stores log their own `language_*` events (a separate, intentional stream)."""
        out = {}
        for t in tables:
            rows = self.m.query(f"SELECT * FROM {t} ORDER BY id")
            if t == "learning_events":
                rows = [r for r in rows if r["event_type"] in KNOWLEDGE_EVENTS]
            out[t] = rows
        return out

    def events(self):
        return [(e["event_type"], e["target"], e["source"]) for e in self.m.recent_learning_events(500)
                if e["event_type"] in KNOWLEDGE_EVENTS]

    def all_event_count(self):
        return len(self.m.query("SELECT * FROM learning_events"))

    def nl(self, text):
        return self.core.learn_from_text(text)

    def off(self, n):
        self.ls.set_status(n, "inactive")

    def on(self, n):
        self.ls.set_status(n, "active")

    def status(self, n):
        return self.k.get(n)["status"]

    def best(self, text):
        found = self.core._find_best_known_concept(text)
        return found["name"] if found else None

    def reply(self, text):
        return self.core.process_input(text)

    def sel(self, msg, terms):
        return select_learned_knowledge(msg, self.k, candidate_terms=list(terms))

    def link(self, word, concept):
        self.core.learn_language_item(EN, "word", word, meaning=None)
        self.core.relate_language_items(item(word), {"concept": concept}, "means")

    def understood(self, message):
        return {x["expression"]: x for x in self.core.understand_language(message).learned_meanings}

    @staticmethod
    def rows(rows, key):
        return [r[key] for r in rows]


# ----------------------------------------------------------------------------------------------------------
class NaturalLanguageLearningToCurrentRetrieval(Base):
    def test_nl_learn_creates_stubs_and_is_current_everywhere(self):
        res = self.nl("Python is a programming language.")
        self.assertEqual((res.errors, res.created_concepts), ([], ["Python", "programming language"]))
        self.assertEqual(self.status("Python"), "stub")
        self.assertIn("Python is a programming language.", self.reply("Tell me about Python"))
        self.assertEqual(self.r.reason("What is Python?").answer, "Python is a programming language.")
        self.assertEqual(self.sel("Tell me about Python", ("python",)).status, "SELECTED")     # relationship content
        self.assertEqual(self.k.resolve_current_name("python")["record"]["name"], "Python")    # unique CI

    def test_nl_provenance_and_event_identity(self):
        self.nl("Python is a programming language.")
        rec = self.k.get("Python")
        self.assertEqual((rec["source"], rec["learning_method"], rec["source_text"], rec["version"]),
                         (NL, "natural_language_understanding", "Python is a programming language.", 1))
        row = self.m.query("SELECT * FROM relationships")[0]
        self.assertEqual((row["from_name"], row["to_name"], row["relation_type"], row["source_type"]),
                         ("Python", "programming language", "IS_A", NL))
        self.assertEqual(self.events(), [("relate", "Python", NL)])                 # exactly one, no stub events

    def test_repeat_is_true_noop_no_second_event(self):
        self.nl("Python is a programming language.")
        before = self.snap()
        res = self.nl("Python is a programming language.")
        self.assertEqual(res.created_relationships, [])
        self.assertEqual(self.snap(), before)
        self.assertEqual(len(self.events()), 1)

    def test_nl_learn_then_teach_activates_and_keeps_language_provenance(self):
        self.nl("Python is a programming language.")
        self.ls.teach("Python", "a language", source="user")
        rec = self.k.get("Python")
        self.assertEqual((rec["status"], rec["description"], rec["source"], rec["version"]),
                         ("active", "a language", "user", 2))
        self.assertEqual((rec["learning_method"], rec["source_text"]),                # None keeps stored values
                         ("natural_language_understanding", "Python is a programming language."))
        self.assertEqual(self.events(), [("relate", "Python", NL), ("teach", "Python", "user")])
        self.assertEqual(len(self.k.relationships_for("Python")["outgoing"]), 1)     # relationship survives teach
        self.assertIn("a language", self.reply("Tell me about Python"))
        self.assertEqual(self.r.reason("What is Python?").answer, "a language")

    def test_nl_learn_then_explicit_correct_activates_stub_once(self):
        self.nl("Python is a programming language.")
        out = self.ls.correct("python", "a language", source="user")                  # unique CI, stub target
        self.assertEqual((out["name"], out["status"], out["description"]), ("Python", "active", "a language"))
        self.assertEqual(self.events(), [("relate", "Python", NL), ("correct", "Python", "user")])
        self.assertNotIn("python", self.rows(self.k.all(), "name"))                   # no competing record

    def test_teach_then_nl_reference_resolves_onto_taught_record(self):
        self.ls.teach("Python", "a language", source="user")
        before_names = self.rows(self.k.all(), "name")
        res = self.nl("python uses indentation.")
        self.assertEqual([i["subject"] for i in res.learned_items], ["Python"])       # unique CI -> stored name
        self.assertEqual(res.created_concepts, ["indentation"])
        self.assertEqual(sorted(self.rows(self.k.all(), "name")), sorted(before_names + ["indentation"]))
        self.assertEqual(self.events()[-1], ("relate", "Python", NL))
        self.assertEqual(self.status("Python"), "active")
        self.assertEqual(self.r.reason("What does Python use?").answer, "Python uses indentation.")

    def test_stub_created_by_nl_never_answers_with_a_none_description(self):
        self.nl("Python is a programming language.")
        self.assertNotIn("None", self.reply("Tell me about Python"))
        self.assertIsNone(self.k.get("Python")["description"])


class CorrectionIntegration(Base):
    def setUp(self):
        super().setUp()
        self.ls.teach("Python", "a snake", confidence=0.6, source="user",
                      source_text="Python is a snake.", learning_method="ael")

    def test_conversational_correction_updates_record_and_current_consumers(self):
        self.assertIn("[CORRECTION ACKNOWLEDGED]", self.reply("not a snake, I mean a programming language."))
        rec = self.k.get("Python")
        self.assertEqual((rec["description"], rec["source"], rec["learning_method"], rec["confidence"]),
                         ("a programming language", "user_correction", "explicit_correction", 0.6))
        self.assertIn("a programming language", self.reply("Tell me about Python"))
        self.assertEqual(self.r.reason("What is Python?").answer, "a programming language")
        self.assertEqual(self.k.search("snake"), [])
        corrections = [e for e in self.events() if e[0] == "correct"]
        self.assertEqual(corrections, [("correct", "Python", "user_correction")])       # persisted target + source

    def test_event_keeps_old_description_but_never_overrides_current_state(self):
        self.reply("not a snake, I mean a programming language.")
        detail = [e for e in self.m.recent_learning_events(50) if e["event_type"] == "correct"][0]["detail"]
        self.assertIn("a snake", detail)                                               # history remembers the old text
        self.assertNotIn("snake", self.reply("Tell me about Python"))                   # current consumers do not
        self.assertEqual(self.sel("Tell me about Python", ("python",)).record["description"], "a programming language")
        self.assertEqual(self.r.reason("What is Python?").answer, "a programming language")

    def test_correction_of_nl_learned_record_is_visible_to_language_meaning(self):
        self.link("py", "Python")
        self.assertIn("a snake", str(self.understood("Tell me about the py please")["py"]))
        self.reply("not a snake, I mean a programming language.")
        got = str(self.understood("Tell me about the py please")["py"])
        self.assertIn("a programming language", got)
        self.assertNotIn("a snake", got)                                                # no stale meaning

    def test_identical_correction_is_noop(self):
        self.reply("not a snake, I mean a programming language.")
        before = self.snap()
        self.reply("not a snake, I mean a programming language.")
        self.assertEqual(self.snap(TABLES[:3]), {t: before[t] for t in TABLES[:3]})

    def test_implicit_correction_never_targets_or_reactivates_inactive(self):
        self.off("Python")
        before = self.snap(("knowledge", "relationships"))
        self.reply("not a snake, I mean a programming language.")
        self.assertEqual(self.snap(("knowledge", "relationships")), before)
        self.assertEqual(self.status("Python"), "inactive")
        self.assertFalse([e for e in self.events() if e[0] == "correct"])

    def test_ambiguous_correction_target_writes_nothing(self):
        self.ls.teach("Cobra", "a snake", source="user")
        before = self.snap()
        self.reply("not a snake, I mean a programming language.")
        self.assertEqual(self.snap(("knowledge", "relationships", "learning_events")),
                         {t: before[t] for t in ("knowledge", "relationships", "learning_events")})


class InactiveTransitions(Base):
    def test_inactive_then_nl_reference_keeps_record_inactive_and_stores_history(self):
        self.ls.teach("Python", "a language", source="user")
        self.off("Python")
        n = len(self.events())
        res = self.nl("Python uses indentation.")
        self.assertEqual(res.errors, [])
        self.assertEqual(self.status("Python"), "inactive")                              # not resurrected (P665/666)
        self.assertEqual(self.events()[n:], [("relate", "Python", NL)])                   # no status event
        self.assertEqual(self.rows(self.k.relationships_for("Python")["outgoing"], "to_name"), ["indentation"])
        self.assertEqual(self.k.current_relationships_for("Python"), {"outgoing": [], "incoming": []})
        self.assertTrue(self.reply("Tell me about Python").startswith(NOT_KNOWN))
        self.assertEqual(self.r.reason("What does Python use?").status, "unknown")
        self.assertEqual(self.sel("Tell me about Python", ("python",)).status, "NOT_FOUND")

    def test_lowercase_nl_reference_resolves_onto_inactive_record_without_duplicate(self):
        self.ls.teach("Python", "a language", source="user")
        self.off("Python")
        self.nl("python uses tabs.")
        self.assertEqual(sorted(self.rows(self.k.all(), "name")), ["Python", "tabs"])
        self.assertEqual(self.status("Python"), "inactive")

    def test_explicit_teach_reactivates_and_relationships_return_as_evidence(self):
        self.ls.teach("Python", "a language", source="user")
        self.off("Python")
        self.nl("Python uses indentation.")
        self.ls.teach("Python", "a language again", source="user")
        self.assertEqual(self.status("Python"), "active")
        self.assertEqual(self.r.reason("What does Python use?").answer, "Python uses indentation.")
        self.assertIn("a language again", self.reply("Tell me about Python"))
        self.assertEqual(self.events()[-1], ("teach", "Python", "user"))

    def test_explicit_correct_reactivates_through_ci_name(self):
        self.ls.teach("Python", "a language", source="user")
        self.off("Python")
        self.ls.correct("python", "a better language", source="user")
        self.assertEqual((self.status("Python"), self.k.get("Python")["description"]), ("active", "a better language"))
        self.assertEqual(self.events()[-1], ("correct", "Python", "user"))

    def test_ael_teach_reactivates_and_logs_ael_event(self):
        self.ls.teach("Snake", "a reptile", source="user")
        self.off("Snake")
        self.assertIn("[AEL OK]", self.reply("TEACH Snake IS a legless reptile"))
        self.assertEqual(self.status("Snake"), "active")
        self.assertEqual(self.events()[-1], ("teach", "Snake", "ael"))

    def test_ael_relate_and_ask_stay_raw_across_inactive(self):
        self.ls.teach("Rust", "a language", source="user")
        self.ls.teach("Language", "a thing", source="user")
        self.assertIn("[AEL OK]", self.reply("RELATE Rust TO Language AS is_a"))
        self.off("Language")
        ask = self.reply("ASK Rust")
        self.assertIn("Rust is_a Language", ask)                                          # raw stored rows listed
        self.assertEqual(self.r.reason("What is Rust?").answer, "a language")             # description, current
        self.assertEqual(self.k.current_relationships_for("Rust")["outgoing"], [])

    def test_status_event_targets_persisted_name_and_source(self):
        self.ls.teach("Python", "a language", source="user")
        self.ls.set_status("python", "inactive")
        self.assertEqual(self.events()[-1], ("status", "Python", "user"))
        n = len(self.events())
        self.ls.set_status("Python", "inactive")                                          # true no-op
        self.assertEqual(len(self.events()), n)

    def test_events_are_history_not_current_state(self):
        self.ls.teach("Zed", "zed", source="user")
        self.off("Zed")
        self.assertEqual([e[0] for e in self.events()], ["teach", "status"])
        self.assertTrue(self.reply("Tell me about Zed").startswith(NOT_KNOWN))            # last 'teach' event != active
        self.assertEqual(self.k.get("Zed")["status"], "inactive")


class RelationshipEvidenceAcrossSystems(Base):
    def chain(self):
        self.nl("Alpha depends on Beta.")
        self.nl("Beta depends on Gamma.")

    def test_relationship_creation_reaches_reasoning(self):
        self.chain()
        self.assertEqual(self.r.reason("Does Alpha depend on Gamma?").answer,
                         "Alpha depends on Gamma (inferred).")

    def test_endpoint_deactivation_and_reactivation_reach_reasoning(self):
        self.chain()
        self.ls.teach("Beta", "middle", source="user")
        self.off("Beta")
        self.assertEqual(self.r.reason("Does Alpha depend on Gamma?").status, "unknown")
        self.assertEqual(len(self.k.relationships_for("Alpha")["outgoing"]), 1)        # stored row kept
        self.on("Beta")
        self.assertEqual(self.r.reason("Does Alpha depend on Gamma?").status, "answered")

    def test_active_inactive_endpoint_matrix_across_learning_paths(self):
        for src_on in (True, False):
            for dst_on in (True, False):
                with self.subTest(src=src_on, dst=dst_on):
                    self.tearDown()
                    self.setUp()
                    self.ls.teach("S", "s", source="user")
                    self.ls.teach("T", "t", source="user")
                    self.ls.relate("S", "T", "USES", source="user")
                    if not src_on:
                        self.off("S")
                    if not dst_on:
                        self.off("T")
                    expect = "S uses T." if (src_on and dst_on) else None
                    self.assertEqual(self.r.reason("What does S use?").answer, expect)

    def test_relationship_identity_is_exact_name_across_language_and_knowledge(self):
        self.ls.teach("Snake", "a reptile", source="user")
        with self.assertRaises(ValueError):                                              # no CI guessing, no creation
            self.core.learn_language_item(EN, "word", "viper", meaning=None)
            self.core.relate_language_items(item("viper"), {"concept": "snake"}, "means")
        self.assertEqual(self.rows(self.k.all(), "name"), ["Snake"])
        self.assertEqual(self.m.query("SELECT * FROM language_item_relationships"), [])
        self.core.relate_language_items(item("viper"), {"concept": "Snake"}, "means")
        self.assertEqual(len(self.m.query("SELECT * FROM language_item_relationships")), 1)

    def test_language_link_writes_no_knowledge_state_or_events(self):
        self.ls.teach("Snake", "a reptile", source="user")
        before = self.snap(("knowledge", "relationships", "learning_events"))
        self.link("viper", "Snake")
        self.assertEqual(self.snap(("knowledge", "relationships", "learning_events")), before)


class LanguageMeaningToConceptKnowledge(Base):
    def test_active_concept_flows_and_inactive_never_becomes_current_via_language_item(self):
        self.ls.teach("Snake", "a reptile", source="user")
        self.link("viper", "Snake")
        got = self.understood("Tell me about the viper please")["viper"]
        self.assertEqual(got["status"], "RESOLVED")
        lang_before = self.snap(LANG_TABLES)
        self.off("Snake")
        got = self.understood("Tell me about the viper please")["viper"]
        self.assertEqual((got["status"], got["meanings"]), ("NOT_FOUND", []))
        self.assertNotIn("reptile", str(self.core.understand_language("Tell me about the viper please").to_dict()))
        # language records are untouched and still reference the concept; they never resurrect it
        self.assertEqual(self.snap(LANG_TABLES), lang_before)
        self.assertEqual(self.status("Snake"), "inactive")
        self.assertEqual(self.core.resolve_language_meaning("viper", language=EN).status, "RESOLVED")   # raw
        self.assertNotIn("reptile", self.reply("Tell me about the viper"))

    def test_reactivation_paths_restore_language_meaning(self):
        self.ls.teach("Snake", "a reptile", source="user")
        self.link("viper", "Snake")
        for reactivate in (lambda: self.on("Snake"),
                           lambda: self.ls.teach("Snake", "a reptile v2", source="user"),
                           lambda: self.ls.correct("snake", "a reptile v3", source="user"),
                           lambda: self.reply("TEACH Snake IS a reptile v4")):
            with self.subTest():
                self.off("Snake")
                self.assertEqual(self.understood("Tell me about the viper please")["viper"]["status"], "NOT_FOUND")
                reactivate()
                self.assertEqual(self.understood("Tell me about the viper please")["viper"]["status"], "RESOLVED")

    def test_concept_correction_reaches_language_and_current_retrieval_immediately(self):
        self.ls.teach("Snake", "a reptile", source="user")
        self.link("viper", "Snake")
        self.ls.correct("Snake", "a legless reptile", source="user")
        self.assertIn("a legless reptile", str(self.understood("Tell me about the viper please")["viper"]))
        self.assertIn("a legless reptile", self.reply("Tell me about Snake"))

    def test_inactive_case_variant_endpoint_is_not_redirected(self):
        self.ls.teach("Snake", "inactive reptile", source="user")
        self.ls.teach("snake", "active reptile", source="user")
        self.off("Snake")
        self.link("viper", "Snake")
        self.assertEqual(self.understood("Tell me about the viper please")["viper"]["status"], "NOT_FOUND")
        self.link("adder", "snake")
        self.assertEqual(self.understood("Tell me about the adder please")["adder"]["status"], "RESOLVED")


class CaseIdentityAcrossBoundaries(Base):
    def two_variants(self):
        self.ls.teach("Python", "upper", source="user")
        self.ls.teach("PYTHON", "lower", source="user")

    def test_exact_case_wins_and_unique_ci_resolves_everywhere(self):
        self.ls.teach("Python", "a language", source="user")
        self.assertEqual(self.best("Tell me about python"), "Python")
        self.assertEqual(self.sel("about pYthon", ("python",)).record["name"], "Python")
        self.assertEqual(self.r.reason("What is PYTHON?").answer, "a language")
        self.assertEqual(self.k.resolve_current_name("python")["status"], "case_insensitive")

    def test_multiple_active_variants_are_never_silently_chosen(self):
        self.two_variants()
        self.assertIsNone(self.best("Tell me about python"))
        self.assertEqual(self.r.reason("What is python?").status, "unknown")
        self.assertEqual(self.sel("about python", ("python",)).status, "AMBIGUOUS")
        self.assertEqual(self.k.resolve_current_name("python")["candidates"], ["PYTHON", "Python"])
        with self.assertRaises(ValueError):
            self.ls.correct("python", "x", source="user")
        with self.assertRaises(ValueError):
            self.ls.set_status("python", "inactive")

    def test_ambiguous_cross_system_operations_leave_all_stores_unchanged(self):
        self.two_variants()
        self.link("py", "Python")
        before = self.snap()
        for fn in (lambda: self.ls.correct("python", "x", source="user"),
                   lambda: self.ls.set_status("python", "inactive"),
                   lambda: self.ls.correct("", "x"),
                   lambda: self.ls.teach("", "x"),
                   lambda: self.core.relate_language_items(item("py"), {"concept": "Nope"}, "means")):
            with self.assertRaises((ValueError, TypeError)):
                fn()
        self.assertEqual(self.snap(), before)

    def test_nl_learning_with_ambiguous_name_creates_new_concept_never_picks_one(self):
        self.two_variants()
        before_events = len(self.events())
        res = self.nl("python uses tabs.")
        self.assertEqual(res.errors, [])
        self.assertEqual([i["subject"] for i in res.learned_items], ["python"])           # P637/672 behavior kept
        self.assertEqual(self.k.get("Python")["version"], 1)
        self.assertEqual(self.k.get("PYTHON")["version"], 1)
        self.assertEqual(self.events()[before_events:], [("relate", "python", NL)])

    def test_active_plus_inactive_variants(self):
        self.two_variants()
        self.off("PYTHON")
        self.assertEqual(self.best("Tell me about python"), "Python")
        self.assertEqual(self.r.reason("What is python?").answer, "upper")
        self.assertEqual(self.sel("about pYthon", ("python",)).status, "AMBIGUOUS")       # P664 conservative
        self.assertEqual(self.k.resolve_name("python")["status"], "ambiguous")             # raw stays raw
        self.on("PYTHON")
        self.assertIsNone(self.best("Tell me about python"))

    def test_teach_case_variant_creates_distinct_record_but_correct_targets_existing(self):
        self.ls.teach("Python", "a language", source="user")
        self.off("Python")
        self.ls.teach("python", "a snake", source="user")                                  # exact identity: new record
        self.assertEqual(sorted(self.rows(self.k.all(), "name")), ["Python", "python"])
        self.assertEqual(self.status("Python"), "inactive")
        self.assertEqual(self.k.resolve_current_name("PYTHON")["record"]["name"], "python")


# ----------------------------------------------------------------------------------------------------------
class EventHistoryIntegrity(Base):
    def test_one_event_per_real_mutation_with_persisted_identity_and_source(self):
        self.ls.teach("Zed", "z", source="user")
        self.ls.correct("zed", "z2")                                                       # source None keeps 'user'
        self.ls.set_status("Zed", "inactive")
        self.ls.relate("Zed", "Yak", "USES", source="user")
        self.assertEqual(self.events(), [("teach", "Zed", "user"), ("correct", "Zed", "user"),
                                         ("status", "Zed", "user"), ("relate", "Zed", "user")])

    def test_true_noops_write_no_event_and_no_rows(self):
        self.ls.teach("Zed", "z", source="user")
        self.ls.relate("Zed", "Yak", "USES", source="user")
        before = self.snap()
        self.ls.teach("Zed", "z", source="user")
        self.ls.correct("Zed", "z")
        self.ls.set_status("Zed", "active")
        self.ls.relate("Zed", "Yak", "USES", source="user")
        self.assertEqual(self.snap(), before)

    def test_read_only_operations_across_all_systems_write_nothing(self):
        self.ls.teach("Python", "a language", source="user")
        self.nl("Python uses indentation.")
        self.link("py", "Python")
        self.ls.teach("indentation", "whitespace", source="user")
        self.off("indentation")
        before = self.snap()
        total = self.all_event_count()
        self.best("Tell me about Python")
        self.reply("Tell me about Python")
        self.reply("ASK Python")
        self.sel("Tell me about Python", ("python",))
        self.r.reason("What does Python use?")
        self.r.check_consistency()
        self.ls.recall("Python")
        self.ls.search("language")
        self.k.resolve_current_name("python")
        self.core.understand_language("Tell me about the py please")
        self.core.resolve_language_meaning("py", language=EN)
        self.core.learn_from_text("Python uses indentation.", auto_commit=False)
        self.assertEqual(self.snap(), before)
        self.assertEqual(self.all_event_count(), total)                                   # no event of any stream

    def test_atomic_rollback_leaves_knowledge_and_events_unchanged(self):
        self.ls.teach("Snake", "a reptile", source="user")
        self.link("viper", "Snake")
        before = self.snap()

        def boom(*a, **kw):
            raise RuntimeError("boom")
        original = self.m.add_learning_event
        self.m.add_learning_event = boom
        try:
            for fn in (lambda: self.ls.teach("New", "d", source="user"),
                       lambda: self.ls.teach("Snake", "changed", source="user"),
                       lambda: self.ls.correct("Snake", "changed", source="user"),
                       lambda: self.ls.set_status("Snake", "inactive"),
                       lambda: self.ls.relate("P", "Q", "USES", source="user")):
                with self.assertRaises(RuntimeError):
                    fn()
            res = self.nl("Java is a language.")                                           # per-item persist_error
            self.assertTrue(res.errors)
            self.assertEqual(res.learned_items, [])
        finally:
            self.m.add_learning_event = original
        self.assertEqual(self.snap(), before)
        self.assertEqual(self.status("Snake"), "active")
        self.assertIsNone(self.k.get("New"))

    def test_nl_learning_against_inactive_target_failure_leaves_no_partial_state(self):
        self.ls.teach("Python", "a language", source="user")
        self.off("Python")
        before = self.snap()
        original = self.m.add_learning_event
        self.m.add_learning_event = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            self.nl("Python uses indentation.")
        finally:
            self.m.add_learning_event = original
        self.assertEqual(self.snap(), before)
        self.assertEqual(self.status("Python"), "inactive")


class SameProcessAndReload(Base):
    def views(self):
        return (self.status("Python"),
                self.r.reason("What does Python use?").status,
                "a language" in self.reply("Tell me about Python"),
                len(self.k.current_relationships_for("Python")["outgoing"]),
                self.understood("Tell me about the py please")["py"]["status"])

    def test_no_stale_state_across_learn_status_and_reactivate_in_one_process(self):
        self.ls.teach("Python", "a language", source="user")
        self.link("py", "Python")
        self.nl("Python uses indentation.")
        live = ("active", "answered", True, 1, "RESOLVED")
        dead = ("inactive", "unknown", False, 0, "NOT_FOUND")
        self.assertEqual(self.views(), live)
        self.off("Python")
        self.assertEqual(self.views(), dead)
        self.ls.correct("Python", "a language v2", source="user")
        self.assertEqual(self.views(), live)

    def test_close_reopen_preserves_current_and_raw_behavior_without_new_events(self):
        self.ls.teach("Python", "a language", source="user")
        self.link("py", "Python")
        self.nl("Python uses indentation.")
        self.off("Python")
        n = len(self.events())
        before = self.snap()
        self.reopen()
        self.assertEqual(self.snap(), before)
        self.assertEqual(len(self.events()), n)
        self.assertEqual(self.views(), ("inactive", "unknown", False, 0, "NOT_FOUND"))
        self.assertEqual(len(self.k.relationships_for("Python")["outgoing"]), 1)          # raw still raw
        self.assertEqual(self.core.resolve_language_meaning("py", language=EN).status, "RESOLVED")
        self.ls.teach("Python", "a language v3", source="user")
        self.reopen()
        self.assertEqual(self.views(), ("active", "answered", True, 1, "RESOLVED"))

    def test_case_ambiguity_survives_reopen(self):
        self.ls.teach("Python", "upper", source="user")
        self.ls.teach("PYTHON", "lower", source="user")
        self.reopen()
        self.assertEqual(self.k.resolve_current_name("python")["status"], "ambiguous")
        self.assertIsNone(self.best("Tell me about python"))
        self.assertEqual(self.sel("about python", ("python",)).status, "AMBIGUOUS")


if __name__ == "__main__":
    unittest.main()
