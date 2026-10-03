# Section 4 - Reasoning, Planning & Agent Loop: Final Acceptance (Prompt 696)

**Result: ACCEPTED. Section 4 (Prompts 680-696) is complete and ready to move to Section 5.** The review found no
production defect; no production file changed in Prompt 696. (The one defect found in Section 4 after 693 was fixed and
documented in Prompt 695: `run_plan_steps` now also gates on `validate_plan_step_states`.) The per-prompt notes
`docs/section4_*_prompt6NN.md` remain the detailed references; this file is the acceptance record.

## Purpose
Turn a request into a deterministic, validated, UNEXECUTED plan without inventing capabilities, and let a caller
drive that plan step by step (or up to N steps) through a caller-owned executor, with every layer reporting the same state.
It is not the Tools section, has no scheduler, and is not wired into `process_input()`.

## Architecture / data flow
```
Request (text) -> RequestContext (680) -> ReasoningOutcome (680) -> build_plan_from_context (681)
   -> validate_plan (680) + validate_step_dependencies (682) + order_plan_steps (683)
   -> [caller sets metadata["execution_authorized"] = True]
   -> validate_plan_step_states (684) / get_ready_plan_steps (686, 688) / evaluate_plan_progress (687)
   -> start / complete / fail_plan_step (689) -> execute_plan_step (691) -> report_plan_step_execution (692)
   -> run_plan_steps (693) -> summarize_plan_run (694)          rollup_plan_status (690) is read by 692/693
```

## Authoritative source for each state decision
| Decision | Authority |
|---|---|
| Step state (pending / in_progress / completed / failed) | `PlanStep.status`, changed only by 689 transitions |
| Evidence of execution | step state + recorded output (`start_plan_step` also sets `executed=True`) |
| Permission to execute | `metadata["execution_authorized"] is True` (never implies or records execution) |
| Flag/state consistency | `validate_plan_step_states` (684); gates transitions, execution, rollup, runner |
| Plan structure / dependency graph | `validate_plan` (680), `validate_step_dependencies` (682) |
| Order | `order_plan_steps` (683): stable Kahn, earliest declared first |
| Ready steps | `get_ready_plan_steps` (686/688): pending, no output, all dependencies completed |
| Counts, complete/blocked flags | `evaluate_plan_progress` (687) |
| Plan-level status | `rollup_plan_status` (690), precedence: empty > complete > failed > in_progress > blocked > pending |
| What one attempt did | `PlanStepExecutionResult` (691), verified against the plan by 692 |
| What a run did | `PlanRunResult` (693) is the record; 694 reads only it |

## Execution boundaries
- Execution is always explicit and caller-driven; nothing runs from validation, readiness, progress, rollup, report or summary.
- The executor is injected by the caller and receives only a step-scoped dict of deep copies (`step_id`, `description`,
  `input_data`, `expected_output`, `required_capabilities`), never the Plan/PlanStep. Its output is stored as a copy.
- The runner takes the first ready step only, sequentially, at most `max_steps` (plain int > 0).
- No retries, tools, internet, API keys, threads, subprocesses, background work, file access, or self-modification.

## Failure / rejection behavior
- Executor exception, or output that is None/blank/not JSON-safe: step recorded `failed` (`EXECUTOR_EXCEPTION` /
  `EXECUTOR_OUTPUT_INVALID`), never re-raised, never retried; the runner stops with `STEP_FAILED` (`ok=False`).
- Precondition rejections (nothing executed, plan untouched, executor never called): invalid plan object / plan /
  plan state / dependency graph, unauthorized plan, unknown or not-ready step, invalid executor, invalid `max_steps`.
- 692 refuses inconsistent or rejected execution results; 694 refuses non-run or self-contradictory run records.
  Nothing is guessed or repaired anywhere; builder rejections return failure codes and no plan.

## Deterministic guarantees
Same context -> same plan and ids (digest-based, fixed `created_at`); same plan state -> same readiness, progress, rollup,
order, report and summary; step ids are always reported in plan order; same plan + deterministic executor -> identical run.

## Verification evidence
- Section 4 regression (`tests/test_section4_*.py`, Prompts 680-696): 353 tests, all passing
  (336 for 680-695 + 17 new acceptance tests `test_section4_final_acceptance_prompt696.py`, one or more per acceptance criterion 1-15).
- Acceptance tests fail if the Prompt 695 runner state gate is removed (checked by mutation on a scratch copy).
- Shipped DB SHA-256 unchanged: `0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb`; no `__pycache__` / `.pyc`.
- The full project suite was not re-run: no production code changed.

## Known intentional limitations
- Nothing in Section 4 runs from `process_input()`; callers must invoke it explicitly.
- Builder plans require no capabilities and are never authorized by the builder; authorization is the caller's act.
- Runner is sequential, first-ready-first; no parallelism, retries, resumption of a failed step, or scheduling.
- The run stops at the first failure, but a separate later explicit run may still start an independent READY step of a
  plan whose rollup status is `failed` (the failed step itself is never retried; steps behind it stay blocked).
- A step may be `completed` without recorded output when set outside the 689/691 transitions (684 does not require output).
- Executors are trusted callables; a `BaseException` (e.g. `KeyboardInterrupt`) is deliberately not caught.
- Prompts 685-687 have no separate note; their readiness/progress contract is in the `plan_builder.py` module docstring.

## Statement
Section 4 acceptance criteria 1-15 are met. **Section 4 is complete.**
