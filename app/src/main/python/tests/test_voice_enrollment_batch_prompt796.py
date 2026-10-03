"""Prompt 796 - Section 10 voice enrollment batch (`voice.voice_enrollment_batch`)."""
import ast
import copy
import gc
import hashlib
import os
import pickle
import sys
import unittest
import weakref
from unittest import mock

from voice import voice_enrollment_batch as vb
from voice import voice_enrollment_pipeline as vpl
from voice.voice_enrollment_batch import VoiceEnrollmentBatchResult, run_voice_enrollment_batch
from voice.voice_enrollment_plan import VoiceEnrollmentPlan, create_voice_enrollment_plan
from voice.voice_enrollment_request import create_voice_enrollment_request
from voice.voice_enrollment_result import VoiceEnrollmentResult

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section10_voice_enrollment_batch_prompt796.md")
MODULE = os.path.join(PY_ROOT, "voice", "voice_enrollment_batch.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
TARGET = "voice.voice_enrollment_batch.run_voice_enrollment_pipeline"
COLL = "VOICE_ENROLLMENT_BATCH_INVALID_COLLECTION"
ITEM = "VOICE_ENROLLMENT_BATCH_INVALID_ITEM"
PERR = "VOICE_ENROLLMENT_BATCH_PIPELINE_ERROR"


def make_plan(n=1, **over):
    d = {"request_id": "enroll_%d" % n, "profile_id": "voice_%d" % n, "enrollment_mode": "standard"}
    d.update(over)
    req = create_voice_enrollment_request(d)
    assert req.ok, req.failures
    res = create_voice_enrollment_plan(req)
    assert res.ok, res.codes()
    return res.plan


class Spoof(object):
    @property
    def __class__(self):
        return VoiceEnrollmentPlan


class Sub(tuple):
    pass


class TestExactTuple(unittest.TestCase):
    def check_bad(self, value):
        with mock.patch(TARGET) as p:
            res = run_voice_enrollment_batch(value)
        p.assert_not_called()
        self.assertIs(type(res), VoiceEnrollmentBatchResult)
        self.assertFalse(res.ok)
        self.assertEqual(res.outputs, ())
        self.assertEqual(res.codes(), [COLL])
        self.assertEqual(res.failures[0]["field"], "plans")

    def test_1_non_tuples_rejected(self):
        plan = make_plan()
        for v in (None, [plan], {plan}, {"a": plan}, "abc", 5, plan, iter((plan,)), (p for p in (plan,)), frozenset([plan]), b"x"):
            self.check_bad(v)

    def test_2_tuple_subclass_rejected(self):
        self.check_bad(Sub((make_plan(),)))

    def test_3_valid_tuple_accepted(self):
        res = run_voice_enrollment_batch((make_plan(),))
        self.assertTrue(res.ok)
        self.assertEqual(res.failures, ())

    def test_3b_empty_tuple_is_valid_with_zero_calls(self):
        with mock.patch(TARGET) as p:
            res = run_voice_enrollment_batch(())
        p.assert_not_called()
        self.assertTrue(res.ok)
        self.assertEqual(res.outputs, ())


class TestInvalidItems(unittest.TestCase):
    def check_item(self, bad, index=1):
        items = [make_plan(1), make_plan(2), make_plan(3)]
        items[index] = bad
        with mock.patch(TARGET) as p:
            res = run_voice_enrollment_batch(tuple(items))
        p.assert_not_called()
        self.assertFalse(res.ok)
        self.assertEqual(res.outputs, ())
        self.assertEqual(res.codes(), [ITEM])
        self.assertEqual(res.failures[0]["field"], "plans[%d]" % index)

    def test_4_invalid_items_rejected(self):
        class Look(object):
            request_id, profile_id, enrollment_mode = "a", "b", "c"
        res = create_voice_enrollment_request({"request_id": "a", "profile_id": "b", "enrollment_mode": "c"})
        for bad in (None, {}, "plan", 1, [], Look(), Spoof(), res, make_plan().to_dict(), VoiceEnrollmentPlan):
            self.check_item(bad)

    def test_5_position_is_reported(self):
        self.check_item(None, 0)
        self.check_item(None, 2)

    def test_6_all_bad_items_reported_in_order(self):
        with mock.patch(TARGET) as p:
            res = run_voice_enrollment_batch((None, make_plan(), Spoof(), 3))
        p.assert_not_called()
        self.assertEqual(res.codes(), [ITEM] * 3)
        self.assertEqual([f["field"] for f in res.failures], ["plans[0]", "plans[2]", "plans[3]"])

    def test_7_item_is_never_read(self):
        class Boom(object):
            def __getattribute__(self, name):
                if name == "__class__":
                    return object.__getattribute__(self, name)
                raise AssertionError("read " + name)
        with mock.patch(TARGET) as p:
            res = run_voice_enrollment_batch((Boom(),))
        p.assert_not_called()
        self.assertEqual(res.codes(), [ITEM])

    def test_8_nested_tuple_item_rejected(self):
        self.check_item((make_plan(),))


class TestAtomicAndCalls(unittest.TestCase):
    def test_9_valid_prefix_then_invalid_calls_nothing(self):
        with mock.patch(TARGET) as p:
            res = run_voice_enrollment_batch((make_plan(1), make_plan(2), None))
        self.assertEqual(p.call_count, 0)
        self.assertEqual(res.outputs, ())

    def test_10_exactly_once_in_order(self):
        plans = (make_plan(1), make_plan(2), make_plan(3))
        with mock.patch(TARGET, side_effect=lambda p: ("out", p.request_id)) as m:
            res = run_voice_enrollment_batch(plans)
        self.assertEqual(m.call_count, 3)
        for call, plan in zip(m.call_args_list, plans):
            self.assertEqual(len(call.args), 1)
            self.assertIs(call.args[0], plan)
            self.assertEqual(call.kwargs, {})
        self.assertEqual(res.outputs, (("out", "enroll_1"), ("out", "enroll_2"), ("out", "enroll_3")))

    def test_11_same_plan_twice_is_called_twice(self):
        plan = make_plan()
        with mock.patch(TARGET) as m:
            run_voice_enrollment_batch((plan, plan))
        self.assertEqual(m.call_count, 2)

    def test_12_validation_completes_before_first_call(self):
        events = []
        real = vb.run_voice_enrollment_pipeline
        with mock.patch(TARGET, side_effect=lambda p: events.append("call") or real(p)):
            run_voice_enrollment_batch((make_plan(1), make_plan(2)))
        self.assertEqual(events, ["call", "call"])

    def test_13_pipeline_exception_gives_stable_failure(self):
        plans = (make_plan(1), make_plan(2), make_plan(3))
        def boom(p):
            if p is plans[1]:
                raise RuntimeError("x")
            return "ok"
        with mock.patch(TARGET, side_effect=boom) as m:
            res = run_voice_enrollment_batch(plans)
        self.assertEqual(m.call_count, 2)
        self.assertFalse(res.ok)
        self.assertEqual(res.outputs, ())
        self.assertEqual(res.codes(), [PERR])
        self.assertEqual(res.failures[0]["field"], "plans[1]")


class TestOutputs(unittest.TestCase):
    def test_14_identity_and_order_with_real_pipeline(self):
        plans = (make_plan(1), make_plan(2), make_plan(3))
        sentinels = [object(), object(), object()]
        with mock.patch(TARGET, side_effect=list(sentinels)):
            res = run_voice_enrollment_batch(plans)
        self.assertEqual(len(res.outputs), 3)
        for a, b in zip(res.outputs, sentinels):
            self.assertIs(a, b)

    def test_15_real_pipeline_results(self):
        plans = (make_plan(1), make_plan(2))
        res = run_voice_enrollment_batch(plans)
        self.assertTrue(res.ok)
        self.assertEqual(len(res.outputs), 2)
        for out, plan in zip(res.outputs, plans):
            self.assertIs(type(out), VoiceEnrollmentResult)
            self.assertEqual(out.request_id, plan.request_id)

    def test_16_outputs_is_a_tuple(self):
        res = run_voice_enrollment_batch((make_plan(),))
        self.assertIs(type(res.outputs), tuple)
        self.assertIs(type(res.failures), tuple)

    def test_17_ok_matches_failures(self):
        self.assertTrue(run_voice_enrollment_batch(()).ok)
        self.assertFalse(run_voice_enrollment_batch([]).ok)


class TestImmutabilityAndRetention(unittest.TestCase):
    def setUp(self):
        self.res = run_voice_enrollment_batch((make_plan(),))
        self.bad = run_voice_enrollment_batch((None,))

    def test_18_attributes_immutable(self):
        for name in ("ok", "outputs", "failures", "_outputs", "extra"):
            with self.assertRaises(AttributeError):
                setattr(self.res, name, 1)
            with self.assertRaises(AttributeError):
                delattr(self.res, name)

    def test_19_no_dict_and_no_direct_construction_or_subclass(self):
        self.assertFalse(hasattr(self.res, "__dict__"))
        with self.assertRaises(TypeError):
            VoiceEnrollmentBatchResult((), ())
        with self.assertRaises(TypeError):
            VoiceEnrollmentBatchResult(object(), (), ())
        with self.assertRaises(TypeError):
            class S(VoiceEnrollmentBatchResult):
                pass

    def test_20_failures_are_fresh_dicts(self):
        f = self.bad.failures
        f[0]["code"] = "changed"
        self.assertEqual(self.bad.failures[0]["code"], ITEM)
        self.assertIsNot(self.bad.failures[0], self.bad.failures[0])

    def test_21_copy_deepcopy_return_self_and_pickle_refused(self):
        self.assertIs(copy.copy(self.res), self.res)
        self.assertIs(copy.deepcopy(self.res), self.res)
        with self.assertRaises(TypeError):
            pickle.dumps(self.res)

    def test_22_value_equality_and_hash(self):
        a = run_voice_enrollment_batch(())
        b = run_voice_enrollment_batch(())
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertNotEqual(a, run_voice_enrollment_batch([]))
        self.assertNotEqual(a, ())

    def test_23_plans_and_input_tuple_not_retained(self):
        plan = make_plan(7)
        before = sys.getrefcount(plan)
        tup = (plan,)
        with mock.patch(TARGET, return_value="x"):
            res = run_voice_enrollment_batch(tup)
        del tup
        gc.collect()
        self.assertEqual(sys.getrefcount(plan), before)
        self.assertFalse([r for r in gc.get_referrers(plan) if r is res or r is res.outputs])
        self.assertEqual(res.outputs, ("x",))

    def test_24_invalid_input_not_retained(self):
        class Holder(object):
            pass
        h = Holder()
        w = weakref.ref(h)
        res = run_voice_enrollment_batch((h,))
        del h
        gc.collect()
        self.assertIsNone(w())
        self.assertFalse(res.ok)

    def test_25_input_tuple_unchanged(self):
        plans = (make_plan(1), make_plan(2))
        snap = tuple(plans)
        run_voice_enrollment_batch(plans)
        self.assertEqual(len(plans), 2)
        for a, b in zip(plans, snap):
            self.assertIs(a, b)


class TestDeterminism(unittest.TestCase):
    def test_26_repeat_runs_are_equal(self):
        plans = (make_plan(1), make_plan(2))
        self.assertEqual(run_voice_enrollment_batch(plans), run_voice_enrollment_batch(plans))
        self.assertEqual(run_voice_enrollment_batch((None,)), run_voice_enrollment_batch((None,)))

    def test_27_results_are_fresh_objects(self):
        plans = (make_plan(),)
        self.assertIsNot(run_voice_enrollment_batch(plans), run_voice_enrollment_batch(plans))

    def test_28_different_inputs_differ(self):
        self.assertNotEqual(run_voice_enrollment_batch((make_plan(1),)), run_voice_enrollment_batch((make_plan(2),)))

    def test_29_no_io_during_run(self):
        with mock.patch("builtins.open", side_effect=AssertionError("io")), mock.patch("os.listdir", side_effect=AssertionError("io")):
            self.assertTrue(run_voice_enrollment_batch((make_plan(),)).ok)


class TestPurityAndDoc(unittest.TestCase):
    def setUp(self):
        with open(MODULE, encoding="utf-8") as fh:
            self.src = fh.read()
        self.tree = ast.parse(self.src)

    def test_30_only_pipeline_and_plan_imports(self):
        mods = sorted(n.module for n in ast.walk(self.tree) if isinstance(n, ast.ImportFrom))
        self.assertEqual(mods, ["voice_enrollment_pipeline", "voice_enrollment_plan"])
        self.assertFalse([n for n in ast.walk(self.tree) if isinstance(n, ast.Import)])

    def test_31_pipeline_called_from_one_site_and_no_lower_layers(self):
        calls = [n for n in ast.walk(self.tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "run_voice_enrollment_pipeline"]
        self.assertEqual(len(calls), 1)
        names = {n.id for n in ast.walk(self.tree) if isinstance(n, ast.Name)}
        for forbidden in ("dispatch_voice_enrollment", "execute_voice_enrollment_plan", "create_voice_enrollment_result"):
            self.assertNotIn(forbidden, names)

    def test_32_no_forbidden_names(self):
        names = {n.id for n in ast.walk(self.tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(self.tree) if isinstance(n, ast.Attribute)}
        for bad in ("open", "os", "sys", "socket", "subprocess", "sqlite3", "random", "time", "datetime", "requests", "urllib", "print", "eval", "exec"):
            self.assertNotIn(bad, names)

    def test_33_no_module_level_mutable_state(self):
        for node in self.tree.body:
            if isinstance(node, ast.Assign):
                self.assertNotIsInstance(node.value, (ast.List, ast.Dict, ast.Set))

    def test_34_public_surface_and_codes(self):
        self.assertEqual(vb.FAILURE_CODES, (COLL, ITEM, PERR))
        for c in vb.FAILURE_CODES:
            self.assertTrue(c.startswith("VOICE_ENROLLMENT_BATCH_"))

    def test_35_not_wired_and_pipeline_unchanged(self):
        for sub in ("core", "agent", "planning", "interface"):
            base = os.path.join(PY_ROOT, sub)
            for root, _d, files in os.walk(base):
                for f in files:
                    if f.endswith(".py"):
                        with open(os.path.join(root, f), encoding="utf-8") as fh:
                            self.assertNotIn("voice_enrollment_batch", fh.read())
        for f in os.listdir(os.path.join(PY_ROOT, "voice")):
            if f.endswith(".py") and f not in ("voice_enrollment_batch.py", "voice_enrollment_batch_summary.py"):      # Prompt 797: the summary reads the batch result type
                with open(os.path.join(PY_ROOT, "voice", f), encoding="utf-8") as fh:
                    self.assertNotIn("voice_enrollment_batch", fh.read())

    def test_36_doc_exists_and_names_the_api(self):
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("run_voice_enrollment_batch", text)
        self.assertIn("Prompt 797 has NOT been started", text)

    def test_37_database_is_pristine(self):
        with open(PROJECT_DB, "rb") as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
