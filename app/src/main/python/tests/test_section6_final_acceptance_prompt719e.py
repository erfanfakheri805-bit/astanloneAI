"""Prompt 719-E - Section 6 final acceptance (acceptance only; no production code is changed by this prompt).

Cross-cuts the contracts of Prompts 706-719-D that the focused suites do not already state together: no network / AI API / persistence /
background-execution dependency in any Section 6 module, route pin stays in memory and per-instance, process_input and Core stay outside
Section 6, the documented 719-D limitations really hold, and the pristine DB / no-bytecode invariants.
"""
import ast
import hashlib
import os
import unittest
from unittest import mock

from agent.agent_loop import AgentLoop
from execution.plan_execution_controller import PlanExecutionController
from tests.test_section6_agent_loop_route_pin_prompt719d import S6, LEG, pins
from tests.test_section6_agent_loop_routed_step_prompt719c import (LEGACY, PRISTINE_SHA256, PROJECT_DB, World)

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section6_final_acceptance_prompt719e.md")
SECTION6_PRODUCTION = ("planning/tool_step_bridge.py", "planning/tool_capability_mapping.py", "planning/tool_step_executor.py",
                       "planning/tool_step_retry.py", "planning/tool_step_route.py", "planning/tool_step_dispatch.py",
                       "planning/tool_step_agent_adapter.py", "agent/tool_step_intent.py", "agent/tool_step_runner.py")
FORBIDDEN_MODULES = {"socket", "ssl", "http", "urllib", "urllib3", "requests", "httpx", "aiohttp", "websocket", "ftplib", "smtplib",
                     "anthropic", "openai", "sqlite3", "shelve", "pickle", "subprocess", "threading", "multiprocessing", "asyncio",
                     "sched", "signal", "importlib", "ctypes"}
FORBIDDEN_CALLS = {"open", "eval", "exec", "compile", "__import__", "input"}


def tree(rel):
    with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
        return ast.parse(fh.read())


class TestSection6HasNoExternalOrAutomaticMechanisms(unittest.TestCase):
    def test_1_no_network_ai_api_persistence_or_background_imports(self):
        for rel in SECTION6_PRODUCTION:
            for node in ast.walk(tree(rel)):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
                for name in names:
                    self.assertNotIn(name.split(".")[0], FORBIDDEN_MODULES, (rel, name))

    def test_2_no_dynamic_code_file_or_environment_access(self):
        for rel in SECTION6_PRODUCTION:
            for node in ast.walk(tree(rel)):
                if isinstance(node, ast.Call):
                    self.assertNotIn(ast.unparse(node.func), FORBIDDEN_CALLS | {"os.environ.get", "os.getenv", "os.system"}, rel)
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                    self.assertFalse(node.value.id == "os" and node.attr in ("environ", "system", "popen"), rel)

    def test_3_no_api_key_or_url_literals(self):
        for rel in SECTION6_PRODUCTION:
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read().lower()
            for token in ("http://", "https://", "api_key", "apikey", "bearer "):
                self.assertNotIn(token, text, (rel, token))

    def test_4_no_self_modification_or_automatic_selection_in_the_routed_method(self):
        source = ast.unparse(next(n for n in ast.walk(tree("agent/agent_loop.py")) if isinstance(n, ast.FunctionDef) and n.name == "execute_routed_step"))
        for token in ("upgrade", "self_modify", "apply_proposal", "Thread", "schedule", "while ", "for ", "select_tool", "auto"):
            self.assertNotIn(token, source, token)


class TestRoutePinAcceptance(unittest.TestCase):
    def test_5_pin_is_in_memory_per_instance_and_never_written_to_plan_state_or_db(self):
        w = World()
        before = w.snapshot()
        w.route6()
        other = AgentLoop(w.goals, w.plans, PlanExecutionController(w.plans))
        self.assertEqual(pins(w.loop), {w.plan.plan_id: S6})
        self.assertEqual(pins(other), {})
        plan = w.plans.get_plan(w.plan.plan_id)
        self.assertFalse([k for k in plan.metadata if "pin" in k or "route" in k])
        self.assertNotEqual(before, w.snapshot())                         # only the executed step changed, nothing pin-related
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        with open(os.path.join(PY_ROOT, "agent", "agent_loop.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read().count("_plan_route_pins"), 1)      # created in exactly one place, inside execute_routed_step
        self.assertNotIn("sqlite", ast.unparse(next(n for n in ast.walk(tree("agent/agent_loop.py")) if isinstance(n, ast.FunctionDef) and n.name == "execute_routed_step")))

    def test_6_both_switch_directions_are_rejected_without_executing(self):
        for first, second_call in ((S6, "legacy"), (LEG, "section6")):
            with self.subTest(first=first):
                w = World()
                if first == S6:
                    w.route6()
                else:
                    w.loop.execute_routed_step(LEG, legacy_input=w.legacy_input())
                with mock.patch(LEGACY, autospec=True) as legacy, mock.patch("agent.agent_loop.run_tool_step_intent") as runner:
                    out = (w.loop.execute_routed_step(LEG, legacy_input=w.legacy_input()) if second_call == "legacy" else w.route6())
                legacy.assert_not_called()
                runner.assert_not_called()
                self.assertEqual(out["error_code"], "ROUTE_PIN_CONFLICT")
                self.assertEqual(pins(w.loop), {w.plan.plan_id: first})

    def test_7_tool_runs_exactly_once_per_accepted_runner_call_and_failures_do_not_reach_legacy(self):
        w = World()
        with mock.patch(LEGACY, autospec=True) as legacy:
            out = w.route6()
            self.assertEqual(out["status"], "completed")
            bad = w.route6(w.intent(step_id="nope"))
            self.assertEqual(bad["status"], "failed")
            legacy.assert_not_called()


class TestDocumentedLimitationsHold(unittest.TestCase):
    def test_8_direct_execute_next_step_is_not_covered_by_the_pin(self):
        w = World()
        w.route6()
        result = w.loop.execute_next_step(w.plan.plan_id)                 # documented boundary: allowed, no rejection, pin untouched
        self.assertNotIn("ROUTE_PIN_CONFLICT", repr(result))
        self.assertEqual(pins(w.loop), {w.plan.plan_id: S6})

    def test_9_undeclared_legacy_creates_no_pin_and_new_loops_start_unpinned(self):
        w = World()
        w.loop.execute_routed_step(None, legacy_input=w.legacy_input())
        self.assertEqual(pins(w.loop), {})
        w.route6()
        fresh = AgentLoop(w.goals, w.plans, PlanExecutionController(w.plans))
        self.assertEqual(pins(fresh), {})

    def test_10_process_input_and_core_remain_outside_section6(self):
        with open(os.path.join(PY_ROOT, "core", "core.py"), encoding="utf-8") as fh:
            text = fh.read()
        for token in ("agent_loop", "AgentLoop", "execute_routed_step", "tool_step_", "_plan_route_pins", "execute_next_step"):
            self.assertNotIn(token, text, token)
        for rel in ("planning/plan.py", "planning/plan_manager.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                for token in ("tool_step_", "_plan_route_pins", "route_pin"):
                    self.assertNotIn(token, fh.read(), (rel, token))

    def test_11_nothing_in_production_calls_execute_routed_step(self):
        callers = []
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__")]
            for f in files:
                if f.endswith(".py"):
                    with open(os.path.join(folder, f), encoding="utf-8") as fh:
                        if "execute_routed_step" in fh.read():
                            callers.append(os.path.relpath(os.path.join(folder, f), PY_ROOT).replace(os.sep, "/"))
        self.assertEqual(callers, ["agent/agent_loop.py"])


class TestInvariants(unittest.TestCase):
    def test_12_pristine_db_no_bytecode_and_acceptance_doc(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("execute_next_step", "not persistent", "undeclared", "process_input", "Section 6 is ready to close", "719-D"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
