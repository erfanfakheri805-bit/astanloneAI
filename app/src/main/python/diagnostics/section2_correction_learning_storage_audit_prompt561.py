"""
Section 2 Correction-Learning Storage/Retrieval Architecture Audit
(Prompt 561)
===========================================================================

Read-only, point-in-time audit of the EXISTING correction-learning
storage and retrieval infrastructure under `language_intelligence/`,
performed per Prompt 560's own "next Section 2 target" note (see
`docs/section2_language_intelligence_prompt560_integration.md`).

Like `diagnostics/section1_architecture_capability_audit.py` (Prompt
557) and `diagnostics/section2_language_intelligence_audit.py` (Prompt
559), this module is a fixed, deterministic data snapshot: it does not
introspect the codebase at import time, does not compute anything
dynamically, does not call into any other subsystem, and does not
mutate any project state. No storage system, database, or memory
system was implemented, duplicated, or modified to produce this audit
- it is AUDIT ONLY, exactly as Prompt 561 requires.

Category definitions (the six Prompt 561 asked for):
    IMPLEMENTED_AND_WORKING        - genuinely works today, in isolation
    IMPLEMENTED_BUT_NOT_INTEGRATED - works, but not reached from the
                                      normal Core runtime path
    PARTIALLY_IMPLEMENTED          - exists but needs more work before
                                      it can reliably support correction
                                      learning end to end
    MISSING                        - does not exist at all
    DUPLICATE_OR_OVERLAPPING       - existing storage/retrieval already
                                      provides the functionality under
                                      another name/path
    INTEGRATION_GAP                - a specific missing connection
                                      between correction understanding,
                                      correction learning, storage,
                                      retrieval, and Core
"""

IMPLEMENTED_AND_WORKING = "implemented_and_working"
IMPLEMENTED_BUT_NOT_INTEGRATED = "implemented_but_not_integrated"
PARTIALLY_IMPLEMENTED = "partially_implemented"
MISSING = "missing"
DUPLICATE_OR_OVERLAPPING = "duplicate_or_overlapping"
INTEGRATION_GAP = "integration_gap"

_VALID_KINDS = (
    IMPLEMENTED_AND_WORKING,
    IMPLEMENTED_BUT_NOT_INTEGRATED,
    PARTIALLY_IMPLEMENTED,
    MISSING,
    DUPLICATE_OR_OVERLAPPING,
    INTEGRATION_GAP,
)


def _entry(name, kind, evidence):
    if kind not in _VALID_KINDS:
        raise ValueError("invalid finding kind: %r" % (kind,))
    return {"name": name, "kind": kind, "evidence": evidence}


FILES_INSPECTED = [
    "language_intelligence/correction_understanding.py",
    "language_intelligence/correction_understanding_result.py",
    "language_intelligence/correction_feedback_record.py",
    "language_intelligence/correction_feedback_record_validation.py",
    "language_intelligence/correction_feedback_learning_input_adapter.py",
    "language_intelligence/correction_learning_input_eligibility.py",
    "language_intelligence/correction_learning_input_handoff.py",
    "language_intelligence/correction_learning_handoff_result.py",
    "language_intelligence/correction_learning_handoff_result_validation.py",
    "language_intelligence/correction_learning_handoff_to_learning_input_adapter.py",
    "language_intelligence/correction_learning_input_storage.py",
    "language_intelligence/correction_learning_input_retrieval.py",
    "language_intelligence/correction_learning_exact_lookup_result.py",
    "language_intelligence/correction_lookup_context.py",
    "language_intelligence/correction_lookup_selection.py",
    "language_intelligence/correction_lookup_usability.py",
    "language_intelligence/correction_application_candidate.py",
    "language_intelligence/correction_application_candidate_readiness.py",
    "language_intelligence/response_generation_context.py",
    "language_intelligence/language_learning_store.py",
    "memory/memory_system.py",
    "core/core.py",
    "understanding/correction_detection.py",
    "understanding/engine.py",
]

TOTAL_FILES_INSPECTED = len(FILES_INSPECTED)

# ----------------------------------------------------------------------
# 1. implemented_and_working
# ----------------------------------------------------------------------
IMPLEMENTED_AND_WORKING_FINDINGS = [
    _entry(
        "sqlite_backed_language_learning_store",
        IMPLEMENTED_AND_WORKING,
        "Core owns exactly one LanguageLearningStore instance "
        "(core/core.py: `self.language_learning = "
        "LanguageLearningStore(self.memory)`), itself backed by the "
        "project's one existing SQLite-backed MemorySystem via the "
        "`language_learning_items` table (schema migration 5, Prompt "
        "416) - the same store every other structured subsystem "
        "(knowledge, skills, rules) already persists through. No "
        "second database exists or is needed.",
    ),
    _entry(
        "correction_learning_input_storage_module",
        IMPLEMENTED_AND_WORKING,
        "language_intelligence/correction_learning_input_storage.py "
        "(Prompt 461) `store_accepted_correction_learning_input"
        "(handoff_result, learning_input, store)` correctly gates on "
        "an ACCEPTED CorrectionLearningHandoffResult, converts via "
        "Prompt 460's adapter, and calls the existing "
        "`store.learn_item(**converted)`. Exercised in isolation by "
        "`tests/test_correction_learning_input_storage.py`; works as "
        "documented when called directly with a real store.",
    ),
    _entry(
        "correction_learning_input_retrieval_module",
        IMPLEMENTED_AND_WORKING,
        "language_intelligence/correction_learning_input_retrieval.py "
        "(Prompts 462-463) `retrieve_stored_correction_learning_input"
        "(store, language, original_expression)` and "
        "`lookup_stored_correction_learning_input_by_original_"
        "expression(store, original_expression, language=None)` are "
        "direct, read-only pass-throughs to the existing "
        "`LanguageLearningStore.get_item()`/`find_items()` (Prompt "
        "416/418). Exercised in isolation by "
        "`tests/test_correction_learning_input_retrieval.py` and "
        "`tests/test_correction_learning_exact_lookup_by_original_"
        "expression.py`; works as documented when called directly.",
    ),
    _entry(
        "correction_lookup_to_application_candidate_chain",
        IMPLEMENTED_AND_WORKING,
        "The full read path CorrectionLearningExactLookupResult "
        "(correction_learning_exact_lookup_result.py, Prompt 464) -> "
        "CorrectionLookupContext (correction_lookup_context.py, "
        "Prompt 465) -> CorrectionSelectionResult "
        "(correction_lookup_selection.select_unique_stored_"
        "correction(), Prompt 469) -> CorrectionApplicationCandidate "
        "(correction_application_candidate.build_correction_"
        "application_candidate(), Prompt 470) is internally complete "
        "and self-consistent: each stage imports only its immediate "
        "predecessor's real output type, never a raw dict shortcut, "
        "and each has its own passing test file.",
    ),
]

# ----------------------------------------------------------------------
# 2. implemented_but_not_integrated
# ----------------------------------------------------------------------
IMPLEMENTED_BUT_NOT_INTEGRATED_FINDINGS = [
    _entry(
        "correction_feedback_and_handoff_family_unreached_from_core",
        IMPLEMENTED_BUT_NOT_INTEGRATED,
        "Grep-confirmed zero importers outside language_intelligence/ "
        "and tests/ for: correction_feedback_record.py, "
        "_validation.py, correction_feedback_learning_input_adapter.py, "
        "correction_learning_input_eligibility.py, "
        "correction_learning_input_handoff.py, "
        "correction_learning_handoff_result.py, "
        "_result_validation.py, and "
        "correction_learning_handoff_to_learning_input_adapter.py. "
        "Every one of these has a passing, isolated test file; none is "
        "reachable from core/core.py or understanding/.",
    ),
    _entry(
        "storage_and_retrieval_modules_unreached_from_core",
        IMPLEMENTED_BUT_NOT_INTEGRATED,
        "correction_learning_input_storage.py and "
        "_retrieval.py themselves have zero importers outside "
        "language_intelligence/ and tests/ (confirmed by grep at audit "
        "time). Nothing in core/core.py or understanding/ ever calls "
        "store_accepted_correction_learning_input(...) or "
        "retrieve_stored_correction_learning_input(...)/"
        "lookup_stored_correction_learning_input_by_original_"
        "expression(...), so Core's own real LanguageLearningStore "
        "instance (`self.language_learning`) is never written to or "
        "read from for a correction, even though the storage/"
        "retrieval code that would do so already works.",
    ),
    _entry(
        "lookup_and_candidate_family_unreached_from_core",
        IMPLEMENTED_BUT_NOT_INTEGRATED,
        "correction_learning_exact_lookup_result.py, "
        "correction_lookup_context.py, correction_lookup_selection.py, "
        "correction_lookup_usability.py, "
        "correction_application_candidate.py, and "
        "_candidate_readiness.py all have zero importers outside "
        "language_intelligence/ and tests/. "
        "response_generation_context.py's own "
        "`correction_application_candidate` and "
        "`correction_lookup_context` transport fields are read via "
        "`getattr(understanding, ..., None)` but a project-wide grep "
        "found no code outside these modules' own package that ever "
        "assigns them, so both are always None on every real Core "
        "call (matches Prompt 559's audit finding, independently "
        "reconfirmed here).",
    ),
]

# ----------------------------------------------------------------------
# 3. partially_implemented
# ----------------------------------------------------------------------
PARTIALLY_IMPLEMENTED_FINDINGS = [
    _entry(
        "correction_understanding_object_discarded_before_core_sees_it",
        PARTIALLY_IMPLEMENTED,
        "DeterministicFallbackBackend._build_correction_understanding() "
        "calls build_correction_understanding(...) (correction_"
        "understanding.py), which DOES return a real "
        "CorrectionUnderstandingResult object - but the backend then "
        "returns `correction.to_dict()`, so only a plain dict ever "
        "reaches Core (`self.last_language_understanding."
        "correction_understanding`, accessed via `[\"status\"]`/`.get"
        "(...)` in core.py). The object itself is discarded. Every "
        "downstream stage (map_correction_understanding_to_result() in "
        "correction_understanding_result.py) requires the ORIGINAL "
        "object, not the dict, so today's Core-visible data cannot "
        "feed the rest of the chain without first being reconstructed.",
    ),
    _entry(
        "learning_input_handoff_reachable_only_from_a_correction_"
        "feedback_record_that_is_never_built",
        PARTIALLY_IMPLEMENTED,
        "The eligibility/handoff/storage chain is only reachable from "
        "map_correction_understanding_result_to_feedback_record() "
        "(correction_feedback_record.py), which itself requires a "
        "correction_understanding_result.CorrectionUnderstandingResult "
        "- the wrapper object one level below the discarded object "
        "above. Nothing in the current codebase ever constructs one "
        "from a real Core message; only test files do. The full "
        "storage write path is code-complete but has never executed "
        "outside a test.",
    ),
]

# ----------------------------------------------------------------------
# 4. missing
# ----------------------------------------------------------------------
MISSING_FINDINGS = [
    _entry(
        "no_core_owned_call_site_for_correction_learning_write_or_read",
        MISSING,
        "No function anywhere in core/core.py or understanding/ calls "
        "any correction-learning storage or retrieval function with "
        "Core's own `self.language_learning` store instance. This is "
        "the one genuinely missing piece; it is a missing CALL, not a "
        "missing capability - every function it would call already "
        "exists and already works (see implemented_and_working above).",
    ),
]

# ----------------------------------------------------------------------
# 5. duplicate_or_overlapping
# ----------------------------------------------------------------------
DUPLICATE_OR_OVERLAPPING_FINDINGS = [
    _entry(
        "two_classes_both_named_correctionunderstandingresult",
        DUPLICATE_OR_OVERLAPPING,
        "correction_understanding.py defines a class "
        "`CorrectionUnderstandingResult` (Prompt 439, the one Core's "
        "backend actually builds and then flattens via `.to_dict()`). "
        "correction_understanding_result.py (Prompt 441) imports that "
        "SAME class aliased as `CorrectionUnderstanding` and then "
        "defines its OWN, DIFFERENT class also named "
        "`CorrectionUnderstandingResult` in the same package. Two "
        "distinct classes share one name across two files; nothing was "
        "renamed to disambiguate. This is a real naming collision, not "
        "just a documentation nit - `isinstance` checks in "
        "map_correction_understanding_to_result() only work because "
        "the import alias renames the first one at import time.",
    ),
    _entry(
        "two_write_paths_to_the_same_learn_item_call",
        DUPLICATE_OR_OVERLAPPING,
        "handoff_correction_learning_input_with_result(learning_input, "
        "store) (Prompt 458) already performs the real write - it "
        "calls handoff_correction_learning_input(), which itself calls "
        "store.learn_item() when the input is eligible - and reports "
        "the outcome as an ACCEPTED/REJECTED/FAILED "
        "CorrectionLearningHandoffResult. "
        "store_accepted_correction_learning_input(handoff_result, "
        "learning_input, store) (Prompt 461) then requires that SAME "
        "ACCEPTED result plus the SAME original learning_input dict, "
        "and calls store.learn_item() a SECOND time for the identical "
        "data. Because learn_item() upserts by (language, item_type, "
        "normalized key), the second call is harmless (it updates the "
        "same row rather than duplicating it) but it is a genuine "
        "second call doing the first call's job again. A correct "
        "integration must use exactly ONE of these two entry points, "
        "not both in sequence.",
    ),
]

# ----------------------------------------------------------------------
# 6. integration_gaps
# ----------------------------------------------------------------------
INTEGRATION_GAP_FINDINGS = [
    _entry(
        "detection_to_understanding_gap",
        INTEGRATION_GAP,
        "USER CORRECTS SOMETHING -> correction detection: EXISTS and "
        "connected (understanding/correction_detection.py's candidate, "
        "consumed by DeterministicFallbackBackend._build_correction_"
        "understanding(), unchanged since Prompt 440).",
    ),
    _entry(
        "understanding_to_learning_input_gap",
        INTEGRATION_GAP,
        "correction understanding -> learning input: BROKEN. The real "
        "CorrectionUnderstandingResult object built by "
        "build_correction_understanding() is flattened to a dict "
        "(`.to_dict()`) before Core ever sees it, and nothing "
        "reconstructs it afterward. Every function needed to turn a "
        "resolved correction into a learning-input dict "
        "(map_correction_understanding_to_result -> map_correction_"
        "understanding_result_to_feedback_record -> convert_"
        "correction_feedback_to_learning_input) exists and is tested, "
        "but none of them is ever called with real data - only the "
        "discarded object could feed the first of the three, and it no "
        "longer exists by the time Core would need it.",
    ),
    _entry(
        "learning_input_to_storage_gap",
        INTEGRATION_GAP,
        "learning input -> storage: BROKEN only for the reason above "
        "(no learning_input dict is ever produced from a real "
        "message). The storage call itself "
        "(handoff_correction_learning_input_with_result -> "
        "store.learn_item()) is fully implemented and would work "
        "immediately if given a real learning_input dict and Core's "
        "own `self.language_learning` store.",
    ),
    _entry(
        "storage_to_retrieval_gap",
        INTEGRATION_GAP,
        "storage -> retrieval: NOT BROKEN, but UNEXERCISED end to end. "
        "retrieve_stored_correction_learning_input() / "
        "lookup_stored_correction_learning_input_by_original_"
        "expression() correctly read back whatever "
        "store_accepted_correction_learning_input() or "
        "handoff_correction_learning_input() wrote, using the same "
        "(language, item_type, key) identity - confirmed by their own "
        "isolated tests - but since nothing ever writes a real "
        "correction row (see above), nothing ever has real data to "
        "retrieve either.",
    ),
    _entry(
        "retrieval_to_candidate_gap",
        INTEGRATION_GAP,
        "retrieval -> correction application candidate: NOT BROKEN, but "
        "UNEXERCISED end to end for the same reason, AND never called "
        "from anywhere Core-reachable regardless "
        "(correction_lookup_selection.select_unique_stored_correction() "
        "has zero non-test, non-package importers).",
    ),
    _entry(
        "candidate_to_core_response_gap",
        INTEGRATION_GAP,
        "correction application candidate -> Core response/application: "
        "BROKEN. response_generation_context.py's "
        "`correction_application_candidate` transport field exists and "
        "is read via getattr(..., None), but is never assigned by any "
        "Core-reachable code (matches Prompt 559's finding; independently "
        "reconfirmed by grep at this audit's time).",
    ),
]

REQUEST_LIFECYCLE_TRACE = [
    "USER CORRECTS SOMETHING",
    "-> correction detection (understanding/correction_detection.py): "
    "CONNECTED (Prompt 440, unchanged)",
    "-> correction understanding (correction_understanding.py, via "
    "DeterministicFallbackBackend._build_correction_understanding): "
    "CONNECTED, but its output is flattened to a plain dict "
    "(`.to_dict()`) before Core stores it - the richer object is "
    "discarded at this exact step",
    "-> learning input (correction_feedback_learning_input_adapter.py "
    "via correction_feedback_record.py): NOT CONNECTED - nothing "
    "reconstructs the discarded object or otherwise builds a "
    "CorrectionFeedbackRecord from real Core data",
    "-> storage (correction_learning_input_storage.py / "
    "correction_learning_handoff_result.py): NOT CONNECTED for the "
    "same reason, though the storage call itself is fully implemented "
    "and Core already owns a real, SQLite-backed "
    "LanguageLearningStore (`self.language_learning`) it could be "
    "given",
    "-> retrieval (correction_learning_input_retrieval.py): NOT "
    "CONNECTED for the same reason, though fully implemented",
    "-> correction application candidate "
    "(correction_application_candidate.py, via correction_lookup_"
    "selection.py): NOT CONNECTED - zero Core-reachable callers, "
    "independent of the storage gap above",
    "-> Core response/application "
    "(response_generation_context.py's transport field): NOT "
    "CONNECTED - the field exists and is read, but nothing assigns it",
]

CAN_EXISTING_STORAGE_SAFELY_SUPPORT_THIS = (
    "Yes, without duplication. Core already owns exactly one "
    "LanguageLearningStore instance (`self.language_learning`, "
    "core/core.py, Prompt 416), itself backed by the project's one "
    "existing SQLite-backed MemorySystem. correction_learning_input_"
    "storage.py and _retrieval.py already write to and read from that "
    "exact store via its existing learn_item()/get_item()/find_items() "
    "API, under the existing ITEM_TYPE_CORRECTION item type. No new "
    "database, table, or memory system is needed - only a real call "
    "site that supplies Core's own store instance and real data built "
    "from a real correction."
)

SMALLEST_IMPLEMENTATION_TARGET_PROMPT_562 = (
    "Add one small, explicit call sequence reachable from Core's "
    "existing step 1e (core.py, where `correction_understanding[\"status\"]"
    " == CORRECTION_STATUS_RESOLVED` is already checked) that: "
    "(1) reconstructs a correction_understanding.CorrectionUnderstanding"
    "Result from the dict Core already has (its to_dict() keys already "
    "match that class's constructor keyword arguments exactly, so this "
    "is a direct, lossless reconstruction, not new logic); "
    "(2) passes it through the EXISTING, already-tested chain - "
    "map_correction_understanding_to_result() -> map_correction_"
    "understanding_result_to_feedback_record() -> convert_correction_"
    "feedback_to_learning_input(); "
    "(3) calls handoff_correction_learning_input_with_result(learning_"
    "input, self.language_learning) EXACTLY ONCE (never followed by "
    "store_accepted_correction_learning_input() for the same data - "
    "see the duplicate_or_overlapping finding above) using Core's own "
    "real store. No new module, class, or storage mechanism is "
    "required; every function this calls already exists and already "
    "has a passing test. Retrieval and CorrectionApplicationCandidate "
    "wiring (the remaining two integration gaps) are intentionally "
    "OUT of this smallest target and left for a later prompt, since "
    "they depend on a second, later message referencing an "
    "already-stored correction - a distinct trigger from the one "
    "storage needs."
)


def build_correction_learning_storage_audit():
    """Return the full, deterministic Prompt 561 audit as plain data.

    Performs no I/O, imports nothing from other project subsystems, and
    mutates no state; returns fresh copies so callers cannot mutate this
    module's own record by mutating the returned structure.
    """
    return {
        "total_files_inspected": TOTAL_FILES_INSPECTED,
        "files_inspected": list(FILES_INSPECTED),
        "implemented_and_working": [dict(e) for e in IMPLEMENTED_AND_WORKING_FINDINGS],
        "implemented_but_not_integrated": [
            dict(e) for e in IMPLEMENTED_BUT_NOT_INTEGRATED_FINDINGS
        ],
        "partially_implemented": [dict(e) for e in PARTIALLY_IMPLEMENTED_FINDINGS],
        "missing": [dict(e) for e in MISSING_FINDINGS],
        "duplicate_or_overlapping": [dict(e) for e in DUPLICATE_OR_OVERLAPPING_FINDINGS],
        "integration_gaps": [dict(e) for e in INTEGRATION_GAP_FINDINGS],
        "request_lifecycle_trace": list(REQUEST_LIFECYCLE_TRACE),
        "can_existing_storage_safely_support_this_without_duplication":
            CAN_EXISTING_STORAGE_SAFELY_SUPPORT_THIS,
        "smallest_implementation_target_prompt_562":
            SMALLEST_IMPLEMENTATION_TARGET_PROMPT_562,
    }
