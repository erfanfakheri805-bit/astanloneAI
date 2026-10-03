"""Prompt 710 - Section 6 explicit capability mapping contract (F2).

Focused tests for `planning/tool_capability_mapping.py` (pure translation: Section 4 `required_capabilities` -> Section 5 grant names)
and its only integration point `execute_plan_tool_step_mapped()` in `planning/tool_step_executor.py`, a gate in front of the unchanged
Prompt 709 `execute_plan_tool_step_preflighted()`. Mapping is translation, never authorization; Section 5 stays the final authority.
"""
import ast
import copy
import hashlib
import inspect
import os
import unittest

from planning import tool_capability_mapping as map_mod
from planning import tool_step_executor as exec_mod
from planning.tool_capability_mapping import (MAPPING_CONFLICTING_ENTRY, MAPPING_DUPLICATE_ENTRY, MAPPING_DUPLICATE_GRANT,
                                              MAPPING_EMPTY_CAPABILITY, MAPPING_EMPTY_GRANTS, MAPPING_INVALID_ENTRY,
                                              MAPPING_INVALID_GRANT_NAME, MAPPING_INVALID_GRANTS, MAPPING_INVALID_REQUIRED,
                                              MAPPING_INVALID_STRUCTURE, MAPPING_UNMAPPED, STATUS_INVALID_INPUT,
                                              STATUS_INVALID_MAPPING, STATUS_SATISFIED, STATUS_UNMAPPED,
                                              CapabilityMappingResult, find_ungranted_capabilities,
                                              map_required_capabilities)
from planning.tool_step_executor import (OUTCOME_COMPLETED, OUTCOME_PRE_REGISTRY_REJECTION, OUTCOME_REGISTRY_PREFLIGHT_REJECTION,
                                         PRESTART_CAPABILITY_MAPPING_REJECTED, PRESTART_INVALID_REJECTION_LOG,
                                         PRESTART_MAPPED_GRANT_NOT_SUPPLIED, REJECTION_RECORD_TYPE, STATUS_TOOL_STEP_COMPLETED,
                                         STATUS_TOOL_STEP_REJECTED, PreflightedToolStepResult,
                                         execute_plan_tool_step_mapped, execute_plan_tool_step_preflighted)
from tools.in_process_tool_registry import (InProcessToolRegistry, TOOL_CAPABILITY_MISSING, TOOL_CONFIRMATION_REQUIRED,
                                            TOOL_DISABLED, TOOL_PERMISSION_DENIED, TOOL_UNKNOWN, _NAME_RE)
from tests.test_section6_tool_step_executor_prompt708 import make_plan, make_registry, req, snapshot, step_of
from tests.test_section6_tool_step_preflight_prompt709 import registry_state, spy_registry_class

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"

RESULT_KEYS = {"ok", "status", "required", "resolved", "grant_names", "missing", "invalid_entries", "failures"}


def entry(cap, *grants):
    return {"capability": cap, "grants": list(grants)}


def run_mapped(plan, request, reg, required, mapping, step_id="s1", log=None):
    return execute_plan_tool_step_mapped(plan, step_id, request, reg, required, mapping, log)


# ---------------------------------------------------------------------------------------------------------------------
# the pure mapper
# ---------------------------------------------------------------------------------------------------------------------

class TestMapper(unittest.TestCase):
    def test_one_to_one_mapping(self):
        res = map_required_capabilities(["Read Files"], [entry("Read Files", "fs_read")])
        self.assertIsInstance(res, CapabilityMappingResult)
        self.assertTrue(res.ok)
        self.assertEqual((res.status, res.required, res.grant_names, res.missing, res.invalid_entries, res.failures),
                         (STATUS_SATISFIED, ("Read Files",), ("fs_read",), (), [], []))
        self.assertEqual(res.resolved, (("Read Files", ("fs_read",)),))

    def test_one_to_many_mapping_keeps_entry_order(self):
        res = map_required_capabilities(["deploy"], [entry("deploy", "net_access", "cap_a", "fs_write")])
        self.assertTrue(res.ok)
        self.assertEqual(res.grant_names, ("net_access", "cap_a", "fs_write"))
        self.assertEqual(res.resolved, (("deploy", ("net_access", "cap_a", "fs_write")),))

    def test_multiple_section4_requirements(self):
        mapping = [entry("b", "g_b1", "shared"), entry("a", "g_a", "shared"), entry("unused", "never")]
        res = map_required_capabilities(["a", "b"], mapping)
        self.assertTrue(res.ok)
        self.assertEqual(res.required, ("a", "b"))
        self.assertEqual(res.grant_names, ("g_a", "shared", "g_b1"))        # required order, shared grant once
        self.assertEqual([c for c, _ in res.resolved], ["a", "b"])
        self.assertNotIn("never", res.grant_names)                           # entries nobody asked for are ignored

    def test_unmapped_requirement_is_reported_not_dropped(self):
        res = map_required_capabilities(["a", "ghost", "b", "phantom"], [entry("a", "g_a"), entry("b", "g_b")])
        self.assertFalse(res.ok)
        self.assertEqual(res.status, STATUS_UNMAPPED)
        self.assertEqual(res.missing, ("ghost", "phantom"))
        self.assertEqual(res.required, ("a", "ghost", "b", "phantom"))       # nothing silently dropped
        self.assertEqual(res.grant_names, ("g_a", "g_b"))                    # the mapped part is still reported
        self.assertEqual(res.codes(), [MAPPING_UNMAPPED, MAPPING_UNMAPPED])
        self.assertEqual([f["capability"] for f in res.failures], ["ghost", "phantom"])

    def test_empty_required_and_empty_mapping_are_valid(self):
        res = map_required_capabilities([], [])
        self.assertTrue(res.ok)
        self.assertEqual((res.required, res.grant_names, res.missing), ((), (), ()))
        self.assertFalse(map_required_capabilities(["x"], []).ok)
        self.assertEqual(map_required_capabilities(["x"], []).status, STATUS_UNMAPPED)

    def test_repeated_required_name_is_one_requirement(self):
        res = map_required_capabilities(["a", "a", "b"], [entry("a", "g_a"), entry("b", "g_b")])
        self.assertEqual((res.required, res.grant_names), (("a", "b"), ("g_a", "g_b")))

    def test_no_case_folding_or_trimming_of_section4_names(self):
        res = map_required_capabilities(["Read"], [entry("read", "fs_read")])
        self.assertEqual((res.status, res.missing), (STATUS_UNMAPPED, ("Read",)))
        res = map_required_capabilities(["read "], [entry("read", "fs_read")])
        self.assertEqual(res.status, STATUS_UNMAPPED)

    def test_tuples_are_accepted_but_sets_and_dicts_are_not(self):
        self.assertTrue(map_required_capabilities(("a",), ({"capability": "a", "grants": ("g",)},)).ok)
        self.assertEqual(map_required_capabilities({"a"}, []).status, STATUS_INVALID_INPUT)
        self.assertEqual(map_required_capabilities(["a"], {"a": ["g"]}).codes(), [MAPPING_INVALID_STRUCTURE])
        self.assertEqual(map_required_capabilities(["a"], [entry("a", "g")]).grant_names, ("g",))
        res = map_required_capabilities(["a"], [{"capability": "a", "grants": {"g1", "g2"}}])
        self.assertEqual(res.codes(), [MAPPING_INVALID_GRANTS])              # a set has no order -> refused

    def test_invalid_required_capabilities(self):
        for bad in (None, "a", 5, ["a", ""], ["a", "   "], ["a", 3], ["a", None], [["a"]], {"a": 1}):
            res = map_required_capabilities(bad, [entry("a", "g")])
            self.assertFalse(res.ok, bad)
            self.assertEqual((res.status, res.codes()), (STATUS_INVALID_INPUT, [MAPPING_INVALID_REQUIRED]), bad)
            self.assertEqual((res.grant_names, res.resolved), ((), ()))

    def test_invalid_mapping_structures(self):
        for bad in (None, "a", 5, {"capability": "a", "grants": ["g"]}, {"a"}):
            res = map_required_capabilities(["a"], bad)
            self.assertEqual((res.status, res.codes()), (STATUS_INVALID_MAPPING, [MAPPING_INVALID_STRUCTURE]), bad)
            self.assertEqual((res.grant_names, res.resolved, res.missing), ((), (), ()))
        for bad_entry in ("a", None, ["a", "g"], {"capability": "a"}, {"grants": ["g"]},
                          {"capability": "a", "grants": ["g"], "extra": 1}, {"cap": "a", "grants": ["g"]}):
            res = map_required_capabilities(["a"], [bad_entry])
            self.assertEqual((res.status, res.codes()), (STATUS_INVALID_MAPPING, [MAPPING_INVALID_ENTRY]), bad_entry)

    def test_empty_names_and_empty_or_malformed_grants(self):
        for name in ("", "   ", None, 3):
            res = map_required_capabilities(["a"], [{"capability": name, "grants": ["g"]}])
            self.assertEqual(res.codes(), [MAPPING_EMPTY_CAPABILITY], name)
        self.assertEqual(map_required_capabilities(["a"], [entry("a")]).codes(), [MAPPING_EMPTY_GRANTS])
        for grants in ("g", None, 5, {"g": 1}):
            res = map_required_capabilities(["a"], [{"capability": "a", "grants": grants}])
            self.assertEqual(res.codes(), [MAPPING_INVALID_GRANTS], grants)

    def test_invalid_section5_capability_names(self):
        for bad in ("", "Upper", "1abc", "has space", "dash-ed", "trailing\n", "x" * 65, "_lead", None, 7):
            res = map_required_capabilities(["a"], [{"capability": "a", "grants": ["ok_name", bad]}])
            self.assertEqual((res.status, res.codes()), (STATUS_INVALID_MAPPING, [MAPPING_INVALID_GRANT_NAME]), repr(bad))
        self.assertTrue(map_required_capabilities(["a"], [entry("a", "x" * 64)]).ok)          # 64 chars is the limit

    def test_duplicate_and_conflicting_mappings(self):
        dup = map_required_capabilities(["a"], [entry("a", "g"), entry("a", "g")])
        self.assertEqual((dup.status, dup.codes()), (STATUS_INVALID_MAPPING, [MAPPING_DUPLICATE_ENTRY]))
        conflict = map_required_capabilities(["a"], [entry("a", "g1"), entry("a", "g2")])
        self.assertEqual(conflict.codes(), [MAPPING_CONFLICTING_ENTRY])
        reordered = map_required_capabilities(["a"], [entry("a", "g1", "g2"), entry("a", "g2", "g1")])
        self.assertEqual(reordered.codes(), [MAPPING_CONFLICTING_ENTRY])       # different order is a different mapping
        self.assertEqual(conflict.grant_names, ())                             # never "last wins" / "first wins"
        same_grant = map_required_capabilities(["a"], [entry("a", "g", "g")])
        self.assertEqual(same_grant.codes(), [MAPPING_DUPLICATE_GRANT])

    def test_invalid_entry_makes_the_whole_mapping_unusable_even_for_other_names(self):
        res = map_required_capabilities(["good"], [entry("good", "g_ok"), entry("bad", "BAD NAME")])
        self.assertEqual(res.status, STATUS_INVALID_MAPPING)
        self.assertEqual((res.grant_names, res.resolved), ((), ()))            # no partial translation from a broken mapping
        self.assertEqual(res.invalid_entries[0]["index"], 1)

    def test_all_problems_are_reported_at_once_in_entry_order(self):
        res = map_required_capabilities(["a"], [{"capability": "", "grants": []}, "x", entry("a", "Bad"), entry("b", "g"),
                                                entry("b", "h")])
        self.assertEqual(res.codes(), [MAPPING_EMPTY_CAPABILITY, MAPPING_EMPTY_GRANTS, MAPPING_INVALID_ENTRY,
                                       MAPPING_INVALID_GRANT_NAME, MAPPING_CONFLICTING_ENTRY])

    def test_invalid_entry_for_a_name_blocks_it_even_if_another_entry_is_valid(self):
        res = map_required_capabilities(["a"], [entry("a", "good"), entry("a", "BAD")])
        self.assertEqual(res.status, STATUS_INVALID_MAPPING)
        self.assertEqual(res.grant_names, ())

    def test_deterministic_ordering_and_repeatability(self):
        mapping = [entry("z", "g_z"), entry("a", "g_a", "g_shared"), entry("m", "g_shared", "g_m")]
        first = map_required_capabilities(["m", "z", "a"], mapping).to_dict()
        for _ in range(5):
            self.assertEqual(map_required_capabilities(["m", "z", "a"], mapping).to_dict(), first)
        self.assertEqual(first["grant_names"], ["g_shared", "g_m", "g_z", "g_a"])
        self.assertEqual(first["required"], ["m", "z", "a"])
        again = map_required_capabilities(["m", "z", "a"], list(reversed(mapping)))     # entry order does not change the result
        self.assertEqual(again.to_dict(), first)

    def test_mapping_does_not_mutate_input(self):
        required = ["a", "b", "a"]
        mapping = [entry("a", "g_a"), entry("b", "g_b1", "g_b2")]
        before = (copy.deepcopy(required), copy.deepcopy(mapping))
        res = map_required_capabilities(required, mapping)
        self.assertEqual((required, mapping), before)
        res.invalid_entries.append("x")
        res.failures.append("x")
        res.to_dict()["grant_names"].append("x")
        self.assertEqual(res.grant_names, ("g_a", "g_b1", "g_b2"))
        mapping[0]["grants"].append("later")                                      # later caller edits change nothing
        self.assertEqual(res.grant_names, ("g_a", "g_b1", "g_b2"))
        bad = map_required_capabilities(["a"], [entry("a", "BAD")])
        before_bad = copy.deepcopy([entry("a", "BAD")])
        self.assertEqual(before_bad, [entry("a", "BAD")])
        self.assertEqual(bad.status, STATUS_INVALID_MAPPING)

    def test_result_is_immutable_plain_data(self):
        res = map_required_capabilities(["a"], [entry("a", "g")])
        for attr in ("status", "grant_names", "required"):
            with self.assertRaises(AttributeError):
                setattr(res, attr, "x")
        with self.assertRaises(AttributeError):
            delattr(res, "status")
        self.assertFalse(hasattr(res, "__dict__"))
        self.assertEqual(set(res.to_dict()), RESULT_KEYS)
        for r in (res, map_required_capabilities(None, []), map_required_capabilities(["x"], []),
                  map_required_capabilities(["a"], None)):
            self.assertEqual(set(r.to_dict()), RESULT_KEYS)

    def test_mapper_cannot_invent_a_grant(self):
        res = map_required_capabilities(["a", "b"], [entry("a", "g_a")])
        self.assertEqual(res.grant_names, ("g_a",))                              # no grant for the unmapped "b"
        self.assertEqual(map_required_capabilities([], [entry("a", "g_a")]).grant_names, ())
        self.assertEqual(map_required_capabilities(["a"], [entry("a", "g_a")]).grant_names, ("g_a",))
        # nothing about the name itself is turned into a grant: "Read Files" does not become "read_files"
        self.assertEqual(map_required_capabilities(["Read Files"], []).grant_names, ())
        # and the mapper has no access to grants at all
        self.assertEqual(list(inspect.signature(map_required_capabilities).parameters), ["required_capabilities", "mapping"])

    def test_find_ungranted_reports_only_missing_mapped_grants(self):
        res = map_required_capabilities(["a", "b"], [entry("a", "g1", "g2"), entry("b", "g3")])
        self.assertEqual(find_ungranted_capabilities(res, ["g1", "g2", "g3"]), ())
        self.assertEqual(find_ungranted_capabilities(res, ["g3", "g1", "extra", "more"]), ("g2",))
        self.assertEqual(find_ungranted_capabilities(res, []), ("g1", "g2", "g3"))
        granted = ["g1"]
        find_ungranted_capabilities(res, granted)
        self.assertEqual(granted, ["g1"])

    def test_section5_name_rule_is_identical_to_the_registry_rule(self):
        self.assertEqual(map_mod._GRANT_NAME_RE.pattern, _NAME_RE.pattern)
        self.assertEqual(map_mod._GRANT_NAME_RE.flags, _NAME_RE.flags)


# ---------------------------------------------------------------------------------------------------------------------
# the integration at the preflighted boundary
# ---------------------------------------------------------------------------------------------------------------------

MAPPING = [entry("Needs A", "cap_a")]


class TestMappedPreflight(unittest.TestCase):
    def test_successful_mapped_preflight_and_execution(self):
        calls = []
        reg, h = make_registry(spy_registry_class(calls))
        plan = make_plan()
        request = req("needs_cap", {"a": 1}, caps=["cap_a"])
        res = run_mapped(plan, request, reg, ["Needs A"], MAPPING)
        self.assertIsInstance(res, PreflightedToolStepResult)
        self.assertTrue(res.ok)
        self.assertEqual((res.status, res.outcome_kind, res.previous_state, res.final_state),
                         (STATUS_TOOL_STEP_COMPLETED, OUTCOME_COMPLETED, "pending", "completed"))
        self.assertEqual((res.preflight_called, res.execution_called, res.rejection_record, res.failures), (True, True, None, []))
        self.assertEqual(calls, ["preflight", "execute_request", "execute", "invoke"])
        self.assertEqual((h["needs_cap"].count, reg.invocation_count()), (1, 1))
        self.assertEqual(step_of(plan, "s1").status, "completed")

    def test_success_is_identical_to_the_unmapped_preflighted_call(self):
        reg_a, _ = make_registry()
        reg_b, _ = make_registry()
        plan_a, plan_b = make_plan(), make_plan()
        mapped = run_mapped(plan_a, req("needs_cap", caps=["cap_a"]), reg_a, ["Needs A"], MAPPING)
        plain = execute_plan_tool_step_preflighted(plan_b, "s1", req("needs_cap", caps=["cap_a"]), reg_b)
        self.assertEqual(mapped.to_dict(), plain.to_dict())
        self.assertEqual(snapshot(plan_a), snapshot(plan_b))
        self.assertEqual(reg_a.get_invocation_history(), reg_b.get_invocation_history())

    def test_empty_requirements_pass_through_to_the_normal_flow(self):
        reg, h = make_registry()
        plan = make_plan()
        res = run_mapped(plan, req("echo", {"k": 1}), reg, [], [])
        self.assertTrue(res.ok)
        self.assertEqual(h["echo"].count, 1)

    def test_multiple_requirements_one_to_many_all_granted(self):
        reg, h = make_registry()
        plan = make_plan()
        mapping = [entry("Needs A", "cap_a", "extra_x"), entry("Other", "extra_y")]
        res = run_mapped(plan, req("needs_cap", caps=["extra_y", "extra_x", "cap_a"]), reg, ["Needs A", "Other"], mapping)
        self.assertTrue(res.ok)
        self.assertEqual(h["needs_cap"].count, 1)

    def test_unmapped_requirement_rejects_before_start(self):
        calls = []
        reg, h = make_registry(spy_registry_class(calls))
        plan = make_plan()
        before, reg_before = snapshot(plan), registry_state(reg)
        log = []
        res = run_mapped(plan, req("needs_cap", caps=["cap_a"]), reg, ["Needs A", "Ghost"], MAPPING, log=log)
        self.assertFalse(res.ok)
        self.assertEqual((res.status, res.outcome_kind), (STATUS_TOOL_STEP_REJECTED, OUTCOME_PRE_REGISTRY_REJECTION))
        self.assertEqual((res.previous_state, res.final_state, res.preflight_called, res.execution_called),
                         ("pending", "pending", False, False))
        self.assertEqual(res.codes(), [PRESTART_CAPABILITY_MAPPING_REJECTED, map_mod.MAPPING_UNMAPPED])
        self.assertEqual(res.failures[0]["capability_mapping"]["missing"], ["Ghost"])
        self.assertEqual(res.failures[0]["capability_mapping"]["status"], STATUS_UNMAPPED)
        self.assertEqual(res.failures[1]["capability"], "Ghost")
        self.assertEqual((snapshot(plan), registry_state(reg), calls, h["needs_cap"].count), (before, reg_before, [], 0))
        self.assertEqual(step_of(plan, "s1").status, "pending")
        self.assertEqual((res.rejection_record["record_type"], res.rejection_record["invocation_recorded"],
                          res.rejection_record["sequence"]), (REJECTION_RECORD_TYPE, False, None))
        self.assertEqual(log, [res.rejection_record])
        self.assertIsNone(res.sequence)

    def test_invalid_mapping_and_invalid_required_reject_before_start(self):
        for required, mapping, code in ((["Needs A"], [entry("Needs A", "BAD NAME")], map_mod.MAPPING_INVALID_GRANT_NAME),
                                        (["Needs A"], None, MAPPING_INVALID_STRUCTURE),
                                        (["Needs A"], [entry("Needs A", "cap_a"), entry("Needs A", "cap_b")],
                                         MAPPING_CONFLICTING_ENTRY),
                                        ([""], MAPPING, MAPPING_INVALID_REQUIRED),
                                        (None, MAPPING, MAPPING_INVALID_REQUIRED)):
            calls = []
            reg, h = make_registry(spy_registry_class(calls))
            plan = make_plan()
            before = snapshot(plan)
            res = run_mapped(plan, req("needs_cap", caps=["cap_a", "cap_b"]), reg, required, mapping)
            self.assertEqual((res.status, res.outcome_kind, res.final_state), (STATUS_TOOL_STEP_REJECTED,
                                                                                OUTCOME_PRE_REGISTRY_REJECTION, "pending"))
            self.assertEqual(res.codes()[0], PRESTART_CAPABILITY_MAPPING_REJECTED)
            self.assertIn(code, res.codes())
            self.assertEqual((snapshot(plan), calls, h["needs_cap"].count, reg.invocation_count()), (before, [], 0, 0))

    def test_missing_caller_grant_rejects_before_start_and_grants_nothing(self):
        calls = []
        reg, h = make_registry(spy_registry_class(calls))
        plan = make_plan()
        before = snapshot(plan)
        request = req("needs_cap", caps=["unrelated"])
        request_before = request.to_dict()
        res = run_mapped(plan, request, reg, ["Needs A"], MAPPING)
        self.assertEqual((res.status, res.outcome_kind, res.final_state), (STATUS_TOOL_STEP_REJECTED,
                                                                            OUTCOME_PRE_REGISTRY_REJECTION, "pending"))
        self.assertEqual(res.codes(), [PRESTART_MAPPED_GRANT_NOT_SUPPLIED])
        self.assertEqual(res.failures[0]["missing_grants"], ["cap_a"])
        self.assertEqual(res.failures[0]["capability_mapping"]["grant_names"], ["cap_a"])
        self.assertEqual((res.preflight_called, res.execution_called), (False, False))
        self.assertEqual((snapshot(plan), calls, h["needs_cap"].count, reg.invocation_count()), (before, [], 0, 0))
        self.assertEqual(request.to_dict(), request_before)                          # the request was not "repaired"
        self.assertEqual(request.granted_capabilities, ("unrelated",))
        self.assertEqual(reg.invocation_count(), 0)

    def test_partially_granted_one_to_many_is_rejected(self):
        reg, h = make_registry()
        plan = make_plan()
        res = run_mapped(plan, req("needs_cap", caps=["cap_a"]), reg, ["Needs A"], [entry("Needs A", "cap_a", "cap_b")])
        self.assertEqual(res.codes(), [PRESTART_MAPPED_GRANT_NOT_SUPPLIED])
        self.assertEqual(res.failures[0]["missing_grants"], ["cap_b"])
        self.assertEqual(h["needs_cap"].count, 0)

    def test_no_grants_at_all_is_rejected_when_something_is_required(self):
        reg, h = make_registry()
        res = run_mapped(make_plan(), req("needs_cap"), reg, ["Needs A"], MAPPING)
        self.assertEqual(res.codes(), [PRESTART_MAPPED_GRANT_NOT_SUPPLIED])
        self.assertEqual(h["needs_cap"].count, 0)

    def test_extra_caller_grants_are_kept_and_not_removed(self):
        seen = []

        class Watch(InProcessToolRegistry):
            def preflight(self, *a, **k):
                seen.append(list(k["granted_capabilities"]))
                return super().preflight(*a, **k)
        reg, h = make_registry(Watch)
        plan = make_plan()
        request = req("needs_cap", caps=["zzz_extra", "cap_a", "another"])
        res = run_mapped(plan, request, reg, ["Needs A"], MAPPING)
        self.assertTrue(res.ok)
        self.assertEqual(seen, [["zzz_extra", "cap_a", "another"]])                  # exactly the caller's grants, extras included
        self.assertEqual(reg.get_invocation_history()[0]["granted_capabilities"], ["another", "cap_a", "zzz_extra"])
        self.assertEqual(request.granted_capabilities, ("zzz_extra", "cap_a", "another"))

    def test_mapped_capability_rejection_by_section5_is_reported_and_step_stays_pending(self):
        # mapping translates and the caller granted the mapped name, but the TOOL needs cap_a: Section 5 says no.
        reg, h = make_registry()
        plan = make_plan()
        before = snapshot(plan)
        res = run_mapped(plan, req("needs_cap", caps=["cap_b"]), reg, ["Wrong"], [entry("Wrong", "cap_b")])
        self.assertEqual((res.status, res.outcome_kind, res.final_state), (STATUS_TOOL_STEP_REJECTED,
                                                                            OUTCOME_REGISTRY_PREFLIGHT_REJECTION, "pending"))
        self.assertEqual(res.reason, TOOL_CAPABILITY_MISSING)
        self.assertTrue(res.preflight_called)
        self.assertFalse(res.execution_called)
        self.assertEqual(res.preflight["missing_capabilities"], ["cap_a"])
        self.assertEqual((snapshot(plan), h["needs_cap"].count, reg.invocation_count()), (before, 0, 0))
        self.assertEqual(res.rejection_record["rejection_kind"], OUTCOME_REGISTRY_PREFLIGHT_REJECTION)

    def test_section5_remains_the_final_authority_over_permissions_and_tools(self):
        reg, h = make_registry()
        # a satisfied mapping never bypasses permission / confirmation / unknown tool / disabled tool checks
        for request, expected in ((req("net", caps=["cap_a"]), TOOL_PERMISSION_DENIED),
                                  (req("confirm", caps=["cap_a"]), TOOL_CONFIRMATION_REQUIRED),
                                  (req("ghost_tool", caps=["cap_a"]), TOOL_UNKNOWN),
                                  (req("off", caps=["cap_a"]), TOOL_DISABLED)):
            plan = make_plan()
            res = run_mapped(plan, request, reg, ["Needs A"], MAPPING)
            self.assertEqual((res.outcome_kind, res.reason, res.final_state), (OUTCOME_REGISTRY_PREFLIGHT_REJECTION, expected,
                                                                                "pending"), expected)
        self.assertEqual(sum(c.count for c in h.values()), 0)
        self.assertEqual(reg.invocation_count(), 0)

    def test_mapping_cannot_invent_a_grant_at_the_boundary(self):
        # the tool needs cap_a; the mapping says "Needs A" -> cap_a; the caller granted nothing: the gate refuses, Section 5 never
        # sees a manufactured grant, and no invocation is recorded.
        calls = []
        reg, h = make_registry(spy_registry_class(calls))
        res = run_mapped(make_plan(), req("needs_cap"), reg, ["Needs A"], MAPPING)
        self.assertFalse(res.ok)
        self.assertEqual((calls, h["needs_cap"].count, reg.invocation_count()), ([], 0, 0))
        # even with the tool's own capability unrelated to the mapping, nothing is added to what the caller supplied
        res = run_mapped(make_plan(), req("needs_cap", caps=["cap_b"]), reg, ["Wrong"], [entry("Wrong", "cap_b")])
        self.assertEqual(res.preflight["granted_capabilities"], ["cap_b"])

    def test_pre_start_rejection_leaves_the_step_pending_and_it_can_run_afterwards(self):
        reg, h = make_registry()
        plan = make_plan()
        first = run_mapped(plan, req("needs_cap"), reg, ["Needs A"], MAPPING)
        self.assertEqual(first.final_state, "pending")
        self.assertEqual(step_of(plan, "s1").status, "pending")
        second = run_mapped(plan, req("needs_cap", caps=["cap_a"]), reg, ["Needs A"], MAPPING)      # caller fixed the request
        self.assertTrue(second.ok)
        self.assertEqual((h["needs_cap"].count, step_of(plan, "s1").status), (1, "completed"))

    def test_no_handler_call_on_any_mapping_failure(self):
        reg, h = make_registry()
        plan = make_plan()
        cases = ((["Ghost"], MAPPING, ["cap_a"]), (["Needs A"], "bad", ["cap_a"]), (["Needs A"], MAPPING, []),
                 ("bad", MAPPING, ["cap_a"]))
        for required, mapping, caps in cases:
            run_mapped(plan, req("needs_cap", caps=caps), reg, required, mapping)
        self.assertEqual(sum(c.count for c in h.values()), 0)
        self.assertEqual((reg.invocation_count(), reg.get_invocation_history()), (0, []))
        self.assertEqual(step_of(plan, "s1").status, "pending")

    def test_mapping_does_not_mutate_request_grants_plan_or_inputs(self):
        reg, _ = make_registry()
        plan = make_plan()
        request = req("needs_cap", {"k": [1]}, caps=["cap_a", "extra"])
        required, mapping = ["Needs A"], [entry("Needs A", "cap_a")]
        before = (request.to_dict(), copy.deepcopy(required), copy.deepcopy(mapping))
        res = run_mapped(plan, request, reg, required, mapping)
        self.assertTrue(res.ok)
        self.assertEqual((request.to_dict(), required, mapping), before)
        # rejected path too
        request2 = req("needs_cap", caps=["extra"])
        before2 = request2.to_dict()
        run_mapped(make_plan(), request2, reg, required, mapping)
        self.assertEqual((request2.to_dict(), required, mapping), (before2, before[1], before[2]))

    def test_rejection_log_and_argument_guards_come_first(self):
        reg, h = make_registry()
        res = run_mapped(make_plan(), req("needs_cap", caps=["cap_a"]), reg, ["Needs A"], MAPPING, log="not a list")
        self.assertEqual(res.codes(), [PRESTART_INVALID_REJECTION_LOG])
        res = run_mapped(make_plan(), "not a request", reg, ["Needs A"], MAPPING)
        self.assertEqual(res.outcome_kind, OUTCOME_PRE_REGISTRY_REJECTION)
        self.assertNotIn(PRESTART_CAPABILITY_MAPPING_REJECTED, res.codes())
        res = run_mapped(make_plan(), req("needs_cap", caps=["cap_a"]), reg, ["Needs A"], MAPPING, step_id="nope")
        self.assertEqual(res.outcome_kind, OUTCOME_PRE_REGISTRY_REJECTION)
        self.assertEqual(h["needs_cap"].count, 0)

    def test_plan_context_still_judged_by_section4_after_a_satisfied_mapping(self):
        reg, h = make_registry()
        plan = make_plan(authorized=False)
        res = run_mapped(plan, req("needs_cap", caps=["cap_a"]), reg, ["Needs A"], MAPPING)
        self.assertEqual((res.status, res.outcome_kind, res.final_state), (STATUS_TOOL_STEP_REJECTED,
                                                                            OUTCOME_PRE_REGISTRY_REJECTION, "pending"))
        self.assertEqual(h["needs_cap"].count, 0)
        self.assertFalse(res.preflight_called)

    def test_rejection_log_receives_one_record_per_mapping_rejection(self):
        reg, _ = make_registry()
        log = []
        run_mapped(make_plan(), req("needs_cap"), reg, ["Needs A"], MAPPING, log=log)
        run_mapped(make_plan(), req("needs_cap", caps=["cap_a"]), reg, ["Ghost"], MAPPING, log=log)
        run_mapped(make_plan(), req("needs_cap", caps=["cap_a"]), reg, ["Needs A"], MAPPING, log=log)     # success: no record
        self.assertEqual([r["codes"][0] for r in log], [PRESTART_MAPPED_GRANT_NOT_SUPPLIED, PRESTART_CAPABILITY_MAPPING_REJECTED])
        self.assertTrue(all(r["record_type"] == REJECTION_RECORD_TYPE and r["sequence"] is None for r in log))

    def test_result_to_dict_shape_is_the_unchanged_709_shape(self):
        reg, _ = make_registry()
        res = run_mapped(make_plan(), req("needs_cap"), reg, ["Needs A"], MAPPING)
        self.assertEqual(set(res.to_dict()), {"ok", "status", "outcome_kind", "step_id", "tool_name", "previous_state",
                                              "final_state", "preflight_called", "preflight", "execution_called", "execution",
                                              "reason", "failures", "rejection_record", "sequence"})


# ---------------------------------------------------------------------------------------------------------------------
# boundaries and guards
# ---------------------------------------------------------------------------------------------------------------------

class TestBoundaries(unittest.TestCase):
    def test_preflighted_function_and_section_contracts_are_unchanged(self):
        self.assertEqual(list(inspect.signature(execute_plan_tool_step_preflighted).parameters),
                         ["plan", "step_id", "request", "registry", "rejection_log"])
        self.assertEqual(list(inspect.signature(execute_plan_tool_step_mapped).parameters),
                         ["plan", "step_id", "request", "registry", "required_capabilities", "capability_mapping",
                          "rejection_log"])
        from planning.plan import PlanStep
        self.assertEqual(PlanStep("x", "d", required_capabilities=["Free Form Name"]).required_capabilities, ["Free Form Name"])
        from tools.tool_request import create_tool_request
        self.assertFalse(create_tool_request("echo", {}, granted_capabilities=["Free Form Name"]).ok)     # Section 5 rule intact

    def test_mapping_module_is_pure_and_imports_only_re(self):
        tree = ast.parse(inspect.getsource(map_mod))
        imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
                  {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        self.assertEqual(imports, {"re"})
        src = inspect.getsource(map_mod)
        for word in ("import socket", "import threading", "import sqlite3", "open(", "global ", "import tools", "CapabilitySystem"):
            self.assertNotIn(word, src)

    def test_only_the_executor_imports_the_mapping_and_tools_stay_isolated(self):
        importers = []
        for root, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__")]
            for f in files:
                if f.endswith(".py"):
                    path = os.path.join(root, f)
                    with open(path, encoding="utf-8") as fh:
                        text = fh.read()
                    if "tool_capability_mapping" in text and not path.endswith("tool_capability_mapping.py"):
                        importers.append(os.path.relpath(path, PY_ROOT).replace(os.sep, "/"))
                    if "execute_plan_tool_step_mapped" in text and not path.endswith(os.path.join("planning", "tool_step_executor.py")) \
                            and not path.endswith(os.path.join("planning", "tool_step_retry.py")) \
                            and not path.endswith(os.path.join("planning", "tool_step_agent_adapter.py")):      # Prompt 711/714: sanctioned callers
                        self.fail("mapped executor is wired into " + path)
        self.assertEqual(sorted(importers), ["planning/tool_step_agent_adapter.py", "planning/tool_step_executor.py"])      # Prompt 714: the adapter reads the pure mapping report

    def test_executor_still_imports_no_tools_and_no_legacy_stack(self):
        tree = ast.parse(inspect.getsource(exec_mod))
        imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertFalse({m.split(".")[0] for m in imports} & {"tools", "execution", "agent", "core"})
        ids = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("CapabilitySystem", "ExecutionEngine", "PlanExecutionController", "process_input", "execute_request",
                     "ToolRequest", "create_tool_request", "register", "handler"):
            self.assertNotIn(word, ids, word)
        # the step's own required_capabilities are never read by the executor
        self.assertNotIn("required_capabilities", {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)})

    def test_no_state_is_kept_between_calls(self):
        reg, _ = make_registry()
        run_mapped(make_plan(), req("needs_cap"), reg, ["Needs A"], MAPPING)
        ok = run_mapped(make_plan(), req("needs_cap", caps=["cap_a"]), reg, ["Needs A"], MAPPING)
        self.assertTrue(ok.ok)                                     # an earlier rejection did not remember or block anything
        bad = run_mapped(make_plan(), req("needs_cap"), reg, ["Needs A"], MAPPING)
        self.assertFalse(bad.ok)                                   # an earlier success did not remember a grant

    def test_database_untouched(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
