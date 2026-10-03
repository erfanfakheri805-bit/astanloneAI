"""Prompt 719-D - per-AgentLoop in-memory plan route pin inside `AgentLoop.execute_routed_step`.

Focused on the pin only: Section 6 pins, repeated Section 6 allowed, cross-route switches rejected, rejections create no pin, Section 6
failures never fall back to legacy, legacy callers unchanged, independent pins per plan and per AgentLoop instance, nothing persistent.
"""
import hashlib
import os
import unittest
from unittest import mock

from agent.agent_loop import AgentLoop
from execution.plan_execution_controller import PlanExecutionController
from tests import section6_agent_loop_baseline_prompt719c as baseline
from tests.test_section6_agent_loop_routed_step_prompt719c import (ENVELOPE_KEYS, FROZEN_AGENT_LOOP_SHA256, LEGACY, PRISTINE_SHA256,
                                                                   PROJECT_DB, World, legacy_view)

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT)))), "docs",
                   "section6_agent_loop_route_pin_prompt719d.md")
S6, LEG = "section6_tool", "legacy_capability"


def pins(loop):
    return dict(loop.__dict__.get("_plan_route_pins", {}))


def add_plan(w, steps=2):
    goal = w.goals.create_goal("g2")
    plan = w.plans.create_plan(goal.goal_id, metadata={"phase": "planning", "executed": False, "execution_authorized": True})
    ids = [w.plans.add_step(plan.plan_id, "s%d" % n).step_id for n in range(steps)]
    return plan, ids


def intent_for(plan, step_id):
    return {"plan_id": plan.plan_id, "step_id": step_id, "max_attempts": 2,
            "tool_request": {"name": "echo", "tool_input": {"a": 1}, "granted_permissions": [], "granted_capabilities": [], "confirmed": False}}


class TestSection6Pin(unittest.TestCase):
    def test_1_first_section6_execution_pins_the_plan(self):
        w = World()
        self.assertEqual(pins(w.loop), {})
        out = w.route6()
        self.assertEqual(out["status"], "completed")
        self.assertEqual(pins(w.loop), {w.plan.plan_id: S6})

    def test_2_repeated_section6_execution_remains_allowed(self):
        w = World()
        w.route6()
        out = w.route6(w.intent(step_id=w.step_ids[1]))
        self.assertEqual((out["stage"], out["status"]), ("execution", "completed"))
        again = w.route6(w.intent(step_id=w.step_ids[1]))                 # rerun of a finished step: runner answers, the pin does not interfere
        self.assertEqual(again["stage"], "execution")
        self.assertNotEqual(again["error_code"], "ROUTE_PIN_CONFLICT")
        self.assertEqual(pins(w.loop), {w.plan.plan_id: S6})

    def test_3_section6_then_legacy_is_rejected_and_nothing_runs(self):
        for label, decl in (("explicit", LEG), ("absent", None), ("unknown", "nope"), ("malformed", 5)):
            with self.subTest(label=label):
                w = World()
                w.route6()
                before = w.snapshot()
                with mock.patch(LEGACY, autospec=True) as legacy:
                    out = w.loop.execute_routed_step(decl, legacy_input=w.legacy_input())
                legacy.assert_not_called()
                self.assertEqual(set(out), ENVELOPE_KEYS)
                self.assertEqual((out["stage"], out["status"], out["error_code"]), ("route_pin", "rejected", "ROUTE_PIN_CONFLICT"))
                self.assertIsNone(out["legacy_result"])
                self.assertIsNone(out["tool_result"])
                self.assertEqual(w.snapshot(), before)
                self.assertEqual(pins(w.loop), {w.plan.plan_id: S6})

    def test_4_explicit_section6_rejections_create_no_pin(self):
        modes = {
            "dispatch_absent_payload": lambda w: w.loop.execute_routed_step(S6, legacy_input=w.legacy_input(), tool_registry=w.registry),
            "invalid_payload": lambda w: w.route6({"x": (1,)}),
            "intent_rejected": lambda w: w.route6(w.intent(max_attempts=0)),
            "unknown_plan": lambda w: w.route6(w.intent(plan_id="other")),
        }
        for label, call in modes.items():
            with self.subTest(label=label):
                w = World()
                out = call(w)
                self.assertIn(out["status"], ("rejected", "failed"))
                self.assertEqual(pins(w.loop), {})
                self.assertEqual(w.loop.execute_routed_step(LEG, legacy_input=w.legacy_input())["stage"], "execution")   # legacy still free

    def test_5_section6_failure_does_not_fall_back_to_legacy_and_keeps_the_pin(self):
        modes = {"run_not_ok": lambda w: w.route6(w.intent(step_id="nope")), "no_registry": lambda w: w.route6(tool_registry=None)}
        for label, call in modes.items():
            with self.subTest(label=label):
                w = World()
                with mock.patch(LEGACY, autospec=True) as legacy:
                    out = call(w)
                    legacy.assert_not_called()
                    self.assertEqual((out["route"], out["status"]), (S6, "failed"))
                    self.assertIsNone(out["legacy_result"])
                    self.assertEqual(pins(w.loop), {w.plan.plan_id: S6})
                    after = w.loop.execute_routed_step(LEG, legacy_input=w.legacy_input())
                    legacy.assert_not_called()
                    self.assertEqual(after["error_code"], "ROUTE_PIN_CONFLICT")

    def test_6_runner_exception_keeps_the_pin_and_never_reaches_legacy(self):
        w = World()
        with mock.patch("agent.agent_loop.run_tool_step_intent", side_effect=RuntimeError("boom")), mock.patch(LEGACY, autospec=True) as legacy:
            with self.assertRaises(RuntimeError):
                w.route6()
            legacy.assert_not_called()
        self.assertEqual(pins(w.loop), {w.plan.plan_id: S6})


class TestLegacyCompatibility(unittest.TestCase):
    def test_7_explicit_legacy_result_is_unchanged_and_pins_a_known_plan(self):
        w, ref = World(), World()
        out = w.loop.execute_routed_step(LEG, legacy_input=w.legacy_input())
        direct = ref.loop.execute_next_step(ref.plan.plan_id)
        self.assertEqual(legacy_view(out["legacy_result"]), legacy_view(direct))
        self.assertEqual((out["route"], out["stage"], out["error_code"]), (LEG, "execution", None))
        self.assertEqual(pins(w.loop), {w.plan.plan_id: LEG})
        self.assertEqual(pins(ref.loop), {})                                # the direct API never touches the pin

    def test_8_repeated_legacy_execution_remains_allowed(self):
        w = World()
        for _ in range(3):
            out = w.loop.execute_routed_step(LEG, legacy_input=w.legacy_input())
            self.assertEqual(out["stage"], "execution")
        self.assertEqual(pins(w.loop), {w.plan.plan_id: LEG})

    def test_9_undeclared_legacy_calls_never_create_a_pin(self):
        for decl in (None, "nope", 7):
            with self.subTest(decl=decl):
                w = World()
                out = w.loop.execute_routed_step(decl, legacy_input=w.legacy_input())
                self.assertEqual((out["route"], out["fallback"], out["stage"]), (LEG, True, "execution"))
                self.assertEqual(pins(w.loop), {})
                after = w.route6(w.intent(step_id=w.step_ids[1]))             # no pin, so nothing is rejected by the pin
                self.assertEqual(after["stage"], "execution")
                self.assertNotEqual(after["error_code"], "ROUTE_PIN_CONFLICT")
                self.assertEqual(pins(w.loop), {w.plan.plan_id: S6})

    def test_10_legacy_then_section6_is_rejected_and_the_runner_is_not_called(self):
        w = World()
        w.loop.execute_routed_step(LEG, legacy_input=w.legacy_input())
        with mock.patch("agent.agent_loop.run_tool_step_intent") as runner:
            out = w.route6()
        runner.assert_not_called()
        self.assertEqual((out["route"], out["stage"], out["status"], out["error_code"]), (S6, "route_pin", "rejected", "ROUTE_PIN_CONFLICT"))
        self.assertEqual(pins(w.loop), {w.plan.plan_id: LEG})

    def test_11_legacy_input_rejections_and_unknown_plans_create_no_pin(self):
        w = World()
        self.assertEqual(w.loop.execute_routed_step(LEG, legacy_input={"plan_id": " "})["error_code"], "LEGACY_INPUT_INVALID")
        self.assertEqual(w.loop.execute_routed_step(LEG, legacy_input={"plan_id": "missing"})["stage"], "execution")
        self.assertEqual(pins(w.loop), {})

    def test_12_direct_execute_next_step_and_run_ignore_the_pin(self):
        w = World()
        w.route6()
        self.assertIn("executed", w.loop.execute_next_step(w.plan.plan_id))
        self.assertIn("status", w.loop.run(w.plan.goal_id, w.plan.plan_id))
        self.assertEqual(pins(w.loop), {w.plan.plan_id: S6})


class TestIsolation(unittest.TestCase):
    def test_13_different_plan_ids_keep_independent_pins(self):
        w = World()
        plan2, ids2 = add_plan(w)
        w.route6()
        self.assertEqual(w.loop.execute_routed_step(LEG, legacy_input={"plan_id": plan2.plan_id})["stage"], "execution")
        self.assertEqual(pins(w.loop), {w.plan.plan_id: S6, plan2.plan_id: LEG})
        self.assertEqual(w.route6(w.intent(step_id=w.step_ids[1]))["status"], "completed")
        self.assertEqual(w.loop.execute_routed_step(LEG, legacy_input=w.legacy_input())["error_code"], "ROUTE_PIN_CONFLICT")
        self.assertEqual(w.route6(intent_for(plan2, ids2[0]))["error_code"], "ROUTE_PIN_CONFLICT")
        plan3, ids3 = add_plan(w)
        self.assertEqual(w.route6(intent_for(plan3, ids3[0]))["status"], "completed")
        self.assertEqual(pins(w.loop), {w.plan.plan_id: S6, plan2.plan_id: LEG, plan3.plan_id: S6})

    def test_14_pins_are_isolated_between_agent_loop_instances(self):
        w = World()
        other = AgentLoop(w.goals, w.plans, PlanExecutionController(w.plans))        # same PlanManager, separate loop
        w.route6()
        self.assertEqual(pins(other), {})
        self.assertEqual(other.execute_routed_step(LEG, legacy_input=w.legacy_input())["stage"], "execution")
        self.assertEqual(pins(other), {w.plan.plan_id: LEG})
        self.assertEqual(pins(w.loop), {w.plan.plan_id: S6})
        self.assertIsNot(w.loop.__dict__["_plan_route_pins"], other.__dict__["_plan_route_pins"])
        self.assertFalse(hasattr(AgentLoop, "_plan_route_pins"))                      # nothing on the class or module level
        import agent.agent_loop as module
        self.assertFalse([n for n in vars(module) if "pin" in n.lower()])

    def test_15_a_new_loop_starts_with_no_pins(self):
        w = World()
        w.route6()
        fresh = AgentLoop(w.goals, w.plans, PlanExecutionController(w.plans))
        self.assertEqual(fresh.execute_routed_step(LEG, legacy_input=w.legacy_input())["stage"], "execution")

    def test_16_the_pin_changes_no_plan_state_and_is_not_persisted(self):
        w = World()
        before = w.snapshot()
        with mock.patch.object(w.loop._plan_manager, "get_plan", wraps=w.plans.get_plan):
            w.loop.execute_routed_step(LEG, legacy_input={"plan_id": "missing"})
        self.assertEqual(w.snapshot(), before)
        w.route6()
        plan = w.plans.get_plan(w.plan.plan_id)
        self.assertNotIn("route", repr(plan.metadata).lower())
        self.assertFalse([k for k in plan.metadata if "pin" in k or "route" in k])
        for step in plan.steps:
            self.assertNotIn("pin", repr(step.to_dict()).lower())
        for obj in (w.plans, w.goals):
            self.assertNotIn("_plan_route_pins", obj.__dict__)
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)

    def test_17_each_call_returns_a_fresh_envelope_with_an_unchanged_shape(self):
        w = World()
        a, b = w.route6(), w.route6(w.intent(step_id=w.step_ids[1]))
        self.assertIsNot(a, b)
        for out in (a, b):
            self.assertEqual(set(out), ENVELOPE_KEYS)                            # no pin field is added to the envelope


class TestBoundaries(unittest.TestCase):
    def test_18_only_execute_routed_step_changed_relative_to_the_pre_719c_agent_loop(self):
        self.assertEqual(hashlib.sha256(baseline.baseline_bytes()).hexdigest(), FROZEN_AGENT_LOOP_SHA256)
        import inspect
        for name in ("__init__", "run", "execute_next_step", "_finish", "_identify_next_step"):
            source = inspect.getsource(getattr(AgentLoop, name))
            for token in ("_plan_route_pins", "ROUTE_PIN", "pins"):
                self.assertNotIn(token, source, (name, token))

    def test_19_process_input_core_plan_and_plan_manager_are_untouched(self):
        from tests.test_section6_agent_loop_adapter_prompt714 import FROZEN_PLAN_MANAGER_SHA256
        from tests.test_section6_agent_loop_routing_decision_prompt715 import FROZEN_ADAPTER_SHA256, FROZEN_CORE_SHA256

        def sha(rel):
            with open(os.path.join(PY_ROOT, rel), "rb") as fh:
                return hashlib.sha256(fh.read()).hexdigest()
        self.assertEqual(sha("core/core.py"), FROZEN_CORE_SHA256)
        self.assertEqual(sha("planning/plan_manager.py"), FROZEN_PLAN_MANAGER_SHA256)
        self.assertEqual(sha("planning/tool_step_agent_adapter.py"), FROZEN_ADAPTER_SHA256)
        with open(os.path.join(PY_ROOT, "core", "core.py"), encoding="utf-8") as fh:
            text = fh.read()
        for token in ("_plan_route_pins", "ROUTE_PIN_CONFLICT", "execute_routed_step"):
            self.assertNotIn(token, text)

    def test_20_pristine_database_no_pycache_and_the_documentation_note(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("_plan_route_pins", "section6_tool", "legacy_capability", "ROUTE_PIN_CONFLICT", "non-persistent", "process_input",
                       "execute_next_step", "residual"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
