"""Prompt 679 - Section 3 final acceptance, regression lock and boundary verification.

Final-acceptance result (docs/section3_final_acceptance_prompt679.md): every acceptance area (A-I) passed against
the real production APIs, so NO production change was made. These tests lock the CROSS-BOUNDARY invariants of the
Section 3 contract; they deliberately do not repeat the per-prompt suites of Prompts 632-678.

Every test builds its own disposable database (tempfile) and constructs
`Core(memory_db_path=<tmp>/c.db, skill_definitions_dir=<tmp>/s)`; nothing here opens the shipped database.
"""
import ast
import hashlib
import os
import sqlite3
import sys
import tempfile
import unittest

from core.core import Core
from language_intelligence.learned_knowledge_context import select_learned_knowledge

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"

KNOWLEDGE_EVENTS = ("teach", "correct", "status", "relate")
KNOWLEDGE_TABLES = ("knowledge", "relationships")
LANG_TABLES = ("language_learning_items", "language_item_relationships")
NOT_KNOWN = "I don't have enough information to answer that yet."
EN = "en"
NL = "understanding_engine"


def sha(path=PROJECT_DB):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def lang_item(key):
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

    # -- helpers ---------------------------------------------------------------------------------------------
    def snap(self, tables=KNOWLEDGE_TABLES + ("learning_events",) + LANG_TABLES):
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

    def total_events(self):
        return len(self.m.query("SELECT * FROM learning_events"))

    def status(self, n):
        return self.k.get(n)["status"]

    def off(self, n):
        self.ls.set_status(n, "inactive")

    def on(self, n):
        self.ls.set_status(n, "active")

    def reply(self, text):
        return self.core.process_input(text)

    def best(self, text):
        found = self.core._find_best_known_concept(text)
        return found["name"] if found else None

    def sel(self, msg, terms):
        return select_learned_knowledge(msg, self.k, candidate_terms=list(terms))

    def link(self, word, concept):
        self.core.learn_language_item(EN, "word", word, meaning=None)
        self.core.relate_language_items(lang_item(word), {"concept": concept}, "means")

    def understood(self, message):
        return {x["expression"]: x for x in self.core.understand_language(message).learned_meanings}

    def consumers(self, name="Python"):
        """One observation per current consumer (A): retrieval, learned context, language meaning, Core
        fallback, ReasoningEngine."""
        rec = self.k.resolve_current_name(name)["record"]
        return {
            "retrieval": rec["description"] if rec else None,
            "context": (self.sel(f"Tell me about {name}", (name.lower(),)).record or {}).get("description"),
            "language": self.understood("Tell me about the py please")["py"]["status"],
            "core": self.reply(f"Tell me about {name}"),
            "reasoning": self.r.reason(f"What is {name}?"),
        }


# ==============================================================================================================
class A_CurrentStateAuthority(Base):
    def test_all_current_consumers_observe_the_same_current_state(self):
        self.ls.teach("Python", "a snake", source="user")
        self.link("py", "Python")
        first = self.consumers()
        self.assertEqual((first["retrieval"], first["context"], first["language"]), ("a snake", "a snake", "RESOLVED"))
        self.assertIn("a snake", first["core"])
        self.assertEqual(first["reasoning"].answer, "a snake")
        self.ls.correct("Python", "a programming language", source="user")
        second = self.consumers()
        self.assertEqual((second["retrieval"], second["context"]), ("a programming language",) * 2)
        self.assertIn("a programming language", second["core"])
        self.assertNotIn("a snake", second["core"])
        self.assertEqual(second["reasoning"].answer, "a programming language")
        self.assertIn("a programming language", str(self.understood("Tell me about the py please")["py"]))

    def test_history_never_overrides_current_state(self):
        self.ls.teach("Python", "a snake", source="user")
        self.ls.correct("Python", "a programming language", source="user")
        self.off("Python")
        self.on("Python")
        events = self.m.recent_learning_events(50)
        self.assertIn("a snake", " ".join(str(e["detail"]) for e in events))       # history remembers old text
        seen = self.consumers()
        self.assertNotIn("snake", seen["core"])
        self.assertEqual(seen["reasoning"].answer, "a programming language")
        self.assertEqual(seen["context"], "a programming language")
        # last event type says nothing about current truth
        self.assertEqual(self.events()[-1][0], "status")
        self.assertEqual(self.status("Python"), "active")

    def test_direct_row_edit_is_seen_at_call_time_by_every_consumer(self):
        """Consumers resolve state at call time: no consumer holds a cached copy."""
        self.ls.teach("Python", "before", source="user")
        self.link("py", "Python")
        self.assertIn("before", self.reply("Tell me about Python"))
        self.m._run("UPDATE knowledge SET description = 'after' WHERE name = 'Python'")
        self.assertEqual(self.r.reason("What is Python?").answer, "after")
        self.assertEqual(self.sel("Tell me about Python", ("python",)).record["description"], "after")
        self.assertIn("after", self.reply("Tell me about Python"))
        self.assertIn("after", str(self.understood("Tell me about the py please")["py"]))
        self.m._run("UPDATE knowledge SET status = 'inactive' WHERE name = 'Python'")
        self.assertEqual(self.r.reason("What is Python?").status, "unknown")
        self.assertEqual(self.understood("Tell me about the py please")["py"]["status"], "NOT_FOUND")


class B_InactiveBoundary(Base):
    def setUp(self):
        super().setUp()
        self.ls.teach("Python", "a language", source="user")
        self.link("py", "Python")

    def test_deactivation_removes_every_current_consumer_but_not_raw_apis(self):
        self.off("Python")
        seen = self.consumers()
        self.assertEqual((seen["retrieval"], seen["context"], seen["language"]), (None, None, "NOT_FOUND"))
        self.assertTrue(seen["core"].startswith(NOT_KNOWN))
        self.assertEqual(seen["reasoning"].status, "unknown")
        self.assertEqual(self.best("Tell me about Python"), None)
        # raw contract: inactive records remain visible
        self.assertEqual(self.k.get("Python")["status"], "inactive")
        self.assertEqual(self.k.resolve_name("Python")["record"]["name"], "Python")
        self.assertIn("Python", [r["name"] for r in self.k.all()])
        self.assertIn("Python", [r["name"] for r in self.k.search("language")])
        self.assertEqual(self.core.resolve_language_meaning("py", language=EN).status, "RESOLVED")   # raw resolve()

    def test_ael_ask_and_recall_stay_raw(self):
        self.off("Python")
        self.assertIn("a language", self.reply("ASK Python"))
        self.assertEqual(self.ls.recall("Python")["status"], "inactive")

    def test_explicit_operations_may_reactivate(self):
        for label, reactivate in (
                ("set_status", lambda: self.on("Python")),
                ("teach", lambda: self.ls.teach("Python", "a language v2", source="user")),
                ("correct", lambda: self.ls.correct("python", "a language v3", source="user")),
                ("ael_teach", lambda: self.reply("TEACH Python IS a language v4"))):
            with self.subTest(label):
                self.off("Python")
                self.assertIsNone(self.consumers()["retrieval"])
                reactivate()
                seen = self.consumers()
                self.assertEqual((self.status("Python"), seen["language"]), ("active", "RESOLVED"))
                self.assertIsNotNone(seen["retrieval"])
                self.assertEqual(seen["reasoning"].status, "answered")

    def test_passive_reads_and_implicit_learning_never_reactivate(self):
        self.off("Python")
        before = self.snap()
        total = self.total_events()
        self.consumers()
        self.reply("ASK Python")
        self.ls.recall("Python")
        self.ls.search("language")
        self.k.resolve_current_name("python")
        self.core.learn_from_text("Python uses indentation.", auto_commit=False)
        self.assertEqual(self.snap(), before)
        self.assertEqual(self.total_events(), total)
        self.nl("Python uses indentation.")                                       # real NL learning
        self.reply("not a snake, I mean a programming language.")                 # implicit correction
        self.assertEqual(self.status("Python"), "inactive")
        self.assertEqual(self.k.get("Python")["description"], "a language")
        self.assertFalse([e for e in self.events() if e[0] in ("correct", "status", "teach")][2:])
        self.assertIsNone(self.consumers()["retrieval"])

    def nl(self, text):
        return self.core.learn_from_text(text)


class C_AmbiguityBoundary(Base):
    def variants(self):
        self.ls.teach("Python", "upper", source="user")
        self.ls.teach("PYTHON", "lower", source="user")

    def assert_ambiguous_everywhere(self):
        self.assertEqual(self.k.resolve_current_name("python")["status"], "ambiguous")
        self.assertIsNone(self.best("Tell me about python"))
        self.assertEqual(self.sel("about python", ("python",)).status, "AMBIGUOUS")
        self.assertEqual(self.r.reason("What is python?").status, "unknown")
        self.assertNotIn("upper", self.reply("Tell me about python"))
        self.assertNotIn("lower", self.reply("Tell me about python"))

    def test_exact_case_unique_record(self):
        self.ls.teach("Python", "a language", source="user")
        self.assertEqual(self.k.resolve_current_name("Python")["status"], "exact")
        self.assertEqual(self.r.reason("What is Python?").answer, "a language")

    def test_unique_case_insensitive_match_resolves(self):
        self.ls.teach("Python", "a language", source="user")
        self.assertEqual(self.k.resolve_current_name("pYTHON")["status"], "case_insensitive")
        self.assertEqual(self.best("Tell me about python"), "Python")
        self.assertEqual(self.r.reason("What is python?").answer, "a language")

    def test_exact_case_wins_over_other_variants(self):
        self.variants()
        self.assertEqual(self.k.resolve_current_name("Python")["record"]["description"], "upper")
        self.assertEqual(self.k.resolve_current_name("PYTHON")["record"]["description"], "lower")

    def test_multiple_active_variants_are_never_selected(self):
        self.variants()
        self.assert_ambiguous_everywhere()
        before = self.snap()
        for fn in (lambda: self.ls.correct("python", "x", source="user"),
                   lambda: self.ls.set_status("python", "inactive")):
            with self.assertRaises(ValueError):
                fn()
        self.assertEqual(self.snap(), before)                                    # no partial mutation, no event

    def test_active_plus_inactive_variants_never_lets_the_inactive_one_participate(self):
        self.variants()
        self.off("PYTHON")
        self.assertEqual(self.k.resolve_current_name("python")["record"]["name"], "Python")
        self.assertEqual(self.r.reason("What is python?").answer, "upper")
        self.assertEqual(self.k.resolve_name("python")["status"], "ambiguous")   # raw stays raw
        self.on("PYTHON")
        self.assert_ambiguous_everywhere()

    def test_ambiguity_survives_reload(self):
        self.variants()
        self.reopen()
        self.assert_ambiguous_everywhere()
        self.off("PYTHON")
        self.reopen()
        self.assertEqual(self.k.resolve_current_name("python")["record"]["name"], "Python")
        self.on("PYTHON")
        self.reopen()
        self.assert_ambiguous_everywhere()

    def test_language_link_never_redirects_to_a_case_variant(self):
        self.ls.teach("Snake", "reptile", source="user")
        self.core.learn_language_item(EN, "word", "viper", meaning=None)
        with self.assertRaises(ValueError):
            self.core.relate_language_items(lang_item("viper"), {"concept": "snake"}, "means")
        self.assertEqual(self.m.query("SELECT * FROM language_item_relationships"), [])


class D_RelationshipBoundary(Base):
    def setUp(self):
        super().setUp()
        self.ls.teach("S", "s", source="user")
        self.ls.teach("T", "t", source="user")
        self.ls.relate("S", "T", "USES", source="user")

    def uses(self):
        return self.r.reason("What does S use?")

    def test_active_to_active_then_inactive_endpoint_then_reactivation(self):
        self.assertEqual(self.uses().answer, "S uses T.")
        self.off("T")
        self.assertEqual(self.uses().status, "unknown")
        self.assertEqual(self.k.current_relationships_for("S"), {"outgoing": [], "incoming": []})
        self.assertEqual(self.k.current_relationships_for("T"), {"outgoing": [], "incoming": []})
        self.on("T")
        self.assertEqual(self.uses().answer, "S uses T.")
        self.assertEqual(len(self.k.current_relationships_for("S")["outgoing"]), 1)

    def test_raw_relationship_apis_keep_documented_behavior(self):
        self.off("T")
        rows = self.k.relationships_for("S")["outgoing"]
        self.assertEqual([(r["from_name"], r["to_name"], r["relation_type"]) for r in rows], [("S", "T", "USES")])
        self.assertEqual(len(self.k.relationships_for("T")["incoming"]), 1)
        ask = self.reply("ASK S")                                                            # AEL ASK stays raw
        self.assertIn("T", ask)
        self.assertIn("USES", ask.upper())

    def test_no_stale_relationship_state_across_reload(self):
        self.off("T")
        self.reopen()
        self.assertEqual(self.uses().status, "unknown")
        self.assertEqual(len(self.k.relationships_for("S")["outgoing"]), 1)
        self.on("T")
        self.reopen()
        self.assertEqual(self.uses().answer, "S uses T.")

    def test_inactive_source_endpoint_is_excluded_too(self):
        self.off("S")
        self.assertEqual(self.uses().status, "unknown")
        self.on("S")
        self.assertEqual(self.uses().status, "answered")

    def test_transitive_reasoning_ignores_inactive_middle(self):
        self.ls.relate("S", "T", "DEPENDS_ON", source="user")
        self.ls.relate("T", "U", "DEPENDS_ON", source="user")
        self.ls.teach("U", "u", source="user")
        self.assertEqual(self.r.reason("Does S depend on U?").status, "answered")
        self.off("T")
        self.assertEqual(self.r.reason("Does S depend on U?").status, "unknown")
        self.on("T")
        self.assertEqual(self.r.reason("Does S depend on U?").status, "answered")


class E_LanguageIntelligenceBoundary(Base):
    def test_meaning_resolution_excludes_inactive_and_keeps_exact_identity(self):
        self.ls.teach("Snake", "inactive reptile", source="user")
        self.ls.teach("snake", "active reptile", source="user")
        self.off("Snake")
        self.link("viper", "Snake")
        self.link("adder", "snake")
        self.assertEqual(self.understood("Tell me about the viper please")["viper"]["status"], "NOT_FOUND")
        self.assertEqual(self.understood("Tell me about the adder please")["adder"]["status"], "RESOLVED")
        self.assertIn("active reptile", str(self.understood("Tell me about the adder please")["adder"]))
        self.assertNotIn("inactive reptile", str(self.core.understand_language("the viper and the adder").to_dict()))

    def test_language_records_are_not_knowledge_status_records(self):
        self.ls.teach("Snake", "a reptile", source="user")
        self.link("viper", "Snake")
        knowledge_before = self.snap(KNOWLEDGE_TABLES + ("learning_events",))
        lang_before = self.snap(LANG_TABLES)
        self.off("Snake")
        self.assertEqual(self.snap(LANG_TABLES), lang_before)                     # status change never rewrites language rows
        self.assertNotIn("status", {c for r in lang_before["language_learning_items"] for c in r.keys()
                                    if c == "status" and r[c] in ("active", "inactive")})
        self.on("Snake")
        self.link("adder", "Snake")                                              # writing language links
        after = self.snap(KNOWLEDGE_TABLES + ("learning_events",))
        self.assertEqual([r["name"] for r in after["knowledge"]], [r["name"] for r in knowledge_before["knowledge"]])
        self.assertEqual(after["relationships"], knowledge_before["relationships"])       # no knowledge writes
        self.assertEqual(len(after["learning_events"]), len(knowledge_before["learning_events"]) + 2)  # two status events only

    def test_language_state_cannot_resurrect_inactive_knowledge(self):
        self.ls.teach("Snake", "a reptile", source="user")
        self.link("viper", "Snake")
        self.off("Snake")
        self.core.learn_language_item(EN, "word", "viper", meaning=None)                      # more language writes
        self.core.understand_language("Tell me about the viper please")
        self.core.resolve_language_meaning("viper", language=EN)
        self.assertEqual(self.status("Snake"), "inactive")
        self.assertEqual(self.understood("Tell me about the viper please")["viper"]["status"], "NOT_FOUND")
        # an item's OWN language meaning is language state: it never revives the concept's description
        self.core.learn_language_item(EN, "word", "viper", meaning="a snake kind")
        got = self.understood("Tell me about the viper please")["viper"]
        self.assertNotIn("a reptile", str(got))
        self.assertEqual(self.status("Snake"), "inactive")
        self.assertIsNone(self.consumers("Snake")["retrieval"])

    def test_nl_teach_correct_and_conversational_correction_boundaries(self):
        self.core.learn_from_text("Python is a programming language.")
        self.assertEqual(self.status("Python"), "stub")
        self.ls.teach("Python", "a snake", source="user")
        self.reply("not a snake, I mean a programming language.")
        self.assertEqual(self.k.get("Python")["source"], "user_correction")
        self.off("Python")
        n = len(self.events())
        self.reply("not a programming language, I mean a snake.")                  # no reactivation, no event
        self.core.learn_from_text("Python uses indentation.")
        self.assertEqual(self.status("Python"), "inactive")
        self.assertEqual([e[0] for e in self.events()[n:]], ["relate"])
        self.ls.correct("Python", "explicit", source="user")                       # explicit path reactivates
        self.assertEqual(self.status("Python"), "active")


class F_EventProvenanceBoundary(Base):
    def test_exactly_one_event_per_real_mutation_with_persisted_identity_source_and_provenance(self):
        self.ls.teach("Zed", "z", source="user", source_text="Zed is z.", learning_method="ael")
        self.ls.correct("zed", "z2")                                                # None keeps 'user'
        self.ls.set_status("zed", "inactive")
        self.ls.relate("Zed", "Yak", "USES", source="user")
        self.core.learn_from_text("Moose is an animal.")
        self.ls.teach("Python", "a snake", source="user")
        self.reply("not a snake, I mean a programming language.")
        self.assertEqual(self.events(), [
            ("teach", "Zed", "user"), ("correct", "Zed", "user"), ("status", "Zed", "user"),
            ("relate", "Zed", "user"), ("relate", "Moose", NL), ("teach", "Python", "user"),
            ("correct", "Python", "user_correction")])
        rec = self.k.get("Zed")
        self.assertEqual((rec["source"], rec["source_text"], rec["learning_method"], rec["version"]),
                         ("user", "Zed is z.", "ael", 3))                            # None keeps stored values
        moose = self.k.get("Moose")
        self.assertEqual((moose["source"], moose["learning_method"], moose["source_text"]),
                         (NL, "natural_language_understanding", "Moose is an animal."))

    def test_true_noops_write_zero_events_and_zero_rows(self):
        self.ls.teach("Zed", "z", source="user")
        self.ls.relate("Zed", "Yak", "USES", source="user")
        self.core.learn_from_text("Moose is an animal.")
        before, total = self.snap(), self.total_events()
        self.ls.teach("Zed", "z", source="user")
        self.ls.correct("Zed", "z")
        self.ls.set_status("Zed", "active")
        self.ls.relate("Zed", "Yak", "USES", source="user")
        self.core.learn_from_text("Moose is an animal.")
        self.assertEqual(self.snap(), before)
        self.assertEqual(self.total_events(), total)

    def test_failed_and_ambiguous_mutations_write_nothing(self):
        self.ls.teach("Python", "upper", source="user")
        self.ls.teach("PYTHON", "lower", source="user")
        before, total = self.snap(), self.total_events()
        for fn in (lambda: self.ls.correct("python", "x"), lambda: self.ls.set_status("python", "inactive"),
                   lambda: self.ls.teach("", "x"), lambda: self.ls.correct("Python", ""),
                   lambda: self.ls.set_status("Python", "bogus")):
            with self.assertRaises((ValueError, TypeError)):
                fn()
        self.assertIsNone(self.ls.correct("Nobody", "x"))                          # unknown: nothing created
        self.assertIsNone(self.ls.set_status("Nobody", "inactive"))
        self.assertEqual(self.snap(), before)
        self.assertEqual(self.total_events(), total)

    def test_event_write_failure_rolls_back_every_mutation_kind(self):
        self.ls.teach("Snake", "a reptile", source="user")
        self.ls.teach("Python", "a snake", source="user")
        self.link("viper", "Snake")
        before, total = self.snap(), self.total_events()

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
            res = self.core.learn_from_text("Java is a language.")
            self.assertTrue(res.errors)
            self.assertEqual(res.learned_items, [])
            with self.assertRaises(RuntimeError):                                   # correction path: raises ...
                self.reply("not a snake, I mean a programming language.")           # ... but commits nothing
        finally:
            self.m.add_learning_event = original
        self.assertEqual(self.snap(), before)
        self.assertEqual(self.total_events(), total)
        self.assertEqual(self.status("Snake"), "active")
        self.assertEqual(self.k.get("Python")["description"], "a snake")
        self.assertIsNone(self.k.get("New"))
        self.assertIsNone(self.k.get("Java"))

    def test_events_are_persisted_history_and_reads_add_none(self):
        self.ls.teach("Python", "a language", source="user")
        self.link("py", "Python")
        self.off("Python")
        before, total = self.snap(), self.total_events()
        self.consumers()
        self.reply("ASK Python")
        self.assertEqual(self.snap(), before)
        self.assertEqual(self.total_events(), total)


class G_ReloadAndIsolation(Base):
    def views(self):
        return (self.status("Python"), self.r.reason("What does Python use?").status,
                "a language" in self.reply("Tell me about Python"),
                len(self.k.current_relationships_for("Python")["outgoing"]),
                self.understood("Tell me about the py please")["py"]["status"])

    def test_same_process_and_reload_agree_through_a_full_lifecycle(self):
        self.ls.teach("Python", "a language", source="user")
        self.link("py", "Python")
        self.core.learn_from_text("Python uses indentation.")
        live, dead = ("active", "answered", True, 1, "RESOLVED"), ("inactive", "unknown", False, 0, "NOT_FOUND")
        for step, expected in (("start", live), ("off", dead), ("on", live)):
            with self.subTest(step):
                if step == "off":
                    self.off("Python")
                elif step == "on":
                    self.on("Python")
                self.assertEqual(self.views(), expected)
                before, total = self.snap(), self.total_events()
                self.reopen()
                self.assertEqual(self.views(), expected)                            # reload agrees with same-process
                self.assertEqual(self.snap(), before)
                self.assertEqual(self.total_events(), total)                        # reads / reopen add no events

    def test_shipped_database_is_pristine_and_untouched_by_disposable_cores(self):
        self.assertEqual(sha(), PRISTINE_SHA256)
        self.ls.teach("Zed", "z", source="user")
        self.core.learn_from_text("Moose is an animal.")
        self.off("Zed")
        self.reopen()
        self.assertEqual(sha(), PRISTINE_SHA256)
        self.assertNotEqual(os.path.abspath(self.db), os.path.abspath(PROJECT_DB))

    def test_core_with_explicit_path_never_opens_the_shipped_database(self):
        opened = []

        def hook(event, args):
            if event == "sqlite3.connect":
                opened.append(os.path.abspath(str(args[0])))
        sys.addaudithook(hook)
        try:
            self._open_fresh_core()
        finally:
            hook_list = opened
        self.assertTrue(hook_list)
        self.assertNotIn(os.path.abspath(PROJECT_DB), hook_list)

    def _open_fresh_core(self):
        tmp = tempfile.mkdtemp()
        core = Core(memory_db_path=os.path.join(tmp, "x.db"), skill_definitions_dir=os.path.join(tmp, "s"))
        core.memory._conn.close()

    def test_no_test_module_builds_a_bare_core_or_memory_system(self):
        offenders = []
        tests_dir = os.path.dirname(os.path.abspath(__file__))
        for fname in sorted(os.listdir(tests_dir)):
            if not fname.endswith(".py"):
                continue
            with open(os.path.join(tests_dir, fname), encoding="utf-8") as fh:
                source = fh.read()
            if "set_platform" in source or "STANDALONE_AI_DATA_DIR" in source:
                continue
            for node in ast.walk(ast.parse(source)):
                if (isinstance(node, ast.Call) and not node.args and not node.keywords
                        and getattr(node.func, "id", getattr(node.func, "attr", None)) in ("Core", "MemorySystem")):
                    offenders.append(f"{fname}:{node.lineno}")
        self.assertEqual(offenders, [])

    def test_this_module_only_uses_disposable_databases(self):
        with open(os.path.abspath(__file__), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("Core", "MemorySystem"):
                self.assertTrue(node.keywords or node.args, f"bare construction at line {node.lineno}")


class H_PublicBoundary(Base):
    """The public raw / current / mutating split future (Section 4) systems build on."""

    CURRENT = ("resolve_current_name", "find_current_by_name_case_insensitive", "current_relationships_for")
    RAW = ("get", "resolve_name", "find_by_name_case_insensitive", "relationships_for", "all", "search")
    MUTATING = ("teach", "correct", "set_status", "relate")

    def test_api_surface_exists(self):
        for name in self.CURRENT + self.RAW:
            self.assertTrue(callable(getattr(self.k, name)), name)
        for name in self.MUTATING + ("recall", "search"):
            self.assertTrue(callable(getattr(self.ls, name)), name)

    def test_raw_and_current_apis_split_on_inactive_records(self):
        self.ls.teach("Python", "a language", source="user")
        self.ls.teach("Rust", "another", source="user")
        self.ls.relate("Python", "Rust", "USES", source="user")
        self.off("Rust")
        self.assertEqual(self.k.get("Rust")["status"], "inactive")                           # raw
        self.assertEqual(self.k.resolve_name("rust")["status"], "case_insensitive")          # raw
        self.assertEqual(self.k.resolve_current_name("rust")["status"], "inactive")          # current
        self.assertIsNone(self.k.find_current_by_name_case_insensitive("rust"))
        self.assertEqual(len(self.k.relationships_for("Python")["outgoing"]), 1)              # raw
        self.assertEqual(self.k.current_relationships_for("Python")["outgoing"], [])          # current

    def test_read_apis_never_mutate(self):
        self.ls.teach("Python", "a language", source="user")
        self.off("Python")
        before, total = self.snap(), self.total_events()
        for name in self.RAW:
            fn = getattr(self.k, name)
            fn("Python") if name not in ("all",) else fn()
        self.k.resolve_current_name("Python")
        self.k.current_relationships_for("Python")
        self.assertEqual(self.snap(), before)
        self.assertEqual(self.total_events(), total)

    def test_only_explicit_mutations_reactivate_and_each_emits_exactly_one_event(self):
        self.ls.teach("Python", "a language", source="user")
        for kind, fn in (("status", lambda: self.on("Python")),
                         ("teach", lambda: self.ls.teach("Python", "v2", source="user")),
                         ("correct", lambda: self.ls.correct("Python", "v3", source="user"))):
            with self.subTest(kind):
                self.off("Python")
                n = len(self.events())
                fn()
                self.assertEqual(self.status("Python"), "active")
                self.assertEqual([e[0] for e in self.events()[n:]], [kind])


if __name__ == "__main__":
    unittest.main()
