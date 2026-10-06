# Prompt 915 - Lightweight RELATE persistence result

Section: Runtime Integration / Productization. Subsection: AEL / Learning Runtime - persistence result accuracy.

## Exact RELATE behavior discovered

- `AELInterpreter._execute_relate` calls `LearningSystem.relate(from, to, relation)`, which returns
  `{"created": bool, "contradiction": row-or-None}`. `created` is False when the relationship already
  existed (no duplicate is stored).
- The interpreter turns that into `ExecutionResult(success=True, message)`. Only the message text
  ("(Already known - no duplicate stored.)") carries the distinction; the per-instruction result has no
  `created` field. A successful RELATE instruction therefore does NOT mean a new relationship was stored.
- A malformed RELATE is a syntax error (`ExecutionResult(None, False, ...)`), a validation failure
  (`kind == "RELATE"`, `success False`), or an exception inside `relate` (`success False`).

## What changed (observation only)

- `runtime_integration/runtime_core.py`: while `Core._handle_ael` runs, `RuntimeCore` also watches
  `self.learning.relate`. The watcher calls the real method, records only the returned `created` bool
  after it returns, and passes the original return value (or exception) through untouched. It is removed
  afterwards (a pre-existing instance attribute, e.g. a test mock, is restored). Result is handed to the
  bridge as `relate_outcomes`.
- `runtime_integration/bridge.py`: the `learning` section gains seven always-present keys:
  `relate_requested`, `relate_instructions_requested`, `relate_instructions_executed`,
  `relate_instructions_failed`, `relationships_created`, `relationships_already_existed`,
  `relate_persistence`.

`relate_persistence` values: `not_a_relate_request`, `new_relationship_created`,
`relationship_already_existed`, `executed_persistence_unconfirmed` (instruction succeeded but no matching
evidence from `LearningSystem.relate`, or learning unavailable), `relate_failed_or_malformed`, `mixed`.

## Unchanged

LearningSystem.relate semantics, the SQLite schema, user-facing replies, AEL TEACH behavior, and ordinary
messages. Existing Prompt 914 learning fields keep their meaning (`learning_performed_by_existing_runtime`
and `ael_learning_instructions_performed` still mean "the existing runtime executed the instruction
successfully"); the new `relate_*` fields are the authoritative answer for whether a relationship is new.

## Safety

No external AI, API or service; no capability execution; no code modification; no self-upgrade; no network;
no new schema.

## Remaining limitation

`created=False` covers both "identical repeat" and "existing row updated with a new confidence/source";
LearningSystem.relate exposes only the bool, so the bridge reports both as `relationship_already_existed`.
