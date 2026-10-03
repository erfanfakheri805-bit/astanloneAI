"""Prompt 753 - Section 8 image operation output validator (`multimedia.image_operation_output_validator`)."""
import ast
import copy
import hashlib
import os
import pickle
import unittest

from multimedia import image_operation_output_validator as v
from multimedia.image_asset import create_image_asset
from multimedia.image_asset_registry import create_image_asset_registry
from multimedia.image_operation_output import ImageOperationOutput, create_image_operation_output
from multimedia.image_operation_output_validator import ImageOperationOutputValidationResult, validate_image_operation_output
from multimedia.image_operation_plan import ImageOperationPlan, create_image_operation_plan
from multimedia.image_operation_request import create_image_operation_request
from multimedia.image_operation_validator import validate_image_operation_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section8_image_operation_output_validator_prompt753.md")
MODULE = os.path.join(PY_ROOT, "multimedia", "image_operation_output_validator.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
P = "IMAGE_OPERATION_OUTPUT_VALIDATION_"
ALL_CODES = [P + c for c in ("INVALID_PLAN", "INVALID_OUTPUT", "IMAGE_ID_MISMATCH", "OPERATION_MISMATCH", "FORMAT_MISMATCH",
                             "WIDTH_MISMATCH", "HEIGHT_MISMATCH")]


def make_plan(**over):
    data = {"image_id": "hero", "operation": "resize", "target_format": "webp", "width": 800, "height": 600, "quality": 85}
    data.update(over)
    asset = create_image_asset({"image_id": data["image_id"], "name": "N", "description": "", "format": "png", "width": 10, "height": 10})
    assert asset.ok, asset.failures
    registry = create_image_asset_registry([asset.asset])
    assert registry.ok, registry.failures
    req = create_image_operation_request(data)
    assert req.ok, req.failures
    validation = validate_image_operation_request(req.request, registry.registry)
    assert validation.ok, validation.failures
    res = create_image_operation_plan(validation)
    assert res.ok, res.failures
    return res.plan


def make_output(**over):
    data = {"image_id": "hero", "operation": "resize", "output_format": "webp", "width": 800, "height": 600}
    data.update(over)
    res = create_image_operation_output(data)
    assert res.ok, res.failures
    return res.output


def run(plan_over=None, out_over=None):
    return validate_image_operation_output(make_plan(**(plan_over or {})), make_output(**(out_over or {})))


class TestValid(unittest.TestCase):
    def test_1_valid_matching_plan_and_output(self):
        res = run()
        self.assertIs(type(res), ImageOperationOutputValidationResult)
        self.assertIs(res.ok, True)
        self.assertEqual(res.failures, ())
        self.assertEqual(res.codes(), [])

    def test_2_exact_object_identity_preserved(self):
        plan, output = make_plan(), make_output()
        res = validate_image_operation_output(plan, output)
        self.assertTrue(res.ok)
        self.assertIs(res.plan, plan)
        self.assertIs(res.output, output)

    def test_3_equal_but_distinct_objects_match(self):
        plan, output = make_plan(), make_output()
        self.assertIsNot(make_plan(), plan)
        self.assertTrue(validate_image_operation_output(make_plan(), output).ok)
        self.assertTrue(validate_image_operation_output(plan, make_output()).ok)

    def test_4_to_dict_of_success(self):
        res = run()
        self.assertEqual(res.to_dict(), {"ok": True, "plan": make_plan().to_dict(), "output": make_output().to_dict(), "failures": []})
        self.assertEqual(list(res.to_dict()), ["ok", "plan", "output", "failures"])

    def test_5_whitespace_values_that_match_exactly_are_ok(self):
        res = run({"operation": "  blur\t", "target_format": " WebP "}, {"operation": "  blur\t", "output_format": " WebP "})
        self.assertTrue(res.ok, res.codes())


class TestInvalidInputs(unittest.TestCase):
    def test_6_invalid_plan(self):
        for bad in (None, {}, make_plan().to_dict(), "plan", 1, make_output()):
            with self.subTest(bad=type(bad).__name__):
                res = validate_image_operation_output(bad, make_output())
                self.assertFalse(res.ok)
                self.assertEqual(res.codes(), [P + "INVALID_PLAN"])
                self.assertIsNone(res.plan)
                self.assertIs(type(res.output), ImageOperationOutput)

    def test_7_invalid_output(self):
        for bad in (None, {}, make_output().to_dict(), "out", 1.5, make_plan()):
            with self.subTest(bad=type(bad).__name__):
                res = validate_image_operation_output(make_plan(), bad)
                self.assertFalse(res.ok)
                self.assertEqual(res.codes(), [P + "INVALID_OUTPUT"])
                self.assertIsNone(res.output)
                self.assertIs(type(res.plan), ImageOperationPlan)

    def test_8_both_invalid_reports_plan_first_and_no_cross_validation(self):
        res = validate_image_operation_output(None, None)
        self.assertEqual(res.codes(), [P + "INVALID_PLAN", P + "INVALID_OUTPUT"])
        self.assertIsNone(res.plan)
        self.assertIsNone(res.output)
        self.assertEqual(res.to_dict()["plan"], None)

    def test_9_invalid_input_skips_cross_validation(self):
        # a valid-looking mismatching output must not produce mismatch codes when the plan is invalid
        res = validate_image_operation_output(object(), make_output(image_id="other", width=1))
        self.assertEqual(res.codes(), [P + "INVALID_PLAN"])
        res = validate_image_operation_output(make_plan(), object())
        self.assertEqual(res.codes(), [P + "INVALID_OUTPUT"])

    def test_10_failure_fields_and_shape(self):
        res = validate_image_operation_output(None, None)
        self.assertEqual([(f["code"], f["field"]) for f in res.failures], [(P + "INVALID_PLAN", "plan"), (P + "INVALID_OUTPUT", "output")])
        for f in res.failures:
            self.assertEqual(sorted(f), ["code", "field", "message"])
            self.assertIs(type(f["message"]), str)

    def test_11_subclasses_rejected(self):
        # the model classes refuse subclassing, so an impostor can only be a look-alike object
        with self.assertRaises(TypeError):
            type("PlanSub", (ImageOperationPlan,), {})
        with self.assertRaises(TypeError):
            type("OutSub", (ImageOperationOutput,), {})

        class FakePlan:
            image_id, operation, target_format, width, height, quality = "hero", "resize", "webp", 800, 600, 85

        class FakeOutput:
            image_id, operation, output_format, width, height = "hero", "resize", "webp", 800, 600

        self.assertEqual(validate_image_operation_output(FakePlan(), make_output()).codes(), [P + "INVALID_PLAN"])
        self.assertEqual(validate_image_operation_output(make_plan(), FakeOutput()).codes(), [P + "INVALID_OUTPUT"])
        self.assertEqual(validate_image_operation_output(FakePlan(), FakeOutput()).codes(), [P + "INVALID_PLAN", P + "INVALID_OUTPUT"])

    def test_12_result_of_other_result_types_rejected(self):
        res_plan = create_image_operation_output({"image_id": "a", "operation": "b", "output_format": "c", "width": 1, "height": 1})
        self.assertEqual(validate_image_operation_output(make_plan(), res_plan).codes(), [P + "INVALID_OUTPUT"])


class TestMismatches(unittest.TestCase):
    def test_13_image_id_mismatch(self):
        res = run(out_over={"image_id": "other"})
        self.assertFalse(res.ok)
        self.assertEqual(res.codes(), [P + "IMAGE_ID_MISMATCH"])
        self.assertEqual(res.failures[0]["field"], "image_id")

    def test_14_operation_mismatch(self):
        res = run(out_over={"operation": "crop"})
        self.assertEqual(res.codes(), [P + "OPERATION_MISMATCH"])
        self.assertEqual(res.failures[0]["field"], "operation")

    def test_15_format_mismatch(self):
        res = run(out_over={"output_format": "png"})
        self.assertEqual(res.codes(), [P + "FORMAT_MISMATCH"])
        self.assertEqual(res.failures[0]["field"], "output_format")

    def test_16_width_mismatch(self):
        res = run(out_over={"width": 801})
        self.assertEqual(res.codes(), [P + "WIDTH_MISMATCH"])
        self.assertEqual(res.failures[0]["field"], "width")

    def test_17_height_mismatch(self):
        res = run(out_over={"height": 599})
        self.assertEqual(res.codes(), [P + "HEIGHT_MISMATCH"])
        self.assertEqual(res.failures[0]["field"], "height")

    def test_18_mismatch_result_keeps_both_exact_objects(self):
        plan, output = make_plan(), make_output(width=1)
        res = validate_image_operation_output(plan, output)
        self.assertFalse(res.ok)
        self.assertIs(res.plan, plan)
        self.assertIs(res.output, output)

    def test_19_multiple_mismatches_in_fixed_field_order(self):
        res = run(out_over={"height": 1, "output_format": "png", "image_id": "x"})
        self.assertEqual(res.codes(), [P + "IMAGE_ID_MISMATCH", P + "FORMAT_MISMATCH", P + "HEIGHT_MISMATCH"])

    def test_20_all_five_mismatch_together(self):
        res = run(out_over={"image_id": "x", "operation": "y", "output_format": "z", "width": 1, "height": 2})
        self.assertEqual(res.codes(), ALL_CODES[2:])

    def test_21_every_subset_reports_in_fixed_order(self):
        names = ["image_id", "operation", "output_format", "width", "height"]
        changed = {"image_id": "x", "operation": "y", "output_format": "z", "width": 1, "height": 2}
        for mask in range(1, 32):
            over = {n: changed[n] for i, n in enumerate(names) if mask >> i & 1}
            expected = [ALL_CODES[2 + i] for i in range(5) if mask >> i & 1]
            with self.subTest(mask=mask):
                self.assertEqual(run(out_over=over).codes(), expected)

    def test_22_quality_is_intentionally_ignored(self):
        self.assertTrue(validate_image_operation_output(make_plan(quality=1), make_output()).ok)
        self.assertTrue(validate_image_operation_output(make_plan(quality=100), make_output()).ok)
        a = validate_image_operation_output(make_plan(quality=1), make_output())
        b = validate_image_operation_output(make_plan(quality=100), make_output())
        self.assertNotEqual(a, b)   # plans differ (value equality), but validation outcome is the same
        self.assertEqual((a.ok, a.codes()), (b.ok, b.codes()))
        self.assertFalse(hasattr(ImageOperationOutput, "quality"))
        self.assertNotIn("quality", [c[1] for c in v.COMPARISONS] + [c[2] for c in v.COMPARISONS])

    def test_23_exact_case_sensitive_matching(self):
        for field, value in (("image_id", "HERO"), ("operation", "Resize"), ("output_format", "WEBP")):
            with self.subTest(field=field):
                res = run(out_over={field: value})
                self.assertFalse(res.ok)
                self.assertEqual(len(res.codes()), 1)

    def test_24_no_trimming_or_normalization(self):
        for field, value in (("image_id", "hero "), ("operation", " resize"), ("output_format", "webp\n")):
            with self.subTest(field=field):
                self.assertFalse(run(out_over={field: value}).ok)
        self.assertFalse(run({"operation": "blur"}, {"operation": "blur "}).ok)

    def test_25_no_coercion_of_values(self):
        # plan target_format vs output output_format are compared as exact values, nothing is converted
        self.assertFalse(run({"target_format": "jpg"}, {"output_format": "jpeg"}).ok)
        self.assertFalse(run({"width": 10}, {"width": 11}).ok)

    def test_26_mismatch_messages_are_deterministic(self):
        a = run(out_over={"width": 5, "height": 6})
        b = run(out_over={"width": 5, "height": 6})
        self.assertEqual(a.failures, b.failures)
        self.assertIn("width", a.failures[0]["message"])


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
        self.assertEqual(ImageOperationOutputValidationResult.__slots__, ("_plan", "_output", "_failures"))

    def test_28_direct_construction_refused(self):
        with self.assertRaises(TypeError):
            ImageOperationOutputValidationResult(object(), make_plan(), make_output(), ())
        with self.assertRaises(TypeError):
            ImageOperationOutputValidationResult(None, None, None, ())
        with self.assertRaises(TypeError):
            ImageOperationOutputValidationResult()

    def test_29_subclassing_refused(self):
        with self.assertRaises(TypeError):
            type("Sub", (ImageOperationOutputValidationResult,), {})

    def test_30_equality_and_hash(self):
        a, b = run(), run()
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        m1, m2 = run(out_over={"width": 1}), run(out_over={"width": 1})
        self.assertEqual(m1, m2)
        self.assertEqual(hash(m1), hash(m2))
        self.assertNotEqual(a, m1)
        self.assertNotEqual(run(out_over={"width": 1}), run(out_over={"height": 1}))
        self.assertNotEqual(a, run({"image_id": "hero", "width": 1}, {"width": 1}))
        self.assertNotEqual(a, a.to_dict())
        self.assertFalse(a == object())
        self.assertEqual(hash(validate_image_operation_output(None, None)), hash(validate_image_operation_output(1, 2)))

    def test_31_fresh_to_dict_and_failures(self):
        res = run(out_over={"width": 1})
        d1, d2 = res.to_dict(), res.to_dict()
        self.assertEqual(d1, d2)
        self.assertIsNot(d1, d2)
        self.assertIsNot(d1["plan"], d2["plan"])
        self.assertIsNot(d1["output"], d2["output"])
        self.assertIsNot(d1["failures"], d2["failures"])
        self.assertIsNot(d1["failures"][0], d2["failures"][0])
        d1["ok"] = True
        d1["plan"]["width"] = -1
        d1["output"]["width"] = -1
        d1["failures"].append("x")
        d1["failures"][0]["code"] = "changed"
        self.assertEqual(res.to_dict(), d2)
        f1, f2 = res.failures, res.failures
        self.assertIsNot(f1[0], f2[0])
        f1[0]["code"] = "changed"
        self.assertEqual(res.codes(), [P + "WIDTH_MISMATCH"])
        c1 = res.codes()
        c1.append("x")
        self.assertEqual(res.codes(), [P + "WIDTH_MISMATCH"])
        self.assertIsInstance(res.failures, tuple)

    def test_32_to_dict_of_failure_with_invalid_inputs(self):
        self.assertEqual(validate_image_operation_output(None, make_output()).to_dict(),
                         {"ok": False, "plan": None, "output": make_output().to_dict(),
                          "failures": [{"code": P + "INVALID_PLAN", "field": "plan", "message": "plan must be exactly an ImageOperationPlan."}]})

    def test_33_copy_and_deepcopy_return_same_object(self):
        for res in (run(), run(out_over={"width": 1}), validate_image_operation_output(None, None)):
            self.assertIs(copy.copy(res), res)
            self.assertIs(copy.deepcopy(res), res)
            self.assertIs(copy.deepcopy({"k": [res]})["k"][0], res)

    def test_34_pickle_refused(self):
        res = run()
        for proto in range(0, pickle.HIGHEST_PROTOCOL + 1):
            with self.subTest(proto=proto):
                with self.assertRaises(TypeError):
                    pickle.dumps(res, protocol=proto)

    def test_35_repr_is_deterministic_and_small(self):
        self.assertEqual(repr(run()), "ImageOperationOutputValidationResult(ok=True, codes=[])")
        self.assertEqual(repr(run(out_over={"width": 1})), "ImageOperationOutputValidationResult(ok=False, codes=['%sWIDTH_MISMATCH'])" % P)

    def test_36_failure_codes_are_stable(self):
        self.assertEqual(list(v.FAILURE_CODES), ALL_CODES)
        self.assertEqual(len(set(v.FAILURE_CODES)), 7)
        self.assertTrue(all(c.startswith(P) for c in v.FAILURE_CODES))
        self.assertEqual([(c, p, o) for c, p, o in v.COMPARISONS],
                         [(ALL_CODES[2], "image_id", "image_id"), (ALL_CODES[3], "operation", "operation"),
                          (ALL_CODES[4], "target_format", "output_format"), (ALL_CODES[5], "width", "width"), (ALL_CODES[6], "height", "height")])


class TestPurityAndDeterminism(unittest.TestCase):
    def test_37_no_mutation_of_plan_or_output(self):
        plan, output = make_plan(quality=7), make_output(width=3)
        plan_before, output_before = plan.to_dict(), output.to_dict()
        plan_hash, output_hash = hash(plan), hash(output)
        res = validate_image_operation_output(plan, output)
        self.assertFalse(res.ok)
        self.assertEqual(plan.to_dict(), plan_before)
        self.assertEqual(output.to_dict(), output_before)
        self.assertEqual((hash(plan), hash(output)), (plan_hash, output_hash))
        self.assertEqual(plan, make_plan(quality=7))
        self.assertEqual(output, make_output(width=3))

    def test_38_deterministic_repeated_validation(self):
        plan, output = make_plan(), make_output(operation="x", height=2)
        first = validate_image_operation_output(plan, output)
        for _ in range(25):
            again = validate_image_operation_output(plan, output)
            self.assertEqual(again, first)
            self.assertEqual(again.codes(), first.codes())
            self.assertEqual(again.to_dict(), first.to_dict())
            self.assertEqual(hash(again), hash(first))
        ok1 = validate_image_operation_output(make_plan(), make_output())
        self.assertEqual([validate_image_operation_output(make_plan(), make_output()) for _ in range(5)], [ok1] * 5)

    def test_39_never_raises_for_odd_inputs(self):
        for a in (None, 0, "", b"", [], {}, object(), float("nan"), ImageOperationOutputValidationResult):
            for b in (None, 0, "", b"", [], {}, object(), float("nan"), ImageOperationOutputValidationResult):
                with self.subTest(a=type(a).__name__, b=type(b).__name__):
                    res = validate_image_operation_output(a, b)
                    self.assertEqual(res.codes(), [P + "INVALID_PLAN", P + "INVALID_OUTPUT"])

    def test_40_module_imports_only_plan_and_output_types_and_does_no_io(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual([(n.module, sorted(a.name for a in n.names)) for n in imports],
                         [("image_operation_output", ["ImageOperationOutput"]), ("image_operation_plan", ["ImageOperationPlan"])])
        self.assertTrue(all(isinstance(n, ast.ImportFrom) and n.level == 1 for n in imports))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"open", "os", "io", "subprocess", "socket", "random", "time", "pathlib", "ImageAsset", "ImageAssetRegistry",
                                  "ImageOperationRequest", "ImageOperationExecutionResult", "bytes", "bytearray", "memoryview"})
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertFalse(attrs & {"read", "write", "resize", "convert", "crop", "decode", "quality", "lower", "upper", "casefold", "strip"})
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value == "quality"])

    def test_41_earlier_production_modules_are_unaware_of_the_validator(self):
        for name in ("image_asset.py", "image_asset_registry.py", "image_operation_request.py", "image_operation_validator.py",
                     "image_operation_plan.py", "image_operation_executor.py", "image_operation_output.py"):
            with open(os.path.join(PY_ROOT, "multimedia", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("image_operation_output_validator", "validate_image_operation_output", "ImageOperationOutputValidationResult"):
                self.assertNotIn(token, text, name)

    def test_42_multimedia_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "multimedia")) if f != "__pycache__"),
                         ["__init__.py", "audio_asset.py", "audio_asset_registry.py", "audio_operation_batch.py", "audio_operation_batch_summary.py", "audio_operation_dispatcher.py", "audio_operation_executor.py", "audio_operation_metadata_executor.py", "audio_operation_output.py", "audio_operation_output_validator.py", "audio_operation_pipeline.py", "audio_operation_plan.py", "audio_operation_request.py", "audio_operation_validator.py", "image_asset.py", "image_asset_registry.py", "image_operation_batch.py", "image_operation_batch_summary.py", "image_operation_dispatcher.py", "image_operation_executor.py",
                          "image_operation_metadata_executor.py", "image_operation_output.py", "image_operation_output_validator.py", "image_operation_pipeline.py", "image_operation_plan.py",
                          "image_operation_request.py", "image_operation_validator.py"])
        with open(os.path.join(PY_ROOT, "multimedia", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_43_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("ImageOperationOutputValidationResult", "validate_image_operation_output", P, "INVALID_PLAN", "INVALID_OUTPUT",
                       "IMAGE_ID_MISMATCH", "OPERATION_MISMATCH", "FORMAT_MISMATCH", "WIDTH_MISMATCH", "HEIGHT_MISMATCH", "quality",
                       "does NOT", "Prompt 754", "target_format", "output_format"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
