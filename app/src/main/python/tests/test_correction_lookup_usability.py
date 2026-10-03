"""
Tests for Prompt 468 - Determine Correction Context Usability.

`is_correction_lookup_context_usable()`
(language_intelligence/correction_lookup_usability.py) is a small,
deterministic check over an already-built Prompt 465
`CorrectionLookupContext`. It inspects only `status` and `records`
(and, per record, `key`/`meaning`); it does not perform a lookup,
select or rank among several usable records, apply a correction, or
generate any response text. Covers:

    1. valid FOUND context with one correction -> usable
    2. valid FOUND context with multiple corrections -> usable
    3. NOT_FOUND -> not usable
    4. FAILED -> not usable
    5. empty correction list -> not usable
    6. invalid/incomplete correction record -> not usable
    7. usability check is deterministic
    8. usability check does not modify the context

Run directly:
    python -m unittest tests.test_correction_lookup_usability -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.correction_lookup_context import (
    CorrectionLookupContext, build_correction_lookup_context,
)
from language_intelligence.correction_learning_exact_lookup_result import (
    CorrectionLearningExactLookupResult,
    STATUS_FOUND, STATUS_NOT_FOUND, STATUS_FAILED,
)
from language_intelligence.correction_lookup_usability import (
    is_correction_lookup_context_usable,
)


def _valid_record(key="dgo", meaning="dog", **overrides):
    record = {
        "id": 1, "language": "en", "item_type": "correction", "key": key,
        "meaning": meaning, "examples": [], "relationships": [],
        "confidence": 0.9, "source": "user_correction", "source_context": None,
        "learning_method": "explicit_correction", "version": 1,
        "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
    }
    record.update(overrides)
    return record


def _found_context(records):
    result = CorrectionLearningExactLookupResult(
        status=STATUS_FOUND, original_expression="dgo", records=records,
    )
    return build_correction_lookup_context(result)


def _not_found_context():
    result = CorrectionLearningExactLookupResult(
        status=STATUS_NOT_FOUND, original_expression="dgo", records=[],
    )
    return build_correction_lookup_context(result)


def _failed_context():
    result = CorrectionLearningExactLookupResult(
        status=STATUS_FAILED, original_expression="dgo", records=[],
        reason="storage_unavailable",
    )
    return build_correction_lookup_context(result)


class TestValidFoundContextWithOneCorrectionIsUsable(unittest.TestCase):
    def test_single_valid_record_is_usable(self):
        context = _found_context([_valid_record()])
        self.assertTrue(is_correction_lookup_context_usable(context))


class TestValidFoundContextWithMultipleCorrectionsIsUsable(unittest.TestCase):
    def test_multiple_valid_records_are_usable(self):
        context = _found_context([
            _valid_record(key="dgo", meaning="dog", language="en"),
            _valid_record(key="dgo", meaning="dogue", language="fr"),
        ])
        self.assertTrue(is_correction_lookup_context_usable(context))

    def test_usable_without_selecting_one(self):
        # Multiple usable records must not be ranked or reduced - the
        # context itself keeps every record; only the boolean answer
        # is asked for here.
        records = [
            _valid_record(key="dgo", meaning="dog", language="en"),
            _valid_record(key="dgo", meaning="dogue", language="fr"),
            _valid_record(key="dgo", meaning="dogg", language="de"),
        ]
        context = _found_context(records)
        self.assertTrue(is_correction_lookup_context_usable(context))
        self.assertEqual(len(context.records), 3)


class TestNotFoundIsNotUsable(unittest.TestCase):
    def test_not_found_is_not_usable(self):
        context = _not_found_context()
        self.assertFalse(is_correction_lookup_context_usable(context))

    def test_not_found_is_not_usable_even_with_stray_records(self):
        # NOT_FOUND always carries records=[] via build_correction_lookup_context,
        # but the status check alone must already be enough to disqualify it -
        # construct the context directly to make sure status is decisive.
        context = CorrectionLookupContext(
            status=STATUS_NOT_FOUND, original_expression="dgo",
            records=[_valid_record()],
        )
        self.assertFalse(is_correction_lookup_context_usable(context))


class TestFailedIsNotUsable(unittest.TestCase):
    def test_failed_is_not_usable(self):
        context = _failed_context()
        self.assertFalse(is_correction_lookup_context_usable(context))

    def test_failed_is_not_usable_even_with_stray_records(self):
        context = CorrectionLookupContext(
            status=STATUS_FAILED, original_expression="dgo",
            records=[_valid_record()], reason="storage_unavailable",
        )
        self.assertFalse(is_correction_lookup_context_usable(context))


class TestEmptyCorrectionListIsNotUsable(unittest.TestCase):
    def test_found_status_with_no_records_is_not_usable(self):
        # Not producible through build_correction_lookup_context (FOUND
        # always carries the lookup's own records), but a hand-built
        # context exercises the "empty records" rule directly.
        context = CorrectionLookupContext(
            status=STATUS_FOUND, original_expression="dgo", records=[],
        )
        self.assertFalse(is_correction_lookup_context_usable(context))


class TestInvalidIncompleteRecordIsNotUsable(unittest.TestCase):
    def test_missing_meaning_is_not_usable(self):
        record = _valid_record()
        del record["meaning"]
        context = _found_context([record])
        self.assertFalse(is_correction_lookup_context_usable(context))

    def test_missing_key_is_not_usable(self):
        record = _valid_record()
        del record["key"]
        context = _found_context([record])
        self.assertFalse(is_correction_lookup_context_usable(context))

    def test_blank_meaning_is_not_usable(self):
        context = _found_context([_valid_record(meaning="   ")])
        self.assertFalse(is_correction_lookup_context_usable(context))

    def test_blank_key_is_not_usable(self):
        context = _found_context([_valid_record(key="")])
        self.assertFalse(is_correction_lookup_context_usable(context))

    def test_none_key_and_meaning_is_not_usable(self):
        context = _found_context([_valid_record(key=None, meaning=None)])
        self.assertFalse(is_correction_lookup_context_usable(context))

    def test_non_dict_record_is_not_usable(self):
        context = CorrectionLookupContext(
            status=STATUS_FOUND, original_expression="dgo", records=["not a dict"],
        )
        self.assertFalse(is_correction_lookup_context_usable(context))

    def test_one_invalid_record_does_not_disqualify_a_valid_one(self):
        incomplete = _valid_record()
        del incomplete["meaning"]
        context = _found_context([incomplete, _valid_record()])
        self.assertTrue(is_correction_lookup_context_usable(context))


class TestUsabilityCheckIsDeterministic(unittest.TestCase):
    def test_same_context_always_produces_the_same_result(self):
        context = _found_context([_valid_record()])
        results = [is_correction_lookup_context_usable(context) for _ in range(5)]
        self.assertEqual(results, [True] * 5)

    def test_not_found_always_produces_the_same_result(self):
        context = _not_found_context()
        results = [is_correction_lookup_context_usable(context) for _ in range(5)]
        self.assertEqual(results, [False] * 5)

    def test_equal_contexts_produce_equal_results(self):
        context_a = _found_context([_valid_record()])
        context_b = _found_context([_valid_record()])
        self.assertEqual(context_a, context_b)
        self.assertEqual(
            is_correction_lookup_context_usable(context_a),
            is_correction_lookup_context_usable(context_b),
        )


class TestUsabilityCheckDoesNotModifyTheContext(unittest.TestCase):
    def test_context_unchanged_after_check(self):
        context = _found_context([_valid_record(), _valid_record(key="gud", meaning="good")])
        before = context.copy()
        is_correction_lookup_context_usable(context)
        self.assertEqual(context, before)

    def test_records_list_unchanged_after_check(self):
        context = _found_context([_valid_record()])
        before_records = copy.deepcopy(context.records)
        is_correction_lookup_context_usable(context)
        self.assertEqual(context.records, before_records)

    def test_not_found_context_unchanged_after_check(self):
        context = _not_found_context()
        before = context.copy()
        is_correction_lookup_context_usable(context)
        self.assertEqual(context, before)

    def test_invalid_type_raises_without_side_effects(self):
        with self.assertRaises(TypeError):
            is_correction_lookup_context_usable({"status": STATUS_FOUND})
        with self.assertRaises(TypeError):
            is_correction_lookup_context_usable(None)


if __name__ == "__main__":
    unittest.main()
