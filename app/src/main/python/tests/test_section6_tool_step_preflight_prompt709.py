"""Prompt 709 - Section 6 pre-start tool preflight and rejection recording (`planning/tool_step_executor.py`).

Focused tests for `execute_plan_tool_step_preflighted(plan, step_id, request, registry, rejection_log=None)`. It asks the Section 5
registry (`registry.preflight(**request.to_registry_arguments())`) BEFORE `start_plan_step()`, and only after a passed preflight
makes exactly one call of the unchanged `execute_plan_tool_step()`. Resolves Prompt 706 hazards H3 and H4; F2 stays open and the
function is not wired into process_input(), the Agent Loop or the legacy execution stack.
"""
import ast
import hashlib
import inspect
import os
import unittest

from planning import tool_step_executor as exec_mod
from planning.plan import Plan, PlanStep
from planning.plan_validation import validate_plan
from planning.tool_step_bridge import (BRIDGE_INVALID_PLAN, BRIDGE_INVALID_REGISTRY, BRIDGE_INVALID_REQUEST,
                                       BRIDGE_INVALID_STEP_ID, BRIDGE_UNKNOWN_STEP)
from planning.tool_step_executor import (OUTCOME_COMPLETED, OUTCOME_PRE_REGISTRY_REJECTION,
                                         OUTCOME_REGISTRY_PREFLIGHT_REJECTION, OUTCOME_TOOL_EXECUTION_FAILURE,
                                         PRESTART_INVALID_REJECTION_LOG, PRESTART_INVALID_REQUEST,
                                         PRESTART_PREFLIGHT_EXCEPTION, REJECTION_RECORD_TYPE, STATUS_TOOL_STEP_COMPLETED,
                                         STATUS_TOOL_STEP_FAILED, STATUS_TOOL_STEP_REJECTED, TOOL_STEP_INVALID_PLAN,
                                         TOOL_STEP_TOOL_FAILED, PreflightedToolStepResult, execute_plan_tool_step,
                                         execute_plan_tool_step_preflighted)
from tools.in_process_tool_registry import (InProcessToolRegistry, TOOL_CAPABILITY_MISSING, TOOL_CONFIRMATION_REQUIRED,
                                            TOOL_DISABLED, TOOL_INVALID_INPUT, TOOL_PERMISSION_DENIED, TOOL_UNKNOWN)
from tools.tool_request import ToolRequest
from tests.test_section6_tool_step_executor_prompt708 import Counting, make_plan, make_registry, req, snapshot, step_of

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"

RESULT_KEYS = {"ok", "status", "outcome_kind", "step_id", "tool_name", "previous_state", "final_state", "preflight_called",
               "preflight", "execution_called", "execution", "reason", "failures", "rejection_record", "sequence"}
RECORD_KEYS = {"record_type", "rejection_kind", "step_id", "tool_name", "codes", "failures", "preflight",
               "invocation_recorded", "sequence"}
PREFLIGHT_KEYS = {"tool_name", "tool_exists", "tool_enabled", "authorization_decision", "authorization_accepted",
                  "required_permissions", "granted_permissions", "confirmed", "required_capabilities", "granted_capabilities",
                  "missing_capabilities", "input_valid", "preflight_status", "outcome_code", "failure_codes", "failures", "ok"}


def forged_request(name="echo", tool_input=None):
    """A ToolRequest built WITHOUT create_tool_request() (all slots set by hand), e.g. carrying an input the registry rejects."""
    forged = object.__new__(ToolRequest)
    for key, value in (("_name", name), ("_input", {"a": {1, 2}} if tool_input is None else tool_input),
                       ("_granted_permissions", ()), ("_granted_capabilities", ()), ("_confirmed", False)):
        object.__setattr__(forged, key, value)
    return forged


def spy_registry_class(calls):
    class Spy(InProcessToolRegistry):
        def preflight(self, *a, **k):
            calls.append("preflight")
            return super().preflight(*a, **k)

        def execute_request(self, request):
            calls.append("execute_request")
            return super().execute_request(request)

        def execute(self, *a, **k):
            calls.append("execute")
            return super().execute(*a, **k)

        def invoke(self, *a, **k):
            calls.append("invoke")
            return super().invoke(*a, **k)
    return Spy


def registry_state(reg):
    return (reg.list_names(), [reg.is_enabled(n) for n in reg.list_names()], reg.invocation_count(),
            reg.get_invocation_history())


def run(plan, request, reg, step_id="s1", log=None):
    return execute_plan_tool_step_preflighted(plan, step_id, request, reg, log)


class TestPreflightSuccess(unittest.TestCase):
    def test_preflight_success_then_one_normal_execution_completes_the_step(self):
        calls = []
        reg, h = make_registry(spy_registry_class(calls))
        plan = make_plan()
        res = run(plan, req("echo", {"a": [1]}), reg)
        self.assertIsInstance(res, PreflightedToolStepResult)
        self.assertTrue(res.ok)
        self.assertEqual((res.status, res.outcome_kind, res.previous_state, res.final_state),
                         (STATUS_TOOL_STEP_COMPLETED, OUTCOME_COMPLETED, "pending", "completed"))
        self.assertEqual((res.preflight_called, res.execution_called, res.reason, res.failures, res.rejection_record),
                         (True, True, None, [], None))
        self.assertTrue(res.preflight["ok"])
        self.assertEqual(calls, ["preflight", "execute_request", "execute", "invoke"])      # one preflight, one execution
        self.assertEqual(h["echo"].count, 1)
        self.assertEqual(reg.invocation_count(), 1)
        self.assertEqual((res.sequence, res.execution["tool_result"]["sequence"]), (1, 1))
        step = step_of(plan, "s1")
        self.assertEqual((step.status, step.output_data["tool_result"]["output"]), ("completed", {"echo": {"a": [1]}}))
        self.assertTrue(validate_plan(plan).valid)

    def test_execution_path_is_identical_to_the_unchanged_adapter(self):
        reg_a, _ = make_registry()
        reg_b, _ = make_registry()
        plan_a, plan_b = make_plan(), make_plan()
        pre = run(plan_a, req("echo", {"k": 1}), reg_a)
        plain = execute_plan_tool_step(plan_b, "s1", req("echo", {"k": 1}), reg_b)
        self.assertEqual(pre.execution, plain.to_dict())
        self.assertEqual(snapshot(plan_a), snapshot(plan_b))
        self.assertEqual(reg_a.get_invocation_history(), reg_b.get_invocation_history())

    def test_preflight_runs_before_the_step_is_started(self):
        seen = []

        class Watch(InProcessToolRegistry):
            def preflight(self, *a, **k):
                seen.append(step_of(plan, "s1").status)
                return super().preflight(*a, **k)
        reg, _ = make_registry(Watch)
        plan = make_plan()
        run(plan, req("echo"), reg)
        self.assertEqual(seen, ["pending"])

    def test_preflight_receives_exactly_the_request_arguments(self):
        got = []

        class Watch(InProcessToolRegistry):
            def preflight(self, **k):
                got.append(k)
                return super().preflight(**k)
        reg, _ = make_registry(Watch)
        request = req("net", {"q": 1}, perms=["network"], caps=["cap_z"], confirmed=True)
        run(make_plan(), request, reg)
        self.assertEqual(got, [request.to_registry_arguments()])

    def test_dependent_step_runs_after_its_dependency(self):
        reg, _ = make_registry()
        plan = make_plan("a", "b", chain=True)
        self.assertTrue(run(plan, req("echo"), reg, "a").ok)
        self.assertTrue(run(plan, req("echo"), reg, "b").ok)
        self.assertEqual([s.status for s in plan.steps], ["completed", "completed"])


class TestRegistryPreflightRejection(unittest.TestCase):
    """Section 5 decides; the executor only passes the verdict through and records it. Each case: step never started."""

    CASES = (
        ("permission", lambda: req("net"), TOOL_PERMISSION_DENIED),
        ("confirmation", lambda: req("confirm", perms=[]), TOOL_CONFIRMATION_REQUIRED),
        ("capability", lambda: req("needs_cap"), TOOL_CAPABILITY_MISSING),
        ("input", lambda: forged_request("echo"), TOOL_INVALID_INPUT),
        ("unknown", lambda: req("does_not_exist"), TOOL_UNKNOWN),
        ("disabled", lambda: req("off"), TOOL_DISABLED),
    )

    def check(self, request, code):
        calls = []
        reg, h = make_registry(spy_registry_class(calls))
        plan = make_plan()
        before_plan, before_reg = snapshot(plan), registry_state(reg)
        log = []
        res = run(plan, request, reg, log=log)
        self.assertFalse(res.ok)
        self.assertEqual((res.status, res.outcome_kind), (STATUS_TOOL_STEP_REJECTED, OUTCOME_REGISTRY_PREFLIGHT_REJECTION))
        self.assertEqual((res.previous_state, res.final_state, res.preflight_called, res.execution_called, res.execution),
                         ("pending", "pending", True, False, None))
        self.assertEqual((res.reason, res.codes()), (code, [code]))
        self.assertEqual(snapshot(plan), before_plan)                      # no plan mutation
        self.assertEqual(step_of(plan, "s1").status, "pending")            # never left in_progress
        self.assertEqual(calls, ["preflight"])                             # no execute_request/execute/invoke
        self.assertTrue(all(c.count == 0 for c in h.values()))             # no handler call
        self.assertEqual(registry_state(reg), before_reg)                  # no invocation-history entry
        self.assertEqual(reg.invocation_count(), 0)
        self.assertIsNone(res.sequence)
        self.assertEqual(log, [res.rejection_record])
        return res, reg

    def test_permission_confirmation_capability_input_unknown_and_disabled_rejections(self):
        for label, build, code in self.CASES:
            with self.subTest(label):
                self.check(build(), code)

    def test_complete_preflight_information_is_preserved(self):
        for label, build, code in self.CASES:
            with self.subTest(label):
                request = build()
                res, reg = self.check(request, code)
                expected = reg.preflight(**request.to_registry_arguments()).to_dict()
                self.assertEqual(res.preflight, expected)
                self.assertEqual(set(res.preflight), PREFLIGHT_KEYS)
                self.assertEqual(res.failures, expected["failures"])
                self.assertEqual(res.rejection_record["preflight"], expected)
                self.assertEqual(res.rejection_record["failures"], expected["failures"])
                self.assertFalse(res.preflight["ok"])
                self.assertEqual(res.preflight["preflight_status"], "rejected")

    def test_detailed_failure_fields_survive(self):
        reg, _ = make_registry()
        res = run(make_plan(), req("net"), reg)
        self.assertEqual(res.failures[0]["missing_permissions"], ["network"])
        self.assertEqual((res.preflight["authorization_decision"], res.preflight["required_permissions"]), ("denied", ["network"]))
        res = run(make_plan(), req("needs_cap", caps=["other"]), reg)
        self.assertEqual((res.failures[0]["missing_capabilities"], res.preflight["granted_capabilities"]), (["cap_a"], ["other"]))
        res = run(make_plan(), req("off"), reg)
        self.assertEqual((res.preflight["tool_exists"], res.preflight["tool_enabled"]), (True, False))
        res = run(make_plan(), req("nope"), reg)
        self.assertEqual((res.preflight["tool_exists"], res.preflight["tool_enabled"]), (False, False))

    def test_a_rejected_request_can_be_retried_by_the_caller_only_after_the_registry_state_changes(self):
        reg, h = make_registry()
        plan = make_plan()
        self.assertEqual(run(plan, req("off"), reg).outcome_kind, OUTCOME_REGISTRY_PREFLIGHT_REJECTION)
        reg.enable("off")
        self.assertTrue(run(plan, req("off"), reg).ok)          # the step was never consumed by the rejection
        self.assertEqual(h["off"].count, 1)

    def test_registry_rejection_record_never_claims_an_invocation(self):
        reg, _ = make_registry()
        res = run(make_plan(), req("net"), reg)
        rec = res.rejection_record
        self.assertEqual(set(rec), RECORD_KEYS)
        self.assertEqual((rec["record_type"], rec["rejection_kind"], rec["invocation_recorded"], rec["sequence"]),
                         (REJECTION_RECORD_TYPE, OUTCOME_REGISTRY_PREFLIGHT_REJECTION, False, None))
        self.assertEqual((rec["step_id"], rec["tool_name"], rec["codes"]), ("s1", "net", [TOOL_PERMISSION_DENIED]))


class TestPreRegistryRejection(unittest.TestCase):
    def check(self, plan, step_id, request, registry, code, *, log=None):
        calls = []
        before = snapshot(plan) if isinstance(plan, Plan) else None
        if isinstance(registry, InProcessToolRegistry):
            registry_before = registry_state(registry)
        log = [] if log is None else log
        res = execute_plan_tool_step_preflighted(plan, step_id, request, registry, log)
        self.assertEqual((res.status, res.outcome_kind), (STATUS_TOOL_STEP_REJECTED, OUTCOME_PRE_REGISTRY_REJECTION))
        self.assertEqual((res.preflight_called, res.execution_called, res.preflight, res.execution, res.sequence),
                         (False, False, None, None, None))
        self.assertEqual(res.reason, code)
        self.assertIn(code, res.codes())
        self.assertEqual(res.final_state, res.previous_state)
        if before is not None:
            self.assertEqual(snapshot(plan), before)
        if isinstance(registry, InProcessToolRegistry):
            self.assertEqual(registry_state(registry), registry_before)
        self.assertEqual(log, [res.rejection_record])
        rec = res.rejection_record
        self.assertEqual((rec["rejection_kind"], rec["invocation_recorded"], rec["sequence"], rec["preflight"]),
                         (OUTCOME_PRE_REGISTRY_REJECTION, False, None, None))
        del calls
        return res

    def test_invalid_request_objects_are_rejected_before_the_registry(self):
        for bad in (None, "echo", {"name": "echo"}, 5, object()):
            with self.subTest(repr(bad)):
                calls = []
                reg, h = make_registry(spy_registry_class(calls))
                self.check(make_plan(), "s1", bad, reg, BRIDGE_INVALID_REQUEST)
                self.assertEqual(calls, [])
                self.assertTrue(all(c.count == 0 for c in h.values()))

    def test_forged_tool_request_without_slots_is_rejected_before_the_registry(self):
        calls = []
        reg, _ = make_registry(spy_registry_class(calls))
        res = self.check(make_plan(), "s1", object.__new__(ToolRequest), reg, PRESTART_INVALID_REQUEST)
        self.assertEqual((calls, res.tool_name), ([], None))

    def test_invalid_bridge_arguments_are_rejected_before_the_registry(self):
        calls = []
        reg, _ = make_registry(spy_registry_class(calls))
        self.check("not a plan", "s1", req("echo"), reg, BRIDGE_INVALID_PLAN)
        self.check(make_plan(), 5, req("echo"), reg, BRIDGE_INVALID_STEP_ID)
        self.check(make_plan(), "  ", req("echo"), reg, BRIDGE_INVALID_STEP_ID)
        self.check(make_plan(), None, req("echo"), reg, BRIDGE_INVALID_STEP_ID)
        self.check(make_plan(), "ghost", req("echo"), reg, BRIDGE_UNKNOWN_STEP)
        self.assertEqual(calls, [])

    def test_all_bridge_argument_problems_are_reported_at_once_in_argument_order(self):
        res = self.check(None, 3, "x", object(), BRIDGE_INVALID_PLAN)
        self.assertEqual(res.codes(), [BRIDGE_INVALID_PLAN, BRIDGE_INVALID_STEP_ID, BRIDGE_INVALID_REQUEST,
                                       BRIDGE_INVALID_REGISTRY])

    def test_invalid_registry_object_is_rejected_and_its_preflight_is_never_touched(self):
        touched = []

        class Impostor:
            def preflight(self, **k):
                touched.append(k)

            def execute_request(self, r):
                touched.append(r)
        for bad in (None, Impostor(), "registry", {}):
            with self.subTest(repr(bad)[:20]):
                self.check(make_plan(), "s1", req("echo"), bad, BRIDGE_INVALID_REGISTRY)
        self.assertEqual(touched, [])

    def test_invalid_plan_and_step_context_pass_the_section_4_verdicts_through(self):
        calls = []
        reg, _ = make_registry(spy_registry_class(calls))
        res = self.check(make_plan(authorized=False), "s1", req("echo"), reg, "EXECUTION_NOT_AUTHORIZED")
        self.assertEqual((res.previous_state, res.final_state), ("pending", "pending"))
        blocked = make_plan("a", "b", chain=True)
        res = self.check(blocked, "b", req("echo"), reg, "STEP_NOT_READY")
        self.assertEqual(step_of(blocked, "a").status, "pending")
        done = make_plan()
        self.assertTrue(run(done, req("echo"), reg).ok)
        calls.clear()
        self.check(done, "s1", req("echo"), reg, "STEP_NOT_READY")          # a finished step is not started again
        self.assertEqual(calls, [])

    def test_structurally_invalid_plan_is_rejected_with_its_issues(self):
        calls = []
        reg, _ = make_registry(spy_registry_class(calls))
        plan = make_plan("a", "b")
        plan.steps[1].dependencies = ["a", "a"]
        if validate_plan(plan).valid:
            plan = make_plan("a")
            plan.steps.append(PlanStep("a", "duplicate id"))
        self.assertFalse(validate_plan(plan).valid)
        res = self.check(plan, "a", req("echo"), reg, TOOL_STEP_INVALID_PLAN)
        self.assertTrue(res.failures[0]["issues"])
        self.assertEqual(calls, [])

    def test_step_context_is_judged_before_the_registry_is_asked(self):
        calls = []
        reg, _ = make_registry(spy_registry_class(calls))
        # the tool would also be rejected by Section 5, but the plan context is reported first and the registry is not asked
        res = self.check(make_plan(authorized=False), "s1", req("off"), reg, "EXECUTION_NOT_AUTHORIZED")
        self.assertEqual(calls, [])
        self.assertEqual(res.outcome_kind, OUTCOME_PRE_REGISTRY_REJECTION)

    def test_invalid_rejection_log_is_a_pre_registry_rejection(self):
        calls = []
        reg, _ = make_registry(spy_registry_class(calls))
        plan = make_plan()
        for bad in ("log", {}, (), 3):
            with self.subTest(repr(bad)):
                res = execute_plan_tool_step_preflighted(plan, "s1", req("echo"), reg, bad)
                self.assertEqual((res.outcome_kind, res.reason), (OUTCOME_PRE_REGISTRY_REJECTION, PRESTART_INVALID_REJECTION_LOG))
                self.assertEqual(step_of(plan, "s1").status, "pending")
        self.assertEqual(calls, [])

    def test_pre_registry_rejection_never_fabricates_an_audit_sequence(self):
        reg, _ = make_registry()
        log = []
        for args in (("s1", None), ("s1", "x"), ("ghost", req("echo"))):
            run(make_plan(), args[1], reg, args[0], log)
        self.assertEqual(len(log), 3)
        for rec in log:
            self.assertEqual((rec["sequence"], rec["invocation_recorded"], rec["preflight"]), (None, False, None))
        self.assertEqual((reg.invocation_count(), reg.get_invocation_history()), (0, []))

    def test_defective_registry_preflight_leaves_the_step_unstarted(self):
        class Broken(InProcessToolRegistry):
            def preflight(self, **k):
                raise RuntimeError("defect")
        reg, h = make_registry(Broken)
        plan = make_plan()
        before = snapshot(plan)
        res = run(plan, req("echo"), reg)
        self.assertEqual((res.status, res.outcome_kind, res.reason), (STATUS_TOOL_STEP_REJECTED,
                                                                        OUTCOME_REGISTRY_PREFLIGHT_REJECTION,
                                                                        PRESTART_PREFLIGHT_EXCEPTION))
        self.assertEqual((res.failures[0]["exception_type"], res.preflight), ("RuntimeError", None))
        self.assertEqual((snapshot(plan), h["echo"].count, reg.invocation_count()), (before, 0, 0))

    def test_base_exception_from_preflight_propagates_without_touching_the_plan(self):
        class Interrupt(InProcessToolRegistry):
            def preflight(self, **k):
                raise KeyboardInterrupt()
        reg, _ = make_registry(Interrupt)
        plan = make_plan()
        before = snapshot(plan)
        with self.assertRaises(KeyboardInterrupt):
            run(plan, req("echo"), reg)
        self.assertEqual(snapshot(plan), before)


class TestExecutionAfterPreflight(unittest.TestCase):
    def test_toctou_tool_disabled_between_preflight_and_execution_fails_the_started_step_normally(self):
        calls = []
        base = spy_registry_class(calls)

        class Racing(base):
            def preflight(self, *a, **k):
                report = super().preflight(*a, **k)
                self.disable("echo")                 # registry state changes right after the (passed) preflight
                return report
        reg, h = make_registry(Racing)
        plan = make_plan()
        res = run(plan, req("echo"), reg)
        self.assertTrue(res.preflight["ok"])
        self.assertEqual((res.status, res.outcome_kind), (STATUS_TOOL_STEP_FAILED, OUTCOME_TOOL_EXECUTION_FAILURE))
        self.assertEqual((res.reason, res.previous_state, res.final_state), (TOOL_STEP_TOOL_FAILED, "pending", "failed"))
        self.assertEqual((res.preflight_called, res.execution_called, res.rejection_record), (True, True, None))
        tr = res.execution["tool_result"]
        self.assertEqual((tr["status"], tr["failure_source"], tr["outcome_code"], tr["execution_status"], tr["handler_called"]),
                         ("failed", "tool", TOOL_DISABLED, "tool_rejected", False))
        self.assertEqual((res.sequence, tr["sequence"]), (1, 1))
        step = step_of(plan, "s1")
        self.assertEqual((step.status, step.output_data["code"], step.output_data["tool_result"]), ("failed", TOOL_STEP_TOOL_FAILED, tr))
        self.assertEqual(h["echo"].count, 0)
        self.assertEqual(calls.count("preflight"), 1)
        self.assertEqual(calls.count("execute_request"), 1)                     # normal path, executed once, no retry
        self.assertEqual(reg.invocation_count(), 1)
        self.assertEqual(reg.get_invocation_history()[0]["outcome_code"], TOOL_DISABLED)
        self.assertTrue(validate_plan(plan).valid)

    def test_toctou_permission_style_change_is_still_judged_by_the_normal_execution_checks(self):
        # the registry state changes between preflight and execution in a different way: a tool is disabled AND re-enabled
        # by the caller between two calls. Each call preflights afresh and nothing from the earlier verdict is reused.
        reg, h = make_registry()
        plan = make_plan("a", "b")
        reg.disable("echo")
        self.assertEqual(run(plan, req("echo"), reg, "a").outcome_kind, OUTCOME_REGISTRY_PREFLIGHT_REJECTION)
        reg.enable("echo")
        self.assertTrue(run(plan, req("echo"), reg, "a").ok)
        self.assertEqual((h["echo"].count, reg.invocation_count()), (1, 1))

    def test_handler_failure_after_a_passed_preflight_is_a_tool_execution_failure(self):
        reg, h = make_registry()
        plan = make_plan()
        res = run(plan, req("boom"), reg)
        self.assertEqual((res.status, res.outcome_kind, res.reason), (STATUS_TOOL_STEP_FAILED, OUTCOME_TOOL_EXECUTION_FAILURE,
                                                                        TOOL_STEP_TOOL_FAILED))
        self.assertTrue(res.preflight["ok"])
        self.assertEqual((h["boom"].count, reg.invocation_count(), step_of(plan, "s1").status), (1, 1, "failed"))
        self.assertEqual(res.execution["tool_result"]["handler_called"], True)

    def test_invalid_output_after_a_passed_preflight_fails_the_step_without_retry(self):
        reg, h = make_registry()
        plan = make_plan()
        res = run(plan, req("badout"), reg)
        self.assertEqual((res.outcome_kind, step_of(plan, "s1").status, h["badout"].count), (OUTCOME_TOOL_EXECUTION_FAILURE,
                                                                                            "failed", 1))
        res2 = run(plan, req("badout"), reg)                                    # a failed step is final
        self.assertEqual((res2.outcome_kind, res2.reason, h["badout"].count), (OUTCOME_PRE_REGISTRY_REJECTION, "STEP_NOT_READY", 1))

    def test_defective_execution_registry_leaves_a_failed_terminal_step(self):
        n = []

        class Broken(InProcessToolRegistry):
            def execute_request(self, request):
                n.append(1)
                raise RuntimeError("defect")
        reg, _ = make_registry(Broken)
        plan = make_plan()
        res = run(plan, req("echo"), reg)
        self.assertEqual((res.status, res.outcome_kind, res.reason, n), (STATUS_TOOL_STEP_FAILED, OUTCOME_TOOL_EXECUTION_FAILURE,
                                                                       "TOOL_STEP_BRIDGE_EXCEPTION", [1]))
        self.assertEqual((step_of(plan, "s1").status, res.sequence), ("failed", None))

    def test_no_step_is_ever_left_in_progress(self):
        for build in (lambda: req("echo"), lambda: req("boom"), lambda: req("net"), lambda: req("off"), lambda: None,
                      lambda: forged_request(), lambda: object.__new__(ToolRequest)):
            with self.subTest(build):
                reg, _ = make_registry()
                plan = make_plan("a", "b")
                run(plan, build(), reg, "a")
                self.assertNotIn("in_progress", [s.status for s in plan.steps])


class TestDistinctionAndRecording(unittest.TestCase):
    def test_the_three_failure_kinds_are_distinguishable(self):
        reg, _ = make_registry()
        pre = run(make_plan(), None, reg)
        registry = run(make_plan(), req("net"), reg)
        execution = run(make_plan(), req("boom"), reg)
        self.assertEqual([r.outcome_kind for r in (pre, registry, execution)],
                         [OUTCOME_PRE_REGISTRY_REJECTION, OUTCOME_REGISTRY_PREFLIGHT_REJECTION, OUTCOME_TOOL_EXECUTION_FAILURE])
        self.assertEqual([r.status for r in (pre, registry, execution)],
                         [STATUS_TOOL_STEP_REJECTED, STATUS_TOOL_STEP_REJECTED, STATUS_TOOL_STEP_FAILED])
        self.assertEqual([(r.preflight_called, r.execution_called) for r in (pre, registry, execution)],
                         [(False, False), (True, False), (True, True)])
        self.assertEqual([r.rejection_record is None for r in (pre, registry, execution)], [False, False, True])
        self.assertEqual(len({"pre_registry_rejection", "registry_preflight_rejection", "tool_execution_failure"}), 3)
        self.assertEqual((OUTCOME_PRE_REGISTRY_REJECTION, OUTCOME_REGISTRY_PREFLIGHT_REJECTION, OUTCOME_TOOL_EXECUTION_FAILURE),
                         ("pre_registry_rejection", "registry_preflight_rejection", "tool_execution_failure"))

    def test_only_the_actual_execution_carries_an_audit_sequence(self):
        reg, _ = make_registry()
        results = [run(make_plan(), None, reg), run(make_plan(), req("net"), reg), run(make_plan(), req("boom"), reg),
                   run(make_plan(), req("echo"), reg)]
        self.assertEqual([r.sequence for r in results], [None, None, 1, 2])
        self.assertEqual(reg.invocation_count(), 2)

    def test_rejection_log_is_caller_owned_ordered_and_only_receives_rejections(self):
        reg, _ = make_registry()
        log = []
        other = []
        run(make_plan(), None, reg, log=log)
        run(make_plan(), req("echo"), reg, log=log)          # success: nothing appended
        run(make_plan(), req("net"), reg, log=log)
        run(make_plan(), req("boom"), reg, log=log)          # execution failure: not a rejection, nothing appended
        run(make_plan(), req("off"), reg, log=other)
        self.assertEqual([r["rejection_kind"] for r in log], [OUTCOME_PRE_REGISTRY_REJECTION, OUTCOME_REGISTRY_PREFLIGHT_REJECTION])
        self.assertEqual([r["rejection_kind"] for r in other], [OUTCOME_REGISTRY_PREFLIGHT_REJECTION])
        self.assertEqual(run(make_plan(), req("net"), reg).rejection_record["step_id"], "s1")   # no log needed to get the record

    def test_module_keeps_no_log_of_its_own(self):
        reg, _ = make_registry()
        run(make_plan(), None, reg)
        public = [n for n in vars(exec_mod) if not n.startswith("_")]
        for name in public:
            value = getattr(exec_mod, name)
            self.assertNotIsInstance(value, (list, dict, set), name)

    def test_records_and_results_are_isolated_copies(self):
        reg, _ = make_registry()
        log = []
        res = run(make_plan(), req("net"), reg, log=log)
        res.rejection_record["failures"][0]["code"] = "TAMPERED"      # editing the result never reaches the caller's log
        res.preflight["failures"][0]["code"] = "TAMPERED"
        self.assertEqual(log[0]["failures"][0]["code"], TOOL_PERMISSION_DENIED)
        self.assertEqual(log[0]["preflight"]["failures"][0]["code"], TOOL_PERMISSION_DENIED)
        fresh = run(make_plan(), req("net"), reg, log=log)
        d = fresh.to_dict()                                           # to_dict() returns fresh copies on every call
        d["preflight"]["failures"].clear()
        d["rejection_record"]["codes"].append("x")
        d["failures"].clear()
        again = fresh.to_dict()
        self.assertEqual(again["preflight"]["failures"][0]["code"], TOOL_PERMISSION_DENIED)
        self.assertEqual((again["rejection_record"]["codes"], len(again["failures"])), ([TOOL_PERMISSION_DENIED], 1))
        log[1]["codes"].append("y")                                   # nor does editing the log reach the result
        self.assertEqual(fresh.rejection_record["codes"], [TOOL_PERMISSION_DENIED])
        self.assertEqual(set(again), RESULT_KEYS)

    def test_result_dict_shape_is_fixed_for_every_outcome(self):
        reg, _ = make_registry()
        for request in (req("echo"), req("boom"), req("net"), None):
            with self.subTest(getattr(request, "name", None)):
                self.assertEqual(set(run(make_plan(), request, reg).to_dict()), RESULT_KEYS)


class TestDeterminismAndIsolation(unittest.TestCase):
    def outcome(self, request_builder):
        reg, _ = make_registry()
        plan = make_plan()
        return run(plan, request_builder(), reg).to_dict(), snapshot(plan)

    def test_repeated_results_are_identical_for_every_outcome_kind(self):
        for build in (lambda: req("echo", {"k": [1, 2]}), lambda: req("boom"), lambda: req("net"), lambda: req("needs_cap"),
                      lambda: None, lambda: forged_request()):
            with self.subTest(build):
                first = self.outcome(build)
                self.assertEqual(first, self.outcome(build))
                self.assertEqual(first, self.outcome(build))

    def test_repeating_a_rejection_on_the_same_plan_and_registry_is_stable_and_side_effect_free(self):
        reg, _ = make_registry()
        plan = make_plan()
        before = (snapshot(plan), registry_state(reg))
        results = [run(plan, req("net"), reg).to_dict() for _ in range(3)]
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1], results[2])
        self.assertEqual((snapshot(plan), registry_state(reg)), before)

    def test_request_is_not_modified_and_is_isolated_from_the_registry(self):
        reg, _ = make_registry()
        request = req("echo", {"a": [1, {"b": 2}]}, perms=["network"], caps=["cap_a"], confirmed=True)
        before = request.to_dict()
        run(make_plan(), request, reg)
        run(make_plan(), request, reg)
        self.assertEqual(request.to_dict(), before)

    def test_handler_input_cannot_reach_back_into_the_request(self):
        seen = []

        def mutate(tool_input):
            tool_input["a"].append(99)
            seen.append(tool_input)
            return {"ok": True}
        reg, _ = make_registry()
        reg.register(exec_mod_tool_spec("mutator", mutate))
        request = req("mutator", {"a": [1]})
        run(make_plan(), request, reg)
        self.assertEqual((request.input, len(seen)), ({"a": [1]}, 1))

    def test_registries_are_isolated_from_each_other(self):
        reg_a, _ = make_registry()
        reg_b, _ = make_registry()
        run(make_plan(), req("echo"), reg_a)
        run(make_plan(), req("net"), reg_b)
        self.assertEqual((reg_a.invocation_count(), reg_b.invocation_count()), (1, 0))

    def test_preflight_verdict_does_not_leak_between_calls(self):
        reg, _ = make_registry()
        plan = make_plan("a", "b")
        self.assertEqual(run(plan, req("net"), reg, "a").outcome_kind, OUTCOME_REGISTRY_PREFLIGHT_REJECTION)
        self.assertTrue(run(plan, req("echo"), reg, "a").ok)             # a prior rejection or grant is never remembered
        self.assertEqual(run(plan, req("net"), reg, "b").outcome_kind, OUTCOME_REGISTRY_PREFLIGHT_REJECTION)


def exec_mod_tool_spec(name, fn):
    from tools.in_process_tool_registry import ToolSpec
    return ToolSpec(name=name, description="d", handler=Counting(fn), input_schema={"type": "object"}, output_description="o")


class TestContractBoundaries(unittest.TestCase):
    def test_signature_and_no_grant_confirmation_or_tool_arguments(self):
        self.assertEqual(list(inspect.signature(execute_plan_tool_step_preflighted).parameters),
                         ["plan", "step_id", "request", "registry", "rejection_log"])
        for extra in ({"confirmed": True}, {"granted_permissions": ["network"]}, {"tool_name": "echo"}, {"retries": 2}):
            reg, _ = make_registry()
            with self.assertRaises(TypeError):
                execute_plan_tool_step_preflighted(make_plan(), "s1", req("echo"), reg, **extra)

    def test_the_existing_adapter_is_unchanged_and_still_does_not_preflight(self):
        calls = []
        reg, _ = make_registry(spy_registry_class(calls))
        execute_plan_tool_step(make_plan(), "s1", req("echo"), reg)
        self.assertEqual(calls, ["execute_request", "execute", "invoke"])
        self.assertEqual(list(inspect.signature(execute_plan_tool_step).parameters), ["plan", "step_id", "request", "registry"])
        res = execute_plan_tool_step(make_plan(), "s1", req("net"), reg)          # H4 behaviour of 708 is preserved
        self.assertEqual((res.status, res.final_state, res.reason), (STATUS_TOOL_STEP_FAILED, "failed", TOOL_STEP_TOOL_FAILED))

    def test_section_5_validation_rules_are_not_duplicated_in_the_executor(self):
        src = inspect.getsource(exec_mod)
        tree = ast.parse(src)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for forbidden in ("SUPPORTED_PERMISSIONS", "_NAME_RE", "CONFIRMATION_PERMISSION", "normalize_tool_output", "has", "is_enabled",
                          "is_invokable", "get_required_permissions", "get_required_capabilities", "granted_permissions",
                          "granted_capabilities", "confirmed", "execute_request", "handler", "enable", "disable"):
            self.assertNotIn(forbidden, names, forbidden)
            self.assertNotIn(forbidden, attrs, forbidden)
        self.assertIn("preflight", attrs)
        self.assertNotIn("tools", {m.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for m in [n.module]})

    def test_f2_stays_unresolved_step_required_capabilities_are_never_read(self):
        reg, _ = make_registry()
        plan = make_plan()
        plan.steps[0].required_capabilities = ["Free-Form Section 4 Capability!"]
        res = run(plan, req("echo"), reg)
        self.assertEqual(res.outcome_kind, OUTCOME_COMPLETED)
        self.assertNotIn("required_capabilities", {n.attr for n in ast.walk(ast.parse(inspect.getsource(exec_mod)))
                                                   if isinstance(n, ast.Attribute)})

    def test_f1_decision_is_unchanged_the_step_layer_is_used_and_no_legacy_stack_is_imported(self):
        src = inspect.getsource(exec_mod)
        imports = {n.module for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)}
        self.assertEqual(imports, {"planning.plan", "planning.plan_builder", "planning.plan_step_execution",
                                   "planning.plan_validation", "planning.tool_capability_mapping",
                                   "planning.tool_step_bridge"})       # Prompt 710 added the pure mapping module
        tree = ast.parse(src)
        identifiers = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
                      {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for legacy in ("PlanExecutionController", "ExecutionEngine", "process_input", "execute_plan_step"):
            self.assertNotIn(legacy, identifiers, legacy)
        self.assertFalse({m.split(".")[0] for m in imports} & {"execution", "agent", "tools"})

    def test_preflighted_function_is_not_wired_into_any_production_module(self):
        for root, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__")]
            for f in files:
                path = os.path.join(root, f)
                if f.endswith(".py") and not path.endswith(os.path.join("planning", "tool_step_executor.py")) \
                        and not path.endswith(os.path.join("planning", "tool_step_retry.py")) \
                        and not path.endswith(os.path.join("planning", "tool_step_agent_adapter.py")):     # Prompt 711/714: sanctioned callers (714 only names it in its docstring)
                    with open(path, encoding="utf-8") as fh:
                        text = fh.read()
                    self.assertNotIn("execute_plan_tool_step_preflighted", text, path)

    def test_no_bytecode_and_database_untouched(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
