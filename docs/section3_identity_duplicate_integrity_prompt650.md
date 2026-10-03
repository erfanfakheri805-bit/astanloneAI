# Prompt 650 - Knowledge identity / duplicate prevention (Section 3)

Result: audit only. No genuine identity defect found; **no production changes**.
Tests: `tests/test_knowledge_identity_duplicate_integrity_prompt650.py`.

Existing identity contract (asserted, unchanged):

- **Write identity is the exact, case-sensitive name.** `learn()`, `teach()` and `relate()` never fold case or whitespace. `Python`, `python` and ` Python ` are separate records. Exact repeats are no-ops. Blank or non-string names are rejected.
- **Resolution** (`correct()`, `resolve_name()`, `find_by_name_case_insensitive()`): an exact match wins, otherwise a single case-insensitive match. Several matches mean `ambiguous`. Then `correct()` raises `ValueError` and writes nothing, and the finders return `None`. Whitespace variants are not matched.
- **Relationship endpoints** are exact names. An existing endpoint is reused. A missing one, including a case or whitespace variant of an existing record, gets a stub (`status="stub"`, `source = source_type or "inferred"`).
- **Stub lifecycle:** `teach()`, `learn()` or `correct()` of the same exact name upgrades the stub in place. The row id is kept, the version goes up by 1, and status becomes `active`. Relationships stay attached. `source` follows `teach()`/`correct()` semantics, and the stub's `source_text`, `learning_method` and `confidence` are kept.
- **Natural-language learning** strips surrounding whitespace, then resolves an exact match first and a unique case-insensitive match second, so it reuses the canonical name. Repeats are no-ops.

Documented limitation (intentional, unchanged): a natural-language candidate that is case-insensitively ambiguous and is not itself an exact stored name (for example `PYTHON` against `Python` and `python`) is not merged into either. It becomes its own new stub, exactly as `learn("PYTHON")` would.
