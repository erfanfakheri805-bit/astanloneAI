# Local Language Model Runtime Foundation (Prompt 398)

## Status in one paragraph

The **boundary** for running an on-device language model exists and is tested.
**No real model and no inference engine are present.** Today every attempt to
use the local-model backend ends in an explicit, typed status
(`model_not_configured` or `model_unavailable`) - never in text. Nothing here
is a fake LLM, nothing is downloaded, and there is no cloud/API code of any kind.

## Prompt 414 - language backend selection

`LanguageIntelligenceCore.select_backend()` makes the routing explicit and returns a `BackendSelection`
(`language_intelligence/backend_selection.py`): with a local-model primary and a fallback backend, a ready model
(MODEL_READY) selects the local backend; MODEL_NOT_CONFIGURED / MODEL_UNAVAILABLE / MODEL_LOAD_FAILED select the
deterministic fallback. In that case `generate_response()` does not call the local backend, provider or runtime at all (no
request, load or inference); the response is the structured "model not used" failure the readiness guard has produced since
Prompt 409 (`LocalLanguageModelBackend.not_ready_response()`), with `status` / `inference_status` / `error_code` / `reason`
unchanged and `fallback_backend_kind` set, so Prompt 406's handling and the deterministic pipeline apply exactly as before.
Every routed response carries `selected_backend_kind` (new, additive field, also in `to_dict()`); `last_backend_selection` holds
the decision. `backend_kind` keeps naming the backend the result describes (the local backend for a blocked model),
`selected_backend_kind` says which one is used, so a fallback is never presented as the local model. A ready model whose
inference then fails stays selected as local and is handled by Prompt 406. With no fallback backend (or a non-local primary)
there is nothing to choose and behavior is as before. Edge: a provider that cannot report availability is not treated as not
ready here, matching the Prompt 409 guard. Tests: `app/src/main/python/tests/test_language_backend_selection.py`.

## Prompt 413 - connecting local inference to response generation

The conversation path already handed a `ResponseGenerationResult` to `Core._handle_conversation` (step 1d); this stage
makes the connection explicit and supported. `Core.use_local_language_model(runtime=None, provider=None, **options)` opts
in: it builds a `LocalLanguageModelBackend` and makes it the primary backend of Core's `LanguageIntelligenceCore`, with the
Core's own deterministic backend as the Prompt 406 fallback. The default is unchanged (deterministic only); nothing is
downloaded, loaded or run by the call. The flow is runtime -> provider -> backend -> standardized `InferenceResult` ->
`ResponseGenerationResult` -> reply. `ResponseGenerationResult.is_generated` (STATUS_GENERATED with real text) tells the
conversation path "this text is the reply" - returned exactly as produced, stored once in memory/context - and
`needs_fallback` (status in `MODEL_FAILURE_STATUSES`) marks a model failure, whose `inference_status`, `error_code`, reason and
safe details stay on `Core.get_last_language_response()` while the existing deterministic pipeline answers; no text is
invented. Understanding, context, topic, reference resolution, language information and the user message are computed
before and independently of the model, so they are untouched. Tests:
`app/src/main/python/tests/test_local_inference_response_generation.py`.

## Prompt 412 - standardized local inference result

`inference.InferenceResult` already is the one result of an inference attempt (nine statuses: success, model_not_configured,
model_unavailable, model_load_failed, inference_failed, invalid_request, resource_limit, timeout, cancelled; plus error code/
message, model/runtime ids, request id, timing, token counts, details). No parallel result type was added. What is new is a
guarantee at the runtime -> provider -> backend boundary: `inference.standardize_inference_result()` returns a valid result
as-is and turns a malformed value (wrong type, unknown status, success without text, output on a failure) into a
STATUS_INFERENCE_FAILED / ERROR_INVALID_RUNTIME_OUTPUT failure; `inference_failure_from_exception()` does the same for a
runtime/provider that raised (exception TYPE name only). `RuntimeBackedProvider.generate()` applies it, and
`map_inference_result()` (used for every path of `LocalLanguageModelBackend.generate_response()`: runtime, readiness guard,
resource guard, contract breach) applies it first, so the `ResponseGenerationResult` is built one way. A failure's safe scalar
`details` (e.g. requested/limit of a resource-limit failure; never model output) now appear in `metadata["details"]`. Behavior
change: a "success" without text used to map to `inference_status="success"` with `model_failed`; it is now
`inference_failed` / `invalid_runtime_output`. Tests: `app/src/main/python/tests/test_standardized_inference_result.py`.

## Prompt 411 - local inference timeout and cancellation

The runtime already enforced the configured timeout (a lower per-request/backend timeout is allowed) and honoured a
`CancellationToken`, cooperatively (`InferenceControl.check()`), discarding any late output and returning
`STATUS_TIMEOUT` / `STATUS_CANCELLED`. The missing piece was a route for a caller to reach it: an optional
`cancellation_token` now travels `Core.generate_language_response()` -> `LanguageIntelligenceCore.generate_response()`
-> `LocalLanguageModelBackend.generate_response()` -> `provider.generate()` -> runtime (forwarded only when given;
`DeterministicFallbackBackend` accepts and ignores it). A timeout or cancellation maps like any runtime failure
(`model_failed`, inference_status `timeout` / `cancelled`, no text), so Prompt 406's fallback applies. One request is
at most one inference: no thread, timer or retry was added. Cancellation is cooperative: an engine that never polls
`control.check()` cannot be interrupted mid-call, but its late output is discarded. Tests:
`app/src/main/python/tests/test_local_inference_timeout_cancellation.py`.

## Prompt 410 - local inference resource guard

After the readiness check (which keeps priority) and once the request is built,
`LocalLanguageModelBackend.generate_response()` asks the provider `check_request_limits(request)`. That is the
runtime's EXISTING pre-load limit check (requested `max_output_tokens`, requested timeout, estimated prompt +
output vs `context_length`), factored into `LocalModelRuntime._limit_violation()` so `generate()` and the guard
share one implementation. Over a limit: the provider/runtime `generate()` is not called, nothing is loaded, and the
existing structured `STATUS_RESOURCE_LIMIT` failure (same error codes, mapped by `map_inference_result`) is returned,
so Prompt 406's fallback applies unchanged. Within limits: the existing inference path continues exactly as before.
Model file vs `max_memory_mb` remains covered by the readiness guard. A provider with no opinion (base-class default
`None`) or that raises does not block; `generate()` still enforces its own limits. No new limits, no retries, no
resizing. Tests: `app/src/main/python/tests/test_local_inference_resource_guard.py`.

## Prompt 409 - pre-inference readiness guard

`LocalLanguageModelBackend.generate_response()` now checks readiness first (the provider's existing
availability, summarised by Prompt 407's `model_readiness()`):

- MODEL_READY - continues to the existing inference path, unchanged.
- MODEL_NOT_CONFIGURED / MODEL_UNAVAILABLE / MODEL_LOAD_FAILED - the provider and runtime are NOT called:
  no request is built, nothing is loaded or inferred. The block is reported through the same structured
  path a runtime failure takes (an `InferenceResult` failure mapped by `map_inference_result`), so the
  result is the familiar `ResponseGenerationResult` and Prompt 406's fallback handling applies unchanged.
  A missing model file keeps its `model_load_failed` inference status and an over-budget model its
  `resource_limit`, exactly as the runtime's own preflight reported them.
- If the provider cannot report availability at all, the guard does not block; the existing path (which
  already reports a provider that breaks its contract) decides.
- Nothing is retried: a remembered load failure is reported without touching the runtime again.

Tests: `app/src/main/python/tests/test_pre_inference_readiness_guard.py`.

## Prompt 408 - exposing local model readiness

`Core.get_local_model_readiness()` (core/core.py) answers "is the local language model currently ready?"
for the higher-level language system by returning what `LanguageIntelligenceCore.check_model_readiness()`
reports (Prompt 407: `ModelReadiness` with MODEL_READY / MODEL_NOT_CONFIGURED / MODEL_UNAVAILABLE /
MODEL_LOAD_FAILED, `error_code`, `message`, `loaded`). It is a one-line delegation: no new status type, no
inference, no model load, and no conversation, context, memory or last-response state is touched. With
today's default (deterministic) backend it reports MODEL_NOT_CONFIGURED. Tests:
`app/src/main/python/tests/test_core_model_readiness.py`.

## Prompt 407 - local model readiness check

`LocalLanguageModelBackend.check_readiness()` (and `LanguageIntelligenceCore.check_model_readiness()`,
which asks the primary backend) returns a `ModelReadiness` (`inference.py`; `model_readiness()` in `local_model_runtime.py` builds it) - a four-way summary
of the existing `ModelAvailability`, so nothing new is observed:

- `MODEL_READY` - a request may be attempted (the model loads lazily on it; `loaded` says whether it already is)
- `MODEL_NOT_CONFIGURED` - no valid, enabled configuration (a disabled or invalid one included)
- `MODEL_LOAD_FAILED` - a load was attempted and failed (never retried by a check)
- `MODEL_UNAVAILABLE` - configured but cannot run now: engine library missing, model file missing or over the memory budget

`error_code` / `message` are the availability's. The check never loads the model, never calls
`provider.generate()`, never runs inference and never raises, so it is safe before every request. It is a
cheap preflight: an engine can still reject a file on the first lazy load, which then shows as
`MODEL_LOAD_FAILED`. A backend without a local model (the deterministic fallback) reports
`MODEL_NOT_CONFIGURED`. Tests: `app/src/main/python/tests/test_local_model_readiness.py`.

## Prompt 406 - local model failure & fallback handling

Every local-model failure is already a structured value below the backend (`InferenceResult` ->
`ResponseGenerationResult`: `status` + `inference_status` + `error_code`, `response_text=None`).
What was missing was the boundary above it: a `LocalLanguageModelBackend` used as the
`LanguageIntelligenceCore` backend raised from `understand()` (always - understanding by a model is
a later stage) and so would have broken `Core.process_input`. Prompt 406 adds one optional argument:

    LanguageIntelligenceCore(backend=LocalLanguageModelBackend(...),
                             fallback_backend=DeterministicFallbackBackend(core.understanding))

- `understand()`: if the primary raises, the SAME arguments go to the fallback backend; the result's
  `source_backend` names it and `last_understanding_fallback` records why (exception type + error code).
- `generate_response()`: a model failure (or a backend that raises / returns the wrong type) comes back
  as the structured failure, unchanged, with `fallback_backend_kind` set. `Core` then does what it always
  did with a result that is not `STATUS_GENERATED`: the existing deterministic pipeline replies. No text
  is written by this layer, so fallback output can never be taken for model output.
- Which state is which: not configured / unavailable / load failed = `inference_status`
  `model_not_configured` / `model_unavailable` / `model_load_failed`; inference failure, timeout,
  cancelled, resource limit, invalid request = `inference_failed` / `timeout` / `cancelled` /
  `resource_limit` / `invalid_request` (response `status` is `model_failed` for these).
- No retry anywhere: one primary call per call, a failed load is not reloaded, a resource failure never
  raises a limit, and a repeated failure is reported again rather than hidden. A conversation-level
  cancellation signal does not exist yet (the backend passes no cancellation token), so a model call that
  reports `cancelled` is handled like any other failure.
- Without `fallback_backend` (the default, and what `Core` builds today) behaviour is exactly as before.
- Tests: `app/src/main/python/tests/test_local_model_failure_fallback.py`.

## Prompt 405 - lightweight conversation state

`context/conversation_state.py:ConversationState` (one per `Core`, cleared by
`reset_context()`) keeps a small, bounded record so important information from a long
conversation stays available without sending the conversation itself:

- what it adds: **earlier topics** (the active-topic tracker only holds the current one),
  **explicit user preferences** ("I prefer ...", "keep it short" / "explain in detail"; a newer
  preference of the same kind replaces the old one, "I no longer prefer X" removes it) and
  **unresolved references**. Topic phrases, key words and reference targets are read from
  the results the pipeline already computed (ActiveTopicResult, ConversationThreadState,
  ResolvedReference) - words only, never message text or assistant replies. Response
  language stays in `LanguageContext` (Prompt 401), not here.
- bounds: 3 background topics, 3 preferences, 2 unresolved references, 8 key words per
  topic, 80 characters per preference; background topics / unresolved references older than
  the `ConversationContext` size (in messages) are dropped.
- path to the model: `Core` attaches the snapshot to the `LanguageUnderstandingResult`
  (`conversation_state`); `build_inference_request` selects only the part relevant to the
  message (`select_relevant_state`: active topic and preferences always; an earlier topic only
  if the message shares a word with it; unresolved references only if the message contains a
  reference word) and sends it as ONE short system message before the turns. It is charged
  against Prompt 404's budget (at most half of it; the rest is left for turns). No room means no
  state; no state means the request is unchanged.
- also fixed here: when Prompt 404's budget left no room at all, the conversation slice was
  not emptied (a 0-character limit was read as "no limit"); it is now empty as documented.
- English-only patterns / term extraction, like the rest of the term-based pipeline.
- Tests: `app/src/main/python/tests/test_conversation_state.py`.

## Prompt 404 - inference request size control

`local_model_mapping.py:build_inference_request` now ties the conversation
slice it sends to the model's OWN configured `context_length` /
`max_output_tokens` (the same numbers `LocalModelRuntime.generate()` already
enforces), instead of only the fixed Prompt-403 ceiling. `LocalLanguageModelBackend.
generate_response()` reads those two numbers once per request from the selected
provider's existing `resource_status()` - nothing is re-declared or duplicated.

- `resolve_request_size_limits(context_length, max_output_tokens)`: falls back to
  `local_model_config.py`'s own conservative defaults when either is unknown; never
  invents a larger number.
- `conversation_char_budget(...)`: how much prior-conversation text still fits, using
  the same char-per-token estimate `LocalModelRuntime._estimate_prompt_tokens` uses
  (imported, not duplicated).
- Context priority when a request has to shrink (never any other order): (1) the
  current user message - never touched; (2) `system_prompt` / `language_context` -
  always sent complete, their size only counts against the budget; (3) the most
  relevant selected turns (`context/relevance.py`); (4) an active-topic/reference
  match, which is exactly a highly-ranked turn from (3); (5) the oldest/least-relevant
  turns, dropped first.
- An impossible request (the user message alone will not fit) is still built exactly
  as given - construction never rewrites or drops it. `LocalModelRuntime.generate()`'s
  existing context-length check (already in place since Prompt 398) is what reports
  it as the structured `STATUS_RESOURCE_LIMIT` / `ERROR_CONTEXT_LENGTH_EXCEEDED`
  failure - no new failure path, no crash, no fabricated text, no retry loop.
- Not touched: Context, Memory, LanguageIntelligenceCore, tokenization (still a plain
  character estimate), or anything about a real model/engine.
- Tests: `app/src/main/python/tests/test_inference_request_size_control.py`.

## Prompt 401 - multilingual / Persian readiness

`InferenceRequest` now carries an optional `language_context` (original text, detected
language and scripts, conversation/requested/response language) next to the untouched
`user_input`, and `ModelInfo` / `LocalModelConfig` can declare supported languages,
scripts, `multilingual` and `default_language` (unknown stays `None`). No model, engine,
translation or canned text was added. See `multilingual_language_context.md`.

## Prompt 400 - provider / adapter layer

```
LanguageIntelligenceCore -> LocalLanguageModelBackend -> LocalModelProvider -> LocalModelRuntime -> local model
```

`local_model_provider.py` adds the replaceable seam so several local model
implementations can exist later without touching `LanguageIntelligenceCore`, Memory,
Context, Knowledge, Reasoning, Planning, Execution or the Agent Loop.

- `LocalModelProvider` (interface): `provider_id`, `availability()`, `model_info()`,
  `load()`, `generate()`, `unload()` (default: unsupported -> `False`), `resource_status()`.
- Results are the **existing** structured types, not new ones: `ModelAvailability`,
  `ModelLoadResult`, and `InferenceResult` (whose status already distinguishes success,
  not configured, unavailable, load failure, inference failure, timeout, cancellation,
  resource limit and invalid request, each with an `error_code`).
- `RuntimeBackedProvider(runtime, provider_id=None)`: pure delegate to a `LocalModelRuntime`
  - no limits, state or text of its own. This is what a real engine plugs into.
- `ProviderRegistry`: `register(provider, default=False)`, `select(provider_id=None)`,
  `get`, `set_default`, `provider_ids`. Unknown id -> `UnknownProviderError`; duplicate id or
  empty registry -> `ProviderRegistryError`. Nothing is silently substituted.
- `ModelInfo`: provider id, model id, format, supported languages, context length, max
  output, `is_local`, `loaded`, runtime name. Values not actually known are `None`
  (a `LocalModelConfig` does not declare languages, so they are always unknown today).
- Backend: `LocalLanguageModelBackend(runtime)` still works (wrapped in a
  `RuntimeBackedProvider`); `LocalLanguageModelBackend(provider=...)` and
  `LocalLanguageModelBackend.from_registry(registry, provider_id=None)` select a provider.
  Successful responses carry `metadata["provider_id"]`. A provider that raises or breaks
  its contract is reported as `model_failed` (exception type only).
- Not added: any real provider, model, engine, cloud call, API key or download.

Adding a second model later: write a `LocalModelRuntime` subclass (or a
`LocalModelProvider` directly), `registry.register(RuntimeBackedProvider(MyRuntime(config),
"my-model"))`, and build the backend with `from_registry`.

## Prompt 399 - backend <-> runtime integration (what changed)

`LocalLanguageModelBackend` is now connected to `LocalModelRuntime` through one
explicit mapping module and a structured availability check. Still no real model
or engine: without one, every path ends in an explicit typed status.

- **Mapping** (`local_model_mapping.py`, pure functions): `build_inference_request`
  gives the runtime only `user_input`, optional system prompt, the last few
  conversation turns, optional generation parameters and an optional (lower)
  timeout. `map_inference_result` gives the rest of the app only a
  `ResponseGenerationResult`:

  | inference status | response status |
  |---|---|
  | `success` (non-empty text) | `generated` |
  | `model_not_configured` | `model_not_configured` |
  | `model_unavailable`, `model_load_failed` | `model_unavailable` |
  | `inference_failed`, `invalid_request`, `resource_limit`, `timeout`, `cancelled`, unknown | `model_failed` |

  `inference_status` and `error_code` are always preserved. `ResponseGenerationResult`
  gained an optional `metadata` dict (`model_id`, `runtime_name`, `request_id`,
  `elapsed_seconds`, `prompt_tokens`, `output_tokens`, `finish_reason`; token counts
  are `None` unless the runtime reported them; never contains prompt/response text).
- **Availability**: `runtime.availability()` / `backend.check_availability()` return a
  `ModelAvailability` (`configured`, `enabled`, `runtime_available`, `loadable`,
  `loaded`, `can_infer`, `state`, `error_code`, `message`). It is read-only: it never
  loads the model (`loadable` = the cheap local path/size preflight), never runs
  inference, never touches the network. A disabled model is `configured=True,
  enabled=False`.
- **Contract failures**: if a runtime raises from `generate()` or returns something
  that is not an `InferenceResult` (or "success" without text), the backend reports
  `model_failed` and names only the exception *type* - never its message.
- **Lazy loading**: constructing the backend, `check_availability()` and `understand()`
  never load a model; the first `generate_response()` does. No automatic retry of a
  failed load.
- **Unchanged**: `DeterministicFallbackBackend` is a separate backend, never called by
  or merged into the local path; `Core` still uses it; `LanguageIntelligenceCore`
  is untouched.

## Architecture

```
LanguageIntelligenceCore                 (Prompt 397, unchanged)
  -> LocalLanguageModelBackend           language_intelligence/local_model_backend.py
    -> LocalModelRuntime                 language_intelligence/local_model_runtime.py
      -> <concrete engine subclass>      NOT PRESENT YET
        -> local model file              NOT PRESENT YET
```

| Concern | Where |
|---|---|
| Model configuration + validation | `local_model_config.py` (`LocalModelConfig`) |
| Inference request / result | `inference.py` (`InferenceRequest`, `InferenceResult`) |
| Loading, limits, timeout, cancellation, error translation | `local_model_runtime.py` (`LocalModelRuntime`, `load()`, `generate()`) |
| Explicit "no engine installed" state | `unavailable_runtime.py` (`UnavailableLocalModelRuntime`) |
| Backend <-> runtime mapping | `local_model_mapping.py` (translation), `local_model_backend.py` (orchestration) |
| Structured availability | `ModelAvailability` in `local_model_runtime.py` |

The deterministic fallback (`DeterministicFallbackBackend`) is a separate
backend. `LocalLanguageModelBackend` never calls it and never returns its output.

### Statuses (`InferenceResult.status`)

`success`, `model_not_configured`, `model_unavailable`, `model_load_failed`,
`inference_failed`, `invalid_request`, `resource_limit`, `timeout`, `cancelled`.
`text` is set only for `success`. Each failure carries a machine-readable
`error_code` and a human message.

`ResponseGenerationResult` (Prompt 397) gained three additive statuses -
`model_not_configured`, `model_unavailable`, `model_failed` - plus optional
`inference_status` / `error_code` fields. `generated` is reported only for a
genuinely successful inference.

### Resource safety (enforced once, in the base class)

- **Context length**: prompt + `max_output_tokens` must fit `context_length`.
  The prompt size is a *character-based estimate* until a real runtime overrides
  `_estimate_prompt_tokens` with its tokenizer.
- **Output size**: a request may not ask for more than the configured `max_output_tokens`.
- **Timeout**: per-config default; a request may only lower it. Load time is not counted.
- **Cancellation**: `CancellationToken`, checked before start, during (cooperatively) and after.
- **Memory**: `max_memory_mb` is checked against the model *file size* before loading
  (a real, cheap lower bound); a concrete runtime may enforce more.
- **Availability**: missing config / disabled / invalid config / missing engine are distinct, explicit states.
- Timeout and cancellation are **cooperative**: an engine must call `control.check()`
  while generating. An engine that ignores it and finishes late is reported as a
  timeout and its output is discarded. There is no thread killing.
- Loading is lazy (first `generate()`); a failed load is remembered and **not**
  retried automatically - call `load()` to retry.

## What is still required to have a real local model

1. **An on-device inference engine** that can run under Chaquopy on
   `arm64-v8a` / `armeabi-v7a` (the ABIs in `app/build.gradle`) and on desktop
   Python. Typical candidates: a llama.cpp Python binding (GGUF), ONNX Runtime,
   or TFLite. Native wheels for these ABIs must be **verified to exist or be
   built**; this was not attempted here. Adding it means a `pip { install ... }`
   block in `app/build.gradle` (currently empty - the project is stdlib-only),
   which is why it has **not** been added silently.
2. **A local model file** (not bundled; no downloading is implemented). It must be
   small enough for the target device's memory (`max_memory_mb`) and should handle
   **Persian and English**, since the project supports both.
3. **A concrete `LocalModelRuntime` subclass** implementing only:
   `runtime_name`, `dependency_status()`, `_load_model(config)`,
   `_run_inference(request, params, config, control)`, and optionally
   `_unload_model()` / `_estimate_prompt_tokens()`.
4. **A configuration** (`LocalModelConfig`) pointing at that file, and one line at
   the construction site: `LanguageIntelligenceCore(LocalLanguageModelBackend(MyRuntime(config)))`.
5. **A later stage** to implement `LocalLanguageModelBackend.understand()`
   (prompt design + validated structured output -> `LanguageUnderstandingResult`).
   Until then it raises rather than fabricating a result. `generate_response()`
   is already wired end to end.

Core, Memory, Context, Knowledge, Reasoning, Planning, Execution and the Agent
Loop do not change for any of the above.

## Tests

`app/src/main/python/tests/test_local_model_provider.py` (Prompt 400) covers registration,
selection, unknown provider, availability, metadata, inference and failure propagation through
a test provider and a runtime-backed provider, backend use of the provider, fallback
independence and Core compatibility.

`app/src/main/python/tests/test_local_model_backend_integration.py` (Prompt 399) covers the
backend -> runtime integration with its own runtime-boundary test double: no model
configured, disabled/unavailable runtime, availability states, successful inference,
load failure, inference failure, timeout/resource/cancel, result conversion and
metadata, runtime contract violations, fallback separation and Core compatibility.

`app/src/main/python/tests/test_local_model_runtime.py` uses a scripted **test
double** (`ScriptedTestRuntime`) that returns whatever a test tells it to. It is
not a model and performs no inference; it exists only to exercise the boundary.
