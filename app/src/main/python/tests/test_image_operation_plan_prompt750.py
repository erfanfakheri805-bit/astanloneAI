"""Prompt 750 - Section 8 image operation plan (`multimedia.image_operation_plan`)."""
import ast
import copy
import hashlib
import os
import pickle
import unittest

from multimedia import image_operation_plan as iop
from multimedia.image_asset import ImageAsset, create_image_asset
from multimedia.image_asset_registry import ImageAssetRegistry, create_image_asset_registry
from multimedia.image_operation_plan import ImageOperationPlan, ImageOperationPlanResult, create_image_operation_plan
from multimedia.image_operation_request import ImageOperationRequest, create_image_operation_request
from multimedia.image_operation_validator import ImageOperationValidationResult, validate_image_operation_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section8_image_operation_plan_prompt750.md")
MODULE = os.path.join(PY_ROOT, "multimedia", "image_operation_plan.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
P = "IMAGE_OPERATION_PLAN_"
FIELDS = ("image_id", "operation", "target_format", "width", "height", "quality")


def make_asset(image_id="hero"):
    r = create_image_asset({"image_id": image_id, "name": "N", "description": "", "format": "png", "width": 10, "height": 10})
    assert r.ok, r.failures
    return r.asset


def make_registry(*assets):
    r = create_image_asset_registry(list(assets))
    assert r.ok, r.failures
    return r.registry


def make_request(**over):
    data = {"image_id": "hero", "operation": "resize", "target_format": "webp", "width": 800, "height": 600, "quality": 85}
    data.update(over)
    r = create_image_operation_request(data)
    assert r.ok, r.failures
    return r.request


def validated(**over):
    """(validation_result, request, asset, registry) for a registered image."""
    asset = make_asset(over.get("image_id", "hero"))
    reg = make_registry(asset)
    req = make_request(**over)
    res = validate_image_operation_request(req, reg)
    assert res.ok, res.codes()
    return res, req, asset, reg


class TestSuccess(unittest.TestCase):
    def test_1_valid_validation_result_produces_the_exact_expected_plan(self):
        vr, _req, _a, _r = validated()
        res = create_image_operation_plan(vr)
        self.assertIs(type(res), ImageOperationPlanResult)
        self.assertTrue(res.ok)
        self.assertEqual(res.failures, ())
        self.assertEqual(res.codes(), [])
        self.assertIs(type(res.plan), ImageOperationPlan)
        self.assertEqual(res.plan.to_dict(), {"image_id": "hero", "operation": "resize", "target_format": "webp", "width": 800, "height": 600, "quality": 85})
        self.assertEqual(res.to_dict(), {"ok": True, "plan": res.plan.to_dict(), "failures": []})

    def test_2_all_six_values_preserved_exactly(self):
        vr, req, _a, _r = validated(image_id="img-7", operation="Totally New  Op", target_format="", width=1, height=99999, quality=100)
        p = create_image_operation_plan(vr).plan
        for name in FIELDS:
            self.assertEqual(getattr(p, name), getattr(req, name), name)
        self.assertEqual((p.image_id, p.operation, p.target_format, p.width, p.height, p.quality),
                         ("img-7", "Totally New  Op", "", 1, 99999, 100))

    def test_3_fields_are_exactly_the_six_in_fixed_order(self):
        self.assertEqual(iop.FIELDS, FIELDS)
        self.assertEqual(ImageOperationPlan.__slots__, tuple("_" + f for f in FIELDS))
        self.assertEqual(list(create_image_operation_plan(validated()[0]).plan.to_dict()), list(FIELDS))

    def test_4_no_normalization_trimming_casefolding_or_coercion(self):
        for over in ({"operation": "  RESIZE\t"}, {"target_format": "  WebP "}, {"image_id": " Hero "}, {"target_format": "   "}):
            with self.subTest(over=over):
                vr, req, _a, _r = validated(**over)
                p = create_image_operation_plan(vr).plan
                self.assertEqual(p.to_dict(), req.to_dict())

    def test_5_exact_string_identity_preserved(self):
        image_id = "".join(["hero", "_", "x"])
        op = "".join(["res", "ize"])
        fmt = "".join(["we", "bp"])
        vr, req, _a, _r = validated(image_id=image_id, operation=op, target_format=fmt)
        p = create_image_operation_plan(vr).plan
        self.assertIs(p.image_id, image_id)
        self.assertIs(p.operation, op)
        self.assertIs(p.target_format, fmt)
        self.assertIs(p.image_id, req.image_id)
        self.assertIs(p.to_dict()["operation"], op)
        for name in ("width", "height", "quality"):
            self.assertIs(getattr(p, name), getattr(req, name))
            self.assertIs(type(getattr(p, name)), int)

    def test_6_operation_and_format_stay_free_text(self):
        for op, fmt in (("blur", "tiff"), ("convert", "not-a-format"), ("\u00e9", "\u00e9"), ("x" * 300, "")):
            with self.subTest(op=op[:8]):
                p = create_image_operation_plan(validated(operation=op, target_format=fmt)[0]).plan
                self.assertEqual((p.operation, p.target_format), (op, fmt))

    def test_7_deterministic_repeated_creation(self):
        vr, _req, _a, _r = validated()
        r1, r2 = create_image_operation_plan(vr), create_image_operation_plan(vr)
        self.assertIsNot(r1, r2)
        self.assertIsNot(r1.plan, r2.plan)
        self.assertEqual(r1, r2)
        self.assertEqual(r1.plan, r2.plan)
        self.assertEqual(hash(r1), hash(r2))
        self.assertEqual(r1.to_dict(), r2.to_dict())
        again = create_image_operation_plan(validated()[0])
        self.assertEqual(again, r1)


class TestFailure(unittest.TestCase):
    def test_8_invalid_validation_result_type(self):
        vr = validated()[0]
        for bad in (None, {}, [], "ok", 5, True, object(), vr.to_dict(), vr.request, make_request(), make_registry()):
            with self.subTest(bad=type(bad).__name__):
                res = create_image_operation_plan(bad)
                self.assertFalse(res.ok)
                self.assertIsNone(res.plan)
                self.assertEqual(res.codes(), [P + "INVALID_VALIDATION_RESULT"])
                self.assertEqual(res.failures[0]["field"], "validation_result")

    def test_9_look_alike_validation_result_is_rejected_and_never_read(self):
        class Fake:
            ok = True

            def __getattr__(self, name):
                raise AssertionError("must not read " + name)

        res = create_image_operation_plan(Fake())
        self.assertEqual(res.codes(), [P + "INVALID_VALIDATION_RESULT"])
        with self.assertRaises(TypeError):
            type("Sub", (ImageOperationValidationResult,), {})

    def test_10_validation_result_with_ok_false(self):
        reg = make_registry(make_asset("hero"))
        failed_results = (
            validate_image_operation_request(make_request(image_id="ghost"), reg),
            validate_image_operation_request(None, reg),
            validate_image_operation_request(make_request(), None),
            validate_image_operation_request(None, None),
        )
        for vr in failed_results:
            with self.subTest(codes=vr.codes()):
                self.assertFalse(vr.ok)
                res = create_image_operation_plan(vr)
                self.assertFalse(res.ok)
                self.assertEqual(res.codes(), [P + "VALIDATION_FAILED"])
                self.assertEqual(res.failures[0]["field"], "validation_result")

    def test_11_no_plan_returned_on_failure(self):
        reg = make_registry()
        for vr in (validate_image_operation_request(make_request(), reg), None):
            res = create_image_operation_plan(vr)
            self.assertIsNone(res.plan)
            self.assertFalse(res.ok)
            self.assertIsNone(res.to_dict()["plan"])
            self.assertFalse(res.to_dict()["ok"])

    def test_12_failed_validation_with_found_request_still_gives_no_plan(self):
        # IMAGE_NOT_FOUND results still carry the (valid) request; a plan must not be built from it.
        vr = validate_image_operation_request(make_request(image_id="ghost"), make_registry())
        self.assertIsNotNone(vr.request)
        self.assertIsNone(create_image_operation_plan(vr).plan)

    def test_13_failure_messages_and_codes_are_stable(self):
        self.assertEqual(iop.FAILURE_CODES, (P + "INVALID_VALIDATION_RESULT", P + "VALIDATION_FAILED"))
        a = create_image_operation_plan(validate_image_operation_request(make_request(image_id="ghost"), make_registry()))
        b = create_image_operation_plan(validate_image_operation_request(make_request(image_id="ghost"), make_registry()))
        self.assertEqual(a, b)
        self.assertEqual(a.failures, b.failures)
        self.assertEqual(set(a.failures[0]), {"code", "field", "message"})
        self.assertIn("IMAGE_OPERATION_VALIDATION_IMAGE_NOT_FOUND", a.failures[0]["message"])
        self.assertEqual(a.to_dict()["failures"], [dict(a.failures[0])])


class TestNoRetentionAndNoMutation(unittest.TestCase):
    def test_14_asset_and_registry_are_not_retained(self):
        vr, req, asset, reg = validated()
        res = create_image_operation_plan(vr)
        forbidden = (asset, reg, req, vr)
        for obj in (res, res.plan):
            for slot in type(obj).__slots__:
                value = getattr(obj, slot)
                for f in forbidden:
                    self.assertIsNot(value, f, slot)
        for value in res.plan.to_dict().values():
            self.assertIs(type(value), str if isinstance(value, str) else int)
        self.assertEqual(sorted(type(res.plan).__slots__), sorted("_" + f for f in FIELDS))
        self.assertFalse(hasattr(res.plan, "asset"))
        self.assertFalse(hasattr(res.plan, "registry"))
        self.assertNotIn("name", res.plan.to_dict())
        self.assertNotIn("description", res.plan.to_dict())
        self.assertFalse(hasattr(res.plan, "__dict__"))
        self.assertFalse(hasattr(res, "__dict__"))

    def test_15_source_validation_result_remains_unchanged(self):
        vr, req, asset, reg = validated()
        before = (vr.to_dict(), hash(vr), vr.request, vr.asset, vr.codes(), vr.failures, vr.ok)
        create_image_operation_plan(vr)
        create_image_operation_plan(vr)
        after = (vr.to_dict(), hash(vr), vr.request, vr.asset, vr.codes(), vr.failures, vr.ok)
        self.assertEqual(before, after)
        self.assertIs(vr.request, req)
        self.assertIs(vr.asset, asset)

    def test_16_request_asset_and_registry_remain_unchanged(self):
        vr, req, asset, reg = validated()
        snap = (req.to_dict(), hash(req), asset.to_dict(), hash(asset), reg.to_dict(), hash(reg))
        create_image_operation_plan(vr)
        self.assertEqual(snap, (req.to_dict(), hash(req), asset.to_dict(), hash(asset), reg.to_dict(), hash(reg)))
        self.assertIs(reg.assets[0], asset)

    def test_17_failed_source_validation_result_remains_unchanged(self):
        vr = validate_image_operation_request(make_request(image_id="ghost"), make_registry())
        before = (vr.to_dict(), hash(vr))
        create_image_operation_plan(vr)
        self.assertEqual(before, (vr.to_dict(), hash(vr)))

    def test_18_plan_is_independent_of_the_asset_even_when_asset_differs_from_request(self):
        asset = create_image_asset({"image_id": "hero", "name": "N", "description": "", "format": "jpeg", "width": 5, "height": 5}).asset
        vr = validate_image_operation_request(make_request(width=4000, height=4000, target_format="png"), make_registry(asset))
        p = create_image_operation_plan(vr).plan
        self.assertEqual((p.width, p.height, p.target_format), (4000, 4000, "png"))


class TestPlanContract(unittest.TestCase):
    def setUp(self):
        self.res = create_image_operation_plan(validated()[0])
        self.plan = self.res.plan
        self.bad = create_image_operation_plan(None)

    def test_19_read_only_properties(self):
        for name in FIELDS:
            with self.subTest(name=name):
                with self.assertRaises(AttributeError):
                    setattr(self.plan, name, 1)
                with self.assertRaises(AttributeError):
                    delattr(self.plan, name)
                with self.assertRaises(AttributeError):
                    setattr(self.plan, "_" + name, 1)
        with self.assertRaises(AttributeError):
            self.plan.extra = 1

    def test_20_direct_construction_refused(self):
        for args in ((), (None, "a", "b", "c", 1, 1, 1), (object(), "a", "b", "c", 1, 1, 1)):
            with self.subTest(n=len(args)):
                with self.assertRaises(TypeError):
                    ImageOperationPlan(*args)
        for args in ((), (None, None, []), (object(), None, [])):
            with self.subTest(n=len(args)):
                with self.assertRaises(TypeError):
                    ImageOperationPlanResult(*args)

    def test_21_subclassing_refused(self):
        with self.assertRaises(TypeError):
            type("S1", (ImageOperationPlan,), {})
        with self.assertRaises(TypeError):
            type("S2", (ImageOperationPlanResult,), {})

    def test_22_result_is_immutable(self):
        for name in ("ok", "plan", "failures", "_plan", "_failures", "extra"):
            with self.subTest(name=name):
                with self.assertRaises(AttributeError):
                    setattr(self.res, name, 1)
                with self.assertRaises(AttributeError):
                    delattr(self.res, name)
        self.assertEqual(ImageOperationPlanResult.__slots__, ("_plan", "_failures"))

    def test_23_fresh_to_dict(self):
        d = self.plan.to_dict()
        d["image_id"] = "mutated"
        d["width"] = -1
        d["extra"] = 1
        self.assertEqual(self.plan.to_dict(), {"image_id": "hero", "operation": "resize", "target_format": "webp", "width": 800, "height": 600, "quality": 85})
        self.assertIsNot(self.plan.to_dict(), self.plan.to_dict())
        rd = self.res.to_dict()
        rd["plan"]["operation"] = "mutated"
        rd["failures"].append("x")
        rd["ok"] = False
        self.assertEqual(self.res.plan.operation, "resize")
        self.assertEqual(self.res.to_dict()["plan"]["operation"], "resize")
        self.assertEqual(self.res.to_dict()["failures"], [])
        self.assertTrue(self.res.to_dict()["ok"])
        self.assertIsNot(self.res.to_dict(), self.res.to_dict())

    def test_24_failure_to_dict_and_failures_are_fresh(self):
        d = self.bad.to_dict()
        self.assertEqual(list(d), ["ok", "plan", "failures"])
        self.assertEqual(d["failures"][0]["code"], P + "INVALID_VALIDATION_RESULT")
        d["failures"][0]["code"] = "mutated"
        f = self.bad.failures
        f[0]["code"] = "mutated"
        self.assertEqual(self.bad.to_dict()["failures"][0]["code"], P + "INVALID_VALIDATION_RESULT")
        self.assertEqual(self.bad.failures[0]["code"], P + "INVALID_VALIDATION_RESULT")
        self.assertIsInstance(self.bad.failures, tuple)

    def test_25_equality_and_hash(self):
        other = create_image_operation_plan(validated()[0])
        self.assertEqual(self.plan, other.plan)
        self.assertEqual(hash(self.plan), hash(other.plan))
        self.assertEqual(self.res, other)
        self.assertEqual(hash(self.res), hash(other))
        self.assertEqual(len({self.plan, other.plan}), 1)
        self.assertEqual(len({self.res, other}), 1)
        for field, value in (("image_id", "other"), ("operation", "blur"), ("target_format", ""), ("width", 801), ("height", 601), ("quality", 86)):
            with self.subTest(field=field):
                diff = create_image_operation_plan(validated(**{field: value})[0]) if field != "image_id" else create_image_operation_plan(validated(image_id="other")[0])
                self.assertNotEqual(self.plan, diff.plan)
                self.assertNotEqual(self.res, diff)
        self.assertNotEqual(self.plan, self.plan.to_dict())
        self.assertNotEqual(self.plan, None)
        self.assertNotEqual(self.plan, make_request())
        self.assertNotEqual(self.res, self.bad)
        self.assertEqual(self.bad, create_image_operation_plan(5))
        self.assertEqual(hash(self.bad), hash(create_image_operation_plan(5)))
        self.assertNotEqual(self.bad, create_image_operation_plan(validate_image_operation_request(None, None)))

    def test_26_copy_and_deepcopy_return_same_object(self):
        for obj in (self.res, self.plan, self.bad):
            self.assertIs(copy.copy(obj), obj)
            self.assertIs(copy.deepcopy(obj), obj)
            self.assertIs(copy.deepcopy({"k": [obj]})["k"][0], obj)

    def test_27_pickle_refused(self):
        for obj in (self.res, self.plan, self.bad):
            for proto in range(pickle.HIGHEST_PROTOCOL + 1):
                with self.subTest(obj=type(obj).__name__, proto=proto):
                    with self.assertRaises(TypeError):
                        pickle.dumps(obj, protocol=proto)

    def test_28_repr_is_stable(self):
        self.assertEqual(repr(self.plan), "ImageOperationPlan(image_id='hero', operation='resize', target_format='webp', width=800, height=600, quality=85)")
        self.assertEqual(repr(self.res), "ImageOperationPlanResult(ok=True, codes=[])")
        self.assertEqual(repr(self.bad), "ImageOperationPlanResult(ok=False, codes=['%sINVALID_VALIDATION_RESULT'])" % P)

    def test_29_plan_has_no_execution_surface(self):
        public = {n for n in dir(self.plan) if not n.startswith("_")}
        self.assertEqual(public, set(FIELDS) | {"to_dict"})
        public = {n for n in dir(self.res) if not n.startswith("_")}
        self.assertEqual(public, {"ok", "plan", "failures", "codes", "to_dict"})


class TestBoundaries(unittest.TestCase):
    def test_30_module_is_pure(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imported = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                imported += [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                imported.append("." * n.level + (n.module or ""))
        self.assertEqual(imported, [".image_operation_validator"])
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"open", "os", "subprocess", "socket", "random", "time", "ImageAsset", "ImageAssetRegistry", "ImageOperationRequest"})
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertFalse(attrs & {"asset", "assets", "lookup", "image_ids"})

    def test_31_earlier_production_modules_are_unaware_of_the_plan(self):
        for name in ("image_asset.py", "image_asset_registry.py", "image_operation_request.py", "image_operation_validator.py"):
            with open(os.path.join(PY_ROOT, "multimedia", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("image_operation_plan", "ImageOperationPlan", "create_image_operation_plan"):
                self.assertNotIn(token, text, name)

    def test_32_multimedia_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "multimedia")) if f != "__pycache__"),
                         ["__init__.py", "audio_asset.py", "audio_asset_registry.py", "audio_operation_batch.py", "audio_operation_batch_summary.py", "audio_operation_dispatcher.py", "audio_operation_executor.py", "audio_operation_metadata_executor.py", "audio_operation_output.py", "audio_operation_output_validator.py", "audio_operation_pipeline.py", "audio_operation_plan.py", "audio_operation_request.py", "audio_operation_validator.py", "image_asset.py", "image_asset_registry.py", "image_operation_batch.py", "image_operation_batch_summary.py", "image_operation_dispatcher.py", "image_operation_executor.py", "image_operation_metadata_executor.py", "image_operation_output.py", "image_operation_output_validator.py", "image_operation_pipeline.py", "image_operation_plan.py",
                          "image_operation_request.py", "image_operation_validator.py"])
        with open(os.path.join(PY_ROOT, "multimedia", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_33_end_to_end_with_prior_prompts_only_through_public_apis(self):
        asset = make_asset("logo")
        reg = make_registry(asset, make_asset("hero"))
        req = make_request(image_id="logo", operation="convert", target_format="png", width=64, height=64, quality=100)
        plan = create_image_operation_plan(validate_image_operation_request(req, reg)).plan
        self.assertEqual(plan.to_dict(), req.to_dict())
        self.assertIs(type(plan), ImageOperationPlan)

    def test_34_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("ImageOperationPlan", "ImageOperationPlanResult", "create_image_operation_plan", "IMAGE_OPERATION_PLAN_",
                       "INVALID_VALIDATION_RESULT", "VALIDATION_FAILED", "does NOT", "Prompt 751", "execution description"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
