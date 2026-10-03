"""
Tests for Prompt 476 - Validate Correction Application Target.

`validate_correction_application_target()`
(language_intelligence/correction_application_target_validation.py)
checks whether an existing Prompt 473 `CorrectionApplicationRequest`
could be safely applied to a target text by the existing Prompt 475
`apply_correction_request()`, using EXACT matching only. It never
modifies the target text and never applies the correction. Covers:

    1. valid request + exact target -> READY
    2. original expression missing -> NOT_READY
    3. invalid request -> INVALID
    4. invalid target -> INVALID
    5. corrected expression missing -> INVALID
    6. target text remains unchanged
    7. exact matching behavior
    8. no fuzzy matching
    9. deterministic repeated validation

Run directly:
    python -m unittest tests.test_correction_application_target_validation -v
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
from language_intelligence.correction_application_target_validation import (
    validate_correction_application_target,
    STATUS_READY, STATUS_NOT_READY, STATUS_INVALID,
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


class TestValidateCorrectionApplicationTarget(unittest.TestCase):

    def test_valid_request_with_exact_target_is_ready(self):
        request = _ready_request(key="dgo", meaning="dog")
        validation = validate_correction_application_target(
            request, "I saw a dgo today.",
        )
        self.assertEqual(validation.status, STATUS_READY)
        self.assertTrue(validation.ready)
        self.assertIsNone(validation.reason)

    def test_original_expression_missing_from_target_is_not_ready(self):
        request = _ready_request(key="dgo", meaning="dog")
        validation = validate_correction_application_target(
            request, "no matching text here",
        )
        self.assertEqual(validation.status, STATUS_NOT_READY)
        self.assertFalse(validation.ready)

    def test_invalid_request_object_is_invalid(self):
        validation = validate_correction_application_target(
            "not a request", "some text",
        )
        self.assertEqual(validation.status, STATUS_INVALID)
        self.assertFalse(validation.ready)

    def test_not_ready_candidate_derived_request_is_invalid(self):
        request = CorrectionApplicationRequest(is_valid=False)
        validation = validate_correction_application_target(
            request, "some text",
        )
        self.assertEqual(validation.status, STATUS_INVALID)

    def test_invalid_target_text_is_invalid(self):
        request = _ready_request(key="dgo", meaning="dog")
        validation = validate_correction_application_target(request, None)
        self.assertEqual(validation.status, STATUS_INVALID)

    def test_corrected_expression_missing_is_invalid(self):
        # A candidate/request built with a blank meaning never becomes
        # "ready" in the first place (Prompt 472), so the resulting
        # request is already invalid - confirm the validator reports
        # INVALID rather than treating it as READY/NOT_READY.
        request = _ready_request(key="dgo", meaning="")
        validation = validate_correction_application_target(
            request, "I saw a dgo today.",
        )
        self.assertEqual(validation.status, STATUS_INVALID)

    def test_target_text_remains_unchanged(self):
        request = _ready_request(key="dgo", meaning="dog")
        target = "I saw a dgo today."
        validate_correction_application_target(request, target)
        self.assertEqual(target, "I saw a dgo today.")

    def test_exact_matching_behavior(self):
        request = _ready_request(key="teh", meaning="the")
        ready = validate_correction_application_target(request, "teh quick fox")
        not_ready = validate_correction_application_target(request, "the quick fox")
        self.assertEqual(ready.status, STATUS_READY)
        self.assertEqual(not_ready.status, STATUS_NOT_READY)

    def test_no_fuzzy_or_case_insensitive_matching(self):
        request = _ready_request(key="Dgo", meaning="Dog")
        # Different case and a near-miss spelling must NOT count as a
        # match - exact, case-sensitive matching only.
        validation_case = validate_correction_application_target(
            request, "I saw a dgo today.",
        )
        validation_near = validate_correction_application_target(
            request, "I saw a Dgu today.",
        )
        self.assertEqual(validation_case.status, STATUS_NOT_READY)
        self.assertEqual(validation_near.status, STATUS_NOT_READY)

    def test_repeated_validation_is_deterministic(self):
        request = _ready_request(key="dgo", meaning="dog")
        target = "I saw a dgo today."
        first = validate_correction_application_target(request, target)
        second = validate_correction_application_target(request, target)
        third = validate_correction_application_target(request, target)
        self.assertEqual(first, second)
        self.assertEqual(second, third)


if __name__ == "__main__":
    unittest.main()
