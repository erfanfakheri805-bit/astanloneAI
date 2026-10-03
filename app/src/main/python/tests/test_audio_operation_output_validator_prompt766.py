"""Prompt 766 - Section 8 audio operation output validator (`multimedia.audio_operation_output_validator`)."""
import ast
import copy
import hashlib
import os
import pickle
import unittest

from multimedia import audio_operation_output_validator as v
from multimedia.audio_asset import create_audio_asset
from multimedia.audio_asset_registry import create_audio_asset_registry
from multimedia.audio_operation_output import AudioOperationOutput, create_audio_operation_output
from multimedia.audio_operation_output_validator import AudioOperationOutputValidationResult, validate_audio_operation_output
from multimedia.audio_operation_plan import AudioOperationPlan, create_audio_operation_plan
from multimedia.audio_operation_request import create_audio_operation_request
from multimedia.audio_operation_validator import validate_audio_operation_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section8_audio_operation_output_validator_prompt766.md")
MODULE = os.path.join(PY_ROOT, "multimedia", "audio_operation_output_validator.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
P = "AUDIO_OPERATION_OUTPUT_VALIDATION_"
ALL_CODES = [P + c for c in ("INVALID_PLAN", "INVALID_OUTPUT", "AUDIO_ID_MISMATCH", "OPERATION_MISMATCH", "FORMAT_MISMATCH",
                             "DURATION_MS_MISMATCH", "SAMPLE_RATE_MISMATCH")]
OUT_FIELDS = ("audio_id", "operation", "output_format", "duration_ms", "sample_rate")
CHANGED = {"audio_id": "x", "operation": "y", "output_format": "z", "duration_ms": 1, "sample_rate": 2}


def make_plan(**over):
    data = {"audio_id": "theme", "operation": "trim", "target_format": "mp3", "duration_ms": 1000, "sample_rate": 22050, "quality": 70}
    data.update(over)
    asset = create_audio_asset({"audio_id": data["audio_id"], "name": "N", "description": "", "format": "ogg", "duration_ms": 5000, "sample_rate": 44100})
    assert asset.ok, asset.failures
    registry = create_audio_asset_registry([asset.asset])
    assert registry.ok, registry.failures
    req = create_audio_operation_request(data)
    assert req.ok, req.failures
    validation = validate_audio_operation_request(req.request, registry.registry)
    assert validation.ok, validation.codes()
    res = create_audio_operation_plan(validation)
    assert res.ok, res.codes()
    return res.plan


def make_output(**over):
    data = {"audio_id": "theme", "operation": "trim", "output_format": "mp3", "duration_ms": 1000, "sample_rate": 22050}
    data.update(over)
    res = create_audio_operation_output(data)
    assert res.ok, res.failures
    return res.output


def run(plan_over=None, out_over=None):
    return validate_audio_operation_output(make_plan(**(plan_over or {})), make_output(**(out_over or {})))


class TestValid(unittest.TestCase):
    def test_1_valid_match(self):
        res = run()
        self.assertIs(type(res), AudioOperationOutputValidationResult)
        self.assertIs(res.ok, True)
        self.assertEqual(res.failures, ())
        self.assertEqual(res.codes(), [])

    def test_2_exact_identity_preserved_on_success(self):
        plan, output = make_plan(), make_output()
        res = validate_audio_operation_output(plan, output)
        self.assertTrue(res.ok)
        self.assertIs(res.plan, plan)
        self.assertIs(res.output, output)

    def test_3_equal_but_distinct_objects_match(self):
        plan, output = make_plan(), make_output()
        self.assertIsNot(make_plan(), plan)
        self.assertTrue(validate_audio_operation_output(make_plan(), output).ok)
        self.assertTrue(validate_audio_operation_output(plan, make_output()).ok)

    def test_4_to_dict_of_success(self):
        res = run()
        self.assertEqual(res.to_dict(), {"ok": True, "plan": make_plan().to_dict(), "output": make_output().to_dict(), "failures": []})
        self.assertEqual(list(res.to_dict()), ["ok", "plan", "output", "failures"])

    def test_5_whitespace_values_that_match_exactly_are_ok(self):
        res = run({"operation": "  fade\t", "target_format": " WAV "}, {"operation": "  fade\t", "output_format": " WAV "})
        self.assertTrue(res.ok, res.codes())


class TestInvalidPlan(unittest.TestCase):
    def test_6_invalid_plan(self):
        for bad in (None, {}, make_plan().to_dict(), "plan", 1, True, make_output()):
            with self.subTest(bad=type(bad).__name__):
                res = validate_audio_operation_output(bad, make_output())
                self.assertFalse(res.ok)
                self.assertEqual(res.codes(), [P + "INVALID_PLAN"])
                self.assertIsNone(res.plan)
                self.assertIsNone(res.output)

    def test_7_invalid_plan_does_not_cross_validate_or_keep_output(self):
        res = validate_audio_operation_output(object(), make_output(audio_id="other", duration_ms=1))
        self.assertEqual(res.codes(), [P + "INVALID_PLAN"])
        self.assertIsNone(res.output)
        self.assertEqual(res.to_dict(), {"ok": False, "plan": None, "output": None,
                                         "failures": [{"code": P + "INVALID_PLAN", "field": "plan",
                                                       "message": "plan must be exactly an AudioOperationPlan."}]})

    def test_8_invalid_plan_wins_when_output_is_also_invalid(self):
        for bad_out in (None, 3, make_plan()):
            res = validate_audio_operation_output(None, bad_out)
            self.assertEqual(res.codes(), [P + "INVALID_PLAN"])
            self.assertIsNone(res.plan)
            self.assertIsNone(res.output)

    def test_9_look_alike_plan_rejected_and_subclassing_refused(self):
        with self.assertRaises(TypeError):
            type("PlanSub", (AudioOperationPlan,), {})

        class FakePlan:
            audio_id, operation, target_format, duration_ms, sample_rate, quality = "theme", "trim", "mp3", 1000, 22050, 70

        res = validate_audio_operation_output(FakePlan(), make_output())
        self.assertEqual(res.codes(), [P + "INVALID_PLAN"])


class TestInvalidOutput(unittest.TestCase):
    def test_10_invalid_output_preserves_exact_plan(self):
        plan = make_plan()
        for bad in (None, {}, make_output().to_dict(), "out", 1.5, False, plan):
            with self.subTest(bad=type(bad).__name__):
                res = validate_audio_operation_output(plan, bad)
                self.assertFalse(res.ok)
                self.assertEqual(res.codes(), [P + "INVALID_OUTPUT"])
                self.assertIs(res.plan, plan)
                self.assertIsNone(res.output)

    def test_11_invalid_output_to_dict_and_failure_shape(self):
        res = validate_audio_operation_output(make_plan(), None)
        self.assertEqual(res.to_dict(), {"ok": False, "plan": make_plan().to_dict(), "output": None,
                                         "failures": [{"code": P + "INVALID_OUTPUT", "field": "output",
                                                       "message": "output must be exactly an AudioOperationOutput."}]})
        self.assertEqual(sorted(res.failures[0]), ["code", "field", "message"])

    def test_12_look_alike_output_and_result_wrapper_rejected(self):
        with self.assertRaises(TypeError):
            type("OutSub", (AudioOperationOutput,), {})

        class FakeOutput:
            audio_id, operation, output_format, duration_ms, sample_rate = "theme", "trim", "mp3", 1000, 22050

        self.assertEqual(validate_audio_operation_output(make_plan(), FakeOutput()).codes(), [P + "INVALID_OUTPUT"])
        wrapper = create_audio_operation_output({"audio_id": "a", "operation": "b", "output_format": "c", "duration_ms": 1, "sample_rate": 1})
        self.assertEqual(validate_audio_operation_output(make_plan(), wrapper).codes(), [P + "INVALID_OUTPUT"])

    def test_13_never_raises_for_odd_inputs(self):
        odd = (None, 0, "", b"", [], {}, object(), float("nan"), AudioOperationOutputValidationResult)
        for a in odd:
            for b in odd:
                with self.subTest(a=type(a).__name__, b=type(b).__name__):
                    res = validate_audio_operation_output(a, b)
                    self.assertEqual(res.codes(), [P + "INVALID_PLAN"])
                    self.assertIsNone(res.plan)
                    self.assertIsNone(res.output)


class TestMismatches(unittest.TestCase):
    def test_14_audio_id_mismatch(self):
        res = run(out_over={"audio_id": "other"})
        self.assertFalse(res.ok)
        self.assertEqual(res.codes(), [P + "AUDIO_ID_MISMATCH"])
        self.assertEqual(res.failures[0]["field"], "audio_id")

    def test_15_operation_mismatch(self):
        res = run(out_over={"operation": "fade"})
        self.assertEqual(res.codes(), [P + "OPERATION_MISMATCH"])
        self.assertEqual(res.failures[0]["field"], "operation")

    def test_16_format_mismatch(self):
        res = run(out_over={"output_format": "wav"})
        self.assertEqual(res.codes(), [P + "FORMAT_MISMATCH"])
        self.assertEqual(res.failures[0]["field"], "output_format")

    def test_17_duration_ms_mismatch(self):
        res = run(out_over={"duration_ms": 1001})
        self.assertEqual(res.codes(), [P + "DURATION_MS_MISMATCH"])
        self.assertEqual(res.failures[0]["field"], "duration_ms")

    def test_18_sample_rate_mismatch(self):
        res = run(out_over={"sample_rate": 44100})
        self.assertEqual(res.codes(), [P + "SAMPLE_RATE_MISMATCH"])
        self.assertEqual(res.failures[0]["field"], "sample_rate")

    def test_19_mismatch_keeps_both_exact_objects(self):
        plan, output = make_plan(), make_output(duration_ms=1)
        res = validate_audio_operation_output(plan, output)
        self.assertFalse(res.ok)
        self.assertIs(res.plan, plan)
        self.assertIs(res.output, output)

    def test_20_all_mismatches_together_in_exact_order(self):
        res = run(out_over=CHANGED)
        self.assertEqual(res.codes(), ALL_CODES[2:])
        self.assertEqual([f["field"] for f in res.failures], ["audio_id", "operation", "output_format", "duration_ms", "sample_rate"])

    def test_21_every_subset_reports_in_fixed_order(self):
        for mask in range(1, 32):
            over = {n: CHANGED[n] for i, n in enumerate(OUT_FIELDS) if mask >> i & 1}
            expected = [ALL_CODES[2 + i] for i in range(5) if mask >> i & 1]
            with self.subTest(mask=mask):
                self.assertEqual(run(out_over=over).codes(), expected)

    def test_22_order_independent_of_how_output_was_built(self):
        scrambled = {"sample_rate": 2, "duration_ms": 1, "output_format": "z", "operation": "y", "audio_id": "x"}
        self.assertEqual(run(out_over=scrambled).codes(), ALL_CODES[2:])

    def test_23_quality_is_ignored(self):
        a = validate_audio_operation_output(make_plan(quality=1), make_output())
        b = validate_audio_operation_output(make_plan(quality=100), make_output())
        self.assertTrue(a.ok and b.ok)
        self.assertNotEqual(a, b)   # plans differ by value, outcome does not
        self.assertEqual((a.ok, a.codes()), (b.ok, b.codes()))
        self.assertFalse(hasattr(AudioOperationOutput, "quality"))
        self.assertNotIn("quality", [c[1] for c in v.COMPARISONS] + [c[2] for c in v.COMPARISONS])
        self.assertEqual(run({"quality": 3}, CHANGED).codes(), ALL_CODES[2:])

    def test_24_exact_case_sensitive_and_untrimmed(self):
        for field, value in (("audio_id", "THEME"), ("operation", "Trim"), ("output_format", "MP3"),
                             ("audio_id", "theme "), ("operation", " trim"), ("output_format", "mp3\n")):
            with self.subTest(field=field, value=value):
                res = run(out_over={field: value})
                self.assertFalse(res.ok)
                self.assertEqual(len(res.codes()), 1)

    def test_25_no_coercion_or_aliasing_of_values(self):
        self.assertFalse(run({"target_format": "mpeg"}, {"output_format": "mp3"}).ok)
        self.assertFalse(run({"duration_ms": 10}, {"duration_ms": 11}).ok)
        self.assertFalse(run({"sample_rate": 8000}, {"sample_rate": 8001}).ok)

    def test_26_mismatch_messages_are_deterministic(self):
        a = run(out_over={"duration_ms": 5, "sample_rate": 6})
        b = run(out_over={"duration_ms": 5, "sample_rate": 6})
        self.assertEqual(a.failures, b.failures)
        self.assertIn("duration_ms", a.failures[0]["message"])
        self.assertIn("sample_rate", a.failures[1]["message"])


class TestResultContract(unittest.TestCase):
    def test_27_immutable(self):
        res = run()
        for name in ("ok", "plan", "output", "failures", "extra", "_failures"):
            with self.subTest(name=name):
                with self.assertRaises(AttributeError):
                    setattr(res, name, 1)
                with self.assertRaises(AttributeError):
                    delattr(res, name)
        self.assertFalse(hasattr(res, "__dict__"))
        self.assertEqual(AudioOperationOutputValidationResult.__slots__, ("_plan", "_output", "_failures"))

    def test_28_direct_construction_and_subclassing_refused(self):
        with self.assertRaises(TypeError):
            AudioOperationOutputValidationResult(object(), make_plan(), make_output(), ())
        with self.assertRaises(TypeError):
            AudioOperationOutputValidationResult(None, None, None, ())
        with self.assertRaises(TypeError):
            AudioOperationOutputValidationResult()
        with self.assertRaises(TypeError):
            type("Sub", (AudioOperationOutputValidationResult,), {})

    def test_29_equality_and_hash(self):
        a, b = run(), run()
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        m1, m2 = run(out_over={"duration_ms": 1}), run(out_over={"duration_ms": 1})
        self.assertEqual(m1, m2)
        self.assertEqual(hash(m1), hash(m2))
        self.assertNotEqual(a, m1)
        self.assertNotEqual(run(out_over={"duration_ms": 1}), run(out_over={"sample_rate": 1}))
        self.assertNotEqual(a, a.to_dict())
        self.assertFalse(a == object())
        self.assertEqual(validate_audio_operation_output(None, None), validate_audio_operation_output(1, 2))
        self.assertEqual(hash(validate_audio_operation_output(None, None)), hash(validate_audio_operation_output(1, 2)))
        self.assertNotEqual(validate_audio_operation_output(None, make_output()), validate_audio_operation_output(make_plan(), None))

    def test_30_fresh_to_dict_and_failures(self):
        res = run(out_over={"duration_ms": 1})
        d1, d2 = res.to_dict(), res.to_dict()
        self.assertEqual(d1, d2)
        self.assertIsNot(d1, d2)
        self.assertIsNot(d1["plan"], d2["plan"])
        self.assertIsNot(d1["output"], d2["output"])
        self.assertIsNot(d1["failures"], d2["failures"])
        self.assertIsNot(d1["failures"][0], d2["failures"][0])
        d1["ok"] = True
        d1["plan"]["duration_ms"] = -1
        d1["output"]["duration_ms"] = -1
        d1["failures"].append("x")
        d1["failures"][0]["code"] = "changed"
        self.assertEqual(res.to_dict(), d2)
        f1, f2 = res.failures, res.failures
        self.assertIsNot(f1[0], f2[0])
        f1[0]["code"] = "changed"
        self.assertEqual(res.codes(), [P + "DURATION_MS_MISMATCH"])
        c1 = res.codes()
        c1.append("x")
        self.assertEqual(res.codes(), [P + "DURATION_MS_MISMATCH"])
        self.assertIsInstance(res.failures, tuple)

    def test_31_copy_and_deepcopy_return_same_object(self):
        for res in (run(), run(out_over={"duration_ms": 1}), validate_audio_operation_output(None, None), validate_audio_operation_output(make_plan(), 1)):
            self.assertIs(copy.copy(res), res)
            self.assertIs(copy.deepcopy(res), res)
            self.assertIs(copy.deepcopy({"k": [res]})["k"][0], res)

    def test_32_pickle_refused(self):
        for res in (run(), validate_audio_operation_output(None, None)):
            for proto in range(0, pickle.HIGHEST_PROTOCOL + 1):
                with self.subTest(proto=proto):
                    with self.assertRaises(TypeError):
                        pickle.dumps(res, protocol=proto)

    def test_33_repr_is_deterministic_and_small(self):
        self.assertEqual(repr(run()), "AudioOperationOutputValidationResult(ok=True, codes=[])")
        self.assertEqual(repr(run(out_over={"sample_rate": 1})),
                         "AudioOperationOutputValidationResult(ok=False, codes=['%sSAMPLE_RATE_MISMATCH'])" % P)

    def test_34_failure_codes_and_comparisons_are_stable(self):
        self.assertEqual(list(v.FAILURE_CODES), ALL_CODES)
        self.assertEqual(len(set(v.FAILURE_CODES)), 7)
        self.assertTrue(all(c.startswith(P) for c in v.FAILURE_CODES))
        self.assertEqual(list(v.COMPARISONS),
                         [(ALL_CODES[2], "audio_id", "audio_id"), (ALL_CODES[3], "operation", "operation"),
                          (ALL_CODES[4], "target_format", "output_format"), (ALL_CODES[5], "duration_ms", "duration_ms"),
                          (ALL_CODES[6], "sample_rate", "sample_rate")])


class TestPurityAndDeterminism(unittest.TestCase):
    def test_35_no_mutation_of_plan_or_output(self):
        plan, output = make_plan(quality=7), make_output(duration_ms=3)
        plan_before, output_before = plan.to_dict(), output.to_dict()
        plan_hash, output_hash = hash(plan), hash(output)
        res = validate_audio_operation_output(plan, output)
        self.assertFalse(res.ok)
        self.assertEqual(plan.to_dict(), plan_before)
        self.assertEqual(output.to_dict(), output_before)
        self.assertEqual((hash(plan), hash(output)), (plan_hash, output_hash))
        self.assertEqual(plan, make_plan(quality=7))
        self.assertEqual(output, make_output(duration_ms=3))

    def test_36_deterministic_repeated_validation(self):
        plan, output = make_plan(), make_output(operation="x", sample_rate=2)
        first = validate_audio_operation_output(plan, output)
        for _ in range(25):
            again = validate_audio_operation_output(plan, output)
            self.assertEqual(again, first)
            self.assertEqual(again.codes(), first.codes())
            self.assertEqual(again.to_dict(), first.to_dict())
            self.assertEqual(hash(again), hash(first))
        ok1 = validate_audio_operation_output(make_plan(), make_output())
        self.assertEqual([validate_audio_operation_output(make_plan(), make_output()) for _ in range(5)], [ok1] * 5)

    def test_37_module_imports_only_plan_and_output_types_and_does_no_io(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual([(n.module, sorted(a.name for a in n.names)) for n in imports],
                         [("audio_operation_output", ["AudioOperationOutput"]), ("audio_operation_plan", ["AudioOperationPlan"])])
        self.assertTrue(all(isinstance(n, ast.ImportFrom) and n.level == 1 for n in imports))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"open", "os", "io", "subprocess", "socket", "random", "time", "pathlib", "AudioAsset", "AudioAssetRegistry",
                                  "AudioOperationRequest", "AudioOperationExecutionResult", "bytes", "bytearray", "memoryview"})
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertFalse(attrs & {"read", "write", "decode", "encode", "quality", "lower", "upper", "casefold", "strip"})
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value == "quality"])

    def test_38_earlier_production_modules_are_unaware_of_the_validator(self):
        for name in ("audio_asset.py", "audio_asset_registry.py", "audio_operation_request.py", "audio_operation_validator.py",
                     "audio_operation_plan.py", "audio_operation_executor.py", "audio_operation_metadata_executor.py", "audio_operation_output.py", "image_operation_output_validator.py"):
            with open(os.path.join(PY_ROOT, "multimedia", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("audio_operation_output_validator", "validate_audio_operation_output", "AudioOperationOutputValidationResult"):
                self.assertNotIn(token, text, name)

    def test_39_multimedia_package_holds_exactly_the_expected_files(self):
        names = sorted(f for f in os.listdir(os.path.join(PY_ROOT, "multimedia")) if f != "__pycache__")
        self.assertEqual([n for n in names if n.startswith("audio_")],
                         ["audio_asset.py", "audio_asset_registry.py", "audio_operation_batch.py", "audio_operation_batch_summary.py", "audio_operation_dispatcher.py", "audio_operation_executor.py", "audio_operation_metadata_executor.py", "audio_operation_output.py",
                          "audio_operation_output_validator.py", "audio_operation_pipeline.py", "audio_operation_plan.py", "audio_operation_request.py",
                          "audio_operation_validator.py"])
        self.assertEqual(len([n for n in names if n.startswith("image_")]), 13)
        with open(os.path.join(PY_ROOT, "multimedia", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_40_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("AudioOperationOutputValidationResult", "validate_audio_operation_output", P, "INVALID_PLAN", "INVALID_OUTPUT",
                       "AUDIO_ID_MISMATCH", "OPERATION_MISMATCH", "FORMAT_MISMATCH", "DURATION_MS_MISMATCH", "SAMPLE_RATE_MISMATCH",
                       "quality", "does NOT", "Prompt 767", "target_format", "output_format"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
