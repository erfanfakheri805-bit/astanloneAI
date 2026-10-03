"""Prompt 712 - Section 6 boundary audit and final acceptance.

Audit/acceptance only: no production behaviour is changed or added by this prompt. The tests drive the complete flow

    plan -> tool request -> capability mapping -> preflight -> controlled step start -> tool execution
         -> completion/failure -> retry policy -> terminal state/reporting

through the public Section 6 entry points only (`execute_plan_tool_step_preflighted`, `execute_plan_tool_step_mapped`,
`execute_plan_tool_step_with_retry`) and assert the 29-point acceptance checklist of Prompt 712. Not wired into process_input() or
the Agent Loop; that hand-over is deliberately out of scope.
"""
import ast
import copy
import glob
import hashlib
import inspect
import os
import unittest

from planning import tool_capability_mapping as mapping_mod
from planning import tool_step_bridge as bridge_mod
from planning import tool_step_executor as exec_mod
from planning import tool_step_retry as retry_mod
from planning.plan_step_execution import start_plan_step
from planning.tool_step_executor import (OUTCOME_COMPLETED, OUTCOME_PRE_REGISTRY_REJECTION,
                                         OUTCOME_REGISTRY_PREFLIGHT_REJECTION, OUTCOME_TOOL_EXECUTION_FAILURE,
                                         PRESTART_CAPABILITY_MAPPING_REJECTED, PRESTART_MAPPED_GRANT_NOT_SUPPLIED,
                                         execute_plan_tool_step_mapped, execute_plan_tool_step_preflighted)
from planning.tool_step_retry import (RETRY_INVALID_LIMIT, RETRY_INVALID_LOG, RETRY_INVALID_MAPPING_PAIR, STATUS_RETRY_COMPLETED,
                                      STATUS_RETRY_FAILED, STATUS_RETRY_REJECTED, STOP_COMPLETED, STOP_EXECUTION_FAILED,
                                      STOP_INVALID_ARGUMENTS, STOP_LIMIT_REACHED, STOP_NON_RETRYABLE,
                                      execute_plan_tool_step_with_retry, is_retryable_prestart_result)
from tools.in_process_tool_registry import InProcessToolRegistry
from tools.tool_request import create_tool_request
from tests.test_section6_tool_step_executor_prompt708 import Counting, make_plan, make_registry, req, snapshot, step_of
from tests.test_section6_tool_step_preflight_prompt709 import registry_state, spy_registry_class
from tests.test_section6_tool_step_retry_prompt711 import enable_after_registry

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT)))), "docs")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
# Digest over (path, sha256) of every Section 4 (planning/*) and Section 5 (tools/*) production module except the four Section 6 modules.
# Frozen by Prompt 712 so that "Section 4/5 contracts unchanged" is enforced, not merely stated. A deliberate later change to a Section 4/5
# module must update this constant consciously (that is the point of the pin).
FROZEN_SECTION45_DIGEST = "82302da178629b7bf64323334282186d83ae40557ad282aa69fd21e2400c6bf1"

SECTION6_MODULES = ("planning/tool_step_bridge.py", "planning/tool_step_executor.py", "planning/tool_capability_mapping.py",
                    "planning/tool_step_retry.py")
MAPPING = [{"capability": "Needs A", "grants": ["cap_a"]}]


def run_retry(plan, request, reg, n, log=None, required=None, mapping=None, step_id="s1"):
    return execute_plan_tool_step_with_retry(plan, step_id, request, reg, n, required, mapping, log)


class ToctouRegistry(InProcessToolRegistry):
    """Preflight passes, then the tool is disabled before the real execution: the failure happens AFTER the step started."""

    def preflight(self, *a, **k):
        res = super().preflight(*a, **k)
        self.disable("echo")
        return res


def state_view(plan, reg):
    return (snapshot(plan), registry_state(reg))


class TestSuccessPaths(unittest.TestCase):
    def test_successful_unmapped_direct_tool_step_execution(self):
        calls = []
        reg, h = make_registry(spy_registry_class(calls))
        plan = make_plan()
        res = execute_plan_tool_step_preflighted(plan, "s1", req("echo", {"a": [1]}), reg)
        self.assertEqual((res.ok, res.status, res.outcome_kind), (True, "completed", OUTCOME_COMPLETED))
        self.assertEqual((res.previous_state, res.final_state, step_of(plan, "s1").status), ("pending", "completed", "completed"))
        # exactly one real invocation, exactly one handler call, exactly one execution entry
        self.assertEqual((h["echo"].count, reg.invocation_count(), calls.count("execute_request")), (1, 1, 1))
        self.assertEqual(calls.count("preflight"), 1)
        self.assertLess(calls.index("preflight"), calls.index("execute_request"))
        self.assertEqual(h["echo"].calls, [{"a": [1]}])

    def test_successful_mapped_execution(self):
        reg, h = make_registry()
        plan = make_plan()
        res = execute_plan_tool_step_mapped(plan, "s1", req("needs_cap", {"k": 1}, caps=["cap_a"]), reg, ["Needs A"], MAPPING)
        self.assertEqual((res.ok, res.outcome_kind, step_of(plan, "s1").status), (True, OUTCOME_COMPLETED, "completed"))
        self.assertEqual((h["needs_cap"].count, reg.invocation_count(), res.sequence), (1, 1, 1))

    def test_success_through_retry_layer_is_a_single_invocation(self):
        reg, h = make_registry()
        plan = make_plan()
        res = run_retry(plan, req("echo"), reg, 4)
        self.assertEqual((res.status, res.stop_reason, res.attempts_made), (STATUS_RETRY_COMPLETED, STOP_COMPLETED, 1))
        self.assertEqual((h["echo"].count, reg.invocation_count()), (1, 1))


class TestPreStartRejections(unittest.TestCase):
    def assert_untouched(self, plan, reg, h, name, before):
        self.assertEqual(state_view(plan, reg), before)
        self.assertEqual((h[name].count, reg.invocation_count(), reg.get_invocation_history()), (0, 0, []))
        self.assertEqual(step_of(plan, "s1").status, "pending")

    def test_mapped_capability_rejection_happens_before_start(self):
        cases = [(["Unknown Need"], MAPPING, PRESTART_CAPABILITY_MAPPING_REJECTED),           # unmapped requirement
                 (["Needs A"], "not a mapping", PRESTART_CAPABILITY_MAPPING_REJECTED),        # malformed mapping
                 (["Needs A"], MAPPING, PRESTART_MAPPED_GRANT_NOT_SUPPLIED)]                  # mapped grant not in the request
        for required, mapping, code in cases:
            reg, h = make_registry()
            plan, log = make_plan(), []
            before = state_view(plan, reg)
            request = req("needs_cap")                     # supplies NO grants
            res = execute_plan_tool_step_mapped(plan, "s1", request, reg, required, mapping, log)
            self.assertEqual((res.status, res.outcome_kind, res.reason, res.execution_called, res.preflight_called),
                             ("rejected", OUTCOME_PRE_REGISTRY_REJECTION, code, False, False))
            self.assertEqual((res.final_state, res.sequence), ("pending", None))
            self.assert_untouched(plan, reg, h, "needs_cap", before)
            self.assertEqual(len(log), 1)
            self.assertEqual((log[0]["record_type"], log[0]["invocation_recorded"], log[0]["sequence"]),
                             ("prestart_rejection", False, None))

    def test_registry_preflight_rejection_happens_before_start(self):
        cases = [("off", {}), ("net", {}), ("confirm", {}), ("needs_cap", {}), ("missing_tool", {})]
        for name, _ in cases:
            calls = []
            reg, h = make_registry(spy_registry_class(calls))
            h.setdefault(name, Counting())
            plan, log = make_plan(), []
            before = state_view(plan, reg)
            res = execute_plan_tool_step_preflighted(plan, "s1", req(name), reg, log)
            self.assertEqual((res.status, res.outcome_kind, res.preflight_called, res.execution_called),
                             ("rejected", OUTCOME_REGISTRY_PREFLIGHT_REJECTION, True, False), name)
            self.assertIsNotNone(res.preflight)
            self.assertNotIn("execute_request", calls)
            self.assertEqual(state_view(plan, reg), before)
            self.assertEqual((h[name].count, reg.invocation_count(), res.sequence), (0, 0, None))
            self.assertEqual((log[0]["invocation_recorded"], log[0]["sequence"]), (False, None))

    def test_no_fabricated_invocation_sequence_after_any_rejection(self):
        reg, h = make_registry()
        plan, log = make_plan(), []
        res = run_retry(plan, req("off"), reg, 3, log=log)
        self.assertEqual([a["sequence"] for a in res.attempts], [None, None, None])
        self.assertEqual([a["invocation_recorded"] for a in res.attempts], [False] * 3)
        self.assertEqual((reg.invocation_count(), reg.get_invocation_history()), (0, []))
        # the FIRST real invocation after three rejections is sequence 1: nothing was consumed by the rejections
        good = run_retry(plan, req("echo"), reg, 1)
        self.assertEqual((good.final["sequence"], good.attempts[0]["sequence"], reg.invocation_count()), (1, 1, 1))

    def test_started_step_is_never_started_by_a_failed_preflight(self):
        reg, h = make_registry()
        plan = make_plan()
        for _ in range(3):
            execute_plan_tool_step_preflighted(plan, "s1", req("off"), reg)
        self.assertEqual(step_of(plan, "s1").status, "pending")


class TestRetryPolicy(unittest.TestCase):
    def test_successful_retry_after_allowed_prestart_rejection(self):
        reg, h = enable_after_registry(flip_after=1)
        plan, log = make_plan(), []
        res = run_retry(plan, req("off"), reg, 3, log=log)
        self.assertEqual((res.status, res.stop_reason, res.attempts_made), (STATUS_RETRY_COMPLETED, STOP_COMPLETED, 2))
        first, second = res.attempts
        self.assertEqual((first["outcome_kind"], first["retryable"], first["execution_started"], first["sequence"]),
                         (OUTCOME_REGISTRY_PREFLIGHT_REJECTION, True, False, None))
        self.assertEqual((second["outcome_kind"], second["execution_started"], second["sequence"]), (OUTCOME_COMPLETED, True, 1))
        self.assertEqual((h["off"].count, reg.invocation_count(), step_of(plan, "s1").status), (1, 1, "completed"))
        self.assertEqual(log, res.attempts)

    def test_retry_limit_exhaustion(self):
        for limit in (1, 2, 5):
            reg, h = make_registry()
            plan, log = make_plan(), []
            res = run_retry(plan, req("off"), reg, limit, log=log)
            self.assertEqual((res.status, res.stop_reason, res.attempts_made, res.max_attempts),
                             (STATUS_RETRY_REJECTED, STOP_LIMIT_REACHED, limit, limit))
            self.assertEqual(len(log), limit)
            self.assertEqual((h["off"].count, reg.invocation_count(), step_of(plan, "s1").status), (0, 0, "pending"))

    def test_retry_limits_are_explicit_and_validated(self):
        self.assertIs(inspect.signature(execute_plan_tool_step_with_retry).parameters["max_attempts"].default,
                      inspect.Parameter.empty)
        for bad in (0, -1, None, True, False, 1.0, "3", [1]):
            reg, h = make_registry()
            plan, log = make_plan(), []
            before = state_view(plan, reg)
            res = run_retry(plan, req("echo"), reg, bad, log=log)
            self.assertEqual((res.status, res.stop_reason, res.attempts_made, res.codes()),
                             (STATUS_RETRY_REJECTED, STOP_INVALID_ARGUMENTS, 0, [RETRY_INVALID_LIMIT]), repr(bad))
            self.assertEqual((log, state_view(plan, reg), h["echo"].count), ([], before, 0))

    def test_terminal_tool_execution_failure_is_not_retried(self):
        for name in ("boom", "badout", "typed"):
            reg, h = make_registry()
            plan, log = make_plan(), []
            res = run_retry(plan, req(name), reg, 5, log=log)
            self.assertEqual((res.status, res.stop_reason, res.attempts_made), (STATUS_RETRY_FAILED, STOP_EXECUTION_FAILED, 1), name)
            self.assertEqual((res.final["outcome_kind"], step_of(plan, "s1").status), (OUTCOME_TOOL_EXECUTION_FAILURE, "failed"))
            self.assertEqual((h[name].count, reg.invocation_count(), len(log)), (1, 1, 1))
            self.assertFalse(log[0]["retryable"])

    def test_no_retry_after_step_start_even_when_failure_is_toctou(self):
        reg, h = make_registry(ToctouRegistry)
        plan = make_plan()
        res = run_retry(plan, req("echo"), reg, 5)
        self.assertEqual((res.status, res.stop_reason, res.attempts_made), (STATUS_RETRY_FAILED, STOP_EXECUTION_FAILED, 1))
        self.assertEqual((step_of(plan, "s1").status, h["echo"].count, res.attempts[0]["execution_started"]), ("failed", 0, True))
        self.assertEqual(reg.invocation_count(), 1)          # the started execution is the single (failed) audited invocation

    def test_started_completed_failed_steps_are_never_silently_rerun(self):
        # completed
        reg, h = make_registry()
        plan = make_plan()
        run_retry(plan, req("echo"), reg, 1)
        again = run_retry(plan, req("echo"), reg, 5)
        self.assertEqual((again.stop_reason, again.attempts_made, h["echo"].count, reg.invocation_count()),
                         (STOP_NON_RETRYABLE, 1, 1, 1))
        # failed
        reg, h = make_registry()
        plan = make_plan()
        run_retry(plan, req("boom"), reg, 1)
        again = run_retry(plan, req("echo"), reg, 5)
        self.assertEqual((again.stop_reason, again.attempts_made, h["echo"].count, step_of(plan, "s1").status),
                         (STOP_NON_RETRYABLE, 1, 0, "failed"))
        # in progress
        reg, h = make_registry()
        plan = make_plan()
        start_plan_step(plan, "s1")
        again = run_retry(plan, req("echo"), reg, 5)
        self.assertEqual((again.stop_reason, again.attempts_made, h["echo"].count, step_of(plan, "s1").status),
                         (STOP_NON_RETRYABLE, 1, 0, "in_progress"))
        for r in (again,):
            self.assertFalse(r.attempts[0]["retryable"])

    def test_retry_allow_list_never_retries_unknown_or_malformed_failures(self):
        class Fake:
            def __init__(self, **kw):
                self.execution_called, self.status, self.outcome_kind = False, "rejected", OUTCOME_PRE_REGISTRY_REJECTION
                self.reason, self.failures, self.previous_state = "SOMETHING_NEW", [], "pending"
                self.__dict__.update(kw)

        for fake in (Fake(), Fake(reason=None), Fake(reason="INVALID_BRIDGE_PLAN"), Fake(reason="INVALID_PLAN"),
                     Fake(reason="STEP_NOT_READY", previous_state="failed"), Fake(reason="STEP_NOT_READY", previous_state=None),
                     Fake(reason=PRESTART_CAPABILITY_MAPPING_REJECTED, failures=[]),
                     Fake(reason=PRESTART_CAPABILITY_MAPPING_REJECTED, failures=[{"capability_mapping": "x"}]),
                     Fake(reason=PRESTART_CAPABILITY_MAPPING_REJECTED, failures=[{"capability_mapping": {"status": "invalid_mapping"}}]),
                     Fake(outcome_kind="weird"), Fake(outcome_kind=OUTCOME_REGISTRY_PREFLIGHT_REJECTION, reason="PRESTART_PREFLIGHT_EXCEPTION"),
                     Fake(execution_called=True), Fake(status="completed"), Fake(status="failed")):
            self.assertFalse(is_retryable_prestart_result(fake), vars(fake))
        self.assertTrue(is_retryable_prestart_result(Fake(reason="STEP_NOT_READY")))
        self.assertTrue(is_retryable_prestart_result(Fake(reason=PRESTART_MAPPED_GRANT_NOT_SUPPLIED)))

    def test_mapped_capability_and_registry_failures_stay_prestart_inside_retry(self):
        reg, h = make_registry()
        plan = make_plan()
        res = run_retry(plan, req("needs_cap"), reg, 2, required=["Needs A"], mapping=MAPPING)
        self.assertEqual((res.stop_reason, res.reason, res.attempts_made), (STOP_LIMIT_REACHED, PRESTART_MAPPED_GRANT_NOT_SUPPLIED, 2))
        res = run_retry(plan, req("needs_cap", caps=["cap_a"]), reg, 2, required=["Needs A"], mapping=[])
        self.assertEqual((res.stop_reason, res.reason), (STOP_LIMIT_REACHED, PRESTART_CAPABILITY_MAPPING_REJECTED))
        res = run_retry(plan, req("needs_cap"), reg, 2)
        self.assertEqual((res.final["outcome_kind"], res.final["execution_called"]), (OUTCOME_REGISTRY_PREFLIGHT_REJECTION, False))
        self.assertEqual((h["needs_cap"].count, reg.invocation_count(), step_of(plan, "s1").status), (0, 0, "pending"))


class TestConsistencyAndIsolation(unittest.TestCase):
    def test_plan_tool_retry_and_audit_state_agree_on_success(self):
        reg, h = enable_after_registry(flip_after=1)
        plan, log = make_plan(), []
        res = run_retry(plan, req("off", {"v": 7}), reg, 3, log=log)
        step = step_of(plan, "s1")
        record = reg.get_invocation_history()[-1]
        tool_result = step.output_data["tool_result"]
        self.assertEqual(step.status, res.final["final_state"])
        self.assertEqual(res.final["execution"]["recorded_output"], step.output_data)
        self.assertEqual((tool_result["sequence"], res.final["sequence"], res.attempts[-1]["sequence"], record["sequence"]), (1,) * 4)
        self.assertEqual((tool_result["tool_name"], record["tool_name"], res.attempts[-1]["tool_name"]), ("off",) * 3)
        self.assertEqual(tool_result["output"], record["output"])
        self.assertEqual(reg.invocation_count(), sum(1 for a in res.attempts if a["invocation_recorded"]))
        self.assertEqual(log, res.attempts)

    def test_plan_tool_retry_and_audit_state_agree_on_failure(self):
        reg, h = make_registry()
        plan, log = make_plan(), []
        res = run_retry(plan, req("boom"), reg, 3, log=log)
        step = step_of(plan, "s1")
        record = reg.get_invocation_history()[-1]
        self.assertEqual((step.status, res.final["final_state"]), ("failed", "failed"))
        self.assertEqual((step.output_data["tool_result"]["sequence"], res.final["sequence"], record["sequence"]), (1, 1, 1))
        self.assertEqual((step.output_data["tool_result"]["outcome_code"], record["outcome_code"]), (record["outcome_code"],) * 2)
        self.assertEqual((res.status, res.stop_reason, res.reason), (STATUS_RETRY_FAILED, STOP_EXECUTION_FAILED, res.final["reason"]))
        self.assertFalse(record["ok"])

    def test_caller_owned_attempt_log_isolation(self):
        reg, h = make_registry()
        plan = make_plan()
        log = [{"pre-existing": True}]
        res = run_retry(plan, req("off"), reg, 2, log=log)
        self.assertEqual(len(log), 3)
        self.assertEqual(log[0], {"pre-existing": True})                   # documented append only; caller data kept
        log[1]["attempt"] = 999
        log[1]["failures"].append("tamper")
        log.clear()
        self.assertEqual([a["attempt"] for a in res.attempts], [1, 2])     # result holds independent copies
        self.assertNotIn("tamper", res.attempts[0]["failures"])
        snap = res.to_dict()
        snap["attempts"][0]["attempt"] = 42
        snap["final"]["status"] = "hacked"
        self.assertEqual((res.attempts[0]["attempt"], res.final["status"]), (1, "rejected"))
        # no hidden module state: a second call with a fresh log sees only its own attempts
        fresh = []
        run_retry(make_plan(), req("off"), reg, 2, log=fresh)
        self.assertEqual([a["attempt"] for a in fresh], [1, 2])
        self.assertEqual(run_retry(make_plan(), req("off"), reg, 1).attempts_made, 1)
        for module in (retry_mod, exec_mod, bridge_mod, mapping_mod):
            self.assertEqual([n for n, v in vars(module).items() if isinstance(v, (list, dict, set)) and not n.startswith("__")], [])

    def test_no_api_mutates_caller_owned_inputs(self):
        for kind in ("mapped_ok", "mapped_rejected", "preflight_rejected", "failure", "retry_success", "retry_limit"):
            reg, h = make_registry()
            plan = make_plan()
            request = req("needs_cap", {"a": {"b": [1]}}, perms=["network"] if False else None, caps=["cap_a"])
            required, mapping = ["Needs A"], copy.deepcopy(MAPPING)
            req_args = copy.deepcopy(request.to_registry_arguments())
            required_before, mapping_before = copy.deepcopy(required), copy.deepcopy(mapping)
            plan_before = snapshot(plan)
            if kind == "mapped_ok":
                execute_plan_tool_step_mapped(plan, "s1", request, reg, required, mapping)
            elif kind == "mapped_rejected":
                execute_plan_tool_step_mapped(plan, "s1", request, reg, ["nope"], mapping)
            elif kind == "preflight_rejected":
                execute_plan_tool_step_preflighted(plan, "s1", req("off"), reg)
                plan_before = snapshot(plan)
            elif kind == "failure":
                execute_plan_tool_step_preflighted(plan, "s1", req("boom"), reg)
            elif kind == "retry_success":
                run_retry(plan, request, reg, 3, required=required, mapping=mapping, log=[])
            else:
                run_retry(plan, req("off"), reg, 3, log=[])
            self.assertEqual(request.to_registry_arguments(), req_args, kind)
            self.assertEqual((required, mapping), (required_before, mapping_before), kind)
            if kind in ("mapped_rejected", "preflight_rejected", "retry_limit"):
                self.assertEqual(snapshot(plan), plan_before, kind)          # rejected paths leave the plan untouched
        # ToolRequest is immutable and caller-owned
        request = req("echo", {"a": 1})
        with self.assertRaises((AttributeError, TypeError)):
            request.name = "other"
        arguments = request.to_registry_arguments()
        arguments["tool_input"]["a"] = 999 if "tool_input" in arguments else None
        self.assertEqual(request.to_registry_arguments()["tool_input" if "tool_input" in arguments else "name"],
                         {"a": 1} if "tool_input" in arguments else "echo")

    def test_step_transitions_are_the_only_plan_mutation(self):
        reg, h = make_registry()
        plan = make_plan("s1", "s2", chain=True)
        before = snapshot(plan)
        run_retry(plan, req("echo"), reg, 2, step_id="s1")
        after = snapshot(plan)
        self.assertNotEqual(before, after)
        self.assertEqual(step_of(plan, "s2").status, "pending")
        self.assertEqual((step_of(plan, "s1").status, reg.invocation_count()), ("completed", 1))


class TestInvalidInputs(unittest.TestCase):
    def test_invalid_arguments_never_start_or_retry_execution(self):
        for kwargs, code in (({"step_id": "ghost"}, "UNKNOWN_BRIDGE_STEP"), ({"step_id": ""}, "INVALID_BRIDGE_STEP_ID"),
                             ({"step_id": 7}, "INVALID_BRIDGE_STEP_ID")):
            reg, h = make_registry()
            plan = make_plan()
            res = run_retry(plan, req("echo"), reg, 4, **kwargs)
            self.assertEqual((res.stop_reason, res.attempts_made, res.reason), (STOP_NON_RETRYABLE, 1, code))
            self.assertEqual((h["echo"].count, reg.invocation_count(), step_of(plan, "s1").status), (0, 0, "pending"))
        reg, h = make_registry()
        for plan_arg, request_arg, reg_arg, code in (("no plan", req("echo"), reg, "INVALID_BRIDGE_PLAN"),
                                                     (make_plan(), "no request", reg, "INVALID_BRIDGE_REQUEST"),
                                                     (make_plan(), req("echo"), object(), "INVALID_BRIDGE_REGISTRY")):
            res = execute_plan_tool_step_with_retry(plan_arg, "s1", request_arg, reg_arg, 4)
            self.assertEqual((res.stop_reason, res.attempts_made, code in res.codes()), (STOP_NON_RETRYABLE, 1, True))
        self.assertEqual((h["echo"].count, reg.invocation_count()), (0, 0))

    def test_invalid_retry_and_mapping_arguments_make_zero_attempts(self):
        reg, h = make_registry()
        plan = make_plan()
        self.assertEqual(run_retry(plan, req("echo"), reg, 3, log="nope").codes(), [RETRY_INVALID_LOG])
        for required, mapping in ((["Needs A"], None), (None, MAPPING)):
            res = run_retry(plan, req("echo"), reg, 3, required=required, mapping=mapping)
            self.assertEqual((res.codes(), res.attempts_made), ([RETRY_INVALID_MAPPING_PAIR], 0))
        bad = execute_plan_tool_step_preflighted(plan, "s1", req("echo"), reg, rejection_log="x")
        self.assertEqual((bad.status, bad.execution_called, bad.preflight_called), ("rejected", False, False))
        self.assertEqual((h["echo"].count, reg.invocation_count(), step_of(plan, "s1").status), (0, 0, "pending"))

    def test_invalid_tool_input_is_rejected_before_any_step_start(self):
        for value in (float("nan"), float("inf"), [1], "text", None, {"k": {1, 2}}):
            built = create_tool_request("echo", value, None, None, False)
            self.assertFalse(built.ok, repr(value))                          # rejected by the Section 5 request factory
        reg, h = make_registry()
        plan = make_plan()
        forged = object.__new__(type(req("echo")))                           # a ToolRequest forged without its factory
        res = run_retry(plan, forged, reg, 4)
        self.assertEqual((res.status, res.stop_reason, res.attempts_made), (STATUS_RETRY_REJECTED, STOP_NON_RETRYABLE, 1))
        self.assertEqual((h["echo"].count, reg.invocation_count(), step_of(plan, "s1").status), (0, 0, "pending"))

    def test_plan_not_ready_is_pending_only_retryable_and_invalid_plan_is_not(self):
        reg, h = make_registry()
        plan = make_plan("a", "b", chain=True)
        res = run_retry(plan, req("echo"), reg, 3, step_id="b")               # dependency 'a' not completed
        self.assertEqual((res.stop_reason, res.attempts_made, res.reason), (STOP_LIMIT_REACHED, 3, "STEP_NOT_READY"))
        self.assertEqual((h["echo"].count, reg.invocation_count(), step_of(plan, "b").status), (0, 0, "pending"))
        plan.steps[0].dependencies = ["ghost"]
        res = run_retry(plan, req("echo"), reg, 3, step_id="a")
        self.assertEqual((res.stop_reason, res.attempts_made, res.reason), (STOP_NON_RETRYABLE, 1, "INVALID_PLAN"))


class TestNoInvocationBypass(unittest.TestCase):
    def test_retry_never_calls_a_handler_or_bypasses_preflight(self):
        calls = []
        reg, h = make_registry(spy_registry_class(calls))
        run_retry(make_plan(), req("echo"), reg, 2)
        self.assertEqual((calls[0], calls.count("preflight"), calls.count("execute_request")), ("preflight", 1, 1))   # preflight, then one execution
        calls.clear()
        run_retry(make_plan(), req("off"), reg, 3)
        self.assertEqual(calls, ["preflight"] * 3)                          # rejections never reach any execution entry point
        calls.clear()
        run_retry(make_plan(), req("boom"), reg, 3)
        self.assertEqual((calls[0], calls.count("preflight"), calls.count("execute_request")), ("preflight", 1, 1))   # no second attempt

    def test_bridge_is_stateless_and_deterministic(self):
        outcomes = []
        for _ in range(2):
            reg, h = make_registry()
            plan = make_plan()
            request = req("echo", {"z": 1})
            outcomes.append(bridge_mod.execute_tool_step(plan, "s1", request, reg).to_dict())
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(outcomes[0]["sequence"], 1)
        again = bridge_mod.execute_tool_step(make_plan(), "s1", req("echo"), make_registry()[0])
        self.assertEqual(again.sequence, 1)                                 # no module counter carried over

    def test_capability_mapping_is_explicit_and_never_inferred(self):
        self.assertEqual(list(inspect.signature(mapping_mod.map_required_capabilities).parameters), ["required_capabilities", "mapping"])
        self.assertFalse(mapping_mod.map_required_capabilities(["Needs A"], []).ok)
        self.assertFalse(mapping_mod.map_required_capabilities(["needs a"], MAPPING).ok)          # no case folding
        self.assertFalse(mapping_mod.map_required_capabilities(["Needs A "], MAPPING).ok)         # no trimming
        self.assertTrue(mapping_mod.map_required_capabilities(["Needs A"], MAPPING).ok)
        # a step's own required_capabilities are never read: a plan step naming a capability maps nothing by itself
        reg, h = make_registry()
        plan = make_plan()
        plan.steps[0].required_capabilities = ["Needs A"]
        res = execute_plan_tool_step_preflighted(plan, "s1", req("needs_cap"), reg)
        self.assertEqual((res.outcome_kind, h["needs_cap"].count), (OUTCOME_REGISTRY_PREFLIGHT_REJECTION, 0))

    def test_section5_stays_the_final_authority_for_mapped_grants(self):
        reg, h = make_registry()
        plan = make_plan()
        res = execute_plan_tool_step_mapped(plan, "s1", req("echo", caps=["cap_a"]), reg, ["Needs A"], MAPPING)
        self.assertTrue(res.ok)                                             # extra grants stay; nothing is stripped
        reg, h = make_registry()
        plan = make_plan()
        wrong = [{"capability": "Needs A", "grants": ["other_cap"]}]
        res = execute_plan_tool_step_mapped(plan, "s1", req("needs_cap", caps=["other_cap"]), reg, ["Needs A"], wrong)
        self.assertEqual((res.outcome_kind, step_of(plan, "s1").status, h["needs_cap"].count),
                         (OUTCOME_REGISTRY_PREFLIGHT_REJECTION, "pending", 0))     # mapping is translation, Section 5 decides


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _parse(rel):
    return ast.parse(_read(os.path.join(PY_ROOT, rel)))


def _imports(path):
    tree = _parse(path)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append(node.module or "")
    return found


class TestSourceAndDependencyGuards(unittest.TestCase):
    def test_only_the_bridge_imports_tools_and_only_section6_modules_import_section6(self):
        offenders, consumers = [], []
        for path in glob.glob(os.path.join(PY_ROOT, "**", "*.py"), recursive=True):
            rel = os.path.relpath(path, PY_ROOT).replace(os.sep, "/")
            if rel.startswith("tests/") or rel.startswith("tools/"):
                continue
            for mod in _imports(rel):
                if mod.split(".")[0] == "tools":
                    offenders.append(rel)
                if "tool_step" in mod or "tool_capability_mapping" in mod:
                    consumers.append(rel)
        self.assertEqual(sorted(set(offenders)), ["agent/tool_step_intent.py", "planning/tool_step_bridge.py"])      # Prompt 719-A: the caller-side intent adapter (imports only tools.tool_request)
        self.assertEqual(sorted(set(consumers)), ["agent/agent_loop.py",      # Prompt 719-C: exact-path exemption - the routed Agent Loop entry point
                                                  "agent/tool_step_runner.py", "planning/tool_step_agent_adapter.py", "planning/tool_step_dispatch.py",
                                                  "planning/tool_step_executor.py",
                                                  "planning/tool_step_retry.py"])       # Prompt 714: the adapter is the third Section 6 consumer; Prompt 717: the dispatch layer imports only the 716 resolver

    def test_tools_package_imports_nothing_from_planning_or_agent_layers(self):
        for path in glob.glob(os.path.join(PY_ROOT, "tools", "*.py")):
            rel = os.path.relpath(path, PY_ROOT)
            for mod in _imports(rel):
                self.assertNotIn(mod.split(".")[0], ("planning", "agent", "core", "execution", "ael", "reasoning", "interface"), rel)

    def test_section6_modules_have_exact_intended_internal_imports(self):
        self.assertEqual(sorted(set(_imports("planning/tool_step_retry.py")) - {""}), ["planning.tool_step_executor"])
        self.assertEqual(_imports("planning/tool_capability_mapping.py"), ["re"])
        self.assertEqual(sorted(_imports("planning/tool_step_bridge.py")),
                         ["copy", "planning.plan", "tools.in_process_tool_registry", "tools.tool_request"])
        self.assertEqual(sorted(_imports("planning/tool_step_executor.py")),
                         ["copy", "planning.plan", "planning.plan_builder", "planning.plan_step_execution", "planning.plan_validation",
                          "planning.tool_capability_mapping", "planning.tool_step_bridge"])

    def test_no_persistence_network_threading_clock_or_randomness_in_section6(self):
        banned = {"sqlite3", "socket", "http", "urllib", "requests", "threading", "multiprocessing", "asyncio", "subprocess", "sched",
                  "time", "datetime", "random", "os", "pickle", "shelve", "json", "logging", "concurrent", "queue", "secrets", "uuid"}
        for path in SECTION6_MODULES:
            for mod in _imports(path):
                self.assertNotIn(mod.split(".")[0], banned, path)

    def test_retry_module_never_touches_handlers_registry_bridge_or_transitions(self):
        tree = _parse("planning/tool_step_retry.py")
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        for forbidden in ("handler", "execute_request", "execute", "invoke", "preflight", "register", "enable", "disable"):
            self.assertNotIn(forbidden, attrs)
        for forbidden in ("start_plan_step", "complete_plan_step", "fail_plan_step", "execute_tool_step", "validate_plan",
                          "InProcessToolRegistry", "eval", "exec", "compile", "__import__"):
            self.assertNotIn(forbidden, names)
        called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertLessEqual({"execute_plan_tool_step_mapped", "execute_plan_tool_step_preflighted"}, called)

    def test_only_the_bridge_reaches_the_registry_execution_entry_point(self):
        for path in ("planning/tool_step_executor.py", "planning/tool_step_retry.py", "planning/tool_capability_mapping.py"):
            tree = _parse(path)
            attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
            self.assertNotIn("execute_request", attrs, path)
            self.assertNotIn("handler", attrs, path)
        bridge = _parse("planning/tool_step_bridge.py")
        self.assertEqual(sum(1 for n in ast.walk(bridge) if isinstance(n, ast.Attribute) and n.attr == "execute_request"), 1)
        executor = _parse("planning/tool_step_executor.py")
        self.assertEqual(sum(1 for n in ast.walk(executor) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                             and n.func.attr == "preflight"), 1)

    def test_section6_is_not_wired_into_legacy_stack_agent_loop_or_process_input(self):
        for path in glob.glob(os.path.join(PY_ROOT, "**", "*.py"), recursive=True):
            rel = os.path.relpath(path, PY_ROOT).replace(os.sep, "/")
            if rel.startswith("tests/") or rel in SECTION6_MODULES or rel == "planning/tool_step_agent_adapter.py" or rel == "agent/tool_step_runner.py":     # Prompt 719-B: exact-path exemption for the caller-side runner; Prompt 714
                continue
            text = _read(path)
            self.assertNotIn("execute_plan_tool_step", text, rel)
            self.assertNotIn("execute_tool_step", text, rel)
            self.assertNotIn("map_required_capabilities", text, rel)
        for path in SECTION6_MODULES:
            for mod in _imports(path):
                self.assertFalse(mod.startswith(("execution", "agent", "core", "ael")), (path, mod))

    def test_two_historical_execution_stacks_remain_separate(self):
        legacy = ("execution/execution_engine.py", "execution/plan_execution_controller.py")
        step_layer = ("planning/plan_step_execution.py", "planning/plan_step_orchestration.py", "planning/plan_runner.py")
        for path in legacy:
            self.assertTrue(os.path.exists(os.path.join(PY_ROOT, path)), path)
            for mod in _imports(path):
                self.assertNotIn("plan_step_execution", mod)
                self.assertNotIn("tool_step", mod)
        for path in step_layer:
            for mod in _imports(path):
                self.assertNotIn("execution_engine", mod)
                self.assertNotIn("plan_execution_controller", mod)
                self.assertFalse(mod.startswith("execution"), (path, mod))

    def test_section4_and_section5_production_contracts_are_unchanged(self):
        files = sorted(f for f in glob.glob(os.path.join(PY_ROOT, "planning", "*.py")) + glob.glob(os.path.join(PY_ROOT, "tools", "*.py"))
                       if not any(k in f for k in ("tool_step_", "tool_capability_mapping")))
        digest = hashlib.sha256()
        for f in files:
            rel = os.path.relpath(f, PY_ROOT).replace(os.sep, "/")
            with open(f, "rb") as fh:
                digest.update(rel.encode() + b"\0" + hashlib.sha256(fh.read()).digest())
        self.assertEqual(digest.hexdigest(), FROZEN_SECTION45_DIGEST)
        self.assertEqual(len(files), 31)

    def test_public_section6_signatures_are_frozen(self):
        sig = lambda fn: list(inspect.signature(fn).parameters)
        self.assertEqual(sig(bridge_mod.execute_tool_step), ["plan", "step_id", "request", "registry"])
        self.assertEqual(sig(exec_mod.execute_plan_tool_step), ["plan", "step_id", "request", "registry"])
        self.assertEqual(sig(exec_mod.execute_plan_tool_step_preflighted), ["plan", "step_id", "request", "registry", "rejection_log"])
        self.assertEqual(sig(exec_mod.execute_plan_tool_step_mapped),
                         ["plan", "step_id", "request", "registry", "required_capabilities", "capability_mapping", "rejection_log"])
        self.assertEqual(sig(execute_plan_tool_step_with_retry),
                         ["plan", "step_id", "request", "registry", "max_attempts", "required_capabilities", "capability_mapping",
                          "attempt_log"])


class TestAcceptanceRecordAndDatabase(unittest.TestCase):
    def test_pristine_database_hash(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)

    def test_acceptance_document_records_hand_over_hazards(self):
        path = os.path.join(DOCS_ROOT, "section6_final_acceptance_prompt712.md")
        self.assertTrue(os.path.exists(path), path)
        text = _read(path).lower()
        for needle in ("ready", "legacy", "executionengine", "planexecutioncontroller", "f3", "nan",
                       "re-running a failed step", "no production defect"):
            self.assertIn(needle, text, needle)


if __name__ == "__main__":
    unittest.main()
