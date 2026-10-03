# Section 4 - Deterministic plan step dependencies (Prompt 682)

Baseline: Prompt 681 (verified). One additive improvement in `planning/plan_builder.py`; no other production file changed.

Steps declare dependencies through the existing `PlanStep.dependencies` list (earlier step ids only). New in this prompt:

- `validate_step_dependencies(plan_or_steps)` -> `DependencyValidationResult(valid, issues, graph, ordered_step_ids)`. Read-only, never
  raises, never repairs or reorders. Issue codes, reported in step order then list position, cycle last:
  `UNKNOWN_DEPENDENCY`, `SELF_DEPENDENCY`, `DUPLICATE_DEPENDENCY`, `FORWARD_DEPENDENCY`, `UNORDERED_DEPENDENCIES`,
  `INVALID_DEPENDENCIES` (non-list / bad input), `DUPLICATE_STEP_ID`, `DEPENDENCY_CYCLE` (cycle path included).
- `build_plan_from_context()` runs it on the generated steps BEFORE creating the plan. Failure -> `rejected` result with the single
  failure `INVALID_DEPENDENCY_GRAPH` (issues attached), no plan, no validation; success keeps `result.dependency_validation`
  (also in `to_dict()` as `dependency_validation`).
- Step construction moved into `_build_steps(ctx)` (behaviour unchanged) so the graph check has one seam.

Dependencies stay meaningful only: review and gap steps depend on the confirmed request (`step-001`); the response step depends on
every earlier step; review/gap steps never depend on each other. Nothing is invented to make the graph non-empty.

Unchanged: Prompt 680 `validate_plan` (its codes and results), all Prompt 681 build behaviour and rejection codes, Section 1-3
contracts. Planning stays side-effect-free: every step `pending`, `executed=False`, `execution_authorized=False`, no capabilities,
no writes, context never mutated. Module imports remain `hashlib` + `planning` only.
