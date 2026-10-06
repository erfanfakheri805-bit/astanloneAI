# Prompt 839 - Capability Contract Integration Checkpoint

Module: `reasoning/capability_integration.py` - `integrate_capability_contract(decision, spec=None, builder=build_capability_contract)` and `classify_capability_result(result)`.
It connects the Prompt 837 reasoning decision to the Prompt 838 capability contract foundation. No existing module, NLU API, reasoning API, Core, Memory or AEL code is changed; `reasoning/capability_contract.py` is untouched.

`integrate_capability_contract` returns the EXISTING Prompt 838 build result unchanged (`version, status, reason, contract, validation, executed`); contract behaviour and validation rules are exactly those of `build_capability_contract`. `builder` defaults to the existing builder and is only a seam for testing against a faulty builder. A builder result that is not a well-formed build result, claims execution, or whose `built` contract fails `validate_capability_contract` / has `execution_allowed` other than `False`, is never passed on; it is replaced by `{status: invalid, reason: integration_result_invalid, contract: None, validation: None, executed: False}` (the real builder never produces this).

`classify_capability_result(result)` distinguishes the situations:
- `decision_not_ready`: `unknown`/`decision_invalid`, or `insufficient` (decision needs clarification / information).
- `spec_missing`: decision ready but `unknown`/`capability_unspecified` (no spec) or `incomplete` (required fields absent).
- `spec_invalid`: `invalid` (spec not a dict, malformed fields, unexpected tool/implementation/handler fields, execution_allowed not False, ...).
- `contract_valid`: `built` - a validated contract with `execution_allowed` False.
- `integration_error`: anything else, including a replaced faulty result.
A decision that is not ready always wins over the spec's state.

Nothing is executed, registered, installed, repaired, modified or invented; no capability name, tool, implementation or handler is supplied by this layer. Bounded, JSON-safe, deterministic, fresh deep-copied results, non-raising. No Memory, AEL, Core, LLM or network.
Tests: `tests/test_capability_integration_prompt839.py` (32 tests).
