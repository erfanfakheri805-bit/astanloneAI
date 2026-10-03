"""
Tests for Prompt 628 - Section 2: Language Intelligence and Request
Understanding - repeated and mixed calls through the REAL public entry
point (`Core.process_input` / `Core.get_last_language_understanding` /
`Core.get_last_response_plan`) must always produce independent,
internally consistent request-understanding state.

Prompts 609-627 already verified individual field propagation and one
full hand-assembled lifecycle trace (Prompt 627, built directly from a
`LanguageUnderstandingResult` + a shared `ResponsePlanner`, not through
`Core`). What none of those files does is drive several REAL,
`Core.process_input`-taught requests back to back - including an
A -> B -> A -> C sequence, an ambiguous classification, and an
unresolved call sitting between two successful ones - and check that
`Core`'s own "last understanding" / "last response plan" getters never
serve stale or mixed state. That is the gap this file closes.

Finding: the architecture already guarantees this. `Core` keeps exactly
one `last_language_understanding` attribute, overwritten wholesale by
each conversational turn (`_handle_conversation`); `get_last_response_
plan()` reads `response_plan` straight off that same object with no
caching or merging logic. No production changes were needed; this file
adds focused regression coverage only.

Run directly:
    python -m unittest tests.test_request_understanding_repeated_lifecycle_prompt628 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from language_intelligence.response_planning import (
    STATUS_RESOLVED, STATUS_AMBIGUOUS, STATUS_UNRESOLVED,
    ACTION_GREET, ACTION_PROVIDE_INFORMATION,
    ResponsePlanner,
)
from language_intelligence.learned_pattern_teaching import STATUS_CREATED
from language_intelligence.learned_pattern_meaning import STATUS_BOUND, STATUS_ALREADY_BOUND


def _teach(core, pattern, meaning, language="en"):
    assert core.teach_sentence_pattern(language, pattern).status == STATUS_CREATED
    assert core.bind_pattern_meaning(language, pattern, meaning).status in (
        STATUS_BOUND, STATUS_ALREADY_BOUND)


class _CoreCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # No skill definitions: a keyword `greet` skill would otherwise
        # answer greetings before the language pipeline runs.
        self.core = Core(
            memory_db_path=os.path.join(self._tmp.name, "core.db"),
            skill_definitions_dir=os.path.join(self._tmp.name, "skills"))


# ======================================================================
class TestMultiRequestSequenceIsolation(unittest.TestCase):
    """Four distinct requests, each changing a different combination of
    original_input/normalized_input/intent/status, run back to back
    through the real entry point - each `get_last_*` read must belong
    only to the request that just ran."""

    def test_four_requests_each_scoped_to_its_own_call(self):
        core = Core(
            memory_db_path=tempfile.mkdtemp() + "/core.db",
            skill_definitions_dir=tempfile.mkdtemp() + "/skills")
        _teach(core, "good morning", "greeting")
        _teach(core, "what is {{topic}}", "ask_question")
        core.teach_sentence_pattern("en", "thanks {{who}}")
        core.bind_pattern_meaning("en", "thanks {{who}}", "gratitude")
        core.bind_pattern_meaning("en", "thanks {{who}}", "farewell")

        # Request 1: RESOLVED greeting.
        core.process_input("good morning")
        u1 = core.get_last_language_understanding()
        p1 = core.get_last_response_plan()
        held_original_1 = u1.original_input
        self.assertEqual(p1["status"], STATUS_RESOLVED)
        self.assertEqual(p1["response_action"], ACTION_GREET)
        self.assertIs(p1["original_message"], held_original_1)

        # Request 2: RESOLVED question, different intent/variables.
        core.process_input("what is python")
        u2 = core.get_last_language_understanding()
        p2 = core.get_last_response_plan()
        self.assertEqual(p2["status"], STATUS_RESOLVED)
        self.assertEqual(p2["response_action"], ACTION_PROVIDE_INFORMATION)
        self.assertEqual(p2["variables"], {"topic": "python"})
        self.assertIsNot(u2, u1)
        self.assertNotEqual(u2.original_input, u1.original_input)
        # Request 1's own already-returned objects are unaffected.
        self.assertIs(u1.original_input, held_original_1)
        self.assertEqual(p1["response_action"], ACTION_GREET)

        # Request 3: AMBIGUOUS classification.
        core.process_input("thanks bob")
        u3 = core.get_last_language_understanding()
        p3 = core.get_last_response_plan()
        self.assertEqual(p3["status"], STATUS_AMBIGUOUS)
        self.assertEqual(len(p3["meaning_candidates"]), 2)
        self.assertTrue(p3["needs_clarification"])
        self.assertIsNot(u3, u2)
        self.assertEqual(p2["response_action"], ACTION_PROVIDE_INFORMATION)  # still intact

        # Request 4: UNRESOLVED, nothing learned for it.
        core.process_input("qwerty zzznoxyzzz unmapped concept")
        u4 = core.get_last_language_understanding()
        p4 = core.get_last_response_plan()
        self.assertEqual(p4["status"], STATUS_UNRESOLVED)
        self.assertIsNone(p4["response_action"])
        self.assertIsNot(u4, u3)
        # Nothing from request 3's ambiguity carries into request 4.
        self.assertEqual(p4["meaning_candidates"], [])
        self.assertNotEqual(p4["status"], p3["status"])


# ======================================================================
class TestAThenBThenAThenCSequence(unittest.TestCase):
    """The specific mixed sequence this prompt calls out: the second A
    must be a FRESH lifecycle result, not stale state carried from the
    first A (checked with held references and `assertIs`, never a raw
    equality check that a stale-but-equal object could pass)."""

    def test_a_b_a_c_is_never_stale(self):
        core = Core(
            memory_db_path=tempfile.mkdtemp() + "/core.db",
            skill_definitions_dir=tempfile.mkdtemp() + "/skills")
        _teach(core, "good morning", "greeting")
        _teach(core, "what is {{topic}}", "ask_question")

        core.process_input("good morning")                 # A
        u_a1 = core.get_last_language_understanding()
        p_a1 = core.get_last_response_plan()
        held_a1_original = u_a1.original_input

        core.process_input("what is python")               # B
        u_b = core.get_last_language_understanding()
        p_b = core.get_last_response_plan()
        self.assertIsNot(u_b, u_a1)

        core.process_input("good morning")                 # A again
        u_a2 = core.get_last_language_understanding()
        p_a2 = core.get_last_response_plan()

        # The second A is a genuinely fresh object, not the first A's.
        self.assertIsNot(u_a2, u_a1)
        self.assertIsNot(p_a2, p_a1)
        self.assertIsNot(u_a2.original_input, held_a1_original)
        # ... but it is correctly re-correlated to the SAME request text.
        self.assertEqual(u_a2.original_input, held_a1_original)
        self.assertEqual(p_a2["status"], STATUS_RESOLVED)
        self.assertEqual(p_a2["response_action"], ACTION_GREET)
        self.assertIs(p_a2["original_message"], u_a2.original_input)

        # It carries nothing left over from B.
        self.assertNotEqual(p_a2["response_action"], p_b["response_action"])
        self.assertEqual(p_a2["variables"], {})

        core.process_input("thanks bob is wrong pattern, unresolved")  # C: unresolved
        _teach(core, "totally different {{thing}}", "custom_action")
        core.process_input("totally different results")    # C: a fresh resolved intent
        p_c = core.get_last_response_plan()
        u_c = core.get_last_language_understanding()
        self.assertNotEqual(u_c.original_input, u_a2.original_input)
        self.assertNotEqual(p_c["response_action"], p_a2["response_action"])
        # A's own state (from the second A) remains exactly as it was.
        self.assertEqual(p_a2["response_action"], ACTION_GREET)
        self.assertIs(p_a2["original_message"], u_a2.original_input)


# ======================================================================
class TestFailureUnresolvedBoundaryAndRecovery(unittest.TestCase):
    """An unresolved call sandwiched between two successful ones must
    not preserve the first success's state, and the recovery call after
    it must publish its own fresh state - not the unresolved call's,
    nor the earlier success's."""

    def test_success_unresolved_recovery(self):
        core = Core(
            memory_db_path=tempfile.mkdtemp() + "/core.db",
            skill_definitions_dir=tempfile.mkdtemp() + "/skills")
        _teach(core, "good morning", "greeting")
        _teach(core, "what is {{topic}}", "ask_question")

        core.process_input("good morning")
        p_success = core.get_last_response_plan()
        u_success = core.get_last_language_understanding()
        self.assertEqual(p_success["status"], STATUS_RESOLVED)

        core.process_input("qwerty zzznoxyzzz unmapped concept")
        p_unresolved = core.get_last_response_plan()
        u_unresolved = core.get_last_language_understanding()
        self.assertEqual(p_unresolved["status"], STATUS_UNRESOLVED)
        self.assertIsNone(p_unresolved["response_action"])
        self.assertNotEqual(u_unresolved.original_input, u_success.original_input)
        # The earlier success is untouched by the unresolved call.
        self.assertEqual(p_success["status"], STATUS_RESOLVED)
        self.assertEqual(p_success["response_action"], ACTION_GREET)

        core.process_input("what is python")
        p_recovery = core.get_last_response_plan()
        u_recovery = core.get_last_language_understanding()
        self.assertEqual(p_recovery["status"], STATUS_RESOLVED)
        self.assertEqual(p_recovery["response_action"], ACTION_PROVIDE_INFORMATION)
        self.assertIs(p_recovery["original_message"], u_recovery.original_input)
        # Recovery carries nothing from the unresolved call or the
        # earlier success.
        self.assertNotEqual(u_recovery.original_input, u_unresolved.original_input)
        self.assertNotEqual(u_recovery.original_input, u_success.original_input)
        self.assertNotEqual(p_recovery["response_action"], p_success["response_action"])
        # And the unresolved call's own already-returned state is
        # unaffected by the recovery that came after it.
        self.assertEqual(p_unresolved["status"], STATUS_UNRESOLVED)


# ======================================================================
class TestRepeatedReadsAreStableAndDoNotMutate(unittest.TestCase):
    """Reading `get_last_language_understanding()` / `get_last_response_
    plan()` repeatedly, without any new call in between, must return the
    SAME object every time (no rebuild) and never mutate it."""

    def test_repeated_reads_return_the_same_objects(self):
        core = Core(
            memory_db_path=tempfile.mkdtemp() + "/core.db",
            skill_definitions_dir=tempfile.mkdtemp() + "/skills")
        _teach(core, "good morning", "greeting")
        core.process_input("good morning")

        u_first = core.get_last_language_understanding()
        p_first = core.get_last_response_plan()
        for _ in range(3):
            u_again = core.get_last_language_understanding()
            p_again = core.get_last_response_plan()
            self.assertIs(u_again, u_first)
            self.assertIs(p_again, p_first)
            self.assertEqual(p_again["response_action"], ACTION_GREET)
            self.assertIs(p_again["original_message"], u_again.original_input)


# ======================================================================
class TestLegacySafeConstructionUnaffectedByRepeatedCalls(unittest.TestCase):
    """A hand-built, pre-normalized-input-era understanding (no
    `normalized_input` key at all) fed through a `ResponsePlanner`
    repeatedly, interleaved with real `Core` calls elsewhere, still
    resolves safely to `None` every time and is never contaminated by
    the unrelated `Core` sequence running independently."""

    def test_legacy_dict_repeated_across_an_unrelated_core_sequence(self):
        core = Core(
            memory_db_path=tempfile.mkdtemp() + "/core.db",
            skill_definitions_dir=tempfile.mkdtemp() + "/skills")
        _teach(core, "good morning", "greeting")

        planner = ResponsePlanner()
        legacy_understanding = {
            "original_input": "legacy message", "detected_language": "english",
            "intent": "legacy_intent", "confidence": 1.0, "ambiguity": None,
            "needs_clarification": False, "referenced_items": [], "active_topic": None,
            "conversation_context": None,
            # no "normalized_input" key at all - legacy shape.
        }

        core.process_input("good morning")
        legacy_plan_1 = planner.plan(legacy_understanding)
        core.process_input("good morning")
        legacy_plan_2 = planner.plan(legacy_understanding)

        self.assertIsNone(legacy_plan_1.normalized_input)
        self.assertIsNone(legacy_plan_2.normalized_input)
        self.assertEqual(legacy_plan_1.original_message, "legacy message")
        self.assertEqual(legacy_plan_2.original_message, "legacy message")
        # The unrelated real Core sequence stayed correctly RESOLVED
        # throughout, untouched by the legacy planner calls.
        self.assertEqual(core.get_last_response_plan()["response_action"], ACTION_GREET)


if __name__ == "__main__":
    unittest.main()
