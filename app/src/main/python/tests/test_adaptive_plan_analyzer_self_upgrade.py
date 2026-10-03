"""
Tests for AdaptivePlanAnalyzer.analyze_self_upgrade_request (Prompt 358)
==========================================================================
Covers connecting `self_upgrade.self_upgrade_request.SelfUpgradeRequest`
(Prompt 357) to the existing `planning.adaptive_plan_analyzer.
AdaptivePlanAnalyzer`: a valid request producing a structured analysis,
an incomplete/invalid request producing a clear blocker instead of a
guess, and blockers being detected from the analyzer's existing,
already-supplied capability registries (missing/unavailable capability,
missing handler).

Run directly:
    python -m unittest tests.test_adaptive_plan_analyzer_self_upgrade -v
or as part of the full suite:
    python -m unittest discover -s . -p "test_*.py" -v
(from app/src/main/python/)
"""

import os
import sys
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from planning.adaptive_plan_analyzer import (
    AdaptivePlanAnalyzer,
    BLOCKER_INVALID_REQUEST,
    BLOCKER_MISSING_CAPABILITY,
    BLOCKER_UNAVAILABLE_CAPABILITY,
    BLOCKER_MISSING_HANDLER,
)
from self_upgrade.self_upgrade_request import SelfUpgradeRequest, STATUS_REQUESTED
from execution.capability_handlers import CapabilityHandlerRegistry
from execution.code_change_plan_capability import (
    CAPABILITY_NAME as CODE_CHANGE_PLAN_NAME,
    make_code_change_plan_handler,
)


class FakeCapabilitySystem:
    """Same minimal stand-in already used by
    tests/test_adaptive_plan_analyzer.py's own FakeCapabilitySystem."""

    def __init__(self, registered=None):
        self._registered = dict(registered) if registered else {}

    def all(self):
        return [
            {"name": name, "enabled": enabled, "status": "enabled" if enabled else "disabled"}
            for name, enabled in self._registered.items()
        ]


def _request(**overrides):
    fields = dict(
        request_id="upgrade_request-1",
        goal="Reduce startup latency",
        requested_capability="code_change_plan",
        reason="Startup is slower than the target budget.",
    )
    fields.update(overrides)
    return SelfUpgradeRequest(**fields)


def _analyzer(capability_system=None, capability_handlers=None):
    goals = GoalManager()
    plans = PlanManager(goals)
    return AdaptivePlanAnalyzer(
        goals, plans,
        capability_system=capability_system,
        capability_handlers=capability_handlers,
    )


RESULT_KEYS = {
    "request_id", "goal", "requested_capability",
    "required_capabilities", "affected_systems", "blockers", "warnings",
}


# --------------------------------------------------------------------
# Valid request
# --------------------------------------------------------------------
class ValidRequestTests(unittest.TestCase):
    def test_result_shape(self):
        analyzer = _analyzer()
        result = analyzer.analyze_self_upgrade_request(_request())
        self.assertEqual(set(result.keys()), RESULT_KEYS)

    def test_fields_pass_through(self):
        analyzer = _analyzer()
        result = analyzer.analyze_self_upgrade_request(_request())
        self.assertEqual(result["request_id"], "upgrade_request-1")
        self.assertEqual(result["goal"], "Reduce startup latency")
        self.assertEqual(result["requested_capability"], "code_change_plan")

    def test_required_capabilities_is_requested_capability(self):
        analyzer = _analyzer()
        result = analyzer.analyze_self_upgrade_request(_request())
        self.assertEqual(result["required_capabilities"], ["code_change_plan"])

    def test_no_blockers_when_capability_registered_and_handled(self):
        capability_system = FakeCapabilitySystem({"code_change_plan": True})
        handlers = CapabilityHandlerRegistry()
        handlers.register("code_change_plan", lambda data: data)
        analyzer = _analyzer(capability_system=capability_system, capability_handlers=handlers)

        result = analyzer.analyze_self_upgrade_request(_request())

        self.assertEqual(result["blockers"], [])

    def test_affected_systems_uses_handler_module(self):
        handlers = CapabilityHandlerRegistry()
        handlers.register(CODE_CHANGE_PLAN_NAME, make_code_change_plan_handler())
        analyzer = _analyzer(capability_handlers=handlers)

        result = analyzer.analyze_self_upgrade_request(
            _request(requested_capability=CODE_CHANGE_PLAN_NAME)
        )

        self.assertEqual(result["affected_systems"], ["execution.code_change_plan_capability"])

    def test_never_mutates_request(self):
        analyzer = _analyzer()
        request = _request()
        analyzer.analyze_self_upgrade_request(request)
        self.assertEqual(request.status, STATUS_REQUESTED)

    def test_warnings_when_no_collaborators_supplied(self):
        analyzer = _analyzer()
        result = analyzer.analyze_self_upgrade_request(_request())
        self.assertTrue(result["warnings"])
        self.assertEqual(result["blockers"], [])
        self.assertEqual(result["affected_systems"], [])


# --------------------------------------------------------------------
# Incomplete / invalid request (requirement 5: blocker, never a guess)
# --------------------------------------------------------------------
class IncompleteRequestTests(unittest.TestCase):
    def test_missing_goal_returns_blocker(self):
        analyzer = _analyzer()
        result = analyzer.analyze_self_upgrade_request(_request(goal=""))

        self.assertEqual(len(result["blockers"]), 1)
        self.assertEqual(result["blockers"][0]["type"], BLOCKER_INVALID_REQUEST)
        self.assertIn("goal", result["blockers"][0]["description"])

    def test_missing_requested_capability_returns_blocker(self):
        analyzer = _analyzer()
        result = analyzer.analyze_self_upgrade_request(_request(requested_capability="   "))

        self.assertEqual(result["blockers"][0]["type"], BLOCKER_INVALID_REQUEST)
        self.assertIn("requested_capability", result["blockers"][0]["description"])

    def test_incomplete_request_does_not_guess_required_capabilities(self):
        analyzer = _analyzer()
        result = analyzer.analyze_self_upgrade_request(_request(requested_capability=""))

        self.assertEqual(result["required_capabilities"], [])
        self.assertEqual(result["affected_systems"], [])

    def test_unknown_status_returns_blocker(self):
        analyzer = _analyzer()
        result = analyzer.analyze_self_upgrade_request(_request(status="NOT_A_STATUS"))

        self.assertEqual(result["blockers"][0]["type"], BLOCKER_INVALID_REQUEST)
        self.assertIn("status", result["blockers"][0]["description"])

    def test_non_request_object_returns_blocker(self):
        analyzer = _analyzer()
        result = analyzer.analyze_self_upgrade_request({"goal": "not a real request"})

        self.assertEqual(result["blockers"][0]["type"], BLOCKER_INVALID_REQUEST)
        self.assertIsNone(result["request_id"])
        self.assertEqual(result["required_capabilities"], [])

    def test_none_request_returns_blocker(self):
        analyzer = _analyzer()
        result = analyzer.analyze_self_upgrade_request(None)
        self.assertEqual(result["blockers"][0]["type"], BLOCKER_INVALID_REQUEST)


# --------------------------------------------------------------------
# Detected blockers from existing capability registries
# --------------------------------------------------------------------
class DetectedBlockerTests(unittest.TestCase):
    def test_missing_capability_in_capability_system(self):
        capability_system = FakeCapabilitySystem({})  # nothing registered
        analyzer = _analyzer(capability_system=capability_system)

        result = analyzer.analyze_self_upgrade_request(_request())

        types = [b["type"] for b in result["blockers"]]
        self.assertIn(BLOCKER_MISSING_CAPABILITY, types)

    def test_unavailable_capability_in_capability_system(self):
        capability_system = FakeCapabilitySystem({"code_change_plan": False})
        analyzer = _analyzer(capability_system=capability_system)

        result = analyzer.analyze_self_upgrade_request(_request())

        types = [b["type"] for b in result["blockers"]]
        self.assertIn(BLOCKER_UNAVAILABLE_CAPABILITY, types)

    def test_missing_handler_in_capability_handlers(self):
        handlers = CapabilityHandlerRegistry()  # nothing registered
        analyzer = _analyzer(capability_handlers=handlers)

        result = analyzer.analyze_self_upgrade_request(_request())

        types = [b["type"] for b in result["blockers"]]
        self.assertIn(BLOCKER_MISSING_HANDLER, types)
        self.assertEqual(result["affected_systems"], [])

    def test_multiple_blockers_can_be_reported_together(self):
        capability_system = FakeCapabilitySystem({})
        handlers = CapabilityHandlerRegistry()
        analyzer = _analyzer(capability_system=capability_system, capability_handlers=handlers)

        result = analyzer.analyze_self_upgrade_request(_request())

        types = {b["type"] for b in result["blockers"]}
        self.assertEqual(types, {BLOCKER_MISSING_CAPABILITY, BLOCKER_MISSING_HANDLER})

    def test_never_executes_upgrade_or_touches_upgrade_system(self):
        # No self_upgrade.upgrade_system.UpgradeSystem is imported or
        # constructed anywhere by this analyzer method - the request's
        # status is never advanced past REQUESTED as a side effect.
        analyzer = _analyzer()
        request = _request()
        analyzer.analyze_self_upgrade_request(request)
        self.assertEqual(request.status, STATUS_REQUESTED)


if __name__ == "__main__":
    unittest.main()
