"""
Tests for Prompt 570 - Define a Safe Correction Application Operation.

`apply_correction_application_candidate()`
(language_intelligence/correction_application_candidate_operation.py)
connects Prompt 569's eligibility boundary
(`evaluate_correction_application_candidate_eligibility()`) to the
EXISTING, already-complete Prompt 473/477 correction-application chain
(`build_correction_application_request()`,
`apply_correction_request_with_validation()`) - it adds no new
matching, validation, or result logic of its own.

Covers Prompt 570 section 8's nineteen items:
    1. A valid eligible real candidate produces the expected correction
       operation.
    2. Original expression is preserved exactly.
    3. Corrected expression is preserved exactly.
    4. `None` candidate returns a deterministic non-applicable result.
    5. Invalid candidate returns a deterministic non-applicable result.
    6. Not-ready candidate returns a deterministic non-applicable
       result.
    7. Application performs zero database/storage access.
    8. Application performs zero retrieval.
    9. Application performs zero selection.
    10. Application does not mutate the candidate.
    11. Application does not mutate the input understanding/context.
    12. Repeated identical inputs produce identical results.
    13. Existing correction acknowledgement remains unchanged.
    14-18. Existing Prompts 565/566/567/568/569 tests remain passing
        (run unmodified as part of the full suite).
    19. No automatic invocation occurs in normal Core processing.

Run directly:
    python -m unittest tests.test_correction_application_candidate_operation_prompt570 -v
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
from language_intelligence.correction_lookup_selection import (
    CorrectionSelectionResult,
    OUTCOME_SELECTED, OUTCOME_AMBIGUOUS, OUTCOME_NOT_FOUND, OUTCOME_FAILED,
)
from language_intelligence.correction_application_candidate import (
    CorrectionApplicationCandidate, build_correction_application_candidate,
)
from language_intelligence.correction_application_candidate_eligibility import (
    REASON_NO_CANDIDATE, REASON_INVALID_CANDIDATE, REASON_CANDIDATE_NOT_READY,
)
from language_intelligence.correction_application_candidate_operation import (
    apply_correction_application_candidate,
)
from language_intelligence.correction_application_result import (
    CorrectionApplicationResult,
    STATUS_APPLIED, STATUS_NOT_APPLIED, STATUS_FAILED,
)
from language_intelligence.correction_understanding import (
    build_correction_understanding,
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
    inserted directly - the SAME helper convention Prompt 567/569's own
    tests already use."""
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
    """Same 'test double only at the boundary' convention Prompt
    567/569's own tests already use."""
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
# 1, 2, 3. A valid eligible candidate produces the expected operation,
# with the original/corrected expressions preserved exactly.
# ----------------------------------------------------------------------
class TestValidEligibleCandidateProducesExpectedOperation(unittest.TestCase):
    def test_valid_candidate_applies_to_matching_target_text(self):
        candidate = _selected_candidate(key="dgo", meaning="dog")
        result = apply_correction_application_candidate(candidate, "I saw a dgo today")
        self.assertIsInstance(result, CorrectionApplicationResult)
        self.assertEqual(result.status, STATUS_APPLIED)
        self.assertTrue(result.applied)
        self.assertEqual(result.corrected_text, "I saw a dog today")

    def test_original_expression_preserved_exactly(self):
        candidate = _selected_candidate(key="dgo", meaning="dog")
        result = apply_correction_application_candidate(candidate, "a dgo ran")
        self.assertEqual(result.matched_text, "dgo")
        self.assertEqual(result.text_before, "a dgo ran")
        self.assertEqual(result.original_text, "a dgo ran")

    def test_corrected_expression_preserved_exactly(self):
        candidate = _selected_candidate(key="dgo", meaning="dog")
        result = apply_correction_application_candidate(candidate, "a dgo ran")
        self.assertEqual(result.replacement_text, "dog")
        self.assertEqual(result.text_after, "a dog ran")

    def test_valid_candidate_from_real_pipeline_applies(self):
        """A candidate produced by the real, wired Section 2 pipeline
        (Core -> trigger -> adapter -> LanguageUnderstandingResult) is
        usable by this operation - not just a hand-built one."""
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            candidate = understanding.correction_application_candidate
            result = apply_correction_application_candidate(candidate, "a dgo ran fast")
            self.assertEqual(result.status, STATUS_APPLIED)
            self.assertEqual(result.corrected_text, "a dog ran fast")
        finally:
            tmpdir.cleanup()

    def test_no_match_in_target_text_is_not_applied(self):
        candidate = _selected_candidate(key="dgo", meaning="dog")
        result = apply_correction_application_candidate(candidate, "completely unrelated text")
        self.assertEqual(result.status, STATUS_NOT_APPLIED)
        self.assertFalse(result.applied)


# ----------------------------------------------------------------------
# 4, 5, 6. None / invalid / not-ready candidate -> deterministic
# non-applicable result.
# ----------------------------------------------------------------------
class TestIneligibleCandidateIsNonApplicable(unittest.TestCase):
    def test_none_candidate_is_failed(self):
        result = apply_correction_application_candidate(None, "a dgo ran")
        self.assertEqual(result.status, STATUS_FAILED)
        self.assertFalse(result.applied)
        self.assertEqual(result.reason, REASON_NO_CANDIDATE)
        self.assertIsNone(result.corrected_text)

    def test_none_candidate_never_raises(self):
        try:
            apply_correction_application_candidate(None, "a dgo ran")
        except Exception as exc:  # noqa: BLE001
            self.fail("apply_correction_application_candidate raised %r" % (exc,))

    def test_invalid_type_candidate_is_failed(self):
        for bad_value in ("not a candidate", 42, [], {}, object()):
            with self.subTest(bad_value=bad_value):
                result = apply_correction_application_candidate(bad_value, "a dgo ran")
                self.assertEqual(result.status, STATUS_FAILED)
                self.assertEqual(result.reason, REASON_INVALID_CANDIDATE)

    def test_invalid_type_candidate_never_raises(self):
        try:
            apply_correction_application_candidate(object(), "a dgo ran")
        except Exception as exc:  # noqa: BLE001
            self.fail("apply_correction_application_candidate raised %r" % (exc,))

    def test_not_ready_is_valid_false_candidate_is_failed(self):
        candidate = CorrectionApplicationCandidate(is_valid=False)
        result = apply_correction_application_candidate(candidate, "a dgo ran")
        self.assertEqual(result.status, STATUS_FAILED)
        self.assertEqual(result.reason, REASON_CANDIDATE_NOT_READY)

    def test_ambiguous_derived_candidate_is_failed(self):
        candidate = _unselected_candidate(OUTCOME_AMBIGUOUS)
        result = apply_correction_application_candidate(candidate, "a dgo ran")
        self.assertEqual(result.status, STATUS_FAILED)
        self.assertEqual(result.reason, REASON_CANDIDATE_NOT_READY)

    def test_not_found_derived_candidate_is_failed(self):
        candidate = _unselected_candidate(OUTCOME_NOT_FOUND)
        result = apply_correction_application_candidate(candidate, "a dgo ran")
        self.assertEqual(result.status, STATUS_FAILED)
        self.assertEqual(result.reason, REASON_CANDIDATE_NOT_READY)

    def test_failed_derived_candidate_is_failed(self):
        candidate = _unselected_candidate(OUTCOME_FAILED)
        result = apply_correction_application_candidate(candidate, "a dgo ran")
        self.assertEqual(result.status, STATUS_FAILED)
        self.assertEqual(result.reason, REASON_CANDIDATE_NOT_READY)

    def test_original_text_preserved_when_ineligible_and_target_is_string(self):
        result = apply_correction_application_candidate(None, "a dgo ran")
        self.assertEqual(result.original_text, "a dgo ran")

    def test_original_text_none_when_ineligible_and_target_not_a_string(self):
        result = apply_correction_application_candidate(None, 12345)
        self.assertIsNone(result.original_text)

    def test_end_to_end_ordinary_message_has_no_candidate_and_is_failed(self):
        core, tmpdir = _make_core()
        try:
            understanding = core.understand_language("hello there")
            self.assertIsNone(understanding.correction_application_candidate)
            result = apply_correction_application_candidate(
                understanding.correction_application_candidate, "hello there")
            self.assertEqual(result.status, STATUS_FAILED)
            self.assertEqual(result.reason, REASON_NO_CANDIDATE)
        finally:
            tmpdir.cleanup()


# ----------------------------------------------------------------------
# 7, 8, 9. Zero database/storage access, zero retrieval, zero selection.
# ----------------------------------------------------------------------
class TestZeroStorageRetrievalSelection(unittest.TestCase):
    def test_zero_store_lookup_calls_for_eligible_candidate(self):
        import language_intelligence.correction_retrieval_understanding_adapter as adapter_module
        candidate = _selected_candidate()
        call_count, restore = _wrap_and_count(
            adapter_module, "build_correction_application_candidate_from_store")
        try:
            apply_correction_application_candidate(candidate, "a dgo ran")
        finally:
            restore()
        self.assertEqual(call_count[0], 0)

    def test_zero_selection_calls_for_eligible_candidate(self):
        import language_intelligence.correction_lookup_selection as selection_module
        candidate = _selected_candidate()
        call_count, restore = _wrap_and_count(
            selection_module, "select_unique_stored_correction")
        try:
            apply_correction_application_candidate(candidate, "a dgo ran")
        finally:
            restore()
        self.assertEqual(call_count[0], 0)

    def test_zero_store_lookup_calls_for_ineligible_candidate(self):
        import language_intelligence.correction_retrieval_understanding_adapter as adapter_module
        call_count, restore = _wrap_and_count(
            adapter_module, "build_correction_application_candidate_from_store")
        try:
            apply_correction_application_candidate(None, "a dgo ran")
        finally:
            restore()
        self.assertEqual(call_count[0], 0)

    def test_zero_learning_store_access_end_to_end(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            candidate = understanding.correction_application_candidate

            call_count, restore = _wrap_and_count(core.language_learning, "get_item")
            try:
                apply_correction_application_candidate(candidate, "a dgo ran")
            finally:
                restore()
            self.assertEqual(call_count[0], 0)
        finally:
            tmpdir.cleanup()

    def test_no_import_of_retrieval_or_storage_modules(self):
        import language_intelligence.correction_application_candidate_operation as op_module
        names = dir(op_module)
        self.assertNotIn("correction_retrieval_trigger", names)
        self.assertNotIn("store_accepted_correction_learning_input", names)
        self.assertNotIn("select_unique_stored_correction", names)
        self.assertNotIn("build_correction_application_candidate_from_store", names)


# ----------------------------------------------------------------------
# 10, 11. No mutation of the candidate or the input understanding.
# ----------------------------------------------------------------------
class TestNoMutation(unittest.TestCase):
    def test_candidate_unchanged_after_application(self):
        candidate = _selected_candidate()
        before = candidate.copy()
        apply_correction_application_candidate(candidate, "a dgo ran")
        self.assertEqual(candidate, before)

    def test_ineligible_candidate_unchanged_after_application(self):
        candidate = _unselected_candidate(OUTCOME_NOT_FOUND)
        before = candidate.copy()
        apply_correction_application_candidate(candidate, "a dgo ran")
        self.assertEqual(candidate, before)

    def test_understanding_unchanged_after_application(self):
        core, tmpdir = _make_core()
        try:
            _store_a_correction(core.language_learning, "dgo", "dog")
            understanding = core.understand_language("not dgo, I mean dog.")
            before = understanding.to_dict()
            apply_correction_application_candidate(
                understanding.correction_application_candidate, "a dgo ran")
            after = understanding.to_dict()
            self.assertEqual(before, after)
        finally:
            tmpdir.cleanup()

    def test_target_text_string_is_not_mutated_in_place(self):
        candidate = _selected_candidate()
        target = "a dgo ran"
        apply_correction_application_candidate(candidate, target)
        self.assertEqual(target, "a dgo ran")


# ----------------------------------------------------------------------
# 12. Repeated identical inputs produce identical results.
# ----------------------------------------------------------------------
class TestDeterminism(unittest.TestCase):
    def test_repeated_calls_return_equal_results_eligible(self):
        candidate = _selected_candidate()
        first = apply_correction_application_candidate(candidate, "a dgo ran")
        second = apply_correction_application_candidate(candidate, "a dgo ran")
        self.assertEqual(first, second)

    def test_repeated_calls_return_equal_results_ineligible(self):
        first = apply_correction_application_candidate(None, "a dgo ran")
        second = apply_correction_application_candidate(None, "a dgo ran")
        self.assertEqual(first, second)

    def test_equal_candidates_produce_equal_results(self):
        candidate_a = _selected_candidate()
        candidate_b = _selected_candidate()
        result_a = apply_correction_application_candidate(candidate_a, "a dgo ran")
        result_b = apply_correction_application_candidate(candidate_b, "a dgo ran")
        self.assertEqual(result_a, result_b)


# ----------------------------------------------------------------------
# 13, 19. Existing correction acknowledgement unchanged; no automatic
# TEXT REWRITING occurs in normal Core processing.
#
# Prompt 572 update: Prompt 572 explicitly connects this operation to
# the real Core conversation path (Core._attach_correction_application_
# result(), called right after Core._attach_correction_application_
# candidate()), so `understanding.correction_application_result` IS now
# populated automatically for a real, eligible candidate, and `core.py`
# DOES now import this module - that is the intended, in-scope change
# Prompt 572 makes; see test_correction_application_result_core_
# prompt572.py for that behavior's own focused coverage. The two
# assertions below are updated to match. What remains true, and is
# still asserted here, is the narrower guarantee this class's name
# refers to: process_input()'s own REPLY TEXT is never automatically
# rewritten by this operation (Prompt 572 explicitly does not change
# final response text), and response_planning.py still never imports
# or calls this operation directly.
# ----------------------------------------------------------------------
class TestNoAutomaticInvocation(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_correction_acknowledgement_unchanged(self):
        reply = self.core.process_input("not dgo, I mean dog.")
        self.assertIn("original_expression: dgo", reply)
        self.assertIn("corrected_expression: dog", reply)

    def test_response_generation_context_carries_the_core_attached_result(self):
        # Prompt 572: Core now attaches a real CorrectionApplicationResult
        # for a real, eligible candidate - see
        # Core._attach_correction_application_result(). This was
        # `assertIsNone(...)` before Prompt 572; the in-scope Prompt 572
        # connection is exactly what makes it non-None here.
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        result = getattr(understanding, "correction_application_result", None)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, STATUS_APPLIED)

    def test_ordinary_process_input_does_not_change_user_text(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        reply = self.core.process_input("what is a dgo")
        # The operation is now connected in Core, but process_input()'s
        # own REPLY TEXT still never silently rewrites the user's typo -
        # Prompt 572 only attaches the structured result to
        # `understanding`, it does not change final response text.
        self.assertNotIn("what is a dog", reply)

    def test_module_now_imported_by_core(self):
        # Prompt 572: this is the intended, in-scope connection - Core
        # now imports and calls apply_correction_application_candidate()
        # from its own _attach_correction_application_result(). Before
        # Prompt 572 this asserted the opposite (assertNotIn).
        import core.core as core_module
        with open(core_module.__file__, "r", encoding="utf-8") as f:
            source = f.read()
        self.assertIn("correction_application_candidate_operation", source)
        self.assertIn("apply_correction_application_candidate", source)

    def test_module_not_imported_by_response_planning(self):
        import language_intelligence.response_planning as planning_module
        with open(planning_module.__file__, "r", encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn("correction_application_candidate_operation", source)
        self.assertNotIn("apply_correction_application_candidate", source)


if __name__ == "__main__":
    unittest.main()
