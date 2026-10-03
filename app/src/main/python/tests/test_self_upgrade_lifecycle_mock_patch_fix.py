"""
Tests for Prompt 558 - regression coverage for the previously-failing
`test_no_stage_runs_twice_in_a_successful_lifecycle`.

Root cause (see docs/section1_lifecycle_test_fix_prompt558.md for the full
writeup): `tests/test_self_upgrade_end_to_end_dry_run.py` used to patch
functions via a hardcoded string target
("tests.test_self_upgrade_end_to_end_dry_run.<name>"). Depending on how
the suite is invoked, that test file can be imported under two different
module names:

    - "tests.test_self_upgrade_end_to_end_dry_run" when run as
      `python -m unittest tests.test_self_upgrade_end_to_end_dry_run`
      (matches every test file's own "Run directly" docstring), or
    - the flat "test_self_upgrade_end_to_end_dry_run" when run via
      `python -m unittest discover -s tests` (used for the full suite).

A hardcoded "tests.<module>.<name>" patch target only ever matches the
first form. Under discovery, `mock.patch("tests.<module>.<name>", ...)`
silently imports and patches a second, otherwise-unused copy of the
module while the actual test harness keeps calling the functions on the
first (flat) copy - so the patched spy's `call_count` always read back 0,
regardless of what the lifecycle actually did.

This is a lifecycle-test-only bug: the lifecycle implementation itself
(self_upgrade/*, agent/agent_loop.py) calls each stage function exactly
once in every invocation mode. Prompt 558 fixed the test by patching
`sys.modules[__name__]` instead of a hardcoded dotted string; this file
pins that fix down and demonstrates the two module identities directly so
the failure mode cannot silently come back.

Run directly:
    python -m unittest tests.test_self_upgrade_lifecycle_mock_patch_fix -v
"""

import importlib
import os
import subprocess
import sys
import unittest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PYTHON_DIR = os.path.dirname(_TESTS_DIR)
sys.path.append(_PYTHON_DIR)
# `unittest discover -s tests` puts the tests/ directory itself on
# sys.path so test files import under their flat name; replicate that
# here so the flat import below succeeds regardless of how *this* file
# was invoked.
sys.path.append(_TESTS_DIR)


class DualModuleIdentityRegressionTests(unittest.TestCase):
    """Demonstrates the exact mechanism behind the original failure."""

    def test_module_can_be_imported_under_two_different_names(self):
        # This is the underlying condition that made the hardcoded string
        # patch target silently target the wrong module object.
        flat = importlib.import_module("test_self_upgrade_end_to_end_dry_run")
        dotted = importlib.import_module(
            "tests.test_self_upgrade_end_to_end_dry_run")
        self.assertIsNot(
            flat, dotted,
            "if these ever become the same module object, the original "
            "bug mechanism no longer applies, but this test file should "
            "be re-checked rather than silently left in place")

    def test_fixed_patch_target_no_longer_uses_a_hardcoded_dotted_string(self):
        # Guards against the exact regression: re-introducing
        # mock.patch("tests.test_self_upgrade_end_to_end_dry_run....)
        # would silently reintroduce the original bug.
        path = os.path.join(_TESTS_DIR, "test_self_upgrade_end_to_end_dry_run.py")
        with open(path, "r", encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn('mock.patch("tests.test_self_upgrade_end_to_end_dry_run', source)


class LifecycleStageSpyRegressionTests(unittest.TestCase):
    """Runs the exact previously-failing test under `unittest discover`,
    the invocation mode that originally exposed the bug, as a subprocess
    so the import-mode is genuinely the discovery one (not the one this
    test file itself happens to run under)."""

    def test_no_stage_runs_twice_passes_under_discovery_invocation(self):
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests",
             "-p", "test_self_upgrade_end_to_end_dry_run.py",
             "-k", "test_no_stage_runs_twice_in_a_successful_lifecycle"],
            cwd=_PYTHON_DIR, capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(
            result.returncode, 0,
            "expected the previously-failing test to pass under "
            "`unittest discover`; stderr:\n%s" % result.stderr)
        self.assertIn("Ran 1 test", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
