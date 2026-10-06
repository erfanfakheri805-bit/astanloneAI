# Prompt 837 - Reasoning Decision Pipeline

Module: `reasoning/reasoning_decision.py` (`decide_reasoning(reasoning_request, plan_builder=build_reasoning_plan)`).
Pipeline: reasoning request (834) -> existing planner `build_reasoning_plan` (835) -> existing validator `validate_reasoning_plan` (836) -> decision. No existing module, NLU API or reasoning API is changed. `plan_builder` defaults to the existing planner and is only a seam for testing against a faulty planner; its output is validated as is, never repaired.

Result keys: `version, decision, reason, request_status, plan_status, validation, next_step, executed`.
- `decision`: `ready` | `needs_clarification` | `needs_information` | `invalid_plan`.
- `ready` only when the request status is `ready`, the plan is valid and the plan is `ready`.
- A valid non-ready plan gives the decision of its own status (`needs_clarification` -> clarification, `needs_information` -> information). `reason` = the first step's `ref` (e.g. `intent_unknown`, `relations_ambiguous`).
- A valid ready plan with a request that does not say `ready` is a conflict: never `ready`; `needs_clarification` if the request says `ambiguous`, else `needs_information`; `reason` = `request_status_conflict`; no next step.
- A plan that fails validation (or a planner that returns nothing usable / raises) gives `invalid_plan`, `reason` = first validation error code, `next_step` None.
- None / malformed request: the planner's `need.reasoning_request_missing / invalid` plan is valid, so `needs_information`.
- `request_status`: the request's own status when one of ready / unknown / ambiguous / unresolved / missing, else None. `plan_status`: the plan's status (None when unusable). `validation`: the Prompt 836 result, unchanged.
- `next_step`: None, or `{id, kind, ref, detail, remaining}` - the first step of a validated plan (it has no dependencies) and how many steps follow; a description only.
- `executed` is always False. Nothing is executed, repaired, modified or invented.

Bounded, JSON-safe, deterministic, non-raising, fresh dict. No Memory, AEL, Core, LLM or network.
Tests: `tests/test_reasoning_decision_prompt837.py` (30 tests).
