# Prompt 919 - Reasoning handoff lifecycle

Section 19: Runtime Integration / Productization. Subsection: Reasoning Runtime Integration.

## Lifecycle

`RuntimeCore.get_last_reasoning_handoff()` always reflects the most recent turn:

- newest turn has a reasoning handoff -> that handoff (`available: True`, `executed: False`);
- newest turn has none (AEL, empty input, failing reasoning section, bridge error, or a turn where `Core`
  raised) -> `bridge.unavailable_reasoning_handoff(reason)` (`available: False`, `executed: False`);
- before the first message -> the same unavailable representation.

An older handoff cannot stay exposed: `last_runtime_result` is replaced at the end of every turn, and it is
now cleared at the start of `RuntimeCore.process_input()`, so a turn that raises before the bridge runs no
longer leaves the previous turn's result (and handoff) in place.

## Changes

`runtime_core.py`: one reset line at the start of `process_input()`. `bridge.py`: the handoff gains
`"available": True` so both shapes can be read the same way. Nothing else changed.

## Unchanged

The handoff is still descriptive/read-only and not consumed by any runtime decision. `Core`, the reasoning
modules, replies, AEL, capabilities, memory and the database schema are untouched. No external AI/API/service,
no network, no capability execution, no self-modification or self-upgrade.
