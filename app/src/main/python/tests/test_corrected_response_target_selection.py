"""
Tests for Prompt 495 - Select Corrected Response Target.

`select_corrected_response_target()` (language_intelligence/
corrected_response_target_selection.py) reads
`context.corrected_response_target`
(`ResponseGenerationContext`, Prompt 494) and returns it exactly when
usable, or `None` otherwise - no response generation, no rewriting,
no correction application, no matching. Covers:

    1. context without corrected target (None) -> None
    2. context with corrected target -> exact target returned
    3. empty/blank target -> safely rejected (None), per the existing
       _is_blank() convention
    4. original context remains unchanged (never mutated)
    5. returned text is preserved exactly (no stripping/transforming)
    6. wrong-typed argument raises TypeError
    7. deterministic repeated calls

Run directly:
    python -m unittest tests.test_corrected_response_target_selection -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from language_intelligence.response_generation_context import ResponseGenerationContext
from language_intelligence.corrected_response_target_selection import (
    select_corrected_response_target,
)


def _plain_context(**overrides):
    fields = dict(
        original_message="hello",
        status="RESOLVED",
        response_action="GREET",
        meaning="greeting",
        meaning_candidates=[],
        matched_pattern=None,
        variables={},
        active_topic=None,
        references=[],
        context=None,
        language="en",
        locale=None,
        unresolved_requirements=[],
    )
    fields.update(overrides)
    return ResponseGenerationContext(**fields)


class TestSelectCorrectedResponseTarget(unittest.TestCase):

    def test_context_without_corrected_target_returns_none(self):
        context = _plain_context()
        self.assertIsNone(select_corrected_response_target(context))

    def test_context_with_corrected_target_returns_exact_target(self):
        context = _plain_context(corrected_response_target="I has a dog")
        self.assertEqual(select_corrected_response_target(context), "I has a dog")

    def test_empty_string_target_rejected(self):
        context = _plain_context(corrected_response_target="")
        self.assertIsNone(select_corrected_response_target(context))

    def test_whitespace_only_target_rejected(self):
        context = _plain_context(corrected_response_target="   ")
        self.assertIsNone(select_corrected_response_target(context))

    def test_original_context_remains_unchanged(self):
        context = _plain_context(corrected_response_target="Some corrected text")
        before = context.to_dict()
        select_corrected_response_target(context)
        after = context.to_dict()
        self.assertEqual(before, after)

    def test_returned_text_preserved_exactly(self):
        context = _plain_context(corrected_response_target="  Exact Text!  ")
        self.assertEqual(select_corrected_response_target(context), "  Exact Text!  ")

    def test_wrong_typed_argument_raises_type_error(self):
        with self.assertRaises(TypeError):
            select_corrected_response_target(None)
        with self.assertRaises(TypeError):
            select_corrected_response_target("not a context")
        with self.assertRaises(TypeError):
            select_corrected_response_target({"corrected_response_target": "x"})

    def test_deterministic_repeated_calls(self):
        context = _plain_context(corrected_response_target="deterministic target")
        first = select_corrected_response_target(context)
        second = select_corrected_response_target(context)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
