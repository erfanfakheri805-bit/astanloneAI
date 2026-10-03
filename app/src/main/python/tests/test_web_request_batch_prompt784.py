"""Prompt 784 - Section 9 web request batch (`web.web_request_batch`)."""
import ast
import collections
import copy
import gc
import hashlib
import os
import pickle
import sys
import unittest
import weakref
from unittest import mock

from web import web_request_batch as wb
from web import web_request_dispatcher as wdisp
from web import web_request_pipeline as wp
from web.web_request import create_web_request
from web.web_request_batch import WebRequestBatchResult, run_web_request_batch
from web.web_request_dispatcher import dispatch_web_request
from web.web_request_executor import WebRequestExecutionResult, execute_web_request_plan
from web.web_request_output import WebRequestOutput, create_web_request_output
from web.web_request_pipeline import run_web_request_pipeline
from web.web_request_plan import WebRequestPlan, create_web_request_plan
from web.web_request_validator import validate_web_request
from web.web_resource import create_web_resource
from web.web_resource_registry import create_web_resource_registry

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section9_web_request_batch_prompt784.md")
MODULE = os.path.join(PY_ROOT, "web", "web_request_batch.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
INVALID_COLLECTION = "WEB_REQUEST_BATCH_INVALID_COLLECTION"
INVALID_PLAN = "WEB_REQUEST_BATCH_INVALID_PLAN"
NOT_IMPL = "WEB_REQUEST_EXECUTOR_NOT_IMPLEMENTED"
PIPELINE_INVALID = "WEB_REQUEST_PIPELINE_INVALID_PLAN"
FIELDS = ("request_id", "url", "method", "resource_type", "timeout_ms")
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


class Lookalike:
    request_id, url, method, resource_type, timeout_ms = "req_1", "https://example.org/x", "GET", "page", 5000

    def to_dict(self):
        return dict(DEFAULT)


class SpoofedClass:
    """isinstance() says it is a WebRequestPlan; its exact type is not."""

    @property
    def __class__(self):
        return WebRequestPlan


class Hostile:
    """Raises on any attribute read, comparison, hashing, iteration, length or repr: proves an input is never looked into."""

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


class HostileTuple(tuple):
    def __iter__(self):
        raise AssertionError("a rejected tuple subclass must not be iterated")

    def __len__(self):
        raise AssertionError("a rejected tuple subclass must not be measured")

    def __getitem__(self, index):
        raise AssertionError("a rejected tuple subclass must not be indexed")


Pair = collections.namedtuple("Pair", "first second")


def live(cls):
    gc.collect()
    return [o for o in gc.get_objects() if type(o) is cls]


def ids_of(result):
    return [o.metadata["request_id"] for o in result.outputs]


class TestValidBatch(unittest.TestCase):
    def test_1_valid_empty_batch(self):
        result = run_web_request_batch(())
        self.assertIs(type(result), WebRequestBatchResult)
        self.assertTrue(result.ok)
        self.assertEqual(result.outputs, ())
        self.assertIs(type(result.outputs), tuple)
        self.assertEqual(result.failures, ())
        self.assertEqual(result.codes(), [])
        self.assertEqual(result.to_dict(), {"ok": True, "outputs": [], "failures": []})

    def test_2_empty_batch_never_calls_the_pipeline(self):
        spy = mock.Mock(wraps=run_web_request_pipeline)
        with mock.patch.object(wb, "run_web_request_pipeline", spy):
            self.assertTrue(run_web_request_batch(()).ok)
        spy.assert_not_called()

    def test_3_valid_single_plan_batch(self):
        plan = make_plan()
        result = run_web_request_batch((plan,))
        self.assertTrue(result.ok)
        self.assertEqual(len(result.outputs), 1)
        out = result.outputs[0]
        self.assertIs(type(out), WebRequestOutput)
        self.assertEqual(out, run_web_request_pipeline(plan))
        self.assertEqual((out.status, out.code), ("NOT_IMPLEMENTED", NOT_IMPL))
        self.assertEqual(out.metadata, DEFAULT)
        self.assertEqual(result.failures, ())
        self.assertEqual(result.codes(), [])

    def test_4_multiple_plans_each_get_their_own_output(self):
        plans = (make_plan(request_id="a"), make_plan(request_id="b", method="POST"), make_plan(request_id="c", resource_type="api", timeout_ms=250))
        result = run_web_request_batch(plans)
        self.assertTrue(result.ok)
        self.assertEqual(len(result.outputs), 3)
        for plan, out in zip(plans, result.outputs):
            self.assertEqual(out, run_web_request_pipeline(plan))
            self.assertEqual(out.metadata, plan.to_dict())
            self.assertEqual(out.code, NOT_IMPL)
        self.assertEqual(len({o for o in result.outputs}), 3)

    def test_5_input_order_is_preserved_not_sorted(self):
        names = ("z", "a", "m", "b", "Z", "10", "9")
        plans = tuple(make_plan(request_id=n) for n in names)
        self.assertEqual(ids_of(run_web_request_batch(plans)), list(names))
        self.assertEqual(ids_of(run_web_request_batch(plans[::-1])), list(names[::-1]))
        self.assertNotEqual(ids_of(run_web_request_batch(plans)), sorted(names))

    def test_6_duplicate_plans_are_not_deduplicated(self):
        plan = make_plan()
        twin = make_plan()
        self.assertIsNot(plan, twin)
        self.assertEqual(plan, twin)
        result = run_web_request_batch((plan, plan, twin))
        self.assertTrue(result.ok)
        self.assertEqual(len(result.outputs), 3)
        self.assertEqual(result.outputs[0], result.outputs[1])
        self.assertEqual(result.outputs[1], result.outputs[2])

    def test_7_values_pass_through_unchanged_for_unusual_but_valid_plans(self):
        plan = make_plan(request_id="  r 1  ", url="HTTPS://Example.ORG/X ", method="get", timeout_ms=1)
        out = run_web_request_batch((plan,)).outputs[0]
        self.assertEqual(out.metadata, plan.to_dict())
        for field in FIELDS:
            self.assertIs(out.metadata[field], getattr(plan, field), field)
        self.assertEqual(list(out.metadata), list(FIELDS))

    def test_8_a_larger_batch_keeps_length_and_order(self):
        plans = tuple(make_plan(request_id="r%03d" % i, timeout_ms=i + 1) for i in range(200))
        result = run_web_request_batch(plans)
        self.assertTrue(result.ok)
        self.assertEqual(ids_of(result), ["r%03d" % i for i in range(200)])
        self.assertEqual([o.metadata["timeout_ms"] for o in result.outputs], list(range(1, 201)))

    def test_9_to_dict_lists_each_output_in_order(self):
        plans = (make_plan(request_id="a"), make_plan(request_id="b"))
        result = run_web_request_batch(plans)
        self.assertEqual(result.to_dict(), {"ok": True, "failures": [],
                                            "outputs": [run_web_request_pipeline(p).to_dict() for p in plans]})
        self.assertEqual(list(result.to_dict()), ["ok", "outputs", "failures"])


class TestPipelineCalls(unittest.TestCase):
    def test_10_pipeline_is_called_exactly_once_per_plan_with_that_plan(self):
        plans = (make_plan(request_id="a"), make_plan(request_id="b"), make_plan(request_id="c"))
        spy = mock.Mock(wraps=run_web_request_pipeline)
        with mock.patch.object(wb, "run_web_request_pipeline", spy):
            result = run_web_request_batch(plans)
        self.assertEqual(spy.call_count, 3)
        for call, plan in zip(spy.call_args_list, plans):
            self.assertEqual(len(call.args), 1)
            self.assertIs(call.args[0], plan)
            self.assertEqual(call.kwargs, {})
        self.assertEqual(ids_of(result), ["a", "b", "c"])

    def test_11_pipeline_is_called_in_input_order(self):
        order = []

        def spy(plan):
            order.append(plan.request_id)
            return run_web_request_pipeline(plan)
        names = ("q", "b", "x", "a")
        with mock.patch.object(wb, "run_web_request_pipeline", spy):
            run_web_request_batch(tuple(make_plan(request_id=n) for n in names))
        self.assertEqual(order, list(names))

    def test_12_the_same_plan_twice_is_two_calls(self):
        plan = make_plan()
        spy = mock.Mock(wraps=run_web_request_pipeline)
        with mock.patch.object(wb, "run_web_request_pipeline", spy):
            result = run_web_request_batch((plan, plan))
        self.assertEqual(spy.call_count, 2)
        self.assertEqual(len(result.outputs), 2)

    def test_13_pipeline_outputs_are_propagated_as_the_same_objects(self):
        sentinels = [run_web_request_pipeline(make_plan(request_id="s1")), run_web_request_pipeline(None),
                     dispatch_web_request(None), create_web_request_output(execute_web_request_plan(None))]
        feed = iter(sentinels)
        with mock.patch.object(wb, "run_web_request_pipeline", mock.Mock(side_effect=lambda plan: next(feed))):
            result = run_web_request_batch(tuple(make_plan(request_id="p%d" % i) for i in range(4)))
        self.assertEqual(len(result.outputs), 4)
        for out, sentinel in zip(result.outputs, sentinels):
            self.assertIs(out, sentinel)
            self.assertEqual(out.to_dict(), sentinel.to_dict())

    def test_14_whatever_the_pipeline_returns_is_kept_unexamined(self):
        junk = (object(), None, 5, "text", [1], {"a": 1})
        feed = iter(junk)
        with mock.patch.object(wb, "run_web_request_pipeline", mock.Mock(side_effect=lambda plan: next(feed))):
            result = run_web_request_batch(tuple(make_plan(request_id="j%d" % i) for i in range(len(junk))))
        self.assertTrue(result.ok)                       # statuses / types of outputs are never interpreted
        self.assertEqual(len(result.outputs), len(junk))
        for out, item in zip(result.outputs, junk):
            self.assertIs(out, item)

    def test_15_a_rejected_pipeline_output_does_not_change_ok_or_get_recoded(self):
        rejected = run_web_request_pipeline(None)
        with mock.patch.object(wb, "run_web_request_pipeline", mock.Mock(return_value=rejected)):
            result = run_web_request_batch((make_plan(),))
        self.assertTrue(result.ok)
        self.assertIs(result.outputs[0], rejected)
        self.assertEqual(result.outputs[0].code, PIPELINE_INVALID)
        self.assertEqual(result.codes(), [])

    def test_16_batch_uses_the_public_pipeline_and_adds_no_chain_logic(self):
        self.assertIs(wb.run_web_request_pipeline, wp.run_web_request_pipeline)
        self.assertIs(wb.WebRequestPlan, WebRequestPlan)
        for name in ("dispatch_web_request", "execute_web_request_plan", "create_web_request_output", "WebRequestOutput"):
            self.assertNotIn(name, vars(wb))

    def test_17_dispatcher_executor_and_factory_run_once_per_plan_inside_the_chain_only(self):
        plans = (make_plan(request_id="a"), make_plan(request_id="b"), make_plan(request_id="c"))
        disp = mock.Mock(wraps=dispatch_web_request)
        ex = mock.Mock(wraps=execute_web_request_plan)
        fac = mock.Mock(wraps=create_web_request_output)
        with mock.patch.object(wp, "dispatch_web_request", disp), mock.patch.object(wdisp, "execute_web_request_plan", ex), \
                mock.patch.object(wdisp, "create_web_request_output", fac):
            result = run_web_request_batch(plans)
        for spy in (disp, ex, fac):
            self.assertEqual(spy.call_count, 3)
        self.assertEqual([c.args[0] for c in disp.call_args_list], list(plans))
        self.assertTrue(all(o.code == NOT_IMPL for o in result.outputs))

    def test_18_the_batch_does_not_re_run_or_re_validate_a_plan(self):
        plan = make_plan()
        spy = mock.Mock(wraps=run_web_request_pipeline)
        with mock.patch.object(wb, "run_web_request_pipeline", spy):
            run_web_request_batch((plan,))
            self.assertEqual(spy.call_count, 1)
            run_web_request_batch((plan,))
            self.assertEqual(spy.call_count, 2)


class TestInvalidCollection(unittest.TestCase):
    def _inputs(self):
        plan = make_plan()
        return (None, [], [plan], list((plan,)), {}, {"plans": plan}, set(), {plan}, frozenset(), "plans", b"plans", 1, 1.5, True,
                (x for x in (plan,)), iter((plan,)), range(2), object(), plan, WebRequestPlan, tuple, type(None), lambda: None, Pair(plan, plan),
                HostileTuple((plan,)), Hostile(), Lookalike())

    def test_19_every_non_tuple_collection_is_rejected_deterministically(self):
        for item in self._inputs():
            result = run_web_request_batch(item)
            self.assertIs(type(result), WebRequestBatchResult)
            self.assertFalse(result.ok)
            self.assertEqual(result.outputs, ())
            self.assertEqual(result.codes(), [INVALID_COLLECTION])
            self.assertEqual(result.failures, ({"code": INVALID_COLLECTION, "field": "plans",
                                                "message": "plans must be exactly a tuple of WebRequestPlan objects."},))
            self.assertEqual(result.to_dict(), {"ok": False, "outputs": [], "failures": [dict(result.failures[0])]})

    def test_20_all_invalid_collections_give_equal_results(self):
        results = [run_web_request_batch(i) for i in self._inputs()]
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(len({hash(r) for r in results}), 1)

    def test_21_a_list_of_valid_plans_is_rejected_unlike_the_registry(self):
        plan = make_plan()
        self.assertFalse(run_web_request_batch([plan]).ok)
        self.assertFalse(run_web_request_batch([]).ok)
        self.assertTrue(run_web_request_batch(()).ok)
        self.assertTrue(run_web_request_batch((plan,)).ok)

    def test_22_tuple_subclasses_and_named_tuples_are_rejected(self):
        plan = make_plan()
        for item in (Pair(plan, plan), HostileTuple((plan,)), HostileTuple()):
            self.assertEqual(run_web_request_batch(item).codes(), [INVALID_COLLECTION])

    def test_23_a_single_plan_outside_a_tuple_is_rejected(self):
        self.assertEqual(run_web_request_batch(make_plan()).codes(), [INVALID_COLLECTION])

    def test_24_invalid_collection_never_reaches_the_pipeline(self):
        boom = mock.Mock(side_effect=AssertionError("must not be called"))
        with mock.patch.object(wb, "run_web_request_pipeline", boom):
            for item in self._inputs():
                self.assertEqual(run_web_request_batch(item).codes(), [INVALID_COLLECTION])
        boom.assert_not_called()

    def test_25_invalid_collection_is_never_read_or_iterated(self):
        self.assertEqual(run_web_request_batch(Hostile()).codes(), [INVALID_COLLECTION])
        self.assertEqual(run_web_request_batch(HostileTuple()).codes(), [INVALID_COLLECTION])
        gen = (x for x in (make_plan(request_id="g1"), make_plan(request_id="g2")))
        self.assertEqual(run_web_request_batch(gen).codes(), [INVALID_COLLECTION])
        self.assertEqual(next(gen).request_id, "g1")           # not consumed
        self.assertEqual(next(gen).request_id, "g2")

    def test_26_invalid_collection_is_not_changed(self):
        items = [make_plan(request_id="a")]
        mapping = {"a": 1}
        run_web_request_batch(items)
        run_web_request_batch(mapping)
        self.assertEqual([p.request_id for p in items], ["a"])
        self.assertEqual(mapping, {"a": 1})


class TestInvalidPlanItem(unittest.TestCase):
    def _items(self):
        plan = make_plan()
        return (None, {}, dict(DEFAULT), "plan", 1, 1.5, True, [], (), (plan,), object(), Lookalike(), SpoofedClass(), WebRequestPlan, type(None),
                b"x", set(), lambda: None, execute_web_request_plan(plan), dispatch_web_request(plan), run_web_request_pipeline(plan),
                run_web_request_batch((plan,)), plan.to_dict(), Hostile())

    def test_27_every_non_plan_item_is_rejected_deterministically(self):
        for item in self._items():
            result = run_web_request_batch((item,))
            self.assertIs(type(result), WebRequestBatchResult)
            self.assertFalse(result.ok)
            self.assertEqual(result.outputs, ())
            self.assertEqual(result.codes(), [INVALID_PLAN])
            self.assertEqual(result.failures, ({"code": INVALID_PLAN, "field": "plans[0]", "message": "plans[0] must be exactly a WebRequestPlan."},))

    def test_28_the_spoofed_class_would_pass_isinstance_but_is_rejected(self):
        self.assertTrue(isinstance(SpoofedClass(), WebRequestPlan))
        self.assertEqual(run_web_request_batch((SpoofedClass(),)).codes(), [INVALID_PLAN])
        with self.assertRaises(TypeError):
            type("Sub", (WebRequestPlan,), {})

    def test_29_the_index_names_the_position_of_the_bad_item(self):
        good = [make_plan(request_id="g%d" % i) for i in range(3)]
        for position in range(4):
            items = list(good)
            items.insert(position, None)
            result = run_web_request_batch(tuple(items))
            self.assertEqual(result.codes(), [INVALID_PLAN])
            self.assertEqual(result.failures[0]["field"], "plans[%d]" % position)
            self.assertEqual(result.outputs, ())

    def test_30_every_bad_item_is_reported_together_in_input_order(self):
        a, b = make_plan(request_id="a"), make_plan(request_id="b")
        result = run_web_request_batch((None, a, "x", b, 3, a))
        self.assertFalse(result.ok)
        self.assertEqual(result.codes(), [INVALID_PLAN] * 3)
        self.assertEqual([f["field"] for f in result.failures], ["plans[0]", "plans[2]", "plans[4]"])
        self.assertEqual(result.outputs, ())

    def test_31_a_bad_item_means_no_pipeline_call_even_for_the_valid_items(self):
        spy = mock.Mock(wraps=run_web_request_pipeline)
        plans = tuple(make_plan(request_id="v%d" % i) for i in range(3))
        with mock.patch.object(wb, "run_web_request_pipeline", spy):
            for bad_position in (0, 1, 3):
                items = list(plans)
                items.insert(bad_position, None)
                self.assertEqual(run_web_request_batch(tuple(items)).codes(), [INVALID_PLAN])
        spy.assert_not_called()

    def test_32_items_are_checked_before_any_plan_runs(self):
        calls = []
        with mock.patch.object(wb, "run_web_request_pipeline", lambda plan: calls.append(plan) or run_web_request_pipeline(plan)):
            run_web_request_batch((make_plan(), make_plan(request_id="b"), object()))
        self.assertEqual(calls, [])

    def test_33_invalid_items_are_never_read_compared_hashed_or_repr_d(self):
        result = run_web_request_batch((Hostile(), make_plan(), Hostile()))
        self.assertEqual(result.codes(), [INVALID_PLAN, INVALID_PLAN])
        self.assertEqual([f["field"] for f in result.failures], ["plans[0]", "plans[2]"])
        for f in result.failures:
            self.assertEqual(set(f), {"code", "field", "message"})
            self.assertIs(type(f["message"]), str)

    def test_34_messages_are_deterministic_and_never_embed_the_object(self):
        class Noisy:
            pass
        first = run_web_request_batch((Noisy(),)).failures
        second = run_web_request_batch((Noisy(),)).failures
        self.assertEqual(first, second)
        self.assertNotIn("Noisy", first[0]["message"])
        self.assertNotIn("object at", first[0]["message"])

    def test_35_nested_tuples_are_not_flattened(self):
        a = make_plan()
        self.assertEqual(run_web_request_batch(((a, a),)).codes(), [INVALID_PLAN])
        self.assertEqual(run_web_request_batch(((),)).codes(), [INVALID_PLAN])

    def test_36_chain_objects_are_not_plans(self):
        plan = make_plan()
        for item in (execute_web_request_plan(plan), dispatch_web_request(plan), run_web_request_pipeline(plan), run_web_request_batch(())):
            self.assertEqual(run_web_request_batch((item,)).codes(), [INVALID_PLAN])


class TestNoRetention(unittest.TestCase):
    def test_37_input_tuple_is_not_retained(self):
        plans = (make_plan(request_id="a"), make_plan(request_id="b"))
        result = run_web_request_batch(plans)
        holders = gc.get_referrers(plans)
        self.assertFalse(any(h is result for h in holders))
        self.assertFalse(any(h is result._outputs or h is result._failures for h in holders))
        self.assertFalse(any(h is vars(wb) for h in holders))
        self.assertFalse(any(r is plans for r in gc.get_referents(result)))
        self.assertFalse(any(r is plans for r in gc.get_referents(vars(wb))))

    def test_38_plans_are_not_retained_by_the_result_or_the_module(self):
        before = len(live(WebRequestPlan))
        plans = (make_plan(request_id="a"), make_plan(request_id="b"), make_plan(request_id="c"))
        result = run_web_request_batch(plans)
        self.assertEqual(len(live(WebRequestPlan)), before + 3)         # sanity: the scan sees the plans
        for plan in plans:
            self.assertFalse(any(r is plan for r in gc.get_referents(result)))
            self.assertFalse(any(r is plan for r in gc.get_referents(result.outputs)))
            self.assertFalse(any(r is plan for r in gc.get_referents(vars(wb))))
        del plans, plan
        self.assertEqual(len(live(WebRequestPlan)), before)              # result is still alive, yet holds no plan
        self.assertEqual(ids_of(result), ["a", "b", "c"])

    def test_39_result_holds_only_outputs_and_plain_strings(self):
        result = run_web_request_batch((make_plan(),))
        self.assertEqual(sorted(type(result).__slots__), ["_failures", "_outputs"])
        self.assertIs(type(result._outputs), tuple)
        self.assertTrue(all(type(o) is WebRequestOutput for o in result._outputs))
        for o in result._outputs:
            for item in (o._status, o._code, o._items):
                self.assertNotIsInstance(item, (WebRequestPlan, WebRequestBatchResult))
        rejected = run_web_request_batch((None, 1))
        for triple in rejected._failures:
            self.assertEqual(len(triple), 3)
            self.assertTrue(all(type(x) is str for x in triple))

    def test_40_a_rejected_input_is_not_retained_by_the_result(self):
        class Weak:
            pass
        item = Weak()
        ref = weakref.ref(item)
        items = (item,)
        result = run_web_request_batch(items)
        self.assertEqual(result.codes(), [INVALID_PLAN])
        del item, items
        gc.collect()
        self.assertIsNone(ref())
        mapping_ref = weakref.ref(Weak_owner := Weak())
        self.assertEqual(run_web_request_batch(Weak_owner).codes(), [INVALID_COLLECTION])
        del Weak_owner
        gc.collect()
        self.assertIsNone(mapping_ref())

    def test_41_pipeline_outputs_live_only_as_long_as_the_result(self):
        before = len(live(WebRequestOutput))
        result = run_web_request_batch(tuple(make_plan(request_id="o%d" % i) for i in range(4)))
        self.assertEqual(len(live(WebRequestOutput)), before + 4)
        del result
        self.assertEqual(len(live(WebRequestOutput)), before)

    def test_42_module_has_no_global_state(self):
        before = dict(vars(wb))
        for item in ((make_plan(),), (), None, [make_plan()], (None,), 1):
            run_web_request_batch(item)
        after = vars(wb)
        self.assertEqual(set(after), set(before))
        for name, value in after.items():
            self.assertIs(value, before[name], name)
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set, WebRequestPlan, WebRequestOutput, WebRequestBatchResult), name)

    def test_43_plans_and_the_tuple_are_not_changed(self):
        plans = (make_plan(request_id="a"), make_plan(request_id="b"))
        snapshot = [(p, p.to_dict(), hash(p)) for p in plans]
        run_web_request_batch(plans)
        self.assertEqual(len(plans), 2)
        for plan, (same, as_dict, h) in zip(plans, snapshot):
            self.assertIs(plan, same)
            self.assertEqual((plan.to_dict(), hash(plan)), (as_dict, h))


class TestResultImmutability(unittest.TestCase):
    def _results(self):
        return (run_web_request_batch((make_plan(), make_plan(request_id="b"))), run_web_request_batch(()), run_web_request_batch(None),
                run_web_request_batch((None, 2)))

    def test_44_returned_result_is_immutable(self):
        for result in self._results():
            for attr in ("ok", "outputs", "failures", "_outputs", "_failures", "extra"):
                with self.assertRaises(AttributeError, msg=attr):
                    setattr(result, attr, ())
            for attr in ("outputs", "_failures"):
                with self.assertRaises(AttributeError, msg=attr):
                    delattr(result, attr)
            with self.assertRaises(AttributeError):
                result.__dict__

    def test_45_outputs_is_an_immutable_tuple(self):
        result = run_web_request_batch((make_plan(), make_plan(request_id="b")))
        self.assertIs(type(result.outputs), tuple)
        with self.assertRaises(TypeError):
            result.outputs[0] = None
        with self.assertRaises(AttributeError):
            result.outputs.append(None)
        self.assertIs(result.outputs, result.outputs)

    def test_46_failures_codes_and_to_dict_are_fresh_copies(self):
        result = run_web_request_batch((None, 2))
        failures = result.failures
        failures[0]["code"] = "changed"
        failures[1]["extra"] = 1
        codes = result.codes()
        codes.append("x")
        data = result.to_dict()
        data["ok"] = True
        data["failures"][0]["field"] = "changed"
        data["failures"].append({})
        self.assertEqual(result.codes(), [INVALID_PLAN, INVALID_PLAN])
        self.assertEqual([f["field"] for f in result.failures], ["plans[0]", "plans[1]"])
        self.assertEqual(len(result.to_dict()["failures"]), 2)
        self.assertFalse(result.to_dict()["ok"])
        self.assertIsNot(result.failures[0], result.failures[0])
        self.assertIsNot(result.to_dict(), result.to_dict())

    def test_47_to_dict_outputs_are_fresh_plain_data(self):
        result = run_web_request_batch((make_plan(),))
        data = result.to_dict()
        data["outputs"][0]["metadata"]["url"] = "changed"
        data["outputs"][0]["status"] = "OK"
        data["outputs"].append({})
        self.assertEqual(result.to_dict()["outputs"], [result.outputs[0].to_dict()])
        self.assertEqual(result.outputs[0].metadata, DEFAULT)

    def test_48_copy_deepcopy_and_pickle(self):
        for result in self._results():
            self.assertIs(copy.copy(result), result)
            self.assertIs(copy.deepcopy(result), result)
            with self.assertRaises(TypeError):
                pickle.dumps(result)

    def test_49_no_direct_construction_and_no_subclassing(self):
        with self.assertRaises(TypeError):
            WebRequestBatchResult(object(), (), ())
        with self.assertRaises(TypeError):
            WebRequestBatchResult(None, (), ())
        with self.assertRaises(TypeError):
            type("Sub", (WebRequestBatchResult,), {})

    def test_50_value_equality_and_hash(self):
        a = run_web_request_batch((make_plan(request_id="a"), make_plan(request_id="b")))
        same = run_web_request_batch((make_plan(request_id="a"), make_plan(request_id="b")))
        swapped = run_web_request_batch((make_plan(request_id="b"), make_plan(request_id="a")))
        other = run_web_request_batch((make_plan(request_id="a"),))
        self.assertEqual(a, same)
        self.assertEqual(hash(a), hash(same))
        self.assertNotEqual(a, swapped)
        self.assertNotEqual(a, other)
        self.assertNotEqual(a, run_web_request_batch(None))
        self.assertNotEqual(run_web_request_batch(()), run_web_request_batch(None))
        self.assertNotEqual(a, a.to_dict())
        self.assertNotEqual(a, "x")
        self.assertEqual(len({a, same, swapped, other}), 3)
        self.assertEqual({a: 1}[same], 1)

    def test_51_repr_is_short_and_informative(self):
        self.assertEqual(repr(run_web_request_batch(())), "WebRequestBatchResult(ok=True, outputs=0, codes=[])")
        self.assertEqual(repr(run_web_request_batch(None)), "WebRequestBatchResult(ok=False, outputs=0, codes=['%s'])" % INVALID_COLLECTION)
        self.assertEqual(repr(run_web_request_batch((make_plan(),))), "WebRequestBatchResult(ok=True, outputs=1, codes=[])")

    def test_52_failure_codes_are_stable_and_prefixed(self):
        self.assertEqual(wb.FAILURE_CODES, (INVALID_COLLECTION, INVALID_PLAN))
        self.assertEqual(wb.FAILURE_INVALID_COLLECTION, INVALID_COLLECTION)
        self.assertEqual(wb.FAILURE_INVALID_PLAN, INVALID_PLAN)
        self.assertTrue(all(c.startswith("WEB_REQUEST_BATCH_") for c in wb.FAILURE_CODES))
        self.assertEqual(len(set(wb.FAILURE_CODES)), 2)


class TestDeterminism(unittest.TestCase):
    def test_53_repeated_calls_are_deterministic(self):
        plans = (make_plan(request_id="a"), make_plan(request_id="b", method="PUT"))
        for item in (plans, (), None, (None, plans[0])):
            results = [run_web_request_batch(item) for _ in range(5)]
            for r in results[1:]:
                self.assertEqual(r, results[0])
                self.assertEqual(hash(r), hash(results[0]))
                self.assertEqual(r.to_dict(), results[0].to_dict())

    def test_54_equal_but_distinct_plan_objects_give_equal_results(self):
        self.assertEqual(run_web_request_batch((make_plan(), make_plan(request_id="b"))),
                         run_web_request_batch((make_plan(), make_plan(request_id="b"))))

    def test_55_order_and_content_change_the_result(self):
        a, b = make_plan(request_id="a"), make_plan(request_id="b")
        self.assertNotEqual(run_web_request_batch((a, b)), run_web_request_batch((b, a)))
        self.assertEqual(sorted(o.metadata["request_id"] for o in run_web_request_batch((a, b)).outputs),
                         sorted(o.metadata["request_id"] for o in run_web_request_batch((b, a)).outputs))
        self.assertNotEqual(run_web_request_batch((a,)), run_web_request_batch((a, a)))

    def test_56_earlier_calls_do_not_influence_later_ones(self):
        a, b = make_plan(request_id="a"), make_plan(request_id="b")
        first = run_web_request_batch((a, b))
        run_web_request_batch((b,))
        run_web_request_batch(None)
        run_web_request_batch((None,))
        self.assertEqual(run_web_request_batch((a, b)), first)

    def test_57_batch_equals_the_pipeline_applied_one_by_one(self):
        plans = tuple(make_plan(request_id="p%d" % i, timeout_ms=10 + i) for i in range(5))
        self.assertEqual(run_web_request_batch(plans).outputs, tuple(run_web_request_pipeline(p) for p in plans))


class TestNoSideEffects(unittest.TestCase):
    def test_58_no_side_effects_filesystem_environment_or_modules(self):
        plans = (make_plan(), make_plan(request_id="b"))
        before_env, before_cwd, before_mods = dict(os.environ), os.getcwd(), set(sys.modules)
        before_tree = sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d)
        for _ in range(3):
            for item in (plans, (), None, [plans[0]], (None,), 1):
                run_web_request_batch(item)
        self.assertEqual(dict(os.environ), before_env)
        self.assertEqual(os.getcwd(), before_cwd)
        self.assertEqual(set(sys.modules), before_mods)
        self.assertEqual(sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d), before_tree)
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)

    def test_59_no_network_filesystem_subprocess_or_database_access(self):
        import builtins
        import io
        import os as _os
        import shutil
        import socket
        import sqlite3
        import subprocess
        import urllib.request
        plans = (make_plan(), make_plan(request_id="b"))
        boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError("forbidden call"))
        with mock.patch.object(socket, "socket", boom), mock.patch.object(socket, "create_connection", boom), \
                mock.patch.object(socket, "getaddrinfo", boom), mock.patch.object(urllib.request, "urlopen", boom), \
                mock.patch.object(subprocess, "Popen", boom), mock.patch.object(subprocess, "run", boom), \
                mock.patch.object(_os, "system", boom), mock.patch.object(_os, "popen", boom), \
                mock.patch.object(builtins, "open", boom), mock.patch.object(io, "open", boom), \
                mock.patch.object(_os, "open", boom), mock.patch.object(_os, "listdir", boom), \
                mock.patch.object(_os, "remove", boom), mock.patch.object(_os, "mkdir", boom), \
                mock.patch.object(shutil, "copy", boom), mock.patch.object(sqlite3, "connect", boom):
            self.assertEqual(run_web_request_batch(plans).codes(), [])
            self.assertEqual(len(run_web_request_batch(plans).outputs), 2)
            self.assertTrue(run_web_request_batch(()).ok)
            self.assertEqual(run_web_request_batch(None).codes(), [INVALID_COLLECTION])
            self.assertEqual(run_web_request_batch((None,)).codes(), [INVALID_PLAN])

    def test_60_no_network_or_system_module_is_loaded_by_the_batch(self):
        for name in ("socket", "http.client", "urllib.request", "requests", "ssl", "sqlite3", "subprocess", "os", "sys", "shutil", "io", "threading",
                     "time", "random", "copy", "pickle"):
            self.assertNotIn(name, vars(wb))

    def test_61_no_clock_randomness_or_concurrency_is_used(self):
        import random
        import threading
        import time
        boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError("forbidden call"))
        with mock.patch.object(time, "time", boom), mock.patch.object(time, "sleep", boom), mock.patch.object(random, "random", boom), \
                mock.patch.object(threading, "Thread", boom):
            self.assertTrue(run_web_request_batch((make_plan(),)).ok)


class TestBoundaries(unittest.TestCase):
    def _tree(self):
        with open(MODULE, encoding="utf-8") as fh:
            return ast.parse(fh.read())

    def test_62_module_imports_only_the_pipeline_function_and_the_plan_type(self):
        imports = [(n.module, n.level, sorted(a.name for a in n.names)) for n in ast.walk(self._tree()) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(sorted(imports), sorted([("web_request_pipeline", 1, ["run_web_request_pipeline"]), ("web_request_plan", 1, ["WebRequestPlan"])]))

    def test_63_module_is_pure_and_does_not_duplicate_pipeline_dispatcher_or_executor_logic(self):
        tree = self._tree()
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run_web_request_batch")
        calls = {ast.unparse(n.func) for n in ast.walk(function) if isinstance(n, ast.Call)}
        self.assertEqual(calls, {"type", "_failure", "WebRequestBatchResult", "enumerate", "tuple", "run_web_request_pipeline"})
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("os", "sys", "io", "pathlib", "subprocess", "socket", "urllib", "http", "requests", "ssl", "sqlite3", "shutil", "random", "time",
                     "datetime", "threading", "asyncio", "concurrent", "anthropic", "openai", "multimedia", "game_creation", "core", "agent",
                     "planning", "WebRequestExecutionResult", "WebRequestValidationResult", "WebResourceRegistry", "execute_web_request_plan",
                     "create_web_request_output", "dispatch_web_request", "validate_web_request", "create_web_request_plan", "WebRequestOutput"):
            self.assertNotIn(word, names, word)
        # the batch never reads a field of a plan or of an output it received (only its own result's private slots)
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for field in ("metadata", "request_id", "url", "method", "resource_type", "timeout_ms", "status", "code", "_status", "_code", "_items",
                      "_request_id", "_url", "_method", "_resource_type", "_timeout_ms"):
            self.assertNotIn(field, attrs, field)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.ImportFrom))
        self.assertEqual([n.name for n in tree.body if isinstance(n, ast.FunctionDef)], ["_failure", "run_web_request_batch"])
        self.assertEqual([n.name for n in tree.body if isinstance(n, ast.ClassDef)], ["WebRequestBatchResult"])

    def test_64_public_function_signature_is_exactly_one_positional_parameter(self):
        function = next(n for n in self._tree().body if isinstance(n, ast.FunctionDef) and n.name == "run_web_request_batch")
        self.assertEqual([a.arg for a in function.args.args], ["plans"])
        self.assertIsNone(function.args.vararg)
        self.assertIsNone(function.args.kwarg)
        self.assertEqual(function.args.defaults, [])
        self.assertEqual(function.args.kwonlyargs, [])

    def test_65_earlier_web_modules_are_unaware_of_the_batch(self):
        for name in ("web_resource.py", "web_resource_registry.py", "web_request.py", "web_request_validator.py", "web_request_plan.py",
                     "web_request_executor.py", "web_request_output.py", "web_request_output_validator.py", "web_request_metadata_executor.py",
                     "web_request_dispatcher.py", "web_request_pipeline.py"):
            with open(os.path.join(PY_ROOT, "web", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("web_request_batch", "run_web_request_batch", "WebRequestBatchResult"):
                self.assertNotIn(token, text, (name, token))

    def test_66_no_production_module_outside_web_references_it(self):
        tokens = ("web_request_batch", "run_web_request_batch", "WebRequestBatchResult")
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

    def test_67_web_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "web")) if f != "__pycache__"),
                         ["__init__.py", "web_request.py", "web_request_batch.py", "web_request_batch_summary.py", "web_request_dispatcher.py", "web_request_executor.py",
                          "web_request_metadata_executor.py", "web_request_output.py", "web_request_output_validator.py", "web_request_pipeline.py",
                          "web_request_plan.py", "web_request_validator.py", "web_resource.py", "web_resource_registry.py"])
        with open(os.path.join(PY_ROOT, "web", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_68_project_database_is_the_pristine_baseline(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)

    def test_69_end_to_end_through_public_apis_only(self):
        plans = (make_plan(request_id="e1", url="https://svc.example/v1", method="POST", resource_type="api", timeout_ms=250),
                 make_plan(request_id="e2"))
        result = run_web_request_batch(plans)
        self.assertTrue(result.ok)
        self.assertEqual(result.outputs, (run_web_request_pipeline(plans[0]), run_web_request_pipeline(plans[1])))
        self.assertEqual(result.outputs, (dispatch_web_request(plans[0]), dispatch_web_request(plans[1])))
        for plan, out in zip(plans, result.outputs):
            self.assertEqual(out.metadata, plan.to_dict())
            self.assertEqual((out.status, out.code), ("NOT_IMPLEMENTED", NOT_IMPL))
        self.assertEqual(run_web_request_batch((None,)).outputs, ())

    def test_70_documentation_exists_and_names_the_public_api(self):
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for token in ("Prompt 784", "run_web_request_batch", "WebRequestBatchResult", INVALID_COLLECTION, INVALID_PLAN, "run_web_request_pipeline",
                      "WebRequestOutput", "tuple", "NOT_IMPLEMENTED"):
            self.assertIn(token, text, token)


if __name__ == "__main__":
    unittest.main()
