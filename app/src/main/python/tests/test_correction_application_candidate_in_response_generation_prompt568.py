"""
Tests for Prompt 568 - Expose Correction Candidate to Response
Generation Safely.

Prompt 567 connected the Prompt 566 trigger to the Prompt 565 adapter,
so a real, already-produced `LanguageUnderstandingResult` can carry a
real `CorrectionApplicationCandidate` (`understanding.
correction_application_candidate`) on the real conversation path. Prompt
471 separately taught `ResponseGenerationContext`
(response_generation_context.py) to carry a candidate all the way
through, via `build_generation_context(..., correction_application_
candidate=...)` and the module-level `generation_context_from_
understanding()`.

This audit found the one place those two existing pieces were not yet
connected: `ResponseGenerationRequest._generation_context_object()`
(response_generation.py) - the method behind the `.generation_context`
and `.selected_response_target` properties, and the one
`build_response_generation_outcome()` (response_generation_outcome.py)
itself reads through `request.generation_context` - built its
`ResponseGenerationContext` without forwarding `understanding.
correction_application_candidate` at all, so `ResponseGenerationRequest(
understanding).generation_context["correction_application_candidate"]`
silently stayed `None` even when `understanding` carried a real
candidate. Prompt 568 adds exactly that one missing keyword argument -
no new class, no new field, no new pipeline stage, and no new
detection/retrieval/trigger anywhere.

Covers Prompt 568 section 7's fifteen items:
    1. A real candidate from Prompt 567 reaches the response-generation
       context.
    2. The exact candidate data is preserved.
    3. `None` remains `None` when no candidate exists.
    4. No additional correction retrieval occurs during propagation.
    5. No additional correction selection occurs during propagation.
    6. Response generation does not automatically apply the candidate.
    7. Existing correction acknowledgement remains unchanged.
    8. Ordinary non-correction messages behave exactly as before.
    9. Ambiguous corrections remain safe.
    10. Unresolved corrections remain safe.
    11. Existing Prompt 565 tests remain passing (run unmodified as
        part of the full suite).
    12. Existing Prompt 566 tests remain passing (ditto).
    13. Existing Prompt 567 tests remain passing (ditto).
    14. Repeated equivalent operations remain deterministic.
    15. Existing response-generation tests remain passing (ditto).

Run directly:
    python -m unittest tests.test_correction_application_candidate_in_response_generation_prompt568 -v
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
from language_intelligence.response_generation import ResponseGenerationRequest
from language_intelligence.response_generation_context import (
    generation_context_from_understanding,
)
from language_intelligence.correction_application_candidate import (
    CorrectionApplicationCandidate,
)
from language_intelligence.correction_understanding import (
    build_correction_understanding,
    STATUS_AMBIGUOUS,
    STATUS_UNRESOLVED,
)
from language_intelligence.language_understanding_result import LanguageUnderstandingResult
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
    """Seed `store` through the EXISTING chain - the same one
    `Core._store_resolved_correction_learning` itself uses - never a
    synthetic row inserted directly. Mirrors
    test_correction_retrieval_trigger_connection_prompt567.py's own
    helper exactly."""
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
    """Same convention as test_correction_retrieval_trigger_connection_
    prompt567.py's own helper - wrap, still delegate, count calls."""
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
# 1 & 2: a real candidate produced by the real Prompt 567 conversation
# path reaches the response-generation context, with its exact data
# preserved.
# ----------------------------------------------------------------------
class TestRealCandidateReachesResponseGenerationContext(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_generation_context_property_carries_the_real_candidate(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        self.assertIsInstance(
            understanding.correction_application_candidate, CorrectionApplicationCandidate)

        context = ResponseGenerationRequest(understanding).generation_context
        self.assertIsNotNone(context)
        self.assertIsNotNone(context["correction_application_candidate"])

    def test_module_level_helper_agrees_with_the_request_property(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")

        via_request = ResponseGenerationRequest(understanding).generation_context
        via_module = generation_context_from_understanding(understanding).to_dict()
        self.assertEqual(
            via_request["correction_application_candidate"],
            via_module["correction_application_candidate"],
        )

    def test_exact_candidate_fields_are_preserved(self):
        _store_a_correction(
            self.core.language_learning, "teh", "the", confidence=0.75, locale="en-US")
        understanding = self.core.understand_language("not teh, I mean the.")
        expected = understanding.correction_application_candidate.to_dict()

        context = ResponseGenerationRequest(understanding).generation_context
        carried = context["correction_application_candidate"]

        self.assertEqual(carried, expected)
        self.assertEqual(carried["original_expression"], "teh")
        self.assertEqual(carried["corrected_expression_or_meaning"], "the")
        self.assertEqual(carried["confidence"], 0.75)
        self.assertTrue(carried["is_valid"])

    def test_generate_response_outcome_reads_a_consistent_generation_context(self):
        # generate_response_outcome() ultimately builds its outcome from
        # the SAME ResponseGenerationRequest.generation_context this test
        # exercises directly (response_generation_outcome.py's own
        # _language_and_locale()) - exercised here end-to-end through
        # Core, never a second, competing computation.
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        outcome = self.core.language_intelligence.generate_response_outcome(
            understanding, context=self.core.context)
        self.assertIsNotNone(outcome)
        # The outcome itself is deliberately bounded (language/locale/
        # status only - see response_generation_outcome.py) and never
        # raises just because a candidate is present.
        self.assertIn(outcome.status, ("SUCCESS", "FALLBACK", "FAILED", "UNRESOLVED"))


# ----------------------------------------------------------------------
# 3: None remains None when no candidate exists.
# ----------------------------------------------------------------------
class TestNoneRemainsNoneWithoutACandidate(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_ordinary_message_produces_no_candidate_in_context(self):
        understanding = self.core.understand_language("hello there, how are you?")
        self.assertIsNone(understanding.correction_application_candidate)
        context = ResponseGenerationRequest(understanding).generation_context
        self.assertIsNone(context["correction_application_candidate"])

    def test_resolved_correction_with_nothing_stored_produces_none(self):
        understanding = self.core.understand_language("not dgo, I mean dog.")
        self.assertIsNone(understanding.correction_application_candidate)
        context = ResponseGenerationRequest(understanding).generation_context
        self.assertIsNone(context["correction_application_candidate"])


# ----------------------------------------------------------------------
# 4 & 5: no additional correction retrieval/selection occurs while
# propagating the candidate to response generation - it is computed
# exactly once, upstream, by Core._attach_correction_application_
# candidate() (Prompt 567); building the response-generation context
# only ever reads the attribute already set.
# ----------------------------------------------------------------------
class TestNoExtraRetrievalOrSelectionDuringPropagation(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_building_the_response_generation_context_performs_no_retrieval(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")

        call_count, restore = _wrap_and_count(
            adapter_module, "build_correction_application_candidate_from_store")
        try:
            ResponseGenerationRequest(understanding).generation_context
            generation_context_from_understanding(understanding)
            self.core.language_intelligence.generate_response_outcome(
                understanding, context=self.core.context)
        finally:
            restore()
        self.assertEqual(call_count[0], 0)

    def test_building_the_response_generation_context_performs_no_selection(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")

        call_count, restore = _wrap_and_count(
            adapter_module, "select_unique_stored_correction")
        try:
            ResponseGenerationRequest(understanding).generation_context
            generation_context_from_understanding(understanding)
        finally:
            restore()
        self.assertEqual(call_count[0], 0)

    def test_end_to_end_process_input_performs_exactly_one_retrieval(self):
        # process_input() drives understanding AND response generation
        # together (Prompt 402/567) - the whole turn still performs
        # exactly one retrieval, not one per stage.
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        call_count, restore = _wrap_and_count(
            core_module, "retrieve_and_attach_correction_application_candidate")
        try:
            self.core.process_input("not dgo, I mean dog.")
        finally:
            restore()
        self.assertEqual(call_count[0], 1)


# ----------------------------------------------------------------------
# 6: response generation never automatically applies the candidate -
# the generated/deferred outcome, and the rest of the generation
# context, are identical whether or not a candidate is present.
# ----------------------------------------------------------------------
class TestNoAutomaticApplication(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_original_message_is_never_replaced_by_the_candidate(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        context = ResponseGenerationRequest(understanding).generation_context
        self.assertEqual(context["original_message"], "not dgo, I mean dog.")
        self.assertNotEqual(context["original_message"], "dog")

    def test_response_action_and_rendering_unaffected_by_candidate_presence(self):
        # SAME understanding (SAME response_plan, SAME learning-store
        # state) both times - only the one attribute this prompt's fix
        # forwards differs, isolating exactly what the candidate's mere
        # presence can and cannot change.
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        self.assertIsNotNone(understanding.correction_application_candidate)

        with_context = ResponseGenerationRequest(understanding).generation_context

        original_candidate = understanding.correction_application_candidate
        understanding.correction_application_candidate = None
        try:
            without_context = ResponseGenerationRequest(understanding).generation_context
        finally:
            understanding.correction_application_candidate = original_candidate

        self.assertIsNotNone(with_context["correction_application_candidate"])
        self.assertIsNone(without_context["correction_application_candidate"])
        for key in ("original_message", "status", "response_action", "meaning",
                    "meaning_candidates", "matched_pattern", "variables",
                    "language_guidance", "response_pattern_selection",
                    "response_pattern_binding", "response_pattern_rendering"):
            self.assertEqual(
                with_context[key], without_context[key],
                msg=f"{key!r} differed when only the candidate's presence differed")

    def test_generate_response_still_defers_with_a_candidate_present(self):
        # Today's only configured backend never generates text - a
        # candidate being present must not change that.
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        result = self.core.language_intelligence.generate_response(
            understanding, context=self.core.context)
        self.assertEqual(result.status, "deferred_to_existing_pipeline")
        self.assertIsNone(result.response_text)


# ----------------------------------------------------------------------
# 7 & 8: existing correction acknowledgement and ordinary conversation
# are both completely unaffected.
# ----------------------------------------------------------------------
class TestAcknowledgementAndOrdinaryMessagesUnaffected(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_acknowledgement_reply_unchanged_with_a_stored_match(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        reply = self.core.process_input("not dgo, I mean dog.")
        self.assertIn("original_expression: dgo", reply)
        self.assertIn("corrected_expression: dog", reply)

    def test_acknowledgement_reply_unchanged_without_a_stored_match(self):
        reply = self.core.process_input("not dgo, I mean dog.")
        self.assertIn("original_expression: dgo", reply)
        self.assertIn("corrected_expression: dog", reply)

    def test_ordinary_conversation_reply_identical_regardless_of_candidate_plumbing(self):
        no_candidate_core, tmp = _make_core()
        try:
            reply_a = self.core.process_input("Hello, how are you today?")
            reply_b = no_candidate_core.process_input("Hello, how are you today?")
            self.assertEqual(reply_a, reply_b)
        finally:
            tmp.cleanup()


# ----------------------------------------------------------------------
# 9 & 10: AMBIGUOUS/UNRESOLVED correction understanding never reaches
# response generation with a candidate attached.
# ----------------------------------------------------------------------
class TestAmbiguousAndUnresolvedStaySafe(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_ambiguous_understanding_produces_no_candidate_in_context(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        ambiguous = build_correction_understanding(
            "not dgo, I mean dog or doge",
            original_expression="dgo",
            corrected_candidates=["dog", "doge"])
        self.assertEqual(ambiguous.status, STATUS_AMBIGUOUS)
        understanding = _minimal_result(ambiguous.to_dict())
        self.core._attach_correction_application_candidate(understanding)

        self.assertIsNone(understanding.correction_application_candidate)
        # _minimal_result() carries no response_plan (it is built
        # directly, not through the full pipeline), so there is no
        # generation context to build at all - confirming the field is
        # never conjured up from nowhere: no plan, no context, and
        # certainly no candidate.
        context = ResponseGenerationRequest(understanding).generation_context
        self.assertIsNone(context)

    def test_unresolved_understanding_produces_no_candidate_in_context(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        unresolved = build_correction_understanding("not dgo", original_expression="dgo")
        self.assertEqual(unresolved.status, STATUS_UNRESOLVED)
        understanding = _minimal_result(unresolved.to_dict())
        self.core._attach_correction_application_candidate(understanding)

        self.assertIsNone(understanding.correction_application_candidate)
        context = ResponseGenerationRequest(understanding).generation_context
        self.assertIsNone(context)


# ----------------------------------------------------------------------
# 14: repeated equivalent operations remain deterministic.
# ----------------------------------------------------------------------
class TestDeterminism(unittest.TestCase):
    def setUp(self):
        self.core, self._tmpdir = _make_core()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_repeated_generation_context_builds_are_equal(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        understanding = self.core.understand_language("not dgo, I mean dog.")
        first = ResponseGenerationRequest(understanding).generation_context
        second = ResponseGenerationRequest(understanding).generation_context
        self.assertEqual(first, second)

    def test_repeated_end_to_end_turns_are_equal(self):
        _store_a_correction(self.core.language_learning, "dgo", "dog")
        first_understanding = self.core.understand_language("not dgo, I mean dog.")
        first = ResponseGenerationRequest(first_understanding).generation_context
        second_understanding = self.core.understand_language("not dgo, I mean dog.")
        second = ResponseGenerationRequest(second_understanding).generation_context
        self.assertEqual(
            first["correction_application_candidate"],
            second["correction_application_candidate"],
        )


if __name__ == "__main__":
    unittest.main()
