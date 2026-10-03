"""
Tests for Prompt 562 - Core -> Correction-Learning Storage Integration.

Prompt 561 audited the correction-learning storage/retrieval layer and
found it fully implemented, fully tested in isolation, and completely
unreachable from Core: the one real `CorrectionUnderstandingResult`
(language_intelligence/correction_understanding.py, Prompt 439) is
flattened to a plain dict, one step upstream of Core, by
`DeterministicFallbackBackend._build_correction_understanding()`,
before the existing storage handoff chain ever sees it.

Prompt 562 adds exactly one call site - `Core._store_resolved_
correction_learning()`, called from `_handle_conversation()`'s
existing step 1e, only when `correction_understanding["status"] ==
CORRECTION_STATUS_RESOLVED` (the same, unchanged condition step 1e
already used for the Prompt 560 acknowledgement reply). It:

    1. reconstructs a real `CorrectionUnderstandingResult` from the
       dict Core already has (`to_dict()`'s keys already match that
       class's own constructor keyword arguments exactly - a direct,
       lossless reconstruction, not new logic)
    2. passes it through the EXISTING, already-tested adapter chain
       (map_correction_understanding_to_result ->
       map_correction_understanding_result_to_feedback_record ->
       convert_correction_feedback_to_learning_input)
    3. calls `handoff_correction_learning_input_with_result()`
       (Prompt 458) EXACTLY ONCE, using Core's own real
       `self.language_learning` store - never followed by
       `store_accepted_correction_learning_input()` for the same data
       (the Prompt 561 audit's duplicate-write finding)

No new storage system, database, or memory system is introduced. No
existing behavior (acknowledgement reply text, AEL, goal-oriented,
Memory/Reasoning/Planning routing) changes.

Run directly:
    python -m unittest tests.test_section2_correction_learning_core_integration_prompt562 -v
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
from language_intelligence.correction_understanding import (
    STATUS_RESOLVED, STATUS_UNRESOLVED, STATUS_AMBIGUOUS, STATUS_NOT_CORRECTION,
)
from language_intelligence.correction_learning_handoff_result import (
    STATUS_ACCEPTED,
)


def _make_core():
    tmpdir = tempfile.TemporaryDirectory()
    db_path = os.path.join(tmpdir.name, "test_memory.sqlite3")
    skills_dir = os.path.join(tmpdir.name, "skills")
    core = Core(memory_db_path=db_path, skill_definitions_dir=skills_dir)
    return core, tmpdir


def _count_learn_item_calls(core):
    """Wraps core.language_learning.learn_item with a counter, still
    delegating to the real, unmodified implementation for every call -
    same "test double only at the boundary" convention already used by
    tests/test_correction_learning_input_handoff.py's
    CountingLanguageLearningStore. Returns a single-element list acting
    as a mutable counter (call_count[0])."""
    call_count = [0]
    original_learn_item = core.language_learning.learn_item

    def counting_learn_item(*args, **kwargs):
        call_count[0] += 1
        return original_learn_item(*args, **kwargs)

    core.language_learning.learn_item = counting_learn_item
    return call_count


# ----------------------------------------------------------------------
# 1 & 3: a valid correction reaches the existing storage handoff, and it
# happens exactly once.
# ----------------------------------------------------------------------
class TestValidCorrectionReachesStorageHandoffExactlyOnce(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_resolved_correction_produces_an_accepted_handoff_result(self):
        self.core.process_input("not dgo, I mean dog.")
        result = self.core.last_correction_learning_handoff_result
        self.assertIsNotNone(result)
        self.assertEqual(result.status, STATUS_ACCEPTED)
        self.assertTrue(result.accepted)

    def test_item_is_actually_stored_in_the_existing_learning_store(self):
        self.core.process_input("not dgo, I mean dog.")
        stored = self.core.language_learning.get_item("en", "correction", "dgo")
        self.assertIsNotNone(stored)
        self.assertEqual(stored["key"], "dgo")
        self.assertEqual(stored["meaning"], "dog")

    def test_exactly_one_learn_item_call_for_one_eligible_correction(self):
        call_count = _count_learn_item_calls(self.core)
        self.core.process_input("not dgo, I mean dog.")
        self.assertEqual(call_count[0], 1)

    def test_repeated_processing_of_the_same_correction_follows_existing_upsert_contract(self):
        # learn_item()'s own existing contract (Prompt 416): the same
        # (language, item_type, key) always resolves to the same row -
        # re-teaching it updates that row rather than duplicating it.
        # Two separate process_input() calls therefore call learn_item()
        # once each (two calls total), but the store still holds exactly
        # one item for "dgo" - the SAME existing behavior any other
        # learn_item() caller already gets, not new deduplication logic
        # added by this prompt.
        call_count = _count_learn_item_calls(self.core)
        self.core.process_input("not dgo, I mean dog.")
        self.core.process_input("not dgo, I mean dog.")
        self.assertEqual(call_count[0], 2)
        stored = self.core.language_learning.get_item("en", "correction", "dgo")
        self.assertIsNotNone(stored)
        self.assertEqual(stored["version"], 2)


# ----------------------------------------------------------------------
# 2: the reconstructed CorrectionUnderstandingResult preserves the
# correct existing fields.
# ----------------------------------------------------------------------
class TestReconstructedObjectPreservesFields(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_direct_call_preserves_key_meaning_confidence_and_source_text(self):
        correction_understanding = {
            "status": STATUS_RESOLVED,
            "original_expression": "recieve",
            "corrected_expression": "receive",
            "corrected_meaning": None,
            "language": "en",
            "locale": "en-US",
            "source_text": "not recieve, I mean receive",
            "confidence": 0.75,
        }
        handoff_result = self.core._store_resolved_correction_learning(
            correction_understanding)
        self.assertEqual(handoff_result.status, STATUS_ACCEPTED)
        stored = self.core.language_learning.get_item("en", "correction", "recieve")
        self.assertIsNotNone(stored)
        self.assertEqual(stored["meaning"], "receive")
        self.assertEqual(stored["confidence"], 0.75)
        self.assertEqual(stored["source_context"], "not recieve, I mean receive")

    def test_corrected_meaning_side_is_preserved_when_expression_is_absent(self):
        correction_understanding = {
            "status": STATUS_RESOLVED,
            "original_expression": "bank",
            "corrected_expression": None,
            "corrected_meaning": "a financial institution",
            "language": "en",
            "locale": None,
            "source_text": "not that bank, I mean a financial institution",
            "confidence": 0.5,
        }
        self.core._store_resolved_correction_learning(correction_understanding)
        stored = self.core.language_learning.get_item("en", "correction", "bank")
        self.assertIsNotNone(stored)
        self.assertEqual(stored["meaning"], "a financial institution")


# ----------------------------------------------------------------------
# 4: non-eligible input produces zero correction-learning storage
# handoffs.
# ----------------------------------------------------------------------
class TestNonEligibleInputProducesZeroHandoffs(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_ordinary_statement_never_calls_learn_item(self):
        call_count = _count_learn_item_calls(self.core)
        self.core.process_input("Python is a programming language.")
        self.assertEqual(call_count[0], 0)
        self.assertIsNone(self.core.last_correction_learning_handoff_result)

    def test_ordinary_question_never_calls_learn_item(self):
        call_count = _count_learn_item_calls(self.core)
        self.core.process_input("What is Python?")
        self.assertEqual(call_count[0], 0)

    def test_ael_command_never_calls_learn_item(self):
        call_count = _count_learn_item_calls(self.core)
        self.core.process_input("TEACH sun IS a star")
        self.assertEqual(call_count[0], 0)

    def test_goal_oriented_request_never_calls_learn_item(self):
        call_count = _count_learn_item_calls(self.core)
        self.core.process_input("I want to build a script that prints hello")
        self.assertEqual(call_count[0], 0)

    def test_text_not_matching_the_correction_marker_never_calls_learn_item(self):
        call_count = _count_learn_item_calls(self.core)
        self.core.process_input("not sure what you mean")
        self.assertEqual(call_count[0], 0)


# ----------------------------------------------------------------------
# 5: ambiguous/unresolved corrections do not create invalid learning
# records.
# ----------------------------------------------------------------------
class TestAmbiguousAndUnresolvedCorrectionsCreateNoInvalidRecords(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_direct_call_with_unresolved_status_stores_nothing(self):
        # UNRESOLVED: only one side of the correction is present.
        correction_understanding = {
            "status": STATUS_UNRESOLVED,
            "original_expression": "dgo",
            "corrected_expression": None,
            "corrected_meaning": None,
            "language": "en",
            "locale": None,
            "source_text": "dgo",
            "confidence": 0.0,
        }
        call_count = _count_learn_item_calls(self.core)
        result = self.core._store_resolved_correction_learning(correction_understanding)
        self.assertIsNone(result)
        self.assertEqual(call_count[0], 0)
        self.assertIsNone(self.core.language_learning.get_item("en", "correction", "dgo"))

    def test_direct_call_with_ambiguous_status_stores_nothing(self):
        correction_understanding = {
            "status": STATUS_AMBIGUOUS,
            "original_expression": "dgo",
            "corrected_expression": None,
            "corrected_meaning": None,
            "language": "en",
            "locale": None,
            "source_text": "dgo",
            "confidence": 0.0,
        }
        call_count = _count_learn_item_calls(self.core)
        result = self.core._store_resolved_correction_learning(correction_understanding)
        self.assertIsNone(result)
        self.assertEqual(call_count[0], 0)
        self.assertIsNone(self.core.language_learning.get_item("en", "correction", "dgo"))

    def test_direct_call_with_not_correction_status_stores_nothing(self):
        correction_understanding = {
            "status": STATUS_NOT_CORRECTION,
            "original_expression": None,
            "corrected_expression": None,
            "corrected_meaning": None,
            "language": None,
            "locale": None,
            "source_text": "hello there",
            "confidence": 0.0,
        }
        call_count = _count_learn_item_calls(self.core)
        result = self.core._store_resolved_correction_learning(correction_understanding)
        self.assertIsNone(result)
        self.assertEqual(call_count[0], 0)

    def test_unresolved_correction_via_full_pipeline_never_short_circuits_or_stores(self):
        # "not dgo" alone (no "I mean"/"I meant" side) does not match the
        # fixed correction marker at all (understanding/correction_
        # detection.py), so correction_understanding stays None here -
        # confirming this class of input never reaches step 1e's
        # RESOLVED branch, and therefore never reaches the storage
        # handoff either.
        call_count = _count_learn_item_calls(self.core)
        reply = self.core.process_input("not dgo")
        self.assertFalse(reply.startswith("[CORRECTION ACKNOWLEDGED]"))
        self.assertEqual(call_count[0], 0)
        self.assertIsNone(self.core.last_correction_learning_handoff_result)


# ----------------------------------------------------------------------
# 6 & 7: existing correction acknowledgement behavior and existing Core
# request behavior remain unchanged.
# ----------------------------------------------------------------------
class TestExistingBehaviorUnchanged(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_acknowledgement_reply_text_is_unchanged(self):
        reply = self.core.process_input("not dgo, I mean dog.")
        self.assertTrue(reply.startswith("[CORRECTION ACKNOWLEDGED]"))
        self.assertIn("original_expression: dgo", reply)
        self.assertIn("corrected_expression: dog", reply)

    def test_message_and_reply_are_still_recorded_in_memory_and_context(self):
        reply = self.core.process_input("not dgo, I mean dog.")
        turns = self.core.get_recent_turns(limit=1)
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["assistant"], reply)

    def test_ordinary_statement_is_learned_exactly_as_before(self):
        reply = self.core.process_input("Python is a programming language.")
        self.assertIn("Python", reply)

    def test_reasoning_still_answers_after_a_correction_acknowledged_turn(self):
        self.core.process_input("not dgo, I mean dog.")
        self.core.process_input("Dog is an animal.")
        reply = self.core.process_input("What is Dog?")
        self.assertNotEqual(reply, "")
        self.assertNotIn("[CORRECTION ACKNOWLEDGED]", reply)

    def test_planning_goal_creation_still_works_after_a_correction_turn(self):
        self.core.process_input("not dgo, I mean dog.")
        reply = self.core.process_input("I want to build a script that prints hello")
        self.assertIn("[GOAL CREATED]", reply)


# ----------------------------------------------------------------------
# 8: deterministic for identical input and state.
# ----------------------------------------------------------------------
class TestDeterministic(unittest.TestCase):
    def test_same_input_on_two_fresh_instances_gives_the_same_handoff_outcome(self):
        core_a, tmpdir_a = _make_core()
        core_b, tmpdir_b = _make_core()
        try:
            core_a.process_input("not dgo, I mean dog.")
            core_b.process_input("not dgo, I mean dog.")
            self.assertEqual(
                core_a.last_correction_learning_handoff_result,
                core_b.last_correction_learning_handoff_result,
            )
            item_a = core_a.language_learning.get_item("en", "correction", "dgo")
            item_b = core_b.language_learning.get_item("en", "correction", "dgo")
            self.assertEqual(item_a["meaning"], item_b["meaning"])
            self.assertEqual(item_a["confidence"], item_b["confidence"])
        finally:
            tmpdir_a.cleanup()
            tmpdir_b.cleanup()


if __name__ == "__main__":
    unittest.main()
