"""Prompt 752 - Section 8 image operation output result contract (`multimedia.image_operation_output`)."""
import ast
import copy
import hashlib
import os
import pickle
import unittest

from multimedia import image_operation_output as ioo
from multimedia.image_operation_output import ImageOperationOutput, ImageOperationOutputResult, create_image_operation_output

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section8_image_operation_output_prompt752.md")
MODULE = os.path.join(PY_ROOT, "multimedia", "image_operation_output.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
P = "IMAGE_OPERATION_OUTPUT_"
FIELDS = ("image_id", "operation", "output_format", "width", "height")
CODE_FOR = {"image_id": P + "INVALID_IMAGE_ID", "operation": P + "INVALID_OPERATION", "output_format": P + "INVALID_OUTPUT_FORMAT",
            "width": P + "INVALID_WIDTH", "height": P + "INVALID_HEIGHT"}


def good(**over):
    d = {"image_id": "hero", "operation": "resize", "output_format": "webp", "width": 800, "height": 600}
    d.update(over)
    return d


def codes_of(data):
    return create_image_operation_output(data).codes()


class TestValid(unittest.TestCase):
    def test_1_valid_metadata(self):
        res = create_image_operation_output(good())
        self.assertIs(type(res), ImageOperationOutputResult)
        self.assertIs(res.ok, True)
        self.assertEqual(res.failures, ())
        self.assertEqual(res.codes(), [])
        self.assertIs(type(res.output), ImageOperationOutput)
        self.assertEqual(res.output.to_dict(), good())
        self.assertEqual(res.to_dict(), {"ok": True, "output": good(), "failures": []})
        self.assertEqual((res.output.image_id, res.output.operation, res.output.output_format, res.output.width, res.output.height),
                         ("hero", "resize", "webp", 800, 600))

    def test_2_exactly_five_fields_in_fixed_order(self):
        self.assertEqual(ioo.FIELDS, FIELDS)
        self.assertEqual(ImageOperationOutput.__slots__, tuple("_" + f for f in FIELDS))
        self.assertEqual(list(create_image_operation_output(good()).output.to_dict()), list(FIELDS))
        reordered = {"height": 6, "width": 5, "output_format": "png", "operation": "crop", "image_id": "a"}
        self.assertEqual(list(create_image_operation_output(reordered).output.to_dict()), list(FIELDS))

    def test_3_no_normalization_trimming_casefolding_or_coercion(self):
        for over in ({"operation": "  RESIZE\t"}, {"output_format": "  WebP "}, {"image_id": " Hero "}, {"output_format": "   "}, {"operation": "\n"}):
            with self.subTest(over=over):
                res = create_image_operation_output(good(**over))
                self.assertTrue(res.ok)
                self.assertEqual(res.output.to_dict(), good(**over))

    def test_4_free_text_values_accepted(self):
        for op, fmt in (("blur", "tiff"), ("convert", "not-a-format"), ("\u00e9", "\u00e9"), ("x" * 500, "y" * 500)):
            with self.subTest(op=op[:6]):
                out = create_image_operation_output(good(operation=op, output_format=fmt)).output
                self.assertEqual((out.operation, out.output_format), (op, fmt))

    def test_5_dimension_boundaries(self):
        for w, h in ((1, 1), (2, 99999), (10 ** 12, 10 ** 12)):
            with self.subTest(w=w):
                out = create_image_operation_output(good(width=w, height=h)).output
                self.assertEqual((out.width, out.height), (w, h))

    def test_6_exact_value_and_string_identity_preserved(self):
        image_id = "".join(["hero", "_", "x"])
        op = "".join(["res", "ize"])
        fmt = "".join(["we", "bp"])
        w, h = 10 ** 6 + 1, 10 ** 6 + 2
        out = create_image_operation_output({"image_id": image_id, "operation": op, "output_format": fmt, "width": w, "height": h}).output
        self.assertIs(out.image_id, image_id)
        self.assertIs(out.operation, op)
        self.assertIs(out.output_format, fmt)
        self.assertIs(out.width, w)
        self.assertIs(out.height, h)
        d = out.to_dict()
        self.assertIs(d["image_id"], image_id)
        self.assertIs(d["operation"], op)
        self.assertIs(d["output_format"], fmt)
        for v in (out.width, out.height):
            self.assertIs(type(v), int)

    def test_7_source_is_not_mutated(self):
        src = good()
        snapshot = dict(src)
        keys = list(src)
        res = create_image_operation_output(src)
        self.assertEqual(src, snapshot)
        self.assertEqual(list(src), keys)
        src["image_id"] = "changed"
        src["width"] = 1
        self.assertEqual(res.output.image_id, "hero")
        self.assertEqual(res.output.width, 800)
        bad = {"image_id": "", "extra": 1}
        before = dict(bad)
        create_image_operation_output(bad)
        self.assertEqual(bad, before)

    def test_8_deterministic_repeated_creation(self):
        r1, r2 = create_image_operation_output(good()), create_image_operation_output(good())
        self.assertIsNot(r1, r2)
        self.assertIsNot(r1.output, r2.output)
        self.assertEqual(r1, r2)
        self.assertEqual(r1.output, r2.output)
        self.assertEqual(hash(r1), hash(r2))
        self.assertEqual(r1.to_dict(), r2.to_dict())
        for _ in range(5):
            self.assertEqual(create_image_operation_output(good()), r1)
        b1, b2 = create_image_operation_output(None), create_image_operation_output(None)
        self.assertIsNot(b1, b2)
        self.assertEqual(b1, b2)
        self.assertEqual(hash(b1), hash(b2))
        m1 = create_image_operation_output({"x": 1})
        self.assertEqual(m1.to_dict(), create_image_operation_output({"x": 1}).to_dict())


class TestInvalid(unittest.TestCase):
    def test_9_wrong_input_type(self):
        class D(dict):
            pass

        for bad in (None, [], (), "x", 5, True, object(), D(good()), good().items(), [("image_id", "a")]):
            with self.subTest(bad=type(bad).__name__):
                res = create_image_operation_output(bad)
                self.assertFalse(res.ok)
                self.assertIsNone(res.output)
                self.assertEqual(res.codes(), [P + "INVALID_INPUT"])
                self.assertIsNone(res.failures[0]["field"])

    def test_10_empty_dict_reports_every_missing_field(self):
        res = create_image_operation_output({})
        self.assertEqual(res.codes(), [P + "MISSING_FIELD"] * 5)
        self.assertEqual([f["field"] for f in res.failures], list(FIELDS))

    def test_11_missing_each_field(self):
        for field in FIELDS:
            with self.subTest(field=field):
                d = good()
                del d[field]
                res = create_image_operation_output(d)
                self.assertFalse(res.ok)
                self.assertIsNone(res.output)
                self.assertEqual(res.codes(), [P + "MISSING_FIELD"])
                self.assertEqual(res.failures[0]["field"], field)

    def test_12_unexpected_fields(self):
        for extra in ("path", "quality", "target_format", "bytes", "Image_Id", ""):
            with self.subTest(extra=extra):
                res = create_image_operation_output(good(**{extra: 1}))
                self.assertFalse(res.ok)
                self.assertEqual(res.codes(), [P + "UNEXPECTED_FIELD"])
                self.assertEqual(res.failures[0]["field"], extra)
        res = create_image_operation_output(good(zeta=1, alpha=2))
        self.assertEqual([f["field"] for f in res.failures], ["alpha", "zeta"])

    def test_13_non_str_field_name_is_unexpected(self):
        for key in (1, None, (1,), b"image_id"):
            with self.subTest(key=repr(key)):
                d = good()
                d[key] = 1
                res = create_image_operation_output(d)
                self.assertEqual(res.codes(), [P + "UNEXPECTED_FIELD"])
                self.assertIsNone(res.failures[0]["field"])

    def test_14_str_subclass_field_name_is_not_accepted_as_a_field(self):
        class S(str):
            pass

        d = {S("image_id"): "a", "operation": "b", "output_format": "c", "width": 1, "height": 1}
        res = create_image_operation_output(d)
        self.assertFalse(res.ok)
        self.assertEqual(res.codes(), [P + "UNEXPECTED_FIELD"])
        self.assertIsNone(res.output)

    def test_15_empty_required_strings_rejected(self):
        for field in ("image_id", "operation", "output_format"):
            with self.subTest(field=field):
                res = create_image_operation_output(good(**{field: ""}))
                self.assertFalse(res.ok)
                self.assertIsNone(res.output)
                self.assertEqual(res.codes(), [CODE_FOR[field]])
                self.assertEqual(res.failures[0]["field"], field)

    def test_16_wrong_string_types(self):
        class S(str):
            pass

        for field in ("image_id", "operation", "output_format"):
            for bad in (None, 5, 1.5, True, b"x", ["x"], ("x",), {"x": 1}, S("x"), object()):
                with self.subTest(field=field, bad=type(bad).__name__):
                    res = create_image_operation_output(good(**{field: bad}))
                    self.assertEqual(res.codes(), [CODE_FOR[field]])
                    self.assertEqual(res.failures[0]["field"], field)

    def test_17_invalid_width_and_height(self):
        class I(int):
            pass

        for field in ("width", "height"):
            for bad in (0, -1, -10 ** 9, 1.0, 800.5, "800", None, [800], (800,), I(5), float("nan"), float("inf"), object()):
                with self.subTest(field=field, bad=repr(bad)):
                    res = create_image_operation_output(good(**{field: bad}))
                    self.assertFalse(res.ok)
                    self.assertIsNone(res.output)
                    self.assertEqual(res.codes(), [CODE_FOR[field]])
                    self.assertEqual(res.failures[0]["field"], field)

    def test_18_bool_rejected_for_width_and_height(self):
        for field in ("width", "height"):
            for bad in (True, False):
                with self.subTest(field=field, bad=bad):
                    self.assertEqual(codes_of(good(**{field: bad})), [CODE_FOR[field]])

    def test_19_all_problems_reported_at_once_in_fixed_order(self):
        d = {"zzz": 1, "aaa": 2, "image_id": "", "operation": 5, "width": True, "height": 0}
        res = create_image_operation_output(d)
        self.assertEqual([(f["code"], f["field"]) for f in res.failures], [
            (P + "UNEXPECTED_FIELD", "aaa"), (P + "UNEXPECTED_FIELD", "zzz"), (CODE_FOR["image_id"], "image_id"),
            (CODE_FOR["operation"], "operation"), (P + "MISSING_FIELD", "output_format"), (CODE_FOR["width"], "width"),
            (CODE_FOR["height"], "height")])

    def test_20_failure_codes_are_exactly_the_eight_with_prefix(self):
        self.assertEqual(ioo.FAILURE_CODES, tuple(P + s for s in ("INVALID_INPUT", "MISSING_FIELD", "UNEXPECTED_FIELD", "INVALID_IMAGE_ID",
                                                                  "INVALID_OPERATION", "INVALID_OUTPUT_FORMAT", "INVALID_WIDTH", "INVALID_HEIGHT")))
        seen = set()
        for d in (None, {}, good(x=1), good(image_id=""), good(operation=1), good(output_format=""), good(width=0), good(height=True)):
            seen.update(codes_of(d))
        self.assertEqual(seen, set(ioo.FAILURE_CODES))

    def test_21_failure_never_carries_an_output(self):
        for d in (None, {}, good(width=0), good(extra=1)):
            res = create_image_operation_output(d)
            self.assertIsNone(res.output)
            self.assertIs(res.ok, False)
            self.assertEqual(res.to_dict()["output"], None)
            self.assertEqual(res.to_dict()["ok"], False)

    def test_22_never_raises_for_hostile_values(self):
        class Evil:
            def __eq__(self, o):
                raise RuntimeError("no")

            def __bool__(self):
                raise RuntimeError("no")

            def __getattr__(self, n):
                raise AssertionError("must not read " + n)

        for field in FIELDS:
            res = create_image_operation_output(good(**{field: Evil()}))
            self.assertEqual(res.codes(), [CODE_FOR[field]])


class TestImmutability(unittest.TestCase):
    def setUp(self):
        self.res = create_image_operation_output(good())
        self.out = self.res.output
        self.bad = create_image_operation_output(good(width=0))

    def test_23_output_properties_are_read_only(self):
        for name in list(FIELDS) + ["_" + f for f in FIELDS] + ["extra", "to_dict"]:
            with self.subTest(name=name):
                with self.assertRaises(AttributeError):
                    setattr(self.out, name, 1)
                with self.assertRaises(AttributeError):
                    delattr(self.out, name)
        self.assertFalse(hasattr(self.out, "__dict__"))

    def test_24_result_is_immutable(self):
        for obj in (self.res, self.bad):
            for name in ("ok", "output", "failures", "_output", "_failures", "extra"):
                with self.subTest(name=name):
                    with self.assertRaises(AttributeError):
                        setattr(obj, name, 1)
                    with self.assertRaises(AttributeError):
                        delattr(obj, name)
        self.assertEqual(ImageOperationOutputResult.__slots__, ("_output", "_failures"))
        self.assertFalse(hasattr(self.res, "__dict__"))

    def test_25_direct_construction_refused(self):
        for args in ((), (None, "a", "b", "c", 1, 1), (object(), "a", "b", "c", 1, 1), (None, good())):
            with self.subTest(n=len(args)):
                with self.assertRaises(TypeError):
                    ImageOperationOutput(*args)
        for args in ((), (None, None, []), (object(), None, []), (object(), self.out, [])):
            with self.subTest(n=len(args)):
                with self.assertRaises(TypeError):
                    ImageOperationOutputResult(*args)

    def test_26_subclassing_refused(self):
        with self.assertRaises(TypeError):
            type("S1", (ImageOperationOutput,), {})
        with self.assertRaises(TypeError):
            type("S2", (ImageOperationOutputResult,), {})

    def test_27_fresh_to_dict(self):
        d = self.out.to_dict()
        d["image_id"] = "mutated"
        d["width"] = -1
        d["extra"] = 1
        self.assertEqual(self.out.to_dict(), good())
        self.assertIsNot(self.out.to_dict(), self.out.to_dict())
        rd = self.res.to_dict()
        rd["output"]["operation"] = "mutated"
        rd["failures"].append("x")
        rd["ok"] = False
        self.assertEqual(self.res.output.operation, "resize")
        self.assertEqual(self.res.to_dict(), {"ok": True, "output": good(), "failures": []})
        self.assertIsNot(self.res.to_dict(), self.res.to_dict())
        self.assertIsNot(self.res.to_dict()["output"], self.res.to_dict()["output"])

    def test_28_failures_are_fresh(self):
        d = self.bad.to_dict()
        self.assertEqual(list(d), ["ok", "output", "failures"])
        self.assertEqual(d["failures"][0]["code"], P + "INVALID_WIDTH")
        d["failures"][0]["code"] = "mutated"
        f = self.bad.failures
        f[0]["code"] = "mutated"
        self.assertEqual(self.bad.to_dict()["failures"][0]["code"], P + "INVALID_WIDTH")
        self.assertEqual(self.bad.failures[0]["code"], P + "INVALID_WIDTH")
        self.assertIsInstance(self.bad.failures, tuple)
        self.assertEqual(list(self.bad.failures[0]), ["code", "field", "message"])
        self.assertIsNot(self.bad.failures[0], self.bad.failures[0])

    def test_29_equality_and_hash(self):
        other = create_image_operation_output(good())
        self.assertEqual(self.out, other.output)
        self.assertEqual(hash(self.out), hash(other.output))
        self.assertEqual(self.res, other)
        self.assertEqual(hash(self.res), hash(other))
        self.assertEqual(len({self.out, other.output}), 1)
        self.assertEqual(len({self.res, other}), 1)
        for field, value in (("image_id", "other"), ("operation", "blur"), ("output_format", "png"), ("width", 801), ("height", 601)):
            with self.subTest(field=field):
                diff = create_image_operation_output(good(**{field: value}))
                self.assertNotEqual(self.out, diff.output)
                self.assertNotEqual(self.res, diff)
        self.assertNotEqual(self.out, self.out.to_dict())
        self.assertNotEqual(self.out, None)
        self.assertNotEqual(self.res, self.bad)
        self.assertNotEqual(self.res, self.res.to_dict())
        self.assertEqual(self.bad, create_image_operation_output(good(width=-5)))
        self.assertEqual(hash(self.bad), hash(create_image_operation_output(good(width=-5))))
        self.assertNotEqual(self.bad, create_image_operation_output(good(height=0)))

    def test_30_copy_and_deepcopy_return_same_object(self):
        for obj in (self.res, self.out, self.bad):
            self.assertIs(copy.copy(obj), obj)
            self.assertIs(copy.deepcopy(obj), obj)
            self.assertIs(copy.deepcopy({"k": [obj]})["k"][0], obj)

    def test_31_pickle_refused(self):
        for obj in (self.res, self.out, self.bad):
            for proto in range(pickle.HIGHEST_PROTOCOL + 1):
                with self.subTest(obj=type(obj).__name__, proto=proto):
                    with self.assertRaises(TypeError):
                        pickle.dumps(obj, protocol=proto)

    def test_32_repr_is_stable(self):
        self.assertEqual(repr(self.out), "ImageOperationOutput(image_id='hero', operation='resize', output_format='webp', width=800, height=600)")
        self.assertEqual(repr(self.res), "ImageOperationOutputResult(ok=True, codes=[])")
        self.assertEqual(repr(self.bad), "ImageOperationOutputResult(ok=False, codes=['%sINVALID_WIDTH'])" % P)

    def test_33_public_surface_is_minimal(self):
        self.assertEqual({n for n in dir(self.out) if not n.startswith("_")}, set(FIELDS) | {"to_dict"})
        self.assertEqual({n for n in dir(self.res) if not n.startswith("_")}, {"ok", "output", "failures", "codes", "to_dict"})

    def test_34_output_holds_only_plain_str_and_int(self):
        out = create_image_operation_output(good()).output
        self.assertEqual([type(v) for v in out.to_dict().values()], [str, str, str, int, int])
        for v in out.to_dict().values():
            self.assertIn(type(v), (str, int))
        self.assertFalse(any(isinstance(v, (bytes, bytearray, memoryview, os.PathLike)) for v in out.to_dict().values()))


class TestBoundaries(unittest.TestCase):
    def test_35_module_is_pure_and_imports_nothing(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))], [])
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"open", "os", "io", "subprocess", "socket", "random", "time", "pathlib", "ImageAsset", "ImageAssetRegistry",
                                  "ImageOperationPlan", "ImageOperationRequest", "ImageOperationExecutionResult"})
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertFalse(attrs & {"read", "write", "resize", "convert", "crop", "decode", "asset", "assets", "plan"})

    def test_36_earlier_production_modules_are_unaware_of_the_output_model(self):
        for name in ("image_asset.py", "image_asset_registry.py", "image_operation_request.py", "image_operation_validator.py",
                     "image_operation_plan.py", "image_operation_executor.py"):
            with open(os.path.join(PY_ROOT, "multimedia", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("image_operation_output", "ImageOperationOutput", "create_image_operation_output"):
                self.assertNotIn(token, text, name)

    def test_37_multimedia_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "multimedia")) if f != "__pycache__"),
                         ["__init__.py", "audio_asset.py", "audio_asset_registry.py", "audio_operation_batch.py", "audio_operation_batch_summary.py", "audio_operation_dispatcher.py", "audio_operation_executor.py", "audio_operation_metadata_executor.py", "audio_operation_output.py", "audio_operation_output_validator.py", "audio_operation_pipeline.py", "audio_operation_plan.py", "audio_operation_request.py", "audio_operation_validator.py", "image_asset.py", "image_asset_registry.py", "image_operation_batch.py", "image_operation_batch_summary.py", "image_operation_dispatcher.py", "image_operation_executor.py",
                          "image_operation_metadata_executor.py", "image_operation_output.py", "image_operation_output_validator.py", "image_operation_pipeline.py", "image_operation_plan.py", "image_operation_request.py", "image_operation_validator.py"])
        with open(os.path.join(PY_ROOT, "multimedia", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_38_independent_of_executor_and_plan_values_by_plain_data_only(self):
        # an output can describe the metadata of a plan's result, but only through plain values (no object link)
        from multimedia.image_operation_executor import execute_image_operation
        self.assertFalse(execute_image_operation(None).ok)
        res = create_image_operation_output({"image_id": "logo", "operation": "convert", "output_format": "png", "width": 64, "height": 64})
        self.assertTrue(res.ok)
        self.assertEqual(res.output.to_dict(), {"image_id": "logo", "operation": "convert", "output_format": "png", "width": 64, "height": 64})

    def test_39_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("ImageOperationOutput", "ImageOperationOutputResult", "create_image_operation_output", "IMAGE_OPERATION_OUTPUT_",
                       "INVALID_INPUT", "MISSING_FIELD", "UNEXPECTED_FIELD", "INVALID_OUTPUT_FORMAT", "does NOT", "Prompt 753", "output_format"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
