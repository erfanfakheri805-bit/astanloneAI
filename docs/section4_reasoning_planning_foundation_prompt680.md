# Section 4 foundation - Reasoning, Planning & Agent Loop (Prompt 680-A)

Baseline: Prompt 679 (verified Section 3). Section 3 contracts are unchanged; no existing production
behaviour changed (`process_input()`, `ReasoningEngine`, `Plan`/`PlanManager`/`Planner`, capability
registries and the execution layer are untouched apart from three additive `Core` entry points).

## Flow

Request Context -> Reasoning Result -> Goal/Information Gaps -> Plan -> Plan Validation -> Inert Execution Handoff

## Reused architecture (not duplicated)

- `ReasoningEngine.reason()` / `ReasoningResult` - the only reasoning; wrapped read-only, never modified.
- `GoalManager`, `PlanManager`, `Planner`, `Plan`, `PlanStep` - the only plan model; `propose_plan=True` goes
  through `Core.create_goal()` + `Core.plan_third_step()`.
- `CapabilitySystem` (persisted registered/enabled state) and `ExecutableCapabilityRegistry` (read-only listing).
  Capability availability = registered AND enabled, identical to `PlanManager.check_plan_capabilities`.
- `KnowledgeSystem.resolve_current_name()` (Prompt 667 current-knowledge boundary), `is_goal_oriented`,
  `parse_query`, `extract_candidate_terms`, `normalize`.

## New foundation

| File | Purpose |
|---|---|
| `planning/request_context.py` | `RequestContext`: per-request, in-memory, never persisted (`persistent=False`). Holds input, normalized request, intent, terms, current-knowledge context, capability snapshot, reasoning outcome, goal, constraints, information gaps, proposed plan, validation, execution eligibility, bounded observations. `build_request_context()` writes nothing. |
| `reasoning/reasoning_contract.py` | `ReasoningOutcome` / `build_reasoning_outcome()`: status, answer/conclusion, relevant CURRENT knowledge, uncertainty, ambiguity, assumptions, evidence, next-action recommendation. `ReasoningResult` and its return contract are unchanged. |
| `planning/plan_validation.py` | `validate_plan()` -> `PlanValidationResult`. Deterministic, read-only, never repairs. |
| `planning/execution_handoff.py` | `ExecutionHandoff` / `prepare_execution_handoff()`: inert record for a future executor. |
| `core/core.py` | `prepare_request_context()`, `validate_plan()`, `prepare_execution_handoff()` - explicit, never called from `process_input()`. |

## Reasoning / planning boundary

Reasoning answers from current knowledge; planning consumes a `ReasoningOutcome` and information gaps. Planning
never re-reasons, never writes knowledge, and never uses historical learning events as current knowledge.

## Current knowledge integration

- Only current knowledge counts. Inactive records are named only as "inactive" (no description/relationship read)
  and give a non-blocking `INACTIVE_KNOWLEDGE_TERM` gap; reactivation is effective immediately (nothing cached).
- Ambiguous names (several current case variants) are a blocking `AMBIGUOUS_KNOWLEDGE_TERM` gap listing candidate
  names only; no candidate is ever chosen. Unresolvable references / contradictions are blocking gaps too.
- Finding (not changed): the engine reports a case-ambiguous name as `unknown`, and a Section 3 acceptance test
  locks that. The contract therefore keeps `status` as the engine's value and adds `effective_status="ambiguous"`
  / `next_action="clarify"` recovered read-only from `resolve_current_name()`. No production defect fix was needed.

## Capability handling

No capability is invented, registered, enabled or disabled. Steps may only name existing capabilities; the context
carries a read-only snapshot. Unregistered -> `UNKNOWN_CAPABILITY`; registered but disabled -> `MISSING_CAPABILITY`.
Without a capability system the check is skipped and a plan that needs capabilities is valid but NOT eligible.

## Plan validation

Empty goal, empty plan, invalid/duplicate step ids, empty step descriptions, invalid dependencies (unknown,
self, non-list), dependency cycles (cycle path reported), unknown/missing capabilities, impossible execution
eligibility (claiming eligibility for an ineligible plan). Output includes a deterministic topological order.
The plan, step statuses and registries are never modified.

## Execution boundary

The handoff is data only: `executed=False`, `inert=True`, `execution_authorized=False`; no callables, no run/execute
method; the module imports only `planning.plan`. It is a snapshot; invalid / ineligible / gap-blocked plans yield a
`rejected` handoff with reasons. Nothing runs shell commands, edits files, installs packages, touches the network
or invokes tools. `RequestContext.execution_eligible` is True only for a valid, eligible plan with no blocking gap.

## Intentional limitations

Deterministic and lightweight; plans still come from the existing 3-step `Planner`; no autonomous loop, executor,
persistence, replanning, or new capabilities; term matching is the existing candidate-term extraction.

## Remaining for Prompt 680 finalization

Full-suite validation (real project + disposable copy), DB hash re-verification, no pycache/pyc, 8-part packaging
(`Project_Prompt680_PartNof8.zip` + `PROJECT_PARTS_MANIFEST_Prompt680.json`) and reconstruction verification.
