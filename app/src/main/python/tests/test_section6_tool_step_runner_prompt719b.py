"""Prompt 719-B - Section 6 caller-side tool step runner (`agent/tool_step_runner.py`).

Focused tests: the runner is a thin adapter from a successful `ToolStepIntentResult` to the existing
`execute_plan_tool_step_with_retry`. Most tests replace the retry layer with a small fake; a few run the real layer end to end.
"""
import ast
import hashlib
import inspect
import os
import pickle
import unittest
from unittest import mock

from agent import tool_step_runner as runner_mod
from agent.tool_step_intent import ToolStepIntentResult, build_tool_step_intent
from agent.tool_step_runner import (OUTCOME_RUNNER_REJECTION, RUNNER_INTENT_NOT_OK, RUNNER_INVALID_INTENT_RESULT,
                                    RUNNER_INVALID_MAPPING_PAIR, RUNNER_PLAN_ID_MISMATCH, STOP_RUNNER_REJECTED,
                                    ToolStepRunResult, run_tool_step_intent)
from planning.tool_step_retry import STATUS_RETRY_COMPLETED, STOP_COMPLETED, STOP_NON_RETRYABLE, ToolStepRetryResult
from tests.test_section6_tool_step_executor_prompt708 import make_plan, make_registry, snapshot, step_of

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
PATCH_TARGET = "agent.tool_step_runner.execute_plan_tool_step_with_retry"

MAPPING = [{"capability": "Needs A", "grants": ["cap_a"]}]
REQUIRED = ["Needs A"]
RESULT_KEYS = {"ok", "plan_id", "step_id", "outcome_kind", "stop_reason", "attempts", "final_step_state", "failures",
               "execution_result"}


def intent(**over):
    data = {"plan_id": "p", "step_id": "s1", "max_attempts": 3,
            "tool_request": {"name": "echo", "tool_input": {"a": 1}, "granted_permissions": [],
                             "granted_capabilities": [], "confirmed": False}}
    data.update(over)
    return data


def built(**over):
    res = build_tool_step_intent(intent(**over))
    assert res.ok, res.codes()
    return res


def fake_retry_result(step_id="s1"):
    res = ToolStepRetryResult(step_id, 3)
    res.status, res.stop_reason, res.attempts_made, res.reason = STATUS_RETRY_COMPLETED, STOP_COMPLETED, 1, "completed"
    res.attempts = [{"record_type": "tool_step_attempt", "attempt": 1}]
    res.final = {"ok": True, "outcome_kind": "completed", "final_state": "completed", "nested": {"k": [1]}}
    return res


class TestDelegation(unittest.TestCase):
    def test_1_successful_intent_reaches_existing_retry_layer(self):
        plan, reg = make_plan(), object()
        with mock.patch(PATCH_TARGET, return_value=fake_retry_result()) as fake:
            out = run_tool_step_intent(built(), plan, reg)
        fake.assert_called_once()
        self.assertIsInstance(out, ToolStepRunResult)
        self.assertEqual((out.ok, out.plan_id, out.step_id, out.outcome_kind, out.stop_reason, out.final_step_state),
                         (True, "p", "s1", "completed", "completed", "completed"))
        self.assertEqual(set(out.to_dict()), RESULT_KEYS)
        args = fake.call_args.args
        self.assertIs(args[0], plan)
        self.assertEqual(args[1], "s1")

    def test_2_failed_intent_result_is_rejected_before_execution(self):
        bad = build_tool_step_intent({})
        self.assertFalse(bad.ok)
        log, reg, plan = [], mock.Mock(), make_plan()
        before = snapshot(plan)
        with mock.patch(PATCH_TARGET) as fake:
            out = run_tool_step_intent(bad, plan, reg, log)
        fake.assert_not_called()
        self.assertEqual(reg.mock_calls, [])
        self.assertEqual(log, [])
        self.assertEqual(snapshot(plan), before)
        self.assertFalse(out.ok)
        self.assertEqual((out.codes(), out.outcome_kind, out.stop_reason, out.attempts, out.execution_result),
                         ([RUNNER_INTENT_NOT_OK], OUTCOME_RUNNER_REJECTION, STOP_RUNNER_REJECTED, [], None))

    def test_3_invalid_result_type_is_rejected(self):
        good = built()
        for bogus in (None, {}, intent(), good.to_dict(), "x", 7, object()):
            with mock.patch(PATCH_TARGET) as fake:
                out = run_tool_step_intent(bogus, make_plan(), mock.Mock())
            fake.assert_not_called()
            self.assertEqual(out.codes(), [RUNNER_INVALID_INTENT_RESULT])
        with self.assertRaises(TypeError):
            ToolStepIntentResult(object(), True, "p", "s1", None, 1, None, None, ())

    def test_4_neither_mapping_argument(self):
        with mock.patch(PATCH_TARGET, return_value=fake_retry_result()) as fake:
            run_tool_step_intent(built(), make_plan(), object())
        self.assertIsNone(fake.call_args.args[5])
        self.assertIsNone(fake.call_args.args[6])

    def test_5_both_mapping_arguments(self):
        with mock.patch(PATCH_TARGET, return_value=fake_retry_result()) as fake:
            run_tool_step_intent(built(required_capabilities=REQUIRED, capability_mapping=MAPPING), make_plan(), object())
        self.assertEqual(fake.call_args.args[5], REQUIRED)
        self.assertEqual(fake.call_args.args[6], MAPPING)

    def test_6_only_required_capabilities_is_rejected(self):
        self._only_one(built(required_capabilities=REQUIRED))

    def test_7_only_capability_mapping_is_rejected(self):
        self._only_one(built(capability_mapping=MAPPING))

    def _only_one(self, result):
        log, reg = [], mock.Mock()
        with mock.patch(PATCH_TARGET) as fake:
            out = run_tool_step_intent(result, make_plan(), reg, log)
        fake.assert_not_called()
        self.assertEqual((reg.mock_calls, log), ([], []))
        self.assertEqual(out.codes(), [RUNNER_INVALID_MAPPING_PAIR])
        self.assertFalse(out.ok)

    def test_plan_id_mismatch_is_rejected_before_execution(self):
        with mock.patch(PATCH_TARGET) as fake:
            out = run_tool_step_intent(built(plan_id="other"), make_plan(), mock.Mock())
            out2 = run_tool_step_intent(built(), object(), mock.Mock())
        fake.assert_not_called()
        self.assertEqual((out.codes(), out2.codes()), ([RUNNER_PLAN_ID_MISMATCH], [RUNNER_PLAN_ID_MISMATCH]))

    def test_8_max_attempts_is_passed_unchanged(self):
        with mock.patch(PATCH_TARGET, return_value=fake_retry_result()) as fake:
            run_tool_step_intent(built(max_attempts=7), make_plan(), object())
        self.assertEqual(fake.call_args.args[4], 7)
        self.assertIs(type(fake.call_args.args[4]), int)

    def test_9_tool_request_is_passed_unchanged(self):
        res = built()
        with mock.patch(PATCH_TARGET, return_value=fake_retry_result()) as fake:
            run_tool_step_intent(res, make_plan(), object())
        self.assertIs(fake.call_args.args[2], res.request)

    def test_10_registry_is_passed_unchanged(self):
        reg = mock.Mock()
        with mock.patch(PATCH_TARGET, return_value=fake_retry_result()) as fake:
            run_tool_step_intent(built(), make_plan(), reg)
        self.assertIs(fake.call_args.args[3], reg)
        self.assertEqual(reg.mock_calls, [])

    def test_11_caller_attempt_log_is_reused(self):
        log = []
        with mock.patch(PATCH_TARGET, return_value=fake_retry_result()) as fake:
            run_tool_step_intent(built(), make_plan(), object(), log)
            run_tool_step_intent(built(), make_plan(), object())
        self.assertIs(fake.call_args_list[0].args[7], log)
        self.assertIsNone(fake.call_args_list[1].args[7])
        self.assertEqual(log, [])          # the runner itself never writes to it

    def test_12_runner_does_not_create_duplicate_attempts(self):
        reg, handlers = make_registry()
        plan, log = make_plan(), []
        out = run_tool_step_intent(built(), plan, reg, log)
        self.assertTrue(out.ok, out.failures)
        self.assertEqual(len(log), 1)
        self.assertEqual(len(out.attempts), 1)
        self.assertEqual(out.attempts, log)
        self.assertEqual(handlers["echo"].count, 1)
        self.assertEqual(step_of(plan, "s1").status, "completed")
        self.assertEqual((out.outcome_kind, out.final_step_state, out.stop_reason), ("completed", "completed", STOP_COMPLETED))

    def test_real_layer_rejection_and_limit_are_reported(self):
        reg, handlers = make_registry()
        log = []
        out = run_tool_step_intent(built(tool_request={"name": "nope", "tool_input": {}, "granted_permissions": [],
                                                       "granted_capabilities": [], "confirmed": False}, max_attempts=2),
                                   make_plan(), reg, log)
        self.assertFalse(out.ok)
        self.assertEqual(len(log), len(out.attempts))
        self.assertEqual(handlers["echo"].count, 0)
        self.assertEqual(out.final_step_state, "pending")

    def test_13_execution_result_is_isolated(self):
        with mock.patch(PATCH_TARGET, return_value=fake_retry_result()):
            out = run_tool_step_intent(built(), make_plan(), object())
        first = out.execution_result
        first["nested"]["k"].append(99)
        first["ok"] = "tampered"
        out.attempts[0]["attempt"] = 99
        out.failures.append({"code": "X"})
        self.assertEqual(out.execution_result["nested"]["k"], [1])
        self.assertIs(out.execution_result["ok"], True)
        self.assertEqual(out.attempts[0]["attempt"], 1)
        self.assertEqual(out.failures, [])
        self.assertIsNot(out.execution_result, out.execution_result)
        with self.assertRaises(AttributeError):
            out.ok = False
        with self.assertRaises(AttributeError):
            out.extra = 1
        with self.assertRaises(TypeError):
            pickle.dumps(out)
        with self.assertRaises(TypeError):
            ToolStepRunResult(object(), True, None, None, None, None, [], None, [], None)
        with self.assertRaises(TypeError):
            type("Sub", (ToolStepRunResult,), {})
        self.assertFalse(hasattr(out, "__dict__"))
        self.assertNotIn("registry", repr(sorted(out.to_dict())))

    def test_result_does_not_expose_the_caller_objects(self):
        reg = mock.Mock()
        with mock.patch(PATCH_TARGET, return_value=fake_retry_result()):
            out = run_tool_step_intent(built(), make_plan(), reg)
        self.assertNotIn(id(reg), [id(v) for v in out.to_dict().values()])
        self.assertEqual(reg.mock_calls, [])


class TestBoundaries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(runner_mod.__file__, encoding="utf-8") as fh:
            cls.source = fh.read()
        cls.tree = ast.parse(cls.source)

    def test_14_runner_does_not_access_agent_loop_or_process_input(self):
        imported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module)
        self.assertEqual(imported, {"agent.tool_step_intent", "planning.tool_step_retry"})
        code_names = {n.id for n in ast.walk(self.tree) if isinstance(n, ast.Name)} | \
                     {n.attr for n in ast.walk(self.tree) if isinstance(n, ast.Attribute)}
        for forbidden in ("process_input", "AgentLoop", "agent_loop", "core", "create_tool_request", "resolve_tool_step_route"):
            self.assertNotIn(forbidden, code_names)

    def test_15_runner_does_not_implement_its_own_retry_logic(self):
        body = inspect.getsource(runner_mod.run_tool_step_intent)
        tree = ast.parse(body)
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, (ast.For, ast.While, ast.ListComp, ast.Try))])
        called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertEqual(called & {"range", "sleep", "execute_plan_tool_step_mapped", "execute_plan_tool_step_preflighted",
                                   "execute_plan_tool_step"}, set())
        self.assertEqual(body.count("execute_plan_tool_step_with_retry("), 1)
        for word in ("time", "random", "threading", "attempts_made", "is_retryable", "start_plan_step", "complete_plan_step"):
            self.assertNotIn(word, self.source.replace("Prompt 711", ""))

    def test_no_module_level_state(self):
        assigned = [t.id for n in self.tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)]
        for name in assigned:
            value = getattr(runner_mod, name)
            self.assertNotIsInstance(value, (list, dict, set))

    def test_db_is_pristine(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
