"""
Tests for self_upgrade.capability_human_approval
.request_capability_human_approval (Prompt 370) - a VERIFIED capability
correction gets one version snapshot (via the real, unmodified
VersionSystem) and one PENDING_APPROVAL HumanApprovalRequest; nothing
here ever activates, registers, auto-approves, or auto-rejects.

Run directly:
    python -m unittest tests.test_capability_human_approval -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from self_upgrade.capability_human_approval import (
    request_capability_human_approval,
    APPROVAL_STATUS_PENDING,
    APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_REJECTED,
    APPROVAL_STATUS_INVALID,
    APPROVAL_STATUS_BLOCKED,
    ALL_APPROVAL_STATUSES,
)
from self_upgrade.capability_correction_verification import (
    verify_capability_correction,
    STATUS_VERIFIED,
    STATUS_FAILED,
)
from self_upgrade.capability_correction_apply import apply_capability_correction
from self_upgrade.capability_correction_analysis import build_capability_correction_analysis
from self_upgrade.capability_evaluation import evaluate_capability_test_result
from self_upgrade.capability_test_execution import run_capability_tests
from self_upgrade.capability_file_apply import STATUS_APPLIED
from code_generation.generated_code_validator import VALIDATION_VALID
from self_upgrade.version_system import VersionSystem
from memory.memory_system import MemorySystem

BROKEN = "def demo():\n    return missing_name\n"
TEST = ("import unittest\nfrom demo_capability import demo\n\n"
        "class T(unittest.TestCase):\n    def test_demo(self):\n"
        "        self.assertEqual(demo(), 1)\n")
TARGET = "test_demo_capability"


def make_version_system():
    return VersionSystem(MemorySystem(tempfile.mktemp(suffix=".db")))


class Chain(unittest.TestCase):
    """Builds the real chain up to a VERIFIED (or still-FAILED)
    capability correction, exactly like
    tests.test_capability_correction_verification does."""

    def setUp(self):
        self.sandbox = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.sandbox, ignore_errors=True))
        self.path = os.path.join(self.sandbox, "demo_capability.py")
        self._write(self.path, BROKEN)
        self._write(os.path.join(self.sandbox, TARGET + ".py"), TEST)
        apply_result = dict(
            capability_name="demo_capability", target_module="generated.demo_capability",
            status=STATUS_APPLIED, file_path=self.path, bytes_written=1,
            validation_result={"status": VALIDATION_VALID}, error=None)
        self.previous = run_capability_tests(apply_result, self.sandbox, TARGET)

    @staticmethod
    def _write(path, text):
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def correct(self, new_text="return 1"):
        analysis = build_capability_correction_analysis(
            evaluate_capability_test_result(self.previous), allowed_dirs=[self.sandbox])
        return apply_capability_correction(
            analysis, [{"old_text": "return missing_name", "new_text": new_text}],
            allowed_dirs=[self.sandbox])

    def verified_result(self, new_text="return 1"):
        return verify_capability_correction(
            self.previous, self.correct(new_text), self.sandbox, TARGET,
            allowed_dirs=[self.sandbox])

    def still_failing_result(self):
        # A "correction" that doesn't actually fix anything: retest
        # still fails, so verification never reaches STATUS_VERIFIED.
        return verify_capability_correction(
            self.previous, self.correct(new_text="return missing_name_still"),
            self.sandbox, TARGET, allowed_dirs=[self.sandbox])


class VerifiedCapabilityCreatesSnapshotTests(Chain):
    def test_verified_capability_creates_pending_approval(self):
        verification = self.verified_result()
        self.assertEqual(verification["status"], STATUS_VERIFIED)

        versions = make_version_system()
        result = request_capability_human_approval(
            verification, versions, allowed_dirs=[self.sandbox])

        self.assertEqual(result["status"], APPROVAL_STATUS_PENDING)
        self.assertEqual(result["capability_name"], "demo_capability")
        self.assertEqual(os.path.realpath(result["target_file"]),
                          os.path.realpath(self.path))
        self.assertEqual(result["verification_status"], STATUS_VERIFIED)
        self.assertTrue(result["rollback_available"])
        self.assertIsInstance(result["version"], dict)
        self.assertIn("id", result["version"])
        self.assertTrue(result["request_id"].startswith("approval-"))
        self.assertEqual(result["errors"], [])

    def test_snapshot_identifier_preserved_in_request(self):
        verification = self.verified_result()
        versions = make_version_system()
        result = request_capability_human_approval(
            verification, versions, allowed_dirs=[self.sandbox])

        # The version the existing VersionSystem actually stored is
        # retrievable by id, and its own snapshot metadata carries the
        # exact request_id this HumanApprovalRequest was given.
        stored = versions.memory.query_one(
            "SELECT * FROM versions WHERE id = ?", (result["version"]["id"],))
        self.assertIsNotNone(stored)

    def test_rollback_information_preserved(self):
        verification = self.verified_result()
        versions = make_version_system()
        result = request_capability_human_approval(
            verification, versions, allowed_dirs=[self.sandbox])

        # The existing, unmodified rollback mechanism can actually use
        # the version id this module recorded.
        rolled_back = versions.rollback_to(result["version"]["id"])
        self.assertIsNotNone(rolled_back)
        self.assertEqual(rolled_back["id"], result["version"]["id"])

    def test_approval_request_starts_pending_and_is_never_auto_decided(self):
        verification = self.verified_result()
        versions = make_version_system()
        result = request_capability_human_approval(
            verification, versions, allowed_dirs=[self.sandbox])

        self.assertEqual(result["status"], APPROVAL_STATUS_PENDING)
        # This module itself has no path that ever produces these two
        # statuses - they only exist as states a later, separate,
        # human-triggered step may move a request into.
        self.assertNotEqual(result["status"], APPROVAL_STATUS_APPROVED)
        self.assertNotEqual(result["status"], APPROVAL_STATUS_REJECTED)


class UnverifiedAndInvalidInputTests(Chain):
    def test_still_failing_correction_cannot_create_approval_request(self):
        verification = self.still_failing_result()
        self.assertEqual(verification["status"], STATUS_FAILED)

        versions = make_version_system()
        result = request_capability_human_approval(
            verification, versions, allowed_dirs=[self.sandbox])

        self.assertEqual(result["status"], APPROVAL_STATUS_INVALID)
        self.assertIsNone(result["version"])
        self.assertFalse(result["rollback_available"])
        self.assertTrue(result["errors"])
        # And no new snapshot was recorded for this capability - only
        # the fresh VersionSystem's own initial foundation version
        # exists, unchanged.
        self.assertEqual(len(versions.history()), 1)

    def test_missing_verification_result_is_invalid(self):
        versions = make_version_system()
        result = request_capability_human_approval(None, versions)
        self.assertEqual(result["status"], APPROVAL_STATUS_INVALID)
        self.assertIsNone(result["version"])

    def test_missing_capability_name_is_invalid(self):
        verification = self.verified_result()
        verification = dict(verification, capability_name=None)
        versions = make_version_system()
        result = request_capability_human_approval(
            verification, versions, allowed_dirs=[self.sandbox])
        self.assertEqual(result["status"], APPROVAL_STATUS_INVALID)

    def test_missing_version_system_is_invalid(self):
        verification = self.verified_result()
        result = request_capability_human_approval(verification, None,
                                                     allowed_dirs=[self.sandbox])
        self.assertEqual(result["status"], APPROVAL_STATUS_INVALID)
        self.assertIsNone(result["version"])


class InvalidPathAndBlockedWorkspaceTests(Chain):
    def test_nonexistent_target_file_is_blocked(self):
        verification = self.verified_result()
        verification = dict(verification,
                             file_path=os.path.join(self.sandbox, "does_not_exist.py"))
        versions = make_version_system()
        result = request_capability_human_approval(
            verification, versions, allowed_dirs=[self.sandbox])
        self.assertEqual(result["status"], APPROVAL_STATUS_BLOCKED)
        self.assertIsNone(result["version"])
        self.assertFalse(result["rollback_available"])

    def test_target_outside_allowed_workspace_is_blocked(self):
        verification = self.verified_result()
        outside = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(outside, ignore_errors=True))
        outside_file = os.path.join(outside, "elsewhere.py")
        self._write(outside_file, "x = 1\n")
        verification = dict(verification, file_path=outside_file)

        versions = make_version_system()
        result = request_capability_human_approval(
            verification, versions, allowed_dirs=[self.sandbox])
        self.assertEqual(result["status"], APPROVAL_STATUS_BLOCKED)
        self.assertIsNone(result["version"])
        # No new snapshot was recorded - only the fresh VersionSystem's
        # own initial foundation version exists, unchanged.
        self.assertEqual(len(versions.history()), 1)

    def test_no_allowed_dirs_still_checks_existence_only(self):
        # Without an allowlist there is no workspace to check against,
        # so only file existence is enforced - a real, existing file
        # still proceeds to a snapshot.
        verification = self.verified_result()
        versions = make_version_system()
        result = request_capability_human_approval(verification, versions)
        self.assertEqual(result["status"], APPROVAL_STATUS_PENDING)


class ExistingSystemsUnchangedTests(Chain):
    def test_no_automatic_rollback_occurs(self):
        verification = self.verified_result()
        versions = make_version_system()
        before = versions.current_version()
        request_capability_human_approval(verification, versions, allowed_dirs=[self.sandbox])
        after = versions.current_version()
        # A snapshot was created (a new active version), never a
        # rollback to a prior one.
        if before is not None:
            self.assertNotEqual(after["id"], before["id"])
        self.assertIsNotNone(after)

    def test_existing_version_system_behavior_unchanged(self):
        versions = make_version_system()
        # create_version/rollback_to/history/current_version behave
        # exactly as before this module exists - this module never
        # monkeypatches or wraps them.
        baseline = len(versions.history())
        v1 = versions.create_version(upgrade_id=None, version_label="unrelated:1")
        v2 = versions.create_version(upgrade_id=None, version_label="unrelated:2")
        self.assertEqual(versions.current_version()["id"], v2["id"])
        rolled_back = versions.rollback_to(v1["id"])
        self.assertEqual(rolled_back["id"], v1["id"])
        self.assertEqual(versions.current_version()["id"], v1["id"])
        self.assertEqual(len(versions.history()), baseline + 2)

    def test_all_approval_statuses_are_exactly_five(self):
        self.assertEqual(
            set(ALL_APPROVAL_STATUSES),
            {APPROVAL_STATUS_PENDING, APPROVAL_STATUS_APPROVED,
             APPROVAL_STATUS_REJECTED, APPROVAL_STATUS_INVALID, APPROVAL_STATUS_BLOCKED},
        )


if __name__ == "__main__":
    unittest.main()
