"""
Tests for Prompt 629 - Section 2: Language Intelligence and Request
Understanding - the FINAL public-state boundary: `Core`'s own exposed
"latest request" surface (`get_last_language_understanding()`,
`get_last_response_plan()`, `get_last_response_normalized_input()`,
`get_last_conversation_response()`) must always publish, replace, and
(where the existing `reset_context()` lifecycle says so) clear exactly
the current request's state - never a stale mix of a previous one.

Prompts 609-628 already covered field-level propagation (609-626),
one full hand-assembled lifecycle trace (627), and repeated/mixed
`Core.process_input` sequences including A->B->A->C and an unresolved
boundary (628). What none of those files does is:

  - assert the OBJECT-IDENTITY correspondence between these four public
    getters for one request (`get_last_response_plan() is
    get_last_language_understanding().response_plan`, etc.) - Prompt 627's
    integration test only checked value equality on this;
  - exercise `reset_context()` itself against this state, confirming
    the EXISTING, documented split: `last_response_normalized_input`
    (and `last_response_correction_usable`) reset to their safe
    defaults, while `last_language_understanding`/`get_last_response_
    plan()` keep their existing (unreset) behavior, exactly as Prompt
    613's own docstring already states - and that a fresh request after
    reset is still correctly, freshly published.

Finding: the architecture already guarantees this. `Core` stores each
request's understanding and derived state as plain attributes,
overwritten wholesale by the next request; `reset_context()` clears
only what its own docstring (Prompt 581/613) already promises. No
production changes were needed; this file adds focused regression
coverage only.

Run directly:
    python -m unittest tests.test_request_understanding_public_state_reset_boundary_prompt629 -v
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
from language_intelligence.response_planning import (
    STATUS_RESOLVED, STATUS_UNRESOLVED, ACTION_GREET, ACTION_PROVIDE_INFORMATION,
)
from language_intelligence.learned_pattern_teaching import STATUS_CREATED
from language_intelligence.learned_pattern_meaning import STATUS_BOUND, STATUS_ALREADY_BOUND


def _teach(core, pattern, meaning, language="en"):
    assert core.teach_sentence_pattern(language, pattern).status == STATUS_CREATED
    assert core.bind_pattern_meaning(language, pattern, meaning).status in (
        STATUS_BOUND, STATUS_ALREADY_BOUND)


def _make_core():
    tmp = tempfile.mkdtemp()
    return Core(memory_db_path=os.path.join(tmp, "core.db"),
                skill_definitions_dir=os.path.join(tmp, "skills"))


# ======================================================================
class TestPublicStateBelongsToTheExactRequest(unittest.TestCase):
    """After one successful request, every exposed public getter
    corresponds - by object identity, not just equality - to THAT
    request, both to each other and to a held reference."""

    def test_getters_correspond_by_identity_for_one_request(self):
        core = _make_core()
        _teach(core, "good morning", "greeting")
        core.process_input("good morning")

        u = core.get_last_language_understanding()
        held_normalized = u.normalized_input
        plan = core.get_last_response_plan()
        conv = core.get_last_conversation_response()
        published_normalized_input = core.get_last_response_normalized_input()

        # get_last_response_plan() IS the exact object living on the
        # understanding's own `response_plan` attribute.
        self.assertIs(plan, u.response_plan)
        # get_last_response_normalized_input() IS the exact string
        # object the understanding and the conversation response carry.
        self.assertIs(published_normalized_input, held_normalized)
        self.assertIs(conv.normalized_input, held_normalized)
        self.assertEqual(plan["status"], STATUS_RESOLVED)
        self.assertEqual(plan["response_action"], ACTION_GREET)


# ======================================================================
class TestNewRequestReplacesRatherThanMerges(unittest.TestCase):
    """A second request must fully REPLACE every one of these getters'
    published values - never merge fields from the first request into
    the second's."""

    def test_second_request_fully_replaces_first(self):
        core = _make_core()
        _teach(core, "good morning", "greeting")
        _teach(core, "what is {{topic}}", "ask_question")

        core.process_input("good morning")
        u1 = core.get_last_language_understanding()
        plan1 = core.get_last_response_plan()
        normalized1 = core.get_last_response_normalized_input()

        core.process_input("what is python")
        u2 = core.get_last_language_understanding()
        plan2 = core.get_last_response_plan()
        normalized2 = core.get_last_response_normalized_input()

        self.assertIsNot(u2, u1)
        self.assertIsNot(plan2, plan1)
        self.assertNotEqual(normalized2, normalized1)
        self.assertEqual(plan2["response_action"], ACTION_PROVIDE_INFORMATION)
        self.assertEqual(plan2["variables"], {"topic": "python"})
        # No leftover field from request 1 anywhere in request 2's plan.
        self.assertNotIn("greeting", str(plan2.get("meaning") or {}))
        # Request 1's own already-published state is untouched.
        self.assertEqual(plan1["response_action"], ACTION_GREET)
        self.assertEqual(normalized1, "good morning")


# ======================================================================
class TestFailureUnresolvedBoundaryPublicState(unittest.TestCase):
    """A successful request, an unresolved one, then a fresh successful
    recovery: every public getter after the boundary belongs only to
    the request that just ran."""

    def test_success_then_unresolved_then_recovery_public_state(self):
        core = _make_core()
        _teach(core, "good morning", "greeting")
        _teach(core, "what is {{topic}}", "ask_question")

        core.process_input("good morning")
        success_normalized = core.get_last_response_normalized_input()
        success_plan = core.get_last_response_plan()

        core.process_input("qwerty zzznoxyzzz unmapped concept")
        unresolved_plan = core.get_last_response_plan()
        unresolved_normalized = core.get_last_response_normalized_input()
        self.assertEqual(unresolved_plan["status"], STATUS_UNRESOLVED)
        self.assertIsNone(unresolved_plan["response_action"])
        self.assertEqual(unresolved_normalized, "qwerty zzznoxyzzz unmapped concept")
        # The prior success's state is untouched by the unresolved call.
        self.assertEqual(success_plan["response_action"], ACTION_GREET)
        self.assertEqual(success_normalized, "good morning")

        core.process_input("what is python")
        recovery_plan = core.get_last_response_plan()
        recovery_normalized = core.get_last_response_normalized_input()
        recovery_u = core.get_last_language_understanding()

        self.assertEqual(recovery_plan["status"], STATUS_RESOLVED)
        self.assertEqual(recovery_plan["response_action"], ACTION_PROVIDE_INFORMATION)
        self.assertEqual(recovery_normalized, "what is python")
        self.assertIs(recovery_plan, recovery_u.response_plan)
        # Recovery carries nothing from the unresolved call or the
        # earlier success.
        self.assertNotEqual(recovery_normalized, unresolved_normalized)
        self.assertNotEqual(recovery_normalized, success_normalized)
        # The unresolved call's own already-published state is unaffected.
        self.assertEqual(unresolved_plan["status"], STATUS_UNRESOLVED)


# ======================================================================
class TestResetContextExistingSplitBehavior(unittest.TestCase):
    """`reset_context()` already documents a specific split (Prompt
    581/613): `last_response_correction_usable` and
    `last_response_normalized_input` reset to their safe defaults;
    `last_language_understanding` / `get_last_response_plan()` keep
    their existing, UNRESET behavior. This locks that exact existing
    split down - it does not invent any new reset behavior."""

    def test_reset_clears_last_response_normalized_input_only(self):
        core = _make_core()
        _teach(core, "good morning", "greeting")
        core.process_input("good morning")

        self.assertEqual(core.get_last_response_normalized_input(), "good morning")
        u_before = core.get_last_language_understanding()
        plan_before = core.get_last_response_plan()

        core.reset_context()

        # Documented reset target: back to its safe default.
        self.assertIsNone(core.get_last_response_normalized_input())
        self.assertFalse(core.get_last_response_correction_usable())
        # Documented NON-reset targets: unchanged by reset_context().
        self.assertIs(core.get_last_language_understanding(), u_before)
        self.assertIs(core.get_last_response_plan(), plan_before)
        self.assertEqual(core.get_last_response_plan()["response_action"], ACTION_GREET)

    def test_fresh_request_after_reset_is_correctly_and_freshly_published(self):
        core = _make_core()
        _teach(core, "good morning", "greeting")
        _teach(core, "what is {{topic}}", "ask_question")

        core.process_input("good morning")
        u_before_reset = core.get_last_language_understanding()
        core.reset_context()
        self.assertIsNone(core.get_last_response_normalized_input())

        core.process_input("what is python")
        u_after = core.get_last_language_understanding()
        plan_after = core.get_last_response_plan()
        normalized_after = core.get_last_response_normalized_input()

        self.assertIsNot(u_after, u_before_reset)
        self.assertEqual(plan_after["status"], STATUS_RESOLVED)
        self.assertEqual(plan_after["response_action"], ACTION_PROVIDE_INFORMATION)
        self.assertEqual(normalized_after, "what is python")
        self.assertIs(plan_after, u_after.response_plan)
        self.assertIs(normalized_after, u_after.normalized_input)


# ======================================================================
class TestRepeatedReadsArePureAndReadOnly(unittest.TestCase):
    """Reading every one of these public getters repeatedly, with no
    intervening request or reset, must always return the identical
    object and must not itself trigger any reset or rebuild."""

    def test_repeated_reads_of_every_getter_are_stable(self):
        core = _make_core()
        _teach(core, "good morning", "greeting")
        core.process_input("good morning")

        u_first = core.get_last_language_understanding()
        plan_first = core.get_last_response_plan()
        normalized_first = core.get_last_response_normalized_input()
        conv_first = core.get_last_conversation_response()

        for _ in range(3):
            self.assertIs(core.get_last_language_understanding(), u_first)
            self.assertIs(core.get_last_response_plan(), plan_first)
            self.assertIs(core.get_last_response_normalized_input(), normalized_first)
            self.assertIs(core.get_last_conversation_response(), conv_first)
            # Reading does not accidentally behave like a reset.
            self.assertIsNotNone(core.get_last_response_normalized_input())


if __name__ == "__main__":
    unittest.main()
