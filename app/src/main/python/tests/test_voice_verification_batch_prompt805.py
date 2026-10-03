"""Prompt 805 - Section 10 voice verification batch (`voice.voice_verification_batch`)."""
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

from voice import voice_verification_batch as vb
from voice import voice_verification_pipeline as vpl
from voice.voice_enrollment_plan import create_voice_enrollment_plan
from voice.voice_enrollment_request import create_voice_enrollment_request
from voice.voice_verification_batch import VoiceVerificationBatchResult, run_voice_verification_batch
from voice.voice_verification_plan import VoiceVerificationPlan, create_voice_verification_plan
from voice.voice_verification_request import create_voice_verification_request
from voice.voice_verification_request_validator import validate_voice_verification_request
from voice.voice_verification_result import VoiceVerificationResult

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section10_voice_verification_batch_prompt805.md")
MODULE = os.path.join(PY_ROOT, "voice", "voice_verification_batch.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
UNCHANGED_SHA256 = {      # existing contracts that Prompt 805 must not touch
    "voice_enrollment_batch.py": "a015f525aa0a4454c10d1295e46c308f84fcdaff13cd6ebad9d38d302bcd7ae1",
    "voice_verification_dispatcher.py": "1188c2c4164b2348bbe3c90181e6fbf4c01c221169d37bc72eff83b54e89d6f7",
    "voice_verification_executor.py": "cdf5393aab4e94191be68cc0ad353e0ff4a930342b96cd6219ab0c68d0e1576e",
    "voice_verification_pipeline.py": "55bdb830f4add444c713466659c398cd1c0866a15c4ee3d062a37287075c3870",
    "voice_verification_plan.py": "72b3373bba221249483e09c2823c4892dfadeed9fca15ccd82de111c7f9ddd28",
    "voice_verification_result.py": "51c1161398590b55b75a4552709a286c68229335f56fd55a8b73c986db78242a",
    "voice_verification_request_validator.py": "518ebd72524b743c32d5974b975529ada07ec93dc8a6a593be1cafa763cb33d5",
}
TARGET = "voice.voice_verification_batch.run_voice_verification_pipeline"
COLL = "VOICE_VERIFICATION_BATCH_INVALID_COLLECTION"
ITEM = "VOICE_VERIFICATION_BATCH_INVALID_ITEM"
PERR = "VOICE_VERIFICATION_BATCH_PIPELINE_ERROR"


def make_plan(n=1, **over):
    d = {"request_id": "verify_%d" % n, "profile_id": "voice_%d" % n, "verification_mode": "standard"}
    d.update(over)
    req = create_voice_verification_request(d)
    assert req.ok, req.failures
    res = create_voice_verification_plan(validate_voice_verification_request(req.request))
    assert res.ok, res.codes()
    return res.plan


class Spoof(object):
    @property
    def __class__(self):
        return VoiceVerificationPlan


class Sub(tuple):
    pass


class TestExactTuple(unittest.TestCase):
    def check_bad(self, value):
        with mock.patch(TARGET) as p:
            res = run_voice_verification_batch(value)
        p.assert_not_called()
        self.assertIs(type(res), VoiceVerificationBatchResult)
        self.assertFalse(res.ok)
        self.assertEqual(res.outputs, ())
        self.assertEqual(res.codes(), [COLL])
        self.assertEqual(res.failures[0]["field"], "plans")

    def test_1_non_tuples_rejected(self):
        plan = make_plan()
        for v in (None, [plan], [], {plan}, {"a": plan}, "abc", 5, plan, iter((plan,)), (p for p in (plan,)), frozenset([plan]), b"x", range(2)):
            with self.subTest(v=type(v).__name__):
                self.check_bad(v)

    def test_2_tuple_subclass_rejected(self):
        self.check_bad(Sub((make_plan(),)))
        self.check_bad(Sub(()))

    def test_2b_spoofed_class_collection_rejected(self):
        class SpoofTuple(object):
            @property
            def __class__(self):
                return tuple
            def __iter__(self):
                raise AssertionError("iterated")
        self.check_bad(SpoofTuple())

    def test_3_valid_tuple_accepted(self):
        res = run_voice_verification_batch((make_plan(),))
        self.assertTrue(res.ok)
        self.assertEqual(res.failures, ())

    def test_3b_empty_tuple_is_valid_with_zero_calls(self):
        with mock.patch(TARGET) as p:
            res = run_voice_verification_batch(())
        p.assert_not_called()
        self.assertTrue(res.ok)
        self.assertEqual(res.outputs, ())
        self.assertEqual(res.failures, ())


class TestInvalidItems(unittest.TestCase):
    def check_item(self, bad, index=1):
        items = [make_plan(1), make_plan(2), make_plan(3)]
        items[index] = bad
        with mock.patch(TARGET) as p:
            res = run_voice_verification_batch(tuple(items))
        p.assert_not_called()
        self.assertFalse(res.ok)
        self.assertEqual(res.outputs, ())
        self.assertEqual(res.codes(), [ITEM])
        self.assertEqual(res.failures[0]["field"], "plans[%d]" % index)

    def test_4_invalid_items_rejected(self):
        class Look(object):
            request_id, profile_id, verification_mode = "a", "b", "c"
        class PlanSub(object):
            pass
        enroll_req = create_voice_enrollment_request({"request_id": "a", "profile_id": "b", "enrollment_mode": "c"})
        enroll_plan = create_voice_enrollment_plan(enroll_req).plan
        vreq = create_voice_verification_request({"request_id": "a", "profile_id": "b", "verification_mode": "c"})
        for bad in (None, {}, "plan", 1, True, [], Look(), Spoof(), vreq, make_plan().to_dict(), VoiceVerificationPlan, enroll_plan, PlanSub(), object()):
            with self.subTest(bad=type(bad).__name__):
                self.check_item(bad)

    def test_5_position_is_reported(self):
        self.check_item(None, 0)
        self.check_item(None, 2)

    def test_6_all_bad_items_reported_in_order(self):
        with mock.patch(TARGET) as p:
            res = run_voice_verification_batch((None, make_plan(), Spoof(), 3))
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
            res = run_voice_verification_batch((Boom(),))
        p.assert_not_called()
        self.assertEqual(res.codes(), [ITEM])

    def test_8_nested_tuple_item_rejected(self):
        self.check_item((make_plan(),))

    def test_8b_plan_subclass_cannot_exist_or_is_rejected(self):
        try:
            class Derived(VoiceVerificationPlan):
                pass
            inst = object.__new__(Derived)
        except TypeError:
            return          # plan type refuses subclassing: nothing to feed in
        self.check_item(inst)


class TestAtomicAndCalls(unittest.TestCase):
    def test_9_valid_prefix_then_invalid_calls_nothing(self):
        with mock.patch(TARGET) as p:
            res = run_voice_verification_batch((make_plan(1), make_plan(2), None))
        self.assertEqual(p.call_count, 0)
        self.assertEqual(res.outputs, ())

    def test_9b_invalid_collection_with_valid_plans_calls_nothing(self):
        with mock.patch(TARGET) as p:
            run_voice_verification_batch([make_plan(1), make_plan(2)])
            run_voice_verification_batch(Sub((make_plan(1),)))
        self.assertEqual(p.call_count, 0)

    def test_10_exactly_once_in_order(self):
        plans = (make_plan(1), make_plan(2), make_plan(3))
        with mock.patch(TARGET, side_effect=lambda p: ("out", p.request_id)) as m:
            res = run_voice_verification_batch(plans)
        self.assertEqual(m.call_count, 3)
        for call, plan in zip(m.call_args_list, plans):
            self.assertEqual(len(call.args), 1)
            self.assertIs(call.args[0], plan)
            self.assertEqual(call.kwargs, {})
        self.assertEqual(res.outputs, (("out", "verify_1"), ("out", "verify_2"), ("out", "verify_3")))

    def test_11_same_plan_twice_is_called_twice(self):
        plan = make_plan()
        with mock.patch(TARGET) as m:
            run_voice_verification_batch((plan, plan))
        self.assertEqual(m.call_count, 2)

    def test_12_calls_go_through_the_public_pipeline(self):
        events = []
        real = vb.run_voice_verification_pipeline
        with mock.patch(TARGET, side_effect=lambda p: events.append("call") or real(p)):
            run_voice_verification_batch((make_plan(1), make_plan(2)))
        self.assertEqual(events, ["call", "call"])

    def test_13_pipeline_exception_stops_and_is_recorded(self):
        plans = (make_plan(1), make_plan(2), make_plan(3))
        def boom(p):
            if p is plans[1]:
                raise RuntimeError("x")
            return "ok"
        with mock.patch(TARGET, side_effect=boom) as m:
            res = run_voice_verification_batch(plans)
        self.assertEqual(m.call_count, 2)                       # plan 3 never processed
        self.assertIs(m.call_args_list[1].args[0], plans[1])
        self.assertFalse(res.ok)
        self.assertEqual(res.outputs, ())
        self.assertEqual(res.codes(), [PERR])
        self.assertEqual(res.failures[0]["field"], "plans[1]")

    def test_13b_first_plan_exception_and_no_exception_leak(self):
        with mock.patch(TARGET, side_effect=ValueError("secret")) as m:
            res = run_voice_verification_batch((make_plan(1), make_plan(2)))
        self.assertEqual(m.call_count, 1)
        self.assertEqual(res.failures[0]["field"], "plans[0]")
        self.assertNotIn("secret", repr(res.failures))

    def test_13c_completed_calls_are_not_undone(self):
        plans = (make_plan(1), make_plan(2))
        done = []
        def side(p):
            if p is plans[1]:
                raise RuntimeError("x")
            done.append(p)
            return "ok"
        with mock.patch(TARGET, side_effect=side) as m:
            run_voice_verification_batch(plans)
        self.assertEqual(done, [plans[0]])
        self.assertEqual(m.call_count, 2)       # no retry, no rollback call

    def test_13d_base_exceptions_are_not_swallowed(self):
        with mock.patch(TARGET, side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                run_voice_verification_batch((make_plan(),))


class TestOutputs(unittest.TestCase):
    def test_14_identity_and_order(self):
        plans = (make_plan(1), make_plan(2), make_plan(3))
        sentinels = [object(), object(), object()]
        with mock.patch(TARGET, side_effect=list(sentinels)):
            res = run_voice_verification_batch(plans)
        self.assertEqual(len(res.outputs), 3)
        for a, b in zip(res.outputs, sentinels):
            self.assertIs(a, b)

    def test_14b_same_pipeline_object_kept_twice(self):
        shared = object()
        with mock.patch(TARGET, return_value=shared):
            res = run_voice_verification_batch((make_plan(1), make_plan(2)))
        self.assertIs(res.outputs[0], shared)
        self.assertIs(res.outputs[1], shared)

    def test_15_real_pipeline_results(self):
        plans = (make_plan(1), make_plan(2))
        res = run_voice_verification_batch(plans)
        self.assertTrue(res.ok)
        self.assertEqual(len(res.outputs), 2)
        for out, plan in zip(res.outputs, plans):
            self.assertIs(type(out), VoiceVerificationResult)
            self.assertEqual(out.request_id, plan.request_id)
            self.assertEqual(out.profile_id, plan.profile_id)

    def test_15b_real_outputs_match_direct_pipeline_calls(self):
        plans = (make_plan(1), make_plan(2))
        res = run_voice_verification_batch(plans)
        for out, plan in zip(res.outputs, plans):
            direct = vpl.run_voice_verification_pipeline(plan)
            self.assertEqual((out.request_id, out.profile_id, out.status, out.code), (direct.request_id, direct.profile_id, direct.status, direct.code))

    def test_16_container_types(self):
        res = run_voice_verification_batch((make_plan(),))
        self.assertIs(type(res.outputs), tuple)
        self.assertIs(type(res.failures), tuple)
        self.assertIs(type(run_voice_verification_batch(None).failures), tuple)

    def test_17_ok_matches_failures(self):
        self.assertTrue(run_voice_verification_batch(()).ok)
        self.assertFalse(run_voice_verification_batch([]).ok)
        self.assertFalse(run_voice_verification_batch((None,)).ok)


class TestImmutabilityAndRetention(unittest.TestCase):
    def setUp(self):
        self.res = run_voice_verification_batch((make_plan(),))
        self.bad = run_voice_verification_batch((None,))

    def test_18_attributes_immutable(self):
        for name in ("ok", "outputs", "failures", "_outputs", "_failures", "extra"):
            with self.assertRaises(AttributeError):
                setattr(self.res, name, 1)
            with self.assertRaises(AttributeError):
                delattr(self.res, name)

    def test_19_no_dict_and_no_direct_construction_or_subclass(self):
        self.assertFalse(hasattr(self.res, "__dict__"))
        with self.assertRaises(TypeError):
            VoiceVerificationBatchResult((), ())
        with self.assertRaises(TypeError):
            VoiceVerificationBatchResult(object(), (), ())
        with self.assertRaises(TypeError):
            class S(VoiceVerificationBatchResult):
                pass

    def test_20_failures_are_fresh_dicts(self):
        f = self.bad.failures
        f[0]["code"] = "changed"
        self.assertEqual(self.bad.failures[0]["code"], ITEM)
        self.assertIsNot(self.bad.failures[0], self.bad.failures[0])
        self.assertEqual(sorted(self.bad.failures[0]), ["code", "field", "message"])

    def test_21_copy_deepcopy_return_self_and_pickle_refused(self):
        self.assertIs(copy.copy(self.res), self.res)
        self.assertIs(copy.deepcopy(self.res), self.res)
        with self.assertRaises(TypeError):
            pickle.dumps(self.res)

    def test_22_value_equality_and_hash(self):
        a = run_voice_verification_batch(())
        b = run_voice_verification_batch(())
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertNotEqual(a, run_voice_verification_batch([]))
        self.assertNotEqual(a, ())

    def test_22b_not_equal_to_other_batch_type(self):
        from voice.voice_enrollment_batch import run_voice_enrollment_batch
        self.assertNotEqual(run_voice_verification_batch(()), run_voice_enrollment_batch(()))

    def test_23_plans_and_input_tuple_not_retained(self):
        plan = make_plan(7)
        before = sys.getrefcount(plan)
        tup = (plan,)
        with mock.patch(TARGET, return_value="x"):
            res = run_voice_verification_batch(tup)
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
        res = run_voice_verification_batch((h,))
        del h
        gc.collect()
        self.assertIsNone(w())
        self.assertFalse(res.ok)

    def test_24b_invalid_collection_not_retained(self):
        class Holder(list):
            pass
        h = Holder([make_plan()])
        w = weakref.ref(h)
        res = run_voice_verification_batch(h)
        del h
        gc.collect()
        self.assertIsNone(w())
        self.assertEqual(res.codes(), [COLL])

    def test_24c_raised_exception_not_retained(self):
        class Err(Exception):
            pass
        err = Err("x")
        w = weakref.ref(err)
        with mock.patch(TARGET, side_effect=err):
            res = run_voice_verification_batch((make_plan(),))
        del err
        gc.collect()
        self.assertIsNone(w())
        self.assertEqual(res.codes(), [PERR])

    def test_25_input_tuple_unchanged(self):
        plans = (make_plan(1), make_plan(2))
        snap = tuple(plans)
        before = [(p.to_dict(), repr(p), hash(p)) for p in plans]
        run_voice_verification_batch(plans)
        self.assertEqual(len(plans), 2)
        for a, b in zip(plans, snap):
            self.assertIs(a, b)
        self.assertEqual([(p.to_dict(), repr(p), hash(p)) for p in plans], before)

    def test_25b_mutating_a_source_list_later_does_not_affect_result(self):
        source = [make_plan(1), make_plan(2)]
        res = run_voice_verification_batch(tuple(source))
        outputs = res.outputs
        source.clear()
        self.assertEqual(res.outputs, outputs)
        self.assertEqual(len(res.outputs), 2)


class TestDeterminism(unittest.TestCase):
    def test_26_repeat_runs_are_equal(self):
        plans = (make_plan(1), make_plan(2))
        with mock.patch(TARGET, side_effect=lambda p: p.request_id):
            a = run_voice_verification_batch(plans)
            b = run_voice_verification_batch(plans)
        self.assertEqual(a, b)
        self.assertEqual(run_voice_verification_batch((None,)), run_voice_verification_batch((None,)))

    def test_27_results_are_fresh_objects(self):
        plans = (make_plan(),)
        self.assertIsNot(run_voice_verification_batch(plans), run_voice_verification_batch(plans))

    def test_28_different_inputs_differ(self):
        with mock.patch(TARGET, side_effect=lambda p: p.request_id):
            self.assertNotEqual(run_voice_verification_batch((make_plan(1),)), run_voice_verification_batch((make_plan(2),)))

    def test_29_no_io_during_run(self):
        plans = (make_plan(),)
        with mock.patch("builtins.open", side_effect=AssertionError("io")), mock.patch("os.listdir", side_effect=AssertionError("io")):
            self.assertTrue(run_voice_verification_batch(plans).ok)


class TestPurityAndDoc(unittest.TestCase):
    def setUp(self):
        with open(MODULE, encoding="utf-8") as fh:
            self.src = fh.read()
        self.tree = ast.parse(self.src)

    def test_30_only_pipeline_and_plan_imports(self):
        mods = sorted(n.module for n in ast.walk(self.tree) if isinstance(n, ast.ImportFrom))
        self.assertEqual(mods, ["voice_verification_pipeline", "voice_verification_plan"])
        self.assertFalse([n for n in ast.walk(self.tree) if isinstance(n, ast.Import)])

    def test_31_pipeline_called_from_one_site_and_no_lower_layers(self):
        calls = [n for n in ast.walk(self.tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "run_voice_verification_pipeline"]
        self.assertEqual(len(calls), 1)
        names = {n.id for n in ast.walk(self.tree) if isinstance(n, ast.Name)}
        for forbidden in ("dispatch_voice_verification", "execute_voice_verification_plan", "create_voice_verification_result", "run_voice_enrollment_pipeline"):
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
            self.assertTrue(c.startswith("VOICE_VERIFICATION_BATCH_"))
        self.assertNotIn("ENROLLMENT", self.src.split('"""', 2)[2])

    def test_35_not_wired_into_runtime(self):
        for sub in ("core", "agent", "planning", "interface", "android_entry.py"):
            base = os.path.join(PY_ROOT, sub)
            files = [base] if base.endswith(".py") else [os.path.join(d, f) for d, _s, fs in os.walk(base) for f in fs if f.endswith(".py")]
            for fp in files:
                with open(fp, encoding="utf-8") as fh:
                    text = fh.read()
                for token in ("voice_verification_batch", "run_voice_verification_batch"):
                    self.assertNotIn(token, text, fp)
        for f in os.listdir(os.path.join(PY_ROOT, "voice")):
            if f.endswith(".py") and f not in ("voice_verification_batch.py", "voice_verification_batch_summary.py"):      # Prompt 806: the summary reads the batch result type
                with open(os.path.join(PY_ROOT, "voice", f), encoding="utf-8") as fh:
                    text = fh.read()
                for token in ("voice_verification_batch", "run_voice_verification_batch"):
                    self.assertNotIn(token, text, f)

    def test_35b_existing_contracts_are_unchanged(self):
        for f, digest in UNCHANGED_SHA256.items():
            with open(os.path.join(PY_ROOT, "voice", f), "rb") as fh:
                self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), digest, f)

    def test_36_doc_exists_and_names_the_api(self):
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("run_voice_verification_batch", text)
        self.assertIn("Prompt 806 has NOT been started", text)

    def test_37_database_is_pristine(self):
        with open(PROJECT_DB, "rb") as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
