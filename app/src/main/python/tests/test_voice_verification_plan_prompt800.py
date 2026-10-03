"""Prompt 800 - Section 10 voice verification plan (`voice.voice_verification_plan`)."""
import ast
import copy
import gc
import hashlib
import os
import pickle
import sys
import unittest
from unittest import mock

from voice import voice_verification_plan as vp
from voice import voice_verification_request as vq
from voice import voice_verification_request_validator as vv
from voice.voice_verification_plan import VoiceVerificationPlan, VoiceVerificationPlanResult, create_voice_verification_plan
from voice.voice_verification_request import VoiceVerificationRequest, create_voice_verification_request
from voice.voice_verification_request_validator import VoiceVerificationRequestValidationResult, validate_voice_verification_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section10_voice_verification_plan_prompt800.md")
MODULE = os.path.join(PY_ROOT, "voice", "voice_verification_plan.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
P = "VOICE_VERIFICATION_PLAN_"
INVALID_VR, FAILED, INVALID_REQ, BAD_RID, BAD_PID, BAD_MODE = (P + "INVALID_VALIDATION_RESULT", P + "VALIDATION_FAILED", P + "INVALID_REQUEST",
                                                              P + "INVALID_REQUEST_ID", P + "INVALID_PROFILE_ID", P + "INVALID_VERIFICATION_MODE")
FIELDS = ("request_id", "profile_id", "verification_mode")
FIELD_CODES = tuple(zip(FIELDS, (BAD_RID, BAD_PID, BAD_MODE)))


class Str(str):
    pass


def data(**over):
    d = {"request_id": "verify_1", "profile_id": "voice_1", "verification_mode": "standard"}
    d.update(over)
    return d


def raw_request(rid="r", pid="p", mode="m"):
    """A VoiceVerificationRequest with arbitrary internals (only possible inside tests, via the contract module's private token)."""
    return VoiceVerificationRequest(vq._CREATE_TOKEN, rid, pid, mode)


def raw_result(request=None, failures=()):
    """A VoiceVerificationRequestValidationResult with arbitrary internals (only possible inside tests, via the validator's private token)."""
    return VoiceVerificationRequestValidationResult(vv._CREATE_TOKEN, request, failures)


def good(**over):
    created = create_voice_verification_request(data(**over))
    assert created.ok, created.failures
    res = validate_voice_verification_request(created.request)
    assert res.ok, res.failures
    return res


class TestValidConversion(unittest.TestCase):
    def test_1_valid_successful_validation_result(self):
        res = create_voice_verification_plan(good())
        self.assertIs(type(res), VoiceVerificationPlanResult)
        self.assertTrue(res.ok)
        self.assertEqual(res.failures, ())
        self.assertEqual(res.codes(), [])
        self.assertIs(type(res.plan), VoiceVerificationPlan)
        self.assertEqual((res.plan.request_id, res.plan.profile_id, res.plan.verification_mode), ("verify_1", "voice_1", "standard"))
        self.assertEqual(res.to_dict(), {"ok": True, "plan": data(), "failures": []})

    def test_2_values_are_copied_exactly_with_identity_and_no_normalization(self):
        rid, pid, mode = " Req-1 ", "PROFILE\n", "  Any Free Text  "
        created = create_voice_verification_request({"request_id": rid, "profile_id": pid, "verification_mode": mode})
        v = validate_voice_verification_request(created.request)
        plan = create_voice_verification_plan(v).plan
        self.assertIs(plan.request_id, v.request.request_id)
        self.assertIs(plan.profile_id, v.request.profile_id)
        self.assertIs(plan.verification_mode, v.request.verification_mode)
        self.assertEqual(plan.to_dict(), {"request_id": rid, "profile_id": pid, "verification_mode": mode})
        for mode in ("unknown-mode", "STANDARD", "standard", "  ", "\u00e9", "x" * 1000):
            with self.subTest(mode=mode):
                self.assertEqual(create_voice_verification_plan(good(verification_mode=mode)).plan.verification_mode, mode)

    def test_3_input_is_unchanged(self):
        v = good()
        before = (v.to_dict(), v.request, repr(v.request), v.failures, hash(v))
        create_voice_verification_plan(v)
        create_voice_verification_plan(v)
        self.assertEqual(before, (v.to_dict(), v.request, repr(v.request), v.failures, hash(v)))
        self.assertIs(v.request, before[1])

    def test_4_to_dict_has_exactly_the_three_fields_and_is_fresh(self):
        plan = create_voice_verification_plan(good()).plan
        a, b = plan.to_dict(), plan.to_dict()
        self.assertEqual(list(a), list(FIELDS))
        self.assertEqual(a, b)
        self.assertIsNot(a, b)
        a["request_id"] = "mutated"
        a["extra"] = 1
        self.assertEqual(plan.to_dict(), data())
        self.assertEqual(list(plan.to_dict()), ["request_id", "profile_id", "verification_mode"])
        self.assertEqual({n for n in dir(plan) if not n.startswith("_")}, set(FIELDS) | {"to_dict"})
        self.assertEqual(vp.FIELDS, FIELDS)


class TestFailedAndInvalidValidationResults(unittest.TestCase):
    def test_5_failed_validation_results_are_rejected(self):
        failed = [validate_voice_verification_request(x) for x in (None, {}, "x", raw_request("", "p", "m"), raw_request("r", 5, "m"), raw_request(1, 2, 3))]
        failed.append(raw_result(raw_request(), [("X", "request", "m")]))
        failed.append(raw_result(None, [("X", "request", "m")]))
        for v in failed:
            with self.subTest(bad=repr(v)):
                self.assertFalse(v.ok)
                res = create_voice_verification_plan(v)
                self.assertFalse(res.ok)
                self.assertIsNone(res.plan)
                self.assertEqual(res.codes(), [FAILED])
                self.assertEqual(res.failures[0]["field"], "validation_result")
                self.assertEqual(res.failures[0]["message"], "The voice verification request did not pass validation.")

    def test_6_wrong_types_are_invalid_validation_result(self):
        v = good()
        created = create_voice_verification_request(data())
        for bad in (None, {}, [], "x", 5, True, object(), v.to_dict(), v.request, VoiceVerificationRequestValidationResult, (v,), created,
                    create_voice_verification_plan(v), create_voice_verification_plan(v).plan):
            with self.subTest(bad=type(bad).__name__):
                res = create_voice_verification_plan(bad)
                self.assertFalse(res.ok)
                self.assertIsNone(res.plan)
                self.assertEqual(res.codes(), [INVALID_VR])
                self.assertEqual(res.to_dict(), {"ok": False, "plan": None, "failures": [
                    {"code": INVALID_VR, "field": "validation_result", "message": "validation_result must be exactly a VoiceVerificationRequestValidationResult."}]})

    def test_7_look_alikes_and_spoofed_class_are_rejected_and_never_read(self):
        class Fake:
            def __getattr__(self, name):
                raise AssertionError("must not read " + name)

        class Spoof:
            __class__ = VoiceVerificationRequestValidationResult
            ok = True
            request = raw_request()
            failures = ()

        self.assertIsInstance(Spoof(), VoiceVerificationRequestValidationResult)      # isinstance is fooled, the exact type check is not
        with self.assertRaises(TypeError):
            type("Sub", (VoiceVerificationRequestValidationResult,), {})
        for bad in (Fake(), Spoof(), mock.MagicMock(spec=VoiceVerificationRequestValidationResult)):
            res = create_voice_verification_plan(bad)
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
            res = create_voice_verification_plan(bad)
            self.assertEqual(res.codes(), [INVALID_VR])
            hash(res)


class TestMalformedValidationResults(unittest.TestCase):
    def test_9_ok_result_with_a_non_request_is_invalid_request(self):
        class Fake:
            request_id = profile_id = verification_mode = "x"

        for bad in (None, Fake(), {"request_id": "a", "profile_id": "b", "verification_mode": "c"}, "req", 5, True, object(), [raw_request()],
                    create_voice_verification_request(data())):
            with self.subTest(bad=type(bad).__name__):
                v = raw_result(bad)
                self.assertTrue(v.ok)
                res = create_voice_verification_plan(v)
                self.assertFalse(res.ok)
                self.assertIsNone(res.plan)
                self.assertEqual(res.codes(), [INVALID_REQ])
                self.assertEqual(res.failures[0]["field"], "request")
                self.assertEqual(res.failures[0]["message"], "The validated request must be exactly a VoiceVerificationRequest.")

    def test_10_failures_present_means_failed_even_with_a_request(self):
        v = raw_result(raw_request(), [("X", None, "m")])
        self.assertFalse(v.ok)
        self.assertEqual(create_voice_verification_plan(v).codes(), [FAILED])

    def test_11_a_raising_ok_read_counts_as_failed(self):
        v = good()
        boom = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
        with mock.patch.object(VoiceVerificationRequestValidationResult, "ok", boom):
            res = create_voice_verification_plan(v)
        self.assertEqual(res.codes(), [FAILED])
        self.assertIsNone(res.plan)
        self.assertTrue(create_voice_verification_plan(v).ok)

    def test_12_each_field_rejects_wrong_types_and_empty_strings(self):
        for index, (field, code) in enumerate(FIELD_CODES):
            for bad in (None, 5, True, b"x", ("a",), Str("abc"), Str(""), ""):
                with self.subTest(field=field, bad=repr(bad)):
                    args = ["r", "p", "m"]
                    args[index] = bad
                    res = create_voice_verification_plan(raw_result(raw_request(*args)))
                    self.assertFalse(res.ok)
                    self.assertIsNone(res.plan)
                    self.assertEqual(res.codes(), [code])
                    self.assertEqual(res.failures[0]["field"], field)
                    self.assertEqual(res.failures[0]["message"], "%s must be an exact non-empty str." % field)

    def test_13_all_field_failures_are_reported_together_in_order(self):
        res = create_voice_verification_plan(raw_result(raw_request(1, 2, 3)))
        self.assertEqual(res.codes(), [BAD_RID, BAD_PID, BAD_MODE])
        self.assertEqual([f["field"] for f in res.failures], list(FIELDS))
        res = create_voice_verification_plan(raw_result(raw_request("", "p", None)))
        self.assertEqual(res.codes(), [BAD_RID, BAD_MODE])
        res = create_voice_verification_plan(raw_result(raw_request("r", Str("p"), "m")))
        self.assertEqual(res.codes(), [BAD_PID])
        first = create_voice_verification_plan(raw_result(raw_request(b"", None, Str("x"))))
        self.assertEqual(first.codes(), [BAD_RID, BAD_PID, BAD_MODE])
        for _ in range(3):
            self.assertEqual(create_voice_verification_plan(raw_result(raw_request(b"", None, Str("x")))).to_dict(), first.to_dict())

    def test_14_a_field_read_that_raises_counts_as_invalid(self):
        def boom(self):
            raise RuntimeError("boom")

        for field, code in FIELD_CODES:
            with self.subTest(field=field):
                v = good()      # validated before the read is made to fail, so only the plan's own re-check can see it
                with mock.patch.object(VoiceVerificationRequest, field, property(boom)):
                    res = create_voice_verification_plan(v)
                self.assertEqual(res.codes(), [code])
                self.assertIsNone(res.plan)

    def test_15_a_raising_request_read_counts_as_invalid_request(self):
        v = good()
        boom = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
        with mock.patch.object(VoiceVerificationRequestValidationResult, "request", boom):
            res = create_voice_verification_plan(v)
        self.assertEqual(res.codes(), [INVALID_REQ])
        self.assertIsNone(res.plan)
        self.assertTrue(create_voice_verification_plan(v).ok)

    def test_16_codes_are_stable_unique_and_prefixed(self):
        self.assertEqual(vp.FAILURE_CODES, (INVALID_VR, FAILED, INVALID_REQ, BAD_RID, BAD_PID, BAD_MODE))
        self.assertEqual(len(set(vp.FAILURE_CODES)), 6)
        for code in vp.FAILURE_CODES:
            self.assertTrue(code.startswith(P))
        self.assertEqual(INVALID_VR, "VOICE_VERIFICATION_PLAN_INVALID_VALIDATION_RESULT")
        self.assertEqual(BAD_MODE, "VOICE_VERIFICATION_PLAN_INVALID_VERIFICATION_MODE")


class TestIdentityAndNonRetention(unittest.TestCase):
    def test_17_plan_holds_only_the_three_primitive_values(self):
        v = good()
        plan = create_voice_verification_plan(v).plan
        self.assertEqual(type(plan).__slots__, ("_request_id", "_profile_id", "_verification_mode"))
        for slot in type(plan).__slots__:
            self.assertIs(type(getattr(plan, slot)), str)
            self.assertIsNot(getattr(plan, slot), v)
            self.assertIsNot(getattr(plan, slot), v.request)
        self.assertIsNot(plan, v.request)
        self.assertNotEqual(plan, v.request)

    def test_18_result_does_not_retain_the_validation_result_or_request(self):
        v = good()
        res = create_voice_verification_plan(v)
        for slot in type(res).__slots__:
            self.assertIsNot(getattr(res, slot), v)
            self.assertIsNot(getattr(res, slot), v.request)
        bad = raw_result(raw_request(1, 2, 3))
        res = create_voice_verification_plan(bad)
        for slot in type(res).__slots__:
            self.assertIsNot(getattr(res, slot), bad)
            self.assertIsNot(getattr(res, slot), bad.request)
        self.assertIsNone(res.plan)
        failed = validate_voice_verification_request(raw_request(1, 2, 3))
        res = create_voice_verification_plan(failed)
        for slot in type(res).__slots__:
            self.assertIsNot(getattr(res, slot), failed)

    def test_19_nothing_in_the_plan_or_result_refers_to_the_input_objects(self):
        request = raw_request("r1", "p1", "m1")
        v = raw_result(request)
        res = create_voice_verification_plan(v)
        self.assertTrue(res.ok)
        for holder in (res, res.plan):
            referents = gc.get_referents(holder)
            self.assertFalse([r for r in referents if r is v or r is request], type(holder).__name__)
        self.assertEqual({type(r) for r in gc.get_referents(res.plan) if r is not VoiceVerificationPlan}, {str})
        self.assertEqual(res.plan.to_dict(), {"request_id": "r1", "profile_id": "p1", "verification_mode": "m1"})

    def test_20_dropping_the_sources_does_not_affect_the_plan(self):
        v = good()
        plan = create_voice_verification_plan(v).plan
        with self.assertRaises(AttributeError):
            v.request = None
        with self.assertRaises(AttributeError):
            v.request.request_id = "mutated"
        del v
        gc.collect()
        self.assertEqual(plan.to_dict(), data())

    def test_21_no_biometric_audio_or_embedding_attributes(self):
        plan = create_voice_verification_plan(good()).plan
        for word in ("audio", "recording", "embedding", "biometric", "sample", "voiceprint", "credential", "registry", "validation"):
            self.assertFalse([n for n in dir(plan) if word in n.lower()], word)


class TestObjectContracts(unittest.TestCase):
    def setUp(self):
        self.v = good()
        self.ok = create_voice_verification_plan(self.v)
        self.bad = create_voice_verification_plan(None)
        self.mal = create_voice_verification_plan(raw_result(raw_request(1, 2, 3)))

    def test_22_immutable(self):
        for obj in (self.ok, self.bad, self.mal, self.ok.plan):
            for name in ("ok", "plan", "failures", "request_id", "_plan", "_request_id", "extra"):
                with self.assertRaises(AttributeError):
                    setattr(obj, name, "x")
                with self.assertRaises(AttributeError):
                    delattr(obj, name)

    def test_23_direct_construction_and_subclassing_refused(self):
        with self.assertRaises(TypeError):
            VoiceVerificationPlan(None, "a", "b", "c")
        with self.assertRaises(TypeError):
            VoiceVerificationPlan(object(), "a", "b", "c")
        with self.assertRaises(TypeError):
            VoiceVerificationPlanResult(None, self.ok.plan, ())
        with self.assertRaises(TypeError):
            type("Sub", (VoiceVerificationPlan,), {})
        with self.assertRaises(TypeError):
            type("Sub", (VoiceVerificationPlanResult,), {})

    def test_24_equality_and_hash(self):
        again = create_voice_verification_plan(good())
        self.assertEqual(self.ok.plan, again.plan)
        self.assertEqual(hash(self.ok.plan), hash(again.plan))
        self.assertEqual(self.ok, again)
        self.assertEqual(hash(self.ok), hash(again))
        self.assertEqual(len({self.ok.plan, again.plan}), 1)
        for field in FIELDS:
            other = create_voice_verification_plan(good(**{field: "other"})).plan
            self.assertNotEqual(self.ok.plan, other)
        self.assertNotEqual(self.ok, self.bad)
        self.assertEqual(self.bad, create_voice_verification_plan(5))
        self.assertEqual(self.mal, create_voice_verification_plan(raw_result(raw_request(9, 9, 9))))
        for other in (self.ok.plan.to_dict(), None, 1, "x", self.v.request):
            self.assertNotEqual(self.ok.plan, other)
        self.assertEqual(self.ok.plan.__eq__(self.v.request), NotImplemented)
        self.assertEqual(self.ok.__eq__(self.ok.to_dict()), NotImplemented)

    def test_25_copy_deepcopy_and_pickle(self):
        for obj in (self.ok, self.bad, self.mal, self.ok.plan):
            self.assertIs(copy.copy(obj), obj)
            self.assertIs(copy.deepcopy(obj), obj)
            for proto in range(pickle.HIGHEST_PROTOCOL + 1):
                with self.assertRaises(TypeError):
                    pickle.dumps(obj, protocol=proto)

    def test_26_repr_is_stable(self):
        self.assertEqual(repr(self.ok.plan), "VoiceVerificationPlan(request_id='verify_1', profile_id='voice_1', verification_mode='standard')")
        self.assertEqual(repr(self.ok), "VoiceVerificationPlanResult(ok=True, codes=[])")
        self.assertEqual(repr(self.bad), "VoiceVerificationPlanResult(ok=False, codes=['%s'])" % INVALID_VR)

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
        self.assertEqual(list(self.ok.to_dict()), ["ok", "plan", "failures"])


class TestDeterminismAndSideEffects(unittest.TestCase):
    def test_28_repeated_conversion_is_deterministic(self):
        v = good()
        results = [create_voice_verification_plan(v) for _ in range(5)]
        for r in results[1:]:
            self.assertEqual(r, results[0])
            self.assertEqual(r.to_dict(), results[0].to_dict())
        for item in (None, raw_result(), raw_result(raw_request(1, 2, 3)), validate_voice_verification_request(None)):
            self.assertEqual(len({create_voice_verification_plan(item) for _ in range(3)}), 1)

    def test_29_no_side_effects(self):
        v, mal = good(), raw_result(raw_request(1, 2, 3))
        before_env, before_cwd, before_mods = dict(os.environ), os.getcwd(), set(sys.modules)
        before_tree = sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d)
        for _ in range(3):
            for item in (v, mal, None):
                create_voice_verification_plan(item)
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
        v, mal = good(), raw_result(raw_request(1, 2, 3))
        boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError("forbidden call"))
        with mock.patch.object(socket, "socket", boom), mock.patch.object(socket, "create_connection", boom), \
                mock.patch.object(subprocess, "Popen", boom), mock.patch.object(_os, "system", boom), mock.patch.object(builtins, "open", boom), \
                mock.patch.object(io, "open", boom), mock.patch.object(_os, "open", boom), mock.patch.object(_os, "listdir", boom), \
                mock.patch.object(sqlite3, "connect", boom):
            self.assertTrue(create_voice_verification_plan(v).ok)
            self.assertEqual(create_voice_verification_plan(mal).codes(), [BAD_RID, BAD_PID, BAD_MODE])
            self.assertEqual(create_voice_verification_plan(None).codes(), [INVALID_VR])


class TestBoundaries(unittest.TestCase):
    def _tree(self):
        with open(MODULE, encoding="utf-8") as fh:
            return ast.parse(fh.read())

    def test_31_module_imports_only_the_request_and_validation_result_types(self):
        imports = sorted((n.module, n.level, sorted(a.name for a in n.names)) for n in ast.walk(self._tree()) if isinstance(n, (ast.Import, ast.ImportFrom)))
        self.assertEqual(imports, [("voice_verification_request", 1, ["VoiceVerificationRequest"]),
                                   ("voice_verification_request_validator", 1, ["VoiceVerificationRequestValidationResult"])])

    def test_32_module_is_pure_and_has_no_module_state(self):
        tree = self._tree()
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "setattr", "globals", "vars"):
            self.assertNotIn(forbidden, calls)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("os", "sys", "io", "pathlib", "subprocess", "socket", "urllib", "http", "requests", "sqlite3", "random", "time", "datetime",
                     "anthropic", "openai", "numpy", "wave", "core", "agent", "planning", "web", "multimedia", "game_creation",
                     "create_voice_verification_request", "validate_voice_verification_request", "VoiceIdentityProfile", "VoiceIdentityProfileRegistry",
                     "VoiceEnrollmentRequest", "VoiceEnrollmentPlan", "audio", "embedding", "biometric"):
            self.assertNotIn(word, names, word)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.ImportFrom))
        for name, value in vars(vp).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_33_existing_voice_modules_are_unaware_of_the_plan_and_unchanged_in_contract(self):
        for name in sorted(os.listdir(os.path.join(PY_ROOT, "voice"))):
            if not name.endswith(".py") or name == "voice_verification_plan.py":
                continue
            with open(os.path.join(PY_ROOT, "voice", name), encoding="utf-8") as fh:
                text = fh.read()
            if name in ("voice_identity_profile.py", "voice_identity_profile_registry.py", "voice_enrollment_request.py", "voice_enrollment_result.py",
                        "voice_enrollment_result_validator.py", "voice_verification_request.py", "voice_verification_request_validator.py"):
                for token in ("voice_verification_plan", "VoiceVerificationPlan", "create_voice_verification_plan"):
                    self.assertNotIn(token, text, (name, token))
        self.assertEqual(vq.FIELDS, FIELDS)
        self.assertEqual(vv.FAILURE_CODES[0], "VOICE_VERIFICATION_REQUEST_VALIDATOR_INVALID_REQUEST")

    def test_34_no_module_outside_voice_references_it(self):
        tokens = ("voice_verification_plan", "VoiceVerificationPlan", "create_voice_verification_plan")
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

    def test_36_end_to_end_through_public_apis_only(self):
        created = create_voice_verification_request(data(request_id="e2e"))
        validated = validate_voice_verification_request(created.request)
        res = create_voice_verification_plan(validated)
        self.assertTrue(res.ok)
        self.assertEqual(res.plan.to_dict(), data(request_id="e2e"))
        self.assertEqual(create_voice_verification_plan(created).codes(), [INVALID_VR])      # the Prompt 798 carrier is not a validation result

    def test_37_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("VoiceVerificationPlan", "VoiceVerificationPlanResult", "create_voice_verification_plan", "VOICE_VERIFICATION_PLAN_",
                       "VoiceVerificationRequestValidationResult", "INVALID_VALIDATION_RESULT", "VALIDATION_FAILED", "INVALID_REQUEST",
                       "INVALID_VERIFICATION_MODE", "does NOT", "Prompt 801"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
