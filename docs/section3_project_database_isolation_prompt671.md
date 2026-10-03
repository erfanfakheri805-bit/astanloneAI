# Prompt 671 - Section 3: test database isolation / pristine project state

## Problem
During the Prompt 670 broader regression the shipped `data/memory.db` changed from the pristine baseline
(`0d79f26a...957bb`) to another hash.

## Root cause (traced, not assumed)
Every `sqlite3.connect()` in the full suite (12,616 tests) was recorded with an audit hook (`sys.addaudithook`)
and compared against the project DB path; the DB hash was compared before/after. Exactly **7 tests in 2 classes**
opened the shipped DB - none of them Prompt 670 or any newly added test:

- `tests/test_learned_pattern_matching_in_understanding.py::TestCoreIntegration` (3 tests)
- `tests/test_learned_sentence_structure_in_understanding.py::TestCoreIntegration` (4 tests)

Each built a bare `Core()`. `Core.__init__` -> `MemorySystem()` -> `_default_db_path()` -> `DesktopPlatformAdapter`
default data dir = `<python root>/data`, i.e. the shipped `data/memory.db`. The tests then wrote to it
(`learn_language_item`, `process_input`); even a bare open runs schema/migration statements.

## Fix (test infrastructure only)
Both classes now create a per-test `tempfile.TemporaryDirectory()` and build
`Core(memory_db_path=<tmp>/memory.db, skill_definitions_dir=<tmp>/skills)`, closing the connection on cleanup.
Assertions, scenarios and coverage are unchanged. No DB is copied/restored afterwards; the expected hash is unchanged.

Other `Core()` sites were audited and are already isolated: `test_platform_layer.py` installs a temp
platform adapter via `set_platform()`; `test_self_upgrade_end_to_end_dry_run.py` only fingerprints the default path.

## Production code
Unchanged. `_default_db_path()`, `default_memory_db_path()` and `DesktopPlatformAdapter` behave exactly as before
(asserted by a test). No env-var/global override was introduced, so tests that legitimately exercise the default
path keep doing so.

## Regression tests - `tests/test_project_database_isolation_prompt671.py`
Project DB hash and an audit-hook connect log are checked around every test. Covers: pristine hash unchanged;
disposable-copy writes; Core init opens only the explicit temp path; knowledge, learning, relationship, lifecycle
status (`set_status`) writes; close/reopen; the two previously offending modules and `test_platform_layer` traced in
a subprocess (no connect to the project DB); a static AST guard against bare `Core()`/`MemorySystem()` in tests
(unless the module installs its own platform adapter); the runtime default path unchanged; Prompt 670 lifecycle
tests still pass. Negative control: against the unfixed tests, the guard and subprocess trace tests fail.

## Intentional limitations
- The static guard is name-based (`Core`/`MemorySystem` with no arguments); indirect construction through other
  helpers is covered only by the dynamic subprocess traces of the affected modules and by the full-suite check.
- Tests that legitimately point at a copy of the project DB may mutate that copy.
