"""Prompt 785 - Section 9 web request batch summary (`web.web_request_batch_summary`)."""
import ast
import copy
import gc
import hashlib
import itertools
import os
import pickle
import sys
import unittest
from unittest import mock

from web import web_request_batch as wb
from web import web_request_batch_summary as ws
from web import web_request_dispatcher as wdisp
from web import web_request_output as wo
from web import web_request_pipeline as wp
from web.web_request import create_web_request
from web.web_request_batch import WebRequestBatchResult, run_web_request_batch
from web.web_request_batch_summary import WebRequestBatchSummary, create_web_request_batch_summary
from web.web_request_dispatcher import dispatch_web_request
from web.web_request_executor import execute_web_request_plan
from web.web_request_output import WebRequestOutput, create_web_request_output
from web.web_request_pipeline import run_web_request_pipeline
from web.web_request_plan import WebRequestPlan, create_web_request_plan
from web.web_request_validator import validate_web_request
from web.web_resource import create_web_resource
from web.web_resource_registry import create_web_resource_registry

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section9_web_request_batch_summary_prompt785.md")
MODULE = os.path.join(PY_ROOT, "web", "web_request_batch_summary.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
INVALID = "WEB_REQUEST_BATCH_SUMMARY_INVALID_RESULT"
MALFORMED = "WEB_REQUEST_BATCH_SUMMARY_MALFORMED_RESULT"
NOT_IMPL = "WEB_REQUEST_EXECUTOR_NOT_IMPLEMENTED"
DEFAULT = {"request_id": "req_1", "url": "https://example.org/x", "method": "GET", "resource_type": "page", "timeout_ms": 5000}


def make_plan(**over):
    data = dict(DEFAULT)
    data.update(over)
    req = create_web_request(data)
    assert req.ok, req.failures
    res = create_web_resource({"resource_id": data["resource_type"], "url": "https://example.org/r", "title": "T", "resource_type": "page"})
    assert res.ok, res.failures
    reg = create_web_resource_registry([res.resource])
    assert reg.ok, reg.failures
    plan = create_web_request_plan(validate_web_request(req.request, reg.registry))
    assert plan.ok, plan.codes()
    return plan.plan


def make_output(status, code, items=None):
    """A real WebRequestOutput with arbitrary status/code (built with the Prompt 779 module's creation token, as the pipeline does for rejections)."""
    return WebRequestOutput(wo._CREATE_TOKEN, status, code, items)


def batch_with(outputs):
    """A real, valid batch whose pipeline returned exactly `outputs` (through the public batch function; the pipeline is patched to feed them)."""
    feed = iter(outputs)
    plans = tuple(make_plan(request_id="p%d" % i) for i in range(len(outputs)))
    with mock.patch.object(wb, "run_web_request_pipeline", lambda plan: next(feed)):
        result = run_web_request_batch(plans)
    assert result.ok and len(result.outputs) == len(outputs)
    return result


def raw_batch(outputs, failures):
    """An exact WebRequestBatchResult that no real batch could produce (private token): the 'malformed exact-type result' cases."""
    return WebRequestBatchResult(wb._CREATE_TOKEN, outputs, failures)


def rejected(code):
    return {"total_count": 0, "output_count": 0, "failure_count": 0, "status_counts": {}, "code_counts": {}, "success": False, "codes": [code]}


def boom(*a, **k):
    raise AssertionError("forbidden call")


class Lookalike:
    outputs, failures, ok = (), (), True

    def codes(self):
        return []

    def to_dict(self):
        return {"ok": True, "outputs": [], "failures": []}


class SpoofedClass:
    """isinstance() says it is a WebRequestBatchResult; its exact type is not."""

    @property
    def __class__(self):
        return WebRequestBatchResult


class Hostile:
    def __getattribute__(self, name):
        raise AssertionError("input must not be read: " + name)

    def __eq__(self, other):
        raise AssertionError("input must not be compared")

    def __hash__(self):
        raise AssertionError("input must not be hashed")

    def __iter__(self):
        raise AssertionError("input must not be iterated")

    def __len__(self):
        raise AssertionError("input must not be measured")

    def __repr__(self):
        raise AssertionError("input must not be repr'd")


class HostileStr(str):
    def __hash__(self):
        raise AssertionError("a rejected str subclass must not be hashed")

    def __eq__(self, other):
        raise AssertionError("a rejected str subclass must not be compared")

    def __lt__(self, other):
        raise AssertionError("a rejected str subclass must not be sorted")


def live(cls):
    gc.collect()
    return [o for o in gc.get_objects() if type(o) is cls]


def plain(value):
    """True when `value` is built only from int/bool/str and tuples of them."""
    if type(value) is tuple:
        return all(plain(v) for v in value)
    return type(value) in (int, bool, str)


class TestValidSummary(unittest.TestCase):
    def test_1_valid_empty_batch(self):
        s = create_web_request_batch_summary(run_web_request_batch(()))
        self.assertIs(type(s), WebRequestBatchSummary)
        self.assertEqual((s.total_count, s.output_count, s.failure_count), (0, 0, 0))
        self.assertEqual((s.status_counts, s.code_counts), ({}, {}))
        self.assertIs(s.success, True)
        self.assertEqual(s.codes(), [])
        self.assertEqual(s.to_dict(), {"total_count": 0, "output_count": 0, "failure_count": 0, "status_counts": {}, "code_counts": {},
                                       "success": True, "codes": []})

    def test_2_single_real_plan(self):
        s = create_web_request_batch_summary(run_web_request_batch((make_plan(),)))
        self.assertEqual((s.total_count, s.output_count, s.failure_count), (1, 1, 0))
        self.assertEqual(s.status_counts, {"NOT_IMPLEMENTED": 1})
        self.assertEqual(s.code_counts, {NOT_IMPL: 1})
        self.assertTrue(s.success)

    def test_3_multiple_real_plans_have_exact_counts(self):
        plans = tuple(make_plan(request_id="r%d" % i) for i in range(7))
        s = create_web_request_batch_summary(run_web_request_batch(plans))
        self.assertEqual((s.total_count, s.output_count, s.failure_count), (7, 7, 0))
        self.assertEqual(s.status_counts, {"NOT_IMPLEMENTED": 7})
        self.assertEqual(s.code_counts, {NOT_IMPL: 7})
        self.assertEqual(s.codes(), [])

    def test_4_mixed_outputs_give_exact_status_and_code_aggregation(self):
        outs = [make_output("A", "X"), make_output("B", "X"), make_output("A", "Y"), make_output("A", "X"), make_output("C", "Z"),
                make_output("B", "Y")]
        s = create_web_request_batch_summary(batch_with(outs))
        self.assertEqual((s.total_count, s.output_count, s.failure_count), (6, 6, 0))
        self.assertEqual(s.status_counts, {"A": 3, "B": 2, "C": 1})
        self.assertEqual(s.code_counts, {"X": 3, "Y": 2, "Z": 1})
        self.assertTrue(s.success)

    def test_5_status_and_code_are_counted_independently(self):
        # same status with different codes, same code with different statuses
        outs = [make_output("S", "c1"), make_output("S", "c2"), make_output("T", "c1"), make_output("S", "c1")]
        s = create_web_request_batch_summary(batch_with(outs))
        self.assertEqual(s.status_counts, {"S": 3, "T": 1})
        self.assertEqual(s.code_counts, {"c1": 3, "c2": 1})

    def test_6_keys_are_exact_never_normalized(self):
        statuses = ["ok", "OK", " OK", "OK ", "Ok", "", "\u00e9", "e\u0301", "NOT_IMPLEMENTED", "not_implemented"]
        s = create_web_request_batch_summary(batch_with([make_output(v, "c") for v in statuses]))
        self.assertEqual(len(s.status_counts), len(statuses))
        self.assertEqual(set(s.status_counts), set(statuses))
        self.assertTrue(all(n == 1 for n in s.status_counts.values()))
        self.assertEqual(s.code_counts, {"c": len(statuses)})

    def test_7_counts_add_up_to_the_output_count(self):
        outs = [make_output("s%d" % (i % 3), "c%d" % (i % 4)) for i in range(50)]
        s = create_web_request_batch_summary(batch_with(outs))
        self.assertEqual(s.output_count, 50)
        self.assertEqual(sum(s.status_counts.values()), 50)
        self.assertEqual(sum(s.code_counts.values()), 50)
        self.assertEqual(s.total_count, s.output_count + s.failure_count)
        self.assertTrue(all(type(n) is int and n >= 1 for n in itertools.chain(s.status_counts.values(), s.code_counts.values())))

    def test_8_larger_batch_counts(self):
        outs = [make_output("s%d" % (i % 3), "c%d" % (i % 4)) for i in range(300)]
        s = create_web_request_batch_summary(batch_with(outs))
        self.assertEqual(s.status_counts, {"s0": 100, "s1": 100, "s2": 100})
        self.assertEqual(s.code_counts, {"c0": 75, "c1": 75, "c2": 75, "c3": 75})

    def test_9_real_pipeline_rejections_are_counted_as_outputs_not_failures(self):
        outs = [run_web_request_pipeline(None), run_web_request_pipeline(make_plan()), run_web_request_pipeline(None)]
        s = create_web_request_batch_summary(batch_with(outs))
        self.assertEqual((s.total_count, s.output_count, s.failure_count), (3, 3, 0))
        self.assertEqual(s.status_counts, {"NOT_IMPLEMENTED": 1, "REJECTED": 2})
        self.assertEqual(s.code_counts, {NOT_IMPL: 1, "WEB_REQUEST_PIPELINE_INVALID_PLAN": 2})
        self.assertTrue(s.success)       # success mirrors the batch's ok, not the outputs' statuses

    def test_10_types_of_the_exposed_values(self):
        s = create_web_request_batch_summary(batch_with([make_output("A", "x")]))
        for value in (s.total_count, s.output_count, s.failure_count):
            self.assertIs(type(value), int)
        self.assertIs(type(s.success), bool)
        self.assertIs(type(s.status_counts), dict)
        self.assertIs(type(s.code_counts), dict)
        self.assertIs(type(s.codes()), list)


class TestRejectedBatchInput(unittest.TestCase):
    """A valid WebRequestBatchResult that itself records failures (a rejected batch) is a valid summary input."""

    def test_11_batch_rejected_for_its_collection(self):
        s = create_web_request_batch_summary(run_web_request_batch([make_plan()]))
        self.assertEqual((s.total_count, s.output_count, s.failure_count), (1, 0, 1))
        self.assertEqual((s.status_counts, s.code_counts), ({}, {}))
        self.assertFalse(s.success)
        self.assertEqual(s.codes(), [])

    def test_12_batch_rejected_for_bad_items_counts_every_failure(self):
        s = create_web_request_batch_summary(run_web_request_batch((None, make_plan(), "x", 3)))
        self.assertEqual((s.total_count, s.output_count, s.failure_count), (3, 0, 3))   # the valid item beside the bad ones is not recorded
        self.assertFalse(s.success)
        self.assertEqual(s.codes(), [])

    def test_13_a_summarised_rejected_batch_differs_from_a_rejected_summary(self):
        s = create_web_request_batch_summary(run_web_request_batch(None))
        self.assertEqual(s.codes(), [])
        self.assertNotEqual(s, create_web_request_batch_summary(None))
        self.assertEqual(s.failure_count, 1)

    def test_14_success_follows_the_batch_ok(self):
        for batch in (run_web_request_batch(()), run_web_request_batch((make_plan(),)), run_web_request_batch(None), run_web_request_batch((None,))):
            self.assertIs(create_web_request_batch_summary(batch).success, batch.ok)


class TestOrdering(unittest.TestCase):
    def test_15_mappings_are_ordered_by_key_not_by_first_seen(self):
        s = create_web_request_batch_summary(batch_with([make_output("b", "y"), make_output("a", "z"), make_output("c", "x")]))
        self.assertEqual(list(s.status_counts), ["a", "b", "c"])
        self.assertEqual(list(s.code_counts), ["x", "y", "z"])
        self.assertEqual(list(s.to_dict()["status_counts"]), ["a", "b", "c"])

    def test_16_order_is_plain_string_order(self):
        keys = ["b", "B", "a", "A", "_", "1", "10", "9", "\u00e9", "z", " "]
        s = create_web_request_batch_summary(batch_with([make_output(k, k) for k in keys]))
        self.assertEqual(list(s.status_counts), sorted(keys))
        self.assertEqual(list(s.code_counts), sorted(keys))

    def test_17_output_order_does_not_change_the_summary(self):
        outs = [make_output("A", "x"), make_output("B", "x"), make_output("A", "y"), make_output("C", "z")]
        first = create_web_request_batch_summary(batch_with(outs))
        for perm in itertools.permutations(outs):
            s = create_web_request_batch_summary(batch_with(list(perm)))
            self.assertEqual(s, first)
            self.assertEqual(hash(s), hash(first))
            self.assertEqual(list(s.status_counts), ["A", "B", "C"])

    def test_18_to_dict_has_a_fixed_key_order(self):
        s = create_web_request_batch_summary(batch_with([make_output("A", "x")]))
        self.assertEqual(list(s.to_dict()), ["total_count", "output_count", "failure_count", "status_counts", "code_counts", "success", "codes"])


class TestInvalidInput(unittest.TestCase):
    def _inputs(self):
        plan = make_plan()
        batch = run_web_request_batch((plan,))
        return (None, {}, [], (), "batch", b"b", 1, 1.5, True, object(), Lookalike(), batch.to_dict(), batch.outputs, batch.failures, WebRequestBatchResult,
                type(None), lambda: None, plan, run_web_request_pipeline(plan), dispatch_web_request(plan), execute_web_request_plan(plan),
                create_web_request_batch_summary(batch), SpoofedClass(), Hostile())

    def test_19_every_non_batch_result_gives_the_deterministic_rejected_summary(self):
        for item in self._inputs():
            s = create_web_request_batch_summary(item)
            self.assertIs(type(s), WebRequestBatchSummary)
            self.assertEqual(s.to_dict(), rejected(INVALID))
            self.assertEqual(s.codes(), [INVALID])
            self.assertIs(s.success, False)

    def test_20_all_invalid_inputs_give_equal_summaries(self):
        results = [create_web_request_batch_summary(i) for i in self._inputs()]
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(len({hash(r) for r in results}), 1)

    def test_21_invalid_input_is_never_read(self):
        self.assertEqual(create_web_request_batch_summary(Hostile()).codes(), [INVALID])

    def test_22_invalid_input_is_not_changed(self):
        data = {"outputs": [1], "failures": []}
        create_web_request_batch_summary(data)
        self.assertEqual(data, {"outputs": [1], "failures": []})

    def test_23b_the_spoofed_class_would_pass_isinstance_but_is_rejected(self):
        self.assertTrue(isinstance(SpoofedClass(), WebRequestBatchResult))
        self.assertEqual(create_web_request_batch_summary(SpoofedClass()).codes(), [INVALID])

    def test_23_a_lookalike_with_the_same_shape_is_rejected(self):
        self.assertEqual(create_web_request_batch_summary(Lookalike()).codes(), [INVALID])
        self.assertEqual(create_web_request_batch_summary(Lookalike()), create_web_request_batch_summary(None))


class TestMalformedExactTypeResult(unittest.TestCase):
    def _assert_malformed(self, batch):
        s = create_web_request_batch_summary(batch)
        self.assertEqual(s.to_dict(), rejected(MALFORMED))
        return s

    def test_24_outputs_that_are_not_exact_web_request_outputs(self):
        class FakeOutput:
            status, code, metadata = "S", "C", None
        for bad in (object(), None, {"status": "S", "code": "C"}, "S", 5, FakeOutput(), ("S", "C"), WebRequestBatchResult, [make_output("S", "C")]):
            self._assert_malformed(raw_batch((bad,), ()))

    def test_25_status_or_code_that_is_not_exactly_a_str(self):
        for bad in (5, None, b"S", 1.5, True, ("S",), HostileStr("S")):
            self._assert_malformed(raw_batch((make_output(bad, "C"),), ()))
            self._assert_malformed(raw_batch((make_output("S", bad),), ()))

    def test_26_outputs_together_with_failures(self):
        out = run_web_request_pipeline(make_plan())
        self._assert_malformed(raw_batch((out,), [("WEB_REQUEST_BATCH_INVALID_PLAN", "plans[0]", "m")]))
        self._assert_malformed(raw_batch((out, out), [("c", "f", "m"), ("c2", "f2", "m2")]))

    def test_27_unreadable_failures(self):
        for failures in ([("only", "two")], [("a", "b", "c", "d")], [5], [None], ["abc"[:2]]):
            self._assert_malformed(raw_batch((), failures))

    def test_28_the_first_problem_rejects_the_whole_summary_nothing_is_partial(self):
        good = [make_output("A", "x"), make_output("B", "y")]
        for bad_at in (0, 1, 2):
            outs = list(good)
            outs.insert(bad_at, object())
            s = self._assert_malformed(raw_batch(tuple(outs), ()))
            self.assertEqual((s.total_count, s.output_count, s.status_counts), (0, 0, {}))

    def test_29_every_malformed_result_gives_one_equal_summary_distinct_from_invalid_input(self):
        out = run_web_request_pipeline(make_plan())
        results = [create_web_request_batch_summary(b) for b in (raw_batch((object(),), ()), raw_batch((make_output(1, "c"),), ()),
                                                                 raw_batch((out,), [("c", "f", "m")]), raw_batch((), [("x",)]))]
        self.assertEqual(len(set(results)), 1)
        self.assertNotEqual(results[0], create_web_request_batch_summary(None))
        self.assertEqual(results[0].codes(), [MALFORMED])

    def test_30_hostile_outputs_and_str_subclasses_are_never_looked_into_or_hashed(self):
        self._assert_malformed(raw_batch((Hostile(),), ()))
        self._assert_malformed(raw_batch((make_output(HostileStr("S"), "C"),), ()))
        self._assert_malformed(raw_batch((make_output("S", HostileStr("C")),), ()))
        self._assert_malformed(raw_batch((make_output("A", "x"), Hostile()), ()))

    def test_31_a_wellformed_hand_built_batch_is_still_valid(self):
        out = run_web_request_pipeline(make_plan())
        s = create_web_request_batch_summary(raw_batch((out, out), ()))
        self.assertEqual((s.total_count, s.output_count, s.failure_count), (2, 2, 0))
        self.assertEqual(s.codes(), [])
        self.assertTrue(s.success)

    def test_32_an_unreadable_output_slot_does_not_raise(self):
        # exact outputs whose private content is odd but whose public status/code are readable strings are fine; metadata is irrelevant
        out = make_output("S", "C", items=(("k", object()),))
        s = create_web_request_batch_summary(raw_batch((out,), ()))
        self.assertEqual(s.status_counts, {"S": 1})


class TestNoReinterpretation(unittest.TestCase):
    def test_33_output_metadata_is_never_read(self):
        batch = batch_with([make_output("A", "x", items=(("k", "v"),)), make_output("B", "y")])
        with mock.patch.object(WebRequestOutput, "metadata", property(boom)), mock.patch.object(WebRequestOutput, "to_dict", boom):
            s = create_web_request_batch_summary(batch)
        self.assertEqual(s.status_counts, {"A": 1, "B": 1})

    def test_34_the_batch_results_failure_codes_messages_and_dicts_are_never_used(self):
        batch = run_web_request_batch((None, 1))
        with mock.patch.object(WebRequestBatchResult, "codes", boom), mock.patch.object(WebRequestBatchResult, "to_dict", boom):
            s = create_web_request_batch_summary(batch)
        self.assertEqual(s.failure_count, 2)

    def test_35_the_outputs_are_unchanged_and_the_same_objects(self):
        outs = [make_output("A", "x"), make_output("B", "y")]
        batch = batch_with(outs)
        before = [(o, o.to_dict(), hash(o)) for o in batch.outputs]
        snapshot = (batch, batch.to_dict(), hash(batch), batch.outputs)
        create_web_request_batch_summary(batch)
        for o, (same, as_dict, h) in zip(batch.outputs, before):
            self.assertIs(o, same)
            self.assertEqual((o.to_dict(), hash(o)), (as_dict, h))
        self.assertEqual((batch, batch.to_dict(), hash(batch)), snapshot[:3])
        self.assertIs(batch.outputs, snapshot[3])
        self.assertEqual([o for o in batch.outputs], outs)


class TestImmutability(unittest.TestCase):
    def _summaries(self):
        return (create_web_request_batch_summary(batch_with([make_output("A", "x"), make_output("B", "y")])),
                create_web_request_batch_summary(run_web_request_batch(())), create_web_request_batch_summary(None),
                create_web_request_batch_summary(raw_batch((object(),), ())))

    def test_36_returned_summary_is_immutable(self):
        for s in self._summaries():
            for attr in ("total_count", "output_count", "failure_count", "status_counts", "code_counts", "success", "_total_count", "_status_counts",
                         "_codes", "extra"):
                with self.assertRaises(AttributeError, msg=attr):
                    setattr(s, attr, 1)
            for attr in ("output_count", "_code_counts"):
                with self.assertRaises(AttributeError, msg=attr):
                    delattr(s, attr)
            with self.assertRaises(AttributeError):
                s.__dict__

    def test_37_mappings_codes_and_to_dict_are_fresh_copies(self):
        s = create_web_request_batch_summary(batch_with([make_output("A", "x"), make_output("B", "y")]))
        st = s.status_counts
        st["A"] = 99
        st["new"] = 1
        cc = s.code_counts
        cc.clear()
        d = s.to_dict()
        d["status_counts"]["B"] = 50
        d["code_counts"]["q"] = 1
        d["codes"].append("x")
        d["success"] = False
        d["total_count"] = -1
        self.assertEqual(s.status_counts, {"A": 1, "B": 1})
        self.assertEqual(s.code_counts, {"x": 1, "y": 1})
        self.assertEqual(s.to_dict()["codes"], [])
        self.assertTrue(s.to_dict()["success"])
        self.assertEqual(s.total_count, 2)
        self.assertIsNot(s.status_counts, s.status_counts)
        self.assertIsNot(s.code_counts, s.code_counts)
        self.assertIsNot(s.to_dict(), s.to_dict())
        self.assertIsNot(s.to_dict()["status_counts"], s.to_dict()["status_counts"])
        codes = create_web_request_batch_summary(None).codes()
        codes.append("x")
        self.assertEqual(create_web_request_batch_summary(None).codes(), [INVALID])

    def test_38_copy_deepcopy_and_pickle(self):
        for s in self._summaries():
            self.assertIs(copy.copy(s), s)
            self.assertIs(copy.deepcopy(s), s)
            with self.assertRaises(TypeError):
                pickle.dumps(s)

    def test_39_no_direct_construction_and_no_subclassing(self):
        with self.assertRaises(TypeError):
            WebRequestBatchSummary(object(), 0, 0, 0, (), (), True, ())
        with self.assertRaises(TypeError):
            WebRequestBatchSummary(None, 0, 0, 0, (), (), True, ())
        with self.assertRaises(TypeError):
            type("Sub", (WebRequestBatchSummary,), {})

    def test_40_value_equality_and_hash(self):
        a = create_web_request_batch_summary(batch_with([make_output("A", "x"), make_output("B", "y")]))
        same = create_web_request_batch_summary(batch_with([make_output("B", "y"), make_output("A", "x")]))
        other = create_web_request_batch_summary(batch_with([make_output("A", "x")]))
        self.assertEqual(a, same)
        self.assertEqual(hash(a), hash(same))
        self.assertNotEqual(a, other)
        self.assertNotEqual(a, create_web_request_batch_summary(None))
        self.assertNotEqual(create_web_request_batch_summary(None), create_web_request_batch_summary(raw_batch((object(),), ())))
        self.assertNotEqual(a, a.to_dict())
        self.assertNotEqual(a, "x")
        self.assertEqual(len({a, same, other}), 2)
        self.assertEqual({a: 1}[same], 1)

    def test_41_counts_that_differ_by_one_field_are_different_summaries(self):
        # same statuses but different codes; same codes but different statuses; same maps but different failure count
        base = create_web_request_batch_summary(batch_with([make_output("A", "x"), make_output("A", "y")]))
        self.assertNotEqual(base, create_web_request_batch_summary(batch_with([make_output("A", "x"), make_output("A", "x")])))
        self.assertNotEqual(base, create_web_request_batch_summary(batch_with([make_output("A", "x"), make_output("B", "y")])))
        self.assertNotEqual(create_web_request_batch_summary(run_web_request_batch(())), create_web_request_batch_summary(run_web_request_batch(None)))

    def test_42_repr_is_short_and_informative(self):
        self.assertEqual(repr(create_web_request_batch_summary(run_web_request_batch(()))),
                         "WebRequestBatchSummary(total_count=0, output_count=0, failure_count=0, success=True, codes=[])")
        self.assertEqual(repr(create_web_request_batch_summary(None)),
                         "WebRequestBatchSummary(total_count=0, output_count=0, failure_count=0, success=False, codes=['%s'])" % INVALID)

    def test_43_codes_are_stable_and_prefixed(self):
        self.assertEqual(ws.CODES, (INVALID, MALFORMED))
        self.assertEqual((ws.CODE_INVALID_RESULT, ws.CODE_MALFORMED_RESULT), (INVALID, MALFORMED))
        self.assertTrue(all(c.startswith("WEB_REQUEST_BATCH_SUMMARY_") for c in ws.CODES))


class TestNoRetention(unittest.TestCase):
    def test_44_batch_result_and_outputs_are_not_retained_by_the_summary(self):
        batch = batch_with([make_output("A", "x"), make_output("B", "y")])
        s = create_web_request_batch_summary(batch)
        held = {id(batch)} | {id(o) for o in batch.outputs} | {id(batch.outputs)}
        self.assertFalse(any(id(r) in held for r in gc.get_referents(s)))
        self.assertFalse(any(r is s for r in gc.get_referents(batch)))
        self.assertFalse(any(h is s for h in gc.get_referrers(batch)))
        for slot in WebRequestBatchSummary.__slots__:
            self.assertTrue(plain(object.__getattribute__(s, slot)), slot)

    def test_45_outputs_live_only_as_long_as_the_batch(self):
        before_out, before_batch = len(live(WebRequestOutput)), len(live(WebRequestBatchResult))
        batch = batch_with([make_output("A", "x") for _ in range(3)])
        s = create_web_request_batch_summary(batch)
        self.assertEqual(len(live(WebRequestOutput)), before_out + 3)       # sanity: the scan sees the outputs
        self.assertEqual(len(live(WebRequestBatchResult)), before_batch + 1)
        del batch
        self.assertEqual(len(live(WebRequestOutput)), before_out)           # the summary is alive and keeps none of them
        self.assertEqual(len(live(WebRequestBatchResult)), before_batch)
        self.assertEqual(s.status_counts, {"A": 3})

    def test_46_rejected_summaries_hold_only_plain_values(self):
        for item in (None, raw_batch((object(),), ()), raw_batch((), [("x",)])):
            s = create_web_request_batch_summary(item)
            for slot in WebRequestBatchSummary.__slots__:
                self.assertTrue(plain(object.__getattribute__(s, slot)), slot)

    def test_47_module_has_no_global_state(self):
        before = dict(vars(ws))
        for item in (batch_with([make_output("A", "x")]), run_web_request_batch(()), None, raw_batch((object(),), ()), 1):
            create_web_request_batch_summary(item)
        after = vars(ws)
        self.assertEqual(set(after), set(before))
        for name, value in after.items():
            self.assertIs(value, before[name], name)
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set, WebRequestBatchResult, WebRequestBatchSummary, WebRequestOutput), name)


class TestDeterminism(unittest.TestCase):
    def test_48_repeated_calls_are_deterministic(self):
        for batch in (batch_with([make_output("A", "x"), make_output("B", "y")]), run_web_request_batch(()), run_web_request_batch((None,)), None,
                      raw_batch((object(),), ())):
            results = [create_web_request_batch_summary(batch) for _ in range(5)]
            for r in results[1:]:
                self.assertEqual(r, results[0])
                self.assertEqual(hash(r), hash(results[0]))
                self.assertEqual(r.to_dict(), results[0].to_dict())
                self.assertEqual(list(r.status_counts), list(results[0].status_counts))

    def test_49_equal_but_distinct_batches_give_equal_summaries(self):
        a = create_web_request_batch_summary(run_web_request_batch((make_plan(), make_plan(request_id="b"))))
        b = create_web_request_batch_summary(run_web_request_batch((make_plan(), make_plan(request_id="b"))))
        self.assertEqual(a, b)

    def test_50_earlier_calls_do_not_influence_later_ones(self):
        batch = batch_with([make_output("A", "x"), make_output("B", "y")])
        first = create_web_request_batch_summary(batch)
        create_web_request_batch_summary(None)
        create_web_request_batch_summary(batch_with([make_output("Z", "z")]))
        create_web_request_batch_summary(raw_batch((object(),), ()))
        self.assertEqual(create_web_request_batch_summary(batch), first)

    def test_51_summary_matches_a_straightforward_recount(self):
        outs = [make_output("s%d" % (i * 7 % 5), "c%d" % (i * 3 % 4)) for i in range(40)]
        s = create_web_request_batch_summary(batch_with(outs))
        self.assertEqual(s.status_counts, {k: sum(1 for o in outs if o.status == k) for k in sorted({o.status for o in outs})})
        self.assertEqual(s.code_counts, {k: sum(1 for o in outs if o.code == k) for k in sorted({o.code for o in outs})})


class TestNoSideEffects(unittest.TestCase):
    def test_52_no_side_effects_filesystem_environment_or_modules(self):
        batch = batch_with([make_output("A", "x")])
        before_env, before_cwd, before_mods = dict(os.environ), os.getcwd(), set(sys.modules)
        before_tree = sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d)
        for _ in range(3):
            for item in (batch, run_web_request_batch(()), None, 1, raw_batch((object(),), ())):
                create_web_request_batch_summary(item)
        self.assertEqual(dict(os.environ), before_env)
        self.assertEqual(os.getcwd(), before_cwd)
        self.assertEqual(set(sys.modules), before_mods)
        self.assertEqual(sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d), before_tree)
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)

    def test_53_no_network_filesystem_subprocess_or_database_access(self):
        import builtins
        import io
        import os as _os
        import shutil
        import socket
        import sqlite3
        import subprocess
        import urllib.request
        batch = run_web_request_batch((make_plan(), make_plan(request_id="b")))
        with mock.patch.object(socket, "socket", boom), mock.patch.object(socket, "create_connection", boom), \
                mock.patch.object(socket, "getaddrinfo", boom), mock.patch.object(urllib.request, "urlopen", boom), \
                mock.patch.object(subprocess, "Popen", boom), mock.patch.object(subprocess, "run", boom), \
                mock.patch.object(_os, "system", boom), mock.patch.object(_os, "popen", boom), \
                mock.patch.object(builtins, "open", boom), mock.patch.object(io, "open", boom), \
                mock.patch.object(_os, "open", boom), mock.patch.object(_os, "listdir", boom), \
                mock.patch.object(_os, "remove", boom), mock.patch.object(_os, "mkdir", boom), \
                mock.patch.object(shutil, "copy", boom), mock.patch.object(sqlite3, "connect", boom):
            self.assertEqual(create_web_request_batch_summary(batch).output_count, 2)
            self.assertTrue(create_web_request_batch_summary(run_web_request_batch(())).success)
            self.assertEqual(create_web_request_batch_summary(None).codes(), [INVALID])
            self.assertEqual(create_web_request_batch_summary(raw_batch((object(),), ())).codes(), [MALFORMED])

    def test_54_no_network_system_clock_random_or_concurrency_module_is_used(self):
        for name in ("socket", "http.client", "urllib.request", "requests", "ssl", "sqlite3", "subprocess", "os", "sys", "shutil", "io", "threading",
                     "time", "random", "copy", "pickle"):
            self.assertNotIn(name, vars(ws))
        import random
        import threading
        import time
        with mock.patch.object(time, "time", boom), mock.patch.object(time, "sleep", boom), mock.patch.object(random, "random", boom), \
                mock.patch.object(threading, "Thread", boom):
            self.assertTrue(create_web_request_batch_summary(run_web_request_batch(())).success)


class TestNoExecutionAndIndependence(unittest.TestCase):
    def test_55_summarising_runs_nothing_again(self):
        disp = mock.Mock(wraps=dispatch_web_request)
        ex = mock.Mock(wraps=execute_web_request_plan)
        fac = mock.Mock(wraps=create_web_request_output)
        pipe = mock.Mock(wraps=run_web_request_pipeline)
        with mock.patch.object(wb, "run_web_request_pipeline", pipe), mock.patch.object(wp, "dispatch_web_request", disp), \
                mock.patch.object(wdisp, "execute_web_request_plan", ex), mock.patch.object(wdisp, "create_web_request_output", fac):
            batch = run_web_request_batch(tuple(make_plan(request_id="p%d" % i) for i in range(3)))
            self.assertEqual([m.call_count for m in (pipe, disp, ex, fac)], [3, 3, 3, 3])
            for _ in range(4):
                s = create_web_request_batch_summary(batch)
                create_web_request_batch_summary(None)
            self.assertEqual([m.call_count for m in (pipe, disp, ex, fac)], [3, 3, 3, 3])      # unchanged: no duplicate execution
        self.assertEqual(s.output_count, 3)

    def test_56_summary_works_with_the_whole_chain_disabled(self):
        batch = run_web_request_batch((make_plan(), make_plan(request_id="b")))
        with mock.patch.object(wb, "run_web_request_pipeline", boom), mock.patch.object(wp, "run_web_request_pipeline", boom), \
                mock.patch.object(wp, "dispatch_web_request", boom), mock.patch.object(wdisp, "dispatch_web_request", boom, create=True), \
                mock.patch.object(wdisp, "execute_web_request_plan", boom), mock.patch.object(wdisp, "create_web_request_output", boom):
            s = create_web_request_batch_summary(batch)
            self.assertEqual((s.output_count, s.status_counts), (2, {"NOT_IMPLEMENTED": 2}))
            self.assertEqual(create_web_request_batch_summary(run_web_request_batch(())).total_count, 0)

    def test_57_summary_module_has_no_chain_or_batch_runner_names(self):
        for name in ("run_web_request_pipeline", "run_web_request_batch", "dispatch_web_request", "execute_web_request_plan", "create_web_request_output",
                     "create_web_request_plan", "validate_web_request", "create_web_request", "WebRequestPlan", "WebRequestExecutionResult"):
            self.assertNotIn(name, vars(ws))
        self.assertIs(ws.WebRequestBatchResult, WebRequestBatchResult)
        self.assertIs(ws.WebRequestOutput, WebRequestOutput)


class TestBoundaries(unittest.TestCase):
    def _tree(self):
        with open(MODULE, encoding="utf-8") as fh:
            return ast.parse(fh.read())

    def test_58_module_imports_only_the_batch_result_type_and_the_output_type(self):
        imports = [(n.module, n.level, sorted(a.name for a in n.names)) for n in ast.walk(self._tree()) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(sorted(imports), sorted([("web_request_batch", 1, ["WebRequestBatchResult"]), ("web_request_output", 1, ["WebRequestOutput"])]))

    def test_59_module_is_pure_and_depends_on_no_pipeline_dispatcher_or_executor(self):
        tree = self._tree()
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_web_request_batch_summary")
        calls = {ast.unparse(n.func) for n in ast.walk(function) if isinstance(n, ast.Call)}
        self.assertEqual(calls, {"type", "_rejected", "len", "WebRequestBatchSummary", "status_counts.get", "code_counts.get", "sorted",
                                 "status_counts.items", "code_counts.items"})
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("os", "sys", "io", "pathlib", "subprocess", "socket", "urllib", "http", "requests", "ssl", "sqlite3", "shutil", "random", "time",
                     "datetime", "threading", "asyncio", "concurrent", "anthropic", "openai", "multimedia", "game_creation", "core", "agent", "planning",
                     "run_web_request_pipeline", "run_web_request_batch", "dispatch_web_request", "execute_web_request_plan", "create_web_request_output",
                     "WebRequestExecutionResult", "WebRequestPlan", "validate_web_request", "create_web_request_plan", "Counter", "defaultdict"):
            self.assertNotIn(word, names, word)
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for field in ("metadata", "to_dict", "codes", "request_id", "url", "method", "resource_type", "timeout_ms", "_items", "_status", "_code",
                      "_outputs", "_failures", "message", "field"):
            self.assertNotIn(field, attrs - {"_codes"}, field)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.ImportFrom))
        self.assertEqual([n.name for n in tree.body if isinstance(n, ast.FunctionDef)], ["_rejected", "create_web_request_batch_summary"])
        self.assertEqual([n.name for n in tree.body if isinstance(n, ast.ClassDef)], ["WebRequestBatchSummary"])

    def test_60_the_only_batch_result_and_output_reads_are_the_public_ones(self):
        function = next(n for n in self._tree().body if isinstance(n, ast.FunctionDef) and n.name == "create_web_request_batch_summary")
        reads = sorted(f"{ast.unparse(n.value)}.{n.attr}" for n in ast.walk(function) if isinstance(n, ast.Attribute)
                       and isinstance(n.value, ast.Name) and n.value.id in ("batch_result", "output"))
        self.assertEqual(reads, ["batch_result.failures", "batch_result.ok", "batch_result.outputs", "output.code", "output.status"])

    def test_61_public_function_signature_is_exactly_one_positional_parameter(self):
        function = next(n for n in self._tree().body if isinstance(n, ast.FunctionDef) and n.name == "create_web_request_batch_summary")
        self.assertEqual([a.arg for a in function.args.args], ["batch_result"])
        self.assertIsNone(function.args.vararg)
        self.assertIsNone(function.args.kwarg)
        self.assertEqual((function.args.defaults, function.args.kwonlyargs), ([], []))

    def test_62_earlier_web_modules_are_unaware_of_the_summary(self):
        for name in ("web_resource.py", "web_resource_registry.py", "web_request.py", "web_request_validator.py", "web_request_plan.py",
                     "web_request_executor.py", "web_request_output.py", "web_request_output_validator.py", "web_request_metadata_executor.py",
                     "web_request_dispatcher.py", "web_request_pipeline.py", "web_request_batch.py"):
            with open(os.path.join(PY_ROOT, "web", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("web_request_batch_summary", "create_web_request_batch_summary", "WebRequestBatchSummary"):
                self.assertNotIn(token, text, (name, token))

    def test_63_no_production_module_outside_web_references_it(self):
        tokens = ("web_request_batch_summary", "create_web_request_batch_summary", "WebRequestBatchSummary")
        skip = {"web", "tests", "__pycache__", "data"}
        checked = 0
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if not (folder == PY_ROOT and d in skip) and d != "__pycache__"]
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        text = fh.read()
                    for token in tokens:
                        self.assertNotIn(token, text, os.path.join(folder, name))
                    checked += 1
        self.assertGreater(checked, 100)

    def test_64_web_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "web")) if f != "__pycache__"),
                         ["__init__.py", "web_request.py", "web_request_batch.py", "web_request_batch_summary.py", "web_request_dispatcher.py",
                          "web_request_executor.py", "web_request_metadata_executor.py", "web_request_output.py", "web_request_output_validator.py",
                          "web_request_pipeline.py", "web_request_plan.py", "web_request_validator.py", "web_resource.py", "web_resource_registry.py"])
        with open(os.path.join(PY_ROOT, "web", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_65_project_database_is_the_pristine_baseline(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)

    def test_66_end_to_end_through_public_apis_only(self):
        plans = (make_plan(request_id="e1", url="https://svc.example/v1", method="POST", resource_type="api", timeout_ms=250), make_plan(request_id="e2"))
        batch = run_web_request_batch(plans)
        s = create_web_request_batch_summary(batch)
        self.assertEqual(s.to_dict(), {"total_count": 2, "output_count": 2, "failure_count": 0, "status_counts": {"NOT_IMPLEMENTED": 2},
                                       "code_counts": {NOT_IMPL: 2}, "success": True, "codes": []})
        rejected_batch = create_web_request_batch_summary(run_web_request_batch((None, None)))
        self.assertEqual((rejected_batch.total_count, rejected_batch.output_count, rejected_batch.failure_count, rejected_batch.success),
                         (2, 0, 2, False))

    def test_67_documentation_exists_and_names_the_public_api(self):
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for token in ("Prompt 785", "create_web_request_batch_summary", "WebRequestBatchSummary", "WebRequestBatchResult", INVALID, MALFORMED,
                      "status_counts", "code_counts", "total_count", "output_count", "failure_count", "NOT_IMPLEMENTED"):
            self.assertIn(token, text, token)


if __name__ == "__main__":
    unittest.main()
