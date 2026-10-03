"""
Tests for Prompt 567 - Connect the Correction Trigger to Existing
Retrieval.

Prompt 565 built the retrieval adapter
(language_intelligence/correction_retrieval_understanding_adapter.py)
and Prompt 566 built the conservative deterministic trigger
(language_intelligence/correction_retrieval_trigger.py), but neither
was ever called from anywhere else in the codebase. Prompt 567 adds
exactly one new call site - `Core._attach_correction_application_
candidate()` - called from both places Core already attaches optional,
best-effort information to a freshly produced `LanguageUnderstandingResult`
(`_handle_conversation`'s step 1c and `understand_language()`), right
after `understanding.correction_understanding` is already available.

Covers Prompt 567 section 9's fifteen items:
    1. Triggered correction performs retrieval through the existing
       adapter.
    2. A real stored correction produces a real
       `CorrectionApplicationCandidate`.
    3. The candidate is exposed through `LanguageUnderstandingResult`.
    4. `to_dict()` preserves the candidate.
    5. Retrieval occurs exactly once per understanding operation.
    6. Selection occurs exactly once.
    7. Non-triggering messages perform zero correction retrieval.
    8. No matching correction produces `candidate=None`.
    9. Ambiguous correction remains conservative.
    10. Unresolved correction remains conservative.
    11. Existing correction acknowledgement remains unchanged.
    12. Existing Prompt 565 adapter tests remain passing (run
        unmodified as part of the full suite).
    13. Existing Prompt 566 trigger tests remain passing (run
        unmodified as part of the full suite).
    14. Repeated equivalent operations remain deterministic.
    15. No automatic correction/application occurs.

Run directly:
    python -m unittest tests.test_correction_retrieval_trigger_connection_prompt567 -v
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
import core.core as core_module
from language_intelligence import correction_retrieval_understanding_adapter as adapter_module
from language_intelligence.language_understanding_result import LanguageUnderstandingResult
from language_intelligence.correction_application_candidate import (
    CorrectionApplicationCandidate,
)
from language_intelligence.correction_understanding import (
    build_correction_understanding,
    STATUS_AMBIGUOUS,
    STATUS_UNRESOLVED,
)
from language_intelligence.correction_understanding_result import (
    map_correction_understanding_to_result,
)
from language_intelligence.correction_feedback_record import (
    map_correction_understanding_result_to_feedback_record,
)
from language_intelligence.correction_feedback_learning_input_adapter import (
    convert_correction_feedback_to_learning_input,
)
from language_intelligence.correction_learning_handoff_result import (
    handoff_correction_learning_input_with_result,
)
from language_intelligence.correction_learning_input_storage import (
    store_accepted_correction_learning_input,
)


def _make_core():
    tmpdir = tempfile.TemporaryDirectory()
    db_path = os.path.join(tmpdir.name, "test_memory.sqlite3")
    skills_dir = os.path.join(tmpdir.name, "skills")
    core = Core(memory_db_path=db_path, skill_definitions_dir=skills_dir)
    return core, tmpdir


def _store_a_correction(store, original_expression="dgo", corrected_expression="dog",
                         language="en", locale="en-US", confidence=0.9):
    """Seed `store` (Core's own real `self.language_learning`) with a
    stored correction through the EXISTING chain - the same one
    `Core._store_resolved_correction_learning` itself uses - never a
    synthetic row inserted directly."""
    source = build_correction_understanding(
        "no I mean %s not %s" % (corrected_expression, original_expression),
        original_expression=original_expression,
        corrected_expression=corrected_expression, language=language,
        locale=locale, confidence=confidence)
    result = map_correction_understanding_to_result(source)
    record = map_correction_understanding_result_to_feedback_record(result)
    learning_input = convert_correction_feedback_to_learning_input(record)
    handoff_result = handoff_correction_learning_input_with_result(learning_input, store)
    stored = store_accepted_correction_learning_input(handoff_result, learning_input, store)
    return learning_input, stored


def _minimal_result(correction_understanding=None):
    return LanguageUnderstandingResult(
        original_input="hello there",
        detected_language="en",
        normalized_input="hello there",
        intent="unknown",
        entities=[],
        referenced_items=[],
        active_topic=None,
        conversation_context=None,
        confidence=0.5,
        ambiguity=False,
        needs_clarification=False,
        correction_understanding=correction_understanding,
    )


def _wrap_and_count(obj, attr_name):
    """Wrap `obj.attr_name` with a call counter, still delegating to the
    real, unmodified function - the SAME 'test double only at the
    boundary' convention already used by
    test_section2_correction_learning_core_integration_prompt562.py's
    `_count_learn_item_calls`. Returns (call_count_list, restore_fn)."""
    original = getattr(obj, attr_name)
    call_count = [0]

    def counting(*args, **kwargs):
        call_count[0] += 1
        return original(*args, **kwargs)

    setattr(obj, attr_name, counting)

    def restore():
        setattr(obj, attr_name, original)

    return call_count, restore


# ----------------------------------------------------------------------
# 1, 2, 3, 4: a triggered, resolved correction with a real stored match
# performs retrieval through the existing adapter and exposes a real
# candidate, preserved by to_dict().
# ----------------------------------------------------------------------
class TestTriggeredRetrievalProducesRealCandidate(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_stored_correction_is_found_and_attached(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        self.core.process_input("not dgo, I mean dog.")
        understanding = self.core.last_language_understanding
        candidate = understanding.correction_application_candidate
        self.assertIsInstance(candidate, CorrectionApplicationCandidate)
        self.assertTrue(candidate.is_valid)
        self.assertEqual(candidate.original_expression, "dgo")

    def test_candidate_data_matches_the_real_stored_correction(self):
        _store_a_correction(self.core.language_learning, "teh", "the", confidence=0.75)
        self.core.process_input("not teh, I mean the.")
        candidate = self.core.last_language_understanding.correction_application_candidate
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.corrected_expression_or_meaning, "the")

    def test_candidate_exposed_through_language_understanding_result(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        self.assertIsInstance(
            understanding.correction_application_candidate, CorrectionApplicationCandidate)

    def test_to_dict_preserves_the_candidate(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        as_dict = understanding.to_dict()
        self.assertIsNotNone(as_dict["correction_application_candidate"])
        self.assertEqual(
            as_dict["correction_application_candidate"]["original_expression"], "dgo")


# ----------------------------------------------------------------------
# 5 & 6: exactly-once retrieval and exactly-once selection per
# understanding operation.
# ----------------------------------------------------------------------
class TestExactlyOnceRetrievalAndSelection(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_retrieval_adapter_called_exactly_once(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        call_count, restore = _wrap_and_count(
            core_module, "retrieve_and_attach_correction_application_candidate")
        try:
            self.core.understand_language("not dgo, I mean dog.")
        finally:
            restore()
        self.assertEqual(call_count[0], 1)

    def test_underlying_lookup_happens_exactly_once(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        call_count, restore = _wrap_and_count(
            adapter_module, "build_correction_application_candidate_from_store")
        try:
            self.core.understand_language("not dgo, I mean dog.")
        finally:
            restore()
        self.assertEqual(call_count[0], 1)

    def test_selection_happens_exactly_once(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        call_count, restore = _wrap_and_count(
            adapter_module, "select_unique_stored_correction")
        try:
            self.core.understand_language("not dgo, I mean dog.")
        finally:
            restore()
        self.assertEqual(call_count[0], 1)

    def test_no_duplicate_candidates_across_repeated_calls(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        first = self.core.understand_language("not dgo, I mean dog.")
        second = self.core.understand_language("not dgo, I mean dog.")
        self.assertIsNotNone(first.correction_application_candidate)
        self.assertIsNotNone(second.correction_application_candidate)


# ----------------------------------------------------------------------
# 7: non-triggering messages perform zero correction retrieval.
# ----------------------------------------------------------------------
class TestNonTriggeringMessagesPerformZeroRetrieval(unittest.TestCase):
    NON_TRIGGERING_MESSAGES = (
        "I mean this is interesting.",
        "What do you mean?",
        "I meant to ask you something.",
        "Actually, tell me about dogs.",
        "Hello, how are you today?",
    )

    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_zero_retrieval_calls_for_ordinary_messages(self):
        call_count, restore = _wrap_and_count(
            core_module, "retrieve_and_attach_correction_application_candidate")
        try:
            for text in self.NON_TRIGGERING_MESSAGES:
                self.core.understand_language(text)
        finally:
            restore()
        self.assertEqual(call_count[0], 0)

    def test_candidate_stays_none_for_ordinary_messages(self):
        for text in self.NON_TRIGGERING_MESSAGES:
            understanding = self.core.understand_language(text)
            self.assertIsNone(understanding.correction_application_candidate)


# ----------------------------------------------------------------------
# 8: the trigger fires (RESOLVED correction) but no matching learned
# correction exists -> candidate stays None, retrieval may run once,
# nothing raises.
# ----------------------------------------------------------------------
class TestNoMatchingCorrectionProducesNoCandidate(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_candidate_is_none_when_nothing_is_stored(self):
        understanding = self.core.understand_language("not dgo, I mean dog.")
        self.assertIsNone(understanding.correction_application_candidate)

    def test_no_exception_escapes(self):
        try:
            understanding = self.core.understand_language("not xyzzy, I mean plugh.")
        except Exception as exc:  # noqa: BLE001
            self.fail(f"understand_language() raised unexpectedly: {exc!r}")
        self.assertIsNone(understanding.correction_application_candidate)

    def test_normal_understanding_continues_unchanged(self):
        understanding = self.core.understand_language("not dgo, I mean dog.")
        self.assertEqual(
            understanding.correction_understanding["original_expression"], "dgo")
        self.assertEqual(
            understanding.correction_understanding["corrected_expression"], "dog")


# ----------------------------------------------------------------------
# 9 & 10: AMBIGUOUS/UNRESOLVED correction understanding stays
# conservative - exercised directly at the connection point, since the
# existing (unchanged, Prompt 440) detector never itself produces these
# statuses from ordinary free-form text (see
# understanding/correction_detection.py's one fixed marker, which
# always yields either both pieces or neither).
# ----------------------------------------------------------------------
class TestAmbiguousAndUnresolvedStayConservative(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_ambiguous_correction_does_not_retrieve_or_attach(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        ambiguous = build_correction_understanding(
            "not dgo, I mean dog or doge",
            original_expression="dgo",
            corrected_candidates=["dog", "doge"])
        self.assertEqual(ambiguous.status, STATUS_AMBIGUOUS)
        understanding = _minimal_result(ambiguous.to_dict())

        call_count, restore = _wrap_and_count(
            core_module, "retrieve_and_attach_correction_application_candidate")
        try:
            self.core._attach_correction_application_candidate(understanding)
        finally:
            restore()

        self.assertEqual(call_count[0], 0)
        self.assertIsNone(understanding.correction_application_candidate)

    def test_unresolved_correction_does_not_retrieve_or_attach(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        unresolved = build_correction_understanding("not dgo", original_expression="dgo")
        self.assertEqual(unresolved.status, STATUS_UNRESOLVED)
        understanding = _minimal_result(unresolved.to_dict())

        call_count, restore = _wrap_and_count(
            core_module, "retrieve_and_attach_correction_application_candidate")
        try:
            self.core._attach_correction_application_candidate(understanding)
        finally:
            restore()

        self.assertEqual(call_count[0], 0)
        self.assertIsNone(understanding.correction_application_candidate)


# ----------------------------------------------------------------------
# 11 & 15: existing correction acknowledgement is unaffected, and no
# automatic correction application occurs anywhere.
# ----------------------------------------------------------------------
class TestAcknowledgementUnaffectedAndNoAutoApplication(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_acknowledgement_reply_text_unchanged_without_a_stored_match(self):
        reply = self.core.process_input("not dgo, I mean dog.")
        self.assertIn("original_expression: dgo", reply)
        self.assertIn("corrected_expression: dog", reply)

    def test_acknowledgement_reply_text_unchanged_with_a_stored_match(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        reply = self.core.process_input("not dgo, I mean dog.")
        self.assertIn("original_expression: dgo", reply)
        self.assertIn("corrected_expression: dog", reply)

    def test_user_message_and_store_are_never_rewritten(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        self.core.process_input("not dgo, I mean dog.")
        understanding = self.core.last_language_understanding
        # The candidate is only informational; original_input is
        # untouched, and the stored item's own meaning is unchanged.
        self.assertEqual(understanding.original_input, "not dgo, I mean dog.")
        stored = self.core.language_learning.get_item("en", "correction", "dgo")
        self.assertEqual(stored["meaning"], "dog")

    def test_ambiguous_and_unresolved_never_reach_acknowledgement_or_candidate(self):
        for text in ("I mean this is interesting.", "What do you mean?"):
            reply = self.core.process_input(text)
            self.assertNotIn("original_expression:", reply)
            understanding = self.core.last_language_understanding
            self.assertIsNone(understanding.correction_application_candidate)


# ----------------------------------------------------------------------
# 14: repeated equivalent operations remain deterministic.
# ----------------------------------------------------------------------
class TestDeterminism(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_repeated_equivalent_calls_produce_equal_candidates(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        first = self.core.understand_language("not dgo, I mean dog.")
        second = self.core.understand_language("not dgo, I mean dog.")
        self.assertEqual(
            first.correction_application_candidate.to_dict(),
            second.correction_application_candidate.to_dict(),
        )

    def test_repeated_no_match_calls_stay_none(self):
        first = self.core.understand_language("not zzz, I mean qqq.")
        second = self.core.understand_language("not zzz, I mean qqq.")
        self.assertIsNone(first.correction_application_candidate)
        self.assertIsNone(second.correction_application_candidate)


if __name__ == "__main__":
    unittest.main()
