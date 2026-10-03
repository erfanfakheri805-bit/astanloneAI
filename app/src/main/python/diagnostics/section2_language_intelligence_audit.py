"""
Section 2 Language Intelligence Architecture/Capability Audit (Prompt 559)
===========================================================================

Read-only, point-in-time audit of the existing "language_intelligence/"
system and its integration with Core, performed at the start of Section 2
("Language Intelligence and Request Understanding").

Like diagnostics/section1_architecture_capability_audit.py (Prompt 557),
this module is a fixed, deterministic data snapshot - it does not
introspect the codebase at import time, does not compute anything
dynamically, does not call into any other subsystem, and does not mutate
any project state.

Method: for every finding below, "integrated" means traced by an actual
import-graph reachability check from the 13 language_intelligence names
Core imports directly (core/core.py lines ~92-107), confirmed against
the real call sites in core/core.py's `_handle_conversation` /
`process_input`. "Not integrated" means grep-confirmed to have zero
importers outside language_intelligence/ and tests/ at audit time.

Category definitions (same three as the Prompt 557 audit):
    A. capability_changes_behavior   -> actually changes application
                                         behavior
    B. records_or_validates_only     -> only records/validates/diagnoses
                                         existing behavior
    C. structural_not_integrated     -> exists structurally but is not
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


TOTAL_LANGUAGE_INTELLIGENCE_FILES_INSPECTED = 74  # includes __init__.py

# ----------------------------------------------------------------------
# 1. implemented_and_core_integrated
# ----------------------------------------------------------------------
IMPLEMENTED_AND_CORE_INTEGRATED = [
    _entry(
        "language_intelligence_understand_call",
        BEHAVIOR_CHANGING,
        "core/core.py `_handle_conversation` step 1c calls "
        "self.language_intelligence.understand(text, context=..., "
        "relevant_context=..., resolved_reference=..., active_topic=...) "
        "on every non-AEL, non-goal, non-skill-matched message and "
        "stores the result as self.last_language_understanding.",
    ),
    _entry(
        "language_intelligence_generate_response_call",
        BEHAVIOR_CHANGING,
        "core/core.py `_handle_conversation` step 1d calls "
        "self.language_intelligence.generate_response(understanding, "
        "context=...) on every such message; if "
        "result.is_generated is True, its response_text is returned "
        "directly, short-circuiting the rest of `_handle_conversation` "
        "(steps 2-5: learning, reasoning, concept lookup, fallback).",
    ),
    _entry(
        "response_planning_ambiguity_handling",
        BEHAVIOR_CHANGING,
        "response_planning.py is imported directly by core/core.py "
        "(ResponsePlanner) and is transitively reachable from "
        "LanguageIntelligenceCore; STATUS_AMBIGUOUS is defined there and "
        "consumed by learned_response_pattern_selection.py, part of the "
        "reachable subgraph from Core's 13 direct imports.",
    ),
    _entry(
        "learned_pattern_and_meaning_apis",
        BEHAVIOR_CHANGING,
        "core/core.py exposes match_learned_pattern, teach_sentence_"
        "pattern, bind_pattern_meaning, resolve_pattern_meaning, "
        "extract_sentence_structure, resolve_language_meaning, "
        "disambiguate_learned_meaning as its own public methods, each "
        "delegating directly to the corresponding language_intelligence "
        "module instance built in __init__.",
    ),
    _entry(
        "goal_intent_classification_readonly",
        RECORDS_OR_VALIDATES_ONLY,
        "language_intelligence/deterministic_fallback_backend.py imports "
        "planning.goal_detection.is_goal_oriented and uses it only inside "
        "_classify_intent (a label on the understanding result); its own "
        "docstring states it 'never calls Core.create_goal or anything "
        "else with a side effect'.",
    ),
]

# ----------------------------------------------------------------------
# 2. implemented_but_not_core_integrated
# ----------------------------------------------------------------------
IMPLEMENTED_BUT_NOT_CORE_INTEGRATED = [
    _entry(
        "correction_application_pipeline",
        STRUCTURAL_NOT_INTEGRATED,
        "correction_application.py, correction_application_candidate.py, "
        "correction_application_candidate_readiness.py, "
        "correction_application_guarded.py, correction_application_"
        "request.py, correction_application_result.py, correction_"
        "application_result_usability.py, correction_application_result_"
        "validation.py, correction_application_target_validation.py, "
        "correction_application_verification.py, correction_application_"
        "verification_result.py - a static import-graph reachability "
        "check from Core's 13 direct language_intelligence imports found "
        "none of these 11 modules reachable. Each has its own test file "
        "(14 tests total across this family) exercising it in isolation.",
    ),
    _entry(
        "correction_feedback_and_learning_handoff",
        STRUCTURAL_NOT_INTEGRATED,
        "correction_feedback_record.py, correction_feedback_record_"
        "validation.py, correction_feedback_learning_input_adapter.py, "
        "correction_learning_exact_lookup_result.py, correction_learning_"
        "handoff_result.py, correction_learning_handoff_result_"
        "validation.py, correction_learning_handoff_to_learning_input_"
        "adapter.py, correction_learning_input_eligibility.py, "
        "correction_learning_input_handoff.py, correction_learning_"
        "input_retrieval.py, correction_learning_input_storage.py - none "
        "reachable from Core's imports; each individually tested.",
    ),
    _entry(
        "correction_lookup_family",
        STRUCTURAL_NOT_INTEGRATED,
        "correction_lookup_context.py, correction_lookup_selection.py, "
        "correction_lookup_usability.py - not reachable from Core's "
        "imports (response_generation_context.py has a "
        "`correction_lookup_context` transport field, but nothing in the "
        "Core-reachable subgraph ever builds a non-None value for it).",
    ),
    _entry(
        "verified_correction_response_family",
        STRUCTURAL_NOT_INTEGRATED,
        "verified_correction_response_input.py, "
        "verified_correction_response_input_adapter.py, "
        "verified_correction_response_input_extraction.py, "
        "verified_correction_response_input_usability.py, "
        "verified_correction_response_instruction.py, "
        "verified_correction_response_instruction_adapter.py - not "
        "reachable from Core's imports. Note: DeterministicFallbackBackend."
        "generate_response accepts a `verified_correction_instruction` "
        "parameter 'for interface parity' but its own comment states it "
        "is 'not used' since the backend generates no text.",
    ),
    _entry(
        "corrected_response_target_and_context",
        STRUCTURAL_NOT_INTEGRATED,
        "corrected_response_target.py and corrected_response_target_"
        "context.py are not reachable from Core's imports (distinct from "
        "corrected_response_target_selection.py, which IS reachable and "
        "IS integrated - see integration_gaps for the distinction).",
    ),
    _entry(
        "correction_understanding_result_family",
        STRUCTURAL_NOT_INTEGRATED,
        "correction_understanding_result.py, correction_understanding_"
        "result_completeness.py, correction_understanding_result_"
        "validation.py are not reachable from Core's imports, although "
        "correction_understanding.py itself IS reachable (only its "
        "_is_blank helper is used, by corrected_response_target_"
        "selection.py).",
    ),
]

# ----------------------------------------------------------------------
# 3. partially_implemented
# ----------------------------------------------------------------------
PARTIALLY_IMPLEMENTED = [
    _entry(
        "language_intelligence_core_response_generation",
        RECORDS_OR_VALIDATES_ONLY,
        "core/core.py's own comment (module docstring around "
        "`_handle_conversation` step 1d) states: 'With today's only "
        "configured backend (DeterministicFallbackBackend...) this "
        "always reports STATUS_DEFERRED... so ordinary conversation is "
        "completely unaffected by this step's presence.' Confirmed in "
        "source: DeterministicFallbackBackend.generate_response "
        "unconditionally returns ResponseGenerationResult(status="
        "STATUS_DEFERRED, response_text=None, ...) - STATUS_GENERATED is "
        "not even imported by that file. The call happens on every "
        "message (implemented_and_core_integrated), but with the current "
        "default configuration it never actually determines a reply.",
    ),
    _entry(
        "local_model_backend",
        STRUCTURAL_NOT_INTEGRATED,
        "language_intelligence/local_model_backend.py "
        "(LocalLanguageModelBackend) is only wired in if the caller "
        "explicitly invokes Core.use_local_language_model(...) "
        "(core/core.py line ~1127); it is never constructed in "
        "Core.__init__ and no other code path calls "
        "use_local_language_model automatically.",
    ),
    _entry(
        "response_generation_context_correction_transport_fields",
        STRUCTURAL_NOT_INTEGRATED,
        "response_generation_context.py's ResponseGenerationContext "
        "carries correction_application_candidate, correction_"
        "application_result and correction_lookup_context as fields, "
        "and generation_context_from_understanding() reads them off the "
        "understanding object via getattr(..., None). A project-wide "
        "grep for `correction_application_candidate =` found no "
        "assignment outside the correction-pipeline modules themselves "
        "(see implemented_but_not_core_integrated); understanding/ "
        "(Core's UnderstandingEngine) never sets it, so on every real "
        "Core-driven call these fields are None. The tests named "
        "'*_in_response_generation.py' explicitly document this as "
        "'transport only... nothing here builds a candidate [or] applies "
        "a stored correction.'",
    ),
]

# ----------------------------------------------------------------------
# 4. diagnostic_or_test_only
# ----------------------------------------------------------------------
DIAGNOSTIC_OR_TEST_ONLY = [
    _entry(
        "no_dedicated_language_intelligence_diagnostic_chain_found",
        STRUCTURAL_NOT_INTEGRATED,
        "Unlike learning/learned_knowledge_statistics.py (Section 1's "
        "validator-of-validator chain), language_intelligence/ has no "
        "single file playing that role at audit time. The closest "
        "analogues are the correction_application_result_validation.py / "
        "correction_application_result_usability.py /correction_"
        "understanding_result_validation.py / correction_understanding_"
        "result_completeness.py modules, listed under "
        "implemented_but_not_core_integrated and redundant_or_"
        "overlapping_components rather than here, since they validate "
        "their own package's data rather than being a separate "
        "diagnostics-only add-on.",
    ),
]

# ----------------------------------------------------------------------
# 5. integration_gaps
# ----------------------------------------------------------------------
INTEGRATION_GAPS = [
    _entry(
        "correction_application_never_invoked_from_understanding",
        STRUCTURAL_NOT_INTEGRATED,
        "understanding/ (Core's UnderstandingEngine, reachable from "
        "process_input) never imports or calls anything from the "
        "correction_application_*.py family, so no CorrectionApplication"
        "Candidate is ever produced on a real Core-driven request for "
        "response_generation_context.py's transport field to carry.",
    ),
    _entry(
        "corrected_response_target_selection_reachable_but_its_sibling_isnt",
        STRUCTURAL_NOT_INTEGRATED,
        "corrected_response_target_selection.py IS reachable (via "
        "response_generation.py) and is integrated, but corrected_"
        "response_target.py and corrected_response_target_context.py - "
        "similarly named, adjacent files - are not imported by it or by "
        "anything else reachable from Core. The selection logic and the "
        "target/context data types it would presumably act on are "
        "disconnected.",
    ),
    _entry(
        "agent_loop_has_no_language_intelligence_import",
        STRUCTURAL_NOT_INTEGRATED,
        "grep across agent/agent_loop.py found zero references to "
        "language_intelligence; the self-upgrade/code-change pipeline "
        "does not use language understanding, correction, or response "
        "generation in any way.",
    ),
    _entry(
        "correction_feedback_learning_input_adapter_not_wired_to_learning_system",
        STRUCTURAL_NOT_INTEGRATED,
        "correction_feedback_learning_input_adapter.py and correction_"
        "learning_input_storage.py exist to hand data to learning/ "
        "(LearningSystem/LearningRecordStore), but since nothing upstream "
        "of them is reachable from Core, they are never invoked on a "
        "real request; learning/learning_system.py's own imports do not "
        "reference them.",
    ),
]

# ----------------------------------------------------------------------
# 6. important_missing_capabilities
# ----------------------------------------------------------------------
IMPORTANT_MISSING_CAPABILITIES = [
    _entry(
        "no_real_text_generation_backend_configured_by_default",
        STRUCTURAL_NOT_INTEGRATED,
        "The only backend Core configures by default (Deterministic"
        "FallbackBackend) never returns STATUS_GENERATED; a request-"
        "understanding foundation needs at least one backend capable of "
        "actually producing response_text through this path, or an "
        "explicit, documented decision that this path stays deferred-"
        "only for now.",
    ),
    _entry(
        "no_path_from_understanding_to_correction_application",
        STRUCTURAL_NOT_INTEGRATED,
        "For the existing correction/verification pipeline to be a "
        "usable capability rather than isolated, tested code, "
        "understanding/ or language_intelligence_core.py needs a call "
        "path that actually constructs a CorrectionApplicationCandidate "
        "from a real user message and passes it through to response "
        "generation.",
    ),
]

# ----------------------------------------------------------------------
# 7. redundant_or_overlapping_components (NOT modified in this prompt)
# ----------------------------------------------------------------------
REDUNDANT_OR_OVERLAPPING_COMPONENTS = [
    _entry(
        "correction_application_result_trio",
        RECORDS_OR_VALIDATES_ONLY,
        "correction_application_result.py, correction_application_"
        "result_validation.py and correction_application_result_"
        "usability.py each wrap the previous module's output "
        "(result -> validate the result's shape -> judge the validated "
        "result's usability), the same base-plus-validate-plus-judge "
        "pattern seen at larger scale in Section 1's learned_knowledge_"
        "statistics.py chain, though far smaller here (3 layers, not "
        "13+). Not modified in this prompt per the Section 1 scope "
        "restriction carried forward.",
    ),
    _entry(
        "correction_understanding_result_trio",
        RECORDS_OR_VALIDATES_ONLY,
        "correction_understanding_result.py, correction_understanding_"
        "result_completeness.py and correction_understanding_result_"
        "validation.py show the same 3-layer wrap pattern as the "
        "correction_application_result trio above, applied to a "
        "different base object.",
    ),
    _entry(
        "verified_correction_response_input_vs_instruction",
        STRUCTURAL_NOT_INTEGRATED,
        "verified_correction_response_input*.py (3 files: input, "
        "input_adapter, input_extraction, input_usability - 4 files) and "
        "verified_correction_response_instruction*.py (2 files: "
        "instruction, instruction_adapter) are similarly named, both "
        "unreachable from Core, and their responsibilities (carrying a "
        "verified correction in vs. carrying an instruction to act on "
        "one out) overlap enough that a reader inspecting only file "
        "names could not easily tell them apart without opening both.",
    ),
]

# ----------------------------------------------------------------------
# 8. section_2_completion_candidates
# ----------------------------------------------------------------------
SECTION_2_COMPLETION_CANDIDATES = [
    "Decide whether the correction/verification pipeline (36 unreachable "
    "modules) is in scope for Section 2 integration, or is intentionally "
    "staged for a later section; this audit found no caller path, not a "
    "missing feature per se.",
    "If in scope: add the smallest call from understanding/ (or "
    "language_intelligence_core.py) that actually constructs a "
    "CorrectionApplicationCandidate from a real message and threads it "
    "into response_generation_context.py's existing transport fields, "
    "rather than adding a new architecture layer.",
    "Decide whether DeterministicFallbackBackend should remain "
    "permanently deferred-only, or whether a real STATUS_GENERATED-"
    "capable backend belongs in Section 2's scope.",
    "Resolve the naming/responsibility overlap between corrected_"
    "response_target_selection.py (integrated) and its unreachable "
    "siblings corrected_response_target.py / corrected_response_target_"
    "context.py, without deleting or refactoring either in this prompt.",
]

REQUEST_PROCESSING_PATH = [
    "USER INPUT (raw_text)",
    "Core.process_input -> InputSystem.normalize",
    "Core.process_input -> Parser.parse (kind: ael | other)",
    "  ael branch -> Core._handle_ael -> AELInterpreter.run -> reply",
    "  other branch -> Core._handle_goal_or_conversation",
    "    -> planning.goal_detection.is_goal_oriented(text)",
    "       goal-oriented -> Core.create_goal -> formatted 'GOAL CREATED' reply",
    "       not goal-oriented -> Core._handle_conversation",
    "         1. SkillSystem.find_matching_skill (short-circuits if matched)",
    "         1b. context/relevance.py + message_reference_resolution.py "
    "+ active_topic.py (read-only)",
    "         1c. LanguageIntelligenceCore.understand(...) -> "
    "LanguageUnderstandingResult (recorded; does not select the branch "
    "taken below)",
    "         1d. LanguageIntelligenceCore.generate_response(...) -> "
    "ResponseGenerationResult; if is_generated, returns response_text "
    "directly (never happens with the default "
    "DeterministicFallbackBackend)",
    "         2. Core.learn_from_text -> UnderstandingEngine + "
    "LearningSystem (returns early if something new was learned)",
    "         3. ReasoningEngine.reason(text) (returns early if "
    "STATUS_ANSWERED)",
    "         4. KnowledgeSystem concept lookup fallback",
    "         5. Core._construct_fallback_reply",
    "Core.process_input -> memory.log_message + context.add_turn",
    "RESPONSE (string) returned to caller",
]

SMALLEST_SAFE_INTEGRATION_POINT = (
    "understanding/ (specifically wherever UnderstandingEngine or "
    "Core._attach_learned_knowledge already builds attributes read by "
    "generation_context_from_understanding via getattr(..., None)) is "
    "the smallest safe point to connect the correction pipeline: adding "
    "a call there that sets `understanding.correction_application_"
    "candidate` when a real correction is detected would reach an "
    "already-existing, already-wired transport field in "
    "response_generation_context.py without changing Core's control "
    "flow, LanguageIntelligenceCore's structure, or any other "
    "subsystem."
)

RECOMMENDED_NEXT_IMPLEMENTATION_TARGET_PROMPT_560 = (
    "Wire a single, minimal call path from a real correction signal "
    "(e.g. the existing understanding/correction_detection.py candidate "
    "already used by _build_correction_understanding) through "
    "correction_application_candidate.py into the existing "
    "response_generation_context.py transport field - the smallest "
    "change that would move the correction/verification pipeline from "
    "implemented_but_not_core_integrated to implemented_and_core_"
    "integrated for at least one concrete case, without adding new "
    "architecture or touching the Section 1 validator chain. NOT "
    "implemented in Prompt 559; left for Prompt 560 per this prompt's "
    "audit-only scope."
)


def build_section2_language_intelligence_audit():
    """Return the full, deterministic Section 2 audit as plain data.

    Performs no I/O, imports nothing from other project subsystems, and
    mutates no state; returns fresh copies so callers cannot mutate this
    module's own record by mutating the returned structure.
    """
    return {
        "total_language_intelligence_files_inspected": TOTAL_LANGUAGE_INTELLIGENCE_FILES_INSPECTED,
        "implemented_and_core_integrated": [dict(e) for e in IMPLEMENTED_AND_CORE_INTEGRATED],
        "implemented_but_not_core_integrated": [dict(e) for e in IMPLEMENTED_BUT_NOT_CORE_INTEGRATED],
        "partially_implemented": [dict(e) for e in PARTIALLY_IMPLEMENTED],
        "diagnostic_or_test_only": [dict(e) for e in DIAGNOSTIC_OR_TEST_ONLY],
        "integration_gaps": [dict(e) for e in INTEGRATION_GAPS],
        "important_missing_capabilities": [dict(e) for e in IMPORTANT_MISSING_CAPABILITIES],
        "redundant_or_overlapping_components": [dict(e) for e in REDUNDANT_OR_OVERLAPPING_COMPONENTS],
        "section_2_completion_candidates": list(SECTION_2_COMPLETION_CANDIDATES),
        "request_processing_path": list(REQUEST_PROCESSING_PATH),
        "smallest_safe_integration_point": SMALLEST_SAFE_INTEGRATION_POINT,
        "recommended_next_implementation_target_prompt_560":
            RECOMMENDED_NEXT_IMPLEMENTATION_TARGET_PROMPT_560,
    }
