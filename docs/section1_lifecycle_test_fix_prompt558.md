# Prompt 558 — Lifecycle Test Failure: Root Cause and Fix

Investigated: `tests.test_self_upgrade_end_to_end_dry_run
.NoAutomaticActivationTests.test_no_stage_runs_twice_in_a_successful_lifecycle`

## Root cause

This was a **test-infrastructure bug, not a lifecycle implementation
bug.**

`tests/test_self_upgrade_end_to_end_dry_run.py` patched four stage
functions using a hardcoded string target, e.g.:

```python
mock.patch("tests.test_self_upgrade_end_to_end_dry_run.build_capability",
            wraps=build_capability)
```

This test file can be imported under two different module names
depending on how the suite is invoked:

- `tests.test_self_upgrade_end_to_end_dry_run` — when run as
  `python -m unittest tests.test_self_upgrade_end_to_end_dry_run` (the
  form documented in every test file's own "Run directly" docstring,
  including this one).
- the flat `test_self_upgrade_end_to_end_dry_run` — when run via
  `python -m unittest discover -s tests -p "test_*.py"` (the form used
  for the full suite, because `-s tests` makes the `tests/` directory
  itself the discovery root and top-level `sys.path` entry).

The hardcoded string target only ever matches the first form. Under
`discover`, `mock.patch("tests.<module>.<name>", ...)` still succeeds
(no `ImportError`) because the test file itself appends the parent
`python/` directory to `sys.path`, so `tests` is importable as a real
package — but doing so imports and patches a **second, otherwise-unused
copy** of the module. The lifecycle harness (`DryRunHarness`) keeps
calling the stage functions defined on the *first* (flat) copy, which was
never patched. Every spy's `call_count` therefore always read back `0`,
independent of what the lifecycle actually did.

Confirmed directly:

```
$ python -m unittest tests.test_self_upgrade_end_to_end_dry_run.NoAutomaticActivationTests.test_no_stage_runs_twice_in_a_successful_lifecycle
OK   (dotted import: single module identity, patch works)

$ python -m unittest discover -s tests -p test_self_upgrade_end_to_end_dry_run.py
FAIL (flat import: dual module identity, patch targets the unused copy)
```

A manual reproduction that mocks the four functions with
`mock.patch.object` on the actually-imported module object (rather than a
hardcoded string) shows each function is called **exactly once** in a
successful lifecycle, in every invocation mode — confirming the
lifecycle implementation itself (`self_upgrade/*`, the stage methods in
the test's own `DryRunHarness`, and `agent/agent_loop.py`'s wiring) is
correct and was never the source of the failure.

A second, pre-existing test in the same file
(`test_failed_verification_does_not_run_registration_again`) has the same
hardcoded-string pattern, but happened not to surface the bug because it
asserts `register_spy.assert_not_called()` — an assertion that is
(incorrectly) satisfied whether or not the patch actually took effect.
That test was fixed for consistency and correctness, even though it was
not itself reported as failing.

## Fix

Test-only change, in `tests/test_self_upgrade_end_to_end_dry_run.py`:
both `mock.patch("tests.test_self_upgrade_end_to_end_dry_run.<name>", ...)`
call sites now use `mock.patch.object(sys.modules[__name__], "<name>", ...)`
instead. `sys.modules[__name__]` always resolves to the module that is
actually executing, regardless of which name it was imported under, so
the patch reliably targets the real call site in every invocation mode.

No production code was changed. Nothing in `self_upgrade/`,
`agent/agent_loop.py`, or any other application module was modified.

## Files changed

- `tests/test_self_upgrade_end_to_end_dry_run.py` (2 patch-target fixes,
  both test-only)
- `tests/test_self_upgrade_lifecycle_mock_patch_fix.py` (new, focused
  regression coverage)
- `docs/section1_lifecycle_test_fix_prompt558.md` (this file)

## Test results

- New focused tests: 3/3 pass
  (`tests.test_self_upgrade_lifecycle_mock_patch_fix`)
- Relevant lifecycle file
  (`tests/test_self_upgrade_end_to_end_dry_run.py`), run the same way the
  full suite runs it (`unittest discover`): 45/45 pass
- Full suite (`unittest discover -s tests -p "test_*.py"`):
  **10,868 tests, 0 failures, 0 errors** (up from 10,865 tests / 1
  failure at the Prompt 557 baseline)

## Was the original failure resolved?

Yes. `test_no_stage_runs_twice_in_a_successful_lifecycle` passes under
both invocation modes, and the full suite now reports zero failures.

## Any remaining failures?

None. No other failures were introduced or uncovered.

## Scope discipline

Per the Prompt 558 restrictions, nothing was touched in
`learning/learned_knowledge_statistics.py` or the Prompt 541–556
validator chain, no new diagnostic validator layer was added, and no
work was done on Section 2 language intelligence, multimodal, web/
automation, game creation, voice, or external AI APIs. The change is
confined to the one failing test file plus one new regression-test file.
