"""
Tests for Prompt 526 - Validate Selected Section Metadata.

`validate_learned_knowledge_diagnostic_report()` (Prompt 514, extended by
Prompts 522 and 525's coverage of the filtered trend) can now also be
handed `selected_sections` metadata - a dict with the four lists Prompt
516's section filter uses (`requested_sections`, `included_sections`,
`unavailable_sections`, `unknown_sections`) - and verifies it:

  * that the four lists are internally consistent (every requested name
    lands in exactly one of included / unavailable / unknown, nothing is
    listed that was not requested, nothing appears twice, and no section
    is both included and unavailable);
  * that an *included* section really has data in the report;
  * that an *unavailable* section is not in fact present and valid in the
    report; and
  * that unknown (not a section of the report at all) and unavailable (a
    real section without data) stay distinct.

The selectable sections are the report's own, including the Prompt 522
filtered `filtered_trend` / `filtered_trend_validation` sections. No
production behaviour changes when `selected_sections` is not given.

Run directly:
    python -m unittest tests.test_learned_knowledge_selected_sections_validation -v
"""

import copy
import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from learning.learned_knowledge_gate import (
    STATUS_PASSED, REASON_OK,
    LearnedKnowledgeGateResult, build_learned_knowledge_gate_trace,
)
from learning.learned_knowledge_statistics import (
    LearnedKnowledgeDecisionStatistics,
    LearnedKnowledgeDiagnosticSnapshotHistory,
    LearnedKnowledgeFilteredSummarySnapshotHistory,
    build_learned_knowledge_diagnostic_report as report,
    validate_learned_knowledge_diagnostic_report as validate,
    filter_learned_knowledge_diagnostic_summary as filt,
    format_learned_knowledge_diagnostic_summary as fmt,
    compare_learned_knowledge_filtered_summary_snapshots as compare,
)

OK = {"valid": True, "well_formed": True, "errors": [], "warnings": []}
_BASE_SECTIONS = ["snapshots", "comparison", "comparison_validation", "trend", "trend_validation"]
_FILTERED_SECTIONS = ["filtered_trend", "filtered_trend_validation"]
_ALL_SECTIONS = _BASE_SECTIONS + _FILTERED_SECTIONS
_SUMMARY_ALL = ["evaluation_counts", "rates", "dominant_rejection_reason",
                "comparison_changes", "trend", "validation_statuses"]

_ACCEPTED = build_learned_knowledge_gate_trace(LearnedKnowledgeGateResult(STATUS_PASSED, REASON_OK))


def _stats(accepted):
    stats = LearnedKnowledgeDecisionStatistics()
    for _ in range(accepted):
        stats.record(_ACCEPTED)
    return stats


def _base_pipeline(steps=(1, 2, 4)):
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    for accepted in steps:
        history.record_statistics(_stats(accepted))
    comparisons = [history.compare_sequences(i, i + 1) for i in range(1, len(steps))]
    return history, comparisons


def _filtered_summary(accepted):
    history = LearnedKnowledgeDiagnosticSnapshotHistory()
    for count in (1, accepted):
        history.record_statistics(_stats(count))
    comparisons = [history.compare_sequences(1, 2)]
    built = report(snapshots=history, comparisons=comparisons)
    return fmt(built, validate(built, snapshots=history, comparisons=comparisons))


def _filtered_comparisons(totals=(1, 2, 5)):
    history = LearnedKnowledgeFilteredSummarySnapshotHistory()
    snaps = [history.record_filtered_summary(filt(_filtered_summary(n), _SUMMARY_ALL))
             for n in totals]
    return [compare(snaps[i], snaps[i + 1]) for i in range(len(snaps) - 1)]


def _full_report():
    """Every one of the seven selectable sections present with real data."""
    history, comparisons = _base_pipeline()
    return report(snapshots=history, comparisons=comparisons,
                  filtered_comparisons=_filtered_comparisons())


def _snapshots_only_report():
    """Only `snapshots` has data (no filtered fields at all)."""
    history, _ = _base_pipeline()
    return report(snapshots=history)


def _selection(requested=(), included=(), unavailable=(), unknown=()):
    return {
        "requested_sections": list(requested),
        "included_sections": list(included),
        "unavailable_sections": list(unavailable),
        "unknown_sections": list(unknown),
    }


class Prompt526TestCase(unittest.TestCase):
    def assert_selection_valid(self, built, selection, **sources):
        result = validate(built, selected_sections=selection, **sources)
        self.assertEqual(result, OK, result)

    def selection_errors(self, built, selection):
        """The errors validation adds for `selection` alone (the report
        itself must be valid on its own, so nothing else is in there)."""
        self.assertEqual(validate(built), OK)
        result = validate(built, selected_sections=selection)
        self.assertFalse(result["valid"], result)
        self.assertTrue(result["well_formed"], result)
        return result["errors"]


# ----------------------------------------------------------------------
# 1. valid selected-section metadata
# ----------------------------------------------------------------------
class ValidSelectedSectionMetadataTests(Prompt526TestCase):

    def test_consistent_metadata_is_valid(self):
        built = _snapshots_only_report()
        selection = _selection(
            requested=["snapshots", "trend", "bogus"],
            included=["snapshots"], unavailable=["trend"], unknown=["bogus"])
        self.assert_selection_valid(built, selection)

    def test_empty_selection_is_valid(self):
        self.assert_selection_valid(_full_report(), _selection())

    def test_selecting_every_section_of_a_full_report_is_valid(self):
        self.assert_selection_valid(
            _full_report(), _selection(requested=_ALL_SECTIONS, included=_ALL_SECTIONS))

    def test_valid_with_sources_given_too(self):
        history, comparisons = _base_pipeline()
        built = report(snapshots=history, comparisons=comparisons)
        self.assert_selection_valid(
            built, _selection(requested=_BASE_SECTIONS, included=_BASE_SECTIONS),
            snapshots=history, comparisons=comparisons)

    def test_extra_keys_in_the_metadata_are_not_judged(self):
        selection = _selection(requested=["snapshots"], included=["snapshots"])
        selection["summary_text"] = "anything"
        selection["report_validity"] = "valid"
        self.assert_selection_valid(_full_report(), selection)

    def test_not_giving_selected_sections_checks_nothing_about_selection(self):
        for built in (_full_report(), _snapshots_only_report()):
            self.assertEqual(validate(built), OK)
        broken = copy.deepcopy(_full_report())
        del broken["trend"]
        result = validate(broken)
        self.assertFalse(result["valid"])
        self.assertFalse(any("selected_sections" in error for error in result["errors"]))


# ----------------------------------------------------------------------
# 2. included section
# ----------------------------------------------------------------------
class IncludedSectionTests(Prompt526TestCase):

    def test_included_section_with_data_is_valid(self):
        for name in _ALL_SECTIONS:
            with self.subTest(section=name):
                self.assert_selection_valid(
                    _full_report(), _selection(requested=[name], included=[name]))

    def test_included_section_that_was_not_requested_is_flagged(self):
        errors = self.selection_errors(
            _full_report(), _selection(requested=[], included=["snapshots"]))
        self.assertEqual(errors, ["section_not_requested:included:snapshots"])

    def test_included_name_that_is_not_a_report_section_is_flagged(self):
        errors = self.selection_errors(
            _full_report(), _selection(requested=["rates"], included=["rates"]))
        self.assertEqual(errors, ["unknown_section_marked_included:rates"])

    def test_included_name_is_matched_exactly_and_case_sensitively(self):
        errors = self.selection_errors(
            _full_report(), _selection(requested=["Snapshots"], included=["Snapshots"]))
        self.assertEqual(errors, ["unknown_section_marked_included:Snapshots"])

    def test_non_string_included_name_is_flagged_without_crashing(self):
        errors = self.selection_errors(
            _full_report(), _selection(requested=[7], included=[7]))
        self.assertEqual(errors, ["unknown_section_marked_included:7"])


# ----------------------------------------------------------------------
# 3. unavailable section
# ----------------------------------------------------------------------
class UnavailableSectionTests(Prompt526TestCase):

    def test_genuinely_unavailable_sections_are_valid_as_unavailable(self):
        built = _snapshots_only_report()
        unavailable = ["comparison", "comparison_validation", "trend", "trend_validation"]
        self.assert_selection_valid(
            built, _selection(requested=["snapshots"] + unavailable,
                              included=["snapshots"], unavailable=unavailable))

    def test_filtered_sections_missing_from_a_plain_report_are_unavailable_not_unknown(self):
        built = _snapshots_only_report()
        self.assertNotIn("filtered_trend", built)
        self.assert_selection_valid(
            built, _selection(requested=_FILTERED_SECTIONS, unavailable=_FILTERED_SECTIONS))

    def test_present_and_valid_section_marked_unavailable_is_flagged(self):
        for name in _ALL_SECTIONS:
            with self.subTest(section=name):
                errors = self.selection_errors(
                    _full_report(), _selection(requested=[name], unavailable=[name]))
                self.assertEqual(errors, ["unavailable_section_present:%s" % name])

    def test_unavailable_section_that_was_not_requested_is_flagged(self):
        errors = self.selection_errors(
            _snapshots_only_report(), _selection(requested=[], unavailable=["trend"]))
        self.assertEqual(errors, ["section_not_requested:unavailable:trend"])

    def test_unavailable_name_that_is_not_a_report_section_is_flagged(self):
        errors = self.selection_errors(
            _snapshots_only_report(), _selection(requested=["bogus"], unavailable=["bogus"]))
        self.assertEqual(errors, ["unknown_section_marked_unavailable:bogus"])

    def test_present_but_invalid_section_marked_unavailable_is_not_flagged_again(self):
        # The section's own problem is the report's error to report; this
        # check only objects to a section that is present AND valid.
        built = copy.deepcopy(_full_report())
        del built["snapshots"]["latest"]["total_evaluations"]
        report_errors = validate(built)["errors"]
        self.assertTrue(report_errors)
        result = validate(
            built, selected_sections=_selection(requested=["snapshots"], unavailable=["snapshots"]))
        self.assertEqual(result["errors"], report_errors)

    def test_unavailable_validation_section_that_is_present_and_valid_is_flagged(self):
        history, comparisons = _base_pipeline()
        built = report(snapshots=history, comparisons=comparisons)
        errors = self.selection_errors(
            built, _selection(requested=["trend_validation"], unavailable=["trend_validation"]))
        self.assertEqual(errors, ["unavailable_section_present:trend_validation"])


# ----------------------------------------------------------------------
# 4. unknown section
# ----------------------------------------------------------------------
class UnknownSectionTests(Prompt526TestCase):

    def test_unknown_names_are_valid_as_unknown(self):
        self.assert_selection_valid(
            _full_report(),
            _selection(requested=["bogus", "rates", 3], unknown=["bogus", "rates", 3]))

    def test_summary_vocabulary_names_are_unknown_to_the_report(self):
        # `"trend"` is the one name Prompt 515/516 share with the report.
        names = [name for name in _SUMMARY_ALL if name != "trend"]
        self.assert_selection_valid(
            _full_report(), _selection(requested=names, unknown=names))

    def test_real_section_marked_unknown_is_flagged(self):
        errors = self.selection_errors(
            _full_report(), _selection(requested=["trend"], unknown=["trend"]))
        self.assertEqual(errors, ["known_section_marked_unknown:trend"])

    def test_real_but_unavailable_section_marked_unknown_is_flagged(self):
        # Unknown and unavailable stay distinct: a real section with no
        # data is unavailable, never unknown.
        errors = self.selection_errors(
            _snapshots_only_report(), _selection(requested=["trend"], unknown=["trend"]))
        self.assertEqual(errors, ["known_section_marked_unknown:trend"])

    def test_unknown_name_that_was_not_requested_is_flagged(self):
        errors = self.selection_errors(
            _full_report(), _selection(requested=[], unknown=["bogus"]))
        self.assertEqual(errors, ["section_not_requested:unknown:bogus"])

    def test_unknown_and_unavailable_are_judged_independently(self):
        built = _snapshots_only_report()
        self.assert_selection_valid(built, _selection(
            requested=["trend", "bogus"], unavailable=["trend"], unknown=["bogus"]))
        errors = self.selection_errors(built, _selection(
            requested=["trend", "bogus"], unavailable=["bogus"], unknown=["trend"]))
        self.assertEqual(errors, [
            "unknown_section_marked_unavailable:bogus", "known_section_marked_unknown:trend"])


# ----------------------------------------------------------------------
# 5. contradictory included / unavailable states
# ----------------------------------------------------------------------
class ContradictoryStateTests(Prompt526TestCase):

    def test_section_both_included_and_unavailable_is_flagged(self):
        errors = self.selection_errors(
            _snapshots_only_report(),
            _selection(requested=["trend"], included=["trend"], unavailable=["trend"]))
        self.assertIn("section_included_and_unavailable:trend", errors)

    def test_contradiction_on_a_section_with_data_is_flagged_alongside_presence(self):
        errors = self.selection_errors(
            _full_report(),
            _selection(requested=["trend"], included=["trend"], unavailable=["trend"]))
        self.assertEqual(errors, [
            "section_included_and_unavailable:trend", "unavailable_section_present:trend"])

    def test_contradiction_is_flagged_once_per_section_even_when_listed_twice(self):
        errors = self.selection_errors(
            _snapshots_only_report(),
            _selection(requested=["trend"], included=["trend", "trend"],
                       unavailable=["trend", "trend"]))
        self.assertEqual(errors.count("section_included_and_unavailable:trend"), 1)

    def test_section_listed_included_and_unknown_is_flagged(self):
        errors = self.selection_errors(
            _full_report(),
            _selection(requested=["trend"], included=["trend"], unknown=["trend"]))
        self.assertEqual(errors, ["known_section_marked_unknown:trend"])

    def test_filtered_section_both_included_and_unavailable_is_flagged(self):
        errors = self.selection_errors(
            _full_report(),
            _selection(requested=["filtered_trend"], included=["filtered_trend"],
                       unavailable=["filtered_trend"]))
        self.assertIn("section_included_and_unavailable:filtered_trend", errors)


# ----------------------------------------------------------------------
# 6. missing corresponding section data
# ----------------------------------------------------------------------
class MissingSectionDataTests(Prompt526TestCase):

    def test_included_section_that_is_unavailable_in_the_report_is_flagged(self):
        errors = self.selection_errors(
            _snapshots_only_report(), _selection(requested=["trend"], included=["trend"]))
        self.assertEqual(errors, ["included_section_without_data:trend"])

    def test_included_section_absent_from_the_report_is_flagged(self):
        broken = copy.deepcopy(_full_report())
        del broken["comparison"]
        result = validate(
            broken, selected_sections=_selection(requested=["comparison"], included=["comparison"]))
        self.assertIn("included_section_without_data:comparison", result["errors"])
        self.assertIn("missing_field:comparison", result["errors"])

    def test_included_section_with_null_payload_is_flagged(self):
        broken = copy.deepcopy(_full_report())
        broken["trend"]["summary"] = None
        result = validate(
            broken, selected_sections=_selection(requested=["trend"], included=["trend"]))
        self.assertIn("included_section_without_data:trend", result["errors"])

    def test_included_section_marked_not_available_is_flagged(self):
        broken = copy.deepcopy(_full_report())
        broken["trend"]["available"] = False
        result = validate(
            broken, selected_sections=_selection(requested=["trend"], included=["trend"]))
        self.assertIn("included_section_without_data:trend", result["errors"])

    def test_included_validation_section_without_a_result_is_flagged(self):
        built = _snapshots_only_report()
        errors = self.selection_errors(
            built, _selection(requested=["comparison_validation"],
                              included=["comparison_validation"]))
        self.assertEqual(errors, ["included_section_without_data:comparison_validation"])

    def test_every_missing_section_is_reported_in_request_order(self):
        errors = self.selection_errors(
            _snapshots_only_report(),
            _selection(requested=["trend", "comparison", "snapshots"],
                       included=["trend", "comparison", "snapshots"]))
        self.assertEqual(errors, [
            "included_section_without_data:trend", "included_section_without_data:comparison"])

    def test_requested_section_in_no_list_is_flagged(self):
        errors = self.selection_errors(
            _full_report(), _selection(requested=["snapshots", "trend"], included=["snapshots"]))
        self.assertEqual(errors, ["requested_section_unaccounted:trend"])


# ----------------------------------------------------------------------
# 7. filtered diagnostic section metadata
# ----------------------------------------------------------------------
class FilteredSectionMetadataTests(Prompt526TestCase):

    def test_filtered_sections_included_when_the_report_carries_them(self):
        self.assert_selection_valid(
            _full_report(), _selection(requested=_FILTERED_SECTIONS, included=_FILTERED_SECTIONS))

    def test_filtered_sections_unavailable_when_built_without_data(self):
        built = report(filtered_comparisons=None, filtered_trend_summary=None)
        self.assertIn("filtered_trend", built)
        self.assert_selection_valid(
            built, _selection(requested=_FILTERED_SECTIONS, unavailable=_FILTERED_SECTIONS))

    def test_filtered_sections_included_without_data_are_flagged(self):
        built = report(filtered_comparisons=None, filtered_trend_summary=None)
        errors = self.selection_errors(
            built, _selection(requested=_FILTERED_SECTIONS, included=_FILTERED_SECTIONS))
        self.assertEqual(errors, [
            "included_section_without_data:filtered_trend",
            "included_section_without_data:filtered_trend_validation"])

    def test_filtered_sections_included_on_a_report_without_the_fields_are_flagged(self):
        errors = self.selection_errors(
            _snapshots_only_report(),
            _selection(requested=_FILTERED_SECTIONS, included=_FILTERED_SECTIONS))
        self.assertEqual(errors, [
            "included_section_without_data:filtered_trend",
            "included_section_without_data:filtered_trend_validation"])

    def test_filtered_sections_present_and_valid_marked_unavailable_are_flagged(self):
        errors = self.selection_errors(
            _full_report(),
            _selection(requested=_FILTERED_SECTIONS, unavailable=_FILTERED_SECTIONS))
        self.assertEqual(errors, [
            "unavailable_section_present:filtered_trend",
            "unavailable_section_present:filtered_trend_validation"])

    def test_filtered_section_marked_unknown_is_flagged(self):
        errors = self.selection_errors(
            _full_report(),
            _selection(requested=["filtered_trend"], unknown=["filtered_trend"]))
        self.assertEqual(errors, ["known_section_marked_unknown:filtered_trend"])

    def test_filtered_look_alike_names_are_unknown(self):
        self.assert_selection_valid(
            _full_report(),
            _selection(requested=["filtered_snapshots", "filtered_comparison"],
                       unknown=["filtered_snapshots", "filtered_comparison"]))

    def test_mixed_base_and_filtered_selection_with_sources(self):
        history, comparisons = _base_pipeline()
        filtered = _filtered_comparisons()
        built = report(snapshots=history, comparisons=comparisons, filtered_comparisons=filtered)
        selection = _selection(
            requested=["snapshots", "filtered_trend", "rates"],
            included=["snapshots", "filtered_trend"], unknown=["rates"])
        self.assert_selection_valid(
            built, selection, snapshots=history, comparisons=comparisons,
            filtered_comparisons=filtered)


# ----------------------------------------------------------------------
# malformed metadata, duplicates, and the validator's own guarantees
# ----------------------------------------------------------------------
class MetadataShapeTests(Prompt526TestCase):

    def test_non_dict_metadata_is_flagged(self):
        for bad in (None, [], "snapshots", 7, ()):
            with self.subTest(bad=bad):
                errors = self.selection_errors(_full_report(), bad)
                self.assertEqual(errors, ["invalid_type:selected_sections"])

    def test_missing_lists_are_flagged_alone(self):
        errors = self.selection_errors(_full_report(), {"requested_sections": ["snapshots"]})
        self.assertEqual(errors, [
            "missing_field:selected_sections.included_sections",
            "missing_field:selected_sections.unavailable_sections",
            "missing_field:selected_sections.unknown_sections"])

    def test_non_list_fields_are_flagged(self):
        selection = _selection()
        selection["included_sections"] = "snapshots"
        selection["unknown_sections"] = None
        errors = self.selection_errors(_full_report(), selection)
        self.assertEqual(errors, [
            "invalid_type:selected_sections.included_sections",
            "invalid_type:selected_sections.unknown_sections"])

    def test_repeated_name_within_a_list_is_flagged(self):
        errors = self.selection_errors(
            _full_report(),
            _selection(requested=["snapshots", "snapshots"], included=["snapshots"]))
        self.assertEqual(errors, ["duplicate_section:requested_sections:snapshots"])

    def test_names_of_different_types_are_not_merged_as_duplicates(self):
        self.assert_selection_valid(
            _full_report(), _selection(requested=[1, 1.0, True], unknown=[1, 1.0, True]))

    def test_a_prompt_516_style_result_is_read_by_its_four_lists_only(self):
        # A real Prompt 516 result is in summary vocabulary, which the
        # report does not have - but its metadata shape is accepted as-is.
        filtered = filt(_filtered_summary(3), ["rates", "bogus"])
        self.assertEqual(filtered["included_sections"], ["rates"])
        result = validate(_full_report(), selected_sections=filtered)
        self.assertEqual(result["errors"], ["unknown_section_marked_included:rates"])


class ValidatorGuaranteeTests(Prompt526TestCase):

    def test_metadata_errors_come_after_the_reports_own_errors(self):
        broken = copy.deepcopy(_full_report())
        del broken["trend"]
        own = validate(broken)["errors"]
        combined = validate(
            broken, selected_sections=_selection(requested=["snapshots"], unavailable=["snapshots"])
        )["errors"]
        self.assertEqual(combined[:len(own)], own)
        self.assertEqual(combined[len(own):], ["unavailable_section_present:snapshots"])

    def test_well_formed_is_not_changed_by_bad_metadata(self):
        built = _full_report()
        result = validate(built, selected_sections=_selection(requested=["x"], included=["x"]))
        self.assertFalse(result["valid"])
        self.assertTrue(result["well_formed"])

    def test_never_mutates_the_report_or_the_metadata(self):
        built = _full_report()
        selection = _selection(
            requested=["snapshots", "trend", "bogus"], included=["snapshots", "trend"],
            unavailable=["trend"], unknown=["bogus"])
        built_before, selection_before = copy.deepcopy(built), copy.deepcopy(selection)
        validate(built, selected_sections=selection)
        self.assertEqual(built, built_before)
        self.assertEqual(selection, selection_before)

    def test_deterministic(self):
        built = _snapshots_only_report()
        selection = _selection(
            requested=["trend", "snapshots", "bogus", "filtered_trend"],
            included=["trend", "bogus"], unavailable=["snapshots", "trend"],
            unknown=["filtered_trend"])
        first = validate(built, selected_sections=selection)
        for _ in range(3):
            self.assertEqual(validate(built, selected_sections=copy.deepcopy(selection)), first)
        self.assertFalse(first["valid"])

    def test_non_dict_report_still_gets_the_existing_error(self):
        self.assertEqual(
            validate(None, selected_sections=_selection()),
            {"valid": False, "well_formed": False, "errors": ["report_not_a_dict"], "warnings": []})


if __name__ == "__main__":
    unittest.main()
