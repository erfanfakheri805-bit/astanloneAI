# Prompt 769 - Section 8: Multimedia - Audio Operation Pipeline

Status: **implemented.** `multimedia/audio_operation_pipeline.py` (pinned by `tests/test_audio_operation_pipeline_prompt769.py`).

## What it does
`process_audio_operation(request, audio_registry)` chains the existing audio-operation contracts into one deterministic call, the audio
counterpart of `process_image_operation()` (Prompt 756):

`request -> registry validation -> plan creation -> dispatch -> output validation`

It adds **no** audio-operation semantics. Every decision is taken by the public function of an earlier prompt; the pipeline only calls them in
order, keeps what they returned and reports the outcome. The Prompt 761-768 production modules are **unchanged** and unaware of the pipeline.
Not wired into `process_input()`, Core, the Planner, the Agent Loop or Section 7.

## Stages (in this exact order; the first failing stage stops the pipeline)
| # | public function used | on failure |
|---|---|---|
| 1 | `validate_audio_operation_request(request, audio_registry)` (Prompt 762) | `ok=False`; `plan`, `dispatch_result`, `output_validation` are `None`; no plan is created, nothing is dispatched |
| 2 | `create_audio_operation_plan(validation_result)` (Prompt 763) | `ok=False`; `dispatch_result`, `output_validation` are `None` |
| 3 | `dispatch_audio_operation(plan)` (Prompt 768) | `ok=False`; exact `plan` and `dispatch_result` kept; output validation is **not** attempted when no output exists |
| 4 | `validate_audio_operation_output(plan, output)` (Prompt 766) | `ok=False`; exact `plan`, `dispatch_result` and `output_validation` kept |

`ok=True` only when the dispatch succeeded **and** the output validation succeeded. Every held object is the very object the earlier function
returned (identity preserved; nothing is copied or rebuilt). `request` holds the request only when it was a valid `AudioOperationRequest`
(the exact object passed in, also when the audio was not found); an invalid request input is never stored.

## Failure codes (only these six; prefix `AUDIO_OPERATION_PIPELINE_`)
| code | when |
|---|---|
| `AUDIO_OPERATION_PIPELINE_INVALID_REQUEST` | validation reported `AUDIO_OPERATION_VALIDATION_INVALID_REQUEST` |
| `AUDIO_OPERATION_PIPELINE_INVALID_REGISTRY` | validation reported `AUDIO_OPERATION_VALIDATION_INVALID_AUDIO_REGISTRY` |
| `AUDIO_OPERATION_PIPELINE_VALIDATION_FAILED` | any other validation failure (e.g. `AUDIO_OPERATION_VALIDATION_AUDIO_NOT_FOUND`) |
| `AUDIO_OPERATION_PIPELINE_PLAN_FAILED` | the plan could not be created |
| `AUDIO_OPERATION_PIPELINE_DISPATCH_FAILED` | the dispatch, or the executor result it holds, did not succeed (e.g. unsupported operation) |
| `AUDIO_OPERATION_PIPELINE_OUTPUT_VALIDATION_FAILED` | the dispatched output did not match the plan |

Each failure is `{"code", "field", "message"}`. There is **one pipeline failure per failure reported by the failing stage**, in that stage's
order, and the exact upstream code is quoted in the message as `[<upstream code>]`; upstream codes are never invented, renamed or dropped. So an
invalid request and an invalid registry are both reported (request first), exactly as Prompt 762 reports them. The failing stage's own result
(`dispatch_result`, `output_validation`) stays available for full detail.

Notes: an unsupported operation (anything but the exact string `"metadata"`) passes validation and planning and fails at dispatch, so it is
`DISPATCH_FAILED`, with the plan and the dispatch result kept. `PLAN_FAILED` cannot be reached with the real Prompt 762/763 functions (a
successful validation always yields a plan); it exists as a defensive stage and is tested with a controlled patch.

## Result: `AudioOperationPipelineResult`
Members: `ok`, `request`, `plan`, `dispatch_result`, `output_validation`, `failures`, `codes()`,
`to_dict()` (`{"ok", "request", "plan", "dispatch_result", "output_validation", "failures"}`, each held object as its own `to_dict()`).
Immutable (`__slots__`, read-only); direct construction and subclassing raise `TypeError`; equality and hash by value (exact type only);
`copy()` / `deepcopy()` return the same object; pickling is refused (as for the other multimedia results); `failures`, `codes()` and `to_dict()`
are fresh on every call. Inputs are never mutated; repeated calls give equal results.

## What this module does NOT do
No audio processing, decoding or samples, no automatic operation selection (the dispatcher knows only `"metadata"`), no filesystem, network,
subprocess, database, AI model or external service, no clock or randomness, no retries or concurrency, no module-level mutable state. It
re-implements none of the checks of Prompts 761-768. Its only imports are the public functions above plus the two Prompt 762 failure-code
constants and the Prompt 763 plan type.

## Test housekeeping
The earlier tests that pin the exact file list of the `multimedia` package (Prompts 746-768) and the Prompt 717/718 frozen-tree exemption lists now
also list the new module; no production module changed. Prompt 770 has **not** been started.
