"""Prompt 793 - Section 10 voice enrollment executor (`voice.voice_enrollment_executor`)."""
import ast
import copy
import gc
import hashlib
import os
import pickle
import sys
import unittest
from unittest import mock

from voice import voice_enrollment_executor as ve
from voice import voice_enrollment_plan as vp
from voice.voice_enrollment_executor import execute_voice_enrollment_plan
from voice.voice_enrollment_plan import VoiceEnrollmentPlan, create_voice_enrollment_plan
from voice.voice_enrollment_request import create_voice_enrollment_request
from voice.voice_enrollment_result import VoiceEnrollmentResult
from voice.voice_enrollment_result_validator import validate_voice_enrollment_result

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section10_voice_enrollment_executor_prompt793.md")
MODULE = os.path.join(PY_ROOT, "voice", "voice_enrollment_executor.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
INVALID_PLAN = "VOICE_ENROLLMENT_EXECUTOR_INVALID_PLAN"
NOT_IMPL = "VOICE_ENROLLMENT_EXECUTOR_NOT_IMPLEMENTED"
FIELDS = ("request_id", "profile_id", "enrollment_mode")


class Str(str):
    pass


def make_plan(**over):
    d = {"request_id": "enroll_1", "profile_id": "voice_1", "enrollment_mode": "standard"}
    d.update(over)
    req = create_voice_enrollment_request(d)
    assert req.ok, req.failures
    res = create_voice_enrollment_plan(req)
    assert res.ok, res.codes()
    return res.plan


def raw_plan(rid="r", pid="p", mode="m"):
    """A VoiceEnrollmentPlan with arbitrary internals (only possible inside tests, via the plan module's private token)."""
    return VoiceEnrollmentPlan(vp._CREATE_TOKEN, rid, pid, mode)


class TestValidPlans(unittest.TestCase):
    def test_1_valid_plan_gives_not_implemented(self):
        res = execute_voice_enrollment_plan(make_plan())
        self.assertIs(type(res), VoiceEnrollmentResult)
        self.assertEqual((res.status, res.code), ("NOT_IMPLEMENTED", NOT_IMPL))
        self.assertEqual(res.to_dict(), {"request_id": "enroll_1", "profile_id": "voice_1", "status": "NOT_IMPLEMENTED", "code": NOT_IMPL,
                                         "metadata": {"request_id": "enroll_1", "profile_id": "voice_1", "enrollment_mode": "standard"}})

    def test_2_metadata_contains_only_the_three_plan_values_in_order(self):
        meta = execute_voice_enrollment_plan(make_plan(request_id="R-9", profile_id="P-9", enrollment_mode="quick")).metadata
        self.assertIs(type(meta), dict)
        self.assertEqual(list(meta), list(FIELDS))
        self.assertEqual(meta, {"request_id": "R-9", "profile_id": "P-9", "enrollment_mode": "quick"})

    def test_3_values_are_copied_exactly_with_identity_and_no_normalization(self):
        rid, pid, mode = " Req ", "PROFILE\n", "  Free Text  "
        plan = make_plan(request_id=rid, profile_id=pid, enrollment_mode=mode)
        res = execute_voice_enrollment_plan(plan)
        for key, source in zip(FIELDS, (plan.request_id, plan.profile_id, plan.enrollment_mode)):
            self.assertIs(res.metadata[key], source)
        self.assertIs(res.request_id, plan.request_id)
        self.assertIs(res.profile_id, plan.profile_id)
        self.assertEqual(res.metadata, {"request_id": rid, "profile_id": pid, "enrollment_mode": mode})

    def test_4_enrollment_mode_is_free_text_and_not_interpreted(self):
        for mode in ("standard", "ANYTHING", "record_now", "x" * 500, "\u062a\u0633\u062a"):
            res = execute_voice_enrollment_plan(make_plan(enrollment_mode=mode))
            self.assertEqual(res.code, NOT_IMPL)
            self.assertEqual(res.metadata["enrollment_mode"], mode)

    def test_5_result_passes_the_existing_result_validator(self):
        res = execute_voice_enrollment_plan(make_plan())
        v = validate_voice_enrollment_result(res)
        self.assertTrue(v.ok)
        self.assertIs(v.result, res)
        rej = execute_voice_enrollment_plan(None)
        self.assertTrue(validate_voice_enrollment_result(rej).ok)

    def test_6_plan_is_unchanged(self):
        plan = make_plan()
        before = (plan.to_dict(), hash(plan), repr(plan))
        execute_voice_enrollment_plan(plan)
        execute_voice_enrollment_plan(plan)
        self.assertEqual(before, (plan.to_dict(), hash(plan), repr(plan)))


class TestNonRetention(unittest.TestCase):
    def test_7_plan_is_not_retained(self):
        plan = make_plan()
        res = execute_voice_enrollment_plan(plan)
        self.assertIsNot(res, plan)
        for obj in (res,) + tuple(gc.get_referents(res)):
            self.assertIsNot(obj, plan)
        for referent in gc.get_referents(res):
            if type(referent) is tuple:
                for item in referent:
                    self.assertFalse(any(sub is plan for sub in (item if type(item) is tuple else (item,))))
        self.assertNotIn(plan, gc.get_referents(res))

    def test_8_only_primitive_values_are_held(self):
        res = execute_voice_enrollment_plan(make_plan())
        self.assertEqual(sorted(type(r).__name__ for r in gc.get_referents(res) if r is not VoiceEnrollmentResult), ["str", "str", "str", "str", "tuple"])
        for key, value in res.metadata.items():
            self.assertIs(type(value), str)

    def test_9_changes_to_the_plan_source_or_returned_metadata_never_affect_the_result(self):
        plan = make_plan()
        res = execute_voice_enrollment_plan(plan)
        meta = res.metadata
        meta["request_id"] = "mutated"
        meta["extra"] = 1
        meta.clear()
        self.assertEqual(res.metadata, {"request_id": "enroll_1", "profile_id": "voice_1", "enrollment_mode": "standard"})
        self.assertIsNot(res.metadata, res.metadata)
        d = res.to_dict()
        d["metadata"]["enrollment_mode"] = "mutated"
        d["status"] = "X"
        self.assertEqual(res.to_dict()["metadata"]["enrollment_mode"], "standard")
        self.assertEqual(res.status, "NOT_IMPLEMENTED")


class TestInvalidPlans(unittest.TestCase):
    def assert_rejected(self, res):
        self.assertIs(type(res), VoiceEnrollmentResult)
        self.assertEqual((res.status, res.code), ("REJECTED", INVALID_PLAN))
        self.assertIsNone(res.metadata)
        self.assertEqual((res.request_id, res.profile_id), (ve.UNKNOWN_ID, ve.UNKNOWN_ID))
        self.assertEqual(res.to_dict(), {"request_id": "UNKNOWN", "profile_id": "UNKNOWN", "status": "REJECTED", "code": INVALID_PLAN, "metadata": None})

    def test_10_invalid_inputs_are_rejected(self):
        plan = make_plan()
        for bad in (None, {}, [], "plan", 5, True, object(), plan.to_dict(), VoiceEnrollmentPlan, (plan,), plan.request_id,
                    create_voice_enrollment_plan(create_voice_enrollment_request({"request_id": "a", "profile_id": "b", "enrollment_mode": "c"})),
                    create_voice_enrollment_request({"request_id": "a", "profile_id": "b", "enrollment_mode": "c"}),
                    execute_voice_enrollment_plan(plan)):
            with self.subTest(bad=type(bad).__name__):
                self.assert_rejected(execute_voice_enrollment_plan(bad))

    def test_11_look_alikes_spoofs_and_mocks_are_rejected_and_never_read(self):
        class Fake:
            def __getattr__(self, name):
                raise AssertionError("must not read " + name)

        class Spoof:
            __class__ = VoiceEnrollmentPlan
            request_id = profile_id = enrollment_mode = "x"

        self.assertIsInstance(Spoof(), VoiceEnrollmentPlan)      # isinstance is fooled, the exact type check is not
        for bad in (Fake(), Spoof(), mock.MagicMock(spec=VoiceEnrollmentPlan)):
            self.assert_rejected(execute_voice_enrollment_plan(bad))
        with self.assertRaises(TypeError):
            type("Sub", (VoiceEnrollmentPlan,), {})

    def test_12_never_raises_for_odd_inputs(self):
        class Boom:
            def __eq__(self, other):
                raise RuntimeError("boom")

            def __hash__(self):
                raise RuntimeError("boom")

            def __getattr__(self, name):
                raise RuntimeError("boom")

        for bad in (Boom(), float("nan"), b"x", {1: 2}, lambda: 1, type, 10 ** 100):
            self.assert_rejected(execute_voice_enrollment_plan(bad))

    def test_13_malformed_exact_plans_are_treated_as_invalid(self):
        for args in ((1, "p", "m"), ("r", None, "m"), ("r", "p", 5), ("", "p", "m"), ("r", "", "m"), ("r", "p", ""), (Str("r"), "p", "m"),
                     ("r", Str("p"), "m"), ("r", "p", Str("m"))):
            with self.subTest(args=args):
                self.assert_rejected(execute_voice_enrollment_plan(raw_plan(*args)))

    def test_14_a_plan_read_that_raises_is_treated_as_invalid(self):
        def boom(self):
            raise RuntimeError("boom")

        for field in FIELDS:
            with self.subTest(field=field):
                with mock.patch.object(VoiceEnrollmentPlan, field, property(boom)):
                    self.assert_rejected(execute_voice_enrollment_plan(make_plan()))
        self.assertEqual(execute_voice_enrollment_plan(make_plan()).code, NOT_IMPL)

    def test_15_constants_are_stable(self):
        self.assertEqual(ve.STATUSES, ("REJECTED", "NOT_IMPLEMENTED"))
        self.assertEqual(ve.CODES, (INVALID_PLAN, NOT_IMPL))
        self.assertEqual(ve.UNKNOWN_ID, "UNKNOWN")
        self.assertEqual(INVALID_PLAN, "VOICE_ENROLLMENT_EXECUTOR_INVALID_PLAN")


class TestResultImmutabilityAndMutationAttempts(unittest.TestCase):
    def setUp(self):
        self.ok = execute_voice_enrollment_plan(make_plan())
        self.bad = execute_voice_enrollment_plan(None)

    def test_16_immutable(self):
        for obj in (self.ok, self.bad):
            for name in ("status", "code", "metadata", "request_id", "profile_id", "_status", "_items", "extra"):
                with self.assertRaises(AttributeError):
                    setattr(obj, name, "x")
                with self.assertRaises(AttributeError):
                    delattr(obj, name)
        self.assertEqual(self.ok.status, "NOT_IMPLEMENTED")

    def test_17_plan_cannot_be_mutated_to_affect_execution(self):
        plan = make_plan()
        for name in FIELDS + ("_request_id", "extra"):
            with self.assertRaises(AttributeError):
                setattr(plan, name, "x")
            with self.assertRaises(AttributeError):
                delattr(plan, name)
        self.assertEqual(execute_voice_enrollment_plan(plan).metadata, plan.to_dict())

    def test_18_direct_construction_and_subclassing_refused(self):
        with self.assertRaises(TypeError):
            VoiceEnrollmentResult(None, "a", "b", "c", "d", None)
        with self.assertRaises(TypeError):
            type("Sub", (VoiceEnrollmentResult,), {})

    def test_19_equality_hash_copy_and_pickle(self):
        again = execute_voice_enrollment_plan(make_plan())
        self.assertEqual(self.ok, again)
        self.assertEqual(hash(self.ok), hash(again))
        self.assertEqual(len({self.ok, again}), 1)
        self.assertNotEqual(self.ok, self.bad)
        self.assertNotEqual(self.ok, execute_voice_enrollment_plan(make_plan(enrollment_mode="other")))
        self.assertEqual(self.bad, execute_voice_enrollment_plan(5))
        for obj in (self.ok, self.bad):
            self.assertIs(copy.copy(obj), obj)
            self.assertIs(copy.deepcopy(obj), obj)
            for proto in range(pickle.HIGHEST_PROTOCOL + 1):
                with self.assertRaises(TypeError):
                    pickle.dumps(obj, protocol=proto)

    def test_20_repr_is_stable(self):
        self.assertEqual(repr(self.ok), "VoiceEnrollmentResult(request_id='enroll_1', profile_id='voice_1', status='NOT_IMPLEMENTED', code='%s')" % NOT_IMPL)
        self.assertEqual(repr(self.bad), "VoiceEnrollmentResult(request_id='UNKNOWN', profile_id='UNKNOWN', status='REJECTED', code='%s')" % INVALID_PLAN)


class TestDeterminismAndSideEffects(unittest.TestCase):
    def test_21_repeated_execution_is_deterministic(self):
        plan = make_plan()
        results = [execute_voice_enrollment_plan(plan) for _ in range(5)]
        for r in results[1:]:
            self.assertEqual(r, results[0])
            self.assertEqual(hash(r), hash(results[0]))
            self.assertEqual(r.to_dict(), results[0].to_dict())
        self.assertEqual(execute_voice_enrollment_plan(make_plan()), execute_voice_enrollment_plan(make_plan()))
        self.assertEqual(len({execute_voice_enrollment_plan(None) for _ in range(3)}), 1)
        self.assertEqual(len({execute_voice_enrollment_plan(raw_plan(1, 2, 3)) for _ in range(3)}), 1)

    def test_22_no_side_effects(self):
        plan = make_plan()
        before_env, before_cwd, before_mods = dict(os.environ), os.getcwd(), set(sys.modules)
        before_tree = sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d)
        for _ in range(3):
            for item in (plan, None, raw_plan(1, 2, 3)):
                execute_voice_enrollment_plan(item)
        self.assertEqual(dict(os.environ), before_env)
        self.assertEqual(os.getcwd(), before_cwd)
        self.assertEqual(set(sys.modules), before_mods)
        self.assertEqual(sorted((d, tuple(sorted(f))) for d, _s, f in os.walk(PY_ROOT) if "__pycache__" not in d), before_tree)
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)

    def test_23_no_io_network_subprocess_audio_or_persistence_calls(self):
        import builtins
        import io
        import os as _os
        import socket
        import sqlite3
        import subprocess
        plan = make_plan()
        boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError("forbidden call"))
        with mock.patch.object(socket, "socket", boom), mock.patch.object(socket, "create_connection", boom), \
                mock.patch.object(subprocess, "Popen", boom), mock.patch.object(_os, "system", boom), mock.patch.object(builtins, "open", boom), \
                mock.patch.object(io, "open", boom), mock.patch.object(_os, "open", boom), mock.patch.object(_os, "listdir", boom), \
                mock.patch.object(sqlite3, "connect", boom):
            self.assertEqual(execute_voice_enrollment_plan(plan).code, NOT_IMPL)
            self.assertEqual(execute_voice_enrollment_plan(None).code, INVALID_PLAN)
            self.assertEqual(execute_voice_enrollment_plan(raw_plan(1, 2, 3)).code, INVALID_PLAN)


class TestBoundaries(unittest.TestCase):
    def _tree(self):
        with open(MODULE, encoding="utf-8") as fh:
            return ast.parse(fh.read())

    def test_24_module_imports_only_the_plan_type_and_result_factory(self):
        imports = sorted((n.module, n.level, sorted(a.name for a in n.names)) for n in ast.walk(self._tree()) if isinstance(n, (ast.Import, ast.ImportFrom)))
        self.assertEqual(imports, [("voice_enrollment_plan", 1, ["VoiceEnrollmentPlan"]), ("voice_enrollment_result", 1, ["create_voice_enrollment_result"])])

    def test_25_module_is_pure_and_has_no_module_state(self):
        tree = self._tree()
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "setattr", "globals", "vars"):
            self.assertNotIn(forbidden, calls)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("os", "sys", "io", "pathlib", "subprocess", "socket", "urllib", "http", "requests", "sqlite3", "random", "time", "datetime",
                     "anthropic", "openai", "numpy", "wave", "core", "agent", "planning", "web", "multimedia", "game_creation", "audio", "embedding",
                     "VoiceEnrollmentRequest", "VoiceIdentityProfile", "create_voice_enrollment_plan", "_items"):
            self.assertNotIn(word, names, word)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ImportFrom))
        for name, value in vars(ve).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_26_existing_voice_modules_are_unaware_of_the_executor(self):
        for name in ("voice_identity_profile.py", "voice_identity_profile_registry.py", "voice_enrollment_request.py", "voice_enrollment_result.py",
                     "voice_enrollment_result_validator.py", "voice_enrollment_plan.py"):
            with open(os.path.join(PY_ROOT, "voice", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("voice_enrollment_executor", "execute_voice_enrollment_plan"):
                self.assertNotIn(token, text, (name, token))
        self.assertEqual(vp.FIELDS, FIELDS)
        self.assertEqual(len(vp.FAILURE_CODES), 6)

    def test_27_no_module_outside_voice_references_it(self):
        tokens = ("voice_enrollment_executor", "execute_voice_enrollment_plan")
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

    def test_28_voice_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "voice")) if f != "__pycache__"),
                         ["__init__.py", "voice_enrollment_batch.py", "voice_enrollment_batch_summary.py", "voice_enrollment_dispatcher.py", "voice_enrollment_executor.py", "voice_enrollment_pipeline.py", "voice_enrollment_plan.py", "voice_enrollment_request.py",
                          "voice_enrollment_result.py", "voice_enrollment_result_validator.py", "voice_identity_profile.py",
                          "voice_identity_profile_registry.py", "voice_verification_authorization.py", "voice_verification_batch.py", "voice_verification_batch_summary.py", "voice_verification_decision.py", "voice_verification_dispatcher.py", "voice_verification_execution.py", "voice_verification_execution_request.py", "voice_verification_executor.py", "voice_verification_handoff.py", "voice_verification_pipeline.py", "voice_verification_plan.py", "voice_verification_profile_resolver.py", "voice_verification_registry.py", "voice_verification_request.py", "voice_verification_request_validator.py", "voice_verification_result.py"])
        with open(os.path.join(PY_ROOT, "voice", "__init__.py"), "rb") as fh:
            self.assertEqual(fh.read(), b"")

    def test_29_end_to_end_through_public_apis_only(self):
        req = create_voice_enrollment_request({"request_id": "e2e", "profile_id": "prof", "enrollment_mode": "m"})
        res = execute_voice_enrollment_plan(create_voice_enrollment_plan(req).plan)
        self.assertEqual((res.status, res.code, res.metadata), ("NOT_IMPLEMENTED", NOT_IMPL, {"request_id": "e2e", "profile_id": "prof", "enrollment_mode": "m"}))
        self.assertEqual(execute_voice_enrollment_plan(create_voice_enrollment_plan(None)).code, INVALID_PLAN)      # a plan *result* is not a plan

    def test_30_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("execute_voice_enrollment_plan", "VoiceEnrollmentPlan", "VoiceEnrollmentResult", "VOICE_ENROLLMENT_EXECUTOR_INVALID_PLAN",
                       "VOICE_ENROLLMENT_EXECUTOR_NOT_IMPLEMENTED", "REJECTED", "NOT_IMPLEMENTED", "UNKNOWN", "does NOT", "Prompt 794"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
