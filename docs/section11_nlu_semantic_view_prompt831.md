# Prompt 831 - Semantic Interpretation Layer

Module: `understanding/nlu_semantic_view.py` (`build_semantic_view`, `semantic_view_from_normalized`, `empty_semantic_view`).
Convenience method: `NLUAnalysis.semantic_view()`. The normalized output (`normalized()`) and raw analysis are unchanged.

View: `{version, intent{primary, effective, recognized}, context{present, turn_index, continuation, again,
refers_to_previous, repeat_count, repeat_of, referenced_turn, inherited_intent}, slots[kind,key,value],
relations[kind,subject,relation,value,slot], bounds{slots_truncated, relations_truncated, relations_ambiguous}}`.

Everything is copied from the existing normalized analysis (no new detection, no inference). `context.present` is True
only when an explicit reference/continuation is set. Bounded by the 829/830 limits (16 each), JSON-safe, deterministic,
fresh detached dict, never raises, no Memory/AEL/Core involvement.
Tests: `tests/test_nlu_semantic_view_prompt831.py` (22 tests).
