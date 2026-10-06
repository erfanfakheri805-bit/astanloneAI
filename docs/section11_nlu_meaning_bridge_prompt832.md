# Prompt 832 - Meaning Resolution Bridge

Module: `understanding/nlu_meaning_bridge.py` (`resolve_references(subject, context=None)`, `empty_resolution`).
Convenience method: `NLUAnalysis.resolve_references(context=None)`. `normalized()`, `semantic_view()` and the raw analysis are unchanged.

Input: an `NLUAnalysis` (or semantic view / normalized dict) and an optional `NLUConversationContext` (read-only, `turn_at` only).
Cues come only from the existing context block: `again` (دوباره ...), `reference` (همونو, قبلی, مثل قبل ...), `continuation` (و, پس ...).

Result keys: `version, status, reason, cues, continuation, primary_intent, effective_intent, inherited_intent, referenced_turn, referenced`.
Status: `none` (no cue) | `resolved` (cue points at an existing earlier turn) | `unresolved` (`no_previous_turn`, `referenced_turn_unavailable`
after reset or the context bound) | `ambiguous` (`context_mismatch`, `invalid_reference`; nothing trusted beyond the message's own intent).
`referenced` = `{turn_index, intent, text}` (text cut at 200 chars) only when a context is given and still retains the turn.

No chains are followed, nothing is invented. Fixed small output, JSON-safe, deterministic, non-raising, fresh dict, no Memory/AEL/Core involvement.
Tests: `tests/test_nlu_meaning_bridge_prompt832.py` (30 tests).
