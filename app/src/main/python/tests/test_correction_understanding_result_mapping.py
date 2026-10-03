"""
Tests for Prompt 442 - Correction Understanding Result Mapping.

`map_correction_understanding_to_result()`
(language_intelligence/correction_understanding_result.py) is the one
small, deterministic conversion from an existing `CorrectionUnderstanding`
(Prompt 439) to the new `CorrectionUnderstandingResult` (Prompt 441). Only:

    1. each valid status maps correctly
    2. all relevant fields are preserved during the mapping
    3. None/optional values are handled per existing project convention
    4. existing correction-understanding behavior is unchanged

Run directly:
    python -m unittest tests.test_correction_understanding_result_mapping -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.correction_understanding import (
    build_correction_understanding,
    STATUS_RESOLVED, STATUS_AMBIGUOUS, STATUS_UNRESOLVED, STATUS_NOT_CORRECTION,
    ALL_STATUSES,
)
from language_intelligence.correction_understanding_result import (
    CorrectionUnderstandingResult,
    map_correction_understanding_to_result,
    build_correction_understanding_result,
)


class TestEachValidStatusMapsCorrectly(unittest.TestCase):
    """1. A CorrectionUnderstanding with each valid status maps correctly."""

    def test_resolved_maps_to_resolved(self):
        source = build_correction_understanding(
            "no I mean dog not dgo", original_expression="dgo",
            corrected_expression="dog", language="en", confidence=0.9)
        mapped = map_correction_understanding_to_result(source)
        self.assertIsInstance(mapped, CorrectionUnderstandingResult)
        self.assertEqual(mapped.status, STATUS_RESOLVED)

    def test_ambiguous_maps_to_ambiguous(self):
        source = build_correction_understanding(
            "not dgo", original_expression="dgo",
            corrected_candidates=["dog", "dig"])
        mapped = map_correction_understanding_to_result(source)
        self.assertEqual(mapped.status, STATUS_AMBIGUOUS)

    def test_unresolved_maps_to_unresolved(self):
        source = build_correction_understanding("dgo", original_expression="dgo")
        mapped = map_correction_understanding_to_result(source)
        self.assertEqual(mapped.status, STATUS_UNRESOLVED)

    def test_not_correction_maps_to_not_correction(self):
        source = build_correction_understanding("hello there")
        mapped = map_correction_understanding_to_result(source)
        self.assertEqual(mapped.status, STATUS_NOT_CORRECTION)

    def test_every_all_statuses_entry_is_covered_by_this_test_class(self):
        # Guards against ALL_STATUSES growing without a matching test above.
        covered = {STATUS_RESOLVED, STATUS_AMBIGUOUS, STATUS_UNRESOLVED, STATUS_NOT_CORRECTION}
        self.assertEqual(covered, set(ALL_STATUSES))


class TestAllRelevantFieldsArePreserved(unittest.TestCase):
    """2. All relevant fields are preserved during the mapping."""

    def test_original_expression_corrected_expression_or_meaning_language_locale_confidence(self):
        source = build_correction_understanding(
            "not dgo, I mean dog.", original_expression="dgo",
            corrected_expression="dog", language="en", locale="en-US", confidence=0.73)
        mapped = map_correction_understanding_to_result(source)
        self.assertEqual(mapped.original_expression, source.original_expression)
        self.assertEqual(mapped.corrected_expression_or_meaning, source.corrected_expression)
        self.assertEqual(mapped.language, source.language)
        self.assertEqual(mapped.locale, source.locale)
        self.assertEqual(mapped.confidence, source.confidence)

    def test_source_text_preserved_verbatim(self):
        raw = "  not dgo,   I mean dog.  "
        source = build_correction_understanding(
            raw, original_expression="dgo", corrected_expression="dog")
        mapped = map_correction_understanding_to_result(source)
        self.assertEqual(mapped.source_text, raw)
        self.assertEqual(mapped.source_text, source.source_text)

    def test_corrected_meaning_is_preserved_into_the_merged_field_when_no_expression(self):
        source = build_correction_understanding(
            "src", original_expression="dgo", corrected_meaning="a domestic animal")
        mapped = map_correction_understanding_to_result(source)
        self.assertEqual(mapped.corrected_expression_or_meaning, "a domestic animal")


class TestNoneOptionalValuesHandledPerConvention(unittest.TestCase):
    """3. None/optional values are handled according to existing project
    convention (never defaulted or invented - copied through as None)."""

    def test_not_correction_result_has_none_fields_except_status_and_source(self):
        source = build_correction_understanding("hello there")
        mapped = map_correction_understanding_to_result(source)
        self.assertIsNone(mapped.original_expression)
        self.assertIsNone(mapped.corrected_expression_or_meaning)
        self.assertIsNone(mapped.language)
        self.assertIsNone(mapped.locale)
        self.assertEqual(mapped.confidence, 0.0)

    def test_no_language_or_locale_supplied_maps_to_none_not_a_default_string(self):
        source = build_correction_understanding(
            "not dgo, I mean dog.", original_expression="dgo", corrected_expression="dog")
        mapped = map_correction_understanding_to_result(source)
        self.assertIsNone(mapped.language)
        self.assertIsNone(mapped.locale)

    def test_neither_corrected_expression_nor_meaning_maps_to_none(self):
        source = build_correction_understanding("dgo", original_expression="dgo")
        mapped = map_correction_understanding_to_result(source)
        self.assertIsNone(mapped.corrected_expression_or_meaning)

    def test_rejects_non_correction_understanding_input(self):
        with self.assertRaises(TypeError):
            map_correction_understanding_to_result({"status": STATUS_RESOLVED})
        with self.assertRaises(TypeError):
            map_correction_understanding_to_result(None)


class TestExistingBehaviorUnchanged(unittest.TestCase):
    """4. Existing correction-understanding behavior remains unchanged."""

    def test_build_correction_understanding_still_behaves_as_before(self):
        result = build_correction_understanding(
            "no I mean dog not dgo", original_expression="dgo",
            corrected_expression="dog", language="en", locale="en-US", confidence=0.9)
        self.assertEqual(result.status, STATUS_RESOLVED)
        self.assertEqual(result.original_expression, "dgo")
        self.assertEqual(result.corrected_expression, "dog")
        self.assertIsNone(result.corrected_meaning)

    def test_prompt_441_alias_still_works_and_matches_the_new_function(self):
        source = build_correction_understanding(
            "src", original_expression="dgo", corrected_expression="dog",
            language="en", confidence=0.5)
        via_alias = build_correction_understanding_result(source)
        via_new_name = map_correction_understanding_to_result(source)
        self.assertEqual(via_alias.to_dict(), via_new_name.to_dict())


if __name__ == "__main__":
    unittest.main()
