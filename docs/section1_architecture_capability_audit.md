# Section 1 Architecture Capability Audit (Prompt 557)

Read-only audit. Structured, machine-checkable data for this report lives in
`app/src/main/python/diagnostics/section1_architecture_capability_audit.py`
and is covered by
`app/src/main/python/tests/test_section1_architecture_capability_audit.py`.
No application behavior was changed to produce this audit.

Roadmap position: Main Section 1 of 10 - Core Infrastructure, Diagnostics,
and Learning Foundations (Prompt 500-570), current position Prompt 557.

## Areas inspected

learning, learned knowledge (`learning/learned_knowledge_statistics.py` and
the Prompt 541-556 chain), memory, reasoning, diagnostics, context, AEL,
planning, execution/capabilities, the agent loop (`agent/agent_loop.py`),
and their integration into `core/core.py`.

## Category definitions used below

- **A - capability_changes_behavior**: actually changes application behavior.
- **B - records_or_validates_only**: only records/validates/diagnoses
  existing behavior.
- **C - structural_not_integrated**: exists structurally but is not
  meaningfully integrated.

No entry below is scored, ranked, or labeled "best"/"worst".

## Implemented core capabilities (A)

- Agent loop orchestration (`agent/agent_loop.py`, 3600 lines)
- Memory system (SQLite-backed, `memory/memory_system.py`)
- Reasoning engine + rule registry
- Conversation context tracking (relevance, active topic, reference
  resolution)
- Planning and goal management
- Step execution (preparation, controller, engine)
- AEL interpreter
- Learned-knowledge gate (`learning/learned_knowledge_gate.py`) - its
  verdict participates in response selection in `core/core.py`
- Understanding engine (term extraction, sentence analysis)
- Health system (`diagnostics/health_system.py`)

Each is imported and actually called from `core/core.py` and/or
`agent/agent_loop.py`.

## Partially implemented capabilities

- **language_intelligence_core** (C): 74 files exist under
  `language_intelligence/`; `core/core.py` uses a subset. A large part of
  the correction/verification pipeline
  (`correction_application_*.py`, `verified_correction_response_*.py`) has
  no import from `core/core.py` or `agent/agent_loop.py` - only from its
  own tests.
- **self_upgrade_pipeline** (C): 31 modules, wired into the agent loop for
  dry-run code-change evaluation, but the pre-existing failing test
  (see below) shows the lifecycle-stage wiring is not fully exercised.
- **execution_learning** (B): records `LearningRecord`s from execution
  outcomes; does not itself choose the next plan step.

## Diagnostic-only capabilities (B / C)

- **learned_knowledge_statistics_chain**: `learning/learned_knowledge_
  statistics.py` is 11,116 lines / 564,499 bytes - 5 classes, 245
  functions/methods. `core/core.py` imports exactly two names from it,
  `LearnedKnowledgeDecisionStatistics` and
  `LearnedKnowledgeDiagnosticSnapshotHistory`, both used as
  counters/history stores. `core/core.py`'s own comment (line ~1049) calls
  this counter "diagnostic-only." The remaining ~200 module-level
  `validate_learned_knowledge_filtered_trend_source_coverage_chain_*`
  functions and siblings are referenced only by the 56
  `tests/test_learned_knowledge_*.py` files, never by application code.
- **learned_knowledge_gate_trace**: stored as
  `last_learned_knowledge_gate_trace`; `core/core.py`'s own comment states
  it is "purely for later internal" use and "never used in response
  generation."
- **capability_system_registry** (C): all 8
  `PLANNED_CAPABILITIES` entries are registered with `enabled=False`,
  `status="planned"` by design; the module's docstring says they "exist as
  named, tracked placeholders," not working features.

## Integration gaps

- The `language_intelligence` correction/verification pipeline is not
  called from `core/core.py` or `agent/agent_loop.py` at audit time.
- `diagnostics/health_system.py` does not surface anything from
  `learning/learned_knowledge_statistics.py`, so the large validator
  chain's output is invisible to the project's one live health-check
  surface.

## Important missing foundation capabilities

- All 8 planned capabilities remain disabled; no enable path was found.
- `tests/test_self_upgrade_end_to_end_dry_run.py::
  NoAutomaticActivationTests::
  test_no_stage_runs_twice_in_a_successful_lifecycle` fails on a clean run
  of the full suite (`spy.call_count == 0`, expected `1`). This is the
  known pre-existing failure named in the Prompt 557 instructions; this
  audit did not attempt to fix it and found no evidence tying it to the
  learned-knowledge chain.

## Redundant / excessively nested diagnostic layers

`learning/learned_knowledge_statistics.py` (lines 8654-11116) contains a
linear chain of validator functions, each wrapping the previous one's
`_result`:

```
validate_learned_knowledge_filtered_trend_source_coverage_chain
  -> ..._chain_stage_order
    -> ..._chain_stage_order_result
      -> ..._chain_stage_order_consistency
        -> ..._chain_stage_order_consistency_result
          -> ..._complete_chain_consistency
            -> ..._complete_chain_consistency_result
              -> ..._complete_chain_consistency_validation
                -> ..._complete_chain_consistency_validation_result
                  -> ..._complete_chain_validation_consistency
                    -> ..._complete_chain_validation_consistency_result
                      -> ..._complete_chain_validation_consistency_result_consistency
                        -> ..._complete_chain_validation_consistency_result_consistency_result
```

Each layer validates the well-formedness of the previous layer's output
structure. None of these functions changes what the underlying
gate/response decision was. 56 of the project's 296 test files exist to
cover this wrapper family, roughly one file per layer.

**Whether continuing to add layers has a concrete functional purpose:**
no application code path was found that consumes any layer past
`LearnedKnowledgeDecisionStatistics` / `LearnedKnowledgeDiagnosticSnapshotHistory`.
Per the Prompt 557 instructions, this audit did not modify the chain.

## Section 1 completion candidates

1. Decide, for each entry in `PLANNED_CAPABILITIES`, whether it is in
   scope for Section 1 sign-off or explicitly deferred.
2. Confirm whether the `language_intelligence` correction/verification
   pipeline is meant to be reachable from `core/core.py` in Section 1, or
   is intentionally staged ahead for Section 2.
3. Resolve or explicitly accept
   `test_no_stage_runs_twice_in_a_successful_lifecycle` as a tracked,
   known gap.
4. Record a decision on whether the learned-knowledge validator-of-
   validator family should stop growing, since no consumer past the two
   imported classes was found.

## Section 2 readiness

**Section 1 is not marked ready to move to Section 2** ("Language
Intelligence and Request Understanding") by this audit, based on:

- Two open Section-1-scoped items at audit time: all 8 planned
  capabilities remain disabled by design, and one pre-existing test
  failure is present in a full, unmodified test run.
- A substantial amount of code already exists under `language_
  intelligence/` that overlaps with Section 2's stated scope; this does
  not by itself mean Section 1 is incomplete, but Section 1 and Section 2
  scope currently overlap in the source tree.

No recommendation is made on how to close these; per the prompt's rules
this audit lists the concrete gaps without ranking or recommending among
them.

## Full test suite (pre-audit baseline, unmodified project)

- 10,854 tests run
- 1 failure: `test_no_stage_runs_twice_in_a_successful_lifecycle`
  (pre-existing, named in the Prompt 557 instructions, not modified here)
- 0 errors

## Focused test added by this prompt

`tests/test_section1_architecture_capability_audit.py` - 11 tests,
checking that `build_section1_architecture_capability_audit()`'s output is
well-formed, deterministic across calls, free of forbidden
score/rank/"best"/"worst" language, and does not import
`core.core` or any behavior-affecting subsystem.
