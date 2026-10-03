"""Prompt 714 - Section 6 Agent-Loop tool-step adapter (`planning/tool_step_agent_adapter.py`).

Focused tests for `execute_agent_tool_step()`: the isolated caller-side boundary a FUTURE Agent Loop must use. It validates (a-f, fixed
order) BEFORE anything starts and then calls only `execute_plan_tool_step_with_retry()`. Nothing here wires the adapter into
process_input(), AgentLoop.run(), the legacy execution stack or PlanManager.refresh_*. Docs: docs/section6_agent_loop_adapter_prompt714.md
"""
import ast
import copy
import glob
import hashlib
import inspect
import json
import os
import pickle
import unittest
from unittest import mock

from planning import tool_step_agent_adapter as adapter_mod
from planning.plan_builder import validate_plan_step_states
from planning.plan_manager import PlanManager
from planning.plan_validation import validate_plan
from planning.tool_step_agent_adapter import (ADAPTER_EXECUTION_NOT_AUTHORIZED, ADAPTER_INCONSISTENT_STEP_STATE,
                                              ADAPTER_INVALID_ATTEMPT_LOG, ADAPTER_INVALID_MAPPING_ARGUMENTS,
                                              ADAPTER_INVALID_MAX_ATTEMPTS, ADAPTER_INVALID_PLAN, ADAPTER_INVALID_PLAN_OBJECT,
                                              ADAPTER_INVALID_STEP_ID, ADAPTER_LEGACY_STEP_STATE,
                                              ADAPTER_MALFORMED_CAPABILITY_MAPPING, ADAPTER_UNKNOWN_STEP, MAX_ADAPTER_ATTEMPTS,
                                              SOURCE_ADAPTER, SOURCE_PRE_START, SOURCE_TOOL_EXECUTION, STATUS_ADAPTER_COMPLETED,
                                              STATUS_ADAPTER_FAILED, STATUS_ADAPTER_REJECTED, AgentToolStepResult,
                                              execute_agent_tool_step)
from tests.test_section6_agent_loop_handover_decision_prompt713 import (FROZEN_LEGACY_DIGEST, FROZEN_SECTION45_DIGEST, digest)
from tests.test_section6_tool_step_executor_prompt708 import make_plan, make_registry, req, snapshot, step_of
from tests.test_section6_tool_step_preflight_prompt709 import registry_state, spy_registry_class
from tests.test_section6_tool_step_retry_prompt711 import enable_after_registry
from tools.tool_request import ToolRequest

from tests.section6_agent_loop_baseline_prompt719c import file_bytes as _baseline_file_bytes, read_text as _baseline_read_text   # Prompt 719-C: exact-path exemption for agent/agent_loop.py, see that helper
PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
FROZEN_AGENT_LOOP_SHA256 = "b69e217564345cad5ae30b76fe6af97c0d6d263098ad4344954d5946b7631157"
FROZEN_PLAN_MANAGER_SHA256 = "885b8835a48ce53e86a9a65d9d0d873d41821c8547d8c1606e6021521b686dc3"
ADAPTER_REL = "planning/tool_step_agent_adapter.py"

MAPPING = [{"capability": "Needs A", "grants": ["cap_a"]}]
RESULT_KEYS = {"ok", "status", "failure_source", "failure_code", "step_id", "execution_started", "final_step_state",
               "retry_stop_reason", "attempt_count", "attempts", "outcome_kind", "tool_result", "failures",
               "invocation_sequence", "mapping", "preflight"}


def read(rel):
    return _baseline_read_text(rel)          # Prompt 719-C: agent/agent_loop.py is read without the sanctioned additions


def run(plan, request, reg, n=3, step_id="s1", **kw):
    return execute_agent_tool_step(plan, step_id, request, reg, n, **kw)


def adapter_imports():
    tree = ast.parse(read(ADAPTER_REL))
    found = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    found += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    return sorted(found)


class Rig:
    """A plan + spy registry + request bundle, with everything needed to prove a call changed nothing."""

    def __init__(self, tool="echo", plan=None, caps=None, tool_input=None):
        self.calls = []
        self.reg, self.h = make_registry(spy_registry_class(self.calls))
        self.plan = plan if plan is not None else make_plan()
        self.request = req(tool, tool_input, caps=caps)
        self.log = []
        self.before_plan = snapshot(self.plan)
        self.before_reg = registry_state(self.reg)

    def assert_untouched_rejection(self, tc, res, code, source=SOURCE_ADAPTER):
        tc.assertIsInstance(res, AgentToolStepResult)
        tc.assertEqual((res.ok, res.status, res.failure_source, res.failure_code), (False, STATUS_ADAPTER_REJECTED, source, code))
        tc.assertEqual(res.codes()[0], code)
        tc.assertEqual((res.execution_started, res.invocation_sequence), (False, None))
        tc.assertEqual(snapshot(self.plan), self.before_plan)
        tc.assertEqual(registry_state(self.reg), self.before_reg)
        tc.assertEqual((self.calls, self.log, self.reg.invocation_count()), ([], [], 0))
        for counter in self.h.values():
            tc.assertEqual(counter.count, 0)


class TestValidExecution(unittest.TestCase):
    def test_valid_execution_completes_the_step_and_reports_everything(self):
        rig = Rig(tool_input={"a": [1, 2]})
        res = run(rig.plan, rig.request, rig.reg, 3, attempt_log=rig.log)
        self.assertIsInstance(res, AgentToolStepResult)
        self.assertTrue(res.ok)
        self.assertEqual((res.status, res.failure_source, res.failure_code, res.step_id), (STATUS_ADAPTER_COMPLETED, None, None, "s1"))
        self.assertEqual((res.execution_started, res.final_step_state, res.retry_stop_reason, res.attempt_count),
                         (True, "completed", "completed", 1))
        self.assertEqual((res.failures, res.outcome_kind, res.mapping), ([], "completed", None))
        self.assertEqual(res.tool_result["output"], {"echo": {"a": [1, 2]}})
        self.assertEqual(res.tool_result["tool_name"], "echo")
        self.assertTrue(res.preflight["ok"])
        self.assertEqual(step_of(rig.plan, "s1").status, "completed")
        self.assertEqual(rig.h["echo"].count, 1)
        self.assertEqual(len(res.attempts), 1)
        self.assertEqual(set(res.to_dict()), RESULT_KEYS)
        self.assertEqual(len(rig.log), 1)                              # the one documented write: the caller's attempt log

    def test_invocation_sequence_is_the_registrys_own_audit_sequence(self):
        rig = Rig()
        res = run(rig.plan, rig.request, rig.reg)
        record = rig.reg.get_invocation_history()[0]
        self.assertEqual((res.invocation_sequence, record["sequence"], res.tool_result["sequence"]), (1, 1, 1))
        self.assertEqual(rig.reg.invocation_count(), 1)

    def test_dependent_step_runs_after_its_dependency_completed(self):
        plan = make_plan("s1", "s2", chain=True)
        reg, _ = make_registry()
        self.assertTrue(run(plan, req("echo"), reg, step_id="s1").ok)
        res = run(plan, req("echo"), reg, step_id="s2")
        self.assertEqual((res.ok, res.final_step_state, res.invocation_sequence), (True, "completed", 2))

    def test_unready_dependent_step_is_a_pre_start_rejection_that_may_be_retried_only_up_to_the_limit(self):
        plan = make_plan("s1", "s2", chain=True)
        rig = Rig(plan=plan)
        res = run(plan, rig.request, rig.reg, 2, step_id="s2")
        self.assertEqual((res.status, res.failure_source, res.failure_code, res.attempt_count, res.retry_stop_reason),
                         (STATUS_ADAPTER_REJECTED, SOURCE_PRE_START, "STEP_NOT_READY", 2, "attempt_limit_reached"))
        self.assertEqual((step_of(plan, "s2").status, rig.h["echo"].count, rig.reg.invocation_count()), ("pending", 0, 0))


class TestValidationRejections(unittest.TestCase):
    def test_missing_plan(self):
        for bad in (None, "plan", 5, {}, object()):
            rig = Rig()
            res = run(bad, rig.request, rig.reg, attempt_log=rig.log)
            rig.assert_untouched_rejection(self, res, ADAPTER_INVALID_PLAN_OBJECT)
            self.assertEqual((res.attempt_count, res.retry_stop_reason, res.final_step_state), (0, None, None))

    def test_invalid_plan(self):
        plan = make_plan()
        plan.steps[0].dependencies = ["ghost"]                         # unknown dependency -> validate_plan() invalid
        rig = Rig(plan=plan)
        self.assertFalse(validate_plan(plan).valid)
        res = run(plan, rig.request, rig.reg, attempt_log=rig.log)
        rig.assert_untouched_rejection(self, res, ADAPTER_INVALID_PLAN)
        self.assertTrue(res.failures[0]["issues"])

    def test_invalid_step_id(self):
        for bad in (None, "", "   ", 5, ["s1"], b"s1"):
            rig = Rig()
            res = run(rig.plan, rig.request, rig.reg, step_id=bad, attempt_log=rig.log)
            rig.assert_untouched_rejection(self, res, ADAPTER_INVALID_STEP_ID)
            self.assertEqual(res.step_id, bad if isinstance(bad, str) else None)

    def test_unknown_step(self):
        rig = Rig()
        res = run(rig.plan, rig.request, rig.reg, step_id="nope", attempt_log=rig.log)
        rig.assert_untouched_rejection(self, res, ADAPTER_UNKNOWN_STEP)
        self.assertEqual((res.step_id, res.final_step_state, res.attempt_count), ("nope", None, 0))

    def test_inconsistent_step_state_is_rejected_before_start(self):
        def in_progress_but_not_executed(p):
            step_of(p, "s1").status = "in_progress"

        def pending_with_output(p):
            step_of(p, "s1").output_data = {"x": 1}

        def non_boolean_flag(p):
            p.metadata["execution_authorized"] = "yes"

        def missing_flag(p):
            del p.metadata["execution_authorized"]

        def unknown_state(p):
            step_of(p, "s1").status = "weird"

        def executed_without_progress(p):
            p.metadata["executed"] = True

        for mutate in (in_progress_but_not_executed, pending_with_output, non_boolean_flag, missing_flag, unknown_state,
                       executed_without_progress):
            plan = make_plan()
            mutate(plan)
            rig = Rig(plan=plan)
            self.assertTrue(validate_plan(plan).valid, mutate.__name__)            # validate_plan() alone accepts these ...
            self.assertFalse(validate_plan_step_states(plan).valid, mutate.__name__)   # ... validate_plan_step_states() does not
            res = run(plan, rig.request, rig.reg, attempt_log=rig.log)
            rig.assert_untouched_rejection(self, res, ADAPTER_INCONSISTENT_STEP_STATE)
            self.assertTrue(res.failures[0]["issues"])

    def test_legacy_ready_state_is_rejected_not_converted_or_repaired(self):
        plan = make_plan()
        step_of(plan, "s1").status = "ready"
        rig = Rig(plan=plan)
        self.assertTrue(validate_plan(plan).valid)                              # conflict C2
        self.assertFalse(validate_plan_step_states(plan).valid)
        with mock.patch.object(PlanManager, "refresh_plan_step_statuses", side_effect=AssertionError("refresh called")), \
                mock.patch.object(PlanManager, "refresh_step_status", side_effect=AssertionError("refresh called")), \
                mock.patch.object(PlanManager, "refresh_after_step_change", side_effect=AssertionError("refresh called")):
            res = run(plan, rig.request, rig.reg, 5, attempt_log=rig.log)
        rig.assert_untouched_rejection(self, res, ADAPTER_LEGACY_STEP_STATE)
        self.assertEqual((res.final_step_state, step_of(plan, "s1").status, res.failures[0]["step_ids"]), ("ready", "ready", ["s1"]))

    def test_legacy_blocked_state_is_rejected_not_converted_or_repaired(self):
        plan = make_plan()
        step_of(plan, "s1").status = "blocked"
        rig = Rig(plan=plan)
        self.assertTrue(validate_plan(plan).valid)
        self.assertFalse(validate_plan_step_states(plan).valid)
        res = run(plan, rig.request, rig.reg, 5, attempt_log=rig.log)
        rig.assert_untouched_rejection(self, res, ADAPTER_LEGACY_STEP_STATE)
        self.assertEqual((res.final_step_state, step_of(plan, "s1").status), ("blocked", "blocked"))

    def test_a_legacy_label_on_another_step_makes_the_whole_plan_ineligible(self):
        plan = make_plan("s1", "s2")
        step_of(plan, "s2").status = "ready"
        rig = Rig(plan=plan)
        res = run(plan, rig.request, rig.reg, attempt_log=rig.log)
        rig.assert_untouched_rejection(self, res, ADAPTER_LEGACY_STEP_STATE)
        self.assertEqual((res.failures[0]["step_ids"], res.final_step_state), (["s2"], "pending"))

    def test_missing_execution_authorization(self):
        rig = Rig(plan=make_plan(authorized=False))
        self.assertTrue(validate_plan_step_states(rig.plan).valid)
        res = run(rig.plan, rig.request, rig.reg, 4, attempt_log=rig.log)
        rig.assert_untouched_rejection(self, res, ADAPTER_EXECUTION_NOT_AUTHORIZED)
        self.assertEqual((res.attempt_count, res.retry_stop_reason), (0, None))          # not retried: a plan-level gate

    def test_authorization_is_not_inferred_from_capabilities_permissions_or_mapping(self):
        rig = Rig(tool="needs_cap", plan=make_plan(authorized=False), caps=["cap_a"])
        res = run(rig.plan, rig.request, rig.reg, 3, required_capabilities=["Needs A"], capability_mapping=MAPPING,
                  attempt_log=rig.log)
        rig.assert_untouched_rejection(self, res, ADAPTER_EXECUTION_NOT_AUTHORIZED)

    def test_invalid_max_attempts(self):
        for bad in (0, -1, None, True, False, 1.0, "3", [1], MAX_ADAPTER_ATTEMPTS + 1, 10 ** 9):
            rig = Rig()
            res = run(rig.plan, rig.request, rig.reg, bad, attempt_log=rig.log)
            rig.assert_untouched_rejection(self, res, ADAPTER_INVALID_MAX_ATTEMPTS)
            self.assertEqual(res.attempt_count, 0, repr(bad))

    def test_max_attempts_has_no_default_and_a_finite_documented_bound(self):
        params = inspect.signature(execute_agent_tool_step).parameters
        self.assertEqual(list(params), ["plan", "step_id", "request", "registry", "max_attempts", "required_capabilities",
                                        "capability_mapping", "attempt_log"])
        self.assertIs(params["max_attempts"].default, inspect.Parameter.empty)
        self.assertEqual(MAX_ADAPTER_ATTEMPTS, 10)
        rig = Rig()
        rig.reg.disable("echo")                                          # a retryable pre-start rejection every time
        res = run(rig.plan, rig.request, rig.reg, MAX_ADAPTER_ATTEMPTS)
        self.assertEqual((res.attempt_count, res.retry_stop_reason), (MAX_ADAPTER_ATTEMPTS, "attempt_limit_reached"))

    def test_invalid_attempt_log(self):
        for bad in ("log", {}, (), 5):
            rig = Rig()
            res = run(rig.plan, rig.request, rig.reg, attempt_log=bad)
            rig.assert_untouched_rejection(self, res, ADAPTER_INVALID_ATTEMPT_LOG)

    def test_invalid_tool_request_is_a_non_retried_pre_start_rejection(self):
        class Forged:
            name = "echo"

        for bad in (None, "not a request", 5, Forged(), object()):
            rig = Rig()
            res = run(rig.plan, bad, rig.reg, 5, attempt_log=rig.log)
            self.assertEqual((res.status, res.failure_source, res.failure_code), (STATUS_ADAPTER_REJECTED, SOURCE_PRE_START,
                                                                                  "INVALID_BRIDGE_REQUEST"))
            self.assertEqual((res.attempt_count, res.retry_stop_reason, res.execution_started, res.invocation_sequence),
                             (1, "non_retryable_rejection", False, None))
            self.assertEqual((snapshot(rig.plan), rig.calls, rig.reg.invocation_count(), rig.h["echo"].count),
                             (rig.before_plan, [], 0, 0))
            self.assertEqual(registry_state(rig.reg), rig.before_reg)
            self.assertEqual(step_of(rig.plan, "s1").status, "pending")

    def test_invalid_registry_is_a_non_retried_pre_start_rejection(self):
        rig = Rig()
        res = run(rig.plan, rig.request, "not a registry", 5)
        self.assertEqual((res.failure_code, res.attempt_count, res.retry_stop_reason), ("INVALID_BRIDGE_REGISTRY", 1,
                                                                                        "non_retryable_rejection"))
        self.assertEqual(snapshot(rig.plan), rig.before_plan)

    def test_malformed_capability_mapping_is_rejected_before_start(self):
        cases = (
            (["Needs A"], [{"capability": "Needs A", "grants": ["BAD NAME"]}], "invalid_mapping"),
            (["Needs A"], "bad", "invalid_mapping"),
            (["Needs A"], {"Needs A": ["cap_a"]}, "invalid_mapping"),
            (["Needs A"], [{"capability": "Needs A", "grants": []}], "invalid_mapping"),
            (["Needs A"], MAPPING + MAPPING, "invalid_mapping"),
            ([""], MAPPING, "invalid_input"),
            (5, MAPPING, "invalid_input"),
            ("Needs A", MAPPING, "invalid_input"),
        )
        for required, mapping, status in cases:
            rig = Rig(tool="needs_cap", caps=["cap_a"])
            res = run(rig.plan, rig.request, rig.reg, 4, required_capabilities=required, capability_mapping=mapping,
                      attempt_log=rig.log)
            rig.assert_untouched_rejection(self, res, ADAPTER_MALFORMED_CAPABILITY_MAPPING)
            self.assertEqual((res.mapping["status"], res.attempt_count), (status, 0), repr((required, mapping)))

    def test_mapping_pair_must_be_supplied_together(self):
        for required, mapping in ((["Needs A"], None), (None, MAPPING)):
            rig = Rig()
            res = run(rig.plan, rig.request, rig.reg, required_capabilities=required, capability_mapping=mapping,
                      attempt_log=rig.log)
            rig.assert_untouched_rejection(self, res, ADAPTER_INVALID_MAPPING_ARGUMENTS)
            self.assertIsNone(res.mapping)


class TestValidationOrder(unittest.TestCase):
    """Each case violates a later stage AND an earlier one: the earlier stage's code must win (a, b, c, d, e, f)."""

    def code(self, plan, step_id="s1", n=3, **kw):
        rig = Rig(plan=plan)
        res = run(plan, rig.request, rig.reg, n, step_id=step_id, **kw)
        rig.assert_untouched_rejection(self, res, res.failure_code)
        return res.failure_code

    def test_a_plan_validity_precedes_everything(self):
        plan = make_plan(authorized=False)
        plan.steps[0].dependencies = ["ghost"]
        step_of(plan, "s1").status = "ready"
        self.assertEqual(self.code(plan, step_id="", n=0, required_capabilities=["x"]), ADAPTER_INVALID_PLAN)
        self.assertEqual(self.code(None, step_id="", n=0), ADAPTER_INVALID_PLAN_OBJECT)

    def test_b_state_consistency_precedes_step_existence_authorization_retry_and_mapping(self):
        plan = make_plan(authorized=False)
        step_of(plan, "s1").status = "ready"
        self.assertEqual(self.code(plan, step_id="ghost", n=0, required_capabilities=["x"]), ADAPTER_LEGACY_STEP_STATE)
        plan = make_plan()
        plan.metadata["executed"] = True
        self.assertEqual(self.code(plan, step_id="ghost", n=0), ADAPTER_INCONSISTENT_STEP_STATE)

    def test_c_step_existence_precedes_authorization_retry_and_mapping(self):
        plan = make_plan(authorized=False)
        self.assertEqual(self.code(plan, step_id="ghost", n=0, required_capabilities=["x"]), ADAPTER_UNKNOWN_STEP)
        self.assertEqual(self.code(plan, step_id=7, n=0), ADAPTER_INVALID_STEP_ID)

    def test_d_authorization_precedes_retry_arguments_and_mapping(self):
        plan = make_plan(authorized=False)
        self.assertEqual(self.code(plan, n=0, required_capabilities=["x"]), ADAPTER_EXECUTION_NOT_AUTHORIZED)

    def test_e_retry_arguments_precede_mapping(self):
        self.assertEqual(self.code(make_plan(), n=0, required_capabilities=["x"]), ADAPTER_INVALID_MAX_ATTEMPTS)
        rig = Rig()
        res = run(rig.plan, rig.request, rig.reg, 2, required_capabilities=["x"], attempt_log="bad")
        self.assertEqual(res.failure_code, ADAPTER_INVALID_ATTEMPT_LOG)

    def test_f_mapping_is_last(self):
        self.assertEqual(self.code(make_plan(), required_capabilities=["x"]), ADAPTER_INVALID_MAPPING_ARGUMENTS)
        self.assertEqual(self.code(make_plan(), required_capabilities=["x"], capability_mapping="bad"),
                         ADAPTER_MALFORMED_CAPABILITY_MAPPING)


class TestMappedExecution(unittest.TestCase):
    def test_successful_mapped_execution(self):
        rig = Rig(tool="needs_cap", caps=["cap_a"])
        res = run(rig.plan, rig.request, rig.reg, 2, required_capabilities=["Needs A"], capability_mapping=MAPPING,
                  attempt_log=rig.log)
        self.assertEqual((res.ok, res.execution_started, res.attempt_count, res.invocation_sequence), (True, True, 1, 1))
        self.assertEqual((res.mapping["status"], res.mapping["grant_names"]), ("satisfied", ["cap_a"]))
        self.assertEqual((rig.h["needs_cap"].count, step_of(rig.plan, "s1").status), (1, "completed"))

    def test_mapping_rejection_before_start_unmapped_requirement(self):
        rig = Rig(tool="needs_cap", caps=["cap_a"])
        res = run(rig.plan, rig.request, rig.reg, 3, required_capabilities=["Needs B"], capability_mapping=MAPPING,
                  attempt_log=rig.log)
        self.assertEqual((res.status, res.failure_source, res.failure_code, res.execution_started),
                         (STATUS_ADAPTER_REJECTED, SOURCE_PRE_START, "CAPABILITY_MAPPING_REJECTED", False))
        self.assertEqual((res.attempt_count, res.retry_stop_reason, res.invocation_sequence), (3, "attempt_limit_reached", None))
        self.assertEqual((res.mapping["status"], res.mapping["missing"]), ("unmapped", ["Needs B"]))
        self.assertEqual((step_of(rig.plan, "s1").status, snapshot(rig.plan), rig.h["needs_cap"].count, rig.reg.invocation_count()),
                         ("pending", rig.before_plan, 0, 0))
        self.assertEqual(rig.calls, [])
        self.assertEqual(len(rig.log), 3)

    def test_mapping_rejection_before_start_grant_not_supplied_and_nothing_is_granted_by_the_mapping(self):
        rig = Rig(tool="needs_cap", caps=[])
        before = rig.request.to_registry_arguments()
        res = run(rig.plan, rig.request, rig.reg, 2, required_capabilities=["Needs A"], capability_mapping=MAPPING)
        self.assertEqual((res.failure_source, res.failure_code, res.attempt_count), (SOURCE_PRE_START, "MAPPED_GRANT_NOT_SUPPLIED", 2))
        self.assertEqual(res.failures[0]["missing_grants"], ["cap_a"])
        self.assertEqual((rig.request.to_registry_arguments(), rig.h["needs_cap"].count, rig.reg.invocation_count()), (before, 0, 0))

    def test_section5_stays_the_final_authority_over_a_satisfied_mapping(self):
        rig = Rig(tool="net", caps=["cap_a"])                          # 'net' needs the network permission the request lacks
        res = run(rig.plan, rig.request, rig.reg, 1, required_capabilities=["Needs A"], capability_mapping=MAPPING)
        self.assertEqual((res.failure_source, res.outcome_kind, res.execution_started), (SOURCE_PRE_START,
                                                                                         "registry_preflight_rejection", False))
        self.assertEqual((rig.h["net"].count, rig.reg.invocation_count()), (0, 0))


class TestRegistryAndRetrySemantics(unittest.TestCase):
    def test_registry_preflight_rejection(self):
        for tool in ("off", "ghost", "net", "confirm"):            # disabled, unknown, missing permission, missing confirmation
            rig = Rig(tool=tool)
            res = run(rig.plan, rig.request, rig.reg, 1, attempt_log=rig.log)
            self.assertEqual((res.status, res.failure_source, res.outcome_kind, res.execution_started),
                             (STATUS_ADAPTER_REJECTED, SOURCE_PRE_START, "registry_preflight_rejection", False), tool)
            self.assertFalse(res.preflight["ok"])
            self.assertEqual((res.invocation_sequence, step_of(rig.plan, "s1").status, res.final_step_state), (None, "pending", "pending"))
            self.assertEqual((rig.reg.invocation_count(), sum(c.count for c in rig.h.values()), rig.calls), (0, 0, ["preflight"]), tool)
            self.assertEqual(snapshot(rig.plan), rig.before_plan)
            self.assertEqual(registry_state(rig.reg), rig.before_reg)

    def test_retryable_pre_start_rejection_may_retry_and_then_complete(self):
        reg, h = enable_after_registry(flip_after=1)                   # 'off' becomes enabled after the first preflight
        plan = make_plan()
        log = []
        res = run(plan, req("off"), reg, 3, attempt_log=log)
        self.assertEqual((res.ok, res.attempt_count, res.retry_stop_reason, res.invocation_sequence), (True, 2, "completed", 1))
        self.assertEqual([a["outcome_kind"] for a in res.attempts], ["registry_preflight_rejection", "completed"])
        self.assertEqual([a["sequence"] for a in res.attempts], [None, 1])                    # the rejection consumed no sequence
        self.assertEqual((h["off"].count, reg.invocation_count(), len(log)), (1, 1, 2))

    def test_retry_never_exceeds_the_callers_max_attempts(self):
        rig = Rig(tool="off")
        res = run(rig.plan, rig.request, rig.reg, 4)
        self.assertEqual((res.attempt_count, res.retry_stop_reason, res.failure_code), (4, "attempt_limit_reached", res.failure_code))
        self.assertEqual(rig.reg.invocation_count(), 0)

    def test_terminal_execution_failure(self):
        for tool in ("boom", "badout", "typed"):
            rig = Rig(tool=tool)
            res = run(rig.plan, rig.request, rig.reg, 5, attempt_log=rig.log)
            self.assertEqual((res.ok, res.status, res.failure_source, res.execution_started),
                             (False, STATUS_ADAPTER_FAILED, SOURCE_TOOL_EXECUTION, True), tool)
            self.assertEqual((res.final_step_state, res.retry_stop_reason, res.attempt_count, res.outcome_kind),
                             ("failed", "execution_failed", 1, "tool_execution_failure"), tool)
            self.assertEqual((res.invocation_sequence, rig.reg.invocation_count(), step_of(rig.plan, "s1").status), (1, 1, "failed"))
            self.assertEqual(res.tool_result["failure_source"], "tool")
            self.assertEqual(res.failure_code, "TOOL_STEP_TOOL_FAILED")

    def test_no_retry_after_start_and_a_failed_or_completed_step_never_runs_again(self):
        rig = Rig(tool="boom")
        first = run(rig.plan, rig.request, rig.reg, 5)
        self.assertEqual((first.attempt_count, rig.h["boom"].count), (1, 1))
        again = run(rig.plan, rig.request, rig.reg, 5)                 # the step is failed: terminal, never re-run in place
        self.assertEqual((again.status, again.failure_source, again.execution_started, again.attempt_count, again.retry_stop_reason),
                         (STATUS_ADAPTER_REJECTED, SOURCE_PRE_START, False, 1, "non_retryable_rejection"))
        self.assertEqual((step_of(rig.plan, "s1").status, rig.h["boom"].count, rig.reg.invocation_count()), ("failed", 1, 1))

        ok = Rig()
        self.assertTrue(run(ok.plan, ok.request, ok.reg, 5).ok)
        again = run(ok.plan, ok.request, ok.reg, 5)
        self.assertEqual((again.status, again.execution_started, again.attempt_count, again.retry_stop_reason),
                         (STATUS_ADAPTER_REJECTED, False, 1, "non_retryable_rejection"))
        self.assertEqual((step_of(ok.plan, "s1").status, ok.h["echo"].count, ok.reg.invocation_count()), ("completed", 1, 1))

    def test_in_progress_step_is_never_restarted(self):
        plan = make_plan()
        rig = Rig(plan=plan)
        from planning.plan_step_execution import start_plan_step
        self.assertTrue(start_plan_step(plan, "s1").ok)
        before = snapshot(plan)
        res = run(plan, rig.request, rig.reg, 5)
        self.assertEqual((res.status, res.execution_started, res.attempt_count, res.final_step_state),
                         (STATUS_ADAPTER_REJECTED, False, 1, "in_progress"))
        self.assertEqual((snapshot(plan), rig.h["echo"].count, rig.reg.invocation_count()), (before, 0, 0))


class TestNoMutation(unittest.TestCase):
    def test_request_grants_and_mapping_are_never_modified_on_any_outcome(self):
        caps, mapping, required = ["cap_a", "extra"], copy.deepcopy(MAPPING), ["Needs A"]
        caps_before, mapping_before, required_before = list(caps), copy.deepcopy(mapping), list(required)
        scenarios = (("needs_cap", make_plan(), {}), ("needs_cap", make_plan(authorized=False), {}),
                     ("boom", make_plan(), {}), ("off", make_plan(), {}))
        for tool, plan, _ in scenarios:
            rig = Rig(tool=tool, plan=plan, caps=caps)
            args_before = rig.request.to_registry_arguments()
            res = run(plan, rig.request, rig.reg, 3, required_capabilities=required, capability_mapping=mapping)
            self.assertIsInstance(res, AgentToolStepResult)
            self.assertEqual(rig.request.to_registry_arguments(), args_before, tool)
            self.assertEqual((caps, mapping, required), (caps_before, mapping_before, required_before), tool)
            self.assertEqual(set(rig.request.to_registry_arguments()["granted_capabilities"]), set(caps_before), tool)

    def test_request_is_immutable_and_the_adapter_never_builds_or_replaces_it(self):
        rig = Rig(tool="needs_cap", caps=["cap_a"])
        with self.assertRaises(Exception):
            rig.request.name = "other"
        with mock.patch.object(rig.reg, "preflight", wraps=rig.reg.preflight) as spy:
            run(rig.plan, rig.request, rig.reg, 1)
        self.assertEqual(spy.call_args.kwargs, rig.request.to_registry_arguments())        # the registry saw the caller's own request
        src = inspect.getsource(adapter_mod)
        for word in ("create_tool_request", "ToolRequest("):
            self.assertNotIn(word, src)

    def test_grants_are_not_changed_by_a_rejected_mapping(self):
        rig = Rig(tool="needs_cap", caps=["other_cap"])
        before = rig.request.to_registry_arguments()
        run(rig.plan, rig.request, rig.reg, 2, required_capabilities=["Needs A"], capability_mapping=MAPPING)
        self.assertEqual(rig.request.to_registry_arguments(), before)
        self.assertNotIn("cap_a", rig.request.to_registry_arguments()["granted_capabilities"])

    def test_the_callers_attempt_log_only_receives_the_retry_layers_records(self):
        log = [{"pre": "existing"}]
        rig = Rig(tool="off")
        res = run(rig.plan, rig.request, rig.reg, 3, attempt_log=log)
        self.assertEqual(log[0], {"pre": "existing"})
        self.assertEqual([r["attempt"] for r in log[1:]], [1, 2, 3])
        self.assertEqual(log[1:], res.attempts)
        log[1]["attempt"] = 99                                          # the caller mutating its log cannot change the result
        self.assertEqual(res.attempts[0]["attempt"], 1)
        rejected = []
        run(make_plan(authorized=False), rig.request, rig.reg, 3, attempt_log=rejected)
        self.assertEqual(rejected, [])                                  # an adapter rejection writes nothing at all

    def test_no_fabricated_sequence_number_and_rejections_consume_none(self):
        rig = Rig()
        rejections = (
            run(None, rig.request, rig.reg), run(make_plan(), rig.request, rig.reg, 0),
            run(make_plan(authorized=False), rig.request, rig.reg), run(make_plan(), "bad", rig.reg),
            run(make_plan(), req("off"), rig.reg, 2), run(make_plan(), req("net"), rig.reg, 2),
            run(make_plan(), rig.request, rig.reg, step_id="nope"))
        for res in rejections:
            self.assertEqual((res.status, res.invocation_sequence, res.execution_started), (STATUS_ADAPTER_REJECTED, None, False))
            self.assertTrue(all(a["sequence"] is None and a["invocation_recorded"] is False for a in res.attempts))
        self.assertEqual((rig.reg.invocation_count(), rig.reg.get_invocation_history()), (0, []))
        real = run(make_plan(), rig.request, rig.reg)
        self.assertEqual((real.ok, real.invocation_sequence), (True, 1))                 # the first real invocation gets sequence 1


class TestResultObject(unittest.TestCase):
    def test_result_is_immutable(self):
        res = run(make_plan(), req("echo"), make_registry()[0])
        with self.assertRaises(AttributeError):
            res.status = "failed"
        with self.assertRaises(AttributeError):
            res.new_field = 1
        with self.assertRaises(AttributeError):
            del res.status
        with self.assertRaises(AttributeError):
            res._status = "failed"
        self.assertFalse(hasattr(res, "__dict__"))
        with self.assertRaises(TypeError):
            type("Sub", (AgentToolStepResult,), {})
        with self.assertRaises(TypeError):
            AgentToolStepResult(object(), status="x")
        with self.assertRaises(TypeError):
            pickle.dumps(res)
        self.assertIs(copy.deepcopy(res), res)
        self.assertIs(copy.copy(res), res)
        self.assertRaises(TypeError, hash, res)
        self.assertEqual(res.status, STATUS_ADAPTER_COMPLETED)

    def test_fresh_copies_on_every_read(self):
        rig = Rig(tool="off")
        res = run(rig.plan, rig.request, rig.reg, 2, required_capabilities=None, capability_mapping=None)
        for name in ("failures", "attempts", "preflight"):
            first, second = getattr(res, name), getattr(res, name)
            self.assertEqual(first, second)
            self.assertIsNot(first, second)
        first = res.attempts
        first[0]["attempt"] = 42
        first.append("junk")
        res.failures[0]["code"] = "TAMPERED"
        res.preflight["ok"] = True
        self.assertEqual((res.attempts[0]["attempt"], len(res.attempts), res.failures[0]["code"], res.preflight["ok"]),
                         (1, 2, res.failure_code, False))
        d1, d2 = res.to_dict(), res.to_dict()
        self.assertEqual(d1, d2)
        self.assertIsNot(d1, d2)
        d1["attempts"].clear()
        d1["failures"][0]["code"] = "X"
        self.assertEqual(len(res.to_dict()["attempts"]), 2)
        self.assertEqual(res, run(make_plan(), req("off"), make_registry()[0], 2))

    def test_tool_result_and_mapping_are_fresh_copies_and_isolated_from_handler_output(self):
        shared = {"k": [1]}
        reg, _ = make_registry()
        reg.register(_shared_spec(shared))
        res = run(make_plan(), req("shared"), reg, 2)
        shared["k"].append(2)                                            # the handler's own object changes afterwards
        self.assertEqual(res.tool_result["output"], {"k": [1]})
        out = res.tool_result
        out["output"]["k"].append(99)
        self.assertEqual(res.tool_result["output"], {"k": [1]})
        self.assertIsNot(res.tool_result, res.tool_result)
        rig = Rig(tool="needs_cap", caps=["cap_a"])
        mapped = run(rig.plan, rig.request, rig.reg, 1, required_capabilities=["Needs A"], capability_mapping=MAPPING)
        mapped.mapping["grant_names"].append("x")
        self.assertEqual(mapped.mapping["grant_names"], ["cap_a"])

    def test_result_is_data_only_and_exposes_no_handler_registry_or_internal_reference(self):
        rig = Rig()
        res = run(rig.plan, rig.request, rig.reg, 2)
        json.dumps(res.to_dict())                                        # plain JSON only

        def walk(value):
            self.assertNotIsInstance(value, (type(rig.reg), ToolRequest, type(rig.plan)))
            self.assertFalse(callable(value))
            if isinstance(value, dict):
                for k, v in value.items():
                    walk(k)
                    walk(v)
            elif isinstance(value, (list, tuple)):
                for v in value:
                    walk(v)
        walk(res.to_dict())
        for name in AgentToolStepResult.__slots__:
            value = object.__getattribute__(res, name)
            self.assertNotIn(value, (rig.reg, rig.plan, rig.request))
            self.assertFalse(callable(value), name)
        for attr in ("registry", "handler", "handlers", "request", "plan", "tools", "_tools", "execute", "invoke"):
            self.assertFalse(hasattr(res, attr), attr)

    def test_result_fields_for_every_status(self):
        expected = {STATUS_ADAPTER_COMPLETED: run(make_plan(), req("echo"), make_registry()[0]),
                    STATUS_ADAPTER_FAILED: run(make_plan(), req("boom"), make_registry()[0]),
                    STATUS_ADAPTER_REJECTED: run(None, req("echo"), make_registry()[0], 1)}
        for status, res in expected.items():
            self.assertEqual((res.status, set(res.to_dict())), (status, RESULT_KEYS))
            self.assertEqual(res.ok, status == STATUS_ADAPTER_COMPLETED)
            self.assertEqual(res.failure_code is None, res.ok)
            self.assertEqual(res.failure_source is None, res.ok)
        self.assertEqual(expected[STATUS_ADAPTER_REJECTED].attempts, [])
        self.assertIsNone(expected[STATUS_ADAPTER_REJECTED].tool_result)


def _shared_spec(shared):
    from tools.in_process_tool_registry import ToolSpec
    return ToolSpec(name="shared", description="d", handler=lambda _: shared, input_schema={"type": "object"}, output_description="o")


class TestExecutionEntryPoint(unittest.TestCase):
    def test_the_only_execution_entry_point_is_the_retry_function_and_it_is_called_once(self):
        rig = Rig()
        real = adapter_mod.execute_plan_tool_step_with_retry
        with mock.patch.object(adapter_mod, "execute_plan_tool_step_with_retry", wraps=real) as spy:
            res = run(rig.plan, rig.request, rig.reg, 3, attempt_log=rig.log)
        self.assertTrue(res.ok)
        spy.assert_called_once_with(rig.plan, "s1", rig.request, rig.reg, 3, None, None, rig.log)

    def test_mapped_call_passes_the_callers_pair_unchanged(self):
        rig = Rig(tool="needs_cap", caps=["cap_a"])
        real = adapter_mod.execute_plan_tool_step_with_retry
        with mock.patch.object(adapter_mod, "execute_plan_tool_step_with_retry", wraps=real) as spy:
            run(rig.plan, rig.request, rig.reg, 2, required_capabilities=["Needs A"], capability_mapping=MAPPING)
        args = spy.call_args.args
        self.assertIs(args[5].__class__, list)
        self.assertEqual((args[5], args[6]), (["Needs A"], MAPPING))

    def test_rejections_never_reach_the_retry_function(self):
        rig = Rig()
        with mock.patch.object(adapter_mod, "execute_plan_tool_step_with_retry") as spy:
            for res in (run(None, rig.request, rig.reg), run(make_plan(authorized=False), rig.request, rig.reg),
                        run(make_plan(), rig.request, rig.reg, 0), run(make_plan(), rig.request, rig.reg, step_id="x")):
                self.assertEqual(res.status, STATUS_ADAPTER_REJECTED)
        spy.assert_not_called()

    def test_lower_level_apis_are_not_called_by_the_adapter(self):
        tree = ast.parse(read(ADAPTER_REL))
        called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        called |= {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        for name in ("execute_plan_tool_step", "execute_tool_step", "execute_plan_tool_step_preflighted",
                     "execute_plan_tool_step_mapped", "execute_request", "execute", "invoke", "preflight", "start_plan_step",
                     "complete_plan_step", "fail_plan_step", "create_tool_request", "refresh_plan_step_statuses",
                     "refresh_step_status", "refresh_after_step_change", "update_step_status", "retry_step"):
            self.assertNotIn(name, called, name)
        self.assertIn("execute_plan_tool_step_with_retry", called)
        self.assertEqual(sum(1 for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                             and n.func.id == "execute_plan_tool_step_with_retry"), 1)

    def test_no_direct_section5_registry_import_or_use(self):
        imports = adapter_imports()
        self.assertEqual(imports, ["copy", "planning.plan", "planning.plan_builder", "planning.plan_validation",
                                   "planning.tool_capability_mapping", "planning.tool_step_retry"])
        for mod in imports:
            self.assertNotEqual(mod.split(".")[0], "tools", mod)
            self.assertFalse(mod.startswith(("execution", "agent", "core", "ael")), mod)
        src = read(ADAPTER_REL)
        for word in ("InProcessToolRegistry", "ToolSpec", "import tools", "from tools", "handler(", ".handler", "sqlite3", "threading",
                     "import time", "random", "open(", "global "):
            self.assertNotIn(word, src, word)
        self.assertEqual([m for m in glob.glob(os.path.join(PY_ROOT, "planning", "*.py"))
                          if any(i.split(".")[0] == "tools" for i in _imports_of(m))
                          and os.path.basename(m) != "tool_step_bridge.py"], [])          # the bridge stays the only importer of tools


def _imports_of(path):
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    found = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module]
    return found + [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]


class TestStatelessness(unittest.TestCase):
    def test_module_holds_no_mutable_module_state(self):
        for name, value in vars(adapter_mod).items():
            if name.startswith("__") or inspect.ismodule(value) or inspect.isclass(value) or inspect.isfunction(value):
                continue
            self.assertIsInstance(value, (str, int, tuple, type(None), object), name)
            self.assertNotIsInstance(value, (list, dict, set, bytearray), name)
        tree = ast.parse(read(ADAPTER_REL))
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, ast.Global)], [])

    def test_identical_inputs_give_equal_results_and_calls_are_independent(self):
        first = run(make_plan(), req("echo", {"a": 1}), make_registry()[0], 2)
        second = run(make_plan(), req("echo", {"a": 1}), make_registry()[0], 2)
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        reg, _ = make_registry()
        one = run(make_plan(), req("echo"), reg)
        other = run(make_plan(), req("echo"), reg)
        self.assertEqual((one.invocation_sequence, other.invocation_sequence), (1, 2))       # only the registry keeps a counter


class TestUntouchedLayers(unittest.TestCase):
    def test_legacy_execution_engine_and_agent_loop_are_untouched(self):
        files = sorted(os.path.relpath(f, PY_ROOT).replace(os.sep, "/") for f in glob.glob(os.path.join(PY_ROOT, "execution", "*.py")))
        files.append("agent/agent_loop.py")
        self.assertEqual((digest(files), len(files)), (FROZEN_LEGACY_DIGEST, 27))
        from execution.execution_engine import ExecutionEngine
        self.assertTrue(callable(getattr(ExecutionEngine, "retry_step", None)))               # legacy retry_step is left alone
        for path in glob.glob(os.path.join(PY_ROOT, "execution", "*.py")):
            text = read(os.path.relpath(path, PY_ROOT))
            for token in ("tool_step_agent_adapter", "execute_agent_tool_step", "tool_step_"):
                self.assertNotIn(token, text, path)

    def test_agent_loop_is_untouched_and_does_not_know_the_adapter(self):
        self.assertEqual(hashlib.sha256(_baseline_file_bytes("agent/agent_loop.py")).hexdigest(), FROZEN_AGENT_LOOP_SHA256)   # Prompt 719-C
        text = _baseline_file_bytes("agent/agent_loop.py").decode("utf-8")                                                 # Prompt 719-C
        for token in ("tool_step", "execute_agent_tool_step", "AgentToolStepResult"):
            self.assertNotIn(token, text)
        from agent.agent_loop import AgentLoop
        self.assertNotIn("execute_agent_tool_step", inspect.getsource(AgentLoop.run))

    def test_process_input_is_not_wired_and_nothing_else_references_the_adapter(self):
        for path in glob.glob(os.path.join(PY_ROOT, "**", "*.py"), recursive=True):
            rel = os.path.relpath(path, PY_ROOT).replace(os.sep, "/")
            if rel.startswith("tests/") or rel == ADAPTER_REL:
                continue
            text = read(rel)
            for token in ("tool_step_agent_adapter", "execute_agent_tool_step", "AgentToolStepResult"):
                self.assertNotIn(token, text, rel)
        tree = ast.parse(read(ADAPTER_REL))
        code_names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertEqual({n for n in code_names if "process_input" in n or "AgentLoop" in n}, set())

    def test_plan_manager_refresh_methods_are_untouched_and_never_called(self):
        with open(os.path.join(PY_ROOT, "planning", "plan_manager.py"), "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), FROZEN_PLAN_MANAGER_SHA256)
        tree = ast.parse(read(ADAPTER_REL))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertFalse({n for n in names if "refresh" in n.lower()} | ({"PlanManager"} & names))
        rig = Rig()
        with mock.patch.object(PlanManager, "refresh_plan_step_statuses", side_effect=AssertionError), \
                mock.patch.object(PlanManager, "refresh_step_status", side_effect=AssertionError), \
                mock.patch.object(PlanManager, "refresh_after_step_change", side_effect=AssertionError):
            self.assertTrue(run(rig.plan, rig.request, rig.reg).ok)
            self.assertEqual(run(make_plan(), rig.request, rig.reg, 0).status, STATUS_ADAPTER_REJECTED)

    def test_section4_and_section5_production_files_are_unchanged(self):
        files = sorted(os.path.relpath(f, PY_ROOT).replace(os.sep, "/")
                       for f in glob.glob(os.path.join(PY_ROOT, "planning", "*.py")) + glob.glob(os.path.join(PY_ROOT, "tools", "*.py"))
                       if not any(k in f for k in ("tool_step_", "tool_capability_mapping")))
        self.assertEqual((digest(files), len(files)), (FROZEN_SECTION45_DIGEST, 31))

    def test_earlier_section6_modules_are_unchanged(self):
        from tests.test_section6_agent_loop_handover_decision_prompt713 import FROZEN_SECTION6_DIGEST, SECTION6
        self.assertEqual(digest(sorted(SECTION6)), FROZEN_SECTION6_DIGEST)

    def test_pristine_database_hash(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


class TestDocumentation(unittest.TestCase):
    def test_document_exists_and_covers_the_required_topics(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT)))), "docs",
                            "section6_agent_loop_adapter_prompt714.md")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        for phrase in ("execute_agent_tool_step", "execute_plan_tool_step_with_retry", "Why this adapter exists",
                       "Why AgentLoop is not modified", "Why legacy `ready`", "Future Agent Loop", "must NOT be called directly",
                       "MAX_ADAPTER_ATTEMPTS", "validate_plan_step_states", "ADAPTER_LEGACY_STEP_STATE"):
            self.assertIn(phrase, text, phrase)


if __name__ == "__main__":
    unittest.main()
