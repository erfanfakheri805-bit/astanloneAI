# Structured Response Planning (Prompt 425)

`language_intelligence/response_planning.py` turns what the language-understanding
pipeline already extracted into a **plan of what a response must contain**. It does
not write the response, retrieve knowledge, or classify intent.

```
LanguageUnderstandingResult ──► ResponsePlanner.plan() ──► ResponsePlan
                                                              │
                              understanding.response_plan ◄───┘  (dict, attached by
                              LanguageIntelligenceCore)           LanguageIntelligenceCore)
```

* Pure function of one understanding result: no store, Knowledge, Memory, clock or
  context object is read; nothing is written. It cannot add a fact, intent, variable
  or meaning the understanding does not already carry.
* Attached by `LanguageIntelligenceCore` to every understanding it returns, whichever
  backend produced it (including the deterministic fallback of the Local Language
  Model path). Planning failure adds a `response_plan_error` warning and never breaks
  understanding.
* Reached via `Core.plan_language_response(understanding)` (a `ResponsePlan`) and
  `Core.get_last_response_plan()` (the dict for the last conversational turn).
  ResponseGeneration reads it from `understanding.response_plan` or
  `ResponseGenerationRequest.response_plan`.

## Status

| status       | meaning |
|--------------|---------|
| `RESOLVED`   | exactly one explicitly learned meaning applies (Prompt 424) |
| `AMBIGUOUS`  | several learned meanings stay undecided: bound meanings (`meaning_candidates`), patterns matching equally (`pattern_candidates`), or – with no intention resolved – a word with several learned meanings (`expression_meanings`). All candidates kept; none picked; `needs_clarification` is true |
| `UNRESOLVED` | no learned intention applies (no pattern matched, structure undetermined, pattern has no bound meaning, nothing learned). `reason` is the existing pipeline's reason, verbatim; the understanding's own `intent`/`confidence`/`needs_clarification` are echoed in `understanding_state` |

## Fields (`ResponsePlan.to_dict()`)

`original_message` (verbatim) · `detected_language` · `locale` (only if an existing
result states one) · `status` · `reason` · `needs_clarification` · `response_action` ·
`response_action_source` · `meaning` · `meaning_candidates` · `matched_pattern` ·
`pattern_candidates` · `variables` · `expression_meanings` · `active_topic` ·
`references` · `context` · `required_items` · `unresolved_requirements` ·
`understanding_state` · `warnings`.

## Response action

Only for `RESOLVED` plans, and only from what was explicitly taught, in order:

1. `response_action` in the stored value of the bound **meaning** item (`learned_meaning`);
2. `response_action` in the stored `meaning` of the matched **pattern** (`learned_pattern`),
   passed through as taught (trimmed);
3. the meaning's **name**, exact match, in a tiny fixed table (`meaning_name`):
   `greet`/`greeting` → `greet`; `ask_question`/`information_request`/`request_information`
   → `provide_information`.

Otherwise `response_action` is `None` and an unresolved requirement
(`response_action` / `no_response_action_defined`) says so.

> The action vocabulary is **not** the `intent` vocabulary. `intent`
> `provide_information` means the *user* states something; `response_action`
> `provide_information` means the *response* must supply known information. The
> heuristic `intent` never selects an action.

## Required items

* `greet` → `{"kind": "greeting", "action": "greet"}`
* `provide_information` → one `information` item: `query` (original message, extracted
  variables, pattern text), `topic`, `references`, linked Knowledge `concepts`
  (names only), and `retrieval: {"from": ["knowledge", "memory"], "performed": false}`.
* any other taught action → no item.

AMBIGUOUS and UNRESOLVED plans have no action and no required items.

## Unresolved requirements

`{"kind", "reason", "detail"}` entries: `meaning` (`ambiguous_meaning`,
`ambiguous_pattern`, or the unresolved reason), `sentence_structure`
(`indeterminate_variable_boundary`), `reference` (`ambiguous_reference`,
`unresolved_reference`), `expression_meaning` (`ambiguous_expression_meaning`),
`response_action` (`no_response_action_defined`).

## Note

The keyword `greet` skill (skills/definitions/greet.json) answers "hi/hello/hey" in
`Core._handle_conversation` *before* the language pipeline runs, so such messages
produce no understanding or plan. That is pre-existing behaviour and unchanged.

## Learned response pattern selection (Prompt 434)

`LearnedResponsePatternSelector` (`language_intelligence/learned_response_pattern_selection.py`)
selects, deterministically, which already-taught learned response pattern applies. Flow:
understanding → learned language guidance → **response pattern selection** →
`ResponseGenerationContext.response_pattern_selection` →
`BackendGenerationRequest.response_pattern_selection`. It generates no text and reads no store.

A learned response pattern is an entry under the `response_patterns` key of a learned item's open
stored value (a meaning, a sentence pattern, or an expression's meaning) - the same place
`response_action` is taught. An entry needs an `id` and may declare conditions: `language`,
`locale`, `meaning`, `sentence_pattern`, `topic`, `reference`, `variables`. Every declared
condition must hold; none is inferred or relaxed.

* `RESOLVED` - exactly one strongest eligible candidate (strength = number of declared conditions
  satisfied). `selected_pattern` is set.
* `AMBIGUOUS` - several equally strong candidates, or the understanding itself is undecided; every
  eligible candidate is kept in taught order and none is picked.
* `NOT_FOUND` - nothing taught, or nothing eligible. Nothing is invented.

Result keys: `status`, `reason`, `selected_pattern`, `candidates`, `language`, `locale`,
`confidence`, `source`, `truncated`. Bounded: at most 20 entries per source and 50 in total.

## Learned response pattern variable binding (Prompt 435)

`LearnedResponsePatternBinder` (`language_intelligence/learned_response_pattern_binding.py`) binds the
variables the ONE pattern Prompt 434 selected needs to values the pipeline already extracted. Flow:
understanding → learned language guidance → response pattern selection → **response pattern variable
binding** → `ResponseGenerationContext.response_pattern_binding` →
`BackendGenerationRequest.response_pattern_binding`. It generates no text (a `template` is only read for
its `{{name}}` placeholders, never rendered), reads no store and never selects a pattern itself.

Required variables are read from the selected entry, de-duplicated, in this order: `required_variables`,
`variables`, then each `{{name}}` in `template`. By default a variable takes the value extracted for that
exact name (`ResponsePlan.variables`, then the MATCHED sentence structure's variable components). An entry
may route a variable to one named piece of context with `variable_sources` (`{"name": "<source>"}`):
`active_topic`, `context_topic`, `reference` (a RESOLVED reference's verbatim text), `expression` (a
RESOLVED learned expression), `meaning` (the resolved meaning's name), `language`, `locale`. Values are
bound exactly as found (no trimming, folding or defaults); a blank or absent value is never bound, and a
variable whose sources hold several different values is a conflict - missing, not guessed.

* `RESOLVED` - every required variable bound (`bound_variables`); the selected pattern is preserved.
* `UNRESOLVED` - some required variables could not be bound: `missing_variables` names them,
  `conflicting_variables` marks the conflicts, already-bound variables are kept.
* `AMBIGUOUS` / `NOT_FOUND` - the selection's own state (and reason, and candidates) is preserved and
  nothing is bound; a missing or unusable selection is `NOT_FOUND`.

Result keys: `status`, `reason`, `original_message`, `selected_pattern`, `pattern_id`, `candidates`,
`required_variables`, `bound_variables`, `missing_variables`, `conflicting_variables`,
`variable_sources`, `meaning`, `language`, `locale`, `confidence`, `source`, `truncated`. Bounded: at
most 20 variables are examined (the rest are reported missing).

## Learned response pattern rendering (Prompt 436)

`LearnedResponsePatternRenderer` (`language_intelligence/learned_response_pattern_rendering.py`) turns the
ONE selected pattern's own `template` plus the variables Prompt 435 bound into a response text. Flow:
understanding → learned language guidance → response pattern selection → variable binding → **pattern
rendering** → `ResponseGenerationContext.response_pattern_rendering` →
`BackendGenerationRequest.response_pattern_rendering` → existing response generation. It is plain
single-pass `{{name}}` substitution: no model, no network, no probabilistic generation, no store, and no
new language knowledge. The template's own text and the bound values are the only things in the output;
a `{{...}}` inside a bound value is never expanded.

* `RESOLVED` - `rendered_text` is set; `failure_reason` is None; `metadata["output_kind"]` marks it as
  deterministic learned-response output.
* `UNRESOLVED` - a placeholder has no usable bound value (or the binding itself was UNRESOLVED):
  `missing_variables` names them, and no text - not even a partial one - is produced.
* `AMBIGUOUS` / `NOT_FOUND` - the binding's state (and reason, and candidates) is preserved and nothing is
  rendered; a missing binding, or an empty / invalid selected pattern (no id, or no non-blank text
  `template`), is `NOT_FOUND`.

Result keys: `status`, `rendered_text`, `pattern_id`, `bound_variables`, `missing_variables`, `language`,
`locale`, `failure_reason`, `candidates`, `original_message`, `confidence`, `source`, `metadata`. The
existing local-model runtime/provider/backend, `ResponseGenerationResult`, backend selection and the
deterministic fallback are unchanged; a context with no learned response pattern carries a `NOT_FOUND`
rendering.

## Learned response integration (Prompt 437)

`decide_learned_response()` (`language_intelligence/learned_response_decision.py`) is the one deterministic
decision point `LanguageIntelligenceCore.generate_response()` runs **before** backend routing. It reads the
selection, binding and rendering the request already carries (Prompts 434–436). Only if the selection is
uniquely RESOLVED, every variable is bound, the template rendered to non-blank text **and** the resulting
`ResponseGenerationResult` passes the Prompt 430 validation is the learned response used; then no backend is
selected or called.

The learned response is an ordinary `ResponseGenerationResult`: `STATUS_GENERATED`, `response_text` exactly the
rendered text, `backend_kind` / `selected_backend_kind` = `"learned_response"` (a new value of the existing field,
not a backend and not in `ALL_BACKEND_KINDS`) and `metadata` (`response_source`, `pattern_id`, `bound_variables`,
`language`, `locale`, `original_message`, pattern `confidence`/`source`). The existing outcome (SUCCESS), validation
(VALID) and `ConversationResponse` (NORMAL) derive from it, so the source stays distinguishable from a local model
(`local_model`), a deterministic fallback (FALLBACK), a failure (FAILED) and an unresolved response (UNRESOLVED).

In every other case (ambiguous / not found selection, unresolved binding, failed render, failed validation, no plan)
the decision is "not used" (`reason` names the first failing step, kept as `last_learned_response_decision`) and the
existing routing – backend selection, local model, deterministic fallback – runs unchanged.
