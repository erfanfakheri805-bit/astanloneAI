"""
Tests for Prompt 569 - Add a Safe Correction Candidate Decision
Boundary.

`evaluate_correction_application_candidate_eligibility()`
(language_intelligence/correction_application_candidate_eligibility.py)
is a small, deterministic, read-only eligibility decision over an
existing `CorrectionApplicationCandidate` (Prompt 470), built entirely
by reusing the EXISTING Prompt 472 readiness guarantee
(`is_correction_application_candidate_ready()`) - it adds no new
candidate-content validation, performs no storage or retrieval access,
and never applies, rewrites, or modifies anything.

Covers Prompt 569 section 7's seventeen items:
    1. A valid real candidate produces the expected eligible decision.
    2. No candidate produces an ineligible decision.
    3. Malformed/invalid candidate data is handled conservatively.
    4. Eligibility is deterministic.
    5. Eligibility performs zero storage/database access.
    6. Eligibility performs zero retrieval operations.
    7. Eligibility does not modify the candidate.
    8. Eligibility does not modify `LanguageUnderstandingResult`.
    9. Eligibility does not modify `ResponseGenerationContext`.
    10. Existing Prompt 565 adapter tests remain passing (run
        unmodified as part of the full suite).
    11. Existing Prompt 566 trigger tests remain passing (run
        unmodified as part of the full suite).
    12. Existing Prompt 567 integration tests remain passing (run
        unmodified as part of the full suite).
    13. Existing Prompt 568 response-generation exposure tests remain
        passing (run unmodified as part of the full suite).
    14. Existing correction acknowledgement remains unchanged.
    15. Ordinary non-correction requests remain unchanged.
    16. Ambiguous/unresolved corrections remain safe (no candidate is
        ever attached for them, so eligibility is never even asked to
        consider one - see Prompt 566/567's own conservative
        behavior, unchanged).
    17. No automatic correction application occurs.

Run directly:
    python -m unittest tests.test_correction_application_candidate_eligibility_prompt569 -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import copy
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from language_intelligence.correction_lookup_selection import (
    CorrectionSelectionResult,
    OUTCOME_SELECTED, OUTCOME_AMBIGUOUS, OUTCOME_NOT_FOUND, OUTCOME_FAILED,
)
from language_intelligence.correction_application_candidate import (
    CorrectionApplicationCandidate, build_correction_application_candidate,
)
from language_intelligence.correction_application_candidate_eligibility import (
    CorrectionApplicationCandidateEligibility,
    evaluate_correction_application_candidate_eligibility,
    REASON_ELIGIBLE, REASON_NO_CANDIDATE, REASON_INVALID_CANDIDATE,
    REASON_CANDIDATE_NOT_READY,
)
from language_intelligence.language_understanding_result import (
    LanguageUnderstandingResult,
)
from language_intelligence.response_generation_context import (
    generation_context_from_understanding,
)
from language_intelligence.correction_understanding import (
    build_correction_understanding, STATUS_AMBIGUOUS, STATUS_UNRESOLVED,
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
    """Seed `store` through the EXISTING chain - never a synthetic row
    inserted directly - the SAME helper convention
    test_correction_retrieval_trigger_connection_prompt567.py already
    uses."""
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


def _valid_record(key="dgo", meaning="dog", language="en", **overrides):
    record = {
        "id": 1, "language": language, "item_type": "correction", "key": key,
        "meaning": meaning, "examples": [], "relationships": [],
        "confidence": 0.9, "source": "user_correction", "source_context": None,
        "learning_method": "explicit_correction", "version": 1,
        "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
    }
    record.update(overrides)
    return record


def _selected_candidate(**overrides):
    record = _valid_record(**overrides)
    result = CorrectionSelectionResult(OUTCOME_SELECTED, correction=record)
    return build_correction_application_candidate(result)


def _unselected_candidate(outcome):
    result = CorrectionSelectionResult(outcome, correction=None)
    return build_correction_application_candidate(result)


def _wrap_and_count(obj, attr_name):
    """Same 'test double only at the boundary' convention already used
    by test_correction_retrieval_trigger_connection_prompt567.py."""
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
# 1. A valid real candidate (built from the Section 2 pipeline's own
# constructor) produces the expected eligible decision.
# ----------------------------------------------------------------------
class TestValidCandidateIsEligible(unittest.TestCase):
    def test_valid_selected_candidate_is_eligible(self):
        candidate = _selected_candidate()
        decision = evaluate_correction_application_candidate_eligibility(candidate)
        self.assertIsInstance(decision, CorrectionApplicationCandidateEligibility)
        self.assertTrue(decision.eligible)
        self.assertEqual(decision.reason, REASON_ELIGIBLE)

    def test_decision_to_dict(self):
        candidate = _selected_candidate()
        decision = evaluate_correction_application_candidate_eligibility(candidate)
        self.assertEqual(
            decision.to_dict(), {"eligible": True, "reason": REASON_ELIGIBLE})

    def test_end_to_end_pipeline_candidate_is_eligible(self):
        """A candidate produced by the real, wired Section 2 pipeline
        (Core -> trigger -> adapter -> LanguageUnderstandingResult) is
        eligible - not just a hand-built one."""
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            candidate = understanding.correction_application_candidate
            decision = evaluate_correction_application_candidate_eligibility(candidate)
            self.assertTrue(decision.eligible)
            self.assertEqual(decision.reason, REASON_ELIGIBLE)
        finally:
            tmpdir.cleanup()


# ----------------------------------------------------------------------
# 2. No candidate produces an ineligible decision.
# ----------------------------------------------------------------------
class TestNoCandidateIsIneligible(unittest.TestCase):
    def test_none_candidate_is_ineligible(self):
        decision = evaluate_correction_application_candidate_eligibility(None)
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.reason, REASON_NO_CANDIDATE)

    def test_end_to_end_ordinary_message_has_no_candidate_and_is_ineligible(self):
        core, tmpdir = _make_core()
        try:
            understanding = core.understand_language("hello there")
            self.assertIsNone(understanding.correction_application_candidate)
            decision = evaluate_correction_application_candidate_eligibility(
                understanding.correction_application_candidate)
            self.assertFalse(decision.eligible)
            self.assertEqual(decision.reason, REASON_NO_CANDIDATE)
        finally:
            tmpdir.cleanup()


# ----------------------------------------------------------------------
# 3. Malformed/invalid candidate data is handled conservatively.
# ----------------------------------------------------------------------
class TestMalformedCandidateIsHandledConservatively(unittest.TestCase):
    def test_non_candidate_object_is_ineligible(self):
        for bad_value in ("not a candidate", 42, 3.14, [], {}, object()):
            with self.subTest(bad_value=bad_value):
                decision = evaluate_correction_application_candidate_eligibility(bad_value)
                self.assertFalse(decision.eligible)
                self.assertEqual(decision.reason, REASON_INVALID_CANDIDATE)

    def test_never_raises_for_malformed_input(self):
        try:
            evaluate_correction_application_candidate_eligibility(object())
        except Exception as exc:  # noqa: BLE001
            self.fail("evaluate_correction_application_candidate_eligibility raised %r" % (exc,))

    def test_invalid_candidate_is_valid_false_is_ineligible(self):
        candidate = CorrectionApplicationCandidate(is_valid=False)
        decision = evaluate_correction_application_candidate_eligibility(candidate)
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.reason, REASON_CANDIDATE_NOT_READY)

    def test_ambiguous_derived_candidate_is_ineligible(self):
        candidate = _unselected_candidate(OUTCOME_AMBIGUOUS)
        decision = evaluate_correction_application_candidate_eligibility(candidate)
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.reason, REASON_CANDIDATE_NOT_READY)

    def test_not_found_derived_candidate_is_ineligible(self):
        candidate = _unselected_candidate(OUTCOME_NOT_FOUND)
        decision = evaluate_correction_application_candidate_eligibility(candidate)
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.reason, REASON_CANDIDATE_NOT_READY)

    def test_failed_derived_candidate_is_ineligible(self):
        candidate = _unselected_candidate(OUTCOME_FAILED)
        decision = evaluate_correction_application_candidate_eligibility(candidate)
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.reason, REASON_CANDIDATE_NOT_READY)

    def test_missing_original_expression_is_ineligible(self):
        candidate = _selected_candidate(key=None)
        decision = evaluate_correction_application_candidate_eligibility(candidate)
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.reason, REASON_CANDIDATE_NOT_READY)

    def test_missing_corrected_expression_or_meaning_is_ineligible(self):
        candidate = _selected_candidate(meaning=None)
        decision = evaluate_correction_application_candidate_eligibility(candidate)
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.reason, REASON_CANDIDATE_NOT_READY)

    def test_unreal_language_is_ineligible(self):
        candidate = _selected_candidate(language="unknown")
        decision = evaluate_correction_application_candidate_eligibility(candidate)
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.reason, REASON_CANDIDATE_NOT_READY)


# ----------------------------------------------------------------------
# 4. Eligibility is deterministic.
# ----------------------------------------------------------------------
class TestEligibilityIsDeterministic(unittest.TestCase):
    def test_repeated_calls_return_equal_decisions(self):
        candidate = _selected_candidate()
        first = evaluate_correction_application_candidate_eligibility(candidate)
        second = evaluate_correction_application_candidate_eligibility(candidate)
        self.assertEqual(first, second)

    def test_equal_candidates_produce_equal_decisions(self):
        candidate_a = _selected_candidate()
        candidate_b = _selected_candidate()
        decision_a = evaluate_correction_application_candidate_eligibility(candidate_a)
        decision_b = evaluate_correction_application_candidate_eligibility(candidate_b)
        self.assertEqual(decision_a, decision_b)

    def test_none_is_always_the_same_decision(self):
        first = evaluate_correction_application_candidate_eligibility(None)
        second = evaluate_correction_application_candidate_eligibility(None)
        self.assertEqual(first, second)


# ----------------------------------------------------------------------
# 5 & 6. Zero storage/database access and zero retrieval operations.
# ----------------------------------------------------------------------
class TestZeroStorageAndZeroRetrieval(unittest.TestCase):
    def test_zero_store_lookup_calls(self):
        import language_intelligence.correction_retrieval_understanding_adapter as adapter_module
        candidate = _selected_candidate()
        call_count, restore = _wrap_and_count(
            adapter_module, "build_correction_application_candidate_from_store")
        try:
            evaluate_correction_application_candidate_eligibility(candidate)
        finally:
            restore()
        self.assertEqual(call_count[0], 0)

    def test_zero_selection_calls(self):
        import language_intelligence.correction_lookup_selection as selection_module
        candidate = _selected_candidate()
        call_count, restore = _wrap_and_count(
            selection_module, "select_unique_stored_correction")
        try:
            evaluate_correction_application_candidate_eligibility(candidate)
        finally:
            restore()
        self.assertEqual(call_count[0], 0)

    def test_zero_learning_store_access_during_end_to_end_evaluation(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            candidate = understanding.correction_application_candidate

            call_count, restore = _wrap_and_count(core.language_learning, "get_item")
            try:
                evaluate_correction_application_candidate_eligibility(candidate)
            finally:
                restore()
            self.assertEqual(call_count[0], 0)
        finally:
            tmpdir.cleanup()

    def test_no_import_of_retrieval_trigger(self):
        import language_intelligence.correction_application_candidate_eligibility as eligibility_module
        names = dir(eligibility_module)
        self.assertNotIn("correction_retrieval_trigger", names)
        self.assertNotIn("build_correction_retrieval_trigger", names)
        self.assertNotIn("store_accepted_correction_learning_input", names)
        self.assertNotIn("select_unique_stored_correction", names)


# ----------------------------------------------------------------------
# 7. Eligibility does not modify the candidate.
# ----------------------------------------------------------------------
class TestEligibilityDoesNotModifyCandidate(unittest.TestCase):
    def test_candidate_unchanged_after_evaluation(self):
        candidate = _selected_candidate()
        before = candidate.copy()
        evaluate_correction_application_candidate_eligibility(candidate)
        self.assertEqual(candidate, before)

    def test_ineligible_candidate_unchanged_after_evaluation(self):
        candidate = _unselected_candidate(OUTCOME_NOT_FOUND)
        before = candidate.copy()
        evaluate_correction_application_candidate_eligibility(candidate)
        self.assertEqual(candidate, before)


# ----------------------------------------------------------------------
# 8. Eligibility does not modify LanguageUnderstandingResult.
# ----------------------------------------------------------------------
class TestEligibilityDoesNotModifyLanguageUnderstandingResult(unittest.TestCase):
    def test_understanding_unchanged_after_evaluation(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            before = understanding.to_dict()
            evaluate_correction_application_candidate_eligibility(
                understanding.correction_application_candidate)
            after = understanding.to_dict()
            self.assertEqual(before, after)
        finally:
            tmpdir.cleanup()


# ----------------------------------------------------------------------
# 9. Eligibility does not modify ResponseGenerationContext.
# ----------------------------------------------------------------------
class TestEligibilityDoesNotModifyResponseGenerationContext(unittest.TestCase):
    def test_context_unchanged_after_evaluation(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            context = generation_context_from_understanding(understanding)
            self.assertIsNotNone(context)
            before = copy.deepcopy(context.to_dict())
            evaluate_correction_application_candidate_eligibility(
                context.correction_application_candidate)
            after = context.to_dict()
            self.assertEqual(before, after)
        finally:
            tmpdir.cleanup()


# ----------------------------------------------------------------------
# 14, 15, 16, 17: existing conversation-level behavior is unchanged.
# ----------------------------------------------------------------------
class TestExistingConversationBehaviorUnchanged(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_correction_acknowledgement_unchanged(self):
        reply = self.core.process_input("not dgo, I mean dog.")
        self.assertIn("original_expression: dgo", reply)
        self.assertIn("corrected_expression: dog", reply)

    def test_ordinary_non_correction_request_unchanged(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("what is the weather like")
        self.assertIsNone(understanding.correction_application_candidate)
        decision = evaluate_correction_application_candidate_eligibility(
            understanding.correction_application_candidate)
        self.assertFalse(decision.eligible)

    def test_ambiguous_correction_understanding_never_produces_a_candidate(self):
        # Same conservative ambiguous/unresolved messages
        # test_correction_retrieval_trigger_connection_prompt567.py's
        # own acknowledgement test uses - Prompt 566/567's own trigger
        # never attaches a candidate for either.
        for text in ("I mean this is interesting.", "What do you mean?"):
            reply = self.core.process_input(text)
            self.assertNotIn("original_expression:", reply)
            understanding = self.core.last_language_understanding
            candidate = understanding.correction_application_candidate
            self.assertIsNone(candidate)
            decision = evaluate_correction_application_candidate_eligibility(candidate)
            self.assertFalse(decision.eligible)
            self.assertEqual(decision.reason, REASON_NO_CANDIDATE)

    def test_no_automatic_correction_application_occurs(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        candidate = understanding.correction_application_candidate
        decision = evaluate_correction_application_candidate_eligibility(candidate)
        self.assertTrue(decision.eligible)
        # Evaluating eligibility must never itself change the
        # generated response/backend behavior.
        outcome = self.core.generate_language_response(understanding)
        self.assertIsNone(getattr(outcome, "generated_text", None))


if __name__ == "__main__":
    unittest.main()
