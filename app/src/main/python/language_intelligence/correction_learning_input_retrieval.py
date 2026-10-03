"""
Language Intelligence - Retrieve Stored Correction Learning Input
========================================================================
Prompt 462. A small, deterministic, READ-ONLY retrieval operation for
a correction-derived learning record previously written by Prompt 461
(`correction_learning_input_storage.
store_accepted_correction_learning_input()`), using the project's
EXISTING language-learning storage retrieval API,
`LanguageLearningStore.get_item()` (language_learning_store.py, Prompt
416) - never a new lookup mechanism.

    store_accepted_correction_learning_input(...)   (Prompt 461, unchanged)
        -> store.learn_item(language, ITEM_TYPE_CORRECTION, key, ...)
    retrieve_stored_correction_learning_input(...)   (THIS module)
        -> store.get_item(language, ITEM_TYPE_CORRECTION, key)         (Prompt 416, unchanged)

This module adds NO new storage mechanism and NO new database: it is
one direct pass-through call to `get_item()`, the EXACT retrieval API
Prompt 461's own stored rows are already addressable through -
`(language, item_type, key)` is the SAME "exact existing identifier"
`LanguageLearningStore._find_row()` already resolves a stored item by
(Prompt 416's own "deterministic - the same triple always resolves to
the same row" behavior). `item_type` is fixed to `ITEM_TYPE_CORRECTION`
(imported from correction_feedback_learning_input_adapter.py, Prompt
455 - never redefined here), the SAME constant Prompt 461's storage
path already writes every correction-derived record under, so a
caller only needs `language` and the original expression (`key`) to
look one back up - exactly what Prompt 461's own caller already has in
hand at storage time.

What is preserved
------------------
`get_item()` is read-only and returns the row's own dict UNCHANGED
(`LanguageLearningItem.to_dict()`) - `key` (the original expression),
`meaning` (the corrected expression or meaning), `language`,
`confidence`, `source`, and `source_context` all come back exactly as
Prompt 461 stored them; nothing is re-derived, re-normalized, or
translated here. `locale` was never part of this stored shape in the
first place (Prompt 455's own documented decision, carried through
Prompts 460 and 461 unchanged) and this module does not invent a place
for it either.

Not found
---------
`get_item()` already returns `None` for "nothing to give back" - the
project's existing NOT_FOUND/empty-result convention (the SAME value
Prompt 455's and Prompt 460's own adapters, and Prompt 461's own
storage operation, already return for their own "nothing here" cases).
This module returns that SAME `None`, unchanged - it invents no new
NOT_FOUND shape of its own.

Prompt 463 adds one further function to this same module,
`lookup_stored_correction_learning_input_by_original_expression()`,
for the explicit "I only have the original expression" case - a thin,
exact-match-only pass-through to the EXISTING
`LanguageLearningStore.find_items()` (Prompt 416/418), fixed to
`ITEM_TYPE_CORRECTION`. See that function's own docstring below for
its NOT_FOUND convention (`find_items()`'s own empty list) and its
storage-ordering behavior when more than one exact record exists.

Behavior
------------------------------------------------------------------------
Pure and deterministic: the same `(store, language, original_expression)`
always returns the same result, and repeated calls never create,
update, or delete anything (`get_item()`'s own existing read-only
guarantee). No semantic inference, fuzzy matching, spelling
correction, or automatic generalization happens anywhere in this
module - lookup is by exact `(language, item_type, key)` identity
only, the same identity `get_item()` already uses for every other
caller. This operation is not wired into any conversation flow or
automatic trigger by this stage - calling it is entirely up to a
separately-scoped caller. It does not touch `LearningAnalyzer`,
correction detection, `CorrectionUnderstanding`,
`CorrectionUnderstandingResult`, `CorrectionFeedbackRecord`, response
generation, or the Local Model Runtime; it adds no Memory or Knowledge
integration and makes no network/API call.
"""

from language_intelligence.correction_feedback_learning_input_adapter import (
    ITEM_TYPE_CORRECTION,
)
from language_intelligence.language_learning_store import LanguageLearningStore


def lookup_stored_correction_learning_input_by_original_expression(
        store, original_expression, language=None):
    """Prompt 463. Explicit, deterministic, EXACT lookup of previously
    stored correction-learning records (Prompt 461) by original
    expression alone - a direct, unchanged call to the EXISTING
    `LanguageLearningStore.find_items()` (Prompt 416), the SAME
    exact-identity search `get_item()` above already uses, with
    `item_type` fixed to `ITEM_TYPE_CORRECTION` (Prompt 455's existing
    constant, reused, never redefined) - the SAME item_type Prompt
    461's storage operation already writes every correction-derived
    record under.

    Unlike `retrieve_stored_correction_learning_input()` above, this
    does not require `language` - `find_items()` already supports
    "I have the written expression but not necessarily its language"
    (Prompt 418's own original reason for existing), so it is reused
    exactly as-is rather than re-implemented. `language` may still be
    given to narrow the match to one language, exactly as
    `find_items()`'s own `language` parameter already does.

    Matching is EXACT only - the SAME case-folded/whitespace-collapsed
    identity `find_items()`/`get_item()` already use for every other
    caller (`language_learning_store._normalize_key`). No fuzzy
    matching, semantic similarity, spelling guess, or inference is
    added here or anywhere else in this module.

    Returns a list of matching stored records (each the SAME dict
    shape `get_item()` returns - `id`, `language`, `item_type`, `key`,
    `meaning`, `examples`, `relationships`, `confidence`, `source`,
    `source_context`, `learning_method`, `version`, `created_at`,
    `updated_at` - all preserved unchanged), ordered exactly the way
    `find_items()` already orders them (`language`, `item_type`, `id`)
    - the project's EXISTING storage ordering. No ranking, scoring, or
    "best match" selection is invented here: when more than one exact
    record exists (the same original expression learned under more
    than one language), all of them come back, in that existing order,
    and the caller decides what to do with them.

    An empty list is returned when no exact record exists - the SAME
    empty-result convention `find_items()` already uses for "nothing to
    give back" (as opposed to `get_item()`'s `None`, which this
    function does not use, since it can return more than one record).

    `store` must be a `LanguageLearningStore` (`TypeError` otherwise -
    the same "isinstance check, then raise" posture the rest of this
    module and Prompt 461 already use).

    Read-only and deterministic: never creates, updates, or deletes
    anything, and never mutates `store` or any argument. This is an
    explicit operation only - nothing in this module calls it
    automatically, and it is not wired into any conversation flow or
    automatic trigger."""
    if not isinstance(store, LanguageLearningStore):
        raise TypeError(
            "store must be a LanguageLearningStore (language_intelligence."
            "language_learning_store.LanguageLearningStore) instance"
        )

    return store.find_items(
        original_expression, language=language, item_type=ITEM_TYPE_CORRECTION)


def retrieve_stored_correction_learning_input(store, language, original_expression):
    """Retrieve a previously stored correction-learning record by its
    exact `(language, original_expression)` identity - a direct,
    unchanged call to the EXISTING `LanguageLearningStore.get_item()`
    (Prompt 416) with `item_type` fixed to `ITEM_TYPE_CORRECTION`
    (Prompt 455's existing constant, reused, never redefined) - the
    SAME item_type Prompt 461's storage operation already writes
    every correction-derived record under.

    `store` must be a `LanguageLearningStore` (`TypeError` otherwise -
    the same "isinstance check, then raise" posture Prompt 457's
    `handoff_correction_learning_input()` and Prompt 461's
    `store_accepted_correction_learning_input()` already use).

    Returns the stored record as a dict (`get_item()`'s own existing
    shape - `language`, `item_type`, `key`, `meaning`, `confidence`,
    `source`, `source_context`, plus the store's own `id`/`version`/
    `created_at`/`updated_at`) when a record with this identity was
    previously stored, or `None` - the SAME existing NOT_FOUND/empty
    value `get_item()` already returns for "nothing to give back" -
    otherwise.

    Read-only and deterministic: never creates, updates, or deletes
    anything, and never mutates `store` or any argument.
    """
    if not isinstance(store, LanguageLearningStore):
        raise TypeError(
            "store must be a LanguageLearningStore (language_intelligence."
            "language_learning_store.LanguageLearningStore) instance"
        )

    return store.get_item(language, ITEM_TYPE_CORRECTION, original_expression)
