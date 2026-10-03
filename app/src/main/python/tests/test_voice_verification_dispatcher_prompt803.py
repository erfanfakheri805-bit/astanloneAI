"""Prompt 803 - Section 10 voice verification dispatcher (`voice.voice_verification_dispatcher`)."""
import ast
import gc
import hashlib
import os
import sys
import unittest
import weakref
from unittest import mock

from voice import voice_verification_dispatcher as vd
from voice import voice_verification_executor as ve
from voice import voice_verification_plan as vp
from voice.voice_verification_dispatcher import dispatch_voice_verification
from voice.voice_verification_plan import VoiceVerificationPlan, create_voice_verification_plan
from voice.voice_verification_request import create_voice_verification_request
from voice.voice_verification_request_validator import validate_voice_verification_request
from voice.voice_verification_result import VoiceVerificationResult, create_voice_verification_result

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section10_voice_verification_dispatcher_prompt803.md")
MODULE = os.path.join(PY_ROOT, "voice", "voice_verification_dispatcher.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
INVALID = "VOICE_VERIFICATION_DISPATCHER_INVALID_PLAN"
TARGET = "voice.voice_verification_dispatcher.execute_voice_verification_plan"


class Plan2(object):
    pass


def make_plan(**over):
    d = {"request_id": "verify_1", "profile_id": "voice_1", "verification_mode": "standard"}
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


class TestExactTypeRejection(unittest.TestCase):
    def check_rejected(self, value):
        with mock.patch(TARGET) as ex:
            res = dispatch_voice_verification(value)
        ex.assert_not_called()
        self.assertIs(type(res), VoiceVerificationResult)
        self.assertEqual((res.status, res.code, res.metadata), ("REJECTED", INVALID, None))
        self.assertEqual((res.request_id, res.profile_id), (ve.UNKNOWN_ID, ve.UNKNOWN_ID))

    def test_1_non_plans_are_rejected(self):
        plan = make_plan()
        for bad in (None, {}, plan.to_dict(), "plan", 1, True, [plan], (plan,), object(), Plan2(), VoiceVerificationPlan, Spoof(), b"", 1.5):
            with self.subTest(bad=type(bad).__name__):
                self.check_rejected(bad)

    def test_2_lookalike_with_plan_attributes_is_rejected(self):
        class Look(object):
            request_id, profile_id, verification_mode = "a", "b", "c"
        self.check_rejected(Look())

    def test_3_other_voice_types_are_rejected(self):
        from voice.voice_enrollment_plan import VoiceEnrollmentPlan as EnrollmentPlan
        req = create_voice_verification_request({"request_id": "r", "profile_id": "p", "verification_mode": "m"})
        validation = validate_voice_verification_request(req.request)
        plan_result = create_voice_verification_plan(validation)
        self.check_rejected(req)
        self.check_rejected(req.request)
        self.check_rejected(validation)
        self.check_rejected(plan_result)
        self.check_rejected(ve.execute_voice_verification_plan(plan_result.plan))      # a result is not a plan
        self.check_rejected(EnrollmentPlan.__new__(EnrollmentPlan))

    def test_4_rejected_result_is_valid_and_has_exact_dict(self):
        res = dispatch_voice_verification(None)
        self.assertEqual(res.to_dict(), {"request_id": "UNKNOWN", "profile_id": "UNKNOWN", "status": "REJECTED", "code": INVALID, "metadata": None})
        self.assertEqual(create_voice_verification_result(res.to_dict()).result, res)

    def test_5_rejection_is_equal_but_a_fresh_object_each_time(self):
        a, b = dispatch_voice_verification(None), dispatch_voice_verification(1)
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
            dispatch_voice_verification(plan)
        self.assertEqual(ex.call_count, 1)
        args, kwargs = ex.call_args
        self.assertEqual(len(args), 1)
        self.assertIs(args[0], plan)
        self.assertEqual(kwargs, {})

    def test_8_returned_object_identity_is_preserved(self):
        plan = make_plan()
        for sentinel in (object(), None, "x", 5, VoiceVerificationResult.__name__):
            with mock.patch(TARGET, return_value=sentinel):
                self.assertIs(dispatch_voice_verification(plan), sentinel)

    def test_9_real_executor_result_is_returned_as_is(self):
        plan = make_plan()
        produced = []
        real = ve.execute_voice_verification_plan

        def spy(p):
            r = real(p)
            produced.append(r)
            return r
        with mock.patch(TARGET, side_effect=spy):
            res = dispatch_voice_verification(plan)
        self.assertEqual(len(produced), 1)
        self.assertIs(res, produced[0])
        self.assertEqual((res.status, res.code), ("NOT_IMPLEMENTED", "VOICE_VERIFICATION_EXECUTOR_NOT_IMPLEMENTED"))
        self.assertEqual(res, real(plan))

    def test_10_executor_rejection_is_returned_unchanged(self):
        plan = VoiceVerificationPlan(vp._CREATE_TOKEN, "r", "p", "")      # malformed, only possible privately
        res = dispatch_voice_verification(plan)
        self.assertEqual(res.code, "VOICE_VERIFICATION_EXECUTOR_INVALID_PLAN")
        self.assertEqual(res, ve.execute_voice_verification_plan(plan))

    def test_11_executor_exception_propagates_not_swallowed(self):
        with mock.patch(TARGET, side_effect=RuntimeError("boom")) as ex:
            with self.assertRaises(RuntimeError):
                dispatch_voice_verification(make_plan())
        self.assertEqual(ex.call_count, 1)

    def test_12_each_dispatch_calls_executor_once(self):
        plan = make_plan()
        with mock.patch(TARGET, return_value=1) as ex:
            for n in range(1, 4):
                dispatch_voice_verification(plan)
                self.assertEqual(ex.call_count, n)


class TestNoDuplicationAndPurity(unittest.TestCase):
    def setUp(self):
        with open(MODULE, encoding="utf-8") as f:
            self.src = f.read()
        self.tree = ast.parse(self.src)

    def test_13_module_has_no_executor_logic(self):
        for name in ("NOT_IMPLEMENTED", "verification_mode", "request_id=", ".metadata", "plan.request_id", "plan.profile_id"):
            body = self.src.split('"""', 2)[2]
            self.assertNotIn(name, body.replace('"request_id": UNKNOWN_ID', ""))

    def test_14_imports_are_only_the_voice_siblings(self):
        mods = [n.module for n in ast.walk(self.tree) if isinstance(n, ast.ImportFrom)]
        self.assertEqual(sorted(mods), ["voice_verification_executor", "voice_verification_plan", "voice_verification_result"])
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
        for n in ("dispatch_voice_verification", "CODE_INVALID_PLAN", "STATUS_REJECTED", "CODES"):
            self.assertIn(n, public)
        self.assertEqual(vd.CODE_INVALID_PLAN, INVALID)
        self.assertEqual(vd.STATUS_REJECTED, "REJECTED")

    def test_18_no_wiring_into_core_or_agent_loop(self):
        for root in ("core", "agent", "planning", "android_entry.py"):
            path = os.path.join(PY_ROOT, root)
            files = [path] if path.endswith(".py") else [os.path.join(d, f) for d, _s, fs in os.walk(path) for f in fs if f.endswith(".py")]
            for fp in files:
                with open(fp, encoding="utf-8") as f:
                    self.assertNotIn("voice_verification_dispatcher", f.read(), fp)

    def test_19_existing_voice_modules_do_not_mention_the_verification_dispatcher(self):
        vdir = os.path.join(PY_ROOT, "voice")
        for f in os.listdir(vdir):
            if f.endswith(".py") and f not in ("voice_verification_dispatcher.py", "voice_verification_pipeline.py"):      # Prompt 804: the pipeline sits in front of the dispatcher
                with open(os.path.join(vdir, f), encoding="utf-8") as fh:
                    text = fh.read()
                for token in ("voice_verification_dispatcher", "dispatch_voice_verification"):
                    self.assertNotIn(token, text, f)

    def test_19b_voice_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "voice")) if f != "__pycache__"),
                         ["__init__.py", "voice_enrollment_batch.py", "voice_enrollment_batch_summary.py", "voice_enrollment_dispatcher.py",
                          "voice_enrollment_executor.py", "voice_enrollment_pipeline.py", "voice_enrollment_plan.py", "voice_enrollment_request.py",
                          "voice_enrollment_result.py", "voice_enrollment_result_validator.py", "voice_identity_profile.py",
                          "voice_identity_profile_registry.py", "voice_verification_authorization.py", "voice_verification_batch.py", "voice_verification_batch_summary.py", "voice_verification_decision.py", "voice_verification_dispatcher.py", "voice_verification_execution.py", "voice_verification_execution_request.py", "voice_verification_executor.py", "voice_verification_handoff.py",
                          "voice_verification_pipeline.py",
                          "voice_verification_plan.py", "voice_verification_profile_resolver.py", "voice_verification_registry.py", "voice_verification_request.py", "voice_verification_request_validator.py",
                          "voice_verification_result.py"])
        with open(os.path.join(PY_ROOT, "voice", "__init__.py"), "rb") as fh:
            self.assertEqual(fh.read(), b"")

    def test_19c_no_module_outside_voice_references_it(self):
        checked = 0
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if not (folder == PY_ROOT and d in ("voice", "tests", "data")) and d != "__pycache__"]
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        text = fh.read()
                    for token in ("voice_verification_dispatcher", "dispatch_voice_verification"):
                        self.assertNotIn(token, text, os.path.join(folder, name))
                    checked += 1
        self.assertGreater(checked, 100)

    def test_19d_stable_codes_and_separation_from_the_enrollment_dispatcher(self):
        import voice.voice_enrollment_dispatcher as ed
        self.assertEqual(vd.CODES, ("VOICE_VERIFICATION_DISPATCHER_INVALID_PLAN",))
        self.assertFalse(set(vd.CODES) & set(ed.CODES))
        code_text = self.src.split('"""', 2)[2]
        for token in ("enrollment", "Enrollment", "ENROLLMENT"):
            self.assertNotIn(token, code_text, token)


class TestMutationAndDeterminism(unittest.TestCase):
    def test_20_plan_is_unchanged_by_dispatch(self):
        plan = make_plan()
        before = (plan.to_dict(), repr(plan), hash(plan))
        dispatch_voice_verification(plan)
        self.assertEqual((plan.to_dict(), repr(plan), hash(plan)), before)

    def test_21_plan_is_not_retained(self):
        plan = make_plan(request_id="retain-test")
        gc.collect()
        before = sys.getrefcount(plan)
        res = dispatch_voice_verification(plan)
        gc.collect()
        self.assertEqual(sys.getrefcount(plan), before)
        self.assertEqual([o for o in gc.get_referrers(plan) if o is res], [])
        self.assertEqual(res.request_id, "retain-test")

    def test_22_invalid_input_is_not_retained(self):
        class Holder(object):
            pass
        h = Holder()
        ref = weakref.ref(h)
        dispatch_voice_verification(h)
        del h
        gc.collect()
        self.assertIsNone(ref())

    def test_23_result_mutation_does_not_affect_later_dispatches(self):
        plan = make_plan()
        first = dispatch_voice_verification(plan)
        meta = first.metadata
        meta["verification_mode"] = "tampered"
        d = first.to_dict()
        d["status"] = "X"
        second = dispatch_voice_verification(plan)
        self.assertEqual(second.metadata["verification_mode"], "standard")
        self.assertEqual(second.status, "NOT_IMPLEMENTED")
        rej = dispatch_voice_verification(None)
        rej.to_dict()["code"] = "X"
        self.assertEqual(dispatch_voice_verification(None).code, INVALID)

    def test_24_deterministic_for_valid_and_invalid(self):
        for _ in range(5):
            self.assertEqual(dispatch_voice_verification(make_plan()), dispatch_voice_verification(make_plan()))
            self.assertEqual(dispatch_voice_verification(None).to_dict(), dispatch_voice_verification(None).to_dict())

    def test_25_equal_plans_give_equal_results_and_different_plans_differ(self):
        a = dispatch_voice_verification(make_plan(request_id="a"))
        b = dispatch_voice_verification(make_plan(request_id="b"))
        self.assertNotEqual(a, b)
        self.assertEqual(a, dispatch_voice_verification(make_plan(request_id="a")))

    def test_26_no_io_during_dispatch(self):
        plan = make_plan()
        with mock.patch("builtins.open", side_effect=AssertionError("io")), mock.patch("socket.socket", side_effect=AssertionError("net")):
            dispatch_voice_verification(plan)
            dispatch_voice_verification(None)


class TestDocAndDb(unittest.TestCase):
    def test_27_doc_exists_and_names_the_api(self):
        with open(DOC, encoding="utf-8") as f:
            text = f.read()
        for needle in ("dispatch_voice_verification", INVALID, "Prompt 803", "Prompt 804 has NOT been started"):
            self.assertIn(needle, text)

    def test_28_database_is_pristine(self):
        with open(PROJECT_DB, "rb") as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
