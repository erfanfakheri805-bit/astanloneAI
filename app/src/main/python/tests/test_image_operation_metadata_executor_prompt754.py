"""Prompt 754 - Section 8 metadata-only image operation executor (`multimedia.image_operation_metadata_executor`)."""
import ast
import builtins
import copy
import hashlib
import os
import pickle
import unittest
from unittest import mock

from multimedia import image_operation_metadata_executor as me
from multimedia.image_asset import create_image_asset
from multimedia.image_asset_registry import create_image_asset_registry
from multimedia.image_operation_executor import execute_image_operation
from multimedia.image_operation_metadata_executor import ImageOperationMetadataExecutionResult, execute_image_operation_metadata
from multimedia.image_operation_output import ImageOperationOutput, create_image_operation_output
from multimedia.image_operation_output_validator import validate_image_operation_output
from multimedia.image_operation_plan import ImageOperationPlan, create_image_operation_plan
from multimedia.image_operation_request import create_image_operation_request
from multimedia.image_operation_validator import validate_image_operation_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section8_image_operation_metadata_executor_prompt754.md")
MODULE = os.path.join(PY_ROOT, "multimedia", "image_operation_metadata_executor.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
P = "IMAGE_OPERATION_METADATA_EXECUTOR_"


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
    def test_1_valid_metadata_operation(self):
        res = execute_image_operation_metadata(make_plan())
        self.assertIs(type(res), ImageOperationMetadataExecutionResult)
        self.assertIs(res.ok, True)
        self.assertEqual(res.failures, ())
        self.assertEqual(res.codes(), [])

    def test_2_exact_plan_identity_preserved(self):
        plan = make_plan()
        res = execute_image_operation_metadata(plan)
        self.assertIs(res.plan, plan)

    def test_3_output_values(self):
        plan = make_plan(image_id="logo", target_format="png", width=64, height=32)
        out = execute_image_operation_metadata(plan).output
        self.assertEqual(out.to_dict(), {"image_id": "logo", "operation": "metadata", "output_format": "png", "width": 64, "height": 32})
        self.assertEqual((out.image_id, out.operation, out.output_format, out.width, out.height),
                         (plan.image_id, plan.operation, plan.target_format, plan.width, plan.height))

    def test_4_output_is_exact_image_operation_output(self):
        self.assertIs(type(execute_image_operation_metadata(make_plan()).output), ImageOperationOutput)

    def test_5_output_factory_is_used(self):
        real = create_image_operation_output
        calls = []

        def spy(data):
            calls.append(data)
            return real(data)

        with mock.patch.object(me, "create_image_operation_output", spy):
            res = execute_image_operation_metadata(make_plan())
        self.assertTrue(res.ok)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], {"image_id": "hero", "operation": "metadata", "output_format": "webp", "width": 800, "height": 600})
        self.assertEqual(res.output, real(calls[0]).output)

    def test_6_output_is_never_constructed_directly(self):
        with mock.patch.object(ImageOperationOutput, "__init__", side_effect=AssertionError("direct construction")) as init:
            with self.assertRaises(AssertionError):
                ImageOperationOutput()
        self.assertTrue(init.called)
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertNotIn("ImageOperationOutput", called)
        self.assertIn("create_image_operation_output", called)

    def test_7_generated_output_passes_output_validation(self):
        plan = make_plan(target_format="avif", width=3, height=4, quality=1)
        res = execute_image_operation_metadata(plan)
        check = validate_image_operation_output(plan, res.output)
        self.assertTrue(check.ok, check.codes())
        self.assertIs(check.plan, plan)
        self.assertIs(check.output, res.output)

    def test_8_exact_string_and_int_identity_preserved(self):
        image_id = "".join(["her", "o", "_x"])
        fmt = "".join(["we", "bp"])
        plan = make_plan(image_id=image_id, target_format=fmt, width=10 ** 6 + 1, height=10 ** 6 + 2)
        out = execute_image_operation_metadata(plan).output
        self.assertIs(out.image_id, plan.image_id)
        self.assertIs(out.operation, plan.operation)
        self.assertIs(out.output_format, plan.target_format)
        self.assertIs(out.width, plan.width)
        self.assertIs(out.height, plan.height)

    def test_9_values_are_not_normalized(self):
        plan = make_plan(image_id=" Hero ", target_format=" WebP ")
        out = execute_image_operation_metadata(plan).output
        self.assertEqual((out.image_id, out.output_format), (" Hero ", " WebP "))

    def test_10_quality_is_ignored(self):
        a = execute_image_operation_metadata(make_plan(quality=1))
        b = execute_image_operation_metadata(make_plan(quality=100))
        self.assertEqual(a.output, b.output)
        self.assertNotIn("quality", a.output.to_dict())

    def test_11_to_dict_of_success(self):
        plan = make_plan()
        res = execute_image_operation_metadata(plan)
        self.assertEqual(list(res.to_dict()), ["ok", "plan", "output", "failures"])
        self.assertEqual(res.to_dict(), {"ok": True, "plan": plan.to_dict(), "output": res.output.to_dict(), "failures": []})


class TestRejections(unittest.TestCase):
    def test_12_unsupported_operation(self):
        for op in ("resize", "convert", "crop", "blur", "x"):
            with self.subTest(op=op):
                plan = make_plan(operation=op)
                res = execute_image_operation_metadata(plan)
                self.assertFalse(res.ok)
                self.assertIs(res.plan, plan)
                self.assertIsNone(res.output)
                self.assertEqual(res.codes(), [P + "UNSUPPORTED_OPERATION"])
                self.assertEqual(res.failures[0]["field"], "operation")

    def test_13_operation_match_is_exact(self):
        for op in ("Metadata", "METADATA", " metadata", "metadata ", "metadata\n", "meta", "metadatas"):
            with self.subTest(op=op):
                res = execute_image_operation_metadata(make_plan(operation=op))
                self.assertFalse(res.ok)
                self.assertEqual(res.codes(), [P + "UNSUPPORTED_OPERATION"])

    def test_14_invalid_plan(self):
        for bad in (None, {}, make_plan().to_dict(), "plan", 1, object(), b"", [], create_image_operation_output(
                {"image_id": "a", "operation": "metadata", "output_format": "c", "width": 1, "height": 1})):
            with self.subTest(bad=type(bad).__name__):
                res = execute_image_operation_metadata(bad)
                self.assertFalse(res.ok)
                self.assertIsNone(res.plan)
                self.assertIsNone(res.output)
                self.assertEqual(res.codes(), [P + "INVALID_PLAN"])
                self.assertEqual(res.failures[0]["field"], "plan")

    def test_15_look_alike_and_subclass_plans_rejected(self):
        with self.assertRaises(TypeError):
            type("Sub", (ImageOperationPlan,), {})

        class Fake:
            image_id, operation, target_format, width, height, quality = "hero", "metadata", "webp", 800, 600, 85

        res = execute_image_operation_metadata(Fake())
        self.assertEqual(res.codes(), [P + "INVALID_PLAN"])
        self.assertIsNone(res.plan)

    def test_16_invalid_plan_object_is_never_read(self):
        class Trap:
            def __getattribute__(self, name):
                raise AssertionError("must not be read: " + name)

        self.assertEqual(execute_image_operation_metadata(Trap()).codes(), [P + "INVALID_PLAN"])

    def test_17_output_creation_failure_for_valid_plan(self):
        plan = make_plan()
        failed = create_image_operation_output({})
        self.assertFalse(failed.ok)
        with mock.patch.object(me, "create_image_operation_output", return_value=failed):
            res = execute_image_operation_metadata(plan)
        self.assertFalse(res.ok)
        self.assertIs(res.plan, plan)
        self.assertIsNone(res.output)
        self.assertEqual(res.codes(), [P + "OUTPUT_CREATION_FAILED"])
        self.assertEqual(res.failures[0]["field"], "output")

    def test_18_output_creation_failure_variants(self):
        plan = make_plan()
        wrong = create_image_operation_output({"image_id": "a", "operation": "metadata", "output_format": "c", "width": 1, "height": 1})
        for name, patch in (("raises", mock.Mock(side_effect=RuntimeError("boom"))), ("returns_none", mock.Mock(return_value=None)),
                            ("ok_but_foreign_output", mock.Mock(return_value=mock.Mock(ok=True, output=object()))),
                            ("ok_without_output", mock.Mock(return_value=mock.Mock(ok=True, output=None))), ("sanity", None)):
            with self.subTest(name=name):
                if patch is None:
                    self.assertTrue(execute_image_operation_metadata(plan).ok)
                    continue
                with mock.patch.object(me, "create_image_operation_output", patch):
                    res = execute_image_operation_metadata(plan)
                self.assertEqual(res.codes(), [P + "OUTPUT_CREATION_FAILED"])
                self.assertIs(res.plan, plan)
                self.assertIsNone(res.output)
        self.assertTrue(wrong.ok)

    def test_19_only_three_failure_codes(self):
        self.assertEqual(me.FAILURE_CODES, (P + "INVALID_PLAN", P + "UNSUPPORTED_OPERATION", P + "OUTPUT_CREATION_FAILED"))
        seen = set()
        for r in (execute_image_operation_metadata(None), execute_image_operation_metadata(make_plan(operation="resize"))):
            seen.update(r.codes())
        with mock.patch.object(me, "create_image_operation_output", return_value=create_image_operation_output(None)):
            seen.update(execute_image_operation_metadata(make_plan()).codes())
        self.assertEqual(seen, set(me.FAILURE_CODES))

    def test_20_failure_to_dict_shapes(self):
        plan = make_plan(operation="resize")
        d = execute_image_operation_metadata(plan).to_dict()
        self.assertEqual((d["ok"], d["plan"], d["output"]), (False, plan.to_dict(), None))
        self.assertEqual([(f["code"], f["field"]) for f in d["failures"]], [(P + "UNSUPPORTED_OPERATION", "operation")])
        d = execute_image_operation_metadata(None).to_dict()
        self.assertEqual((d["ok"], d["plan"], d["output"]), (False, None, None))
        self.assertEqual([f["code"] for f in d["failures"]], [P + "INVALID_PLAN"])


class TestResultContract(unittest.TestCase):
    def test_21_immutable(self):
        res = execute_image_operation_metadata(make_plan())
        for name in ("ok", "plan", "output", "failures", "extra", "_failures"):
            with self.subTest(name=name):
                with self.assertRaises(AttributeError):
                    setattr(res, name, 1)
                with self.assertRaises(AttributeError):
                    delattr(res, name)
        self.assertFalse(hasattr(res, "__dict__"))
        self.assertEqual(ImageOperationMetadataExecutionResult.__slots__, ("_plan", "_output", "_failures"))

    def test_22_direct_construction_refused(self):
        for args in ((), (object(), None, None, ()), (None, make_plan(), None, ())):
            with self.subTest(n=len(args)):
                with self.assertRaises(TypeError):
                    ImageOperationMetadataExecutionResult(*args)

    def test_23_subclassing_refused(self):
        with self.assertRaises(TypeError):
            type("Sub", (ImageOperationMetadataExecutionResult,), {})

    def test_24_equality_and_hash(self):
        a, b = execute_image_operation_metadata(make_plan()), execute_image_operation_metadata(make_plan())
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        self.assertNotEqual(a, execute_image_operation_metadata(make_plan(width=1)))
        self.assertNotEqual(a, execute_image_operation_metadata(make_plan(operation="resize")))
        self.assertNotEqual(execute_image_operation_metadata(make_plan(operation="resize")), execute_image_operation_metadata(make_plan(operation="crop")))
        self.assertEqual(execute_image_operation_metadata(None), execute_image_operation_metadata(1))
        self.assertEqual(hash(execute_image_operation_metadata(None)), hash(execute_image_operation_metadata(1)))
        self.assertNotEqual(a, a.to_dict())
        self.assertFalse(a == object())

    def test_25_fresh_to_dict_failures_and_codes(self):
        res = execute_image_operation_metadata(make_plan())
        d1, d2 = res.to_dict(), res.to_dict()
        self.assertEqual(d1, d2)
        self.assertIsNot(d1, d2)
        self.assertIsNot(d1["plan"], d2["plan"])
        self.assertIsNot(d1["output"], d2["output"])
        self.assertIsNot(d1["failures"], d2["failures"])
        d1["ok"] = False
        d1["plan"]["width"] = -1
        d1["output"]["width"] = -1
        d1["failures"].append("x")
        self.assertEqual(res.to_dict(), d2)
        self.assertEqual(res.output.width, 800)
        bad = execute_image_operation_metadata(None)
        f1, f2 = bad.failures, bad.failures
        self.assertIsNot(f1[0], f2[0])
        f1[0]["code"] = "changed"
        c = bad.codes()
        c.append("x")
        self.assertEqual(bad.codes(), [P + "INVALID_PLAN"])
        self.assertIsInstance(bad.failures, tuple)
        self.assertIsNot(bad.to_dict()["failures"], bad.to_dict()["failures"])

    def test_26_copy_and_deepcopy_return_same_object(self):
        for res in (execute_image_operation_metadata(make_plan()), execute_image_operation_metadata(None),
                    execute_image_operation_metadata(make_plan(operation="resize"))):
            self.assertIs(copy.copy(res), res)
            self.assertIs(copy.deepcopy(res), res)
            self.assertIs(copy.deepcopy([res])[0], res)

    def test_27_pickle_refused(self):
        res = execute_image_operation_metadata(make_plan())
        for proto in range(0, pickle.HIGHEST_PROTOCOL + 1):
            with self.subTest(proto=proto):
                with self.assertRaises(TypeError):
                    pickle.dumps(res, protocol=proto)

    def test_28_repr(self):
        self.assertEqual(repr(execute_image_operation_metadata(make_plan())), "ImageOperationMetadataExecutionResult(ok=True, codes=[])")
        self.assertEqual(repr(execute_image_operation_metadata(None)),
                         "ImageOperationMetadataExecutionResult(ok=False, codes=['%sINVALID_PLAN'])" % P)


class TestPurityAndDeterminism(unittest.TestCase):
    def test_29_no_mutation_of_plan(self):
        plan = make_plan(quality=7)
        before, h = plan.to_dict(), hash(plan)
        for _ in range(3):
            execute_image_operation_metadata(plan)
        self.assertEqual(plan.to_dict(), before)
        self.assertEqual(hash(plan), h)
        self.assertEqual(plan, make_plan(quality=7))

    def test_30_deterministic_repeated_execution(self):
        plan = make_plan()
        first = execute_image_operation_metadata(plan)
        for _ in range(25):
            again = execute_image_operation_metadata(plan)
            self.assertEqual(again, first)
            self.assertEqual(again.to_dict(), first.to_dict())
            self.assertEqual(hash(again), hash(first))
            self.assertIs(again.plan, plan)
        bad = execute_image_operation_metadata(make_plan(operation="resize"))
        self.assertEqual([execute_image_operation_metadata(make_plan(operation="resize")) for _ in range(5)], [bad] * 5)

    def test_31_never_raises_for_odd_inputs(self):
        for a in (None, 0, "", b"", [], {}, object(), float("nan"), ImageOperationMetadataExecutionResult, ImageOperationPlan):
            with self.subTest(a=type(a).__name__):
                self.assertEqual(execute_image_operation_metadata(a).codes(), [P + "INVALID_PLAN"])

    def test_32_no_filesystem_access(self):
        def refuse(*a, **k):
            raise AssertionError("filesystem access attempted")

        plan = make_plan()
        with mock.patch.object(builtins, "open", refuse), mock.patch("os.listdir", refuse), mock.patch("os.stat", refuse), \
                mock.patch("os.scandir", refuse), mock.patch("os.walk", refuse), mock.patch("os.path.exists", refuse), \
                mock.patch("os.path.isfile", refuse), mock.patch("io.open", refuse):
            self.assertTrue(execute_image_operation_metadata(plan).ok)
            self.assertEqual(execute_image_operation_metadata(make_plan(operation="resize")).codes(), [P + "UNSUPPORTED_OPERATION"])
            self.assertEqual(execute_image_operation_metadata(None).codes(), [P + "INVALID_PLAN"])

    def test_33_module_imports_only_plan_and_output_and_does_no_io(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertTrue(all(isinstance(n, ast.ImportFrom) and n.level == 1 for n in imports))
        self.assertEqual([(n.module, sorted(a.name for a in n.names)) for n in imports],
                         [("image_operation_output", ["ImageOperationOutput", "create_image_operation_output"]), ("image_operation_plan", ["ImageOperationPlan"])])
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"open", "os", "io", "subprocess", "socket", "random", "time", "pathlib", "ImageAsset", "ImageAssetRegistry",
                                  "ImageOperationRequest", "bytes", "bytearray", "memoryview", "Image", "PIL", "cv2"})
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertFalse(attrs & {"read", "write", "resize", "convert", "crop", "decode", "quality", "lower", "upper", "casefold", "strip"})

    def test_34_prompt_751_executor_is_unchanged_in_behaviour_and_unaware(self):
        plan = make_plan()
        res = execute_image_operation(plan)
        self.assertFalse(res.ok)
        self.assertEqual(res.codes(), ["IMAGE_OPERATION_EXECUTOR_NOT_IMPLEMENTED"])
        self.assertIs(res.plan, plan)
        for name in ("image_asset.py", "image_asset_registry.py", "image_operation_request.py", "image_operation_validator.py",
                     "image_operation_plan.py", "image_operation_executor.py", "image_operation_output.py", "image_operation_output_validator.py"):
            with open(os.path.join(PY_ROOT, "multimedia", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("image_operation_metadata_executor", "execute_image_operation_metadata", "ImageOperationMetadataExecutionResult"):
                self.assertNotIn(token, text, name)

    def test_35_multimedia_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "multimedia")) if f != "__pycache__"),
                         ["__init__.py", "audio_asset.py", "audio_asset_registry.py", "audio_operation_batch.py", "audio_operation_batch_summary.py", "audio_operation_dispatcher.py", "audio_operation_executor.py", "audio_operation_metadata_executor.py", "audio_operation_output.py", "audio_operation_output_validator.py", "audio_operation_pipeline.py", "audio_operation_plan.py", "audio_operation_request.py", "audio_operation_validator.py", "image_asset.py", "image_asset_registry.py", "image_operation_batch.py", "image_operation_batch_summary.py", "image_operation_dispatcher.py", "image_operation_executor.py",
                          "image_operation_metadata_executor.py", "image_operation_output.py", "image_operation_output_validator.py", "image_operation_pipeline.py",
                          "image_operation_plan.py", "image_operation_request.py", "image_operation_validator.py"])
        with open(os.path.join(PY_ROOT, "multimedia", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_36_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("ImageOperationMetadataExecutionResult", "execute_image_operation_metadata", P, "INVALID_PLAN", "UNSUPPORTED_OPERATION",
                       "OUTPUT_CREATION_FAILED", "create_image_operation_output", "\"metadata\"", "does NOT", "Prompt 755", "Prompt 751"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
