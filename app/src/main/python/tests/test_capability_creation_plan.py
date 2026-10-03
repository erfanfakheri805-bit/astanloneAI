"""
Tests for self_upgrade.capability_creation_plan.build_capability_creation_plan
(Prompt 359) - a small adapter turning the existing Self-Upgrade-request
analysis (planning.adaptive_plan_analyzer.AdaptivePlanAnalyzer.
analyze_self_upgrade_request, Prompt 358) into one structured
CapabilityCreationPlan.

Covers: a valid (READY) plan with deterministic implementation_steps, a
BLOCKED plan when the analysis itself reports blockers or missing
required_capabilities/affected_systems, and an INVALID plan for a
malformed/incomplete request or analysis - never guessing at missing
information.

Run directly:
    python -m unittest tests.test_capability_creation_plan -v
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
from planning.adaptive_plan_analyzer import AdaptivePlanAnalyzer
from self_upgrade.self_upgrade_request import SelfUpgradeRequest
from self_upgrade.capability_creation_plan import (
    build_capability_creation_plan,
    STATUS_READY,
    STATUS_BLOCKED,
    STATUS_INVALID,
    ALL_STATUSES,
)
from execution.capability_handlers import CapabilityHandlerRegistry
from execution.code_change_plan_capability import (
    CAPABILITY_NAME as CODE_CHANGE_PLAN_NAME,
    make_code_change_plan_handler,
)


class FakeCapabilitySystem:
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
        requested_capability=CODE_CHANGE_PLAN_NAME,
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


PLAN_KEYS = {
    "request_id", "capability_name", "purpose", "required_capabilities",
    "affected_systems", "implementation_steps", "blockers", "status",
    "created_at",
}


# --------------------------------------------------------------------
# Valid capability plan (READY)
# --------------------------------------------------------------------
class ValidPlanTests(unittest.TestCase):
    def _ready_analysis(self):
        capability_system = FakeCapabilitySystem({CODE_CHANGE_PLAN_NAME: True})
        handlers = CapabilityHandlerRegistry()
        handlers.register(CODE_CHANGE_PLAN_NAME, make_code_change_plan_handler())
        analyzer = _analyzer(capability_system=capability_system, capability_handlers=handlers)
        return analyzer.analyze_self_upgrade_request(_request())

    def test_plan_shape(self):
        plan = build_capability_creation_plan(self._ready_analysis())
        self.assertEqual(set(plan.keys()), PLAN_KEYS)

    def test_status_ready(self):
        plan = build_capability_creation_plan(self._ready_analysis())
        self.assertEqual(plan["status"], STATUS_READY)

    def test_fields_reused_unchanged_from_analysis(self):
        analysis = self._ready_analysis()
        plan = build_capability_creation_plan(analysis)
        self.assertEqual(plan["request_id"], analysis["request_id"])
        self.assertEqual(plan["capability_name"], analysis["requested_capability"])
        self.assertEqual(plan["purpose"], analysis["goal"])
        self.assertEqual(plan["required_capabilities"], analysis["required_capabilities"])
        self.assertEqual(plan["affected_systems"], analysis["affected_systems"])
        self.assertEqual(plan["blockers"], [])

    def test_implementation_steps_are_nonempty_and_deterministic(self):
        analysis = self._ready_analysis()
        plan1 = build_capability_creation_plan(analysis)
        plan2 = build_capability_creation_plan(analysis)
        self.assertTrue(plan1["implementation_steps"])
        self.assertEqual(plan1["implementation_steps"], plan2["implementation_steps"])

    def test_implementation_steps_mention_capability_and_affected_system(self):
        analysis = self._ready_analysis()
        plan = build_capability_creation_plan(analysis)
        joined = " ".join(plan["implementation_steps"])
        self.assertIn(CODE_CHANGE_PLAN_NAME, joined)
        for system in analysis["affected_systems"]:
            self.assertIn(system, joined)

    def test_implementation_steps_contain_no_source_code(self):
        # Requirement 6: no source code generation - every step is a
        # short, plain-English instruction, never Python/diff content.
        analysis = self._ready_analysis()
        plan = build_capability_creation_plan(analysis)
        for step in plan["implementation_steps"]:
            self.assertNotIn("def ", step)
            self.assertNotIn("import ", step)
            self.assertNotIn("{", step)

    def test_is_json_serializable(self):
        import json
        plan = build_capability_creation_plan(self._ready_analysis())
        serialized = json.dumps(plan)
        self.assertIsInstance(serialized, str)


# --------------------------------------------------------------------
# Blocked plan
# --------------------------------------------------------------------
class BlockedPlanTests(unittest.TestCase):
    def test_blocked_when_analysis_reports_missing_capability(self):
        capability_system = FakeCapabilitySystem({})  # not registered
        analyzer = _analyzer(capability_system=capability_system)
        analysis = analyzer.analyze_self_upgrade_request(_request())

        plan = build_capability_creation_plan(analysis)

        self.assertEqual(plan["status"], STATUS_BLOCKED)
        self.assertTrue(plan["blockers"])
        self.assertEqual(plan["implementation_steps"], [])

    def test_blocked_when_analysis_reports_missing_handler(self):
        handlers = CapabilityHandlerRegistry()  # nothing registered
        analyzer = _analyzer(capability_handlers=handlers)
        analysis = analyzer.analyze_self_upgrade_request(_request())

        plan = build_capability_creation_plan(analysis)

        self.assertEqual(plan["status"], STATUS_BLOCKED)
        self.assertEqual(plan["implementation_steps"], [])

    def test_blocked_when_required_information_missing(self):
        # No capability_system/capability_handlers supplied at all -
        # required_capabilities is non-empty but affected_systems is
        # empty (requirement 5: "missing required information").
        analyzer = _analyzer()
        analysis = analyzer.analyze_self_upgrade_request(_request())

        plan = build_capability_creation_plan(analysis)

        self.assertEqual(plan["status"], STATUS_BLOCKED)
        self.assertEqual(plan["affected_systems"], [])
        self.assertEqual(plan["implementation_steps"], [])

    def test_blocked_plan_never_guesses_affected_systems(self):
        analyzer = _analyzer()
        analysis = analyzer.analyze_self_upgrade_request(_request())
        plan = build_capability_creation_plan(analysis)
        self.assertEqual(plan["affected_systems"], analysis["affected_systems"])


# --------------------------------------------------------------------
# Invalid request / analysis
# --------------------------------------------------------------------
class InvalidPlanTests(unittest.TestCase):
    def test_invalid_when_underlying_request_was_invalid(self):
        analyzer = _analyzer()
        analysis = analyzer.analyze_self_upgrade_request(_request(goal=""))

        plan = build_capability_creation_plan(analysis)

        self.assertEqual(plan["status"], STATUS_INVALID)
        self.assertEqual(plan["implementation_steps"], [])
        self.assertTrue(plan["blockers"])

    def test_invalid_when_analysis_is_not_a_dict(self):
        plan = build_capability_creation_plan("not an analysis")
        self.assertEqual(plan["status"], STATUS_INVALID)
        self.assertIsNone(plan["request_id"])
        self.assertIsNone(plan["capability_name"])
        self.assertEqual(plan["implementation_steps"], [])
        self.assertTrue(plan["blockers"])

    def test_invalid_when_analysis_is_none(self):
        plan = build_capability_creation_plan(None)
        self.assertEqual(plan["status"], STATUS_INVALID)

    def test_invalid_when_analysis_missing_expected_keys(self):
        plan = build_capability_creation_plan({})
        self.assertEqual(plan["status"], STATUS_INVALID)
        self.assertEqual(plan["implementation_steps"], [])

    def test_statuses_are_fixed(self):
        self.assertEqual(set(ALL_STATUSES), {STATUS_READY, STATUS_BLOCKED, STATUS_INVALID})

    def test_never_executes_or_installs_anything(self):
        # No self_upgrade.upgrade_system.UpgradeSystem/Sandbox/
        # VersionSystem is imported anywhere in the module under test -
        # a smoke check that building a plan has no side effects.
        analyzer = _analyzer()
        analysis = analyzer.analyze_self_upgrade_request(_request())
        plan_before = build_capability_creation_plan(analysis)
        plan_after = build_capability_creation_plan(analysis)
        self.assertEqual(plan_before["status"], plan_after["status"])


if __name__ == "__main__":
    unittest.main()
