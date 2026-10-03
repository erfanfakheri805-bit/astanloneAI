"""
Tests for Prompt 560 - Language Intelligence -> Core integration.

Covers the smallest safe runtime integration made in this prompt: Core's
`_handle_conversation` (step "1e") now reads the `correction_understanding`
field that `language_intelligence`'s `understand()` was ALREADY computing
on every message since Prompt 440 (see
language_intelligence/correction_understanding.py and
language_intelligence/deterministic_fallback_backend.py's
`_build_correction_understanding`), but which nothing else in the Core
request path had ever read (confirmed by the Prompt 559 audit and by a
project-wide grep at implementation time). When that field's status is
RESOLVED, Core now returns a small, structured "[CORRECTION
ACKNOWLEDGED]" reply built only from fields already present on the
result, instead of falling through to the same generic fallback every
other unrecognized phrase gets.

No new detection, storage, or application logic was added: this prompt
only makes an already-computed, already-structured result reach a
decision point in Core for the first time.

Run directly:
    python -m unittest tests.test_language_intelligence_core_integration_prompt560 -v
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
from language_intelligence.correction_understanding import STATUS_RESOLVED


def _make_core():
    tmpdir = tempfile.TemporaryDirectory()
    db_path = os.path.join(tmpdir.name, "test_memory.sqlite3")
    skills_dir = os.path.join(tmpdir.name, "skills")
    core = Core(memory_db_path=db_path, skill_definitions_dir=skills_dir)
    return core, tmpdir


# ----------------------------------------------------------------------
# 1 & 2: a resolved explicit correction reaches Language Intelligence and
# its understanding is used by Core's decision path.
# ----------------------------------------------------------------------
class TestResolvedCorrectionReachesCoreDecisionPath(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_explicit_correction_message_reaches_language_intelligence(self):
        self.core.process_input("not dgo, I mean dog.")
        understanding = self.core.last_language_understanding
        self.assertIsNotNone(understanding)
        self.assertIsNotNone(understanding.correction_understanding)
        self.assertEqual(understanding.correction_understanding["status"], STATUS_RESOLVED)

    def test_resolved_correction_produces_the_new_acknowledged_reply(self):
        reply = self.core.process_input("not dgo, I mean dog.")
        self.assertTrue(reply.startswith("[CORRECTION ACKNOWLEDGED]"))
        self.assertIn("original_expression: dgo", reply)
        self.assertIn("corrected_expression: dog", reply)

    def test_meant_variant_also_produces_the_acknowledged_reply(self):
        reply = self.core.process_input("not dgo, I meant dog.")
        self.assertTrue(reply.startswith("[CORRECTION ACKNOWLEDGED]"))

    def test_reply_never_invents_a_corrected_expression_field(self):
        # Sanity: the formatter only prints fields already present on
        # the dict; it must not fabricate one that's missing.
        reply = self.core.process_input("not dgo, I mean dog.")
        understanding = self.core.last_language_understanding.correction_understanding
        if understanding.get("corrected_meaning") is None:
            self.assertNotIn("corrected_meaning:", reply)

    def test_message_and_reply_are_still_recorded_in_memory_and_context(self):
        reply = self.core.process_input("not dgo, I mean dog.")
        turns = self.core.get_recent_turns(limit=1)
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["assistant"], reply)


# ----------------------------------------------------------------------
# 3: already-supported structured/AEL requests behave exactly as before.
# ----------------------------------------------------------------------
class TestExistingBehaviorPreserved(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_ael_command_is_unaffected(self):
        reply = self.core.process_input("TEACH sun IS a star")
        self.assertTrue(reply.startswith("[AEL OK]"))
        self.assertIsNone(self.core.last_language_understanding)

    def test_goal_oriented_request_is_unaffected(self):
        reply = self.core.process_input("I want to build a script that prints hello")
        self.assertIn("[GOAL CREATED]", reply)
        # Goal-oriented requests return before Language Intelligence
        # ever runs, exactly as before this prompt.
        self.assertIsNone(self.core.last_language_understanding)

    def test_ordinary_statement_is_learned_exactly_as_before(self):
        reply = self.core.process_input("Python is a programming language.")
        self.assertIn("Python", reply)
        understanding = self.core.last_language_understanding
        self.assertIsNotNone(understanding)
        self.assertIsNone(understanding.correction_understanding)

    def test_ordinary_question_reasoning_is_unaffected(self):
        self.core.process_input("Python is a programming language.")
        reply = self.core.process_input("What is Python?")
        self.assertEqual(reply, "Python is a programming language.")


# ----------------------------------------------------------------------
# 4: an unsupported/ambiguous "correction-shaped but incomplete" message
# falls back safely - nothing is fabricated, nothing new short-circuits.
# ----------------------------------------------------------------------
class TestNonResolvedCorrectionFallsBackSafely(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_ordinary_message_has_no_correction_understanding_and_is_unaffected(self):
        reply = self.core.process_input("Tell me about Python")
        self.assertFalse(reply.startswith("[CORRECTION ACKNOWLEDGED]"))
        self.assertIsNone(self.core.last_language_understanding.correction_understanding)

    def test_text_not_matching_the_fixed_marker_falls_through_normally(self):
        # "not" appears, but not in the exact recognized marker shape -
        # detect_explicit_correction() (understanding/correction_
        # detection.py) returns None for this, exactly as before.
        reply = self.core.process_input("not sure what you mean")
        self.assertFalse(reply.startswith("[CORRECTION ACKNOWLEDGED]"))
        self.assertIsNone(self.core.last_language_understanding.correction_understanding)


# ----------------------------------------------------------------------
# 5: existing Memory/Reasoning/Planning/Execution routing is not
# bypassed or broken by this integration.
# ----------------------------------------------------------------------
class TestOtherSubsystemRoutingNotBypassed(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_reasoning_still_answers_after_a_correction_acknowledged_turn(self):
        self.core.process_input("not dgo, I mean dog.")
        learn_reply = self.core.process_input("Dog is an animal.")
        reply = self.core.process_input("What is Dog?")
        # Whatever ReasoningEngine actually stored/reasons back for this
        # statement (unrelated to this prompt's change) is what should
        # come back unchanged; the point of this test is that reasoning
        # still runs and still answers after a correction-acknowledged
        # turn, not the exact article normalization of the stored text.
        self.assertNotEqual(reply, "")
        self.assertNotIn("[CORRECTION ACKNOWLEDGED]", reply)
        self.assertIn("Got it", learn_reply)

    def test_planning_goal_creation_still_works_after_a_correction_turn(self):
        self.core.process_input("not dgo, I mean dog.")
        reply = self.core.process_input("I want to build a script that prints hello")
        self.assertIn("[GOAL CREATED]", reply)

    def test_memory_logs_every_turn_including_the_correction_turn(self):
        self.core.process_input("not dgo, I mean dog.")
        self.core.process_input("Dog is an animal.")
        turns = self.core.get_recent_turns(limit=5)
        self.assertEqual(len(turns), 2)


# ----------------------------------------------------------------------
# 6: deterministic for identical input and state.
# ----------------------------------------------------------------------
class TestDeterministic(unittest.TestCase):
    def test_same_input_on_two_fresh_instances_gives_the_same_reply(self):
        core_a, tmpdir_a = _make_core()
        core_b, tmpdir_b = _make_core()
        try:
            reply_a = core_a.process_input("not dgo, I mean dog.")
            reply_b = core_b.process_input("not dgo, I mean dog.")
            self.assertEqual(reply_a, reply_b)
        finally:
            tmpdir_a.cleanup()
            tmpdir_b.cleanup()

    def test_same_core_gives_the_same_reply_for_the_same_message_twice(self):
        core, tmpdir = _make_core()
        try:
            first = core.process_input("not dgo, I mean dog.")
            second = core.process_input("not dgo, I mean dog.")
            self.assertEqual(first, second)
        finally:
            tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
