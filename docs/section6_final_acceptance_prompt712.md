# Prompt 712 - Section 6 boundary audit and final acceptance

**Result: ACCEPTED. No production defect found; no production file changed.** Only this document and
`tests/test_section6_final_acceptance_prompt712.py` were added. Audited: Prompts 707-711 (`planning/tool_step_bridge.py`,
`tool_step_executor.py`, `tool_capability_mapping.py`, `tool_step_retry.py`) against the Section 4 and Section 5 contracts.

Flow audited: plan -> tool request -> capability mapping -> preflight -> controlled step start -> tool execution -> completion/failure ->
retry policy -> terminal state/reporting.

## Checklist (Prompt 712, items 1-29)

| # | Item | Result | Enforced by |
|---|---|---|---|
| 1 | Bridge stateless/deterministic | PASS | `test_bridge_is_stateless_and_deterministic`, module-state check |
| 2 | ToolRequest immutable, caller-owned | PASS | `test_no_api_mutates_caller_owned_inputs` |
| 3 | Capability mapping explicit, never inferred | PASS | `test_capability_mapping_is_explicit_and_never_inferred` |
| 4 | Section 5 final authority | PASS | `test_section5_stays_the_final_authority_for_mapped_grants` |
| 5 | Preflight failure never starts a step | PASS | `test_registry_preflight_rejection_happens_before_start` |
| 6 | No fabricated invocation/sequence | PASS | `test_no_fabricated_invocation_sequence_after_any_rejection` |
| 7 | Started step never retried | PASS | `test_no_retry_after_step_start_even_when_failure_is_toctou` |
| 8 | Completed/failed/in-progress never re-run | PASS | `test_started_completed_failed_steps_are_never_silently_rerun` |
| 9 | Attempts caller-owned, no hidden state | PASS | `test_caller_owned_attempt_log_isolation` |
| 10 | Retry limit explicit and validated | PASS | `test_retry_limits_are_explicit_and_validated` |
| 11 | Allow-list never retries unknown/malformed | PASS | `test_retry_allow_list_never_retries_unknown_or_malformed_failures` |
| 12 | Mapped capability failures pre-start | PASS | `test_mapped_capability_rejection_happens_before_start` |
| 13 | Registry preflight failures pre-start | PASS | `test_registry_preflight_rejection_happens_before_start` |
| 14 | Real execution failure terminal | PASS | `test_terminal_tool_execution_failure_is_not_retried` |
| 15 | Success = exactly one real invocation | PASS | `test_successful_*` |
| 16 | Plan/tool/retry/audit agree | PASS | `test_plan_tool_retry_and_audit_state_agree_on_success/failure` |
| 17 | No mutation beyond documented transitions/log append | PASS | `test_no_api_mutates_caller_owned_inputs`, `test_step_transitions_are_the_only_plan_mutation` |
| 18 | Deep-copy/isolation intact | PASS | log-isolation and result `to_dict()` tests |
| 19 | Section 4 contracts unchanged | PASS | frozen digest of `planning/*` (non-Section-6) |
| 20 | Section 5 contracts unchanged | PASS | frozen digest of `tools/*` |
| 21 | Source guards enforce boundaries | PASS | `TestSourceAndDependencyGuards` (and the existing 697-711 guards) |
| 22 | No hidden import/wiring path | PASS | import-graph tests: only the bridge imports `tools`; only the executor/retry import Section 6 modules; nothing else references them |
| 23 | Retry never calls a handler | PASS | AST guard + call-spy test |
| 24 | Retry never bypasses preflight | PASS | call-spy test (preflight precedes every execution) |
| 25 | Invalid arguments never start/retry | PASS | `TestInvalidInputs` |
| 26 | Two execution stacks separate | PASS | `test_two_historical_execution_stacks_remain_separate` |
| 27 | Hazards documented | PASS | section below |
| 28 | No automatic capability mapping sourcing | PASS | mapping signature/inference tests; plan `required_capabilities` never read |
| 29 | No auto-selection/scheduling/background/persistence/network | PASS | banned-import guard over all four Section 6 modules |

## Remaining hand-over hazards (documented, deliberately NOT implemented)

1. **`ready`-status incompatibility.** The Section 4 step layer (`start_plan_step`, Prompt 689) starts steps from the state its own readiness rule
   allows on `pending` steps; the legacy Agent Loop stack (`ExecutionEngine` / `PlanExecutionController`) runs steps whose status is `ready`
   (set by `PlanManager` refresh). `validate_plan_step_states`, `get_ready_plan_steps` and `start_plan_step` reject `ready`/`blocked` step states in this layer (note: `validate_plan` alone does not; see Prompt 713, C2/C3), so one plan cannot be driven by both stacks.
2. **Legacy execution-stack separation.** The Prompt 689-694 step layer plus Section 6 is one stack; `execution/execution_engine.py` and
   `execution/plan_execution_controller.py` (the Agent Loop) is the other. Neither imports the other; Section 6 is not wired into
   `process_input()`, the Agent Loop, the Planner or `execute_plan_step()`. The hand-over must choose a direction explicitly.
3. **F3 NaN/inf asymmetry.** Section 4 structured data accepts NaN/inf; Section 5 rejects it. Plan -> tool fails closed at `create_tool_request()`
   (`INVALID_TOOL_REQUEST_INPUT`, verified here); tool -> plan is always accepted. Unchanged and unresolved.
4. **Policy for intentionally re-running a failed step.** A failed step is final (`STEP_NOT_READY`, never retried, verified here). Re-running a
   failed step would need an explicit new Section 4 reset transition and a caller-visible policy; none exists and none was added.

Also still true: `max_attempts` has no upper bound (caller responsibility); retries re-ask an unchanged condition synchronously with no delay.

## Verdict

Section 6 is ready for **final hand-over design work** (Agent Loop / `process_input()` integration), not for silent wiring: hazards 1-4
must each be decided explicitly first. Recommended **Prompt 713**: a read-only hand-over decision record (which stack the Agent Loop should
drive, how `ready` maps, F3 policy, failed-step re-run policy) with tests pinning the decisions, before any integration code.
