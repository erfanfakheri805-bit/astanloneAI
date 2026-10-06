# Prompt 910 — Runtime Integration Foundation

First implementation stage after Sections 12–18. It connects already-built architecture to the real
message path through one read-only bridge. No new architecture section, no frozen-tree file touched.

## Runtime path before this change

```
MainActivity.java -> android_entry.start() -> interface/server.py (ThreadingHTTPServer)
  -> POST /api/message {text} -> Core.process_input(raw_text)
       normalize -> log user message -> parser
       -> "ael"          : _handle_ael                       (AEL interpreter)
       -> otherwise      : _handle_goal_or_conversation
            goal prefix  : create_goal -> "[GOAL CREATED]"
            else         : _handle_conversation
                skill -> language_intelligence (deterministic backend defers; a real
                local model would short-circuit here) -> correction acknowledgement
                -> Persian NLU fact stage -> learn_from_text -> ReasoningEngine.reason
                -> concept lookup -> Persian NLU question/request -> deterministic fallback
       log assistant message -> context.add_turn -> reply string
```

The Section 12–18 modules (`reasoning/reasoning_foundation|plan|decision|capability_boundary`,
`capabilities/` registry/matching/selection, `autonomy/`) were not reachable from this path. Only
the NLU analysis (Prompts 824–833) was computed, and only stored on `Core.last_nlu_analysis`.

## The new integration point

`runtime_integration/` (new package, outside every layer that must not know the capability stack):

- `bridge.py` — `build_runtime_result(turn)`: the read-only bridge.
- `runtime_core.py` — `RuntimeCore(Core)`: calls `Core.process_input()` unchanged, then (after the
  reply is final, with context counts still "before this message") builds the bridge result from the
  turn and keeps it as `last_runtime_result`.

`interface/server.py` `run()` and `android_entry.start()` now build a `RuntimeCore`, so every message
from the server or the app reaches the bridge:

```
POST /api/message -> RuntimeCore.process_input -> Core.process_input (unchanged) -> reply
                                               -> bridge.build_runtime_result -> last_runtime_result
GET  /api/runtime-result  (new, read-only)  -> that result
```

Why a subclass: existing boundary tests (Prompts 718, 842, 845, 846) pin the exact body of
`Core.process_input` and `_handle_goal_or_conversation`, and forbid `core/` (and other layers) from
referencing the capability registry/matching/selection modules. A subclass leaves both functions
byte-identical, and a plain `Core` (every existing test and caller) behaves exactly as before.

`core/core.py` changes are additive and inert for a plain `Core`: a `_turn_state = None` class
attribute, a `_mark_source()` helper, one `_mark_source(...)` label at each existing return point of
`_handle_conversation`, and a guarded stash of the relevance/reference/topic it already computed.
No branch condition, reply text or stored value changed. `/api/message` payloads are unchanged.

The result is one fixed-order, JSON-safe dict:

| Key | Content |
|---|---|
| `status` | `enriched` · `limited` · `invalid_input` · `bridge_error` |
| `route` | `empty_input` · `ael` · `goal` · `conversation` |
| `input` | raw type, normalized text (clipped to 200 chars in the report), length, validity |
| `understood_input` | Core's own `NLUAnalysis` via the Prompt 831 semantic view: intent, question/request/negation/correction flags, context reference, slots, relations |
| `reasoning` | Prompt 833 reasoning input → 834 request → 835 plan (steps) → 836/837 decision → 840 capability boundary, all with `executed: false` |
| `capability` | exact whole-word capability name found in the message → Prompt 841 registry projection → 845 match → 846 selection; suggestion only |
| `memory_context` | recent turns available, relevant turns Core selected, resolved reference, active topic, NLU turns recorded |
| `response` | `source` (one of 13 labels), `deterministic_fallback`, `generated_by_local_model` |
| `local_model` | backend kind, `Core.get_local_model_readiness()` status, whether a real backend is connected, whether it generated this turn, the connection point (`Core.use_local_language_model`) |
| `execution` | `allowed`, `executed`, `capability_executed`, `code_modified`, `autonomy_chain_executable`, `external_service_used` — constant `false`; `model_invoked`; `existing_runtime_effects` |

`execution.allowed/executed` describe the bridge and capabilities. `existing_runtime_effects`
separately and honestly lists what Core's *pre-existing* path already did that turn (AEL program
interpreted, goal + empty plan created, knowledge learned, personal fact stored, correction stored).

Design rules: observer only (never writes a reply, store, or context); never raises (a failing
section shrinks only itself; a total failure yields a minimal `bridge_error` result and the reply is
unchanged); NLU is Core's own analysis when it made one — otherwise the same pipeline is run
read-only and **records nothing** into the NLU context.

## What is now actually consumed by the runtime

- NLU analysis, semantic view, reasoning input (Prompts 824–833) — reported per turn
- Reasoning request, plan, plan validation, decision (834–837)
- Reasoning→capability boundary (840), without a spec, so no contract is ever built
- Capability registry, matching, selection (841, 845, 846), fed from Core's own capability table
- Conversation context, relevance selection, reference resolution, active topic (already in Core)
- Local-model readiness boundary (Prompts 407/408/413)

## Still not runtime-connected

- Capability contract (838/839) — needs an explicit spec nothing supplies
- Capability execution boundary (847) and readiness (848) — need an explicit lifecycle state; Core's
  `capabilities` table has none, so it is reported as `not_evaluated_no_explicit_lifecycle_state`
- Section 14 upgrade pipeline (849–862), Section 15 research/learning (863–875), Section 16
  capability creation (876–893), Section 17 approval/permission (894–901), Section 18 autonomy chain
  (902–909) — descriptive/safety architecture; deliberately **not** imported by the bridge
- A real local language model — only the boundary exists; the default backend is deterministic
- English NLU — the intent rules are Persian-centric, so most English messages report intent `unknown`
  and a `needs_information` decision (reported honestly, never guessed)

## Limitations to know

- The registry projection declares `outputs: ["capability_result"]` because the Prompt 841 descriptor
  requires an output; Core's capability table has no inputs/outputs. It is a lookup shape only.
- Capability identification is exact whole-word name matching (`code analysis`, `code_analysis`);
  no synonyms, so "analyze my code" suggests nothing.
- `last_runtime_result` is per-Core, like the other `last_*` fields; concurrent HTTP requests share it.
- Only a `RuntimeCore` produces results; code that builds a plain `Core` gets none (by design).

## What Prompt 911 should address

Make the runtime decision *use* the result rather than only report it, still without execution: give
capabilities an explicit lifecycle state (so the Prompt 847 boundary can be evaluated), feed
`reasoning.decision` / `next_stage` into response construction (e.g. ask the clarifying question the
plan names instead of the generic fallback), and begin widening English intent coverage — each behind
the same fallback-compatibility guarantee proven here. Connecting a real local model remains a
separate, later step through `Core.use_local_language_model`.
