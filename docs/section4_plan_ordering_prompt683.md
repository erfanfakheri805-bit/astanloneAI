# Section 4 - Deterministic plan step ordering (Prompt 683)

Baseline: Prompt 682 (verified). One additive improvement in `planning/plan_builder.py`; no other production file changed
(`core/core.py` and `process_input()` untouched).

`order_plan_steps(plan_or_steps)` -> `PlanOrderResult(status, ordered_step_ids, steps, dependency_validation, failures)`:

- Gate: `validate_step_dependencies()` (Prompt 682). Any invalid graph (unknown, self, duplicate, forward, unordered, non-list,
  cycle) is rejected with the single failure `INVALID_DEPENDENCY_GRAPH` (issues attached), no order, no steps. Nothing is repaired
  or silently reordered.
- Order: Kahn topological sort; among steps ready at the same time the earliest DECLARED step goes first (no sets, hashing, clock
  or randomness). Dependencies always precede dependents; independent steps keep declared order; same input -> same result.
- Because 682 requires dependencies to point backwards, the order of a valid graph coincides with declared order; the utility
  proves and returns that order explicitly rather than assuming it.
- Read-only: the input plan/steps are never mutated; `result.steps` are fresh `PlanStep` copies (ids, dependencies, status and data
  identical to the originals). Generated step ids and dependency declarations are unchanged.

Not executed: `executed=False`, `execution_authorized=False`, no capabilities, no writes, no Core/`process_input()` hook.
Module imports remain `hashlib` + `planning` only.
