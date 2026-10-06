# Prompt 914 - AEL learning state (runtime integration)

Finding: the existing runtime DOES persist AEL `TEACH` and `RELATE`.
`Core._handle_ael` -> `AELInterpreter.run` -> `LearningSystem.teach/relate`
(knowledge store). Before Prompt 914 the bridge could not see this: it only saw
the reply source `ael_program_interpreted` and always reported
`learning_performed_by_existing_runtime = False` for AEL input.

Change (observe-only):
- `RuntimeCore._handle_ael` temporarily watches `self.ael.run` and records, per
  instruction, `{kind, success}` from the interpreter's own results. The reply
  string is still exactly what `Core._handle_ael` returns.
- `bridge._learning_section` uses those results. New learning keys:
  `learning_outcome` and `ael_learning_instructions_performed`.

`learning_outcome` values:
- `not_a_learning_request` - ordinary message
- `performed_by_existing_runtime` - a TEACH/RELATE succeeded (or an existing
  conversation-path storage effect was reported)
- `interpreted_not_performed` - request recognised, existing runtime did not store it
  (execution failed, or no per-instruction result available)
- `learning_unavailable` - no learning system
- `malformed_or_unparsed` - syntax error / malformed input

Unchanged: no schema or database change, no new learning system, no capability
execution, no external AI/API/service, no code modification, no self-upgrade.
`learning_executed_by_bridge` is always False.
Known limit: a RELATE that was "already known" still counts as performed (the
interpreter reports success; no new duplicate is stored).
