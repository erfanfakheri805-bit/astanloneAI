"""Prompt 794 - Section 10 voice enrollment dispatcher (`voice.voice_enrollment_dispatcher`)."""
import ast
import gc
import hashlib
import os
import sys
import unittest
import weakref
from unittest import mock

from voice import voice_enrollment_dispatcher as vd
from voice import voice_enrollment_executor as ve
from voice import voice_enrollment_plan as vp
from voice.voice_enrollment_dispatcher import dispatch_voice_enrollment
from voice.voice_enrollment_plan import VoiceEnrollmentPlan, create_voice_enrollment_plan
from voice.voice_enrollment_request import create_voice_enrollment_request
from voice.voice_enrollment_result import VoiceEnrollmentResult
from voice.voice_enrollment_result_validator import validate_voice_enrollment_result

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section10_voice_enrollment_dispatcher_prompt794.md")
MODULE = os.path.join(PY_ROOT, "voice", "voice_enrollment_dispatcher.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
INVALID = "VOICE_ENROLLMENT_DISPATCHER_INVALID_PLAN"
TARGET = "voice.voice_enrollment_dispatcher.execute_voice_enrollment_plan"


class Plan2(object):
    pass


def make_plan(**over):
    d = {"request_id": "enroll_1", "profile_id": "voice_1", "enrollment_mode": "standard"}
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


class TestExactTypeRejection(unittest.TestCase):
    def check_rejected(self, value):
        with mock.patch(TARGET) as ex:
            res = dispatch_voice_enrollment(value)
        ex.assert_not_called()
        self.assertIs(type(res), VoiceEnrollmentResult)
        self.assertEqual((res.status, res.code, res.metadata), ("REJECTED", INVALID, None))
        self.assertEqual((res.request_id, res.profile_id), (ve.UNKNOWN_ID, ve.UNKNOWN_ID))

    def test_1_non_plans_are_rejected(self):
        plan = make_plan()
        for bad in (None, {}, plan.to_dict(), "plan", 1, True, [plan], (plan,), object(), Plan2(), VoiceEnrollmentPlan, Spoof(), b"", 1.5):
            with self.subTest(bad=type(bad).__name__):
                self.check_rejected(bad)

    def test_2_lookalike_with_plan_attributes_is_rejected(self):
        class Look(object):
            request_id, profile_id, enrollment_mode = "a", "b", "c"
        self.check_rejected(Look())

    def test_3_other_voice_types_are_rejected(self):
        req = create_voice_enrollment_request({"request_id": "r", "profile_id": "p", "enrollment_mode": "m"})
        self.check_rejected(req)
        self.check_rejected(req.request)
        self.check_rejected(create_voice_enrollment_plan(req))

    def test_4_rejected_result_is_valid_and_has_exact_dict(self):
        res = dispatch_voice_enrollment(None)
        self.assertEqual(res.to_dict(), {"request_id": "UNKNOWN", "profile_id": "UNKNOWN", "status": "REJECTED", "code": INVALID, "metadata": None})
        self.assertTrue(validate_voice_enrollment_result(res).ok)

    def test_5_rejection_is_equal_but_a_fresh_object_each_time(self):
        a, b = dispatch_voice_enrollment(None), dispatch_voice_enrollment(1)
        self.assertEqual(a, b)

    def test_6_rejection_reads_nothing_from_input(self):
        class Boom(object):
            def __getattribute__(self, name):
                raise AssertionError("read " + name)
        self.check_rejected(Boom())


class TestDelegation(unittest.TestCase):
    def test_7_valid_plan_calls_executor_exactly_once_with_same_plan(self):
        plan = make_plan()
        sentinel = object()
        with mock.patch(TARGET, return_value=sentinel) as ex:
            dispatch_voice_enrollment(plan)
        self.assertEqual(ex.call_count, 1)
        args, kwargs = ex.call_args
        self.assertEqual(len(args), 1)
        self.assertIs(args[0], plan)
        self.assertEqual(kwargs, {})

    def test_8_returned_object_identity_is_preserved(self):
        plan = make_plan()
        for sentinel in (object(), None, "x", 5, VoiceEnrollmentResult.__name__):
            with mock.patch(TARGET, return_value=sentinel):
                self.assertIs(dispatch_voice_enrollment(plan), sentinel)

    def test_9_real_executor_result_is_returned_as_is(self):
        plan = make_plan()
        produced = []
        real = ve.execute_voice_enrollment_plan

        def spy(p):
            r = real(p)
            produced.append(r)
            return r
        with mock.patch(TARGET, side_effect=spy):
            res = dispatch_voice_enrollment(plan)
        self.assertEqual(len(produced), 1)
        self.assertIs(res, produced[0])
        self.assertEqual((res.status, res.code), ("NOT_IMPLEMENTED", "VOICE_ENROLLMENT_EXECUTOR_NOT_IMPLEMENTED"))
        self.assertEqual(res, real(plan))

    def test_10_executor_rejection_is_returned_unchanged(self):
        plan = VoiceEnrollmentPlan(vp._CREATE_TOKEN, "r", "p", "")      # malformed, only possible privately
        res = dispatch_voice_enrollment(plan)
        self.assertEqual(res.code, "VOICE_ENROLLMENT_EXECUTOR_INVALID_PLAN")
        self.assertEqual(res, ve.execute_voice_enrollment_plan(plan))

    def test_11_executor_exception_propagates_not_swallowed(self):
        with mock.patch(TARGET, side_effect=RuntimeError("boom")) as ex:
            with self.assertRaises(RuntimeError):
                dispatch_voice_enrollment(make_plan())
        self.assertEqual(ex.call_count, 1)

    def test_12_each_dispatch_calls_executor_once(self):
        plan = make_plan()
        with mock.patch(TARGET, return_value=1) as ex:
            for n in range(1, 4):
                dispatch_voice_enrollment(plan)
                self.assertEqual(ex.call_count, n)


class TestNoDuplicationAndPurity(unittest.TestCase):
    def setUp(self):
        with open(MODULE, encoding="utf-8") as f:
            self.src = f.read()
        self.tree = ast.parse(self.src)

    def test_13_module_has_no_executor_logic(self):
        for name in ("NOT_IMPLEMENTED", "enrollment_mode", "request_id=", ".metadata", "plan.request_id", "plan.profile_id"):
            body = self.src.split('"""', 2)[2]
            self.assertNotIn(name, body.replace('"request_id": UNKNOWN_ID', ""))

    def test_14_imports_are_only_the_voice_siblings(self):
        mods = [n.module for n in ast.walk(self.tree) if isinstance(n, ast.ImportFrom)]
        self.assertEqual(sorted(mods), ["voice_enrollment_executor", "voice_enrollment_plan", "voice_enrollment_result"])
        self.assertFalse([n for n in ast.walk(self.tree) if isinstance(n, ast.Import)])

    def test_15_no_forbidden_calls_or_names(self):
        names = {n.id for n in ast.walk(self.tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(self.tree) if isinstance(n, ast.Attribute)}
        for bad in ("open", "socket", "subprocess", "requests", "urllib", "os", "sys", "time", "random", "sqlite3", "print", "input", "eval", "exec"):
            self.assertNotIn(bad, names)

    def test_16_no_module_level_mutable_state(self):
        for node in self.tree.body:
            if isinstance(node, ast.Assign):
                self.assertNotIsInstance(node.value, (ast.List, ast.Dict, ast.Set))

    def test_17_public_surface(self):
        public = sorted(n for n in dir(vd) if not n.startswith("_"))
        for n in ("dispatch_voice_enrollment", "CODE_INVALID_PLAN", "STATUS_REJECTED", "CODES"):
            self.assertIn(n, public)
        self.assertEqual(vd.CODE_INVALID_PLAN, INVALID)
        self.assertEqual(vd.STATUS_REJECTED, "REJECTED")

    def test_18_no_wiring_into_core_or_agent_loop(self):
        for root in ("core", "agent", "planning", "android_entry.py"):
            path = os.path.join(PY_ROOT, root)
            files = [path] if path.endswith(".py") else [os.path.join(d, f) for d, _s, fs in os.walk(path) for f in fs if f.endswith(".py")]
            for fp in files:
                with open(fp, encoding="utf-8") as f:
                    self.assertNotIn("voice_enrollment_dispatcher", f.read(), fp)

    def test_19_existing_voice_modules_do_not_mention_dispatcher(self):
        vdir = os.path.join(PY_ROOT, "voice")
        for f in os.listdir(vdir):
            if f.endswith(".py") and f not in ("voice_enrollment_dispatcher.py", "voice_enrollment_pipeline.py", "voice_enrollment_batch.py", "voice_enrollment_batch_summary.py", "voice_verification_pipeline.py", "voice_verification_batch.py", "voice_verification_batch_summary.py"):      # Prompt 795: the pipeline sits in front of the dispatcher; Prompt 796: the batch sits in front of the pipeline; Prompt 804: the verification pipeline sits in front of the verification dispatcher; Prompt 805: the verification batch sits in front of the verification pipeline; Prompt 806: the verification batch summary reads the batch result type
                with open(os.path.join(vdir, f), encoding="utf-8") as fh:
                    self.assertNotIn("dispatcher", fh.read(), f)


class TestMutationAndDeterminism(unittest.TestCase):
    def test_20_plan_is_unchanged_by_dispatch(self):
        plan = make_plan()
        before = (plan.to_dict(), repr(plan), hash(plan))
        dispatch_voice_enrollment(plan)
        self.assertEqual((plan.to_dict(), repr(plan), hash(plan)), before)

    def test_21_plan_is_not_retained(self):
        plan = make_plan(request_id="retain-test")
        gc.collect()
        before = sys.getrefcount(plan)
        res = dispatch_voice_enrollment(plan)
        gc.collect()
        self.assertEqual(sys.getrefcount(plan), before)
        self.assertEqual([o for o in gc.get_referrers(plan) if o is res], [])
        self.assertEqual(res.request_id, "retain-test")

    def test_22_invalid_input_is_not_retained(self):
        class Holder(object):
            pass
        h = Holder()
        ref = weakref.ref(h)
        dispatch_voice_enrollment(h)
        del h
        gc.collect()
        self.assertIsNone(ref())

    def test_23_result_mutation_does_not_affect_later_dispatches(self):
        plan = make_plan()
        first = dispatch_voice_enrollment(plan)
        meta = first.metadata
        meta["enrollment_mode"] = "tampered"
        d = first.to_dict()
        d["status"] = "X"
        second = dispatch_voice_enrollment(plan)
        self.assertEqual(second.metadata["enrollment_mode"], "standard")
        self.assertEqual(second.status, "NOT_IMPLEMENTED")
        rej = dispatch_voice_enrollment(None)
        rej.to_dict()["code"] = "X"
        self.assertEqual(dispatch_voice_enrollment(None).code, INVALID)

    def test_24_deterministic_for_valid_and_invalid(self):
        for _ in range(5):
            self.assertEqual(dispatch_voice_enrollment(make_plan()), dispatch_voice_enrollment(make_plan()))
            self.assertEqual(dispatch_voice_enrollment(None).to_dict(), dispatch_voice_enrollment(None).to_dict())

    def test_25_equal_plans_give_equal_results_and_different_plans_differ(self):
        a = dispatch_voice_enrollment(make_plan(request_id="a"))
        b = dispatch_voice_enrollment(make_plan(request_id="b"))
        self.assertNotEqual(a, b)
        self.assertEqual(a, dispatch_voice_enrollment(make_plan(request_id="a")))

    def test_26_no_io_during_dispatch(self):
        plan = make_plan()
        with mock.patch("builtins.open", side_effect=AssertionError("io")), mock.patch("socket.socket", side_effect=AssertionError("net")):
            dispatch_voice_enrollment(plan)
            dispatch_voice_enrollment(None)


class TestDocAndDb(unittest.TestCase):
    def test_27_doc_exists_and_names_the_api(self):
        with open(DOC, encoding="utf-8") as f:
            text = f.read()
        for needle in ("dispatch_voice_enrollment", INVALID, "Prompt 794", "Prompt 795 has NOT been started"):
            self.assertIn(needle, text)

    def test_28_database_is_pristine(self):
        with open(PROJECT_DB, "rb") as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
