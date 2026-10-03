# Prompt 780 - Section 9: Web Request Output Validator

Status: **implemented.** `web/web_request_output_validator.py` (pinned by `tests/test_web_request_output_validator_prompt780.py`). Eighth Section 9 module.
It follows `WebRequestOutput` (Prompt 779) and checks the shape of that output. It executes nothing.

## Public API
`validate_web_request_output(output)` returns a `WebRequestOutputValidationResult`. It never raises for bad inputs and never changes what it is given.

| input | ok | output | failure codes (prefix `WEB_REQUEST_OUTPUT_VALIDATOR_`) |
|---|---|---|---|
| not exactly a `WebRequestOutput` (None, dict, look-alike, subclass-free types) | `False` | `None` | `INVALID_OUTPUT` (nothing is read from the input) |
| an exact `WebRequestOutput` whose `status` is not an exact `str` | `False` | `None` | `INVALID_STATUS` |
| ... whose `code` is not an exact `str` | `False` | `None` | `INVALID_CODE` |
| ... whose `metadata` is neither `None` nor an exact `dict` | `False` | `None` | `INVALID_METADATA` |
| an exact `WebRequestOutput` with valid status, code and metadata | `True` | the very same object | none |

Status, code and metadata problems are reported together, in that order. Contents are NOT interpreted: string values, metadata keys and metadata values are
never normalized, parsed or compared with anything.

## Result object
`WebRequestOutputValidationResult` has `ok`, `output`, `failures` and `codes()`, plus `to_dict()` returning FRESH plain data `{"ok", "output", "failures"}`.
On success `output` preserves object identity. On any failure `output` is `None`: an invalid or malformed object is never retained. `failures` is a tuple of
fresh `{"code", "field", "message"}` dicts. Immutable (`__slots__`, assignment/deletion raises), not subclassable, direct construction refused, equality and
hash by value (exact type only), `copy`/`deepcopy` return the same (therefore equal) object, pickling raises `TypeError`. Repeated validation is deterministic.

## What this module does NOT do
- It does NOT perform networking, filesystem access, subprocess execution, persistence, database access, or AI-model / external-service calls.
- It does NOT read or inspect any project state other than the one output it is given.
- It does NOT modify the `WebRequestOutput` or any earlier Section 9 module, Core, the Planner, the Agent Loop or earlier sections, and is not wired into
  `process_input()`.
- Its only import is the Prompt 779 output type.

## Limitations
`WebRequestOutput` can only be created by `create_web_request_output()`, so a malformed output cannot arise in normal use; this validator is a defensive
contract check for future layers.

## Section 9 position
Prompt 780 is the eighth Section 9 prompt. Prompt 781 has NOT been started.
