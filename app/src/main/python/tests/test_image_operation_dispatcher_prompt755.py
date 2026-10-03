"""Prompt 755 - Section 8 image operation dispatcher (`multimedia.image_operation_dispatcher`)."""
import ast
import builtins
import copy
import hashlib
import os
import pickle
import unittest
from unittest import mock

from multimedia import image_operation_dispatcher as d
from multimedia import image_operation_metadata_executor as me
from multimedia.image_asset import create_image_asset
from multimedia.image_asset_registry import create_image_asset_registry
from multimedia.image_operation_dispatcher import ImageOperationDispatchResult, dispatch_image_operation
from multimedia.image_operation_executor import execute_image_operation
from multimedia.image_operation_metadata_executor import ImageOperationMetadataExecutionResult, execute_image_operation_metadata
from multimedia.image_operation_output import ImageOperationOutput, create_image_operation_output
from multimedia.image_operation_output_validator import validate_image_operation_output
from multimedia.image_operation_plan import ImageOperationPlan, create_image_operation_plan
from multimedia.image_operation_request import create_image_operation_request
from multimedia.image_operation_validator import validate_image_operation_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section8_image_operation_dispatcher_prompt755.md")
MODULE = os.path.join(PY_ROOT, "multimedia", "image_operation_dispatcher.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
P = "IMAGE_OPERATION_DISPATCHER_"


def make_plan(**over):
    data = {"image_id": "hero", "operation": "metadata", "target_format": "webp", "width": 800, "height": 600, "quality": 85}
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


class TestSuccess(unittest.TestCase):
    def test_1_valid_metadata_dispatch(self):
        res = dispatch_image_operation(make_plan())
        self.assertIs(type(res), ImageOperationDispatchResult)
        self.assertIs(res.ok, True)
        self.assertEqual(res.failures, ())
        self.assertEqual(res.codes(), [])

    def test_2_exact_plan_identity(self):
        plan = make_plan()
        res = dispatch_image_operation(plan)
        self.assertIs(res.plan, plan)
        self.assertIs(res.result.plan, plan)

    def test_3_exact_result_type_and_output(self):
        plan = make_plan(image_id="logo", target_format="png", width=64, height=32)
        res = dispatch_image_operation(plan)
        self.assertIs(type(res.result), ImageOperationMetadataExecutionResult)
        self.assertIs(type(res.result.output), ImageOperationOutput)
        self.assertEqual(res.result.output.to_dict(), {"image_id": "logo", "operation": "metadata", "output_format": "png", "width": 64, "height": 32})
        self.assertEqual(res.result, execute_image_operation_metadata(plan))

    def test_4_routes_through_prompt_754_function_exactly_once_and_returns_its_result_unchanged(self):
        plan = make_plan()
        real = execute_image_operation_metadata
        calls, returned = [], []

        def spy(arg):
            calls.append(arg)
            r = real(arg)
            returned.append(r)
            return r

        with mock.patch.object(d, "execute_image_operation_metadata", spy):
            res = dispatch_image_operation(plan)
        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0], plan)
        self.assertIs(res.result, returned[0])

    def test_5_executor_result_is_held_unchanged_even_when_it_fails(self):
        plan = make_plan()
        failed = create_image_operation_output(None)
        with mock.patch.object(me, "create_image_operation_output", return_value=failed):
            inner = execute_image_operation_metadata(plan)
        self.assertEqual(inner.codes(), [me.FAILURE_OUTPUT_CREATION_FAILED])
        with mock.patch.object(d, "execute_image_operation_metadata", return_value=inner):
            res = dispatch_image_operation(plan)
        self.assertIs(res.result, inner)
        self.assertIs(res.plan, plan)
        self.assertFalse(res.ok)
        self.assertEqual(res.failures, ())          # dispatcher adds no code of its own; the executor's code stays inside `result`
        self.assertEqual(res.result.codes(), [me.FAILURE_OUTPUT_CREATION_FAILED])
        self.assertEqual(res.to_dict()["result"]["failures"][0]["code"], me.FAILURE_OUTPUT_CREATION_FAILED)

    def test_6_output_passes_output_validation(self):
        plan = make_plan(target_format="avif", width=3, height=4, quality=1)
        res = dispatch_image_operation(plan)
        self.assertTrue(validate_image_operation_output(plan, res.result.output).ok)

    def test_7_exact_string_and_int_identity_preserved(self):
        image_id = "".join(["her", "o", "_x"])
        fmt = "".join(["we", "bp"])
        plan = make_plan(image_id=image_id, target_format=fmt, width=10 ** 6 + 1, height=10 ** 6 + 2)
        out = dispatch_image_operation(plan).result.output
        self.assertIs(out.image_id, plan.image_id)
        self.assertIs(out.output_format, plan.target_format)
        self.assertIs(out.width, plan.width)
        self.assertIs(out.height, plan.height)

    def test_8_to_dict_of_success(self):
        plan = make_plan()
        res = dispatch_image_operation(plan)
        self.assertEqual(list(res.to_dict()), ["ok", "plan", "result", "failures"])
        self.assertEqual(res.to_dict(), {"ok": True, "plan": plan.to_dict(), "result": res.result.to_dict(), "failures": []})


class TestRejections(unittest.TestCase):
    def test_9_unsupported_operation(self):
        for op in ("resize", "convert", "crop", "blur", "x"):
            with self.subTest(op=op):
                plan = make_plan(operation=op)
                res = dispatch_image_operation(plan)
                self.assertFalse(res.ok)
                self.assertIs(res.plan, plan)
                self.assertIsNone(res.result)
                self.assertEqual(res.codes(), [P + "UNSUPPORTED_OPERATION"])
                self.assertEqual(res.failures[0]["field"], "operation")

    def test_10_operation_match_is_exact(self):
        for op in ("Metadata", "METADATA", " metadata", "metadata ", "metadata\n", "meta", "metadatas"):
            with self.subTest(op=op):
                self.assertEqual(dispatch_image_operation(make_plan(operation=op)).codes(), [P + "UNSUPPORTED_OPERATION"])

    def test_11_executor_not_called_for_unsupported_operation(self):
        with mock.patch.object(d, "execute_image_operation_metadata", side_effect=AssertionError("must not be called")) as m:
            res = dispatch_image_operation(make_plan(operation="resize"))
            self.assertEqual(res.codes(), [P + "UNSUPPORTED_OPERATION"])
            self.assertEqual(dispatch_image_operation(None).codes(), [P + "INVALID_PLAN"])
        m.assert_not_called()

    def test_12_invalid_plan(self):
        out = create_image_operation_output({"image_id": "a", "operation": "metadata", "output_format": "c", "width": 1, "height": 1})
        for bad in (None, {}, make_plan().to_dict(), "plan", 1, object(), b"", [], out, execute_image_operation_metadata(make_plan())):
            with self.subTest(bad=type(bad).__name__):
                res = dispatch_image_operation(bad)
                self.assertFalse(res.ok)
                self.assertIsNone(res.plan)
                self.assertIsNone(res.result)
                self.assertEqual(res.codes(), [P + "INVALID_PLAN"])
                self.assertEqual(res.failures[0]["field"], "plan")

    def test_13_look_alike_and_subclass_plans_rejected_and_never_read(self):
        with self.assertRaises(TypeError):
            type("Sub", (ImageOperationPlan,), {})

        class Fake:
            image_id, operation, target_format, width, height, quality = "hero", "metadata", "webp", 800, 600, 85

        class Trap:
            def __getattribute__(self, name):
                raise AssertionError("must not be read: " + name)

        for bad in (Fake(), Trap()):
            with self.subTest(bad=type(bad).__name__):
                with mock.patch.object(d, "execute_image_operation_metadata", side_effect=AssertionError("must not be called")):
                    self.assertEqual(dispatch_image_operation(bad).codes(), [P + "INVALID_PLAN"])

    def test_14_only_two_failure_codes(self):
        self.assertEqual(d.FAILURE_CODES, (P + "INVALID_PLAN", P + "UNSUPPORTED_OPERATION"))
        seen = set(dispatch_image_operation(None).codes()) | set(dispatch_image_operation(make_plan(operation="resize")).codes())
        self.assertEqual(seen, set(d.FAILURE_CODES))
        self.assertEqual([n for n in dir(d) if n.startswith("FAILURE_") and n != "FAILURE_CODES"], ["FAILURE_INVALID_PLAN", "FAILURE_UNSUPPORTED_OPERATION"])

    def test_15_failure_to_dict_shapes(self):
        plan = make_plan(operation="resize")
        x = dispatch_image_operation(plan).to_dict()
        self.assertEqual((x["ok"], x["plan"], x["result"]), (False, plan.to_dict(), None))
        self.assertEqual([(f["code"], f["field"]) for f in x["failures"]], [(P + "UNSUPPORTED_OPERATION", "operation")])
        y = dispatch_image_operation(None).to_dict()
        self.assertEqual((y["ok"], y["plan"], y["result"]), (False, None, None))
        self.assertEqual([(f["code"], f["field"]) for f in y["failures"]], [(P + "INVALID_PLAN", "plan")])


class TestResultContract(unittest.TestCase):
    def test_16_immutable(self):
        res = dispatch_image_operation(make_plan())
        for name in ("ok", "plan", "result", "failures", "extra", "_failures"):
            with self.subTest(name=name):
                with self.assertRaises(AttributeError):
                    setattr(res, name, 1)
                with self.assertRaises(AttributeError):
                    delattr(res, name)
        self.assertFalse(hasattr(res, "__dict__"))
        self.assertEqual(ImageOperationDispatchResult.__slots__, ("_plan", "_result", "_failures"))

    def test_17_direct_construction_refused(self):
        for args in ((), (object(), None, None, ()), (None, make_plan(), None, ())):
            with self.subTest(n=len(args)):
                with self.assertRaises(TypeError):
                    ImageOperationDispatchResult(*args)

    def test_18_subclassing_refused(self):
        with self.assertRaises(TypeError):
            type("Sub", (ImageOperationDispatchResult,), {})

    def test_19_equality_and_hash(self):
        a, b = dispatch_image_operation(make_plan()), dispatch_image_operation(make_plan())
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        self.assertNotEqual(a, dispatch_image_operation(make_plan(width=1)))
        self.assertNotEqual(a, dispatch_image_operation(make_plan(operation="resize")))
        self.assertNotEqual(dispatch_image_operation(make_plan(operation="resize")), dispatch_image_operation(make_plan(operation="crop")))
        self.assertEqual(dispatch_image_operation(None), dispatch_image_operation(1))
        self.assertEqual(hash(dispatch_image_operation(None)), hash(dispatch_image_operation(1)))
        self.assertNotEqual(a, a.to_dict())
        self.assertNotEqual(a, a.result)
        self.assertFalse(a == object())

    def test_20_fresh_to_dict_failures_and_codes(self):
        res = dispatch_image_operation(make_plan())
        d1, d2 = res.to_dict(), res.to_dict()
        self.assertEqual(d1, d2)
        self.assertIsNot(d1, d2)
        for key in ("plan", "result", "failures"):
            self.assertIsNot(d1[key], d2[key])
        self.assertIsNot(d1["result"]["output"], d2["result"]["output"])
        d1["ok"] = False
        d1["plan"]["width"] = -1
        d1["result"]["output"]["width"] = -1
        d1["result"]["failures"].append("x")
        d1["failures"].append("x")
        self.assertEqual(res.to_dict(), d2)
        self.assertEqual(res.result.output.width, 800)
        bad = dispatch_image_operation(None)
        f1, f2 = bad.failures, bad.failures
        self.assertIsNot(f1[0], f2[0])
        f1[0]["code"] = "changed"
        c = bad.codes()
        c.append("x")
        self.assertEqual(bad.codes(), [P + "INVALID_PLAN"])
        self.assertIsInstance(bad.failures, tuple)

    def test_21_copy_and_deepcopy_return_same_object(self):
        for res in (dispatch_image_operation(make_plan()), dispatch_image_operation(None), dispatch_image_operation(make_plan(operation="resize"))):
            self.assertIs(copy.copy(res), res)
            self.assertIs(copy.deepcopy(res), res)
            self.assertIs(copy.deepcopy([res])[0], res)

    def test_22_pickle_refused_like_the_other_multimedia_results(self):
        for res in (dispatch_image_operation(make_plan()), dispatch_image_operation(None)):
            for proto in range(0, pickle.HIGHEST_PROTOCOL + 1):
                with self.subTest(proto=proto):
                    with self.assertRaises(TypeError):
                        pickle.dumps(res, protocol=proto)

    def test_23_repr(self):
        self.assertEqual(repr(dispatch_image_operation(make_plan())), "ImageOperationDispatchResult(ok=True, codes=[])")
        self.assertEqual(repr(dispatch_image_operation(None)), "ImageOperationDispatchResult(ok=False, codes=['%sINVALID_PLAN'])" % P)


class TestPurityAndDeterminism(unittest.TestCase):
    def test_24_no_mutation_of_plan(self):
        plan = make_plan(quality=7)
        before, h = plan.to_dict(), hash(plan)
        for op in ("metadata",):
            for _ in range(3):
                dispatch_image_operation(plan)
        other = make_plan(operation="resize")
        before2 = other.to_dict()
        dispatch_image_operation(other)
        self.assertEqual(plan.to_dict(), before)
        self.assertEqual(hash(plan), h)
        self.assertEqual(plan, make_plan(quality=7))
        self.assertEqual(other.to_dict(), before2)

    def test_25_deterministic_repeated_calls(self):
        plan = make_plan()
        first = dispatch_image_operation(plan)
        for _ in range(25):
            again = dispatch_image_operation(plan)
            self.assertEqual(again, first)
            self.assertEqual(again.to_dict(), first.to_dict())
            self.assertEqual(hash(again), hash(first))
            self.assertIs(again.plan, plan)
        bad = dispatch_image_operation(make_plan(operation="resize"))
        self.assertEqual([dispatch_image_operation(make_plan(operation="resize")) for _ in range(5)], [bad] * 5)

    def test_26_never_raises_for_odd_inputs(self):
        for a in (None, 0, "", b"", [], {}, object(), float("nan"), ImageOperationDispatchResult, ImageOperationPlan):
            with self.subTest(a=type(a).__name__):
                self.assertEqual(dispatch_image_operation(a).codes(), [P + "INVALID_PLAN"])

    def test_27_no_filesystem_access(self):
        def refuse(*a, **k):
            raise AssertionError("filesystem access attempted")

        plan = make_plan()
        with mock.patch.object(builtins, "open", refuse), mock.patch("os.listdir", refuse), mock.patch("os.stat", refuse), \
                mock.patch("os.scandir", refuse), mock.patch("os.walk", refuse), mock.patch("os.path.exists", refuse), \
                mock.patch("os.path.isfile", refuse), mock.patch("io.open", refuse):
            self.assertTrue(dispatch_image_operation(plan).ok)
            self.assertEqual(dispatch_image_operation(make_plan(operation="resize")).codes(), [P + "UNSUPPORTED_OPERATION"])
            self.assertEqual(dispatch_image_operation(None).codes(), [P + "INVALID_PLAN"])

    def test_28_module_imports_only_plan_and_metadata_executor_and_does_no_io(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertTrue(all(isinstance(n, ast.ImportFrom) and n.level == 1 for n in imports))
        self.assertEqual([(n.module, sorted(a.name for a in n.names)) for n in imports],
                         [("image_operation_metadata_executor", ["execute_image_operation_metadata"]), ("image_operation_plan", ["ImageOperationPlan"])])
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"open", "os", "io", "subprocess", "socket", "random", "time", "pathlib", "ImageAsset", "ImageAssetRegistry",
                                  "ImageOperationRequest", "ImageOperationOutput", "create_image_operation_output", "execute_image_operation",
                                  "bytes", "bytearray", "memoryview", "Image", "PIL", "cv2"})
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertFalse(attrs & {"read", "write", "resize", "convert", "crop", "decode", "quality", "lower", "upper", "casefold", "strip"})

    def test_29_prompt_751_and_754_behaviour_unchanged_and_unaware_of_dispatcher(self):
        plan = make_plan()
        r751 = execute_image_operation(plan)
        self.assertEqual((r751.ok, r751.codes()), (False, ["IMAGE_OPERATION_EXECUTOR_NOT_IMPLEMENTED"]))
        self.assertTrue(execute_image_operation_metadata(plan).ok)
        self.assertEqual(execute_image_operation_metadata(make_plan(operation="resize")).codes(), [me.FAILURE_UNSUPPORTED_OPERATION])
        for name in ("image_asset.py", "image_asset_registry.py", "image_operation_request.py", "image_operation_validator.py",
                     "image_operation_plan.py", "image_operation_executor.py", "image_operation_output.py", "image_operation_output_validator.py",
                     "image_operation_metadata_executor.py"):
            with open(os.path.join(PY_ROOT, "multimedia", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("image_operation_dispatcher", "dispatch_image_operation", "ImageOperationDispatchResult"):
                self.assertNotIn(token, text, name)

    def test_30_multimedia_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "multimedia")) if f != "__pycache__"),
                         ["__init__.py", "audio_asset.py", "audio_asset_registry.py", "audio_operation_batch.py", "audio_operation_batch_summary.py", "audio_operation_dispatcher.py", "audio_operation_executor.py", "audio_operation_metadata_executor.py", "audio_operation_output.py", "audio_operation_output_validator.py", "audio_operation_pipeline.py", "audio_operation_plan.py", "audio_operation_request.py", "audio_operation_validator.py", "image_asset.py", "image_asset_registry.py", "image_operation_batch.py", "image_operation_batch_summary.py", "image_operation_dispatcher.py",
                          "image_operation_executor.py", "image_operation_metadata_executor.py", "image_operation_output.py",
                          "image_operation_output_validator.py", "image_operation_pipeline.py", "image_operation_plan.py", "image_operation_request.py",
                          "image_operation_validator.py"])
        with open(os.path.join(PY_ROOT, "multimedia", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_31_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("ImageOperationDispatchResult", "dispatch_image_operation", P, "INVALID_PLAN", "UNSUPPORTED_OPERATION",
                       "execute_image_operation_metadata", "\"metadata\"", "does NOT", "Prompt 756", "Prompt 751", "Prompt 754"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
