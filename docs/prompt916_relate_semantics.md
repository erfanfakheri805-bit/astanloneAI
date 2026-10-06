# Prompt 916 - RELATE persistence semantics (documentation only)

Section: Runtime Integration / Productization. Subsection: AEL / Learning Runtime.

## Semantics discovered in Prompt 915

1. `LearningSystem.relate()` returns a `created` boolean (inside `{"created": bool, "contradiction": ...}`).
2. `created=True` means a new relationship was created.
3. `created=False` means no new relationship was created. It does not distinguish:
   - an identical existing relationship (true no-op), or
   - an existing relationship updated with new confidence/source.
4. `AELInterpreter` exposes a successful RELATE execution (`success=True`) but does not directly expose
   the `created` flag; only the message text differs.
5. Prompt 915's runtime integration observes the real `LearningSystem.relate()` result without changing
   its semantics.
6. The bridge reports one of:
   - new relationship created (`new_relationship_created`)
   - relationship already existed / no new creation (`relationship_already_existed`)
   - unconfirmed persistence (`executed_persistence_unconfirmed`)
   - failed/malformed RELATE (`relate_failed_or_malformed`)

## Known limitation

Because `created=False` covers both "identical" and "updated", the bridge reports both as
`relationship_already_existed`. This is intentionally left for a future focused change.

## Scope of this prompt

Documentation only. No runtime code, tests, database or schema changes. No external AI/API/service,
no network, no capability execution, no self-modification, no self-upgrade.
