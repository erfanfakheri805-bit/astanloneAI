"""
Tests for the SelfUpgradeRequest model (self_upgrade/self_upgrade_request.py).

Covers: creating a valid request, validation failures for an empty/
missing goal and requested_capability, an invalid status, to_dict()
serialization, and that this stage never executes or otherwise acts
on a request - it is a standalone record only.

Run directly:
    python -m unittest tests.test_self_upgrade_request -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from self_upgrade.self_upgrade_request import (
    SelfUpgradeRequest,
    STATUS_REQUESTED,
    STATUS_ANALYZING,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_REJECTED,
    ALL_STATUSES,
    DEFAULT_STATUS,
)


def _valid_request(**overrides):
    fields = dict(
        request_id="upgrade_request-1",
        goal="Reduce startup latency",
        requested_capability="code_change_plan",
        reason="Startup is slower than the target budget.",
    )
    fields.update(overrides)
    return SelfUpgradeRequest(**fields)


class TestValidRequest(unittest.TestCase):
    def setUp(self):
        self.request = _valid_request()

    def test_is_valid(self):
        self.assertTrue(self.request.is_valid())

    def test_fields_stored_as_given(self):
        self.assertEqual(self.request.request_id, "upgrade_request-1")
        self.assertEqual(self.request.goal, "Reduce startup latency")
        self.assertEqual(self.request.requested_capability, "code_change_plan")
        self.assertEqual(self.request.reason, "Startup is slower than the target budget.")

    def test_default_status_is_requested(self):
        self.assertEqual(self.request.status, STATUS_REQUESTED)
        self.assertEqual(DEFAULT_STATUS, STATUS_REQUESTED)

    def test_created_at_is_set(self):
        self.assertIsInstance(self.request.created_at, str)
        self.assertTrue(self.request.created_at)

    def test_reason_defaults_to_empty_string(self):
        request = SelfUpgradeRequest(
            request_id="upgrade_request-2", goal="Improve reliability", requested_capability="code_change_plan",
        )
        self.assertEqual(request.reason, "")
        self.assertTrue(request.is_valid())


class TestSupportedInitialStatuses(unittest.TestCase):
    """Requirement 3: exactly these five statuses are supported, and a
    request built with any one of them is valid."""

    def test_all_statuses(self):
        self.assertEqual(
            ALL_STATUSES,
            (STATUS_REQUESTED, STATUS_ANALYZING, STATUS_COMPLETED, STATUS_FAILED, STATUS_REJECTED),
        )

    def test_each_supported_status_is_valid(self):
        for status in ALL_STATUSES:
            request = _valid_request(status=status)
            self.assertTrue(request.is_valid(), f"status {status!r} should be valid")

    def test_unsupported_status_is_invalid(self):
        request = _valid_request(status="NOT_A_REAL_STATUS")
        self.assertFalse(request.is_valid())


class TestValidationFailures(unittest.TestCase):
    """Requirement 4: goal and requested_capability must be non-empty."""

    def test_empty_goal_is_invalid(self):
        request = _valid_request(goal="")
        self.assertFalse(request.is_valid())

    def test_whitespace_only_goal_is_invalid(self):
        request = _valid_request(goal="   ")
        self.assertFalse(request.is_valid())

    def test_missing_goal_type_is_invalid(self):
        request = _valid_request(goal=None)
        self.assertFalse(request.is_valid())

    def test_empty_requested_capability_is_invalid(self):
        request = _valid_request(requested_capability="")
        self.assertFalse(request.is_valid())

    def test_whitespace_only_requested_capability_is_invalid(self):
        request = _valid_request(requested_capability="   ")
        self.assertFalse(request.is_valid())

    def test_wrong_type_requested_capability_is_invalid(self):
        request = _valid_request(requested_capability=123)
        self.assertFalse(request.is_valid())

    def test_empty_request_id_is_invalid(self):
        request = _valid_request(request_id="")
        self.assertFalse(request.is_valid())

    def test_non_string_reason_is_invalid(self):
        request = _valid_request(reason=123)
        self.assertFalse(request.is_valid())

    def test_construction_never_raises_on_bad_input(self):
        try:
            request = SelfUpgradeRequest(
                request_id=None, goal=None, requested_capability=None, reason=None, status="bogus",
            )
        except Exception as exc:  # pragma: no cover - defensive
            self.fail(f"SelfUpgradeRequest construction raised: {exc!r}")
        self.assertFalse(request.is_valid())


class TestSerialization(unittest.TestCase):
    """Requirement 5: the model is serializable via to_dict()."""

    def test_to_dict_contains_required_fields(self):
        request = _valid_request()
        data = request.to_dict()
        self.assertEqual(
            set(data.keys()),
            {"request_id", "goal", "requested_capability", "reason", "status", "created_at"},
        )

    def test_to_dict_values_match_instance(self):
        request = _valid_request()
        data = request.to_dict()
        self.assertEqual(data["request_id"], request.request_id)
        self.assertEqual(data["goal"], request.goal)
        self.assertEqual(data["requested_capability"], request.requested_capability)
        self.assertEqual(data["reason"], request.reason)
        self.assertEqual(data["status"], request.status)
        self.assertEqual(data["created_at"], request.created_at)

    def test_to_dict_is_json_serializable(self):
        import json
        request = _valid_request()
        json.dumps(request.to_dict())  # never raises on a plain, serializable result


class TestNeverExecutesOrActsOnARequest(unittest.TestCase):
    """Requirements 6, 7: this stage never executes an upgrade and
    never modifies existing upgrade behavior - a SelfUpgradeRequest is
    a standalone record with no execution/analysis methods at all."""

    def test_no_execution_or_analysis_methods(self):
        request = _valid_request()
        for forbidden in ("execute", "run", "analyze", "approve", "apply"):
            self.assertFalse(hasattr(request, forbidden))

    def test_status_never_changes_on_its_own(self):
        request = _valid_request()
        self.assertEqual(request.status, STATUS_REQUESTED)
        request.is_valid()
        request.to_dict()
        self.assertEqual(request.status, STATUS_REQUESTED)


if __name__ == "__main__":
    unittest.main()
