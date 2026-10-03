"""
Tests for Prompt 563 - Section 2 Correction-Learning Retrieval/
Application Architecture Audit.

Two groups of tests:

1. Structural tests on the audit's own output (mirrors the same checks
   used for the Prompt 559/561 audits) - well-formed, deterministic,
   free of forbidden score/rank/"best"/"worst" language.

2. Real-behavior regression tests that independently verify the audit's
   two central factual claims against a real `Core` instance (not a
   synthetic fixture), so a later prompt that changes any of this is
   caught immediately:

   a. a RESOLVED correction stored through Prompt 562's real Core write
      path can be read back, correctly, by the existing retrieval
      functions, and can be carried, correctly, all the way to a valid
      `CorrectionApplicationCandidate` - using ONLY existing,
      already-tested functions, with NO new retrieval or candidate
      logic added by this prompt;
   b. that full chain is still never triggered automatically by
      `Core.process_input()` - `correction_application_candidate` does
      not merely read back `None` on `last_language_understanding`, the
      attribute does not exist there at all, and ordinary conversation
      behavior after a stored correction is completely unaffected by
      its mere presence in the store.

Run directly:
    python -m unittest tests.test_section2_correction_retrieval_application_audit_prompt563 -v
"""

import os
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diagnostics.section2_correction_retrieval_application_audit_prompt563 import (
    build_correction_retrieval_application_audit,
    IMPLEMENTED_AND_WORKING,
    IMPLEMENTED_BUT_NOT_INTEGRATED,
    PARTIALLY_IMPLEMENTED,
    MISSING,
    DUPLICATE_OR_OVERLAPPING,
    INTEGRATION_GAP,
)
from core.core import Core
from language_intelligence.correction_learning_exact_lookup_result import (
    lookup_correction_learning_input_by_original_expression_with_result,
    STATUS_FOUND as LOOKUP_STATUS_FOUND,
)
from language_intelligence.correction_lookup_context import build_correction_lookup_context
from language_intelligence.correction_lookup_selection import (
    select_unique_stored_correction,
    OUTCOME_SELECTED,
)
from language_intelligence.correction_application_candidate import (
    build_correction_application_candidate,
)

REQUIRED_TOP_LEVEL_KEYS = {
    "total_files_inspected",
    "files_inspected",
    "implemented_and_working",
    "implemented_but_not_integrated",
    "partially_implemented",
    "missing",
    "duplicate_or_overlapping",
    "integration_gaps",
    "request_lifecycle_trace",
    "can_the_remaining_gap_be_closed_by_a_small_connection_alone",
    "smallest_concrete_missing_foundation_for_a_later_prompt",
}

ENTRY_LIST_KEYS = (
    "implemented_and_working",
    "implemented_but_not_integrated",
    "partially_implemented",
    "missing",
    "duplicate_or_overlapping",
    "integration_gaps",
)

FORBIDDEN_WORDS = ("best", "worst", "score", "rank")

_ABSENT = object()


class Section2CorrectionRetrievalApplicationAuditStructureTests(unittest.TestCase):

    def setUp(self):
        self.audit = build_correction_retrieval_application_audit()

    def test_returns_all_required_top_level_keys(self):
        self.assertEqual(set(self.audit.keys()), REQUIRED_TOP_LEVEL_KEYS)

    def test_deterministic_across_calls(self):
        second = build_correction_retrieval_application_audit()
        self.assertEqual(self.audit, second)

    def test_returned_structure_is_not_the_module_level_constant(self):
        self.audit["implemented_and_working"].append({"name": "x"})
        fresh = build_correction_retrieval_application_audit()
        import diagnostics.section2_correction_retrieval_application_audit_prompt563 as mod
        self.assertEqual(len(fresh["implemented_and_working"]),
                          len(mod.IMPLEMENTED_AND_WORKING_FINDINGS))

    def test_every_entry_has_name_kind_and_evidence(self):
        for key in ENTRY_LIST_KEYS:
            for entry in self.audit[key]:
                self.assertEqual(set(entry.keys()), {"name", "kind", "evidence"})
                self.assertIsInstance(entry["name"], str)
                self.assertTrue(entry["name"])
                self.assertIsInstance(entry["evidence"], str)
                self.assertTrue(entry["evidence"])

    def test_entry_kind_matches_its_own_list(self):
        expected_kind = {
            "implemented_and_working": IMPLEMENTED_AND_WORKING,
            "implemented_but_not_integrated": IMPLEMENTED_BUT_NOT_INTEGRATED,
            "partially_implemented": PARTIALLY_IMPLEMENTED,
            "missing": MISSING,
            "duplicate_or_overlapping": DUPLICATE_OR_OVERLAPPING,
            "integration_gaps": INTEGRATION_GAP,
        }
        for key, kind in expected_kind.items():
            for entry in self.audit[key]:
                self.assertEqual(entry["kind"], kind)

    def test_no_forbidden_score_rank_language(self):
        blob = repr(self.audit).lower()
        for word in FORBIDDEN_WORDS:
            self.assertNotIn(word, blob)

    def test_at_least_one_finding_in_every_populated_category(self):
        # duplicate_or_overlapping is legitimately empty this prompt -
        # nothing new was found to duplicate. Every other category has
        # at least one finding.
        for key in ENTRY_LIST_KEYS:
            if key == "duplicate_or_overlapping":
                continue
            self.assertGreater(len(self.audit[key]), 0, key)

    def test_conclusion_is_that_a_small_connection_alone_is_not_enough(self):
        conclusion = self.audit[
            "can_the_remaining_gap_be_closed_by_a_small_connection_alone"]
        self.assertTrue(conclusion.startswith("No."))


class RealCoreRetrievalAndCandidateChainRegressionTests(unittest.TestCase):
    """Confirms, against a real Core instance, that retrieval and the
    CorrectionApplicationCandidate chain genuinely work end to end on
    data Prompt 562's own write path produces - using no new logic of
    this prompt's own."""

    def _fresh_core(self):
        tmpdir = tempfile.TemporaryDirectory()
        self._tmpdirs.append(tmpdir)
        db_path = os.path.join(tmpdir.name, "test_memory.sqlite3")
        return Core(memory_db_path=db_path)

    def setUp(self):
        self._tmpdirs = []
        self.core = self._fresh_core()

    def tearDown(self):
        for tmpdir in self._tmpdirs:
            tmpdir.cleanup()

    def _store_a_real_correction(self):
        reply = self.core.process_input("not car, I mean bus")
        self.assertEqual(
            reply,
            "[CORRECTION ACKNOWLEDGED]\n"
            "original_expression: car\n"
            "corrected_expression: bus\n"
            "language: english",
        )
        self.assertIsNotNone(self.core.last_correction_learning_handoff_result)
        self.assertTrue(self.core.last_correction_learning_handoff_result.accepted)

    def test_stored_correction_is_readable_through_existing_retrieval(self):
        self._store_a_real_correction()
        lookup_result = lookup_correction_learning_input_by_original_expression_with_result(
            self.core.language_learning, "car")
        self.assertEqual(lookup_result.status, LOOKUP_STATUS_FOUND)
        self.assertEqual(len(lookup_result.records), 1)
        record = lookup_result.records[0]
        self.assertEqual(record["key"], "car")
        self.assertEqual(record["meaning"], "bus")
        self.assertEqual(record["language"], "english")

    def test_full_chain_produces_a_valid_candidate_from_real_data(self):
        self._store_a_real_correction()
        lookup_result = lookup_correction_learning_input_by_original_expression_with_result(
            self.core.language_learning, "car")
        context = build_correction_lookup_context(lookup_result)
        selection = select_unique_stored_correction(context)
        self.assertEqual(selection.outcome, OUTCOME_SELECTED)
        candidate = build_correction_application_candidate(selection)
        self.assertTrue(candidate.is_valid)
        self.assertEqual(candidate.original_expression, "car")
        self.assertEqual(candidate.corrected_expression_or_meaning, "bus")
        self.assertEqual(candidate.language, "english")

    def test_no_stored_correction_yields_not_found_not_a_fabricated_candidate(self):
        # Nothing stored yet in this fresh Core - the exact_lookup
        # result must be the existing NOT_FOUND outcome, and the
        # resulting candidate must be invalid, not fabricated.
        lookup_result = lookup_correction_learning_input_by_original_expression_with_result(
            self.core.language_learning, "car")
        self.assertNotEqual(lookup_result.status, LOOKUP_STATUS_FOUND)
        context = build_correction_lookup_context(lookup_result)
        selection = select_unique_stored_correction(context)
        candidate = build_correction_application_candidate(selection)
        self.assertFalse(candidate.is_valid)
        self.assertIsNone(candidate.original_expression)

    def test_candidate_chain_is_still_never_triggered_automatically(self):
        """The central Prompt 563 finding, reconfirmed after Prompt
        564: Prompt 564 added the missing `correction_application_
        candidate` field/parameter this test previously found absent
        (see docs/section2_correction_retrieval_application_audit_
        prompt563.md, "missing foundation" item 2) - but only that
        data path. Even with a real stored correction available,
        nothing in Core.process_input() computes or attaches a
        CorrectionApplicationCandidate on its own: the field exists
        now, and is still always None."""
        self._store_a_real_correction()
        self.core.process_input("what about car")
        self.assertIsNone(
            getattr(self.core.last_language_understanding,
                    "correction_application_candidate", _ABSENT),
        )
        self.assertIsNone(
            getattr(self.core.last_language_understanding,
                    "correction_lookup_context", "<missing-attr>"))

    def test_ordinary_conversation_after_a_stored_correction_is_unaffected(self):
        """A stored correction sitting in the learning store must not
        change how Core answers an unrelated later message - since
        nothing reads it back automatically, this is the expected
        (pre-existing) fallback behavior, not new behavior added here."""
        self._store_a_real_correction()
        other_core = self._fresh_core()
        reply_with_stored_correction = self.core.process_input("tell me about dogs")
        reply_without = other_core.process_input("tell me about dogs")
        self.assertEqual(reply_with_stored_correction, reply_without)

    def test_repeated_audit_run_against_fresh_core_instances_is_deterministic(self):
        first = self._fresh_core()
        second = self._fresh_core()
        first.process_input("not car, I mean bus")
        second.process_input("not car, I mean bus")
        first_lookup = lookup_correction_learning_input_by_original_expression_with_result(
            first.language_learning, "car")
        second_lookup = lookup_correction_learning_input_by_original_expression_with_result(
            second.language_learning, "car")
        self.assertEqual(
            {k: v for k, v in first_lookup.records[0].items()
             if k not in ("id", "created_at", "updated_at")},
            {k: v for k, v in second_lookup.records[0].items()
             if k not in ("id", "created_at", "updated_at")},
        )


if __name__ == "__main__":
    unittest.main()
