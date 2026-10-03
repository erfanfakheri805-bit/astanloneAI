"""
Web Request Pipeline (Prompt 783, Section 9 - Web / Service Work)
=================================================================
A small deterministic pipeline around the existing Web Request dispatcher (Prompt 782). It checks that its input is a `WebRequestPlan` (Prompt 777),
hands it to the public `dispatch_web_request(plan)` and returns the dispatched `WebRequestOutput` (Prompt 779). It never performs a request.

    run_web_request_pipeline(plan) -> WebRequestOutput(status, code, metadata)

BEHAVIOR
1. `plan` must be exactly a `WebRequestPlan` (None, a dict, a look-alike, ... is not). Anything else gives a REJECTED `WebRequestOutput` with status
   "REJECTED", code `WEB_REQUEST_PIPELINE_INVALID_PLAN` and metadata None. The dispatcher is NOT called and nothing is read from the input.
2. A valid plan is passed to the public `dispatch_web_request(plan)` exactly once and the `WebRequestOutput` it returns is returned as is: the very same
   object, so status, code and metadata are unchanged (today status "NOT_IMPLEMENTED", code `WEB_REQUEST_EXECUTOR_NOT_IMPLEMENTED` and the plan's five
   values as metadata). Nothing is re-coded, re-validated, copied or re-interpreted.
3. Neither the plan nor the dispatched output is retained: both live only in the call. No module-level state of any kind.

NO DUPLICATED LOGIC
The pipeline does not call the executor or the output factory and does not look at the plan's values. Execution and output creation stay inside the
dispatcher (Prompt 782), which uses the executor (Prompt 778) and the output factory (Prompt 779).

THE ONE REJECTED OUTPUT
As in Prompt 782, the pipeline's own rejection is built with the `WebRequestOutput` class and the Prompt 779 module's private creation token, so
`WebRequestOutput` remains the one output type of the chain. No existing production module was changed for this.

RESULT
The returned `WebRequestOutput` is the Prompt 779 type: immutable, value-comparable, `to_dict()` gives fresh {"status", "code", "metadata"}. Repeated runs
of the same plan are deterministic. The function never raises for bad inputs and never mutates anything it is given.

WHAT THIS MODULE DOES NOT DO
No networking, no filesystem access, no subprocess, no persistence, no database, no AI model or external service call, and no request is ever executed.
No clock or randomness, no module-level mutable state. Its only imports are the Prompt 777 plan type, the Prompt 782 dispatcher function and the Prompt 779
output type and creation token. Not wired into `process_input()`, Core, the Planner, the Agent Loop or any earlier section.
"""

from .web_request_dispatcher import dispatch_web_request
from .web_request_output import _CREATE_TOKEN as _OUTPUT_CREATE_TOKEN
from .web_request_output import WebRequestOutput
from .web_request_plan import WebRequestPlan

STATUS_REJECTED = "REJECTED"

CODE_INVALID_PLAN = "WEB_REQUEST_PIPELINE_INVALID_PLAN"
CODES = (CODE_INVALID_PLAN,)


def run_web_request_pipeline(plan):
    """Run an exact `WebRequestPlan` through the existing dispatcher and return its `WebRequestOutput` unchanged.
    Performs no I/O of any kind. Deterministic, never raises for bad inputs, retains and changes nothing it is given."""
    if type(plan) is not WebRequestPlan:
        return WebRequestOutput(_OUTPUT_CREATE_TOKEN, STATUS_REJECTED, CODE_INVALID_PLAN, None)
    return dispatch_web_request(plan)
