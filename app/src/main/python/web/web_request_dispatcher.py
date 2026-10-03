"""
Web Request Dispatcher (Prompt 782, Section 9 - Web / Service Work)
===================================================================
A small deterministic dispatcher for the Web Request execution chain. It takes a `WebRequestPlan` (Prompt 777), sends it through the existing
placeholder executor (Prompt 778) and returns the existing output object (Prompt 779). It never performs a request.

    dispatch_web_request(plan) -> WebRequestOutput(status, code, metadata)

BEHAVIOR
1. `plan` must be exactly a `WebRequestPlan` (None, a dict, a look-alike, ... is not). Anything else gives a REJECTED `WebRequestOutput` with status
   "REJECTED", code `WEB_REQUEST_DISPATCHER_INVALID_PLAN` and metadata None. The executor is NOT called and nothing is read from the input.
2. A valid plan is passed to the public `execute_web_request_plan(plan)` (Prompt 778). Its `WebRequestExecutionResult` (today always NOT_IMPLEMENTED)
   is converted with the public `create_web_request_output(execution_result)` (Prompt 779) and that output is returned as is: status, code and
   metadata are exactly what the output factory produces (the very same `str` / `int` objects, same key order). Nothing is re-coded or re-interpreted.
3. Neither the plan nor the execution result is retained: both live only in local variables of the call. No module-level state of any kind.

THE ONE REJECTED OUTPUT
The existing output factory can only build the invalid-execution-result rejection (`WEB_REQUEST_OUTPUT_INVALID_EXECUTION_RESULT`), so the dispatcher's own
rejection is built with the `WebRequestOutput` class and its module-private creation token from the Prompt 779 module. No existing production module was
changed for this, and `WebRequestOutput` remains the one output type of the chain (no second output class, no look-alike).

RESULT
The returned `WebRequestOutput` is the Prompt 779 type: immutable, value-comparable, `to_dict()` gives fresh {"status", "code", "metadata"}. Repeated
dispatch of the same plan is deterministic. The function never raises for bad inputs and never mutates anything it is given.

WHAT THIS MODULE DOES NOT DO
No networking, no filesystem access, no subprocess, no persistence, no database, no AI model or external service call, and no request is ever executed.
It does not parse or validate the plan's values and does not look at a registry. No clock or randomness, no module-level mutable state. Its only
imports are the Prompt 777 plan type, the Prompt 778 executor function and the Prompt 779 output type, token and factory. Not wired into
`process_input()`, Core, the Planner, the Agent Loop or any earlier section.
"""

from .web_request_executor import execute_web_request_plan
from .web_request_output import _CREATE_TOKEN as _OUTPUT_CREATE_TOKEN
from .web_request_output import WebRequestOutput, create_web_request_output
from .web_request_plan import WebRequestPlan

STATUS_REJECTED = "REJECTED"

CODE_INVALID_PLAN = "WEB_REQUEST_DISPATCHER_INVALID_PLAN"
CODES = (CODE_INVALID_PLAN,)


def dispatch_web_request(plan):
    """Run an exact `WebRequestPlan` through the existing executor and output factory and return a `WebRequestOutput`.
    Performs no I/O of any kind. Deterministic, never raises for bad inputs, retains and changes nothing it is given."""
    if type(plan) is not WebRequestPlan:
        return WebRequestOutput(_OUTPUT_CREATE_TOKEN, STATUS_REJECTED, CODE_INVALID_PLAN, None)
    return create_web_request_output(execute_web_request_plan(plan))
