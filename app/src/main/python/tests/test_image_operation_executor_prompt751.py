"""Prompt 751 - Section 8 image operation executor boundary (`multimedia.image_operation_executor`)."""
import ast
import builtins
import copy
import hashlib
import io
import os
import pickle
import unittest
from unittest import mock

from multimedia import image_operation_executor as ioe
from multimedia.image_asset import create_image_asset
from multimedia.image_asset_registry import create_image_asset_registry
from multimedia.image_operation_executor import ImageOperationExecutionResult, execute_image_operation
from multimedia.image_operation_plan import ImageOperationPlan, create_image_operation_plan
from multimedia.image_operation_request import create_image_operation_request
from multimedia.image_operation_validator import validate_image_operation_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section8_image_operation_executor_prompt751.md")
MODULE = os.path.join(PY_ROOT, "multimedia", "image_operation_executor.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
P = "IMAGE_OPERATION_EXECUTOR_"
INVALID, NOT_IMPL = P + "INVALID_PLAN", P + "NOT_IMPLEMENTED"
FIELDS = ("image_id", "operation", "target_format", "width", "height", "quality")


def make_plan(**over):
    image_id = over.get("image_id", "hero")
    a = create_image_asset({"image_id": image_id, "name": "N", "description": "", "format": "png", "width": 10, "height": 10})
    assert a.ok, a.failures
    reg = create_image_asset_registry([a.asset])
    assert reg.ok, reg.failures
    data = {"image_id": "hero", "operation": "resize", "target_format": "webp", "width": 800, "height": 600, "quality": 85}
    data.update(over)
    req = create_image_operation_request(data)
    assert req.ok, req.failures
    vr = validate_image_operation_request(req.request, reg.registry)
    assert vr.ok, vr.codes()
    pr = create_image_operation_plan(vr)
    assert pr.ok, pr.codes()
    return pr.plan


BAD_PLANS = (None, {}, [], "plan", 5, True, object(), (), b"x")


class TestInvalidPlan(unittest.TestCase):
    def test_1_invalid_plan_is_rejected(self):
        plan_dict = make_plan().to_dict()
        for bad in BAD_PLANS + (plan_dict,):
            with self.subTest(bad=type(bad).__name__):
                res = execute_image_operation(bad)
                self.assertIs(type(res), ImageOperationExecutionResult)
                self.assertIs(res.ok, False)
                self.assertIsNone(res.plan)
                self.assertEqual(res.status, "rejected")
                self.assertEqual(res.codes(), [INVALID])
                self.assertEqual(res.failures[0]["field"], "plan")

    def test_2_look_alike_plan_is_rejected_and_never_read(self):
        class Fake:
            def __getattr__(self, name):
                raise AssertionError("must not read " + name)

        for fake in (Fake(), mock.MagicMock()):
            res = execute_image_operation(fake)
            self.assertEqual((res.ok, res.plan, res.status, res.codes()), (False, None, "rejected", [INVALID]))

    def test_3_other_pipeline_objects_are_rejected(self):
        plan = make_plan()
        pr = create_image_operation_plan(None)
        for bad in (pr, plan.to_dict(), repr(plan)):
            self.assertEqual(execute_image_operation(bad).codes(), [INVALID])

    def test_4_invalid_plan_never_raises(self):
        class Evil:
            def __eq__(self, o):
                raise RuntimeError("no")

            __hash__ = None

        for bad in (Evil(), float("nan"), 10 ** 100):
            self.assertEqual(execute_image_operation(bad).status, "rejected")


class TestValidPlan(unittest.TestCase):
    def test_5_valid_plan_is_not_implemented_never_success(self):
        plan = make_plan()
        res = execute_image_operation(plan)
        self.assertIs(type(res), ImageOperationExecutionResult)
        self.assertIs(res.ok, False)
        self.assertEqual(res.status, "not_implemented")
        self.assertEqual(res.codes(), [NOT_IMPL])
        self.assertEqual(len(res.failures), 1)
        self.assertEqual(res.failures[0]["field"], "plan")
        self.assertEqual(res.to_dict()["ok"], False)

    def test_6_exact_plan_identity_preserved(self):
        plan = make_plan()
        res = execute_image_operation(plan)
        self.assertIs(res.plan, plan)
        self.assertIs(execute_image_operation(plan).plan, plan)
        self.assertIs(type(res.plan), ImageOperationPlan)

    def test_7_exact_value_preservation_through_result(self):
        image_id = "".join(["hero", "_", "x"])
        op = "".join(["res", "ize"])
        fmt = "".join(["we", "bp"])
        plan = make_plan(image_id=image_id, operation=op, target_format=fmt, width=1, height=99999, quality=100)
        res = execute_image_operation(plan)
        self.assertIs(res.plan.image_id, image_id)
        self.assertIs(res.plan.operation, op)
        self.assertIs(res.plan.target_format, fmt)
        self.assertEqual((res.plan.width, res.plan.height, res.plan.quality), (1, 99999, 100))
        self.assertEqual(res.to_dict()["plan"], {"image_id": image_id, "operation": op, "target_format": fmt, "width": 1, "height": 99999, "quality": 100})
        self.assertEqual(list(res.to_dict()["plan"]), list(FIELDS))

    def test_8_odd_but_valid_values_preserved_without_interpretation(self):
        for over in ({"operation": "  RESIZE\t"}, {"target_format": "  WebP "}, {"target_format": ""}, {"operation": "blur", "target_format": "tiff"}):
            with self.subTest(over=over):
                plan = make_plan(**over)
                res = execute_image_operation(plan)
                self.assertEqual((res.status, res.codes()), ("not_implemented", [NOT_IMPL]))
                self.assertEqual(res.plan.to_dict(), plan.to_dict())

    def test_9_status_is_exact_str_and_limited(self):
        self.assertEqual(ioe.STATUSES, ("rejected", "not_implemented"))
        for res in (execute_image_operation(make_plan()), execute_image_operation(None)):
            self.assertIs(type(res.status), str)
            self.assertIn(res.status, ("rejected", "not_implemented"))
            self.assertIs(type(res.to_dict()["status"]), str)

    def test_10_failure_codes_are_exactly_the_two(self):
        self.assertEqual(ioe.FAILURE_CODES, (INVALID, NOT_IMPL))
        seen = set()
        for arg in (None, make_plan(), 5, {}):
            seen.update(execute_image_operation(arg).codes())
        self.assertEqual(seen, {INVALID, NOT_IMPL})
        for res in (execute_image_operation(None), execute_image_operation(make_plan())):
            self.assertEqual(len(res.codes()), 1)

    def test_11_status_and_code_pairing(self):
        self.assertEqual((execute_image_operation(None).status, execute_image_operation(None).codes()), ("rejected", [INVALID]))
        p = make_plan()
        self.assertEqual((execute_image_operation(p).status, execute_image_operation(p).codes()), ("not_implemented", [NOT_IMPL]))


class TestSafety(unittest.TestCase):
    def test_12_no_filesystem_access(self):
        plan = make_plan()

        def boom(*a, **k):
            raise AssertionError("filesystem access attempted")

        targets = [(builtins, "open"), (io, "open"), (os, "open"), (os, "listdir"), (os, "scandir"), (os, "stat"), (os, "remove"),
                   (os, "rename"), (os, "mkdir"), (os, "walk")]
        patches = [mock.patch.object(m, n, boom) for m, n in targets]
        for p in patches:
            p.start()
        try:
            for arg in (plan, None, {}, 5):
                res = execute_image_operation(arg)
                res.to_dict()
                res.failures
                repr(res)
                hash(res)
        finally:
            for p in reversed(patches):
                p.stop()

    def test_13_no_mutation_of_supplied_plan(self):
        plan = make_plan()
        before = (plan.to_dict(), repr(plan), hash(plan), plan.__slots__)
        res = execute_image_operation(plan)
        res.to_dict()["plan"]["image_id"] = "mutated"
        self.assertEqual((plan.to_dict(), repr(plan), hash(plan), plan.__slots__), before)
        self.assertEqual(plan, make_plan())
        bad = {"image_id": "x"}
        execute_image_operation(bad)
        self.assertEqual(bad, {"image_id": "x"})

    def test_14_deterministic_repeated_execution(self):
        plan = make_plan()
        r1, r2 = execute_image_operation(plan), execute_image_operation(plan)
        self.assertIsNot(r1, r2)
        self.assertEqual(r1, r2)
        self.assertEqual(hash(r1), hash(r2))
        self.assertEqual(r1.to_dict(), r2.to_dict())
        self.assertEqual(r1.failures, r2.failures)
        for _ in range(5):
            self.assertEqual(execute_image_operation(plan), r1)
        b1, b2 = execute_image_operation(None), execute_image_operation(None)
        self.assertIsNot(b1, b2)
        self.assertEqual(b1, b2)
        self.assertEqual(hash(b1), hash(b2))
        self.assertEqual(execute_image_operation(make_plan()), r1)

    def test_15_no_execution_surface(self):
        res = execute_image_operation(make_plan())
        self.assertEqual({n for n in dir(res) if not n.startswith("_")}, {"ok", "plan", "status", "failures", "codes", "to_dict"})
        public = {n for n in dir(ioe) if not n.startswith("_")}
        self.assertEqual(public, {"ImageOperationPlan", "STATUS_REJECTED", "STATUS_NOT_IMPLEMENTED", "STATUSES", "FAILURE_INVALID_PLAN",
                                  "FAILURE_NOT_IMPLEMENTED", "FAILURE_CODES", "ImageOperationExecutionResult", "execute_image_operation"})


class TestResultContract(unittest.TestCase):
    def setUp(self):
        self.plan = make_plan()
        self.res = execute_image_operation(self.plan)
        self.bad = execute_image_operation(None)

    def test_16_direct_construction_refused(self):
        for args in ((), (None, None, "rejected", []), (object(), None, "rejected", []), (object(), self.plan, "not_implemented", [])):
            with self.subTest(n=len(args)):
                with self.assertRaises(TypeError):
                    ImageOperationExecutionResult(*args)

    def test_17_subclassing_refused(self):
        with self.assertRaises(TypeError):
            type("S", (ImageOperationExecutionResult,), {})

    def test_18_immutable(self):
        for obj in (self.res, self.bad):
            for name in ("ok", "plan", "status", "failures", "_plan", "_status", "_failures", "extra"):
                with self.subTest(name=name):
                    with self.assertRaises(AttributeError):
                        setattr(obj, name, 1)
                    with self.assertRaises(AttributeError):
                        delattr(obj, name)
        self.assertEqual(ImageOperationExecutionResult.__slots__, ("_plan", "_status", "_failures"))
        self.assertFalse(hasattr(self.res, "__dict__"))

    def test_19_fresh_to_dict_and_failures(self):
        self.assertEqual(list(self.res.to_dict()), ["ok", "plan", "status", "failures"])
        d = self.res.to_dict()
        d["plan"]["image_id"] = "mutated"
        d["failures"][0]["code"] = "mutated"
        d["failures"].append("x")
        d["status"] = "mutated"
        d["ok"] = True
        f = self.res.failures
        f[0]["code"] = "mutated"
        self.assertEqual(self.res.to_dict(), {"ok": False, "plan": self.plan.to_dict(), "status": "not_implemented",
                                              "failures": [{"code": NOT_IMPL, "field": "plan", "message": self.res.failures[0]["message"]}]})
        self.assertEqual(self.res.plan.image_id, "hero")
        self.assertIsNot(self.res.to_dict(), self.res.to_dict())
        self.assertIsNot(self.res.to_dict()["plan"], self.res.to_dict()["plan"])
        self.assertIsNot(self.res.failures[0], self.res.failures[0])
        self.assertIsInstance(self.res.failures, tuple)
        bd = self.bad.to_dict()
        self.assertEqual((bd["ok"], bd["plan"], bd["status"], [x["code"] for x in bd["failures"]]), (False, None, "rejected", [INVALID]))
        bd["failures"][0]["code"] = "mutated"
        self.assertEqual(self.bad.codes(), [INVALID])

    def test_20_equality_and_hash(self):
        other = execute_image_operation(make_plan())
        self.assertEqual(self.res, other)
        self.assertEqual(hash(self.res), hash(other))
        self.assertEqual(len({self.res, other}), 1)
        self.assertEqual(self.bad, execute_image_operation(5))
        self.assertEqual(hash(self.bad), hash(execute_image_operation(5)))
        self.assertNotEqual(self.res, self.bad)
        for field, value in (("operation", "blur"), ("target_format", ""), ("width", 801), ("height", 601), ("quality", 86), ("image_id", "other")):
            with self.subTest(field=field):
                self.assertNotEqual(self.res, execute_image_operation(make_plan(**{field: value})))
        for foreign in (self.res.to_dict(), None, self.plan, "x"):
            self.assertNotEqual(self.res, foreign)

    def test_21_copy_and_deepcopy_return_same_object(self):
        for obj in (self.res, self.bad):
            self.assertIs(copy.copy(obj), obj)
            self.assertIs(copy.deepcopy(obj), obj)
            self.assertIs(copy.deepcopy({"k": [obj]})["k"][0], obj)
        self.assertIs(copy.deepcopy(self.res).plan, self.plan)

    def test_22_pickle_refused(self):
        for obj in (self.res, self.bad):
            for proto in range(pickle.HIGHEST_PROTOCOL + 1):
                with self.subTest(proto=proto):
                    with self.assertRaises(TypeError):
                        pickle.dumps(obj, protocol=proto)

    def test_23_repr_is_stable(self):
        self.assertEqual(repr(self.res), "ImageOperationExecutionResult(ok=False, status='not_implemented', codes=['%s'])" % NOT_IMPL)
        self.assertEqual(repr(self.bad), "ImageOperationExecutionResult(ok=False, status='rejected', codes=['%s'])" % INVALID)


class TestBoundaries(unittest.TestCase):
    def test_24_module_is_pure(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imported = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                imported += [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                imported.append("." * n.level + (n.module or ""))
        self.assertEqual(imported, [".image_operation_plan"])
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"open", "os", "io", "subprocess", "socket", "random", "time", "pathlib", "ImageAsset", "ImageAssetRegistry",
                                  "ImageOperationRequest", "ImageOperationValidationResult"})
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertFalse(attrs & {"asset", "assets", "lookup", "image_ids", "read", "write", "resize", "convert", "crop", "decode"})

    def test_25_earlier_production_modules_are_unaware_of_the_executor(self):
        for name in ("image_asset.py", "image_asset_registry.py", "image_operation_request.py", "image_operation_validator.py", "image_operation_plan.py"):
            with open(os.path.join(PY_ROOT, "multimedia", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("image_operation_executor", "ImageOperationExecutionResult", "execute_image_operation"):
                self.assertNotIn(token, text, name)

    def test_26_multimedia_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "multimedia")) if f != "__pycache__"),
                         ["__init__.py", "audio_asset.py", "audio_asset_registry.py", "audio_operation_batch.py", "audio_operation_batch_summary.py", "audio_operation_dispatcher.py", "audio_operation_executor.py", "audio_operation_metadata_executor.py", "audio_operation_output.py", "audio_operation_output_validator.py", "audio_operation_pipeline.py", "audio_operation_plan.py", "audio_operation_request.py", "audio_operation_validator.py", "image_asset.py", "image_asset_registry.py", "image_operation_batch.py", "image_operation_batch_summary.py", "image_operation_dispatcher.py", "image_operation_executor.py",
                          "image_operation_metadata_executor.py", "image_operation_output.py", "image_operation_output_validator.py", "image_operation_pipeline.py", "image_operation_plan.py", "image_operation_request.py", "image_operation_validator.py"])
        with open(os.path.join(PY_ROOT, "multimedia", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_27_end_to_end_through_public_apis_only(self):
        plan = make_plan(image_id="logo", operation="convert", target_format="png", width=64, height=64, quality=100)
        res = execute_image_operation(plan)
        self.assertEqual((res.ok, res.status, res.codes()), (False, "not_implemented", [NOT_IMPL]))
        self.assertIs(res.plan, plan)

    def test_28_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("ImageOperationExecutionResult", "execute_image_operation", "IMAGE_OPERATION_EXECUTOR_", "INVALID_PLAN",
                       "NOT_IMPLEMENTED", "not_implemented", "rejected", "does NOT", "Prompt 752", "execution boundary"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
