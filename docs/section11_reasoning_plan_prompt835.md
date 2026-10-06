# Prompt 835 - Deterministic Reasoning Plan

Module: `reasoning/reasoning_plan.py` (`build_reasoning_plan(reasoning_request)`, `empty_reasoning_plan`).
Input: the Prompt 834 reasoning request (`build_reasoning_request(...)`). The request builder, the reasoning input and all NLU APIs are unchanged.

Result keys: `version, status, request_status, goal, steps, step_count, truncated, executed`.
- `status`: `ready` | `needs_clarification` (an ambiguity is present) | `needs_information` (everything else). Recomputed from the request's goal / unresolved / missing fields, not copied; `request_status` echoes the request's own status string.
- Step: `{id, kind, ref, detail, depends_on, executed}`. Ids are stable (`kind`, or `kind.code` for clarify / need) and unique per plan. `executed` is always False; `depends_on` lists earlier step ids. Kinds: `consider_reference`, `consider_slots`, `consider_relations`, `address_goal`, `clarify`, `need`. No tool, capability or action is ever named.
- Ready plan: `consider_reference` (only with a resolved reference), `consider_slots` / `consider_relations` (only when present; detail = count), then `address_goal` (ref = the goal's intent, detail = its source), depending on all earlier steps.
- Not ready: only `clarify` / `need` steps - one per unresolved item (clarify for an ambiguity, need for an unresolved reference; detail = the request's reason / count), then one `need` per missing code. A goal that is not known always yields `need.intent_unknown`. Never an `address_goal` step: missing information is asked for, not guessed.
- None / malformed request, or a code outside the Prompt 834 vocabulary: `needs_information` with `need.reasoning_request_missing` / `need.reasoning_request_invalid`.
- Bounded at 8 steps (`truncated` flag). Pure stdlib, deterministic, non-raising, fresh dict, request never modified. No Memory, AEL, Core, execution, LLM or network.
Tests: `tests/test_reasoning_plan_prompt835.py` (25 tests).
