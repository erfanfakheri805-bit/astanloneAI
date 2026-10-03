"""
Section 2 Correction-Learning Retrieval/Application Architecture Audit
(Prompt 563)
===========================================================================

Read-only, point-in-time audit of the EXISTING correction-learning
RETRIEVAL and CorrectionApplicationCandidate infrastructure under
`language_intelligence/`, performed per Prompt 562's own "smallest
logical next capability" note
(docs/section2_correction_learning_core_integration_prompt562.md):
"connect the already-tested retrieve_stored_correction_learning_input()
/ lookup_stored_correction_learning_input_by_original_expression() to a
real Core call site ... using the same real self.language_learning
store this prompt already connected for writes."

Prompt 563's own instructions require inspecting the existing
architecture FIRST and implementing ONLY a genuinely small missing
runtime connection, if one exists - and, if the remaining gap instead
requires a new subsystem or architectural redesign, to make NO broad
change and document the exact missing foundation instead. This module
is that documentation. Like
`diagnostics/section2_correction_learning_storage_audit_prompt561.py`
(Prompt 561) and `diagnostics/section2_language_intelligence_audit.py`
(Prompt 559), it is a fixed, deterministic data snapshot: it does not
introspect the codebase at import time, does not compute anything
dynamically, does not call into any other subsystem, and does not
mutate any project state. No new retrieval system, storage system,
database, or memory system was implemented, duplicated, or modified to
produce this audit or as a side effect of writing it - it is AUDIT
ONLY.

Category definitions (the same six Prompt 561 used):
    IMPLEMENTED_AND_WORKING        - genuinely works today, in isolation
    IMPLEMENTED_BUT_NOT_INTEGRATED - works, but not reached from the
                                      normal Core runtime path
    PARTIALLY_IMPLEMENTED          - exists but needs more work before
                                      it can reliably support correction
                                      application end to end
    MISSING                        - does not exist at all
    DUPLICATE_OR_OVERLAPPING       - existing code already provides the
                                      functionality under another name/path
    INTEGRATION_GAP                - a specific missing connection
                                      between retrieval, the
                                      CorrectionApplicationCandidate
                                      chain, and Core
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
    "core/core.py",
    "language_intelligence/correction_learning_input_retrieval.py",
    "language_intelligence/correction_learning_exact_lookup_result.py",
    "language_intelligence/correction_lookup_context.py",
    "language_intelligence/correction_lookup_selection.py",
    "language_intelligence/correction_lookup_usability.py",
    "language_intelligence/correction_application_candidate.py",
    "language_intelligence/correction_application_candidate_readiness.py",
    "language_intelligence/language_understanding_result.py",
    "language_intelligence/language_intelligence_core.py",
    "language_intelligence/response_generation_context.py",
    "language_intelligence/response_generation.py",
    "language_intelligence/local_model_backend.py",
    "language_intelligence/language_learning_store.py",
]

TOTAL_FILES_INSPECTED = len(FILES_INSPECTED)

# ----------------------------------------------------------------------
# 1. implemented_and_working
# ----------------------------------------------------------------------
IMPLEMENTED_AND_WORKING_FINDINGS = [
    _entry(
        "retrieval_now_reads_back_real_prompt_562_written_rows",
        IMPLEMENTED_AND_WORKING,
        "Confirmed end to end against a real, freshly constructed Core "
        "instance (not a synthetic fixture): a real RESOLVED correction "
        "processed through Core.process_input() is written by Prompt "
        "562's _store_resolved_correction_learning() under "
        "(language, ITEM_TYPE_CORRECTION, original_expression) - the "
        "EXACT identity "
        "lookup_correction_learning_input_by_original_expression_with_"
        "result(store, original_expression) / "
        "retrieve_stored_correction_learning_input(store, language, "
        "original_expression) already read from (Prompts 462/463/464). "
        "This closes the one open question Prompt 561's audit left "
        "about this pair (\"storage -> retrieval: NOT BROKEN, but "
        "UNEXERCISED end to end\" - now exercised, with real data, and "
        "correct).",
    ),
    _entry(
        "full_candidate_chain_now_produces_a_valid_candidate_from_real_data",
        IMPLEMENTED_AND_WORKING,
        "The full read path "
        "lookup_correction_learning_input_by_original_expression_with_"
        "result() -> build_correction_lookup_context() -> "
        "select_unique_stored_correction() -> "
        "build_correction_application_candidate() was run, end to end, "
        "against the real row from the finding above, and produced a "
        "CorrectionApplicationCandidate with is_valid=True and the "
        "correct original_expression/corrected_expression_or_meaning/"
        "language/source fields. Confirms Prompt 561's "
        "\"internally complete and self-consistent\" finding for this "
        "chain, now with real (not only synthetic per-stage test) data.",
    ),
]

# ----------------------------------------------------------------------
# 2. implemented_but_not_integrated
# ----------------------------------------------------------------------
IMPLEMENTED_BUT_NOT_INTEGRATED_FINDINGS = [
    _entry(
        "retrieval_and_candidate_family_still_zero_core_reachable_callers",
        IMPLEMENTED_BUT_NOT_INTEGRATED,
        "Grep-confirmed zero importers outside language_intelligence/, "
        "diagnostics/, and tests/ for: "
        "correction_learning_input_retrieval.py, "
        "correction_learning_exact_lookup_result.py, "
        "correction_lookup_context.py, correction_lookup_selection.py, "
        "correction_lookup_usability.py, "
        "correction_application_candidate.py, and "
        "_candidate_readiness.py. Unchanged from Prompt 561's own "
        "finding - this prompt independently reconfirms it after "
        "Prompt 562's storage-side integration, since that integration "
        "only added a WRITE call site (core.py's "
        "_store_resolved_correction_learning), never a read/retrieval "
        "call site.",
    ),
    _entry(
        "response_generation_context_transport_fields_still_never_assigned",
        IMPLEMENTED_BUT_NOT_INTEGRATED,
        "response_generation_context.py's "
        "`correction_application_candidate` and "
        "`correction_lookup_context` fields on ResponseGenerationContext "
        "still exist and are still read via getattr(understanding, ..., "
        "None) inside generation_context_from_understanding() - but a "
        "project-wide grep found no code outside these modules' own "
        "package (and outside tests/) that ever assigns either one. "
        "Confirmed directly on a real Core instance: after "
        "Core.process_input(), "
        "getattr(core.last_language_understanding, "
        "'correction_application_candidate', '<absent>') returns "
        "'<absent>' - the attribute does not merely hold None, it does "
        "not exist on the object at all (see MISSING finding below).",
    ),
]

# ----------------------------------------------------------------------
# 3. partially_implemented
# ----------------------------------------------------------------------
PARTIALLY_IMPLEMENTED_FINDINGS = [
    _entry(
        "language_understanding_result_has_no_slot_for_the_candidate",
        PARTIALLY_IMPLEMENTED,
        "language_understanding_result.py's LanguageUnderstandingResult"
        ".__init__ accepts and stores `correction_lookup_context` "
        "(Prompt 466) but has no `correction_application_candidate` "
        "parameter or attribute at all. Only "
        "ResponseGenerationContext (one stage further downstream, "
        "response_generation_context.py) carries that field. Before any "
        "real Core-reachable code could assign a candidate onto the "
        "understanding object response generation itself reads from, "
        "LanguageUnderstandingResult's own constructor would need a new "
        "parameter - a change to an existing, shared class's contract, "
        "not the addition of a call using only what already exists.",
    ),
]

# ----------------------------------------------------------------------
# 4. missing
# ----------------------------------------------------------------------
MISSING_FINDINGS = [
    _entry(
        "no_trigger_exists_for_when_to_look_up_a_stored_correction",
        MISSING,
        "Prompt 562's write-side call site had a ready-made, "
        "already-existing trigger: step 1e's unchanged "
        "`correction_understanding[\"status\"] == "
        "CORRECTION_STATUS_RESOLVED` condition. No equivalent trigger "
        "exists anywhere in core/core.py, understanding/, or "
        "language_intelligence/ for the read side - there is no "
        "existing concept, anywhere in the current codebase, of \"this "
        "expression, in this ordinary (non-correction) message, is one "
        "Core has a previously stored correction for; look it up "
        "before replying.\" Prompt 561's own audit already flagged this "
        "distinction (\"[retrieval] depend[s] on a second, later "
        "message referencing an already-stored correction - a distinct "
        "trigger from the one storage needs\"); this audit confirms it "
        "still does not exist after Prompt 562.",
    ),
    _entry(
        "no_store_reference_reaches_the_call_site_that_builds_understanding",
        MISSING,
        "Core's real, SQLite-backed LanguageLearningStore instance "
        "(`self.language_learning`) is owned by Core "
        "(core/core.py), not by `self.language_intelligence` "
        "(the LanguageIntelligenceCore instance whose `.understand()` "
        "actually builds the LanguageUnderstandingResult retrieval "
        "would need to attach a candidate to). "
        "LanguageIntelligenceCore.understand()'s signature "
        "(raw_text, context, relevant_context, resolved_reference, "
        "active_topic) has no store parameter today, so even with a "
        "trigger decided, there is no existing path for the store "
        "instance itself to reach the code that would perform the "
        "lookup at the point the understanding object is built.",
    ),
]

# ----------------------------------------------------------------------
# 5. duplicate_or_overlapping
# ----------------------------------------------------------------------
DUPLICATE_OR_OVERLAPPING_FINDINGS = []

# ----------------------------------------------------------------------
# 6. integration_gaps
# ----------------------------------------------------------------------
INTEGRATION_GAP_FINDINGS = [
    _entry(
        "storage_to_retrieval_gap_now_closed",
        INTEGRATION_GAP,
        "storage -> retrieval: CLOSED as of this audit. Real data "
        "written by Prompt 562's Core-reachable write path is now "
        "confirmed readable, with correct field values, by the "
        "existing retrieval functions, using the same real "
        "self.language_learning store instance. No code change was "
        "needed for this half - both sides already agreed on the same "
        "(language, item_type, key) identity.",
    ),
    _entry(
        "retrieval_to_candidate_gap_now_closed_in_isolation",
        INTEGRATION_GAP,
        "retrieval -> CorrectionApplicationCandidate: CLOSED in "
        "isolation as of this audit (see "
        "full_candidate_chain_now_produces_a_valid_candidate_from_"
        "real_data above) - but STILL zero Core-reachable callers, "
        "independent of the data question. This gap is about "
        "reachability, not correctness, and reachability is unchanged.",
    ),
    _entry(
        "candidate_to_core_response_gap_still_open_and_now_understood_"
        "to_require_new_design",
        INTEGRATION_GAP,
        "CorrectionApplicationCandidate -> Core response/application: "
        "STILL BROKEN, and - unlike Prompt 562's write-side gap, which "
        "was a single missing call using entirely existing pieces - "
        "this gap cannot be closed by a call alone. Closing it requires "
        "(1) a new, currently-nonexistent decision about WHEN a "
        "message's understanding should trigger a stored-correction "
        "lookup at all (see no_trigger_exists_for_when_to_look_up_a_"
        "stored_correction above), and (2) a new constructor parameter "
        "on LanguageUnderstandingResult plus a way for Core's own store "
        "instance to reach LanguageIntelligenceCore.understand() (see "
        "no_store_reference_reaches_the_call_site_that_builds_"
        "understanding above). Both are genuine new design decisions, "
        "not a missing call between existing pieces - this is the "
        "\"would require a new subsystem or architectural redesign\" "
        "case Prompt 563 itself distinguishes from a small connection, "
        "and per Prompt 563's own instructions is intentionally NOT "
        "implemented here.",
    ),
]

REQUEST_LIFECYCLE_TRACE = [
    "A LATER MESSAGE REUSES A PREVIOUSLY CORRECTED EXPRESSION",
    "-> stored correction exists (correction_learning_input_storage.py, "
    "via Prompt 562's Core write path): CONFIRMED PRESENT for any "
    "expression a user has previously, explicitly corrected in this "
    "conversation history",
    "-> retrieval (correction_learning_input_retrieval.py / "
    "correction_learning_exact_lookup_result.py): CONNECTABLE AND "
    "CORRECT when called, but NOT CALLED anywhere Core-reachable - no "
    "code decides a later message should trigger this lookup at all",
    "-> CorrectionApplicationCandidate (correction_lookup_context.py -> "
    "correction_lookup_selection.py -> "
    "correction_application_candidate.py): CONNECTABLE AND CORRECT when "
    "given a real lookup result, but likewise NOT CALLED anywhere "
    "Core-reachable",
    "-> Core response/application (response_generation_context.py's "
    "transport field, LanguageUnderstandingResult): NOT CONNECTED - the "
    "transport field exists on ResponseGenerationContext and is read, "
    "but LanguageUnderstandingResult (one stage earlier, where a "
    "Core-reachable assignment would have to happen) has no matching "
    "field to assign in the first place, and no code decides when to "
    "assign it even if it did",
]

CAN_THE_REMAINING_GAP_BE_CLOSED_BY_A_SMALL_CONNECTION_ALONE = (
    "No. Unlike Prompt 562's gap (a single missing call, using only "
    "pieces that already existed, gated by a condition - step 1e's "
    "CORRECTION_STATUS_RESOLVED check - that already existed), the "
    "remaining retrieval-to-Core-response gap requires two new design "
    "decisions that do not yet exist anywhere in this codebase: (1) "
    "what makes an ordinary, later message eligible for a stored-"
    "correction lookup, and (2) how Core's own store instance reaches "
    "the point in LanguageIntelligenceCore.understand() where the "
    "understanding object is built, plus a new field on "
    "LanguageUnderstandingResult itself to carry the result. Per "
    "Prompt 563's own instructions (\"If the existing retrieval/"
    "application path is incomplete and would require a new subsystem "
    "or architectural redesign: Do NOT build it in this prompt\"), no "
    "broad change was made; this audit documents the exact missing "
    "foundation instead."
)

SMALLEST_CONCRETE_MISSING_FOUNDATION_FOR_A_LATER_PROMPT = (
    "Before any call-site connection can be added, a later prompt needs "
    "an explicit, narrow, deterministic design decision for the trigger "
    "- e.g. (illustrative only, not a recommendation to build without "
    "further review) \"when the current message's own detected key "
    "expression exactly matches a `key` already stored under "
    "ITEM_TYPE_CORRECTION for the active language, look it up\" - plus "
    "the one new LanguageUnderstandingResult constructor parameter "
    "(`correction_application_candidate=None`, following the exact "
    "existing convention `correction_lookup_context` already uses) and "
    "a way for `LanguageIntelligenceCore.understand()` (or a Core-side "
    "step immediately after it returns, working from the already-"
    "returned LanguageUnderstandingResult and Core's own "
    "self.language_learning, the same posture Prompt 562's storage call "
    "already uses) to perform the lookup and assign the result. No new "
    "storage, database, retrieval mechanism, or CorrectionApplication"
    "Candidate logic would be needed - every one of those pieces "
    "already exists, already works, and was reconfirmed against real "
    "data by this audit."
)


def build_correction_retrieval_application_audit():
    """Return the full, deterministic Prompt 563 audit as plain data.

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
        "can_the_remaining_gap_be_closed_by_a_small_connection_alone":
            CAN_THE_REMAINING_GAP_BE_CLOSED_BY_A_SMALL_CONNECTION_ALONE,
        "smallest_concrete_missing_foundation_for_a_later_prompt":
            SMALLEST_CONCRETE_MISSING_FOUNDATION_FOR_A_LATER_PROMPT,
    }
