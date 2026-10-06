# Prompt 833 - NLU -> Reasoning Bridge

Module: `understanding/nlu_reasoning_input.py` (`build_reasoning_input(subject, context=None)`, `empty_reasoning_input`).
Convenience method: `NLUAnalysis.reasoning_input(context=None)`. `normalized()`, `semantic_view()`, `resolve_references()` and the raw analysis are unchanged.

Built only from the Prompt 831 semantic view and the Prompt 832 meaning bridge (`context` is read-only, via the bridge).

Result keys: `version, status, intent, known, unresolved, missing`.
- `intent`: `primary, effective, inherited, recognized` (inherited/effective follow the bridge: only a *resolved* reference may inherit).
- `known`: `slots`, `relations` (copied from the view, <= 16 each) and `reference` = `{status, cues, continuation, referenced_turn, referenced}`.
- `unresolved`: `reference_status` (None | `unresolved` | `ambiguous`), `reference_reason`, `ambiguous_relations`, `slots_truncated`, `relations_truncated`.
- `missing`: fixed-order codes from `intent_unknown, reference_unresolved, reference_ambiguous, relations_ambiguous, slots_truncated, relations_truncated`.
- `status`: `ambiguous` > `unresolved` > `unknown` (intent unknown and no slots/relations) > `ready`.

Nothing is detected or invented (no goals, entities or filled-in slots). Bounded, JSON-safe, deterministic, non-raising, fresh dict, inputs never modified. No Memory, AEL, Core, storage, LLM or network involvement.
Tests: `tests/test_nlu_reasoning_input_prompt833.py` (25 tests).
