"""
Language Intelligence - Store Accepted Correction Learning Input
========================================================================
Prompt 461. A small, explicit, EXPLICITLY-CALLED operation that writes
an ACCEPTED correction-learning input - the dict Prompt 460's adapter
(`correction_learning_handoff_to_learning_input_adapter.
convert_accepted_correction_handoff_to_learning_input()`) produces -
into the project's EXISTING language-learning storage
(`LanguageLearningStore.learn_item()`, language_learning_store.py,
Prompt 416).

    CorrectionLearningHandoffResult (Prompt 458) + learning_input (Prompt 455)
        -> convert_accepted_correction_handoff_to_learning_input(...) (Prompt 460)
        -> store_accepted_correction_learning_input(...)              (THIS module)
        -> LanguageLearningStore.learn_item(...)                      (Prompt 416, unchanged)

This module adds NO new storage mechanism, NO new database, and NO new
learning algorithm - it is two steps, in this exact order, and
nothing else:

    1. convert via Prompt 460's EXISTING adapter (imported, never
       re-implemented or re-derived here) - which itself only
       succeeds for a structurally valid, `ACCEPTED`
       `CorrectionLearningHandoffResult` (Prompt 459's validation,
       reused transitively through Prompt 460);
    2. not converted (Prompt 460 returned `None` - a `REJECTED` or
       `FAILED` handoff, a structurally INVALID result, or an
       incomplete/non-dict learning input) -> return `None`
       immediately, the project's existing safe-empty-result
       convention (the SAME value Prompt 460's own adapter, Prompt
       455's own adapter, and `LanguageLearningStore.get_item()`
       already return for "nothing to give back") - `store` is never
       called or even inspected in this case;
    3. converted -> call `store.learn_item(**converted_learning_input)` -
       the EXISTING storage API, called exactly the way
       `handoff_correction_learning_input()` (Prompt 457) already
       calls it for this identical dict shape. Whatever `learn_item()`
       returns (a dict, Prompt 416) or raises (`ValueError`/`TypeError`
       for a structurally bad value - the same exceptions it already
       raises for every other caller) is passed straight back,
       unchanged and uncaught. This module invents no new
       success/failure shape of its own for the storage layer's own
       outcome.

Because `learn_item()` resolves to the same (language, item_type,
normalized key) row every time (Prompt 416's own existing
"deterministic - re-teaching it never creates a duplicate" behavior),
calling this operation more than once for the same converted input
UPDATES the existing row rather than duplicating it - the exact same
"repeated calls behave consistently" convention
`test_correction_learning_input_handoff.py`'s own
`test_re_handing_off_the_same_input_updates_rather_than_duplicates`
already documents for Prompt 457. Nothing new is introduced here for
that behavior either.

What is preserved
------------------
Everything Prompt 460's adapter already preserves from the original
correction-feedback flow - `key` (the original expression), `meaning`
(the corrected expression or meaning), `language`, `confidence`,
`source`, and `source_context` - reaches `learn_item()` UNCHANGED,
because `converted_learning_input` IS that same dict (a deep copy),
expanded as keyword arguments. `locale` was never part of this shape
(Prompt 455's own documented decision, carried through Prompt 460
unchanged) and is not invented here either.

This operation is EXPLICIT and CONTROLLED: calling it is entirely up
to a separately-scoped caller. It is not wired into any conversation
flow, request handler, or automatic trigger by this stage - nothing in
this module calls it on its own, and it introduces no hook, listener,
or background job that would.

No semantic inference, guessing, fuzzy matching, or automatic
generalization happens anywhere in this module: it makes exactly one
decision (was Prompt 460's conversion successful?) and, when so, one
direct pass-through call to an already-existing storage API. This
module does not touch `LearningAnalyzer`, correction detection,
`CorrectionUnderstanding`, `CorrectionUnderstandingResult`,
`CorrectionFeedbackRecord`, response generation, or the Local Model
Runtime; it adds no Memory or Knowledge integration and makes no
network/API call.
"""

from language_intelligence.correction_learning_handoff_to_learning_input_adapter import (
    convert_accepted_correction_handoff_to_learning_input,
)
from language_intelligence.language_learning_store import LanguageLearningStore


def store_accepted_correction_learning_input(handoff_result, learning_input, store):
    """Write an ACCEPTED correction-learning input into the existing
    language-learning storage, EXPLICITLY - this function is never
    called automatically by this module or any other stage.

    `handoff_result` and `learning_input` are passed straight to
    Prompt 460's `convert_accepted_correction_handoff_to_learning_input()`
    (reused, never re-implemented). If that conversion returns `None`
    (a `REJECTED`/`FAILED`/structurally INVALID handoff, or an
    incomplete/non-dict learning input) this function returns `None`
    immediately - `store` is never called or even inspected.

    Otherwise `store` must be a `LanguageLearningStore`
    (`TypeError` otherwise - the same "isinstance check, then raise"
    posture `handoff_correction_learning_input()`, Prompt 457, already
    uses), and this function returns exactly
    `store.learn_item(**converted_learning_input)`'s own result. Any
    exception `learn_item()` itself raises propagates unchanged - no
    new error handling or result convention is invented here for the
    storage layer's own outcome.

    Pure and deterministic apart from `learn_item()`'s own existing
    side effects (which may write to `store`'s underlying storage
    exactly as it already does for any other caller - no second
    storage mechanism is introduced here). Neither `handoff_result`
    nor `learning_input` is mutated by this function.
    """
    converted = convert_accepted_correction_handoff_to_learning_input(
        handoff_result, learning_input)
    if converted is None:
        return None

    if not isinstance(store, LanguageLearningStore):
        raise TypeError(
            "store must be a LanguageLearningStore (language_intelligence."
            "language_learning_store.LanguageLearningStore) instance"
        )

    return store.learn_item(**converted)
