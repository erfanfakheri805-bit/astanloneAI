"""Prompt 791 - Section 10 voice enrollment result validator (`voice.voice_enrollment_result_validator`)."""
import ast
import copy
import hashlib
import os
import pickle
import sys
import unittest
from unittest import mock

from voice import voice_enrollment_result as vr
from voice import voice_enrollment_result_validator as vv
from voice.voice_enrollment_result import VoiceEnrollmentResult, create_voice_enrollment_result
from voice.voice_enrollment_result_validator import VoiceEnrollmentResultValidationResult, validate_voice_enrollment_result

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section10_voice_enrollment_result_validator_prompt791.md")
MODULE = os.path.join(PY_ROOT, "voice", "voice_enrollment_result_validator.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
P = "VOICE_ENROLLMENT_RESULT_VALIDATOR_"
INVALID_RESULT, INVALID_REQUEST_ID, INVALID_PROFILE_ID, INVALID_STATUS, INVALID_CODE, INVALID_METADATA = (
    P + "INVALID_RESULT", P + "INVALID_REQUEST_ID", P + "INVALID_PROFILE_ID", P + "INVALID_STATUS", P + "INVALID_CODE", P + "INVALID_METADATA")
FIELD_CODES = (("request_id", INVALID_REQUEST_ID), ("profile_id", INVALID_PROFILE_ID), ("status", INVALID_STATUS), ("code", INVALID_CODE),
               ("metadata", INVALID_METADATA))


class Str(str):
    pass


class Dict(dict):
    pass


def valid(**over):
    data = {"request_id": "enroll_1", "profile_id": "voice_1", "status": "COMPLETED", "code": "OK", "metadata": {"step": 1}}
    data.update(over)
    return data


def make(**over):
    res = create_voice_enrollment_result(valid(**over))
    assert res.ok, res.failures
    return res.result


def raw(request_id="r", profile_id="p", status="s", code="c", items=None):
    """A VoiceEnrollmentResult with arbitrary internals (only possible inside tests, via the contract module's private token)."""
    return VoiceEnrollmentResult(vr._CREATE_TOKEN, request_id, profile_id, status, code, items)


class TestValidResults(unittest.TestCase):
    def test_1_valid_result_with_metadata(self):
        obj = make()
        res = validate_voice_enrollment_result(obj)
        self.assertIs(type(res), VoiceEnrollmentResultValidationResult)
        self.assertTrue(res.ok)
        self.assertEqual(res.failures, ())
        self.assertEqual(res.codes(), [])
        self.assertEqual(res.to_dict(), {"ok": True, "result": obj.to_dict(), "failures": []})

    def test_2_valid_result_with_metadata_none_and_empty_dict(self):
        for meta in (None, {}):
            with self.subTest(metadata=meta):
                obj = make(metadata=meta)
                res = validate_voice_enrollment_result(obj)
                self.assertTrue(res.ok)
                self.assertIs(res.result, obj)
                self.assertEqual(res.to_dict()["result"]["metadata"], meta)

    def test_3_contents_are_not_interpreted(self):
        weird = {1: object(), "": [], ("t",): {"nested": {1, 2}}, "k": float("nan")}
        obj = make(request_id=" x ", profile_id="PROFILE", status="  ", code="ok\n", metadata=weird)
        res = validate_voice_enrollment_result(obj)
        self.assertTrue(res.ok)
        self.assertEqual((res.result.request_id, res.result.status, res.result.code), (" x ", "  ", "ok\n"))
        self.assertTrue(validate_voice_enrollment_result(raw(items=(("k", object()),))).ok)

    def test_4_identity_is_preserved_on_success(self):
        for obj in (make(), make(metadata=None), make(status="whatever")):
            res = validate_voice_enrollment_result(obj)
            self.assertIs(res.result, obj)
            self.assertIs(validate_voice_enrollment_result(obj).result, obj)

    def test_5_result_is_unchanged(self):
        obj = make()
        before = (obj.to_dict(), hash(obj), repr(obj))
        validate_voice_enrollment_result(obj)
        validate_voice_enrollment_result(obj)
        self.assertEqual(before, (obj.to_dict(), hash(obj), repr(obj)))


class TestWrongTypesAndSpoofs(unittest.TestCase):
    def test_6_wrong_types_are_invalid_result(self):
        obj = make()
        for bad in (None, {}, [], "result", 5, True, object(), obj.to_dict(), VoiceEnrollmentResult, (obj,), create_voice_enrollment_result(valid()),
                    validate_voice_enrollment_result(obj)):
            with self.subTest(bad=type(bad).__name__):
                res = validate_voice_enrollment_result(bad)
                self.assertFalse(res.ok)
                self.assertIsNone(res.result)
                self.assertEqual(res.codes(), [INVALID_RESULT])
                self.assertEqual(res.to_dict(), {"ok": False, "result": None, "failures": [
                    {"code": INVALID_RESULT, "field": "result", "message": "result must be exactly a VoiceEnrollmentResult."}]})

    def test_7_look_alike_is_rejected_and_never_read(self):
        class Fake:
            def __getattr__(self, name):
                raise AssertionError("must not read " + name)

        res = validate_voice_enrollment_result(Fake())
        self.assertEqual(res.codes(), [INVALID_RESULT])
        self.assertIsNone(res.result)

    def test_8_spoofed_class_attribute_is_rejected(self):
        class Spoof:
            __class__ = VoiceEnrollmentResult
            request_id = profile_id = status = code = "x"
            metadata = None

        spoof = Spoof()
        self.assertIsInstance(spoof, VoiceEnrollmentResult)      # isinstance is fooled, the exact type check is not
        res = validate_voice_enrollment_result(spoof)
        self.assertEqual(res.codes(), [INVALID_RESULT])
        self.assertIsNone(res.result)

    def test_9_subclassing_is_impossible_and_duck_typed_mock_is_rejected(self):
        with self.assertRaises(TypeError):
            type("Sub", (VoiceEnrollmentResult,), {})
        m = mock.MagicMock(spec=VoiceEnrollmentResult)
        self.assertEqual(validate_voice_enrollment_result(m).codes(), [INVALID_RESULT])

    def test_10_never_raises_for_odd_inputs(self):
        class Boom:
            def __eq__(self, other):
                raise RuntimeError("boom")

            def __hash__(self):
                raise RuntimeError("boom")

            def __getattr__(self, name):
                raise RuntimeError("boom")

        for bad in (Boom(), float("nan"), b"x", {1: 2}, lambda: 1, type, 10 ** 100):
            res = validate_voice_enrollment_result(bad)
            self.assertEqual(res.codes(), [INVALID_RESULT])
            self.assertIsNone(res.result)
            hash(res)


class TestFieldFailures(unittest.TestCase):
    def test_11_each_string_field_rejects_wrong_types_and_empty(self):
        for index, (field, code) in enumerate(FIELD_CODES[:4]):
            for bad in (None, 5, True, b"x", ("a",), Str("abc"), Str(""), ""):
                with self.subTest(field=field, bad=repr(bad)):
                    args = ["r", "p", "s", "c"]
                    args[index] = bad
                    res = validate_voice_enrollment_result(raw(*args))
                    self.assertFalse(res.ok)
                    self.assertIsNone(res.result)
                    self.assertEqual(res.codes(), [code])
                    self.assertEqual(res.failures[0]["field"], field)

    def test_12_metadata_rejects_non_none_non_dict(self):
        obj = make()
        for bad in ([], (), "m", 5, Dict(a=1), [("a", 1)], {1, 2}, True):
            with self.subTest(metadata=type(bad).__name__):
                with mock.patch.object(VoiceEnrollmentResult, "metadata", property(lambda self, _b=bad: _b)):
                    res = validate_voice_enrollment_result(obj)
                self.assertFalse(res.ok)
                self.assertIsNone(res.result)
                self.assertEqual(res.codes(), [INVALID_METADATA])
                self.assertEqual(res.failures[0]["field"], "metadata")

    def test_13_a_field_read_that_raises_counts_as_invalid(self):
        for bad_items in (5, "abc", (1, 2), object()):
            with self.subTest(items=repr(bad_items)):
                res = validate_voice_enrollment_result(raw(items=bad_items))
                self.assertEqual(res.codes(), [INVALID_METADATA])
                self.assertIsNone(res.result)

        def boom(self):
            raise RuntimeError("boom")

        for field, code in FIELD_CODES[:4]:
            with self.subTest(field=field):
                with mock.patch.object(VoiceEnrollmentResult, field, property(boom)):
                    res = validate_voice_enrollment_result(make())
                self.assertEqual(res.codes(), [code])

    def test_14_all_failures_are_reported_together_in_field_order(self):
        res = validate_voice_enrollment_result(raw(1, 2, 3, 4, 5))
        self.assertEqual(res.codes(), [c for _f, c in FIELD_CODES])
        self.assertEqual([f["field"] for f in res.failures], [f for f, _c in FIELD_CODES])
        self.assertIsNone(res.result)
        self.assertIsNone(res.to_dict()["result"])
        res = validate_voice_enrollment_result(raw("", "p", None, "c", 3))
        self.assertEqual(res.codes(), [INVALID_REQUEST_ID, INVALID_STATUS, INVALID_METADATA])
        res = validate_voice_enrollment_result(raw("r", Str("p"), "s", "", None))
        self.assertEqual(res.codes(), [INVALID_PROFILE_ID, INVALID_CODE])

    def test_15_malformed_result_is_never_retained(self):
        obj = raw(5, ["unhashable"], 3, None, 7)
        res = validate_voice_enrollment_result(obj)
        for slot in type(res).__slots__:
            self.assertIsNot(getattr(res, slot), obj)
        self.assertIsNone(res.result)
        self.assertIsInstance(hash(res), int)
        self.assertEqual(res, validate_voice_enrollment_result(raw(5, ["unhashable"], 3, None, 7)))

    def test_16_codes_are_stable_unique_and_prefixed(self):
        self.assertEqual(vv.FAILURE_CODES, (INVALID_RESULT, INVALID_REQUEST_ID, INVALID_PROFILE_ID, INVALID_STATUS, INVALID_CODE, INVALID_METADATA))
        self.assertEqual(len(set(vv.FAILURE_CODES)), 6)
        for code in vv.FAILURE_CODES:
            self.assertTrue(code.startswith(P))
        self.assertEqual(INVALID_RESULT, "VOICE_ENROLLMENT_RESULT_VALIDATOR_INVALID_RESULT")


class TestResultContract(unittest.TestCase):
    def setUp(self):
        self.obj = make()
        self.ok = validate_voice_enrollment_result(self.obj)
        self.bad = validate_voice_enrollment_result(None)
        self.mal = validate_voice_enrollment_result(raw(1, 2, 3, 4, 5))

    def test_17_immutable(self):
        for o in (self.ok, self.bad, self.mal):
            for name in ("ok", "result", "failures", "_result", "_failures", "extra"):
                with self.assertRaises(AttributeError):
                    setattr(o, name, "x")
                with self.assertRaises(AttributeError):
                    delattr(o, name)
        self.assertIs(self.ok.result, self.obj)

    def test_18_direct_construction_and_subclassing_refused(self):
        with self.assertRaises(TypeError):
            VoiceEnrollmentResultValidationResult(None, self.obj, ())
        with self.assertRaises(TypeError):
            VoiceEnrollmentResultValidationResult(object(), None, [])
        with self.assertRaises(TypeError):
            type("Sub", (VoiceEnrollmentResultValidationResult,), {})

    def test_19_fresh_dict_and_failures(self):
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
        self.assertIsNot(a["result"], b["result"])
        self.assertIsNot(a["result"]["metadata"], b["result"]["metadata"])
        a["result"]["metadata"]["step"] = "mutated"
        self.assertEqual(self.ok.to_dict(), {"ok": True, "result": self.obj.to_dict(), "failures": []})
        self.assertEqual(self.obj.metadata, {"step": 1})
        self.assertIsInstance(self.bad.failures, tuple)
        self.assertIsNot(self.bad.codes(), self.bad.codes())

    def test_20_equality_and_hash(self):
        again = validate_voice_enrollment_result(make())
        self.assertEqual(self.ok, again)
        self.assertEqual(hash(self.ok), hash(again))
        self.assertEqual(len({self.ok, again}), 1)
        self.assertEqual(self.bad, validate_voice_enrollment_result(5))
        self.assertEqual(self.mal, validate_voice_enrollment_result(raw(9, 9, 9, 9, 9)))
        self.assertNotEqual(self.ok, self.bad)
        self.assertNotEqual(self.bad, self.mal)
        self.assertNotEqual(self.ok, validate_voice_enrollment_result(make(status="OTHER")))
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
        self.assertIs(copy.deepcopy(self.ok).result, self.obj)

    def test_22_repr_and_public_surface(self):
        self.assertEqual(repr(self.ok), "VoiceEnrollmentResultValidationResult(ok=True, codes=[])")
        self.assertEqual(repr(self.bad), "VoiceEnrollmentResultValidationResult(ok=False, codes=['%s'])" % INVALID_RESULT)
        for o in (self.ok, self.bad, self.mal):
            self.assertEqual({n for n in dir(o) if not n.startswith("_")}, {"ok", "result", "failures", "codes", "to_dict"})


class TestDeterminismAndSideEffects(unittest.TestCase):
    def test_23_repeated_validation_is_deterministic(self):
        obj = make()
        results = [validate_voice_enrollment_result(obj) for _ in range(5)]
        for r in results[1:]:
            self.assertEqual(r, results[0])
            self.assertEqual(r.to_dict(), results[0].to_dict())
            self.assertIs(r.result, obj)
        for item in (None, raw(1, 2, 3, 4, 5), raw("", "", "", "", [])):
            self.assertEqual(len({validate_voice_enrollment_result(item) for _ in range(3)}), 1)
            self.assertEqual(validate_voice_enrollment_result(item).codes(), validate_voice_enrollment_result(item).codes())

    def test_24_no_side_effects(self):
        obj, mal = make(), raw(1, 2, 3, 4, 5)
        before_env, before_cwd, before_mods = dict(os.environ), os.getcwd(), set(sys.modules)
        before_tree = sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d)
        for _ in range(3):
            for item in (obj, mal, None):
                validate_voice_enrollment_result(item)
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
        obj, mal = make(), raw(1, 2, 3, 4, 5)
        boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError("forbidden call"))
        with mock.patch.object(socket, "socket", boom), mock.patch.object(socket, "create_connection", boom), \
                mock.patch.object(subprocess, "Popen", boom), mock.patch.object(_os, "system", boom), mock.patch.object(builtins, "open", boom), \
                mock.patch.object(io, "open", boom), mock.patch.object(_os, "open", boom), mock.patch.object(_os, "listdir", boom), \
                mock.patch.object(sqlite3, "connect", boom):
            self.assertTrue(validate_voice_enrollment_result(obj).ok)
            self.assertEqual(validate_voice_enrollment_result(mal).codes(), [c for _f, c in FIELD_CODES])
            self.assertEqual(validate_voice_enrollment_result(None).codes(), [INVALID_RESULT])


class TestBoundaries(unittest.TestCase):
    def _tree(self):
        with open(MODULE, encoding="utf-8") as fh:
            return ast.parse(fh.read())

    def test_26_module_imports_only_the_result_type(self):
        imports = [(n.module, n.level, sorted(a.name for a in n.names)) for n in ast.walk(self._tree()) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(imports, [("voice_enrollment_result", 1, ["VoiceEnrollmentResult"])])

    def test_27_module_is_pure_and_has_no_module_state(self):
        tree = self._tree()
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "setattr", "globals", "vars"):
            self.assertNotIn(forbidden, calls)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("os", "sys", "io", "pathlib", "subprocess", "socket", "urllib", "http", "requests", "sqlite3", "random", "time", "datetime",
                     "anthropic", "openai", "numpy", "wave", "core", "agent", "planning", "web", "multimedia", "game_creation",
                     "VoiceEnrollmentRequest", "VoiceIdentityProfile", "create_voice_enrollment_result", "_items", "_request_id"):
            self.assertNotIn(word, names, word)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.ImportFrom))
        for name, value in vars(vv).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_28_existing_voice_contracts_are_unaware_of_the_validator(self):
        for name in ("voice_identity_profile.py", "voice_identity_profile_registry.py", "voice_enrollment_request.py", "voice_enrollment_result.py"):
            with open(os.path.join(PY_ROOT, "voice", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("voice_enrollment_result_validator", "VoiceEnrollmentResultValidationResult", "validate_voice_enrollment_result"):
                self.assertNotIn(token, text, (name, token))
        self.assertEqual(vr.FIELDS, ("request_id", "profile_id", "status", "code", "metadata"))
        self.assertEqual(len(vr.FAILURE_CODES), 8)

    def test_29_no_module_outside_voice_references_it(self):
        tokens = ("voice_enrollment_result_validator", "VoiceEnrollmentResultValidationResult", "validate_voice_enrollment_result")
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
        created = create_voice_enrollment_result(valid(request_id="e2e", metadata=None))
        res = validate_voice_enrollment_result(created.result)
        self.assertTrue(res.ok)
        self.assertIs(res.result, created.result)
        self.assertFalse(validate_voice_enrollment_result(created).ok)      # the factory's carrier is not a result

    def test_32_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("VoiceEnrollmentResultValidationResult", "validate_voice_enrollment_result", "VOICE_ENROLLMENT_RESULT_VALIDATOR_", "INVALID_RESULT",
                       "INVALID_REQUEST_ID", "INVALID_PROFILE_ID", "INVALID_STATUS", "INVALID_CODE", "INVALID_METADATA", "does NOT", "Prompt 792"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
