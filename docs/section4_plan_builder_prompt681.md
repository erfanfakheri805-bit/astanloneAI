# Section 4 - Deterministic plan builder (Prompt 681)

Baseline: Prompt 680 (verified). One additive improvement; no existing behaviour changed.

Flow: `RequestContext` -> `build_plan_from_context()` -> `PlanBuildResult` (unexecuted `Plan` + `PlanValidationResult`, or
ordered failure codes and no plan) -> existing `validate_plan` / `prepare_execution_handoff`.

- `planning/plan_builder.py` (new): pure, dependency-free (`hashlib` + planning modules only).
- `Core.build_plan_from_context(ctx)` (new, additive): thin wrapper; never called from `process_input()`.

Plan shape: ids `plan-<digest>` / `request-<digest>` (digest of normalized request + intent), steps `step-001...` in order:
confirm request/intent, review each CURRENT knowledge record, address each NON-blocking gap, prepare response (depends on all
earlier steps). Original input, normalized request, intent and goal are kept in `metadata`. Fixed `created_at` sentinel.

Planning vs execution: all steps `pending`, `metadata.executed=False`, `execution_authorized=False`, no capabilities required
or invented, no tools/filesystem/memory/knowledge/goal/plan-store writes, the context is never mutated or attached-to.

Rejection (no plan, deterministic codes): `INVALID_CONTEXT`, `EMPTY_REQUEST`, `INCOMPLETE_CONTEXT`, `PERSISTENT_CONTEXT`,
`BLOCKING_INFORMATION_GAPS` (gaps listed; ambiguity is never resolved by guessing), `GENERATED_PLAN_INVALID`.
