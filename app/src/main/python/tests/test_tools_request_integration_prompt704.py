"""Prompt 704 - ToolRequest registry entry point + Section 5 contract-audit regressions. Pure in-memory."""
import copy
import hashlib
import json
import os
import unittest

from tools import in_process_tool_registry as mod
from tools.in_process_tool_registry import (InProcessToolRegistry, ToolSpec, ToolExecutionResult, normalize_tool_output,
                                            validate_tool_spec)
from tools.tool_request import ToolRequest, create_tool_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"


class Handler:
    def __init__(self, value=None, exc=None, mutate=False):
        self.value, self.exc, self.mutate, self.calls = ({"ok": True} if value is None else value), exc, mutate, []

    def __call__(self, tool_input):
        self.calls.append(tool_input)
        if self.mutate:
            tool_input["mutated_by_handler"] = True
            for v in tool_input.values():
                if isinstance(v, list):
                    v.append("x")
        if self.exc:
            raise self.exc
        return self.value


def spec(name="req_tool", handler=None, **kw):
    return ToolSpec(name=name, description="d", handler=handler or Handler(), input_schema={"type": "object"},
                    output_description="o", **kw)


def reg_with(*specs):
    reg = InProcessToolRegistry()
    for s in specs:
        assert reg.register(s).ok, s
    return reg


def req(name="req_tool", tool_input=None, perms=None, caps=None, confirmed=False):
    res = create_tool_request(name, {"a": [1]} if tool_input is None else tool_input, perms, caps, confirmed)
    assert res.ok, res.failures
    return res.request


def has_callable(value):
    if callable(value):
        return True
    if isinstance(value, dict):
        return any(has_callable(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(has_callable(v) for v in value)
    return False


class ExecuteRequestBasicTests(unittest.TestCase):
    def test_valid_request_executes_once_and_is_audited_once(self):
        h = Handler({"echo": 1})
        reg = reg_with(spec(handler=h))
        res = reg.execute_request(req(tool_input={"q": "x"}))
        self.assertIsInstance(res, ToolExecutionResult)
        self.assertTrue(res.ok)
        self.assertEqual(res.execution_status, "succeeded")
        self.assertEqual(res.output, {"echo": 1})
        self.assertEqual(h.calls, [{"q": "x"}])
        self.assertEqual(reg.invocation_count(), 1)
        rec = reg.get_invocation_history()[0]
        self.assertEqual((rec["tool_name"], rec["outcome_code"], rec["handler_called"], rec["sequence"]),
                         ("req_tool", "TOOL_COMPLETED", True, 1))
        self.assertEqual(rec["input"], {"q": "x"})

    def test_equivalent_to_direct_execute_with_the_same_arguments(self):
        request = req(tool_input={"k": [1, {"z": 2}]}, perms=["network"], caps=["web_search"], confirmed=True)
        results = []
        for how in ("request", "direct"):
            h = Handler({"v": 1})
            reg = reg_with(spec(handler=h, permissions=["network", "user_confirmation"], capabilities=["web_search"]))
            res = reg.execute_request(request) if how == "request" else reg.execute(**request.to_registry_arguments())
            results.append((res.to_dict(), reg.get_invocation_history(), h.calls))
        self.assertEqual(results[0], results[1])

    def test_uses_the_single_existing_execution_path(self):
        counts = {"execute": 0, "invoke": 0, "evaluate": 0, "handler": 0}

        class Spy(InProcessToolRegistry):
            def execute(self, *a, **k):
                counts["execute"] += 1
                return super().execute(*a, **k)

            def invoke(self, *a, **k):
                counts["invoke"] += 1
                return super().invoke(*a, **k)

            def _evaluate(self, *a, **k):
                counts["evaluate"] += 1
                return super()._evaluate(*a, **k)

        def handler(tool_input):
            counts["handler"] += 1
            return {}

        reg = Spy()
        assert reg.register(spec(handler=handler)).ok
        reg.execute_request(req())
        self.assertEqual(counts, {"execute": 1, "invoke": 1, "evaluate": 1, "handler": 1})

    def test_handler_runs_at_most_once_even_when_it_fails(self):
        for handler in (Handler(exc=ValueError("boom")), Handler(value={1, 2}), Handler(value=float("nan"))):
            reg = reg_with(spec(handler=handler))
            res = reg.execute_request(req())
            self.assertEqual(res.execution_status, "handler_failed")
            self.assertEqual(len(handler.calls), 1)
            self.assertEqual(reg.invocation_count(), 1)

    def test_output_type_validation_still_applies(self):
        h = Handler(value=[1])
        reg = reg_with(spec(handler=h, output_type="object"))
        res = reg.execute_request(req())
        self.assertEqual((res.execution_status, res.outcome_code), ("output_invalid", "TOOL_OUTPUT_VALIDATION_FAILED"))
        self.assertIsNone(res.output)
        self.assertEqual(len(h.calls), 1)

    def test_same_request_can_be_executed_repeatedly_each_call_audited_and_independent(self):
        h = Handler(mutate=True)
        reg = reg_with(spec(handler=h))
        request = req(tool_input={"a": [1]})
        reg.execute_request(request)
        reg.execute_request(request)
        self.assertEqual(len(h.calls), 2)
        self.assertIsNot(h.calls[0], h.calls[1])
        self.assertIsNot(h.calls[0]["a"], h.calls[1]["a"])
        self.assertEqual(h.calls[1]["a"], [1, "x"])            # second run saw a clean copy, not the first run's mutation
        self.assertEqual(request.input, {"a": [1]})
        self.assertEqual([r["sequence"] for r in reg.get_invocation_history()], [1, 2])


class NoBypassTests(unittest.TestCase):
    """A request never skips any check the registry performs; outcome must equal preflight() on the same arguments."""

    def scenarios(self):
        return [
            ("unknown", reg_with(spec()), req(name="ghost"), "UNKNOWN_TOOL", "tool_rejected"),
            ("disabled", reg_with(spec(enabled=False)), req(), "TOOL_DISABLED", "tool_rejected"),
            ("perm_denied", reg_with(spec(permissions=["network"])), req(), "TOOL_PERMISSION_DENIED", "authorization_rejected"),
            ("perm_wrong", reg_with(spec(permissions=["network"])), req(perms=["filesystem"]), "TOOL_PERMISSION_DENIED",
             "authorization_rejected"),
            ("confirm_missing", reg_with(spec(permissions=["user_confirmation"])), req(perms=["user_confirmation"]),
             "TOOL_CONFIRMATION_REQUIRED", "authorization_rejected"),
            ("cap_missing", reg_with(spec(capabilities=["web_search"])), req(caps=["other_cap"]), "TOOL_CAPABILITY_MISSING",
             "authorization_rejected"),
        ]

    def test_every_pre_handler_rejection_matches_preflight_and_never_calls_the_handler(self):
        for label, reg, request, code, status in self.scenarios():
            handler_calls = sum(len(e["handler"].calls) for e in reg._entries.values())
            pre = reg.preflight(**request.to_registry_arguments())
            self.assertEqual(reg.invocation_count(), 0, label)          # preflight is read-only
            res = reg.execute_request(request)
            self.assertEqual(pre.outcome_code, code, label)
            self.assertEqual((res.outcome_code, res.execution_status), (code, status), label)
            self.assertFalse(res.handler_called, label)
            self.assertEqual(handler_calls, sum(len(e["handler"].calls) for e in reg._entries.values()), label)
            self.assertEqual(reg.invocation_count(), 1, label)          # rejections are audited
            rec = reg.get_invocation_history()[0]
            self.assertEqual((rec["outcome_code"], rec["handler_called"]), (code, False), label)

    def test_accepted_requests_pass_preflight_and_run(self):
        reg = reg_with(spec(permissions=["network", "user_confirmation"], capabilities=["web_search"]))
        request = req(perms=["network"], caps=["web_search"], confirmed=True)
        self.assertTrue(reg.preflight(**request.to_registry_arguments()).ok)
        self.assertTrue(reg.execute_request(request).ok)

    def test_request_never_supplies_authorization_the_caller_did_not_give(self):
        h = Handler()
        reg = reg_with(spec(handler=h, permissions=["network", "user_confirmation"], capabilities=["web_search"]))
        args = req().to_registry_arguments()
        self.assertEqual((args["granted_permissions"], args["granted_capabilities"], args["confirmed"]), ([], [], False))
        self.assertEqual(reg.execute_request(req()).outcome_code, "TOOL_PERMISSION_DENIED")
        self.assertEqual(h.calls, [])

    def test_authorization_is_not_remembered_between_requests(self):
        h = Handler()
        reg = reg_with(spec(handler=h, permissions=["network", "user_confirmation"], capabilities=["web_search"]))
        self.assertTrue(reg.execute_request(req(perms=["network"], caps=["web_search"], confirmed=True)).ok)
        again = reg.execute_request(req())                       # same tool, no grants this time
        self.assertEqual(again.outcome_code, "TOOL_PERMISSION_DENIED")
        self.assertEqual(len(h.calls), 1)
        self.assertEqual(sorted(vars(reg)), ["_entries", "_history"])
        for entry in reg._entries.values():
            self.assertFalse(any("grant" in k or "confirm" in k for k in entry))

    def test_forged_request_slots_are_still_checked_by_the_registry(self):
        h = Handler()
        reg = reg_with(spec(handler=h, permissions=["network"]))
        forged = object.__new__(ToolRequest)
        for slot, value in (("_name", "req_tool"), ("_input", {"a": 1}), ("_granted_permissions", ()),
                            ("_granted_capabilities", ()), ("_confirmed", False)):
            object.__setattr__(forged, slot, value)
        self.assertEqual(reg.execute_request(forged).outcome_code, "TOOL_PERMISSION_DENIED")
        object.__setattr__(forged, "_input", 5)                                  # forged, invalid input
        object.__setattr__(forged, "_granted_permissions", ("network",))          # the caller's own grant
        self.assertEqual(reg.execute_request(forged).outcome_code, "INVALID_TOOL_INPUT")
        object.__setattr__(forged, "_name", "req_tool\n")                         # forged trailing-newline name
        self.assertEqual(reg.execute_request(forged).outcome_code, "UNKNOWN_TOOL")
        self.assertEqual(h.calls, [])


class InvalidRequestObjectTests(unittest.TestCase):
    def bad_objects(self):
        good = req()
        empty_forged = object.__new__(ToolRequest)
        half_forged = object.__new__(ToolRequest)
        object.__setattr__(half_forged, "_name", "req_tool")                     # other slots never set
        broken_grants = object.__new__(ToolRequest)
        for slot, value in (("_name", "req_tool"), ("_input", {}), ("_granted_permissions", 7),
                            ("_granted_capabilities", ()), ("_confirmed", False)):
            object.__setattr__(broken_grants, slot, value)
        return [None, "req_tool", 5, [], {}, good.to_dict(), good.to_registry_arguments(), object(), ToolRequest,
                lambda: good, empty_forged, half_forged, broken_grants]

    def test_invalid_objects_rejected_deterministically_without_calling_the_handler(self):
        h = Handler()
        reg = reg_with(spec(handler=h))
        bad = self.bad_objects()
        for i, obj in enumerate(bad):                                        # index label: repr() of a forged instance is not safe
            res = reg.execute_request(obj)
            self.assertFalse(res.ok, i)
            self.assertEqual((res.outcome_code, res.execution_status), ("INVALID_TOOL_REQUEST", "tool_rejected"), i)
            self.assertFalse(res.handler_called)
            self.assertFalse(res.output_available)
            self.assertIsNone(res.output)
            self.assertIsNone(res.tool_name)
            self.assertEqual(res.authorization_decision, "not_evaluated")
            self.assertFalse(res.authorization_accepted)
            self.assertEqual([f["code"] for f in res.failures], ["INVALID_TOOL_REQUEST"])
        self.assertEqual(h.calls, [])
        self.assertEqual(reg.invocation_count(), len(bad))                  # audited like any rejected call

    def test_invalid_request_results_are_repeatable(self):
        outs = []
        for _ in range(2):
            reg = reg_with(spec())
            outs.append([(reg.execute_request(o).to_dict(), ) for o in (None, {}, "x")] + [reg.get_invocation_history()])
        self.assertEqual(json.dumps(outs[0], sort_keys=True), json.dumps(outs[1], sort_keys=True))

    def test_invalid_request_record_agrees_with_result(self):
        reg = reg_with(spec())
        res = reg.execute_request(None)
        rec = reg.get_invocation_history()[-1]
        self.assertEqual((rec["sequence"], rec["outcome_code"], rec["handler_called"], rec["status"], rec["tool_name"]),
                         (res.sequence, res.outcome_code, res.handler_called, "rejected", res.tool_name))
        self.assertEqual((rec["input_json_safe"], rec["input"], rec["authorization_decision"]), (False, None, "not_evaluated"))

    def test_invalid_request_does_not_touch_other_state(self):
        reg = reg_with(spec(enabled=False))
        reg.execute_request(42)
        self.assertEqual(reg.list_names(), ["req_tool"])
        self.assertFalse(reg.is_enabled("req_tool"))


class IsolationAndNoExposureTests(unittest.TestCase):
    def test_handler_mutating_its_input_cannot_change_request_or_audit(self):
        h = Handler(mutate=True)
        reg = reg_with(spec(handler=h))
        request = req(tool_input={"a": [1], "n": {"m": 1}})
        reg.execute_request(request)
        self.assertEqual(request.input, {"a": [1], "n": {"m": 1}})
        self.assertEqual(reg.get_invocation_history()[0]["input"], {"a": [1], "n": {"m": 1}})

    def test_mutating_result_or_history_output_changes_nothing(self):
        reg = reg_with(spec(handler=Handler({"o": [1]})))
        res = reg.execute_request(req())
        res.output["o"].append(2)
        res.failures.append("x")
        hist = reg.get_invocation_history()
        hist[0]["output"]["o"].append(3)
        hist[0]["input"]["a"].append(9)
        fresh = reg.get_invocation_history()[0]
        self.assertEqual((fresh["output"], fresh["input"]), ({"o": [1]}, {"a": [1]}))

    def test_handler_output_is_a_fresh_plain_copy(self):
        shared = {"o": [1]}
        reg = reg_with(spec(handler=Handler(shared)))
        res = reg.execute_request(req())
        self.assertIsNot(res.output, shared)
        shared["o"].append("later")
        self.assertEqual(reg.get_invocation_history()[0]["output"], {"o": [1]})

    def test_results_and_records_never_hold_or_expose_the_handler(self):
        h = Handler()
        reg = reg_with(spec(handler=h, permissions=["network"]))
        results = [reg.execute_request(req(perms=["network"])), reg.execute_request(req()), reg.execute_request(None),
                   reg.execute_request(req(name="ghost"))]
        for res in results:
            self.assertNotIn("handler", res.__slots__)
            self.assertFalse(has_callable(res.to_dict()))
            self.assertNotIn(id(h), [id(getattr(res, s)) for s in res.__slots__])
        self.assertFalse(has_callable(reg.get_invocation_history()))
        self.assertFalse(has_callable(req().to_dict()))
        self.assertFalse(hasattr(req(), "handler"))

    def test_request_is_unchanged_after_registry_use(self):
        request = req(tool_input={"a": [1]}, perms=["network"], caps=["c_one"], confirmed=True)
        before = request.to_dict()
        reg = reg_with(spec(handler=Handler(mutate=True), permissions=["network"]))
        reg.execute_request(request)
        reg.execute_request(request)
        self.assertEqual(request.to_dict(), before)
        with self.assertRaises(AttributeError):
            request.confirmed = False


class AuditResultConsistencyTests(unittest.TestCase):
    def cases(self):
        ok, boom = Handler({"v": 1}), Handler(exc=RuntimeError("x"))
        bad_out, wrong_type = Handler({1, 2}), Handler([1])
        reg = reg_with(spec("ok_tool", ok, permissions=["network"]), spec("boom", boom), spec("bad_out", bad_out),
                       spec("wrong_type", wrong_type, output_type="object"), spec("off", enabled=False),
                       spec("needs_cap", capabilities=["a_cap"]), spec("needs_confirm", permissions=["user_confirmation"]))
        requests = [req("ok_tool", perms=["network"]), req("boom"), req("bad_out"), req("wrong_type"), req("off"),
                    req("needs_cap"), req("needs_confirm"), req("ok_tool"), req("ghost")]
        return reg, requests, [ok, boom, bad_out, wrong_type]

    def test_result_and_record_agree_for_every_outcome_kind(self):
        reg, requests, _ = self.cases()
        results = [reg.execute_request(r) for r in requests]
        history = reg.get_invocation_history()
        self.assertEqual(len(history), len(requests))
        for res, rec in zip(results, history):
            self.assertEqual(res.sequence, rec["sequence"])
            self.assertEqual(res.tool_name, rec["tool_name"])
            self.assertEqual(res.outcome_code, rec["outcome_code"])
            self.assertEqual(res.handler_called, rec["handler_called"])
            self.assertEqual(res.output, rec["output"])
            self.assertEqual(res.output_available, rec["output_available"])
            self.assertEqual(res.failures, rec["failures"])
            self.assertEqual(res.authorization_decision, rec["authorization_decision"])
            self.assertEqual(res.execution_status == "succeeded", rec["ok"])
        self.assertEqual([r.execution_status for r in results],
                         ["succeeded", "handler_failed", "handler_failed", "output_invalid", "tool_rejected",
                          "authorization_rejected", "authorization_rejected", "authorization_rejected", "tool_rejected"])

    def test_handler_called_flag_matches_reality_and_is_at_most_once(self):
        reg, requests, handlers = self.cases()
        for r in requests:
            before = [len(h.calls) for h in handlers]
            res = reg.execute_request(r)
            delta = sum(len(h.calls) for h in handlers) - sum(before)
            self.assertIn(delta, (0, 1))
            self.assertEqual(res.handler_called, delta == 1, r.name)
            self.assertEqual(reg.get_invocation_history()[-1]["handler_called"], delta == 1, r.name)

    def test_nested_call_from_a_handler_keeps_sequence_and_result_consistent(self):
        holder = {}

        def outer(tool_input):
            holder["inner"] = holder["reg"].execute_request(req("inner_tool"))
            return {"done": True}

        reg = reg_with(spec("outer_tool", outer), spec("inner_tool"))
        holder["reg"] = reg
        res = reg.execute_request(req("outer_tool"))
        hist = reg.get_invocation_history()
        self.assertEqual([h["tool_name"] for h in hist], ["inner_tool", "outer_tool"])
        self.assertEqual(res.sequence, 2)
        self.assertEqual(hist[res.sequence - 1]["tool_name"], "outer_tool")
        self.assertEqual(holder["inner"].sequence, 1)

    def test_identical_runs_are_deterministic(self):
        dumps = []
        for _ in range(3):
            reg, requests, _ = self.cases()
            out = [reg.execute_request(r).to_dict() for r in requests]
            dumps.append(json.dumps([out, reg.get_invocation_history()], sort_keys=True))
        self.assertEqual(dumps[0], dumps[1])
        self.assertEqual(dumps[1], dumps[2])

    def test_every_status_code_is_mapped(self):
        for code in ("TOOL_COMPLETED", "TOOL_HANDLER_EXCEPTION", "TOOL_OUTPUT_INVALID", "TOOL_OUTPUT_VALIDATION_FAILED",
                     "TOOL_PERMISSION_DENIED", "TOOL_CONFIRMATION_REQUIRED", "INVALID_TOOL_AUTHORIZATION",
                     "TOOL_CAPABILITY_MISSING", "INVALID_TOOL_INPUT", "UNKNOWN_TOOL", "TOOL_DISABLED", "INVALID_TOOL_REQUEST"):
            self.assertIn(code, mod._EXEC_STATUS_BY_CODE)


class RegexEdgeCaseRegressionTests(unittest.TestCase):
    """Genuine defect: `$` matched before a trailing newline, so 'tool\\n' was a registrable name/capability."""

    def test_trailing_newline_names_are_rejected_by_the_registry(self):
        for bad in ("tool\n", "\ntool", "tool\n\n", "to\nol", "tool\r\n", "tool "):
            res = InProcessToolRegistry().register(spec(bad))
            self.assertFalse(res.ok, repr(bad))
            self.assertEqual(res.codes(), ["INVALID_TOOL_NAME"], repr(bad))
            self.assertEqual([f["code"] for f in validate_tool_spec(spec(bad))], ["INVALID_TOOL_NAME"], repr(bad))

    def test_trailing_newline_capabilities_are_rejected(self):
        self.assertEqual(validate_tool_spec(spec(capabilities=["cap\n"]))[0]["code"], "INVALID_TOOL_CAPABILITIES")
        reg = reg_with(spec(capabilities=["cap"]))
        pre = reg.preflight("req_tool", {}, granted_capabilities=["cap\n"])
        self.assertEqual(pre.outcome_code, "INVALID_TOOL_AUTHORIZATION")
        res = reg.execute("req_tool", {}, granted_capabilities=["cap\n"])
        self.assertEqual((res.outcome_code, res.handler_called), ("INVALID_TOOL_AUTHORIZATION", False))

    def test_lookup_of_newline_name_finds_nothing_and_valid_names_still_work(self):
        reg = reg_with(spec("tool"))
        self.assertFalse(reg.has("tool\n"))
        self.assertIsNone(reg.describe("tool\n"))
        self.assertEqual(reg.preflight("tool\n", {}).outcome_code, "UNKNOWN_TOOL")
        self.assertTrue(reg.execute("tool", {}).ok)
        for good in ("a", "a" * 64, "a_1", "z9_"):
            self.assertTrue(InProcessToolRegistry().register(spec(good)).ok, good)
        for bad in ("a" * 65, "", "A", "1a", "_a", "a-b"):
            self.assertFalse(InProcessToolRegistry().register(spec(bad)).ok, bad)

    def test_request_and_registry_now_agree_on_names(self):
        for name in ("tool", "tool\n", "a" * 64, "a" * 65, "Tool", "", "t_1"):
            self.assertEqual(create_tool_request(name, {}).ok, InProcessToolRegistry().register(spec(name)).ok, repr(name))


class RecursionAndIsolationRegressionTests(unittest.TestCase):
    """Genuine defects: cyclic/deep input or schema raised RecursionError (no audit record); a dict subclass could hand the handler
    the caller's own object and run caller hooks."""

    def cyclic(self):
        c = {}
        c["self"] = c
        return c

    def deep(self, n=5000):
        root = cur = {}
        for _ in range(n):
            cur["k"] = {}
            cur = cur["k"]
        return root

    def test_cyclic_and_deep_input_is_a_normal_rejection_everywhere(self):
        for label, bad in (("cyclic", self.cyclic()), ("deep", self.deep())):
            h = Handler()
            reg = reg_with(spec(handler=h))
            pre = reg.preflight("req_tool", bad)
            self.assertEqual((pre.outcome_code, pre.input_valid), ("INVALID_TOOL_INPUT", False), label)
            self.assertEqual(reg.invocation_count(), 0, label)
            inv = reg.invoke("req_tool", bad)
            self.assertEqual(inv.codes(), ["INVALID_TOOL_INPUT"], label)
            res = reg.execute("req_tool", bad)
            self.assertEqual((res.execution_status, res.handler_called), ("input_rejected", False), label)
            self.assertEqual(reg.invocation_count(), 2, label)                 # both calls audited
            rec = reg.get_invocation_history()[0]
            self.assertEqual((rec["input_json_safe"], rec["input"], rec["input_type"]), (False, None, "dict"), label)
            self.assertEqual(h.calls, [], label)

    def test_cyclic_and_deep_input_schema_is_a_registration_failure(self):
        for bad in (self.cyclic(), self.deep()):
            s = spec()
            s.input_schema = bad
            res = InProcessToolRegistry().register(s)
            self.assertEqual(res.codes(), ["INVALID_TOOL_INPUT_SCHEMA"])

    def test_moderately_nested_input_still_works(self):
        h = Handler()
        reg = reg_with(spec(handler=h))
        nested = self.deep(50)
        self.assertTrue(reg.execute("req_tool", nested).ok)
        self.assertEqual(h.calls[0], nested)

    def test_json_safe_has_one_authority(self):
        samples = [{}, {"a": [1, 2.5, None, True, "s"]}, {"a": (1,)}, {"a": {1}}, {1: 2}, {"a": float("inf")}, b"x", None, 3, "s",
                   [1], {"a": object()}, self.cyclic(), self.deep()]
        for v in samples:
            self.assertEqual(mod._json_safe(v), normalize_tool_output(v)[0])

    def test_dict_subclass_input_gives_the_handler_a_plain_private_copy(self):
        ran = []

        class Sneaky(dict):
            def __deepcopy__(self, memo):
                ran.append("deepcopy")
                return self                                                  # would hand the caller's own object over

            def items(self):
                ran.append("items")
                return super().items()

        class Lst(list):
            def __iter__(self):
                ran.append("iter")
                return super().__iter__()

        src = Sneaky(a=Lst([1, 2]))
        h = Handler(mutate=True)
        reg = reg_with(spec(handler=h))
        self.assertTrue(reg.execute("req_tool", src).ok)
        seen = h.calls[0]
        self.assertIsNot(seen, src)
        self.assertIs(type(seen), dict)
        self.assertIs(type(seen["a"]), list)
        self.assertEqual(src, {"a": [1, 2]})                                 # handler's mutations did not reach the caller
        self.assertEqual(ran, [])                                             # no caller hook ran
        rec = reg.get_invocation_history()[0]
        self.assertEqual(rec["input"], {"a": [1, 2]})
        self.assertTrue(rec["input_json_safe"])

    def test_registry_keeps_a_plain_private_copy_of_the_schema(self):
        class Sneaky(dict):
            def __deepcopy__(self, memo):
                return self

        schema = Sneaky(type="object", props={"x": [1]})
        s = spec()
        s.input_schema = schema
        reg = reg_with(s)
        schema["props"]["x"].append(2)
        d = reg.describe("req_tool")
        self.assertEqual(d["input_schema"], {"type": "object", "props": {"x": [1]}})
        self.assertIs(type(d["input_schema"]), dict)
        d["input_schema"]["props"]["x"].append(3)
        self.assertEqual(reg.describe("req_tool")["input_schema"]["props"]["x"], [1])

    def test_preflight_still_never_calls_handler_or_audits(self):
        h = Handler()
        reg = reg_with(spec(handler=h))
        for inp in ({}, {"a": 1}, self.cyclic(), 5, None):
            reg.preflight("req_tool", inp)
        self.assertEqual((h.calls, reg.invocation_count()), ([], 0))


class BoundaryAndStateTests(unittest.TestCase):
    def test_no_module_level_request_state(self):
        before = copy.deepcopy(mod._EXEC_STATUS_BY_CODE)
        reg = reg_with(spec())
        for _ in range(3):
            reg.execute_request(req())
            reg.execute_request(None)
        self.assertEqual(mod._EXEC_STATUS_BY_CODE, before)
        other = InProcessToolRegistry()
        self.assertEqual((other.invocation_count(), len(other)), (0, 0))      # a second registry shares nothing

    def test_process_input_planner_and_agent_loop_do_not_reference_the_entry_point(self):
        for sub in ("core", "agent", "planning", "reasoning", "execution", "context", "understanding"):
            for root, _d, files in os.walk(os.path.join(PY_ROOT, sub)):
                for f in files:
                    if f.endswith(".py") and f != "tool_step_bridge.py" and not (sub == "agent" and f == "tool_step_intent.py"):      # Prompt 707: the one sanctioned, caller-driven consumer; Prompt 719-A: exact-path exemption for the caller-side intent adapter
                        with open(os.path.join(root, f), encoding="utf-8") as fh:
                            text = fh.read()
                        self.assertNotIn("execute_request", text, f)
                        self.assertNotIn("tool_request", text, f)

    def test_pristine_db_hash(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
