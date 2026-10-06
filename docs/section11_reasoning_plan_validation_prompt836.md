# Prompt 836 - Reasoning Plan Validation

Module: `reasoning/reasoning_plan_validation.py` (`validate_reasoning_plan(plan)`). Validates plans from `build_reasoning_plan` (Prompt 835). The planner, the reasoning request / input and all NLU APIs are unchanged. The validator only reads: it never executes, repairs, reorders or guesses, and the plan is never modified.

Result keys: `version, valid, status, error_count, errors, truncated, steps_checked`.
- `status` is `valid` | `invalid`; `valid` is True only with zero errors.
- `errors` = `[{code, where}]` in discovery order, no duplicates, at most 16 (`truncated` flags more). `where` is a field name or a path such as `steps[2].depends_on[0]`.
- Only the first 8 steps and 8 dependencies per step are examined (`too_many_steps`, `too_many_dependencies`).

Error codes
- Plan fields: `plan_not_dict, missing_field, unexpected_field, invalid_version, invalid_status, invalid_request_status, invalid_goal, invalid_steps, invalid_step_count, step_count_mismatch, invalid_truncated, contradictory_truncated, executed_not_false, no_steps, too_many_steps`.
- Steps: `malformed_step, missing_step_field, unexpected_step_field, invalid_step_id, duplicate_step_id, invalid_step_kind, unstable_step_id` (id must equal `kind`, or `kind.ref` for clarify / need), `invalid_step_ref, invalid_step_detail, invalid_depends_on, too_many_dependencies, executed_not_false`.
- Dependencies: `duplicate_dependency, self_dependency, missing_dependency, forward_dependency` (only earlier steps may be depended on), `dependency_cycle` (one error per cyclic group; a self-loop is `self_dependency` only).
- Plan contract: `contradictory_status` (ready with clarify/need steps; not-ready with consider/address_goal steps; needs_clarification without a clarify step or needs_information with one), `contradictory_goal`, `address_goal_missing`, `address_goal_misplaced` (exactly one, last), `address_goal_dependencies` (must depend on every earlier step), `goal_mismatch` (address_goal ref/detail vs the plan goal), `step_order_violation` (consider_reference, consider_slots, consider_relations), `unexpected_dependency` (only address_goal may depend on anything).
- `validator_error`: defensive only.

Pure stdlib, deterministic, JSON-safe, non-raising, fresh dict. No Memory, AEL, Core, execution, LLM or network.
Tests: `tests/test_reasoning_plan_validation_prompt836.py` (41 tests).
