# Prompt 834 - Reasoning Foundation

Module: `reasoning/reasoning_foundation.py` (`build_reasoning_request(reasoning_input)`, `empty_reasoning_request`).
Input: the Prompt 833 reasoning input (`build_reasoning_input(...)` / `NLUAnalysis.reasoning_input(...)`). No NLU module, `normalized()`, `semantic_view()`, `resolve_references()` or `reasoning_input()` behavior is changed.

Result keys: `version, status, goal, known, unresolved, missing, next_action`.
- `goal`: `{intent, source, state}` - the effective intent as stated (`source` = `primary` | `inherited`); `intent None / state unresolved` when no goal is stated. No goal is ever derived from slots.
- `known`: `slots`, `relations` (<= 16 each, JSON-safe items only) and `reference` (only a *resolved* reference, else None).
- `unresolved`: list of `{code, detail}` - `reference_unresolved` / `reference_ambiguous` (detail = reason) and `relations_ambiguous` (detail = count). Never guessed.
- `missing`: codes `reasoning_input_missing`, `reasoning_input_invalid`, `intent_unknown`, `slots_truncated`, `relations_truncated`.
- `next_action`: `{action, reason, executed}`; action `proceed` (ready) | `clarify` (ambiguous) | `request_information` (all else); `executed` is always False. It is a label only - nothing is run.
- `status` (recomputed from the input's explicit fields, not copied): `ambiguous` > `unresolved` > `unknown` > `missing` > `ready`.

None / malformed input gives status `unknown` with `reasoning_input_missing` / `reasoning_input_invalid`. Pure stdlib, deterministic, non-raising, fresh dict, input never modified. No Memory, AEL, Core, execution, LLM or network.
Tests: `tests/test_reasoning_foundation_prompt834.py` (23 tests).
