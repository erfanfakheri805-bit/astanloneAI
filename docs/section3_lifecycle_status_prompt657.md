# Prompt 657 - End-of-lifecycle / status behavior of knowledge records (Section 3)

Result: audit only. No genuine defect found; **no production changes**.
Tests: `tests/test_knowledge_lifecycle_status_prompt657.py` (30 tests).

## Does a retirement / deactivation API exist? No.
There is no retire, deactivate, archive, delete, forget or expire operation for knowledge, and no production `DELETE FROM knowledge`. Nothing was added. `status` is a plain `TEXT NOT NULL DEFAULT 'active'` column with no CHECK constraint.

## Every production path that sets a knowledge status
All writes go through `KnowledgeSystem.learn()` (the only code that runs `INSERT INTO knowledge` / `UPDATE knowledge`):
- `learn(status=...)`: direct `KnowledgeSystem` call. Default `active`; any string is stored unvalidated.
- `correct(status=...)`: `KnowledgeSystem.correct()`. `None` becomes `active`.
- `relate()` creates a missing endpoint with `status="stub"`.

`LearningSystem.teach()`, `LearningSystem.correct()`, natural-language learning and conversational correction can only end in `active`, or create `stub` via `relate()`. A non-active status other than `stub` (tests use `deprecated`, an existing convention) is reachable only by calling `KnowledgeSystem` directly. No status value was added.

## Three states that are not conflated
| State | Meaning |
|---|---|
| Exists, non-active | Row present, same id. `get`, `all`, `search`, `recall`, `resolve_name` and context selection find it. Relationships stay attached. |
| Does not exist | `get` is None, `resolve_name` is `not_found`, `correct()` returns None and creates nothing. It has no events. |
| Historically changed | `learning_events` rows exist for the name. This says nothing about the current status. A stub can be non-active with no teach/correct history; an active record can have many events. |

## Verified semantics
- **Transitions:** a status change is an ordinary mutation. Version +1, `updated_at` moves, id, `created_at` and provenance stay. The same effective values again are a no-op, with no phantom event. Flip-flops are real each time. Non-active to active: `teach` (same text), `correct` (status None), or a stub upgrade. All update the same row.
- **Events:** direct `KnowledgeSystem` transitions write none (L4). `teach` of a non-active record logs a normal `teach` event. A status-only `correct` logs `'d' -> 'd'` (L2, preserved). Failed lifecycle ops (event insert raising) roll back knowledge and history, also after reopen.
- **Correction / teaching of a non-active record:** updates one row; no duplicate is created. The case-insensitive unique match resolves; an ambiguous or case-variant name raises and mutates nothing. A near-miss name is non-existent, not a lifecycle op.
- **Relationships:** never redirected, duplicated, deleted or status-filtered. `relate()` on non-active endpoints reuses them verbatim (no reactivation, no version bump, no new stub). Edges are identical through every transition. An edge refresh on a non-active endpoint touches only the edge.
- **Readers:** none filter by status. A bare stub (no description, no edge) is not usable learned-knowledge content (Prompt 637/638); the same stub with an edge is.
- **Natural language:** NL relations reuse a non-active record without mutating it. Conversational correction goes through `LearningSystem.correct`, so a non-active record becomes `active` with the normal `correct` event. NL on other concepts leaves non-active records alone.
- **History / persistence:** events stay append-only. State survives close/reopen exactly and continues afterwards. Independent lifecycle sequences give the same final state in either order.

## Remaining limitations (intentional, unchanged)
- **No end-of-life mechanism:** the only implicit "inactive" states are `stub` and any string a direct caller stores.
- **Reactivation on teach/correct:** `teach()` and `correct()` always set `active`, so re-teaching or correcting a non-active record reactivates it. That is existing behavior and was not made symmetric.
- **L2 / L4:** status is absent from events (L2), and direct `KnowledgeSystem` status changes write no events (L4). Version is therefore not reconstructable from history once such calls are used; the live row stays authoritative.
