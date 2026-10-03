"""Prompt 792 - Section 10 voice enrollment plan (`voice.voice_enrollment_plan`)."""
import ast
import copy
import gc
import hashlib
import os
import pickle
import sys
import unittest
from unittest import mock

from voice import voice_enrollment_plan as vp
from voice import voice_enrollment_request as vq
from voice.voice_enrollment_plan import VoiceEnrollmentPlan, VoiceEnrollmentPlanResult, create_voice_enrollment_plan
from voice.voice_enrollment_request import VoiceEnrollmentRequest, VoiceEnrollmentRequestResult, create_voice_enrollment_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section10_voice_enrollment_plan_prompt792.md")
MODULE = os.path.join(PY_ROOT, "voice", "voice_enrollment_plan.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
P = "VOICE_ENROLLMENT_PLAN_"
INVALID_VR, FAILED, INVALID_REQ, BAD_RID, BAD_PID, BAD_MODE = (P + "INVALID_VALIDATION_RESULT", P + "VALIDATION_FAILED", P + "INVALID_REQUEST",
                                                              P + "INVALID_REQUEST_ID", P + "INVALID_PROFILE_ID", P + "INVALID_ENROLLMENT_MODE")
FIELDS = ("request_id", "profile_id", "enrollment_mode")
FIELD_CODES = tuple(zip(FIELDS, (BAD_RID, BAD_PID, BAD_MODE)))


class Str(str):
    pass


def data(**over):
    d = {"request_id": "enroll_1", "profile_id": "voice_1", "enrollment_mode": "standard"}
    d.update(over)
    return d


def good():
    res = create_voice_enrollment_request(data())
    assert res.ok, res.failures
    return res


def raw_request(rid="r", pid="p", mode="m"):
    """A VoiceEnrollmentRequest with arbitrary internals (only possible inside tests, via the contract module's private token)."""
    return VoiceEnrollmentRequest(vq._CREATE_TOKEN, rid, pid, mode)


class TestValidConversion(unittest.TestCase):
    def test_1_valid_conversion(self):
        res = create_voice_enrollment_plan(good())
        self.assertIs(type(res), VoiceEnrollmentPlanResult)
        self.assertTrue(res.ok)
        self.assertEqual(res.failures, ())
        self.assertEqual(res.codes(), [])
        self.assertIs(type(res.plan), VoiceEnrollmentPlan)
        self.assertEqual((res.plan.request_id, res.plan.profile_id, res.plan.enrollment_mode), ("enroll_1", "voice_1", "standard"))
        self.assertEqual(res.to_dict(), {"ok": True, "plan": data(), "failures": []})

    def test_2_values_are_copied_exactly_with_identity_and_no_normalization(self):
        rid, pid, mode = " Req-1 ", "PROFILE\n", "  Any Free Text  "
        v = create_voice_enrollment_request({"request_id": rid, "profile_id": pid, "enrollment_mode": mode})
        plan = create_voice_enrollment_plan(v).plan
        self.assertIs(plan.request_id, v.request.request_id)
        self.assertIs(plan.profile_id, v.request.profile_id)
        self.assertIs(plan.enrollment_mode, v.request.enrollment_mode)
        self.assertEqual(plan.to_dict(), {"request_id": rid, "profile_id": pid, "enrollment_mode": mode})

    def test_3_input_is_unchanged(self):
        v = good()
        before = (v.to_dict(), v.request, repr(v.request), list(v.failures))
        create_voice_enrollment_plan(v)
        create_voice_enrollment_plan(v)
        self.assertEqual(before, (v.to_dict(), v.request, repr(v.request), list(v.failures)))
        self.assertIs(v.request, before[1])

    def test_4_to_dict_has_exactly_the_three_fields_and_is_fresh(self):
        plan = create_voice_enrollment_plan(good()).plan
        a, b = plan.to_dict(), plan.to_dict()
        self.assertEqual(list(a), list(FIELDS))
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        a["request_id"] = "mutated"
        a["extra"] = 1
        self.assertEqual(plan.to_dict(), data())
        self.assertEqual({n for n in dir(plan) if not n.startswith("_")}, set(FIELDS) | {"to_dict"})
        self.assertEqual(vp.FIELDS, FIELDS)


class TestFailedAndInvalidValidationResults(unittest.TestCase):
    def test_5_failed_validation_results_are_rejected(self):
        for bad_data in ({}, None, data(request_id=""), data(profile_id=5), data(enrollment_mode=None), dict(data(), extra=1), [1]):
            with self.subTest(bad=repr(bad_data)):
                v = create_voice_enrollment_request(bad_data)
                self.assertFalse(v.ok)
                res = create_voice_enrollment_plan(v)
                self.assertFalse(res.ok)
                self.assertIsNone(res.plan)
                self.assertEqual(res.codes(), [FAILED])
                self.assertEqual(res.failures[0]["field"], "validation_result")

    def test_6_wrong_types_are_invalid_validation_result(self):
        v = good()
        for bad in (None, {}, [], "x", 5, True, object(), v.to_dict(), v.request, VoiceEnrollmentRequestResult, (v,), create_voice_enrollment_plan(v),
                    create_voice_enrollment_plan(v).plan):
            with self.subTest(bad=type(bad).__name__):
                res = create_voice_enrollment_plan(bad)
                self.assertFalse(res.ok)
                self.assertIsNone(res.plan)
                self.assertEqual(res.codes(), [INVALID_VR])
                self.assertEqual(res.to_dict(), {"ok": False, "plan": None, "failures": [
                    {"code": INVALID_VR, "field": "validation_result", "message": "validation_result must be exactly a VoiceEnrollmentRequestResult."}]})

    def test_7_look_alikes_and_spoofed_class_are_rejected_and_never_read(self):
        class Fake:
            def __getattr__(self, name):
                raise AssertionError("must not read " + name)

        class Spoof:
            __class__ = VoiceEnrollmentRequestResult
            ok = True
            request = raw_request()

        class Sub(VoiceEnrollmentRequestResult):
            pass

        self.assertIsInstance(Spoof(), VoiceEnrollmentRequestResult)
        for bad in (Fake(), Spoof(), Sub(request=raw_request()), mock.MagicMock(spec=VoiceEnrollmentRequestResult)):
            res = create_voice_enrollment_plan(bad)
            self.assertEqual(res.codes(), [INVALID_VR])
            self.assertIsNone(res.plan)

    def test_8_never_raises_for_odd_inputs(self):
        class Boom:
            def __eq__(self, other):
                raise RuntimeError("boom")

            def __hash__(self):
                raise RuntimeError("boom")

            def __getattr__(self, name):
                raise RuntimeError("boom")

        for bad in (Boom(), float("nan"), b"x", {1: 2}, lambda: 1, type, 10 ** 100):
            res = create_voice_enrollment_plan(bad)
            self.assertEqual(res.codes(), [INVALID_VR])
            hash(res)


class TestMalformedValidationResults(unittest.TestCase):
    def test_9_ok_result_with_a_non_request_is_invalid_request(self):
        class Fake:
            request_id = profile_id = enrollment_mode = "x"

        for bad in (Fake(), {"request_id": "a", "profile_id": "b", "enrollment_mode": "c"}, "req", 5, True, object(), [raw_request()]):
            with self.subTest(bad=type(bad).__name__):
                v = VoiceEnrollmentRequestResult(request=bad)
                res = create_voice_enrollment_plan(v)
                self.assertFalse(res.ok)
                self.assertIsNone(res.plan)
                self.assertEqual(res.codes(), [INVALID_REQ])
                self.assertEqual(res.failures[0]["field"], "request")

    def test_10_failures_present_means_failed_even_with_a_request(self):
        v = VoiceEnrollmentRequestResult(request=raw_request(), failures=[{"code": "X", "field": None, "message": "m"}])
        self.assertFalse(v.ok)
        self.assertEqual(create_voice_enrollment_plan(v).codes(), [FAILED])
        self.assertEqual(create_voice_enrollment_plan(VoiceEnrollmentRequestResult()).codes(), [FAILED])

    def test_11_a_raising_ok_read_counts_as_failed(self):
        class BadFailures:
            def __bool__(self):
                raise RuntimeError("boom")

        v = VoiceEnrollmentRequestResult(request=raw_request(), failures=BadFailures())
        res = create_voice_enrollment_plan(v)
        self.assertEqual(res.codes(), [FAILED])
        self.assertIsNone(res.plan)

    def test_12_each_field_rejects_wrong_types_and_empty_strings(self):
        for index, (field, code) in enumerate(FIELD_CODES):
            for bad in (None, 5, True, b"x", ("a",), Str("abc"), Str(""), ""):
                with self.subTest(field=field, bad=repr(bad)):
                    args = ["r", "p", "m"]
                    args[index] = bad
                    res = create_voice_enrollment_plan(VoiceEnrollmentRequestResult(request=raw_request(*args)))
                    self.assertFalse(res.ok)
                    self.assertIsNone(res.plan)
                    self.assertEqual(res.codes(), [code])
                    self.assertEqual(res.failures[0]["field"], field)

    def test_13_all_field_failures_are_reported_together_in_order(self):
        res = create_voice_enrollment_plan(VoiceEnrollmentRequestResult(request=raw_request(1, 2, 3)))
        self.assertEqual(res.codes(), [BAD_RID, BAD_PID, BAD_MODE])
        self.assertEqual([f["field"] for f in res.failures], list(FIELDS))
        res = create_voice_enrollment_plan(VoiceEnrollmentRequestResult(request=raw_request("", "p", None)))
        self.assertEqual(res.codes(), [BAD_RID, BAD_MODE])
        res = create_voice_enrollment_plan(VoiceEnrollmentRequestResult(request=raw_request("r", Str("p"), "m")))
        self.assertEqual(res.codes(), [BAD_PID])

    def test_14_a_field_read_that_raises_counts_as_invalid(self):
        def boom(self):
            raise RuntimeError("boom")

        for field, code in FIELD_CODES:
            with self.subTest(field=field):
                with mock.patch.object(VoiceEnrollmentRequest, field, property(boom)):
                    res = create_voice_enrollment_plan(good())
                self.assertEqual(res.codes(), [code])
                self.assertIsNone(res.plan)

    def test_15_a_raising_request_read_counts_as_failed_validation(self):
        v = good()
        boom = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
        with mock.patch.object(VoiceEnrollmentRequestResult, "request", boom):
            res = create_voice_enrollment_plan(v)
        self.assertEqual(res.codes(), [FAILED])
        self.assertIsNone(res.plan)
        self.assertTrue(create_voice_enrollment_plan(v).ok)

    def test_16_codes_are_stable_unique_and_prefixed(self):
        self.assertEqual(vp.FAILURE_CODES, (INVALID_VR, FAILED, INVALID_REQ, BAD_RID, BAD_PID, BAD_MODE))
        self.assertEqual(len(set(vp.FAILURE_CODES)), 6)
        for code in vp.FAILURE_CODES:
            self.assertTrue(code.startswith(P))
        self.assertEqual(INVALID_VR, "VOICE_ENROLLMENT_PLAN_INVALID_VALIDATION_RESULT")


class TestIdentityAndNonRetention(unittest.TestCase):
    def test_17_plan_holds_only_the_three_primitive_values(self):
        v = good()
        plan = create_voice_enrollment_plan(v).plan
        self.assertEqual(type(plan).__slots__, ("_request_id", "_profile_id", "_enrollment_mode"))
        for slot in type(plan).__slots__:
            self.assertIs(type(getattr(plan, slot)), str)
            self.assertIsNot(getattr(plan, slot), v)
            self.assertIsNot(getattr(plan, slot), v.request)
        self.assertIsNot(plan, v.request)
        self.assertNotEqual(plan, v.request)

    def test_18_result_does_not_retain_the_validation_result_or_request(self):
        v = good()
        res = create_voice_enrollment_plan(v)
        for slot in type(res).__slots__:
            self.assertIsNot(getattr(res, slot), v)
            self.assertIsNot(getattr(res, slot), v.request)
        bad = VoiceEnrollmentRequestResult(request=raw_request(1, 2, 3))
        res = create_voice_enrollment_plan(bad)
        for slot in type(res).__slots__:
            self.assertIsNot(getattr(res, slot), bad)
            self.assertIsNot(getattr(res, slot), bad.request)
        self.assertIsNone(res.plan)

    def test_19_nothing_in_the_plan_or_result_refers_to_the_input_objects(self):
        v = VoiceEnrollmentRequestResult(request=raw_request("r1", "p1", "m1"))
        request = v.request
        res = create_voice_enrollment_plan(v)
        self.assertTrue(res.ok)
        for holder in (res, res.plan):
            referents = gc.get_referents(holder)
            self.assertFalse([r for r in referents if r is v or r is request], type(holder).__name__)
        self.assertEqual({type(r) for r in gc.get_referents(res.plan) if r is not VoiceEnrollmentPlan}, {str})
        self.assertEqual(res.plan.to_dict(), {"request_id": "r1", "profile_id": "p1", "enrollment_mode": "m1"})

    def test_20_later_changes_to_the_carrier_do_not_affect_the_plan(self):
        v = good()
        plan = create_voice_enrollment_plan(v).plan
        v.request = None
        v.failures.append({"code": "X"})
        self.assertEqual(plan.to_dict(), data())

    def test_21_no_biometric_audio_or_embedding_attributes(self):
        plan = create_voice_enrollment_plan(good()).plan
        for word in ("audio", "recording", "embedding", "biometric", "sample", "voiceprint", "credential", "registry"):
            self.assertFalse([n for n in dir(plan) if word in n.lower()], word)


class TestObjectContracts(unittest.TestCase):
    def setUp(self):
        self.v = good()
        self.ok = create_voice_enrollment_plan(self.v)
        self.bad = create_voice_enrollment_plan(None)
        self.mal = create_voice_enrollment_plan(VoiceEnrollmentRequestResult(request=raw_request(1, 2, 3)))

    def test_22_immutable(self):
        for obj in (self.ok, self.bad, self.mal, self.ok.plan):
            for name in ("ok", "plan", "failures", "request_id", "_plan", "_request_id", "extra"):
                with self.assertRaises(AttributeError):
                    setattr(obj, name, "x")
                with self.assertRaises(AttributeError):
                    delattr(obj, name)

    def test_23_direct_construction_and_subclassing_refused(self):
        with self.assertRaises(TypeError):
            VoiceEnrollmentPlan(None, "a", "b", "c")
        with self.assertRaises(TypeError):
            VoiceEnrollmentPlan(object(), "a", "b", "c")
        with self.assertRaises(TypeError):
            VoiceEnrollmentPlanResult(None, self.ok.plan, ())
        with self.assertRaises(TypeError):
            type("Sub", (VoiceEnrollmentPlan,), {})
        with self.assertRaises(TypeError):
            type("Sub", (VoiceEnrollmentPlanResult,), {})

    def test_24_equality_and_hash(self):
        again = create_voice_enrollment_plan(good())
        self.assertEqual(self.ok.plan, again.plan)
        self.assertEqual(hash(self.ok.plan), hash(again.plan))
        self.assertEqual(self.ok, again)
        self.assertEqual(hash(self.ok), hash(again))
        self.assertEqual(len({self.ok.plan, again.plan}), 1)
        for field in FIELDS:
            other = create_voice_enrollment_plan(create_voice_enrollment_request(data(**{field: "other"}))).plan
            self.assertNotEqual(self.ok.plan, other)
        self.assertNotEqual(self.ok, self.bad)
        self.assertEqual(self.bad, create_voice_enrollment_plan(5))
        self.assertEqual(self.mal, create_voice_enrollment_plan(VoiceEnrollmentRequestResult(request=raw_request(9, 9, 9))))
        for other in (self.ok.plan.to_dict(), None, 1, "x", self.v.request):
            self.assertNotEqual(self.ok.plan, other)
        self.assertEqual(self.ok.plan.__eq__(self.v.request), NotImplemented)

    def test_25_copy_deepcopy_and_pickle(self):
        for obj in (self.ok, self.bad, self.mal, self.ok.plan):
            self.assertIs(copy.copy(obj), obj)
            self.assertIs(copy.deepcopy(obj), obj)
            for proto in range(pickle.HIGHEST_PROTOCOL + 1):
                with self.assertRaises(TypeError):
                    pickle.dumps(obj, protocol=proto)

    def test_26_repr_is_stable(self):
        self.assertEqual(repr(self.ok.plan), "VoiceEnrollmentPlan(request_id='enroll_1', profile_id='voice_1', enrollment_mode='standard')")
        self.assertEqual(repr(self.ok), "VoiceEnrollmentPlanResult(ok=True, codes=[])")
        self.assertEqual(repr(self.bad), "VoiceEnrollmentPlanResult(ok=False, codes=['%s'])" % INVALID_VR)

    def test_27_result_surface_and_fresh_failures(self):
        for obj in (self.ok, self.bad, self.mal):
            self.assertEqual({n for n in dir(obj) if not n.startswith("_")}, {"ok", "plan", "failures", "codes", "to_dict"})
            a, b = obj.to_dict(), obj.to_dict()
            self.assertEqual(a, b)
            self.assertIsNot(a["failures"], b["failures"])
            a["failures"].append({"code": "x"})
            for f in obj.failures:
                f["code"] = "mutated"
            self.assertEqual(obj.to_dict(), b)
        self.assertIsInstance(self.bad.failures, tuple)


class TestDeterminismAndSideEffects(unittest.TestCase):
    def test_28_repeated_conversion_is_deterministic(self):
        v = good()
        results = [create_voice_enrollment_plan(v) for _ in range(5)]
        for r in results[1:]:
            self.assertEqual(r, results[0])
            self.assertEqual(r.to_dict(), results[0].to_dict())
        for item in (None, VoiceEnrollmentRequestResult(), VoiceEnrollmentRequestResult(request=raw_request(1, 2, 3))):
            self.assertEqual(len({create_voice_enrollment_plan(item) for _ in range(3)}), 1)

    def test_29_no_side_effects(self):
        v, mal = good(), VoiceEnrollmentRequestResult(request=raw_request(1, 2, 3))
        before_env, before_cwd, before_mods = dict(os.environ), os.getcwd(), set(sys.modules)
        before_tree = sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d)
        for _ in range(3):
            for item in (v, mal, None):
                create_voice_enrollment_plan(item)
        self.assertEqual(dict(os.environ), before_env)
        self.assertEqual(os.getcwd(), before_cwd)
        self.assertEqual(set(sys.modules), before_mods)
        self.assertEqual(sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d), before_tree)
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)

    def test_30_no_io_network_subprocess_or_persistence_calls(self):
        import builtins
        import io
        import os as _os
        import socket
        import sqlite3
        import subprocess
        v, mal = good(), VoiceEnrollmentRequestResult(request=raw_request(1, 2, 3))
        boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError("forbidden call"))
        with mock.patch.object(socket, "socket", boom), mock.patch.object(socket, "create_connection", boom), \
                mock.patch.object(subprocess, "Popen", boom), mock.patch.object(_os, "system", boom), mock.patch.object(builtins, "open", boom), \
                mock.patch.object(io, "open", boom), mock.patch.object(_os, "open", boom), mock.patch.object(_os, "listdir", boom), \
                mock.patch.object(sqlite3, "connect", boom):
            self.assertTrue(create_voice_enrollment_plan(v).ok)
            self.assertEqual(create_voice_enrollment_plan(mal).codes(), [BAD_RID, BAD_PID, BAD_MODE])
            self.assertEqual(create_voice_enrollment_plan(None).codes(), [INVALID_VR])


class TestBoundaries(unittest.TestCase):
    def _tree(self):
        with open(MODULE, encoding="utf-8") as fh:
            return ast.parse(fh.read())

    def test_31_module_imports_only_the_request_types(self):
        imports = [(n.module, n.level, sorted(a.name for a in n.names)) for n in ast.walk(self._tree()) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(imports, [("voice_enrollment_request", 1, ["VoiceEnrollmentRequest", "VoiceEnrollmentRequestResult"])])

    def test_32_module_is_pure_and_has_no_module_state(self):
        tree = self._tree()
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "setattr", "globals", "vars"):
            self.assertNotIn(forbidden, calls)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("os", "sys", "io", "pathlib", "subprocess", "socket", "urllib", "http", "requests", "sqlite3", "random", "time", "datetime",
                     "anthropic", "openai", "numpy", "wave", "core", "agent", "planning", "web", "multimedia", "game_creation",
                     "create_voice_enrollment_request", "VoiceIdentityProfile", "VoiceIdentityProfileRegistry", "VoiceEnrollmentResult"):
            self.assertNotIn(word, names, word)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.ImportFrom))
        for name, value in vars(vp).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_33_existing_voice_modules_are_unaware_of_the_plan_and_unchanged_in_contract(self):
        for name in ("voice_identity_profile.py", "voice_identity_profile_registry.py", "voice_enrollment_request.py", "voice_enrollment_result.py",
                     "voice_enrollment_result_validator.py"):
            with open(os.path.join(PY_ROOT, "voice", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("voice_enrollment_plan", "VoiceEnrollmentPlan", "create_voice_enrollment_plan"):
                self.assertNotIn(token, text, (name, token))
        self.assertEqual(vq.FIELDS, FIELDS)
        self.assertEqual(vq.FAILURE_CODES[0], "VOICE_ENROLLMENT_REQUEST_INVALID_INPUT")

    def test_34_no_module_outside_voice_references_it(self):
        tokens = ("voice_enrollment_plan", "VoiceEnrollmentPlan", "create_voice_enrollment_plan")
        checked = 0
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if not (folder == PY_ROOT and d in ("voice", "tests", "data")) and d != "__pycache__"]
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        text = fh.read()
                    for token in tokens:
                        self.assertNotIn(token, text, os.path.join(folder, name))
                    checked += 1
        self.assertGreater(checked, 100)

    def test_35_voice_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "voice")) if f != "__pycache__"),
                         ["__init__.py", "voice_enrollment_batch.py", "voice_enrollment_batch_summary.py", "voice_enrollment_dispatcher.py", "voice_enrollment_executor.py", "voice_enrollment_pipeline.py", "voice_enrollment_plan.py", "voice_enrollment_request.py", "voice_enrollment_result.py",
                          "voice_enrollment_result_validator.py", "voice_identity_profile.py", "voice_identity_profile_registry.py", "voice_verification_authorization.py", "voice_verification_batch.py", "voice_verification_batch_summary.py", "voice_verification_decision.py", "voice_verification_dispatcher.py", "voice_verification_execution.py", "voice_verification_execution_request.py", "voice_verification_executor.py", "voice_verification_handoff.py", "voice_verification_pipeline.py", "voice_verification_plan.py", "voice_verification_profile_resolver.py", "voice_verification_registry.py", "voice_verification_request.py", "voice_verification_request_validator.py", "voice_verification_result.py"])
        with open(os.path.join(PY_ROOT, "voice", "__init__.py"), "rb") as fh:
            self.assertEqual(fh.read(), b"")

    def test_36_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("VoiceEnrollmentPlan", "VoiceEnrollmentPlanResult", "create_voice_enrollment_plan", "VOICE_ENROLLMENT_PLAN_", "VoiceEnrollmentRequestResult",
                       "INVALID_VALIDATION_RESULT", "VALIDATION_FAILED", "INVALID_REQUEST", "INVALID_ENROLLMENT_MODE", "does NOT", "Prompt 793"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
