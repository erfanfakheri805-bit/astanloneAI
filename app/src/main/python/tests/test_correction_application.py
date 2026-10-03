"""
Tests for Prompt 475 - Apply Correction Request with Exact Matching.

`apply_correction_request()`
(language_intelligence/correction_application.py) applies an existing
Prompt 473 `CorrectionApplicationRequest` to a target text using EXACT
matching only, and returns the outcome as an existing Prompt 474
`CorrectionApplicationResult`. It never modifies the target text
outside an exact match, never raises, and is not connected to the
conversation/response pipeline. Covers:

    1. exact expression found and replaced
    2. exact expression not found
    3. multiple exact occurrences
    4. empty target text
    5. invalid request
    6. unchanged text when correction is not applied
    7. correct CorrectionApplicationResult status
    8. applied flag correctness
    9. preservation of original target text
    10. corrected output correctness

Run directly:
    python -m unittest tests.test_correction_application -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.correction_lookup_selection import (
    CorrectionSelectionResult, OUTCOME_SELECTED,
)
from language_intelligence.correction_application_candidate import (
    build_correction_application_candidate,
)
from language_intelligence.correction_application_request import (
    CorrectionApplicationRequest, build_correction_application_request,
)
from language_intelligence.correction_application_result import (
    STATUS_APPLIED, STATUS_NOT_APPLIED, STATUS_FAILED,
)
from language_intelligence.correction_application import (
    apply_correction_request,
)


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


def _ready_request(**overrides):
    record = _valid_record(**overrides)
    result = CorrectionSelectionResult(OUTCOME_SELECTED, correction=record)
    candidate = build_correction_application_candidate(result)
    return build_correction_application_request(candidate)


class TestApplyCorrectionRequest(unittest.TestCase):

    def test_exact_expression_found_and_replaced(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request(request, "I saw a dgo today.")
        self.assertEqual(result.status, STATUS_APPLIED)
        self.assertTrue(result.applied)
        self.assertEqual(result.corrected_text, "I saw a dog today.")

    def test_exact_expression_not_found(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request(request, "I saw a cat today.")
        self.assertEqual(result.status, STATUS_NOT_APPLIED)
        self.assertFalse(result.applied)

    def test_multiple_exact_occurrences_are_all_replaced(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request(
            request, "dgo dgo dgo saw another dgo",
        )
        self.assertEqual(result.status, STATUS_APPLIED)
        self.assertEqual(result.corrected_text, "dog dog dog saw another dog")
        self.assertEqual(result.metadata.get("occurrences_replaced"), 4)

    def test_empty_target_text(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request(request, "")
        self.assertEqual(result.status, STATUS_NOT_APPLIED)
        self.assertFalse(result.applied)
        self.assertEqual(result.original_text, "")
        self.assertEqual(result.corrected_text, "")

    def test_invalid_request_object_produces_failed(self):
        result = apply_correction_request("not a request", "some text")
        self.assertEqual(result.status, STATUS_FAILED)
        self.assertFalse(result.applied)

    def test_not_ready_request_produces_failed(self):
        request = CorrectionApplicationRequest(is_valid=False)
        result = apply_correction_request(request, "some text")
        self.assertEqual(result.status, STATUS_FAILED)
        self.assertFalse(result.applied)
        self.assertEqual(result.original_text, "some text")

    def test_non_string_target_text_produces_failed(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request(request, None)
        self.assertEqual(result.status, STATUS_FAILED)
        self.assertFalse(result.applied)

    def test_unchanged_text_when_not_applied(self):
        request = _ready_request(key="dgo", meaning="dog")
        target = "no matching expression here"
        result = apply_correction_request(request, target)
        self.assertEqual(result.original_text, target)
        self.assertEqual(result.corrected_text, target)

    def test_applied_flag_matches_status(self):
        request = _ready_request(key="dgo", meaning="dog")
        applied_result = apply_correction_request(request, "a dgo")
        not_applied_result = apply_correction_request(request, "no match")
        failed_result = apply_correction_request(request, None)
        self.assertEqual(applied_result.applied, applied_result.status == STATUS_APPLIED)
        self.assertEqual(not_applied_result.applied, not_applied_result.status == STATUS_APPLIED)
        self.assertEqual(failed_result.applied, failed_result.status == STATUS_APPLIED)

    def test_original_target_text_is_preserved_on_applied(self):
        request = _ready_request(key="dgo", meaning="dog")
        target = "a dgo walked by"
        result = apply_correction_request(request, target)
        self.assertEqual(result.original_text, target)
        # target_text itself is never mutated (str is immutable, but
        # confirm the value used for original_text still matches).
        self.assertEqual(target, "a dgo walked by")

    def test_corrected_output_is_exact(self):
        request = _ready_request(key="teh", meaning="the")
        result = apply_correction_request(request, "teh quick fox")
        self.assertEqual(result.corrected_text, "the quick fox")

    def test_applied_result_reports_matched_and_replacement_text(self):
        # Prompt 478: APPLIED results also report the exact match.
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request(
            request, "dgo dgo saw another dgo",
        )
        self.assertEqual(result.matched_text, "dgo")
        self.assertEqual(result.replacement_text, "dog")
        self.assertEqual(result.match_count, 3)

    def test_applied_result_preserves_before_and_after_text(self):
        # Prompt 479: APPLIED results also carry text_before/text_after.
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request(request, "a dgo here")
        self.assertEqual(result.text_before, "a dgo here")
        self.assertEqual(result.text_after, "a dog here")

    def test_not_applied_result_has_identical_before_and_after_text(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request(request, "no match here")
        self.assertEqual(result.text_before, "no match here")
        self.assertEqual(result.text_after, "no match here")

    def test_does_not_modify_unrelated_text(self):
        request = _ready_request(key="dgo", meaning="dog")
        result = apply_correction_request(request, "a dgomatic dgo")
        # "dgo" is an exact substring of "dgomatic" too - exact
        # substring matching replaces every exact occurrence,
        # including within a larger word; nothing else changes.
        self.assertEqual(result.corrected_text, "a dogmatic dog")


if __name__ == "__main__":
    unittest.main()
