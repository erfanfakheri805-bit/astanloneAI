# Prompt 917 - Runtime -> Reasoning handoff inspection (documentation only)

Section 19: Runtime Integration / Productization. Subsection: Runtime State -> Reasoning/Decision Handoff.

## Current runtime path (normal user message)

`interface/server.py` / `android_entry.start()` -> `RuntimeCore.process_input()` -> `Core.process_input()`
(normalize, parse, route AEL / goal / conversation) -> for conversation turns `Core._handle_conversation()`
runs `persian_nlu.analyze_in_context()` and stores the `NLUAnalysis` as `Core.last_nlu_analysis` ->
reply returned unchanged -> `RuntimeCore._record_runtime_result()` -> `bridge.build_runtime_result()` ->
kept as `last_runtime_result` (read-only view: `GET /api/runtime-result`).

## Structured state available at the handoff point

`bridge.build_runtime_result()` receives one per-turn dict and already produces a structured result with:
input/message (`input`), understanding (`understood_input`: intent, slots, relations, context reference),
goal (`reasoning.goal`), context/memory (`memory_context`), learning (`learning`, incl. `relate_*` from 915),
and next action/decision (`reasoning.next_action`, `decision`, `next_step`, `capability_boundary`).
Underneath, `NLUAnalysis.reasoning_input(nlu_context)` (`understanding/nlu_reasoning_input.py`) is the
compact reasoning-ready record (intent, known slots/relations/reference, unresolved, missing).

## Exact point that could be used later

`runtime_integration/bridge.py::_reasoning_section(analysis, nlu_context)`, called from
`RuntimeCore._record_runtime_result()`. It already chains, read-only and deterministically:
`analysis.reasoning_input()` -> `reasoning.reasoning_foundation.build_reasoning_request()` ->
`reasoning.reasoning_plan.build_reasoning_plan()` -> `reasoning.reasoning_decision.decide_reasoning()` ->
`reasoning.capability_boundary.evaluate_reasoning_capability_boundary()`; `executed` is always False.
The smallest future hook is the `request` / `decision` values inside that function (or the
`last_runtime_result["reasoning"]` section after the turn).

## What is NOT connected

- `Core.process_input()` / `_handle_conversation()` do not consume the request, plan or decision; the reply
  is produced before the bridge runs and the bridge cannot change it.
- Goal and AEL turns have no NLU analysis, so `reasoning` is "unavailable" for them (conversation turns only).
- `last_runtime_result` is observed (API/tests) but not fed into any planner, goal manager or later turn.
- Memory and learning state are reported next to the reasoning section, not passed into it.
- No capability execution, autonomy chain, or self-upgrade is reachable from this path.

## Why Prompt 917 does not connect it

The existing reasoning foundation is already reached read-only; using its output to steer replies would be a
new runtime behavior (a decision about which reply path runs) and needs its own focused change and tests.
This prompt is inspection and documentation only: no production code, tests, database or schema changes,
no external AI/API/service, no network, no capability execution, no self-modification.
