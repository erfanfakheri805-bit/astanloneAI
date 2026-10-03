"""
Section 1 Architecture Capability Audit (Prompt 557)
=====================================================

Read-only, point-in-time audit of Section 1 ("Core Infrastructure,
Diagnostics, and Learning Foundations", Prompt 500-570).

This module records the findings of a manual source-structure inspection
performed for Prompt 557. It does NOT introspect the codebase at import
time, does NOT compute anything dynamically, does NOT call into any other
subsystem, and does NOT mutate any project state. It is a fixed,
deterministic snapshot describing what existed in the project tree at the
time of the audit, expressed as plain data so it can be asserted on by a
test in the same way any other diagnostic snapshot in this project is
tested.

Per the audit's own rules (see docs/section1_architecture_capability_audit.md):
    - no scores
    - no rankings
    - no "best"/"worst" labels
    - no recommendations
    - no predictions
    - factual categories only, each backed by concrete evidence
      (file path / line reference / import relationship)

Distinguishing categories used throughout this audit:
    A. capability_changes_behavior   -> actually changes application behavior
    B. records_or_validates_only     -> only records/validates/diagnoses
                                         existing behavior
    C. structural_not_integrated     -> exists structurally, not
                                         meaningfully integrated
"""

BEHAVIOR_CHANGING = "capability_changes_behavior"
RECORDS_OR_VALIDATES_ONLY = "records_or_validates_only"
STRUCTURAL_NOT_INTEGRATED = "structural_not_integrated"

_VALID_KINDS = (BEHAVIOR_CHANGING, RECORDS_OR_VALIDATES_ONLY, STRUCTURAL_NOT_INTEGRATED)


def _entry(name, kind, evidence):
    if kind not in _VALID_KINDS:
        raise ValueError("invalid capability kind: %r" % (kind,))
    return {"name": name, "kind": kind, "evidence": evidence}


IMPLEMENTED_CORE_CAPABILITIES = [
    _entry(
        "agent_loop_orchestration",
        BEHAVIOR_CHANGING,
        "agent/agent_loop.py (3600 lines) wires planning, execution, "
        "test evaluation, code-change evaluation/rollback and self-upgrade "
        "adapters into one control flow invoked by Core.",
    ),
    _entry(
        "memory_system",
        BEHAVIOR_CHANGING,
        "memory/memory_system.py: SQLite-backed store (14 CREATE TABLE "
        "statements) used by Core, CapabilitySystem, KnowledgeSystem and "
        "others for persistence.",
    ),
    _entry(
        "reasoning_engine",
        BEHAVIOR_CHANGING,
        "reasoning/reasoning_engine.py + rule_registry.py + rules.py are "
        "imported by core/core.py and drive STATUS_ANSWERED responses.",
    ),
    _entry(
        "conversation_context_tracking",
        BEHAVIOR_CHANGING,
        "context/conversation_context.py, active_topic.py, relevance.py, "
        "topic_awareness.py, message_reference_resolution.py are imported "
        "and called from core/core.py to select relevant turns and resolve "
        "references before a response is produced.",
    ),
    _entry(
        "planning_and_goal_management",
        BEHAVIOR_CHANGING,
        "planning/goal_manager.py, plan_manager.py, planner.py, "
        "goal_detection.py are imported by core/core.py and by "
        "agent/agent_loop.py; goal-oriented input changes control flow.",
    ),
    _entry(
        "step_execution",
        BEHAVIOR_CHANGING,
        "execution/step_execution_preparation.py, "
        "step_execution_controller.py, execution_engine.py, "
        "plan_execution_controller.py are invoked from core/core.py and "
        "agent/agent_loop.py to actually run plan steps.",
    ),
    _entry(
        "ael_interpreter",
        BEHAVIOR_CHANGING,
        "ael/interpreter.py (AELInterpreter) is imported and instantiated "
        "in core/core.py; ael_parser.py/tokenizer.py/validator.py feed it.",
    ),
    _entry(
        "learned_knowledge_gate",
        BEHAVIOR_CHANGING,
        "learning/learned_knowledge_gate.py: evaluate_learned_knowledge_gate "
        "is called from core/core.py (~line 1061) and its verdict "
        "(last_learned_knowledge_gate) participates in response selection.",
    ),
    _entry(
        "understanding_engine",
        BEHAVIOR_CHANGING,
        "understanding/engine.py (UnderstandingEngine), term_extraction.py, "
        "sentence_analysis.py are imported and used in core/core.py to "
        "classify incoming messages.",
    ),
    _entry(
        "health_system",
        BEHAVIOR_CHANGING,
        "diagnostics/health_system.py (HealthSystem) is imported into "
        "core/core.py and exposes a live health check surface, distinct "
        "from the learned-knowledge diagnostic chain.",
    ),
]

PARTIALLY_IMPLEMENTED_CAPABILITIES = [
    _entry(
        "language_intelligence_core",
        STRUCTURAL_NOT_INTEGRATED,
        "language_intelligence/ contains 74 files (backends, correction "
        "pipeline, learned pattern/response modules) - substantially more "
        "than a Section 1 dependency would need. core/core.py imports and "
        "uses a subset (MeaningResolver, LearnedMeaningDisambiguator, "
        "ResponsePlanner, LanguageIntelligenceCore, etc.); a large portion "
        "of the correction/verification pipeline "
        "(correction_application_*.py, verified_correction_response_*.py) "
        "has no import found from core/core.py or agent/agent_loop.py and "
        "is only referenced from its own tests.",
    ),
    _entry(
        "self_upgrade_pipeline",
        STRUCTURAL_NOT_INTEGRATED,
        "self_upgrade/ has 31 modules (version_system, capability_"
        "evaluation, capability_correction_*) wired into agent/agent_loop.py "
        "for dry-run code-change evaluation; UpgradeSystem is imported into "
        "core/core.py, but the known pre-existing failing test "
        "test_no_stage_runs_twice_in_a_successful_lifecycle shows the "
        "lifecycle-stage wiring is not fully exercised end to end.",
    ),
    _entry(
        "execution_learning",
        RECORDS_OR_VALIDATES_ONLY,
        "learning/execution_learning.py + learning_record_store.py are "
        "imported into core/core.py and agent/agent_loop.py; they store "
        "LearningRecords from execution outcomes but do not themselves "
        "change which plan step is chosen next (the choice is made by "
        "planning/execution modules before the record is written).",
    ),
]

DIAGNOSTIC_ONLY_CAPABILITIES = [
    _entry(
        "learned_knowledge_statistics_chain",
        RECORDS_OR_VALIDATES_ONLY,
        "learning/learned_knowledge_statistics.py is 11,116 lines / "
        "564,499 bytes with 5 classes and 245 functions/methods. "
        "core/core.py imports exactly two names from it - "
        "LearnedKnowledgeDecisionStatistics and "
        "LearnedKnowledgeDiagnosticSnapshotHistory - both instantiated as "
        "counters/history stores (core/core.py line ~145). The remaining "
        "~200 module-level functions (the validate_learned_knowledge_"
        "filtered_trend_source_coverage_chain_stage_order_* family and "
        "siblings) are referenced only from the 49 test_learned_knowledge_*"
        " test files in tests/, not from any application module. "
        "core/core.py's own comment at line ~1049 labels the statistics "
        "counter itself 'diagnostic-only'.",
    ),
    _entry(
        "learned_knowledge_gate_trace",
        RECORDS_OR_VALIDATES_ONLY,
        "build_learned_knowledge_gate_trace() output is stored as "
        "last_learned_knowledge_gate_trace; core/core.py's own comment "
        "(line ~1041) states it is 'purely for later internal' use and is "
        "'never used in response generation'.",
    ),
    _entry(
        "capability_system_registry",
        STRUCTURAL_NOT_INTEGRATED,
        "capabilities/capability_system.py (73 lines): PLANNED_CAPABILITIES "
        "are registered with enabled=False, status='planned' by design "
        "(seed_planned_capabilities). The module's own docstring states "
        "capabilities 'are registered but disabled - they exist as named, "
        "tracked placeholders'.",
    ),
]

INTEGRATION_GAPS = [
    _entry(
        "language_intelligence_correction_pipeline_not_called_from_core",
        STRUCTURAL_NOT_INTEGRATED,
        "correction_application*.py, correction_learning_*.py and "
        "verified_correction_response_*.py (language_intelligence/) define "
        "a multi-stage correction-application/verification pipeline; no "
        "import of these names was found in core/core.py or "
        "agent/agent_loop.py at audit time - only in their own tests and "
        "each other.",
    ),
    _entry(
        "diagnostic_chain_not_surfaced_to_health_system",
        STRUCTURAL_NOT_INTEGRATED,
        "diagnostics/health_system.py does not import anything from "
        "learning/learned_knowledge_statistics.py, so the large validator "
        "chain's output is not exposed through the project's one live "
        "health-check surface.",
    ),
]

IMPORTANT_MISSING_FOUNDATION_CAPABILITIES = [
    _entry(
        "capabilities_remain_all_disabled",
        STRUCTURAL_NOT_INTEGRATED,
        "Every entry in capabilities.capability_system.PLANNED_CAPABILITIES "
        "(image_input, file_input, code_generation, code_analysis, "
        "ui_modification, project_creation, development_3d, "
        "game_development) is seeded with enabled=False; none has an "
        "enable path found in core/core.py or agent/agent_loop.py.",
    ),
    _entry(
        "self_upgrade_lifecycle_stage_double_invocation_gap",
        STRUCTURAL_NOT_INTEGRATED,
        "tests/test_self_upgrade_end_to_end_dry_run.py::"
        "NoAutomaticActivationTests::"
        "test_no_stage_runs_twice_in_a_successful_lifecycle fails "
        "(spy.call_count == 0, expected 1) on a clean run of the full "
        "suite, independent of this audit and independent of the "
        "learned-knowledge chain.",
    ),
]

REDUNDANT_OR_EXCESSIVELY_NESTED_DIAGNOSTIC_LAYERS = [
    _entry(
        "filtered_trend_source_coverage_chain_wrapping",
        RECORDS_OR_VALIDATES_ONLY,
        "learning/learned_knowledge_statistics.py contains a linear chain "
        "of validator functions, each wrapping the previous one's "
        "'_result': validate_learned_knowledge_filtered_trend_source_"
        "coverage_chain -> ..._chain_stage_order -> "
        "..._chain_stage_order_result -> ..._chain_stage_order_consistency "
        "-> ..._chain_stage_order_consistency_result -> "
        "..._complete_chain_consistency -> ..._complete_chain_consistency_"
        "result -> ..._complete_chain_consistency_validation -> "
        "..._complete_chain_consistency_validation_result -> "
        "..._complete_chain_validation_consistency -> "
        "..._complete_chain_validation_consistency_result -> "
        "..._complete_chain_validation_consistency_result_consistency -> "
        "..._complete_chain_validation_consistency_result_consistency_"
        "result (lines 8654-11116 of that file). Each layer validates the "
        "well-formedness of the previous layer's output structure; none "
        "changes what the underlying gate/response decision was.",
    ),
    _entry(
        "one_test_file_per_wrapper_layer",
        RECORDS_OR_VALIDATES_ONLY,
        "56 of the 296 test files in tests/ (test_learned_knowledge_*.py) "
        "exist to cover the statistics-chain wrapper family above, "
        "roughly one test file per added layer.",
    ),
]

# Smallest set of genuinely useful remaining tasks identified for Section 1.
# Deliberately not ranked or scored; listed in the order the audit
# encountered the underlying gap.
SECTION_1_COMPLETION_CANDIDATES = [
    "Decide, for each capability in "
    "capabilities.capability_system.PLANNED_CAPABILITIES, whether it is "
    "in scope for Section 1 sign-off or is explicitly deferred; the "
    "registry alone does not indicate which.",
    "Confirm whether the language_intelligence correction/verification "
    "pipeline (correction_application_*.py, verified_correction_"
    "response_*.py) is meant to be reachable from core/core.py in Section "
    "1, or is intentionally staged ahead for Section 2.",
    "Resolve or explicitly accept "
    "test_no_stage_runs_twice_in_a_successful_lifecycle as a known, "
    "tracked pre-existing gap (this audit does not attribute a cause).",
    "Record a decision on whether "
    "learning/learned_knowledge_statistics.py's validator-of-validator "
    "family should stop growing, since this audit found no application "
    "code path that consumes any layer past "
    "LearnedKnowledgeDecisionStatistics / "
    "LearnedKnowledgeDiagnosticSnapshotHistory.",
]

SECTION_1_READY_FOR_SECTION_2 = False

SECTION_1_READINESS_NOTES = [
    "Core Infrastructure capabilities (agent loop, memory, reasoning, "
    "context, planning, execution, AEL) are imported and called from "
    "core/core.py - see implemented_core_capabilities.",
    "Two Section-1-scoped items are open at audit time: all eight planned "
    "capabilities remain disabled by design, and one pre-existing test "
    "failure (test_no_stage_runs_twice_in_a_successful_lifecycle) is "
    "present in a full, unmodified test run.",
    "A substantial amount of code already exists under language_"
    "intelligence/ that overlaps with the stated scope of Section 2 "
    "('Language Intelligence and Request Understanding'); its presence "
    "does not by itself indicate Section 1 is incomplete, but it means "
    "Section 2 scope and Section 1 scope currently overlap in the source "
    "tree.",
]


def build_section1_architecture_capability_audit():
    """Return the full, deterministic Section 1 audit as plain data.

    Calling this function performs no I/O, no imports of other project
    subsystems, and no mutation of any state; it returns copies of the
    module-level constants above so callers cannot mutate the audit's
    own record by mutating the returned structure.
    """
    return {
        "implemented_core_capabilities": [dict(e) for e in IMPLEMENTED_CORE_CAPABILITIES],
        "partially_implemented_capabilities": [dict(e) for e in PARTIALLY_IMPLEMENTED_CAPABILITIES],
        "diagnostic_only_capabilities": [dict(e) for e in DIAGNOSTIC_ONLY_CAPABILITIES],
        "integration_gaps": [dict(e) for e in INTEGRATION_GAPS],
        "important_missing_foundation_capabilities": [
            dict(e) for e in IMPORTANT_MISSING_FOUNDATION_CAPABILITIES
        ],
        "redundant_or_excessively_nested_diagnostic_layers": [
            dict(e) for e in REDUNDANT_OR_EXCESSIVELY_NESTED_DIAGNOSTIC_LAYERS
        ],
        "section_1_completion_candidates": list(SECTION_1_COMPLETION_CANDIDATES),
        "section_1_ready_for_section_2": SECTION_1_READY_FOR_SECTION_2,
        "section_1_readiness_notes": list(SECTION_1_READINESS_NOTES),
    }
