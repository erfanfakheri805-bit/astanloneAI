# Prompt 756 - Section 8: Multimedia - Image Operation Pipeline

Status: **implemented.** `multimedia/image_operation_pipeline.py` (pinned by `tests/test_image_operation_pipeline_prompt756.py`).

## What it does
`process_image_operation(request, image_registry)` chains the existing image-operation contracts into one deterministic call:

`request -> registry validation -> plan creation -> dispatch -> output validation`

It adds **no** image-operation semantics. Every decision is taken by the public function of an earlier prompt; the pipeline only calls them in
order, keeps what they returned and reports the outcome. The Prompt 748-755 production modules are **unchanged** and unaware of the pipeline.
Not wired into `process_input()`, Core, the Planner, the Agent Loop or Section 7.

## Stages (in order; the first failing stage stops the pipeline)
| # | public function used | on failure |
|---|---|---|
| 1 | `validate_image_operation_request(request, image_registry)` (Prompt 749) | `ok=False`; `plan`, `dispatch_result`, `output_validation` are `None`; no plan is created, nothing is dispatched |
| 2 | `create_image_operation_plan(validation_result)` (Prompt 750) | `ok=False`; `dispatch_result`, `output_validation` are `None` |
| 3 | `dispatch_image_operation(plan)` (Prompt 755) | `ok=False`; exact `plan` and `dispatch_result` kept; output validation is **not** attempted when no output exists |
| 4 | `validate_image_operation_output(plan, output)` (Prompt 753) | `ok=False`; exact `plan`, `dispatch_result` and `output_validation` kept |

`ok=True` only when the dispatch succeeded **and** the output validation succeeded. Every held object is the very object the earlier function
returned (identity preserved; nothing is copied or rebuilt). `request` holds the request only when it was a valid `ImageOperationRequest`
(the exact object passed in, also when the image was not found); an invalid request input is never stored.

## Failure codes (only these six; prefix `IMAGE_OPERATION_PIPELINE_`)
| code | when |
|---|---|
| `IMAGE_OPERATION_PIPELINE_INVALID_REQUEST` | validation reported `IMAGE_OPERATION_VALIDATION_INVALID_REQUEST` |
| `IMAGE_OPERATION_PIPELINE_INVALID_REGISTRY` | validation reported `IMAGE_OPERATION_VALIDATION_INVALID_IMAGE_REGISTRY` |
| `IMAGE_OPERATION_PIPELINE_VALIDATION_FAILED` | any other validation failure (e.g. `IMAGE_OPERATION_VALIDATION_IMAGE_NOT_FOUND`) |
| `IMAGE_OPERATION_PIPELINE_PLAN_FAILED` | the plan could not be created |
| `IMAGE_OPERATION_PIPELINE_DISPATCH_FAILED` | the dispatch, or the executor result it holds, did not succeed (e.g. unsupported operation) |
| `IMAGE_OPERATION_PIPELINE_OUTPUT_VALIDATION_FAILED` | the dispatched output did not match the plan |

Each failure is `{"code", "field", "message"}`. There is **one pipeline failure per failure reported by the failing stage**, in that stage's
order, and the exact upstream code is quoted in the message as `[<upstream code>]`; upstream codes are never invented, renamed or dropped. So an
invalid request and an invalid registry are both reported (request first), exactly as Prompt 749 reports them. The failing stage's own result
(`dispatch_result`, `output_validation`) stays available for full detail. Fields: the upstream field for validation failures
(`request`, `image_registry`, `image_id`), otherwise `plan`, `dispatch_result` or `output_validation`.

Notes: an unsupported operation (anything but the exact string `"metadata"`) passes validation and planning and fails at dispatch, so it is
`DISPATCH_FAILED`, with the plan and the dispatch result kept. `PLAN_FAILED` cannot be reached with the real Prompt 749/750 functions (a successful
validation always yields a plan); it exists as a defensive stage and is tested with a controlled patch.

## Result: `ImageOperationPipelineResult`
Members: `ok`, `request`, `plan`, `dispatch_result`, `output_validation`, `failures`, `codes()`, `to_dict()`
(`{"ok", "request", "plan", "dispatch_result", "output_validation", "failures"}`, each held object as its own `to_dict()`).
Immutable (`__slots__`, read-only); direct construction and subclassing raise `TypeError`; equality and hash by value (exact type only);
`copy()` / `deepcopy()` return the same object; pickling is refused (as for the other multimedia results); `failures`, `codes()` and `to_dict()`
are fresh on every call. Inputs are never mutated; repeated calls give equal results.

## What this module does NOT do
No image processing, decoding or pixels, no automatic operation selection (the dispatcher knows only `"metadata"`), no filesystem, network,
database, AI model or external service, no clock or randomness, no module-level mutable state. It re-implements none of the checks of
Prompts 748-755. Its only imports are the public functions above plus the two Prompt 749 failure-code constants and the Prompt 750 plan type.

## Test housekeeping
The earlier tests that pin the exact file list of the `multimedia` package (Prompts 746-755) and the Prompt 717/718 frozen-tree exemption lists now
also list the new module; no production module changed. Prompt 757 has **not** been started.
