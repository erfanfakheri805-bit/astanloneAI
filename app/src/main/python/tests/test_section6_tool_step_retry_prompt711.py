"""Prompt 711 - Section 6 controlled retry policy (`planning/tool_step_retry.py`).

Focused tests for `execute_plan_tool_step_with_retry()`: a stateless, caller-controlled loop over the existing preflighted/mapped
pre-start path. Only failures BEFORE the step starts (and only those on the documented list) are retried; a started step is never
retried. Not wired into process_input() or the Agent Loop.
"""
import ast
import copy
import hashlib
import inspect
import os
import unittest

from planning import tool_step_retry as retry_mod
from planning.tool_step_executor import (OUTCOME_COMPLETED, OUTCOME_PRE_REGISTRY_REJECTION,
                                         OUTCOME_REGISTRY_PREFLIGHT_REJECTION, OUTCOME_TOOL_EXECUTION_FAILURE,
                                         PRESTART_CAPABILITY_MAPPING_REJECTED, PRESTART_MAPPED_GRANT_NOT_SUPPLIED)
from planning.tool_step_retry import (RETRY_INVALID_LIMIT, RETRY_INVALID_LOG, RETRY_INVALID_MAPPING_PAIR, STATUS_RETRY_COMPLETED,
                                      STATUS_RETRY_FAILED, STATUS_RETRY_REJECTED, STOP_COMPLETED, STOP_EXECUTION_FAILED,
                                      STOP_INVALID_ARGUMENTS, STOP_LIMIT_REACHED, STOP_NON_RETRYABLE, ToolStepRetryResult,
                                      execute_plan_tool_step_with_retry, is_retryable_prestart_result)
from tools.in_process_tool_registry import (InProcessToolRegistry, TOOL_CAPABILITY_MISSING, TOOL_DISABLED)
from tests.test_section6_tool_step_executor_prompt708 import make_plan, make_registry, req, snapshot, step_of
from tests.test_section6_tool_step_preflight_prompt709 import registry_state, spy_registry_class

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"

MAPPING = [{"capability": "Needs A", "grants": ["cap_a"]}]
RESULT_KEYS = {"ok", "status", "stop_reason", "step_id", "max_attempts", "attempts_made", "attempts", "final", "reason", "failures"}
RECORD_KEYS = {"record_type", "attempt", "outcome_kind", "status", "execution_started", "retryable", "step_id", "tool_name",
               "previous_state", "final_state", "reason", "codes", "failures", "invocation_recorded", "sequence"}


def retry(plan, request, reg, n, step_id="s1", log=None, required=None, mapping=None):
    return execute_plan_tool_step_with_retry(plan, step_id, request, reg, n, required, mapping, log)


class EnableAfter(InProcessToolRegistry):
    """Registry whose disabled tool 'off' becomes enabled after `flip_after` preflight calls (an OUTSIDE change between attempts)."""
    flip_after = 1

    def __init__(self):
        super().__init__()
        self.preflights = 0

    def preflight(self, *a, **k):
        res = super().preflight(*a, **k)
        self.preflights += 1
        if self.preflights == self.flip_after:
            self.enable("off")
        return res


def enable_after_registry(flip_after=1):
    reg, h = make_registry(type("R", (EnableAfter,), {"flip_after": flip_after}))
    return reg, h


class TestArguments(unittest.TestCase):
    def test_attempt_limit_validation_makes_zero_attempts(self):
        for bad in (0, -1, None, True, False, 1.0, "3", [1], 2 ** 0.5):
            calls = []
            reg, h = make_registry(spy_registry_class(calls))
            plan = make_plan()
            before, log = snapshot(plan), []
            res = retry(plan, req("echo"), reg, bad, log=log)
            self.assertIsInstance(res, ToolStepRetryResult)
            self.assertEqual((res.status, res.stop_reason, res.attempts_made, res.attempts, res.final),
                             (STATUS_RETRY_REJECTED, STOP_INVALID_ARGUMENTS, 0, [], None), repr(bad))
            self.assertEqual((res.codes(), res.reason), ([RETRY_INVALID_LIMIT], RETRY_INVALID_LIMIT))
            self.assertEqual((calls, log, snapshot(plan), h["echo"].count, reg.invocation_count()), ([], [], before, 0, 0))

    def test_no_default_limit_exists(self):
        self.assertEqual(list(inspect.signature(execute_plan_tool_step_with_retry).parameters),
                         ["plan", "step_id", "request", "registry", "max_attempts", "required_capabilities",
                          "capability_mapping", "attempt_log"])
        self.assertIs(inspect.signature(execute_plan_tool_step_with_retry).parameters["max_attempts"].default,
                      inspect.Parameter.empty)

    def test_invalid_log_and_mapping_pair_are_immediate_rejections_without_attempts(self):
        reg, h = make_registry()
        plan = make_plan()
        res = retry(plan, req("echo"), reg, 3, log="nope")
        self.assertEqual((res.codes(), res.attempts_made, res.stop_reason), ([RETRY_INVALID_LOG], 0, STOP_INVALID_ARGUMENTS))
        for required, mapping in ((["Needs A"], None), (None, MAPPING)):
            res = retry(plan, req("echo"), reg, 3, required=required, mapping=mapping)
            self.assertEqual((res.codes(), res.attempts_made), ([RETRY_INVALID_MAPPING_PAIR], 0))
        self.assertEqual((h["echo"].count, reg.invocation_count(), step_of(plan, "s1").status), (0, 0, "pending"))

    def test_bad_underlying_arguments_are_one_non_retryable_attempt(self):
        reg, h = make_registry()
        for kwargs in ({"step_id": "nope"}, {"step_id": ""}):
            plan = make_plan()
            res = retry(plan, req("echo"), reg, 5, **kwargs)
            self.assertEqual((res.status, res.stop_reason, res.attempts_made), (STATUS_RETRY_REJECTED, STOP_NON_RETRYABLE, 1))
            self.assertFalse(res.attempts[0]["retryable"])
        res = retry(make_plan(), "not a request", reg, 5)
        self.assertEqual((res.stop_reason, res.attempts_made), (STOP_NON_RETRYABLE, 1))
        res = retry(make_plan(), req("echo"), "not a registry", 5)
        self.assertEqual((res.stop_reason, res.attempts_made), (STOP_NON_RETRYABLE, 1))
        res = retry("not a plan", req("echo"), reg, 5)
        self.assertEqual((res.stop_reason, res.attempts_made), (STOP_NON_RETRYABLE, 1))
        self.assertEqual(h["echo"].count, 0)

    def test_invalid_plan_is_not_retried(self):
        reg, h = make_registry()
        plan = make_plan()
        plan.steps[0].dependencies = ["ghost"]           # invalid plan (unknown dependency)
        res = retry(plan, req("echo"), reg, 4)
        self.assertEqual((res.stop_reason, res.attempts_made, res.reason), (STOP_NON_RETRYABLE, 1, "INVALID_PLAN"))
        self.assertEqual(h["echo"].count, 0)

    def test_malformed_mapping_and_required_list_are_not_retried(self):
        for required, mapping in ((["Needs A"], [{"capability": "Needs A", "grants": ["BAD NAME"]}]), (["Needs A"], "bad"),
                                  ([""], MAPPING), (None if False else 5, MAPPING)):
            reg, h = make_registry()
            res = retry(make_plan(), req("needs_cap", caps=["cap_a"]), reg, 4, required=required, mapping=mapping)
            self.assertEqual((res.stop_reason, res.attempts_made, res.reason), (STOP_NON_RETRYABLE, 1,
                                                                                 PRESTART_CAPABILITY_MAPPING_REJECTED))
            self.assertEqual(h["needs_cap"].count, 0)


class TestRetryBehaviour(unittest.TestCase):
    def test_one_allowed_attempt_success(self):
        reg, h = make_registry()
        plan = make_plan()
        res = retry(plan, req("echo", {"a": 1}), reg, 1)
        self.assertTrue(res.ok)
        self.assertEqual((res.status, res.stop_reason, res.attempts_made, res.max_attempts), (STATUS_RETRY_COMPLETED,
                                                                                               STOP_COMPLETED, 1, 1))
        self.assertEqual((res.final["outcome_kind"], h["echo"].count, step_of(plan, "s1").status), (OUTCOME_COMPLETED, 1, "completed"))
        self.assertEqual(set(res.to_dict()), RESULT_KEYS)

    def test_one_allowed_attempt_retryable_rejection_hits_the_limit(self):
        reg, h = make_registry()
        res = retry(make_plan(), req("off"), reg, 1)
        self.assertEqual((res.status, res.stop_reason, res.attempts_made, res.reason), (STATUS_RETRY_REJECTED, STOP_LIMIT_REACHED,
                                                                                         1, TOOL_DISABLED))
        self.assertTrue(res.attempts[0]["retryable"])

    def test_multiple_allowed_attempts_retryable_rejection_runs_to_the_limit(self):
        calls = []
        reg, h = make_registry(spy_registry_class(calls))
        plan = make_plan()
        before = snapshot(plan)
        res = retry(plan, req("off"), reg, 4)
        self.assertEqual((res.status, res.stop_reason, res.attempts_made), (STATUS_RETRY_REJECTED, STOP_LIMIT_REACHED, 4))
        self.assertEqual(calls, ["preflight"] * 4)                 # each attempt is exactly one preflight, never an execution
        self.assertEqual((h["off"].count, reg.invocation_count(), snapshot(plan)), (0, 0, before))
        self.assertEqual([a["attempt"] for a in res.attempts], [1, 2, 3, 4])
        self.assertTrue(all(a["retryable"] and not a["execution_started"] for a in res.attempts))

    def test_retryable_prestart_rejection_then_success_when_the_registry_changed_outside(self):
        reg, h = enable_after_registry(1)
        plan = make_plan()
        res = retry(plan, req("off", {"k": 1}), reg, 5)
        self.assertTrue(res.ok)
        self.assertEqual((res.attempts_made, res.stop_reason), (2, STOP_COMPLETED))
        self.assertEqual([(a["outcome_kind"], a["status"], a["execution_started"]) for a in res.attempts],
                         [(OUTCOME_REGISTRY_PREFLIGHT_REJECTION, "rejected", False), (OUTCOME_COMPLETED, "completed", True)])
        self.assertEqual((h["off"].count, reg.invocation_count(), step_of(plan, "s1").status), (1, 1, "completed"))

    def test_retry_stops_after_success_even_with_attempts_left(self):
        calls = []
        reg, h = make_registry(spy_registry_class(calls))
        res = retry(make_plan(), req("echo"), reg, 10)
        self.assertEqual((res.attempts_made, calls.count("preflight"), h["echo"].count), (1, 1, 1))

    def test_real_tool_execution_failure_is_terminal(self):
        reg, h = make_registry()
        plan = make_plan()
        res = retry(plan, req("boom"), reg, 5)
        self.assertEqual((res.status, res.stop_reason, res.attempts_made), (STATUS_RETRY_FAILED, STOP_EXECUTION_FAILED, 1))
        self.assertEqual(res.final["outcome_kind"], OUTCOME_TOOL_EXECUTION_FAILURE)
        self.assertEqual((h["boom"].count, reg.invocation_count(), step_of(plan, "s1").status), (1, 1, "failed"))
        self.assertTrue(res.attempts[0]["execution_started"])
        self.assertFalse(res.attempts[0]["retryable"])
        self.assertFalse(res.ok)

    def test_toctou_failure_after_a_passed_preflight_is_terminal(self):
        class Disable(InProcessToolRegistry):
            def preflight(self, *a, **k):
                out = super().preflight(*a, **k)
                self.disable("echo")            # passes now, is disabled before execution
                return out
        reg, h = make_registry(Disable)
        plan = make_plan()
        res = retry(plan, req("echo"), reg, 5)
        self.assertEqual((res.status, res.stop_reason, res.attempts_made), (STATUS_RETRY_FAILED, STOP_EXECUTION_FAILED, 1))
        self.assertEqual((step_of(plan, "s1").status, h["echo"].count), ("failed", 0))

    def test_no_retry_after_a_started_step_for_any_started_outcome(self):
        for tool in ("boom", "badout", "typed"):
            reg, h = make_registry()
            plan = make_plan()
            res = retry(plan, req(tool), reg, 6)
            self.assertEqual((res.stop_reason, res.attempts_made, step_of(plan, "s1").status), (STOP_EXECUTION_FAILED, 1, "failed"), tool)
            self.assertEqual(reg.invocation_count(), 1)

    def test_no_retry_after_completion_and_a_completed_step_never_runs_again(self):
        reg, h = make_registry()
        plan = make_plan()
        self.assertTrue(retry(plan, req("echo"), reg, 3).ok)
        again = retry(plan, req("echo"), reg, 5)
        self.assertEqual((again.status, again.stop_reason, again.attempts_made), (STATUS_RETRY_REJECTED, STOP_NON_RETRYABLE, 1))
        self.assertEqual((again.attempts[0]["previous_state"], again.attempts[0]["retryable"]), ("completed", False))
        self.assertEqual((h["echo"].count, reg.invocation_count(), step_of(plan, "s1").status), (1, 1, "completed"))

    def test_failed_step_is_not_run_again(self):
        reg, h = make_registry()
        plan = make_plan()
        retry(plan, req("boom"), reg, 2)
        again = retry(plan, req("boom"), reg, 5)
        self.assertEqual((again.stop_reason, again.attempts_made), (STOP_NON_RETRYABLE, 1))
        self.assertEqual((h["boom"].count, reg.invocation_count()), (1, 1))

    def test_step_not_ready_is_retryable_only_while_pending(self):
        reg, h = make_registry()
        plan = make_plan("a", "b", chain=True)
        res = retry(plan, req("echo"), reg, 3, step_id="b")
        self.assertEqual((res.stop_reason, res.attempts_made, res.reason), (STOP_LIMIT_REACHED, 3, "STEP_NOT_READY"))
        self.assertTrue(all(a["previous_state"] == "pending" and a["retryable"] for a in res.attempts))
        self.assertEqual(h["echo"].count, 0)

    def test_unauthorized_plan_is_retryable_pending_step_condition(self):
        reg, h = make_registry()
        plan = make_plan(authorized=False)
        res = retry(plan, req("echo"), reg, 2)
        self.assertEqual((res.stop_reason, res.attempts_made), (STOP_LIMIT_REACHED, 2))
        self.assertEqual(h["echo"].count, 0)

    def test_mapped_capability_rejection_remains_pre_start(self):
        calls = []
        reg, h = make_registry(spy_registry_class(calls))
        plan = make_plan()
        before = snapshot(plan)
        res = retry(plan, req("needs_cap", caps=["cap_a"]), reg, 3, required=["Needs A", "Ghost"], mapping=MAPPING)
        self.assertEqual((res.stop_reason, res.attempts_made, res.reason), (STOP_LIMIT_REACHED, 3, PRESTART_CAPABILITY_MAPPING_REJECTED))
        self.assertTrue(all(a["outcome_kind"] == OUTCOME_PRE_REGISTRY_REJECTION and not a["execution_started"]
                            and a["retryable"] for a in res.attempts))
        self.assertEqual((calls, h["needs_cap"].count, snapshot(plan), reg.invocation_count()), ([], 0, before, 0))

    def test_missing_required_granted_capability_is_retryable_and_pre_start(self):
        reg, h = make_registry()
        plan = make_plan()
        res = retry(plan, req("needs_cap", caps=["other"]), reg, 2, required=["Needs A"], mapping=MAPPING)
        self.assertEqual((res.stop_reason, res.attempts_made, res.reason), (STOP_LIMIT_REACHED, 2, PRESTART_MAPPED_GRANT_NOT_SUPPLIED))
        self.assertEqual((h["needs_cap"].count, reg.invocation_count(), step_of(plan, "s1").status), (0, 0, "pending"))

    def test_registry_preflight_rejection_remains_pre_start(self):
        reg, h = make_registry()
        plan = make_plan()
        res = retry(plan, req("needs_cap", caps=["cap_b"]), reg, 2, required=["W"], mapping=[{"capability": "W", "grants": ["cap_b"]}])
        self.assertEqual((res.final["outcome_kind"], res.reason, res.attempts_made), (OUTCOME_REGISTRY_PREFLIGHT_REJECTION,
                                                                                       TOOL_CAPABILITY_MISSING, 2))
        self.assertEqual((h["needs_cap"].count, reg.invocation_count(), step_of(plan, "s1").status), (0, 0, "pending"))

    def test_mapped_success_and_defective_preflight_is_not_retried(self):
        reg, h = make_registry()
        ok = retry(make_plan(), req("needs_cap", caps=["cap_a", "extra"]), reg, 3, required=["Needs A"], mapping=MAPPING)
        self.assertTrue(ok.ok)
        self.assertEqual(ok.attempts_made, 1)

        class Defective(InProcessToolRegistry):
            def preflight(self, *a, **k):
                raise RuntimeError("defect")
        reg2, h2 = make_registry(Defective)
        res = retry(make_plan(), req("echo"), reg2, 4)
        self.assertEqual((res.stop_reason, res.attempts_made, res.reason), (STOP_NON_RETRYABLE, 1, "PRESTART_PREFLIGHT_EXCEPTION"))
        self.assertEqual(h2["echo"].count, 0)

    def test_programming_errors_propagate_and_are_not_retried(self):
        class Broken(InProcessToolRegistry):
            def preflight(self, *a, **k):
                raise KeyboardInterrupt()
        reg, h = make_registry(Broken)
        with self.assertRaises(KeyboardInterrupt):
            retry(make_plan(), req("echo"), reg, 3)


class TestRecordsAndIsolation(unittest.TestCase):
    def test_no_fabricated_audit_or_invocation_records(self):
        reg, h = make_registry()
        plan = make_plan()
        res = retry(plan, req("off"), reg, 4)
        self.assertEqual((reg.invocation_count(), reg.get_invocation_history()), (0, []))
        for a in res.attempts:
            self.assertEqual((a["sequence"], a["invocation_recorded"], a["execution_started"]), (None, False, False))
        self.assertIsNone(res.final["sequence"])
        # a real execution carries the registry's own sequence, unchanged
        reg2, _ = enable_after_registry(2)
        ok = retry(make_plan(), req("off"), reg2, 5)
        self.assertEqual([a["sequence"] for a in ok.attempts], [None, None, 1])
        self.assertEqual((ok.attempts[-1]["invocation_recorded"], reg2.get_invocation_history()[0]["sequence"]), (True, 1))
        self.assertEqual(reg2.invocation_count(), 1)

    def test_caller_owned_attempt_log_isolation(self):
        reg, _ = make_registry()
        log_a, log_b = ["pre-existing"], []
        res = retry(make_plan(), req("off"), reg, 3, log=log_a)
        retry(make_plan(), req("off"), reg, 2, log=log_b)
        self.assertEqual((len(log_a), len(log_b)), (4, 2))
        self.assertEqual(log_a[0], "pre-existing")
        self.assertEqual(log_a[1:], res.attempts)
        log_a[1]["reason"] = "tampered"
        log_a[1]["failures"].append("x")
        self.assertNotEqual(res.attempts[0]["reason"], "tampered")          # log entries are independent copies
        res.attempts[1]["reason"] = "tampered"
        self.assertNotEqual(log_a[2]["reason"], "tampered")
        res.to_dict()["attempts"][0]["codes"].append("x")
        self.assertNotIn("x", res.attempts[0]["codes"])
        self.assertFalse(hasattr(retry_mod, "LOG") or hasattr(retry_mod, "_log") or hasattr(retry_mod, "HISTORY"))

    def test_no_log_is_needed_and_none_is_kept_between_calls(self):
        reg, _ = make_registry()
        first = retry(make_plan(), req("off"), reg, 2)
        second = retry(make_plan(), req("off"), reg, 2)
        self.assertEqual(first.to_dict(), second.to_dict())                  # no memory of the earlier call

    def test_deterministic_attempt_numbering_and_order(self):
        outs = []
        for _ in range(3):
            reg, _ = make_registry()
            log = []
            res = retry(make_plan(), req("off"), reg, 4, log=log)
            outs.append((res.to_dict(), log))
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(outs[1], outs[2])
        self.assertEqual([r["attempt"] for r in outs[0][1]], [1, 2, 3, 4])
        self.assertEqual(set(outs[0][1][0]), RECORD_KEYS)
        self.assertTrue(all(r["record_type"] == "tool_step_attempt" for r in outs[0][1]))

    def test_record_contents_cover_outcome_status_failures_and_started_flag(self):
        reg, _ = make_registry()
        rec = retry(make_plan(), req("off"), reg, 1).attempts[0]
        self.assertEqual((rec["outcome_kind"], rec["status"], rec["execution_started"], rec["reason"], rec["codes"]),
                         (OUTCOME_REGISTRY_PREFLIGHT_REJECTION, "rejected", False, TOOL_DISABLED, [TOOL_DISABLED]))
        self.assertEqual(rec["failures"][0]["code"], TOOL_DISABLED)
        self.assertEqual((rec["previous_state"], rec["final_state"], rec["tool_name"], rec["step_id"]), ("pending", "pending", "off", "s1"))

    def test_no_mutation_of_request_mapping_grants_or_required_list(self):
        reg, _ = make_registry()
        request = req("needs_cap", {"k": [1]}, caps=["extra", "cap_a"])
        required, mapping = ["Needs A", "Ghost"], copy.deepcopy(MAPPING) + [{"capability": "Unused", "grants": ["zzz"]}]
        before = (request.to_dict(), copy.deepcopy(required), copy.deepcopy(mapping))
        retry(make_plan(), request, reg, 3, required=required, mapping=mapping)
        self.assertEqual((request.to_dict(), required, mapping), before)
        self.assertEqual(request.granted_capabilities, ("extra", "cap_a"))
        # and each attempt passes the very same request: the registry sees identical grants every time
        seen = []

        class Watch(InProcessToolRegistry):
            def preflight(self, *a, **k):
                seen.append((k["granted_capabilities"], k["granted_permissions"], k["confirmed"]))
                return super().preflight(*a, **k)
        reg2, _ = make_registry(Watch)
        retry(make_plan(), req("off", caps=["c_x"]), reg2, 3)
        self.assertEqual(len(seen), 3)
        self.assertTrue(all(s == seen[0] for s in seen))


class TestClassificationAndBoundaries(unittest.TestCase):
    def test_classifier_is_an_allow_list(self):
        from planning.tool_step_executor import PreflightedToolStepResult
        r = PreflightedToolStepResult("s1", "echo")
        r.status, r.outcome_kind, r.reason, r.previous_state = "rejected", OUTCOME_PRE_REGISTRY_REJECTION, "SOMETHING_NEW", "pending"
        self.assertFalse(is_retryable_prestart_result(r))
        r.reason = "STEP_NOT_READY"
        self.assertTrue(is_retryable_prestart_result(r))
        r.previous_state = "completed"
        self.assertFalse(is_retryable_prestart_result(r))
        r.previous_state, r.execution_called = "pending", True
        self.assertFalse(is_retryable_prestart_result(r))

    def test_module_imports_only_the_executor_and_uses_no_time_or_threads(self):
        src = inspect.getsource(retry_mod)
        tree = ast.parse(src)
        imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
                  {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        self.assertEqual(imports, {"planning.tool_step_executor"})
        ids = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("execute_request", "execute", "invoke", "handler", "start_plan_step", "complete_plan_step", "fail_plan_step",
                     "preflight", "sleep", "time", "random", "threading", "Thread", "Timer", "global", "process_input",
                     "ExecutionEngine", "PlanExecutionController", "CapabilitySystem", "create_tool_request"):
            self.assertNotIn(word, ids, word)
        for word in ("global ", "import time", "import threading", "import sqlite3", "open("):
            self.assertNotIn(word, src)

    def test_not_wired_into_any_other_production_module(self):
        for root, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__")]
            for f in files:
                path = os.path.join(root, f)
                if f.endswith(".py") and not path.endswith(os.path.join("planning", "tool_step_retry.py")) \
                        and not path.endswith(os.path.join("planning", "tool_step_agent_adapter.py")) \
                        and not path.endswith(os.path.join("agent", "tool_step_runner.py")):     # Prompt 714 adapter; Prompt 719-B runner
                    with open(path, encoding="utf-8") as fh:
                        text = fh.read()
                    self.assertNotIn("tool_step_retry", text, path)
                    self.assertNotIn("execute_plan_tool_step_with_retry", text, path)

    def test_earlier_section6_signatures_are_unchanged(self):
        from planning.tool_step_executor import (execute_plan_tool_step, execute_plan_tool_step_mapped,
                                                 execute_plan_tool_step_preflighted)
        self.assertEqual(list(inspect.signature(execute_plan_tool_step).parameters), ["plan", "step_id", "request", "registry"])
        self.assertEqual(list(inspect.signature(execute_plan_tool_step_preflighted).parameters),
                         ["plan", "step_id", "request", "registry", "rejection_log"])
        self.assertEqual(list(inspect.signature(execute_plan_tool_step_mapped).parameters),
                         ["plan", "step_id", "request", "registry", "required_capabilities", "capability_mapping", "rejection_log"])

    def test_registry_state_untouched_by_all_pre_start_stops(self):
        reg, _ = make_registry()
        before = registry_state(reg)
        retry(make_plan(), req("off"), reg, 3)
        retry(make_plan(), req("echo"), reg, 3, step_id="ghost")
        self.assertEqual(registry_state(reg), before)

    def test_database_untouched(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
