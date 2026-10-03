# Prompt 704 - Section 5: ToolRequest registry entry point + contract audit (Prompts 697-704)

## 1. Entry point
`InProcessToolRegistry.execute_request(request) -> ToolExecutionResult` is exactly `self.execute(**request.to_registry_arguments())` for a
genuine `ToolRequest`. It therefore runs the one existing path: `execute` -> `invoke` -> `_invoke` -> `_evaluate` (the same single check
`preflight()` uses) -> the one handler call site -> output normalization/validation -> one audit record -> a result built from that record.
No rule is duplicated, there is no second execution path, and the request only carries the caller's own arguments (it grants nothing).
Anything that is not a usable `ToolRequest` (wrong type, or an instance forged without `create_tool_request()`) is rejected with the new code
`INVALID_TOOL_REQUEST` (execution status `tool_rejected`, `handler_called` False, `tool_name` None, authorization `not_evaluated`) and is
audited like every other rejected call (its record has `input` None). `tools.tool_request` is imported lazily inside the method because
that module imports the registry; nothing outside `tools/` references either module.

## 2. Audit method
Read every Section 5 boundary, then probed the registry empirically (cyclic/deep input and schema, hostile subclasses, trailing-newline
names, re-entrant handlers, forged requests), then ran mutation checks: the new defect regression tests fail against the Prompt 703
registry (9 of 11 fail; the other 2 are "valid things still work" guards).

## 3. Findings

| # | Finding | Verdict | Action |
|---|---|---|---|
| F1 | `_NAME_RE` ended in `$`, which also matches before a trailing newline: `"tool\n"` registered as a tool name, `"cap\n"` as a capability name (spec and granted). Contradicts the documented "exact" name contract at the authoritative boundary. | **Genuine defect** | Anchor with `\Z` (one token, one constant, covers names and both capability checks). |
| F2 | Cyclic or very deep `tool_input` raised `RecursionError` out of `preflight()`, `invoke()` and `execute()` (no audit record, depth depends on the interpreter); a cyclic `input_schema` raised out of `register()`. Broke "preflight never raises", "every returning `invoke()` is audited", "register never raises", determinism. | **Genuine defect** | see F4 |
| F3 | Input isolation: `copy.deepcopy(tool_input)` ran caller-supplied hooks, and a dict subclass with `__deepcopy__` returning itself made the handler receive the caller's own object; `_json_safe` also iterated caller subclasses. | **Genuine defect** (direct path; the `ToolRequest` path was already immune because requests hold normalized plain data) | see F4 |
| F4 | Root cause of F2/F3 and a duplicated authority: two "JSON-safe" definitions (`_json_safe`, unbounded and hook-running; `_normalize`, hardened, depth-capped) with different depth rules. | **Genuine (duplicated authority)** | `_json_safe` now delegates to `normalize_tool_output`; `_evaluate` normalizes the input once (validity + the plain private copy the handler receives); the audit record and stored `input_schema` are plain copies. Input nested deeper than `MAX_OUTPUT_DEPTH` (100) is now `INVALID_TOOL_INPUT`. |

Checked, no defect found (each covered by a test):
- **Bypass paths**: one handler call site; `_evaluate` reached only from `preflight` and `_invoke`; `execute_request` cannot skip existence, enabled, authorization-argument, permission, confirmation, capability, input, output or audit steps; forged request slots still go through the registry.
- **handler_called correctness / audit-result disagreement**: for every outcome kind result, record and real handler call count agree; result is derived from the record; sequence stays correct under a re-entrant (nested) call.
- **Failure/outcome codes**: every record outcome code maps to exactly one execution status; the only new code is `INVALID_TOOL_REQUEST` (-> `tool_rejected`). Preflight outcome equals execution outcome for every pre-handler rejection.
- **Authorization persistence**: registry state is only `_entries` and `_history`; grants/confirmation are per call and never stored (a second call without grants is denied).
- **Determinism**: identical runs on fresh registries give identical results/history; no module-level mutable request state.
- **Backwards compatibility**: all 253 pre-existing Section 5 tests pass. Six assertions were edited because they pin the contract this prompt intentionally changes: four "registry import set" checks (Prompts 699-702) gain the lazy `tools.tool_request` import, the Prompt 700 outcome-code set gains `INVALID_TOOL_REQUEST`, and my own Prompt 703 guard now allows only the registry to reference requests.

## 4. The `"tool\n"` regex edge case: fixed (genuine defect)
It is a defect at an authoritative registry boundary, not merely a request-contract nicety: `register()` accepted the name, `has()`/`describe()`
/`invoke()` then treated it as a normal tool, and the same constant validated capability names. The documented contract is exact names
`^[a-z][a-z0-9_]{0,63}$`; `$` is the only reason it was not enforced. The root cause is one token; the fix changes nothing for any name that
was valid under the documented contract. (`tool_request.py` already used `fullmatch`; it is left as is.)

## 5. Retained on purpose (low severity, documented)
- A caller-supplied hostile `list`/`set` **subclass** for `granted_*` is iterated more than once inside `_evaluate`. Grants are caller-authoritative (the caller could simply grant the permission), so this is not a privilege boundary; the `ToolRequest` path passes plain lists.
- A `str` subclass used as a tool *name* runs its own `__hash__`/`__eq__` in `has()`. Same reasoning; requests store an exact `str`.
- A handler `BaseException` (KeyboardInterrupt, SystemExit) still propagates unrecorded (Prompt 698 decision).
- `repr()` of an instance forged with `object.__new__(ToolRequest)` raises; the registry never calls it.
- Older `ToolDefinition`/`ToolRegistry` are unchanged and out of scope.

Limitations: not wired into `process_input()`, Planner or Agent Loop; `execute_request` has no preflight-only twin (use `preflight(**request.to_registry_arguments())`);
no request storage, ids, retries, scheduling or persistence. Tests: `tests/test_tools_request_integration_prompt704.py`.
