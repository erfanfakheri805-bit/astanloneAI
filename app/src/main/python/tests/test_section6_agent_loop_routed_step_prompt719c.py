"""Prompt 719-C - AgentLoop wiring to the Section 6 tool-step runner (`AgentLoop.execute_routed_step`).

Focused on this one seam only: legacy route unchanged, explicit Section 6 route reaches the 719-B runner exactly once, invalid routing /
intent rejection never executes, runner results are propagated, and an explicit Section 6 route never falls back to legacy. Most tests use
the real stack (real PlanManager, real registry, real retry layer); call-shape tests wrap the real collaborators with `mock.patch(wraps=...)`.
"""
import ast
import copy
import glob
import hashlib
import inspect
import os
import unittest
from unittest import mock

from agent.agent_loop import AgentLoop
from agent.tool_step_intent import build_tool_step_intent
from agent.tool_step_runner import OUTCOME_RUNNER_REJECTION, RUNNER_PLAN_ID_MISMATCH, run_tool_step_intent
from execution.plan_execution_controller import PlanExecutionController
from planning.goal_manager import GoalManager
from planning.plan_manager import PlanManager
from planning.tool_step_dispatch import resolve_tool_step_dispatch
from tests import section6_agent_loop_baseline_prompt719c as baseline
from tests.test_section6_agent_loop_routing_decision_prompt715 import FROZEN_ADAPTER_SHA256, FROZEN_CORE_SHA256
from tests.test_section6_agent_loop_adapter_prompt714 import FROZEN_PLAN_MANAGER_SHA256
from tests.test_section6_tool_step_executor_prompt708 import make_registry

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT)))), "docs",
                   "section6_agent_loop_routed_step_prompt719c.md")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
FROZEN_AGENT_LOOP_SHA256 = "b69e217564345cad5ae30b76fe6af97c0d6d263098ad4344954d5946b7631157"      # pre-719-C bytes of agent/agent_loop.py

RUNNER = "agent.agent_loop.run_tool_step_intent"
INTENT = "agent.agent_loop.build_tool_step_intent"
DISPATCH = "agent.agent_loop.resolve_tool_step_dispatch"
LEGACY = "agent.agent_loop.AgentLoop.execute_next_step"
ENVELOPE_KEYS = {"route", "explicit", "fallback", "route_code", "dispatch_status", "dispatch_code", "stage", "status",
                 "error_code", "failures", "legacy_result", "tool_result"}


class World:
    """One test-owned AgentLoop over a real PlanManager holding one authorized Section 6 plan with pending steps."""

    def __init__(self, authorized=True, steps=2):
        self.goals = GoalManager()
        goal = self.goals.create_goal("g")
        self.plans = PlanManager(self.goals)
        self.plan = self.plans.create_plan(goal.goal_id, metadata={"phase": "planning", "executed": False,
                                                                   "execution_authorized": authorized})
        self.step_ids = [self.plans.add_step(self.plan.plan_id, "step %d" % n).step_id for n in range(steps)]
        self.loop = AgentLoop(self.goals, self.plans, PlanExecutionController(self.plans))
        self.registry, self.handlers = make_registry()

    def intent(self, **over):
        data = {"plan_id": self.plan.plan_id, "step_id": self.step_ids[0], "max_attempts": 2,
                "tool_request": {"name": "echo", "tool_input": {"a": 1}, "granted_permissions": [],
                                 "granted_capabilities": [], "confirmed": False}}
        data.update(over)
        return data

    def legacy_input(self):
        return {"plan_id": self.plan.plan_id}

    def route6(self, tool_input=None, **kw):
        kw.setdefault("tool_registry", self.registry)
        return self.loop.execute_routed_step("section6_tool", tool_input=self.intent() if tool_input is None else tool_input, **kw)

    def snapshot(self):
        plan = self.plans.get_plan(self.plan.plan_id)
        return repr(([s.to_dict() for s in plan.steps], plan.metadata))


def legacy_view(result):
    """Stable part of an `execute_next_step` result (drops the per-run context / execution ids)."""
    out = dict(result)
    execution = out.get("execution_result")
    if execution:
        out["execution_result"] = {k: v for k, v in execution.items() if k not in ("context", "execution_id")}
    return out


class TestLegacyRouteUnchanged(unittest.TestCase):
    def test_1_explicit_legacy_route_calls_execute_next_step_once_and_returns_its_result(self):
        w = World()
        sentinel = {"executed": False, "step_id": None, "success": None, "execution_result": None, "reason": "r", "warnings": []}
        capability_system = object()
        with mock.patch(LEGACY, autospec=True, return_value=sentinel) as legacy, mock.patch(RUNNER) as runner, mock.patch(INTENT) as intent:
            out = w.loop.execute_routed_step("legacy_capability", legacy_input=w.legacy_input(), capability_system=capability_system)
        legacy.assert_called_once_with(w.loop, w.plan.plan_id, capability_system)
        runner.assert_not_called()
        intent.assert_not_called()
        self.assertEqual(set(out), ENVELOPE_KEYS)
        self.assertEqual((out["route"], out["explicit"], out["fallback"], out["stage"], out["error_code"], out["tool_result"]),
                         ("legacy_capability", True, False, "execution", None, None))
        self.assertEqual(out["legacy_result"], sentinel)

    def test_2_real_legacy_result_equals_a_direct_execute_next_step_call(self):
        a, b = World(), World()
        routed = a.loop.execute_routed_step("legacy_capability", legacy_input=a.legacy_input())
        direct = b.loop.execute_next_step(b.plan.plan_id)
        self.assertEqual(legacy_view(routed["legacy_result"]), legacy_view(direct))
        self.assertEqual(a.snapshot(), b.snapshot())
        self.assertEqual(routed["status"], "executed" if direct["executed"] else "not_executed")

    def test_3_absent_unknown_and_malformed_declarations_fall_back_to_legacy_and_never_to_section6(self):
        class StrSub(str):
            pass
        for declaration in (None, "", "Section6_Tool", "section6_tool ", "tool", 7, b"section6_tool", ["section6_tool"], StrSub("section6_tool")):
            with self.subTest(declaration=declaration):
                w = World()
                with mock.patch(LEGACY, autospec=True, return_value={"executed": False}) as legacy, mock.patch(RUNNER) as runner, \
                        mock.patch(INTENT) as intent:
                    out = w.loop.execute_routed_step(declaration, legacy_input=w.legacy_input(), tool_input=w.intent(), tool_registry=w.registry)
                legacy.assert_called_once()
                runner.assert_not_called()
                intent.assert_not_called()
                self.assertEqual((out["route"], out["explicit"], out["fallback"]), ("legacy_capability", False, True))
                self.assertEqual(w.handlers["echo"].count, 0)

    def test_4_legacy_route_ignores_an_invalid_tool_input(self):
        w = World()
        with mock.patch(LEGACY, autospec=True, return_value={"executed": False}) as legacy, mock.patch(RUNNER) as runner:
            out = w.loop.execute_routed_step("legacy_capability", legacy_input=w.legacy_input(), tool_input={"bad": (1, 2), "x": object()})
        legacy.assert_called_once()
        runner.assert_not_called()
        self.assertEqual((out["route"], out["dispatch_status"]), ("legacy_capability", "ready"))

    def test_5_invalid_legacy_payloads_never_execute(self):
        bad = ({}, {"plan_id": ""}, {"plan_id": "   "}, {"plan_id": 5}, {"plan_id": "p", "extra": 1}, {"other": "p"}, [], "plan-1")
        for payload in bad:
            with self.subTest(payload=payload):
                w = World()
                with mock.patch(LEGACY, autospec=True) as legacy, mock.patch(RUNNER) as runner:
                    out = w.loop.execute_routed_step("legacy_capability", legacy_input=payload, tool_input=w.intent(), tool_registry=w.registry)
                legacy.assert_not_called()
                runner.assert_not_called()
                self.assertEqual((out["route"], out["status"], out["legacy_result"], out["tool_result"]), ("legacy_capability", "rejected", None, None))
                self.assertIn(out["error_code"], ("LEGACY_INPUT_INVALID",))

    def test_6_absent_legacy_payload_is_rejected_by_dispatch_on_the_legacy_route(self):
        w = World()
        with mock.patch(LEGACY, autospec=True) as legacy, mock.patch(RUNNER) as runner:
            out = w.loop.execute_routed_step(None, tool_input=w.intent(), tool_registry=w.registry)
        legacy.assert_not_called()
        runner.assert_not_called()
        self.assertEqual((out["route"], out["stage"], out["status"], out["error_code"], out["dispatch_status"]),
                         ("legacy_capability", "dispatch", "rejected", "REJECTED_PAYLOAD_ABSENT", "rejected"))
        self.assertEqual(w.handlers["echo"].count, 0)


class TestSection6RouteReachesRunner(unittest.TestCase):
    def test_7_explicit_route_calls_the_runner_exactly_once_with_the_loops_plan_and_the_callers_registry(self):
        w = World()
        with mock.patch(RUNNER, wraps=run_tool_step_intent) as runner, mock.patch(LEGACY, autospec=True) as legacy:
            out = w.route6()
        runner.assert_called_once()
        legacy.assert_not_called()
        intent_result, plan, registry = runner.call_args.args
        self.assertTrue(intent_result.ok)
        self.assertIs(plan, w.plans.get_plan(w.plan.plan_id))
        self.assertIs(registry, w.registry)
        self.assertEqual(len(runner.call_args.args), 3)
        self.assertEqual(runner.call_args.kwargs, {})
        self.assertEqual((out["route"], out["explicit"], out["fallback"], out["stage"], out["status"], out["error_code"]),
                         ("section6_tool", True, False, "execution", "completed", None))

    def test_8_end_to_end_the_tool_runs_once_and_the_step_completes(self):
        w = World()
        out = w.route6()
        self.assertEqual(set(out), ENVELOPE_KEYS)
        self.assertEqual(w.handlers["echo"].count, 1)
        self.assertEqual(w.plans.get_plan(w.plan.plan_id).steps[0].status, "completed")
        self.assertEqual(w.plans.get_plan(w.plan.plan_id).steps[1].status, "pending")      # only the named step; no "next ready step" selection
        self.assertIsNone(out["legacy_result"])
        tool = out["tool_result"]
        self.assertEqual((tool["ok"], tool["plan_id"], tool["step_id"], tool["outcome_kind"], tool["final_step_state"]),
                         (True, w.plan.plan_id, w.step_ids[0], "completed", "completed"))

    def test_9_the_result_is_the_runners_result_unchanged(self):
        a, b = World(), World()
        out = a.route6()
        direct = run_tool_step_intent(build_tool_step_intent(b.intent()), b.plans.get_plan(b.plan.plan_id), b.registry)
        self.assertEqual(out["tool_result"], direct.to_dict())
        self.assertEqual(out["failures"], direct.failures)

    def test_10_optional_capability_fields_travel_to_the_runner_untouched(self):
        w = World()
        extras = {"required_capabilities": ["Needs A"], "capability_mapping": [{"capability": "Needs A", "grants": ["cap_a"]}]}
        tool_request = {"name": "needs_cap", "tool_input": {}, "granted_permissions": [], "granted_capabilities": ["cap_a"], "confirmed": False}
        with mock.patch(RUNNER, wraps=run_tool_step_intent) as runner:
            out = w.route6(w.intent(tool_request=tool_request, **extras))
        runner.assert_called_once()
        self.assertEqual(runner.call_args.args[0].required_capabilities, extras["required_capabilities"])
        self.assertEqual(runner.call_args.args[0].capability_mapping, extras["capability_mapping"])
        self.assertEqual((out["status"], w.handlers["needs_cap"].count), ("completed", 1))

    def test_11_callers_payload_is_never_mutated_and_later_edits_cannot_reach_the_result(self):
        w = World()
        payload = w.intent()
        before = copy.deepcopy(payload)
        out = w.route6(payload)
        self.assertEqual(payload, before)
        out["tool_result"]["step_id"] = "changed"
        payload["step_id"] = "changed"
        self.assertEqual(w.route6(w.intent(step_id=w.step_ids[1]))["tool_result"]["step_id"], w.step_ids[1])

    def test_12_each_call_returns_a_fresh_envelope(self):
        w = World()
        first = w.route6()
        second = w.route6(w.intent(step_id=w.step_ids[1]))
        self.assertIsNot(first, second)
        self.assertIsNot(first["tool_result"], second["tool_result"])
        first["failures"].append("x")
        self.assertEqual(second["failures"], [])


class TestInvalidRoutingOrIntentNeverExecutes(unittest.TestCase):
    def assert_nothing_ran(self, w, before, runner, legacy):
        runner.assert_not_called()
        legacy.assert_not_called()
        self.assertEqual(w.handlers["echo"].count, 0)
        self.assertEqual(w.snapshot(), before)

    def test_13_missing_or_non_json_safe_tool_input_is_rejected_by_dispatch_on_the_section6_route(self):
        cases = ((None, "REJECTED_PAYLOAD_ABSENT"), ({"step_id": (1, 2)}, "REJECTED_PAYLOAD_INVALID"), ({"a": object()}, "REJECTED_PAYLOAD_INVALID"),
                 ({1: "x"}, "REJECTED_PAYLOAD_INVALID"), (float("nan"), "REJECTED_PAYLOAD_INVALID"))
        for payload, code in cases:
            with self.subTest(code=code, payload=repr(payload)[:30]):
                w = World()
                with mock.patch(RUNNER) as runner, mock.patch(LEGACY, autospec=True) as legacy:
                    out = w.loop.execute_routed_step("section6_tool", legacy_input=w.legacy_input(), tool_input=payload, tool_registry=w.registry)
                self.assertEqual((out["route"], out["stage"], out["status"], out["error_code"], out["dispatch_status"]),
                                 ("section6_tool", "dispatch", "rejected", code, "rejected"))
                self.assertEqual((out["legacy_result"], out["tool_result"]), (None, None))
                self.assertEqual(w.handlers["echo"].count, 0)
                runner.assert_not_called()
                legacy.assert_not_called()

    def test_14_intent_rejections_do_not_execute_and_carry_the_intent_failures(self):
        w0 = World()
        bad_intents = {
            "missing_key": {k: v for k, v in w0.intent().items() if k != "max_attempts"},
            "extra_key": w0.intent(surprise=1),
            "alternate_name": {**{k: v for k, v in w0.intent().items() if k != "tool_request"}, "request": w0.intent()["tool_request"]},
            "bad_max_attempts": w0.intent(max_attempts=0),
            "bool_max_attempts": w0.intent(max_attempts=True),
            "blank_plan_id": w0.intent(plan_id="  "),
            "not_a_dict_request": w0.intent(tool_request=["echo"]),
            "request_defaults_omitted": w0.intent(tool_request={"name": "echo", "tool_input": {}}),
            "bad_tool_name": w0.intent(tool_request={"name": "Not A Name", "tool_input": {}, "granted_permissions": [],
                                                      "granted_capabilities": [], "confirmed": False}),
            "string_permissions": w0.intent(tool_request={"name": "echo", "tool_input": {"a": 1}, "granted_permissions": "network",
                                                        "granted_capabilities": [], "confirmed": False}),
        }
        for label, payload in bad_intents.items():
            with self.subTest(label=label):
                w = World()
                before = w.snapshot()
                with mock.patch(RUNNER) as runner, mock.patch(LEGACY, autospec=True) as legacy:
                    out = w.route6(payload)
                self.assert_nothing_ran(w, before, runner, legacy)
                self.assertEqual((out["route"], out["stage"], out["status"], out["error_code"], out["dispatch_status"]),
                                 ("section6_tool", "payload", "rejected", "SECTION6_INTENT_REJECTED", "ready"))
                self.assertTrue(out["failures"])
                self.assertEqual(out["failures"], build_tool_step_intent(payload).failures)
                self.assertEqual((out["legacy_result"], out["tool_result"]), (None, None))

    def test_15_the_intent_adapter_is_called_once_and_its_rejection_skips_the_runner(self):
        w = World()
        with mock.patch(INTENT, wraps=build_tool_step_intent) as intent, mock.patch(RUNNER) as runner:
            w.route6(w.intent(max_attempts=0))
        intent.assert_called_once()
        runner.assert_not_called()

    def test_16_dispatch_is_resolved_exactly_once_per_call(self):
        for declaration, kwargs in (("section6_tool", {"tool_input": None}), ("legacy_capability", {"legacy_input": None}), (None, {})):
            with self.subTest(declaration=declaration):
                w = World()
                with mock.patch(DISPATCH, wraps=resolve_tool_step_dispatch) as dispatch:
                    w.loop.execute_routed_step(declaration, **kwargs)
                dispatch.assert_called_once()


class TestRunnerResultsArePropagated(unittest.TestCase):
    def test_17_a_runner_rejection_is_propagated_and_nothing_executes(self):
        w = World()
        payload = w.intent(plan_id="no-such-plan")
        before = w.snapshot()
        with mock.patch(RUNNER, wraps=run_tool_step_intent) as runner, mock.patch(LEGACY, autospec=True) as legacy:
            out = w.route6(payload)
        runner.assert_called_once()
        legacy.assert_not_called()
        self.assertEqual(runner.call_args.args[1], None)                                  # PlanManager.get_plan() miss is passed on unchanged
        self.assertEqual((out["stage"], out["status"], out["error_code"]), ("execution", "failed", "SECTION6_RUN_NOT_OK"))
        self.assertEqual(out["tool_result"]["outcome_kind"], OUTCOME_RUNNER_REJECTION)
        self.assertEqual([f["code"] for f in out["failures"]], [RUNNER_PLAN_ID_MISMATCH])
        self.assertEqual(out["failures"], out["tool_result"]["failures"])
        self.assertEqual((w.handlers["echo"].count, w.snapshot()), (0, before))

    def test_18_a_non_ok_runner_result_from_the_existing_stack_is_propagated(self):
        cases = {
            "not_authorized": (dict(authorized=False), {}, {}),
            "unknown_step": (dict(), dict(step_id="nope"), {}),
            "missing_registry": (dict(), {}, dict(tool_registry=None)),
            "unknown_tool": (dict(), dict(tool_request={"name": "no_such_tool", "tool_input": {}, "granted_permissions": [],
                                                        "granted_capabilities": [], "confirmed": False}), {}),
        }
        for label, (world_kw, intent_kw, route_kw) in cases.items():
            with self.subTest(label=label):
                w = World(**world_kw)
                with mock.patch(RUNNER, wraps=run_tool_step_intent) as runner, mock.patch(LEGACY, autospec=True) as legacy:
                    out = w.route6(w.intent(**intent_kw), **route_kw)
                runner.assert_called_once()
                legacy.assert_not_called()
                self.assertEqual((out["route"], out["stage"], out["status"], out["error_code"]), ("section6_tool", "execution", "failed", "SECTION6_RUN_NOT_OK"))
                self.assertFalse(out["tool_result"]["ok"])
                self.assertTrue(out["failures"])
                self.assertEqual(w.handlers["echo"].count, 0)
                self.assertIsNone(out["legacy_result"])

    def test_19_a_tool_execution_failure_is_reported_once_with_no_extra_attempts(self):
        w = World()
        tool_request = {"name": "boom", "tool_input": {}, "granted_permissions": [], "granted_capabilities": [], "confirmed": False}
        with mock.patch(RUNNER, wraps=run_tool_step_intent) as runner, mock.patch(LEGACY, autospec=True) as legacy:
            out = w.route6(w.intent(tool_request=tool_request, max_attempts=5))
        runner.assert_called_once()
        legacy.assert_not_called()
        self.assertEqual((out["status"], w.handlers["boom"].count), ("failed", 1))         # tool execution failure is terminal; no loop-level retry
        self.assertEqual(w.plans.get_plan(w.plan.plan_id).steps[0].status, "failed")
        self.assertEqual(len(out["tool_result"]["attempts"]), 1)


class TestNoFallbackFromSection6ToLegacy(unittest.TestCase):
    def test_20_no_section6_failure_mode_ever_reaches_the_legacy_path(self):
        modes = {
            "absent_payload": lambda w: w.loop.execute_routed_step("section6_tool", legacy_input=w.legacy_input(), tool_registry=w.registry),
            "invalid_payload": lambda w: w.route6({"x": (1,)}),
            "intent_rejected": lambda w: w.route6(w.intent(max_attempts=0)),
            "runner_rejected": lambda w: w.route6(w.intent(plan_id="other")),
            "run_not_ok": lambda w: w.route6(w.intent(step_id="nope")),
            "no_registry": lambda w: w.route6(tool_registry=None),
        }
        for label, call in modes.items():
            with self.subTest(label=label):
                w = World()
                with mock.patch(LEGACY, autospec=True) as legacy, mock.patch.object(w.plans, "refresh_plan_step_statuses") as refresh:
                    out = call(w)
                legacy.assert_not_called()
                refresh.assert_not_called()
                self.assertEqual(out["route"], "section6_tool")
                self.assertIsNone(out["legacy_result"])
                self.assertEqual(out["status"], "rejected" if label in ("absent_payload", "invalid_payload", "intent_rejected") else "failed")

    def test_21_an_unexpected_runner_exception_propagates_and_is_not_turned_into_a_legacy_call(self):
        w = World()
        with mock.patch(RUNNER, side_effect=RuntimeError("boom")) as runner, mock.patch(LEGACY, autospec=True) as legacy:
            with self.assertRaises(RuntimeError):
                w.route6()
        runner.assert_called_once()
        legacy.assert_not_called()

    def test_22_an_unexpected_intent_exception_propagates_and_is_not_turned_into_a_legacy_call(self):
        w = World()
        with mock.patch(INTENT, side_effect=RuntimeError("boom")), mock.patch(RUNNER) as runner, mock.patch(LEGACY, autospec=True) as legacy:
            with self.assertRaises(RuntimeError):
                w.route6()
        runner.assert_not_called()
        legacy.assert_not_called()

    def test_23_the_section6_branch_never_refreshes_or_selects_a_legacy_step(self):
        w = World()
        with mock.patch.object(w.plans, "refresh_plan_step_statuses") as refresh, mock.patch.object(w.loop, "_identify_next_step") as nxt:
            out = w.route6()
        refresh.assert_not_called()
        nxt.assert_not_called()
        self.assertEqual(out["status"], "completed")


class TestExistingAgentLoopBehaviourAndBoundaries(unittest.TestCase):
    def test_24_everything_but_the_sanctioned_additions_is_byte_identical_to_the_pre_719c_agent_loop(self):
        self.assertEqual(hashlib.sha256(baseline.baseline_bytes()).hexdigest(), FROZEN_AGENT_LOOP_SHA256)

    def test_25_the_only_additions_are_three_imports_and_one_method(self):
        with open(os.path.join(PY_ROOT, "agent", "agent_loop.py"), encoding="utf-8") as fh:
            now = ast.parse(fh.read())
        before = ast.parse(baseline.baseline_text())

        def imports(tree):
            return sorted(ast.dump(n) for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)))

        def methods(tree):
            cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AgentLoop")
            return [n.name for n in cls.body if isinstance(n, ast.FunctionDef)]
        self.assertEqual(len(imports(now)) - len(imports(before)), 3)
        self.assertEqual(sorted(set(methods(now)) - set(methods(before))), ["execute_routed_step"])
        self.assertEqual([m for m in methods(now) if m != "execute_routed_step"], methods(before))

    def test_26_existing_entry_points_keep_their_signatures_and_do_not_know_the_new_method(self):
        self.assertEqual(list(inspect.signature(AgentLoop.run).parameters), ["self", "goal_id", "plan_id", "max_iterations"])
        self.assertEqual(list(inspect.signature(AgentLoop.execute_next_step).parameters), ["self", "plan_id", "capability_system"])
        self.assertEqual(list(inspect.signature(AgentLoop.execute_routed_step).parameters),
                         ["self", "declaration", "legacy_input", "tool_input", "capability_system", "tool_registry"])
        for name in ("run", "execute_next_step", "__init__", "_finish", "_identify_next_step"):
            source = inspect.getsource(getattr(AgentLoop, name))
            for token in ("execute_routed_step", "tool_step", "run_tool_step_intent", "resolve_tool_step_dispatch"):
                self.assertNotIn(token, source, (name, token))

    def test_27_existing_legacy_behaviour_is_compatible_run_and_execute_next_step_still_work(self):
        w = World(steps=0)
        self.assertEqual(w.loop.execute_next_step(w.plan.plan_id)["executed"], False)
        result = w.loop.run(w.plan.goal_id, w.plan.plan_id)
        self.assertIn(result["status"], ("unknown", "not_satisfied", "satisfied", "blocked"))
        self.assertTrue(result["success"])

    def test_28_process_input_core_plan_and_plan_manager_are_untouched(self):
        def sha(rel):
            with open(os.path.join(PY_ROOT, rel), "rb") as fh:
                return hashlib.sha256(fh.read()).hexdigest()
        self.assertEqual(sha("core/core.py"), FROZEN_CORE_SHA256)
        self.assertEqual(sha("planning/plan_manager.py"), FROZEN_PLAN_MANAGER_SHA256)
        self.assertEqual(sha("planning/tool_step_agent_adapter.py"), FROZEN_ADAPTER_SHA256)
        with open(os.path.join(PY_ROOT, "core", "core.py"), encoding="utf-8") as fh:
            core_text = fh.read()
        for token in ("agent_loop", "AgentLoop", "execute_routed_step", "tool_step_"):
            self.assertNotIn(token, core_text)

    def test_29_nothing_in_production_calls_the_new_method(self):
        callers = []
        for path in glob.glob(os.path.join(PY_ROOT, "**", "*.py"), recursive=True):
            rel = os.path.relpath(path, PY_ROOT).replace(os.sep, "/")
            if rel.startswith("tests/"):
                continue
            with open(path, encoding="utf-8") as fh:
                if "execute_routed_step" in fh.read():
                    callers.append(rel)
        self.assertEqual(callers, ["agent/agent_loop.py"])                 # defined there; never invoked by run(), process_input or any module

    def test_30_the_new_method_holds_to_its_boundary(self):
        source = baseline.method_source()
        tree = ast.parse("class _C:\n" + source)
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("create_tool_request", "map_required_capabilities", "execute_plan_tool_step_with_retry", "execute_agent_tool_step",
                          "self.retry_step", "self._plan_manager.refresh_plan_step_statuses", "self._identify_next_step", "open", "eval", "exec"):
            self.assertNotIn(forbidden, calls)
        self.assertEqual(sum(1 for n in ast.walk(tree) if isinstance(n, ast.Call) and ast.unparse(n.func) == "run_tool_step_intent"), 1)
        self.assertEqual(sum(1 for n in ast.walk(tree) if isinstance(n, ast.Call) and ast.unparse(n.func) == "self.execute_next_step"), 1)
        self.assertFalse(any(isinstance(n, ast.Try) for n in ast.walk(tree)))          # nothing is caught, so no failure can be swallowed into a fallback
        body = source.split('"""')[2]                                                     # code after the docstring
        for token in ("execution_authorized", "max_attempts", "granted_", "required_capabilities", "capability_mapping", "refresh_"):
            self.assertNotIn(token, body)

    def test_31_legacy_call_sits_only_in_the_legacy_branch_before_any_section6_work(self):
        source = baseline.method_source()
        self.assertLess(source.index("self.execute_next_step("), source.index("build_tool_step_intent(payload)"))
        self.assertLess(source.index("if not dispatch.is_section6_tool:"), source.index("self.execute_next_step("))
        legacy_block = source[source.index("if not dispatch.is_section6_tool:"):source.index("build_tool_step_intent(payload)")]
        self.assertIn("return envelope(", legacy_block.rsplit("self.execute_next_step(", 1)[1])      # the legacy branch always returns; never falls through

    def test_32_pristine_database_no_pycache_and_the_documentation_note(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("execute_routed_step", "process_input", "caller-owned", "legacy", "section6_tool", "never falls back", "residual"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
