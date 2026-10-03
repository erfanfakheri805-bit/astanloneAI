# Multilingual & Persian Language Readiness (Prompt 401)

## Status in one paragraph

The **architecture** for a future local multilingual model with real Persian ability
is in place and tested. **No language model, translation, canned reply, cloud call,
API key or download was added.** Nothing here can *understand* or *write* Persian;
it only makes sure Persian (and mixed-language) text reaches the model layer
intact, together with an honest description of its language situation.

```
user message (verbatim)
  -> LanguageContext                         language_intelligence/language_context.py
  -> LanguageUnderstandingResult.language_context
  -> InferenceRequest.language_context       (next to user_input, never instead of it)
  -> LocalModelProvider -> LocalModelRuntime -> (future) local model
```

## The original text is never replaced

`InferenceRequest.user_input` is always the user's original message: Persian ZWNJ,
Arabic vs. Persian yeh/kaf (ي/ی, ك/ک), Persian and Latin digits, Persian/Arabic
punctuation, code layout, URLs and filenames stay exactly as typed. The
Understanding Engine's `normalized_text` (NFKC + whitespace collapse) is carried
separately for **analysis only** - NFKC rewrites compatibility characters (`x²`, `ﬁ`,
fullwidth forms) and collapsing whitespace flattens code, so it is never sent as the
message. Normalization does not unify Arabic/Persian letter forms or convert digits.

## LanguageContext

| field | meaning |
|---|---|
| `original_text` | the message, verbatim |
| `normalized_text` | analysis-only normalized form, or `None` |
| `detected_language` | `english` / `persian` / `unknown` (script-level) |
| `detection_confidence` | `unknown` (no dominant language), `low` (mixed scripts), `high` (single script) |
| `detection_method` | `script_heuristic` |
| `scripts` | scripts present in the *prose*, most letters first (`arabic`, `latin`, `cyrillic`, ...); several = mixed input |
| `conversation_language` | majority of the last 3 *user* turns, or `None` |
| `requested_language` | explicit request, or `None` |
| `default_language` | configured default, or `None` |
| `response_language` / `response_language_source` | preferred reply language (or `None`) and why |

Mixed input (Persian + English terms, Persian + code, English + Persian names) is
represented by `scripts` / `mixed_script`; the dominant language is never presented
as the whole story.

## Response language priority

1. **Explicit request** - the `requested_language` argument (e.g. a UI setting), else a
   conservative recognizer over the text ("answer in Persian", "به انگلیسی جواب بده").
   Questions ("how do you say hi in Persian?"), negations and descriptions do not match.
2. **Conversation language** - so a single off-language message never flips the reply
   language; a sustained change does (2 of the last 3 user turns).
3. **Detection of this message** - used when it names a language; mixed-script results
   are still used (a Persian sentence with an English term is answered in Persian) but
   carry `low` confidence.
4. **Configured default** - `DeterministicFallbackBackend(engine, default_language=...)`.

With nothing known, `response_language` is `None` and the model decides from the text.
Identifiers are the project's labels; `canonical_language` maps codes/names
(`fa`, `fas`, `farsi`, `fa-IR` -> `persian`; `en`, `en-US` -> `english`).

## Detection changes (understanding/language_detection.py)

Same results for ordinary English/Persian prose, but: only **letters** are counted
(Persian/Arabic digits and `؟ ، ؛` are no longer counted as Persian letters), fenced
code, `inline code` and URLs are ignored for counting, and the dominant script is chosen
among all scripts (a Cyrillic sentence with one Latin word is `unknown`, not `english`).

**Known limitation (by design):** detection is script-level. It cannot tell Persian from
another Arabic-script language, or English from another Latin-script language, and
unfenced code inside a Persian sentence still counts as Latin letters (reported as
mixed). Only a real model can do better; `detection_method` records that this is a
heuristic so a future model-based detector can say otherwise.

## Model language capabilities

`ModelInfo` (and `LocalModelConfig`, which feeds it) can **declare**
`supported_languages`, `supported_scripts`, `multilingual` and `default_language`.
Unknown stays `None`. `ModelInfo.supports_language("persian")` is `True` only for a
declared language (`"fa"` == `"persian"`), `False` if a list was declared without it,
and `None` (unknown) if nothing was declared - `multilingual=True` alone never claims
Persian. Declarations are the configurer's; this layer neither infers nor verifies them.

```python
LocalModelConfig(model_id="my-model", model_path="/data/model.gguf",
                 supported_languages=["en", "fa"], supported_scripts=["latin", "arabic"],
                 multilingual=True, default_language="fa")
```

## What a future model integration does

A concrete runtime/provider reads `request.language_context` (response language,
detected language, scripts, conversation language) and decides how to prompt the
model; `user_input` is the untouched message. No prompt orchestration lives here.
Adding Persian ability = adding a real model + engine (see `local_model_runtime.md`) and
declaring its languages - nothing above the provider changes.

## Compatibility

`InferenceRequest.to_dict()` gained a `language_context` key (the only existing test
touched is the one that pins that key list). All new constructor arguments are optional
and last; `LanguageIntelligenceCore.understand(..., requested_language=None)` forwards
the argument only when given, so older backends keep working. Core is unchanged.
