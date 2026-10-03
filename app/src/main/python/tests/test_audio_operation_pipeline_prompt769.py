"""Prompt 769 - Section 8 audio operation pipeline (`multimedia.audio_operation_pipeline`)."""
import ast
import builtins
import copy
import hashlib
import os
import pickle
import unittest
from unittest import mock

from multimedia import audio_operation_metadata_executor as me
from multimedia import audio_operation_pipeline as p
from multimedia.audio_asset import create_audio_asset
from multimedia.audio_asset_registry import create_audio_asset_registry
from multimedia.audio_operation_dispatcher import AudioOperationDispatchResult, dispatch_audio_operation
from multimedia.audio_operation_output_validator import AudioOperationOutputValidationResult, validate_audio_operation_output
from multimedia.audio_operation_pipeline import AudioOperationPipelineResult, process_audio_operation
from multimedia.audio_operation_plan import AudioOperationPlan, create_audio_operation_plan
from multimedia.audio_operation_request import create_audio_operation_request
from multimedia.audio_operation_validator import validate_audio_operation_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section8_audio_operation_pipeline_prompt769.md")
MODULE = os.path.join(PY_ROOT, "multimedia", "audio_operation_pipeline.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
P = "AUDIO_OPERATION_PIPELINE_"
V = "AUDIO_OPERATION_VALIDATION_"

BASE = {"audio_id": "theme", "operation": "metadata", "target_format": "mp3", "duration_ms": 1000, "sample_rate": 22050, "quality": 70}


def make_registry(*audio_ids):
    assets = []
    for audio_id in (audio_ids or ("theme",)):
        created = create_audio_asset({"audio_id": audio_id, "name": "N", "description": "", "format": "ogg", "duration_ms": 5000, "sample_rate": 44100})
        assert created.ok, created.failures
        assets.append(created.asset)
    registry = create_audio_asset_registry(assets)
    assert registry.ok, registry.failures
    return registry.registry


def make_request(**over):
    data = dict(BASE)
    data.update(over)
    created = create_audio_operation_request(data)
    assert created.ok, created.failures
    return created.request


class TestSuccess(unittest.TestCase):
    def test_01_successful_metadata_pipeline(self):
        res = process_audio_operation(make_request(), make_registry())
        self.assertIs(type(res), AudioOperationPipelineResult)
        self.assertIs(res.ok, True)
        self.assertEqual(res.failures, ())
        self.assertEqual(res.codes(), [])
        self.assertIs(type(res.plan), AudioOperationPlan)
        self.assertIs(type(res.dispatch_result), AudioOperationDispatchResult)
        self.assertIs(type(res.output_validation), AudioOperationOutputValidationResult)
        self.assertEqual(res.dispatch_result.result.output.to_dict(),
                         {"audio_id": "theme", "operation": "metadata", "output_format": "mp3", "duration_ms": 1000, "sample_rate": 22050})

    def test_02_exact_request_identity(self):
        req = make_request()
        self.assertIs(process_audio_operation(req, make_registry()).request, req)

    def test_03_exact_plan_identity(self):
        res = process_audio_operation(make_request(), make_registry())
        self.assertIs(res.plan, res.dispatch_result.plan)
        self.assertIs(res.plan, res.dispatch_result.result.plan)
        self.assertIs(res.plan, res.output_validation.plan)
        self.assertEqual(res.plan.to_dict(), BASE)

    def test_04_exact_dispatch_result_identity(self):
        req, reg = make_request(), make_registry()
        plan = create_audio_operation_plan(validate_audio_operation_request(req, reg)).plan
        sentinel = dispatch_audio_operation(plan)
        with mock.patch.object(p, "dispatch_audio_operation", return_value=sentinel) as dispatch:
            res = process_audio_operation(req, reg)
        dispatch.assert_called_once()
        self.assertIs(res.dispatch_result, sentinel)
        self.assertEqual(dispatch.call_args.args[0], plan)

    def test_05_exact_output_validation_result(self):
        req, reg = make_request(), make_registry()
        sentinel = validate_audio_operation_output(
            create_audio_operation_plan(validate_audio_operation_request(req, reg)).plan,
            dispatch_audio_operation(create_audio_operation_plan(validate_audio_operation_request(req, reg)).plan).result.output)
        with mock.patch.object(p, "validate_audio_operation_output", return_value=sentinel) as validate:
            res = process_audio_operation(req, reg)
        validate.assert_called_once()
        self.assertIs(res.output_validation, sentinel)
        self.assertIs(validate.call_args.args[0], res.plan)
        self.assertIs(validate.call_args.args[1], res.dispatch_result.result.output)
        self.assertIs(res.ok, True)

    def test_06_stages_are_chained_in_order_through_the_public_apis(self):
        calls = []

        def spy(name, fn):
            def wrapper(*a, **k):
                calls.append(name)
                return fn(*a, **k)
            return wrapper

        with mock.patch.object(p, "validate_audio_operation_request", spy("validate", p.validate_audio_operation_request)), \
                mock.patch.object(p, "create_audio_operation_plan", spy("plan", p.create_audio_operation_plan)), \
                mock.patch.object(p, "dispatch_audio_operation", spy("dispatch", p.dispatch_audio_operation)), \
                mock.patch.object(p, "validate_audio_operation_output", spy("output", p.validate_audio_operation_output)):
            self.assertTrue(process_audio_operation(make_request(), make_registry()).ok)
        self.assertEqual(calls, ["validate", "plan", "dispatch", "output"])

    def test_07_to_dict_shape(self):
        res = process_audio_operation(make_request(), make_registry())
        d = res.to_dict()
        self.assertEqual(list(d), ["ok", "request", "plan", "dispatch_result", "output_validation", "failures"])
        self.assertEqual(d["request"], BASE)
        self.assertEqual(d["plan"], BASE)
        self.assertEqual(d["dispatch_result"], res.dispatch_result.to_dict())
        self.assertEqual(d["output_validation"], res.output_validation.to_dict())
        self.assertEqual((d["ok"], d["failures"]), (True, []))


class TestInvalidInputs(unittest.TestCase):
    def assert_stopped_at_validation(self, res):
        self.assertIs(res.ok, False)
        self.assertIsNone(res.plan)
        self.assertIsNone(res.dispatch_result)
        self.assertIsNone(res.output_validation)

    def test_10_invalid_request(self):
        for bad in (None, {}, dict(BASE), "theme", 0, object()):
            with self.subTest(bad=type(bad).__name__):
                res = process_audio_operation(bad, make_registry())
                self.assert_stopped_at_validation(res)
                self.assertIsNone(res.request)
                self.assertEqual(res.codes(), [P + "INVALID_REQUEST"])
                self.assertEqual(res.failures[0]["field"], "request")
                self.assertIn(V + "INVALID_REQUEST", res.failures[0]["message"])

    def test_11_invalid_registry_keeps_the_valid_request_identity(self):
        req = make_request()
        for bad in (None, {}, [], "registry", object()):
            with self.subTest(bad=type(bad).__name__):
                res = process_audio_operation(req, bad)
                self.assert_stopped_at_validation(res)
                self.assertIs(res.request, req)
                self.assertEqual(res.codes(), [P + "INVALID_REGISTRY"])
                self.assertEqual(res.failures[0]["field"], "audio_registry")
                self.assertIn(V + "INVALID_AUDIO_REGISTRY", res.failures[0]["message"])

    def test_12_both_inputs_invalid_reports_both_in_validation_order(self):
        res = process_audio_operation(None, None)
        self.assert_stopped_at_validation(res)
        self.assertIsNone(res.request)
        self.assertEqual(res.codes(), [P + "INVALID_REQUEST", P + "INVALID_REGISTRY"])

    def test_13_missing_audio(self):
        req = make_request(audio_id="ghost")
        res = process_audio_operation(req, make_registry("theme"))
        self.assert_stopped_at_validation(res)
        self.assertIs(res.request, req)
        self.assertEqual(res.codes(), [P + "VALIDATION_FAILED"])
        self.assertEqual(res.failures[0]["field"], "audio_id")
        self.assertIn(V + "AUDIO_NOT_FOUND", res.failures[0]["message"])

    def test_14_missing_audio_in_empty_registry_and_exact_id_matching(self):
        empty = create_audio_asset_registry([]).registry
        self.assertEqual(process_audio_operation(make_request(), empty).codes(), [P + "VALIDATION_FAILED"])
        for odd in ("THEME", " theme", "theme "):
            with self.subTest(audio_id=odd):
                self.assertEqual(process_audio_operation(make_request(audio_id=odd), make_registry("theme")).codes(), [P + "VALIDATION_FAILED"])

    def test_15_upstream_validation_codes_are_exposed_one_to_one(self):
        for req, reg in ((None, None), (make_request(), None), (None, make_registry()), (make_request(audio_id="x"), make_registry())):
            upstream = validate_audio_operation_request(req, reg).codes()
            res = process_audio_operation(req, reg)
            self.assertEqual(len(res.failures), len(upstream))
            for failure, code in zip(res.failures, upstream):
                self.assertIn("[%s]" % code, failure["message"])

    def test_16_validation_failure_creates_no_plan_and_dispatches_nothing(self):
        with mock.patch.object(p, "create_audio_operation_plan") as plan, mock.patch.object(p, "dispatch_audio_operation") as dispatch, \
                mock.patch.object(p, "validate_audio_operation_output") as output:
            for req, reg in ((None, make_registry()), (make_request(), None), (make_request(audio_id="ghost"), make_registry())):
                process_audio_operation(req, reg)
        plan.assert_not_called()
        dispatch.assert_not_called()
        output.assert_not_called()

    def test_17_never_raises_for_odd_inputs(self):
        odd = (None, 0, "", b"", [], {}, object(), float("nan"), AudioOperationPipelineResult, AudioOperationPlan)
        for a in odd:
            for b in odd:
                with self.subTest(a=type(a).__name__, b=type(b).__name__):
                    res = process_audio_operation(a, b)
                    self.assertIs(res.ok, False)
                    self.assertTrue(set(res.codes()) <= {P + "INVALID_REQUEST", P + "INVALID_REGISTRY"})


class TestLaterStageFailures(unittest.TestCase):
    def test_20_unsupported_operation_is_a_dispatch_failure(self):
        req = make_request(operation="trim")
        res = process_audio_operation(req, make_registry())
        self.assertIs(res.ok, False)
        self.assertIs(res.request, req)
        self.assertEqual(res.plan.to_dict(), dict(BASE, operation="trim"))
        self.assertIs(type(res.dispatch_result), AudioOperationDispatchResult)
        self.assertIsNone(res.dispatch_result.result)
        self.assertEqual(res.dispatch_result.codes(), ["AUDIO_OPERATION_DISPATCHER_UNSUPPORTED_OPERATION"])
        self.assertIsNone(res.output_validation)
        self.assertEqual(res.codes(), [P + "DISPATCH_FAILED"])
        self.assertIn("AUDIO_OPERATION_DISPATCHER_UNSUPPORTED_OPERATION", res.failures[0]["message"])

    def test_21_dispatch_failure_preserves_exact_plan_and_dispatch_result_and_skips_output_validation(self):
        req, reg = make_request(operation="Metadata"), make_registry()
        plan = create_audio_operation_plan(validate_audio_operation_request(req, reg)).plan
        sentinel = dispatch_audio_operation(plan)
        self.assertFalse(sentinel.ok)
        with mock.patch.object(p, "dispatch_audio_operation", return_value=sentinel), \
                mock.patch.object(p, "validate_audio_operation_output") as output:
            res = process_audio_operation(req, reg)
        output.assert_not_called()
        self.assertIs(res.dispatch_result, sentinel)
        self.assertEqual(res.plan, plan)
        self.assertIsNone(res.output_validation)
        self.assertEqual(res.codes(), [P + "DISPATCH_FAILED"])

    def test_22_dispatch_failure_exact_plan_object_is_the_dispatchers_plan(self):
        res = process_audio_operation(make_request(operation="mix"), make_registry())
        self.assertIs(res.plan, res.dispatch_result.plan)

    def test_23_executor_level_failure_stays_in_dispatch_result_and_is_exposed(self):
        failed_output = me.create_audio_operation_output({})
        self.assertFalse(failed_output.ok)
        with mock.patch.object(me, "create_audio_operation_output", return_value=failed_output):
            res = process_audio_operation(make_request(), make_registry())
        self.assertIs(res.ok, False)
        self.assertEqual(res.dispatch_result.codes(), [])
        self.assertEqual(res.dispatch_result.result.codes(), [me.FAILURE_OUTPUT_CREATION_FAILED])
        self.assertIsNone(res.output_validation)
        self.assertEqual(res.codes(), [P + "DISPATCH_FAILED"])
        self.assertIn(me.FAILURE_OUTPUT_CREATION_FAILED, res.failures[0]["message"])

    def test_24_output_validation_failure_via_controlled_setup(self):
        req, reg = make_request(), make_registry()
        other_plan = create_audio_operation_plan(validate_audio_operation_request(make_request(duration_ms=1, sample_rate=2, target_format="wav"), reg)).plan
        mismatched = dispatch_audio_operation(other_plan)
        self.assertTrue(mismatched.ok)
        with mock.patch.object(p, "dispatch_audio_operation", return_value=mismatched):
            res = process_audio_operation(req, reg)
        self.assertIs(res.ok, False)
        self.assertIs(res.request, req)
        self.assertEqual(res.plan.to_dict(), BASE)
        self.assertIs(res.dispatch_result, mismatched)
        self.assertIs(type(res.output_validation), AudioOperationOutputValidationResult)
        self.assertFalse(res.output_validation.ok)
        self.assertIs(res.output_validation.plan, res.plan)
        self.assertIs(res.output_validation.output, mismatched.result.output)
        self.assertEqual(res.output_validation.codes(), ["AUDIO_OPERATION_OUTPUT_VALIDATION_FORMAT_MISMATCH",
                                                        "AUDIO_OPERATION_OUTPUT_VALIDATION_DURATION_MS_MISMATCH",
                                                        "AUDIO_OPERATION_OUTPUT_VALIDATION_SAMPLE_RATE_MISMATCH"])
        self.assertEqual(res.codes(), [P + "OUTPUT_VALIDATION_FAILED"] * 3)
        for failure, code in zip(res.failures, res.output_validation.codes()):
            self.assertEqual(failure["field"], "output_validation")
            self.assertIn("[%s]" % code, failure["message"])

    def test_25_output_validation_result_is_held_unchanged_when_it_fails(self):
        req, reg = make_request(), make_registry()
        plan = create_audio_operation_plan(validate_audio_operation_request(req, reg)).plan
        failing = validate_audio_operation_output(plan, None)
        self.assertFalse(failing.ok)
        with mock.patch.object(p, "validate_audio_operation_output", return_value=failing):
            res = process_audio_operation(req, reg)
        self.assertIs(res.output_validation, failing)
        self.assertIs(res.ok, False)
        self.assertIs(type(res.dispatch_result), AudioOperationDispatchResult)
        self.assertTrue(res.dispatch_result.ok)

    def test_26_plan_failure_via_controlled_setup(self):
        req, reg = make_request(), make_registry()
        failed_plan = create_audio_operation_plan(None)
        with mock.patch.object(p, "create_audio_operation_plan", return_value=failed_plan), \
                mock.patch.object(p, "dispatch_audio_operation") as dispatch:
            res = process_audio_operation(req, reg)
        dispatch.assert_not_called()
        self.assertIs(res.ok, False)
        self.assertIs(res.request, req)
        self.assertIsNone(res.plan)
        self.assertIsNone(res.dispatch_result)
        self.assertIsNone(res.output_validation)
        self.assertEqual(res.codes(), [P + "PLAN_FAILED"])
        self.assertIn("AUDIO_OPERATION_PLAN_INVALID_VALIDATION_RESULT", res.failures[0]["message"])

    def test_27_ok_requires_dispatch_and_output_validation_success(self):
        res = process_audio_operation(make_request(), make_registry())
        self.assertTrue(res.ok)
        self.assertTrue(res.dispatch_result.ok and res.output_validation.ok)
        for bad in (make_request(operation="trim"), make_request(audio_id="ghost")):
            self.assertFalse(process_audio_operation(bad, make_registry()).ok)


class TestFailureCodes(unittest.TestCase):
    def test_30_only_the_six_codes_exist(self):
        self.assertEqual(p.FAILURE_CODES, tuple(P + s for s in ("INVALID_REQUEST", "INVALID_REGISTRY", "VALIDATION_FAILED", "PLAN_FAILED",
                                                              "DISPATCH_FAILED", "OUTPUT_VALIDATION_FAILED")))
        self.assertEqual(len(set(p.FAILURE_CODES)), 6)

    def test_31_every_produced_code_is_one_of_the_six(self):
        reg = make_registry()
        seen = set()
        for req, rg in ((None, None), (make_request(), None), (make_request(audio_id="g"), reg), (make_request(operation="x"), reg),
                        (make_request(), reg)):
            seen.update(process_audio_operation(req, rg).codes())
        self.assertTrue(seen <= set(p.FAILURE_CODES))
        self.assertEqual(seen, {P + "INVALID_REQUEST", P + "INVALID_REGISTRY", P + "VALIDATION_FAILED", P + "DISPATCH_FAILED"})

    def test_32_failures_are_fresh_three_key_dicts(self):
        res = process_audio_operation(None, None)
        for f in res.failures:
            self.assertEqual(list(f), ["code", "field", "message"])
            self.assertTrue(all(type(v) is str for v in f.values()))
        res.failures[0]["code"] = "tampered"
        self.assertEqual(res.codes()[0], P + "INVALID_REQUEST")
        self.assertIsNot(res.failures[0], res.failures[0])


class TestNoMutationAndDeterminism(unittest.TestCase):
    def test_40_no_mutation_of_inputs(self):
        req, reg = make_request(), make_registry("theme", "jingle")
        before = (req.to_dict(), reg.to_dict(), hash(req), hash(reg), reg.lookup("theme").asset)
        for _ in range(3):
            process_audio_operation(req, reg)
            process_audio_operation(make_request(operation="trim"), reg)
            process_audio_operation(make_request(audio_id="ghost"), reg)
        self.assertEqual(before[:4], (req.to_dict(), reg.to_dict(), hash(req), hash(reg)))
        self.assertIs(before[4], reg.lookup("theme").asset)
        self.assertEqual(req.to_dict(), BASE)

    def test_41_deterministic_repeated_calls(self):
        req, reg = make_request(), make_registry()
        results = [process_audio_operation(req, reg) for _ in range(5)]
        self.assertTrue(all(r == results[0] for r in results))
        self.assertEqual(len({hash(r) for r in results}), 1)
        self.assertEqual(len({repr(r.to_dict()) for r in results}), 1)
        bad = process_audio_operation(make_request(operation="trim"), reg)
        self.assertEqual([process_audio_operation(make_request(operation="trim"), reg) for _ in range(5)], [bad] * 5)

    def test_42_equal_inputs_built_separately_give_equal_results(self):
        a = process_audio_operation(make_request(), make_registry())
        b = process_audio_operation(make_request(), make_registry())
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))

    def test_43_fresh_to_dict(self):
        res = process_audio_operation(make_request(), make_registry())
        d1, d2 = res.to_dict(), res.to_dict()
        self.assertEqual(d1, d2)
        self.assertIsNot(d1, d2)
        for key in ("request", "plan", "dispatch_result", "output_validation", "failures"):
            self.assertIsNot(d1[key], d2[key])
        d1["plan"]["duration_ms"] = -1
        d1["dispatch_result"]["result"]["output"]["duration_ms"] = -1
        d1["failures"].append("x")
        d1["ok"] = False
        self.assertEqual(res.to_dict(), d2)
        self.assertEqual(res.plan.duration_ms, 1000)
        self.assertTrue(res.ok)

    def test_44_to_dict_of_failed_results(self):
        d = process_audio_operation(None, make_registry()).to_dict()
        self.assertEqual((d["ok"], d["request"], d["plan"], d["dispatch_result"], d["output_validation"]), (False, None, None, None, None))
        self.assertEqual([f["code"] for f in d["failures"]], [P + "INVALID_REQUEST"])
        d = process_audio_operation(make_request(operation="trim"), make_registry()).to_dict()
        self.assertEqual(d["plan"]["operation"], "trim")
        self.assertIsNotNone(d["dispatch_result"])
        self.assertIsNone(d["output_validation"])


class TestResultModel(unittest.TestCase):
    def setUp(self):
        self.ok = process_audio_operation(make_request(), make_registry())
        self.bad = process_audio_operation(make_request(operation="trim"), make_registry())

    def test_50_equality_and_hash(self):
        self.assertEqual(self.ok, process_audio_operation(make_request(), make_registry()))
        self.assertNotEqual(self.ok, self.bad)
        self.assertNotEqual(self.ok, self.ok.to_dict())
        self.assertNotEqual(self.ok, None)
        self.assertEqual(len({self.ok, process_audio_operation(make_request(), make_registry()), self.bad}), 2)
        self.assertNotEqual(process_audio_operation(make_request(duration_ms=1), make_registry()), self.ok)

    def test_51_immutable(self):
        for name in ("ok", "request", "plan", "dispatch_result", "output_validation", "failures", "extra"):
            with self.subTest(name=name):
                with self.assertRaises(AttributeError):
                    setattr(self.ok, name, 1)
                with self.assertRaises(AttributeError):
                    delattr(self.ok, name)
        self.assertFalse(hasattr(self.ok, "__dict__"))

    def test_52_no_direct_construction_and_no_subclassing(self):
        with self.assertRaises(TypeError):
            AudioOperationPipelineResult()
        with self.assertRaises(TypeError):
            AudioOperationPipelineResult(object(), None, None, None, None, ())
        with self.assertRaises(TypeError):
            AudioOperationPipelineResult(None, None, None, None, None, ())
        with self.assertRaises(TypeError):
            type("Sub", (AudioOperationPipelineResult,), {})

    def test_53_copy_and_deepcopy_return_the_same_object(self):
        for res in (self.ok, self.bad):
            self.assertIs(copy.copy(res), res)
            self.assertIs(copy.deepcopy(res), res)
            self.assertIs(copy.deepcopy([res])[0], res)

    def test_54_pickle_refused(self):
        for res in (self.ok, self.bad):
            for proto in range(0, pickle.HIGHEST_PROTOCOL + 1):
                with self.subTest(proto=proto):
                    with self.assertRaises(TypeError):
                        pickle.dumps(res, protocol=proto)

    def test_55_repr(self):
        self.assertEqual(repr(self.ok), "AudioOperationPipelineResult(ok=True, codes=[])")
        self.assertEqual(repr(self.bad), "AudioOperationPipelineResult(ok=False, codes=['%sDISPATCH_FAILED'])" % P)


class TestBoundaries(unittest.TestCase):
    def test_60_no_filesystem_access(self):
        def refuse(*a, **k):
            raise AssertionError("filesystem access attempted")

        req, reg, bad = make_request(), make_registry(), make_request(operation="trim")
        with mock.patch.object(builtins, "open", refuse), mock.patch("os.listdir", refuse), mock.patch("os.stat", refuse), \
                mock.patch("os.scandir", refuse), mock.patch("os.walk", refuse), mock.patch("os.path.exists", refuse), \
                mock.patch("os.path.isfile", refuse), mock.patch("io.open", refuse):
            self.assertTrue(process_audio_operation(req, reg).ok)
            self.assertEqual(process_audio_operation(bad, reg).codes(), [P + "DISPATCH_FAILED"])
            self.assertEqual(process_audio_operation(None, None).codes(), [P + "INVALID_REQUEST", P + "INVALID_REGISTRY"])
            self.assertEqual(process_audio_operation(make_request(audio_id="g"), reg).codes(), [P + "VALIDATION_FAILED"])

    def test_61_module_uses_only_the_public_apis_and_does_no_io(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertTrue(all(isinstance(n, ast.ImportFrom) and n.level == 1 for n in imports))
        self.assertEqual([(n.module, sorted(a.name for a in n.names)) for n in imports], [
            ("audio_operation_dispatcher", ["dispatch_audio_operation"]),
            ("audio_operation_output_validator", ["validate_audio_operation_output"]),
            ("audio_operation_plan", ["AudioOperationPlan", "create_audio_operation_plan"]),
            ("audio_operation_validator", ["FAILURE_INVALID_AUDIO_REGISTRY", "FAILURE_INVALID_REQUEST", "validate_audio_operation_request"])])
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"open", "os", "io", "subprocess", "socket", "random", "time", "pathlib", "AudioAsset", "AudioAssetRegistry",
                                  "AudioOperationRequest", "AudioOperationOutput", "create_audio_operation_output",
                                  "execute_audio_operation", "execute_audio_operation_metadata", "bytes", "bytearray", "memoryview",
                                  "Audio", "wave", "pydub", "numpy"})
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertFalse(attrs & {"read", "write", "trim", "convert", "mix", "decode", "lower", "upper", "casefold", "strip"})
        mutable = [n for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.value, (ast.List, ast.Dict, ast.Set))]
        self.assertEqual(mutable, [])

    def test_62_earlier_modules_are_unaware_of_the_pipeline(self):
        for name in ("audio_asset.py", "audio_asset_registry.py", "audio_operation_request.py", "audio_operation_validator.py",
                     "audio_operation_plan.py", "audio_operation_executor.py", "audio_operation_output.py",
                     "audio_operation_output_validator.py", "audio_operation_metadata_executor.py", "audio_operation_dispatcher.py"):
            with open(os.path.join(PY_ROOT, "multimedia", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("audio_operation_pipeline", "process_audio_operation", "AudioOperationPipelineResult"):
                self.assertNotIn(token, text, name)

    def test_63_not_wired_into_the_runtime(self):
        for folder in ("core", "planning", "agent", "game_creation"):
            for root, _dirs, files in os.walk(os.path.join(PY_ROOT, folder)):
                for f in files:
                    if f.endswith(".py"):
                        with open(os.path.join(root, f), encoding="utf-8") as fh:
                            text = fh.read()
                        self.assertNotIn("audio_operation_pipeline", text, os.path.join(root, f))
        with open(os.path.join(PY_ROOT, "multimedia", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_64_multimedia_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "multimedia")) if f != "__pycache__"),
                         ["__init__.py", "audio_asset.py", "audio_asset_registry.py", "audio_operation_batch.py", "audio_operation_batch_summary.py", "audio_operation_dispatcher.py", "audio_operation_executor.py",
                          "audio_operation_metadata_executor.py", "audio_operation_output.py", "audio_operation_output_validator.py",
                          "audio_operation_pipeline.py", "audio_operation_plan.py", "audio_operation_request.py", "audio_operation_validator.py",
                          "image_asset.py", "image_asset_registry.py", "image_operation_batch.py", "image_operation_batch_summary.py",
                          "image_operation_dispatcher.py", "image_operation_executor.py", "image_operation_metadata_executor.py",
                          "image_operation_output.py", "image_operation_output_validator.py", "image_operation_pipeline.py",
                          "image_operation_plan.py", "image_operation_request.py", "image_operation_validator.py"])

    def test_65_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("AudioOperationPipelineResult", "process_audio_operation", P, "INVALID_REQUEST", "INVALID_REGISTRY", "VALIDATION_FAILED",
                       "PLAN_FAILED", "DISPATCH_FAILED", "OUTPUT_VALIDATION_FAILED", "validate_audio_operation_request",
                       "create_audio_operation_plan", "dispatch_audio_operation", "validate_audio_operation_output", "does NOT",
                       "Prompt 770", "has **not** been started"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
