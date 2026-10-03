"""Prompt 799 - Section 10 voice verification request validator (`voice.voice_verification_request_validator`)."""
import ast
import copy
import hashlib
import os
import pickle
import sys
import unittest
from unittest import mock

from voice import voice_verification_request as vr
from voice import voice_verification_request_validator as vv
from voice.voice_verification_request import VoiceVerificationRequest, create_voice_verification_request
from voice.voice_verification_request_validator import VoiceVerificationRequestValidationResult, validate_voice_verification_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section10_voice_verification_request_validator_prompt799.md")
MODULE = os.path.join(PY_ROOT, "voice", "voice_verification_request_validator.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
P = "VOICE_VERIFICATION_REQUEST_VALIDATOR_"
INVALID_REQUEST, INVALID_REQUEST_ID, INVALID_PROFILE_ID, INVALID_VERIFICATION_MODE = (
    P + "INVALID_REQUEST", P + "INVALID_REQUEST_ID", P + "INVALID_PROFILE_ID", P + "INVALID_VERIFICATION_MODE")
FIELD_CODES = (("request_id", INVALID_REQUEST_ID), ("profile_id", INVALID_PROFILE_ID), ("verification_mode", INVALID_VERIFICATION_MODE))


class Str(str):
    pass


def valid(**over):
    data = {"request_id": "verify_1", "profile_id": "voice_1", "verification_mode": "STANDARD"}
    data.update(over)
    return data


def make(**over):
    res = create_voice_verification_request(valid(**over))
    assert res.ok, res.failures
    return res.request


def raw(request_id="r", profile_id="p", verification_mode="m"):
    """A VoiceVerificationRequest with arbitrary internals (only possible inside tests, via the contract module's private token)."""
    return VoiceVerificationRequest(vr._CREATE_TOKEN, request_id, profile_id, verification_mode)


class TestValidRequests(unittest.TestCase):
    def test_1_valid_request(self):
        obj = make()
        res = validate_voice_verification_request(obj)
        self.assertIs(type(res), VoiceVerificationRequestValidationResult)
        self.assertTrue(res.ok)
        self.assertEqual(res.failures, ())
        self.assertEqual(res.codes(), [])
        self.assertEqual(res.to_dict(), {"ok": True, "request": obj.to_dict(), "failures": []})

    def test_2_contents_are_not_interpreted(self):
        for mode in (" x ", "  ", "unknown-mode", "STANDARD", "standard", "ok\n", "\u00e9"):
            with self.subTest(mode=mode):
                obj = make(request_id=" r ", profile_id="PROFILE", verification_mode=mode)
                res = validate_voice_verification_request(obj)
                self.assertTrue(res.ok)
                self.assertEqual((res.request.request_id, res.request.verification_mode), (" r ", mode))

    def test_3_identity_is_preserved_on_success(self):
        for obj in (make(), make(verification_mode="whatever"), raw()):
            res = validate_voice_verification_request(obj)
            self.assertIs(res.request, obj)
            self.assertIs(validate_voice_verification_request(obj).request, obj)

    def test_4_request_is_unchanged(self):
        obj = make()
        before = (obj.to_dict(), hash(obj), repr(obj))
        validate_voice_verification_request(obj)
        validate_voice_verification_request(obj)
        self.assertEqual(before, (obj.to_dict(), hash(obj), repr(obj)))


class TestWrongTypesAndSpoofs(unittest.TestCase):
    def test_5_wrong_types_are_invalid_request(self):
        obj = make()
        for bad in (None, {}, [], "request", 5, True, object(), obj.to_dict(), VoiceVerificationRequest, (obj,),
                    create_voice_verification_request(valid()), validate_voice_verification_request(obj)):
            with self.subTest(bad=type(bad).__name__):
                res = validate_voice_verification_request(bad)
                self.assertFalse(res.ok)
                self.assertIsNone(res.request)
                self.assertEqual(res.codes(), [INVALID_REQUEST])
                self.assertEqual(res.to_dict(), {"ok": False, "request": None, "failures": [
                    {"code": INVALID_REQUEST, "field": "request", "message": "request must be exactly a VoiceVerificationRequest."}]})

    def test_6_look_alike_is_rejected_and_never_read(self):
        class Fake:
            def __getattr__(self, name):
                raise AssertionError("must not read " + name)

        res = validate_voice_verification_request(Fake())
        self.assertEqual(res.codes(), [INVALID_REQUEST])
        self.assertIsNone(res.request)

    def test_7_spoofed_class_attribute_is_rejected(self):
        class Spoof:
            __class__ = VoiceVerificationRequest
            request_id = profile_id = verification_mode = "x"

        spoof = Spoof()
        self.assertIsInstance(spoof, VoiceVerificationRequest)      # isinstance is fooled, the exact type check is not
        res = validate_voice_verification_request(spoof)
        self.assertEqual(res.codes(), [INVALID_REQUEST])
        self.assertIsNone(res.request)

    def test_8_subclassing_is_impossible_and_mock_is_rejected(self):
        with self.assertRaises(TypeError):
            type("Sub", (VoiceVerificationRequest,), {})
        m = mock.MagicMock(spec=VoiceVerificationRequest)
        self.assertEqual(validate_voice_verification_request(m).codes(), [INVALID_REQUEST])

    def test_9_never_raises_for_odd_inputs(self):
        class Boom:
            def __eq__(self, other):
                raise RuntimeError("boom")

            def __hash__(self):
                raise RuntimeError("boom")

            def __getattr__(self, name):
                raise RuntimeError("boom")

        for bad in (Boom(), float("nan"), b"x", {1: 2}, lambda: 1, type, 10 ** 100):
            res = validate_voice_verification_request(bad)
            self.assertEqual(res.codes(), [INVALID_REQUEST])
            self.assertIsNone(res.request)
            hash(res)


class TestFieldFailures(unittest.TestCase):
    def test_10_each_field_rejects_wrong_types_and_empty(self):
        for index, (field, code) in enumerate(FIELD_CODES):
            for bad in (None, 5, True, b"x", ("a",), Str("abc"), Str(""), ""):
                with self.subTest(field=field, bad=repr(bad)):
                    args = ["r", "p", "m"]
                    args[index] = bad
                    res = validate_voice_verification_request(raw(*args))
                    self.assertFalse(res.ok)
                    self.assertIsNone(res.request)
                    self.assertEqual(res.codes(), [code])
                    self.assertEqual(res.failures[0]["field"], field)
                    self.assertEqual(res.failures[0]["message"], ("%s must be an exact non-empty str." % field))

    def test_11_a_field_read_that_raises_counts_as_invalid(self):
        def boom(self):
            raise RuntimeError("boom")

        for field, code in FIELD_CODES:
            with self.subTest(field=field):
                with mock.patch.object(VoiceVerificationRequest, field, property(boom)):
                    res = validate_voice_verification_request(make())
                self.assertEqual(res.codes(), [code])
                self.assertIsNone(res.request)

    def test_12_all_failures_are_reported_together_in_field_order(self):
        res = validate_voice_verification_request(raw(1, 2, 3))
        self.assertEqual(res.codes(), [c for _f, c in FIELD_CODES])
        self.assertEqual([f["field"] for f in res.failures], [f for f, _c in FIELD_CODES])
        self.assertIsNone(res.request)
        self.assertIsNone(res.to_dict()["request"])
        res = validate_voice_verification_request(raw("", "p", None))
        self.assertEqual(res.codes(), [INVALID_REQUEST_ID, INVALID_VERIFICATION_MODE])
        res = validate_voice_verification_request(raw("r", Str("p"), ""))
        self.assertEqual(res.codes(), [INVALID_PROFILE_ID, INVALID_VERIFICATION_MODE])
        res = validate_voice_verification_request(raw(None, "p", "m"))
        self.assertEqual(res.codes(), [INVALID_REQUEST_ID])

    def test_13_failure_ordering_is_deterministic(self):
        bad = raw(b"", None, Str("x"))
        first = validate_voice_verification_request(bad)
        for _ in range(5):
            again = validate_voice_verification_request(bad)
            self.assertEqual(again.codes(), first.codes())
            self.assertEqual(again.failures, first.failures)
            self.assertEqual(again.to_dict(), first.to_dict())
        self.assertEqual(first.codes(), [INVALID_REQUEST_ID, INVALID_PROFILE_ID, INVALID_VERIFICATION_MODE])

    def test_14_request_is_none_on_every_failure_and_malformed_object_never_retained(self):
        obj = raw(5, ["unhashable"], 3)
        res = validate_voice_verification_request(obj)
        for slot in type(res).__slots__:
            self.assertIsNot(getattr(res, slot), obj)
        self.assertIsNone(res.request)
        self.assertIsInstance(hash(res), int)
        self.assertEqual(res, validate_voice_verification_request(raw(5, ["unhashable"], 3)))

    def test_15_codes_are_stable_unique_and_prefixed(self):
        self.assertEqual(vv.FAILURE_CODES, (INVALID_REQUEST, INVALID_REQUEST_ID, INVALID_PROFILE_ID, INVALID_VERIFICATION_MODE))
        self.assertEqual(len(set(vv.FAILURE_CODES)), 4)
        for code in vv.FAILURE_CODES:
            self.assertTrue(code.startswith(P))
        self.assertEqual(INVALID_REQUEST, "VOICE_VERIFICATION_REQUEST_VALIDATOR_INVALID_REQUEST")


class TestResultContract(unittest.TestCase):
    def setUp(self):
        self.obj = make()
        self.ok = validate_voice_verification_request(self.obj)
        self.bad = validate_voice_verification_request(None)
        self.mal = validate_voice_verification_request(raw(1, 2, 3))

    def test_16_immutable(self):
        for o in (self.ok, self.bad, self.mal):
            for name in ("ok", "request", "failures", "_request", "_failures", "extra"):
                with self.assertRaises(AttributeError):
                    setattr(o, name, "x")
                with self.assertRaises(AttributeError):
                    delattr(o, name)
        self.assertIs(self.ok.request, self.obj)

    def test_17_direct_construction_and_subclassing_refused(self):
        with self.assertRaises(TypeError):
            VoiceVerificationRequestValidationResult(None, self.obj, ())
        with self.assertRaises(TypeError):
            VoiceVerificationRequestValidationResult(object(), None, [])
        with self.assertRaises(TypeError):
            type("Sub", (VoiceVerificationRequestValidationResult,), {})

    def test_18_to_dict_is_fresh_plain_data(self):
        for res in (self.ok, self.bad, self.mal):
            a, b = res.to_dict(), res.to_dict()
            self.assertEqual(a, b)
            self.assertIsNot(a, b)
            self.assertIsNot(a["failures"], b["failures"])
            for fa, fb in zip(a["failures"], b["failures"]):
                self.assertIsNot(fa, fb)
            a["ok"] = "X"
            a["failures"].append({"code": "x"})
            for f in res.failures:
                f["code"] = "mutated"
            self.assertEqual(res.to_dict(), b)
        a, b = self.ok.to_dict(), self.ok.to_dict()
        self.assertIsNot(a["request"], b["request"])
        a["request"]["request_id"] = "mutated"
        self.assertEqual(self.ok.to_dict(), {"ok": True, "request": self.obj.to_dict(), "failures": []})
        self.assertEqual(self.obj.request_id, "verify_1")
        self.assertEqual(list(self.ok.to_dict()), ["ok", "request", "failures"])
        self.assertEqual(self.mal.to_dict()["failures"][0], {
            "code": INVALID_REQUEST_ID, "field": "request_id", "message": "request_id must be an exact non-empty str."})
        self.assertIsInstance(self.bad.failures, tuple)

    def test_19_codes_returns_fresh_list(self):
        self.assertEqual(self.ok.codes(), [])
        self.assertEqual(self.bad.codes(), [INVALID_REQUEST])
        self.assertEqual(self.mal.codes(), [c for _f, c in FIELD_CODES])
        c = self.mal.codes()
        c.append("x")
        self.assertEqual(self.mal.codes(), [code for _f, code in FIELD_CODES])
        self.assertIsNot(self.bad.codes(), self.bad.codes())

    def test_20_equality_and_hash(self):
        again = validate_voice_verification_request(make())
        self.assertEqual(self.ok, again)
        self.assertEqual(hash(self.ok), hash(again))
        self.assertEqual(len({self.ok, again}), 1)
        self.assertEqual(self.bad, validate_voice_verification_request(5))
        self.assertEqual(self.mal, validate_voice_verification_request(raw(9, 9, 9)))
        self.assertNotEqual(self.ok, self.bad)
        self.assertNotEqual(self.bad, self.mal)
        self.assertNotEqual(self.ok, validate_voice_verification_request(make(verification_mode="OTHER")))
        for other in (self.ok.to_dict(), None, 1, "x", self.obj):
            self.assertNotEqual(self.ok, other)
        self.assertEqual(self.ok.__eq__(self.ok.to_dict()), NotImplemented)

    def test_21_copy_deepcopy_and_pickle(self):
        for o in (self.ok, self.bad, self.mal):
            for c in (copy.copy(o), copy.deepcopy(o), copy.deepcopy({"k": [o]})["k"][0]):
                self.assertEqual(c, o)
                self.assertEqual(c.to_dict(), o.to_dict())
            for proto in range(pickle.HIGHEST_PROTOCOL + 1):
                with self.assertRaises(TypeError):
                    pickle.dumps(o, protocol=proto)
        self.assertIs(copy.deepcopy(self.ok).request, self.obj)

    def test_22_repr_and_public_surface(self):
        self.assertEqual(repr(self.ok), "VoiceVerificationRequestValidationResult(ok=True, codes=[])")
        self.assertEqual(repr(self.bad), "VoiceVerificationRequestValidationResult(ok=False, codes=['%s'])" % INVALID_REQUEST)
        for o in (self.ok, self.bad, self.mal):
            self.assertEqual({n for n in dir(o) if not n.startswith("_")}, {"ok", "request", "failures", "codes", "to_dict"})


class TestDeterminismAndSideEffects(unittest.TestCase):
    def test_23_repeated_validation_is_deterministic(self):
        obj = make()
        results = [validate_voice_verification_request(obj) for _ in range(5)]
        for r in results[1:]:
            self.assertEqual(r, results[0])
            self.assertEqual(r.to_dict(), results[0].to_dict())
            self.assertIs(r.request, obj)
        for item in (None, raw(1, 2, 3), raw("", "", "")):
            self.assertEqual(len({validate_voice_verification_request(item) for _ in range(3)}), 1)

    def test_24_no_side_effects(self):
        obj, mal = make(), raw(1, 2, 3)
        before_env, before_cwd, before_mods = dict(os.environ), os.getcwd(), set(sys.modules)
        before_tree = sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d)
        for _ in range(3):
            for item in (obj, mal, None):
                validate_voice_verification_request(item)
        self.assertEqual(dict(os.environ), before_env)
        self.assertEqual(os.getcwd(), before_cwd)
        self.assertEqual(set(sys.modules), before_mods)
        self.assertEqual(sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d), before_tree)
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)

    def test_25_no_io_network_subprocess_or_persistence_calls(self):
        import builtins
        import io
        import os as _os
        import socket
        import sqlite3
        import subprocess
        obj, mal = make(), raw(1, 2, 3)
        boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError("forbidden call"))
        with mock.patch.object(socket, "socket", boom), mock.patch.object(socket, "create_connection", boom), \
                mock.patch.object(subprocess, "Popen", boom), mock.patch.object(_os, "system", boom), mock.patch.object(builtins, "open", boom), \
                mock.patch.object(io, "open", boom), mock.patch.object(_os, "open", boom), mock.patch.object(_os, "listdir", boom), \
                mock.patch.object(sqlite3, "connect", boom):
            self.assertTrue(validate_voice_verification_request(obj).ok)
            self.assertEqual(validate_voice_verification_request(mal).codes(), [c for _f, c in FIELD_CODES])
            self.assertEqual(validate_voice_verification_request(None).codes(), [INVALID_REQUEST])


class TestBoundaries(unittest.TestCase):
    def _tree(self):
        with open(MODULE, encoding="utf-8") as fh:
            return ast.parse(fh.read())

    def test_26_module_imports_only_the_request_type(self):
        imports = [(n.module, n.level, sorted(a.name for a in n.names)) for n in ast.walk(self._tree()) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(imports, [("voice_verification_request", 1, ["VoiceVerificationRequest"])])

    def test_27_module_is_pure_and_has_no_module_state(self):
        tree = self._tree()
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "setattr", "globals", "vars"):
            self.assertNotIn(forbidden, calls)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("os", "sys", "io", "pathlib", "subprocess", "socket", "urllib", "http", "requests", "sqlite3", "random", "time", "datetime",
                     "anthropic", "openai", "numpy", "wave", "core", "agent", "planning", "web", "multimedia", "game_creation",
                     "VoiceEnrollmentRequest", "VoiceIdentityProfile", "create_voice_verification_request", "audio", "embedding", "biometric"):
            self.assertNotIn(word, names, word)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.ImportFrom))
        for name, value in vars(vv).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_28_existing_voice_contracts_are_unaware_of_the_validator(self):
        for name in ("voice_identity_profile.py", "voice_identity_profile_registry.py", "voice_enrollment_request.py", "voice_enrollment_result.py",
                     "voice_verification_request.py"):
            with open(os.path.join(PY_ROOT, "voice", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("voice_verification_request_validator", "VoiceVerificationRequestValidationResult", "validate_voice_verification_request"):
                self.assertNotIn(token, text, (name, token))
        self.assertEqual(vr.FIELDS, ("request_id", "profile_id", "verification_mode"))
        self.assertEqual(len(vr.FAILURE_CODES), 6)

    def test_29_no_module_outside_voice_references_it(self):
        tokens = ("voice_verification_request_validator", "VoiceVerificationRequestValidationResult", "validate_voice_verification_request")
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

    def test_30_voice_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "voice")) if f != "__pycache__"),
                         ["__init__.py", "voice_enrollment_batch.py", "voice_enrollment_batch_summary.py", "voice_enrollment_dispatcher.py", "voice_enrollment_executor.py", "voice_enrollment_pipeline.py", "voice_enrollment_plan.py", "voice_enrollment_request.py", "voice_enrollment_result.py", "voice_enrollment_result_validator.py",
                          "voice_identity_profile.py", "voice_identity_profile_registry.py", "voice_verification_authorization.py", "voice_verification_batch.py", "voice_verification_batch_summary.py", "voice_verification_decision.py", "voice_verification_dispatcher.py", "voice_verification_execution.py", "voice_verification_execution_request.py", "voice_verification_executor.py", "voice_verification_handoff.py", "voice_verification_pipeline.py", "voice_verification_plan.py", "voice_verification_profile_resolver.py", "voice_verification_registry.py", "voice_verification_request.py", "voice_verification_request_validator.py", "voice_verification_result.py"])
        with open(os.path.join(PY_ROOT, "voice", "__init__.py"), "rb") as fh:
            self.assertEqual(fh.read(), b"")

    def test_31_end_to_end_through_public_apis_only(self):
        created = create_voice_verification_request(valid(request_id="e2e"))
        res = validate_voice_verification_request(created.request)
        self.assertTrue(res.ok)
        self.assertIs(res.request, created.request)
        self.assertFalse(validate_voice_verification_request(created).ok)      # the factory's carrier is not a request

    def test_32_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("VoiceVerificationRequestValidationResult", "validate_voice_verification_request", "VOICE_VERIFICATION_REQUEST_VALIDATOR_",
                       "INVALID_REQUEST", "INVALID_REQUEST_ID", "INVALID_PROFILE_ID", "INVALID_VERIFICATION_MODE", "does NOT", "Prompt 800"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
