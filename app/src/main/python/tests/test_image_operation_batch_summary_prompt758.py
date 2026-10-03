"""Prompt 758 - Section 8 image operation batch summary (`multimedia.image_operation_batch_summary`)."""
import ast
import builtins
import copy
import hashlib
import os
import pickle
import unittest
from unittest import mock

from multimedia import image_operation_batch as b
from multimedia import image_operation_batch_summary as s
from multimedia.image_asset import create_image_asset
from multimedia.image_asset_registry import create_image_asset_registry
from multimedia.image_operation_batch import ImageOperationBatchResult, process_image_operations
from multimedia.image_operation_batch_summary import ImageOperationBatchSummary, create_image_operation_batch_summary
from multimedia.image_operation_pipeline import process_image_operation
from multimedia.image_operation_request import create_image_operation_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section8_image_operation_batch_summary_prompt758.md")
MODULE = os.path.join(PY_ROOT, "multimedia", "image_operation_batch_summary.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
INVALID = "IMAGE_OPERATION_BATCH_SUMMARY_INVALID_RESULT"

BASE = {"image_id": "hero", "operation": "metadata", "target_format": "webp", "width": 800, "height": 600, "quality": 85}


def make_registry(*image_ids):
    assets = []
    for image_id in (image_ids or ("hero", "logo")):
        created = create_image_asset({"image_id": image_id, "name": "N", "description": "", "format": "png", "width": 10, "height": 10})
        assert created.ok, created.failures
        assets.append(created.asset)
    registry = create_image_asset_registry(assets)
    assert registry.ok, registry.failures
    return registry.registry


def make_request(**over):
    data = dict(BASE)
    data.update(over)
    created = create_image_operation_request(data)
    assert created.ok, created.failures
    return created.request


def good():
    return make_request()


def bad_dispatch():
    return make_request(operation="resize")


def bad_missing():
    return make_request(image_id="ghost")


def make_batch(*makers):
    return process_image_operations([m() for m in makers], make_registry())


class FakeResult:
    """Stand-in pipeline result; counts every access except `ok`."""

    def __init__(self, ok):
        self.ok = ok
        self.touched = []

    def codes(self):
        self.touched.append("codes")
        return ["FAKE"]

    def to_dict(self):
        self.touched.append("to_dict")
        return {}

    def __getattr__(self, name):
        self.touched.append(name)
        raise AttributeError(name)


def batch_of_fakes(*oks):
    fakes = [FakeResult(ok) for ok in oks]
    reqs = [make_request() for _ in fakes]
    with mock.patch.object(b, "process_image_operation", side_effect=fakes):
        batch = process_image_operations(reqs, make_registry())
    for fake in fakes:
        del fake.touched[:]
    return batch, fakes


class TestValidBatches(unittest.TestCase):
    def test_01_empty_valid_batch(self):
        for empty in ([], ()):
            with self.subTest(kind=type(empty).__name__):
                summary = create_image_operation_batch_summary(process_image_operations(empty, make_registry()))
                self.assertIs(type(summary), ImageOperationBatchSummary)
                self.assertEqual((summary.total, summary.successful, summary.failed), (0, 0, 0))
                self.assertIs(summary.success, True)
                self.assertEqual(summary.codes(), [])
                self.assertEqual(summary.to_dict(), {"total": 0, "successful": 0, "failed": 0, "success": True, "codes": []})

    def test_02_all_success_batch(self):
        summary = create_image_operation_batch_summary(make_batch(good, good, good))
        self.assertEqual((summary.total, summary.successful, summary.failed), (3, 3, 0))
        self.assertIs(summary.success, True)
        self.assertEqual(summary.codes(), [])

    def test_03_single_success(self):
        summary = create_image_operation_batch_summary(make_batch(good))
        self.assertEqual((summary.total, summary.successful, summary.failed, summary.success), (1, 1, 0, True))

    def test_04_all_failure_batch(self):
        summary = create_image_operation_batch_summary(make_batch(bad_dispatch, bad_missing, bad_dispatch, bad_missing))
        self.assertEqual((summary.total, summary.successful, summary.failed), (4, 0, 4))
        self.assertIs(summary.success, False)
        self.assertEqual(summary.codes(), [])

    def test_05_single_failure(self):
        summary = create_image_operation_batch_summary(make_batch(bad_dispatch))
        self.assertEqual((summary.total, summary.successful, summary.failed, summary.success), (1, 0, 1, False))

    def test_06_mixed_batch_exact_counts(self):
        summary = create_image_operation_batch_summary(make_batch(good, bad_dispatch, good, bad_missing, good))
        self.assertEqual((summary.total, summary.successful, summary.failed), (5, 3, 2))
        self.assertIs(summary.success, False)
        self.assertEqual(summary.codes(), [])

    def test_07_one_failure_among_many_successes_is_not_a_success(self):
        summary = create_image_operation_batch_summary(make_batch(good, good, good, good, bad_missing))
        self.assertEqual((summary.total, summary.successful, summary.failed, summary.success), (5, 4, 1, False))

    def test_08_counts_follow_the_results_not_their_order(self):
        a = create_image_operation_batch_summary(make_batch(good, bad_dispatch, good))
        c = create_image_operation_batch_summary(make_batch(bad_dispatch, good, good))
        self.assertEqual(a, c)

    def test_09_types_are_exact(self):
        summary = create_image_operation_batch_summary(make_batch(good, bad_dispatch))
        for value in (summary.total, summary.successful, summary.failed):
            self.assertIs(type(value), int)
        self.assertIs(type(summary.success), bool)
        self.assertIs(type(summary.codes()), list)

    def test_10_total_equals_successful_plus_failed(self):
        for makers in ((), (good,), (bad_dispatch,), (good, bad_missing), (good, good, bad_dispatch, bad_missing)):
            with self.subTest(n=len(makers)):
                summary = create_image_operation_batch_summary(make_batch(*makers))
                self.assertEqual(summary.total, summary.successful + summary.failed)
                self.assertEqual(summary.total, len(makers))
                self.assertIs(summary.success, summary.failed == 0)


class TestExactOkCounting(unittest.TestCase):
    def test_20_only_ok_exactly_true_counts_as_successful(self):
        batch, _fakes = batch_of_fakes(True, 1, "yes", None, False, 0, True, [1])
        summary = create_image_operation_batch_summary(batch)
        self.assertEqual((summary.total, summary.successful, summary.failed), (8, 2, 6))
        self.assertIs(summary.success, False)

    def test_21_truthy_but_not_true_is_a_failure(self):
        batch, _fakes = batch_of_fakes(1, "True")
        summary = create_image_operation_batch_summary(batch)
        self.assertEqual((summary.total, summary.successful, summary.failed, summary.success), (2, 0, 2, False))

    def test_22_only_ok_is_read_from_each_result(self):
        batch, fakes = batch_of_fakes(True, False, True)
        summary = create_image_operation_batch_summary(batch)
        self.assertEqual((summary.total, summary.successful, summary.failed), (3, 2, 1))
        for fake in fakes:
            self.assertEqual(fake.touched, [])      # no codes(), no to_dict(), no other attribute

    def test_23_summary_does_not_use_batch_failures_or_batch_ok(self):
        batch = make_batch(good, bad_dispatch)
        with mock.patch.object(ImageOperationBatchResult, "failures", new_callable=mock.PropertyMock, side_effect=AssertionError("failures read")), \
                mock.patch.object(ImageOperationBatchResult, "ok", new_callable=mock.PropertyMock, side_effect=AssertionError("ok read")), \
                mock.patch.object(ImageOperationBatchResult, "codes", side_effect=AssertionError("codes read")), \
                mock.patch.object(ImageOperationBatchResult, "to_dict", side_effect=AssertionError("to_dict read")):
            summary = create_image_operation_batch_summary(batch)
        self.assertEqual((summary.total, summary.successful, summary.failed), (2, 1, 1))


class TestInvalidInput(unittest.TestCase):
    def invalid_inputs(self):
        batch = make_batch(good)
        pipeline_result = process_image_operation(good(), make_registry())
        return [None, 0, 1, True, "", "batch", b"x", [], (), {}, set(), object(), batch.to_dict(), list(batch.results), batch.results,
                batch.results[0], pipeline_result, make_request(), make_registry(), ImageOperationBatchResult, FakeResult(True),
                create_image_operation_batch_summary(batch)]

    def test_30_invalid_input_exact_shape(self):
        for value in self.invalid_inputs():
            with self.subTest(value=type(value).__name__):
                summary = create_image_operation_batch_summary(value)
                self.assertIs(type(summary), ImageOperationBatchSummary)
                self.assertIs(summary.success, False)
                self.assertEqual((summary.total, summary.successful, summary.failed), (0, 0, 0))

    def test_31_invalid_input_exact_code(self):
        for value in self.invalid_inputs():
            with self.subTest(value=type(value).__name__):
                summary = create_image_operation_batch_summary(value)
                self.assertEqual(summary.codes(), [INVALID])
                self.assertEqual(summary.to_dict(), {"total": 0, "successful": 0, "failed": 0, "success": False, "codes": [INVALID]})

    def test_32_the_only_code_is_the_summary_level_code(self):
        self.assertEqual(s.CODE_INVALID_RESULT, INVALID)
        codes = {v for k, v in vars(s).items() if isinstance(v, str) and v.startswith("IMAGE_OPERATION_")}
        self.assertEqual(codes, {INVALID})
        for makers in ((), (good,), (bad_dispatch,), (good, bad_missing)):
            self.assertEqual(create_image_operation_batch_summary(make_batch(*makers)).codes(), [])

    def test_33_batch_result_with_invalid_batch_input_is_still_a_valid_summary_input(self):
        invalid_batch = process_image_operations(None, make_registry())      # an ImageOperationBatchResult with ok=False and no results
        summary = create_image_operation_batch_summary(invalid_batch)
        self.assertEqual((summary.total, summary.successful, summary.failed, summary.success, summary.codes()), (0, 0, 0, True, []))

    def test_34_batch_result_look_alike_is_rejected(self):
        class Fake:
            results = ()
            ok = True
            failures = ()

        self.assertEqual(create_image_operation_batch_summary(Fake()).codes(), [INVALID])
        mocked = mock.Mock(spec=ImageOperationBatchResult)
        mocked.results = ()
        self.assertEqual(create_image_operation_batch_summary(mocked).codes(), [INVALID])

    def test_35_never_raises(self):
        class Hostile:
            def __getattr__(self, name):
                raise RuntimeError(name)

            def __eq__(self, other):
                raise RuntimeError("eq")

        for value in (Hostile(), float("nan"), 10 ** 100, lambda: None, type):
            create_image_operation_batch_summary(value)


class TestNoMutationAndDeterminism(unittest.TestCase):
    def snapshot(self, batch):
        return (batch.results, tuple(id(r) for r in batch.results), batch.to_dict(), hash(batch), batch.codes(), batch.failures,
                [r.to_dict() for r in batch.results], [hash(r) for r in batch.results], [r.request for r in batch.results])

    def test_40_batch_result_and_contained_results_are_not_mutated(self):
        batch = make_batch(good, bad_dispatch, good, bad_missing)
        before = self.snapshot(batch)
        create_image_operation_batch_summary(batch)
        after = self.snapshot(batch)
        self.assertEqual(before, after)
        for x, y in zip(before[0], after[0]):
            self.assertIs(x, y)
        self.assertIs(batch.results, batch.results)

    def test_41_empty_batch_is_not_mutated(self):
        batch = make_batch()
        before = self.snapshot(batch)
        create_image_operation_batch_summary(batch)
        self.assertEqual(before, self.snapshot(batch))

    def test_42_summary_does_not_retain_the_batch(self):
        batch = make_batch(good)
        summary = create_image_operation_batch_summary(batch)
        for name in s.ImageOperationBatchSummary.__slots__:
            self.assertNotIn(type(getattr(summary, name)).__name__, ("ImageOperationBatchResult", "ImageOperationPipelineResult"))
        self.assertFalse(hasattr(summary, "batch_result"))
        self.assertFalse(hasattr(summary, "results"))

    def test_43_deterministic_repeated_calls(self):
        batch = make_batch(good, bad_dispatch, good)
        results = [create_image_operation_batch_summary(batch) for _ in range(5)]
        self.assertEqual(len({hash(r) for r in results}), 1)
        self.assertEqual(len({repr(r) for r in results}), 1)
        for r in results[1:]:
            self.assertEqual(r, results[0])
            self.assertEqual(r.to_dict(), results[0].to_dict())
            self.assertIsNot(r, results[0])      # a new summary each call, no cache

    def test_44_equal_batches_built_separately_give_equal_summaries(self):
        a = create_image_operation_batch_summary(make_batch(good, bad_missing))
        c = create_image_operation_batch_summary(make_batch(good, bad_missing))
        self.assertEqual(a, c)
        self.assertEqual(hash(a), hash(c))

    def test_45_no_module_level_state_is_changed(self):
        before = {k: v for k, v in vars(s).items() if not k.startswith("__")}
        create_image_operation_batch_summary(make_batch(good, bad_dispatch))
        create_image_operation_batch_summary(None)
        after = {k: v for k, v in vars(s).items() if not k.startswith("__")}
        self.assertEqual(before, after)

    def test_46_invalid_input_is_not_mutated(self):
        data = {"results": [1, 2]}
        items = [good()]
        create_image_operation_batch_summary(data)
        create_image_operation_batch_summary(items)
        self.assertEqual(data, {"results": [1, 2]})
        self.assertEqual(items, [good()])


class TestResultModel(unittest.TestCase):
    def setUp(self):
        self.empty = create_image_operation_batch_summary(make_batch())
        self.ok = create_image_operation_batch_summary(make_batch(good, good))
        self.mixed = create_image_operation_batch_summary(make_batch(good, bad_dispatch))
        self.failed = create_image_operation_batch_summary(make_batch(bad_dispatch, bad_missing))
        self.invalid = create_image_operation_batch_summary(None)

    def all(self):
        return (self.empty, self.ok, self.mixed, self.failed, self.invalid)

    def test_50_equality_and_hash(self):
        self.assertEqual(self.ok, create_image_operation_batch_summary(make_batch(good, good)))
        self.assertEqual(hash(self.ok), hash(create_image_operation_batch_summary(make_batch(good, good))))
        self.assertEqual(self.invalid, create_image_operation_batch_summary("other invalid"))
        self.assertEqual(hash(self.invalid), hash(create_image_operation_batch_summary(1)))
        self.assertEqual(len(set(self.all())), 5)
        for i, left in enumerate(self.all()):
            for j, right in enumerate(self.all()):
                self.assertEqual(left == right, i == j)
        self.assertEqual(len({self.ok, create_image_operation_batch_summary(make_batch(good, good)), self.mixed}), 2)

    def test_51_equality_is_exact_type_only(self):
        self.assertNotEqual(self.ok, self.ok.to_dict())
        self.assertNotEqual(self.ok, None)
        self.assertNotEqual(self.ok, (2, 2, 0, True, ()))
        self.assertNotEqual(self.empty, self.invalid)      # same counts, different success and code

    def test_52_fresh_to_dict(self):
        for summary in self.all():
            first = summary.to_dict()
            self.assertIsNot(first, summary.to_dict())
            self.assertIsNot(first["codes"], summary.to_dict()["codes"])
            first["total"] = 99
            first["success"] = None
            first["codes"].append("X")
            first["extra"] = 1
            second = summary.to_dict()
            self.assertEqual(second, {"total": summary.total, "successful": summary.successful, "failed": summary.failed,
                                      "success": summary.success, "codes": summary.codes()})
            self.assertEqual(list(second), ["total", "successful", "failed", "success", "codes"])

    def test_53_fresh_codes(self):
        first = self.invalid.codes()
        self.assertIsNot(first, self.invalid.codes())
        first.append("X")
        first.clear()
        self.assertEqual(self.invalid.codes(), [INVALID])
        valid = self.ok.codes()
        valid.append("X")
        self.assertEqual(self.ok.codes(), [])

    def test_54_immutable(self):
        for summary in self.all():
            for name in ("total", "successful", "failed", "success", "codes", "extra", "_total"):
                with self.subTest(name=name):
                    with self.assertRaises(AttributeError):
                        setattr(summary, name, 1)
                    with self.assertRaises(AttributeError):
                        delattr(summary, name)
            self.assertFalse(hasattr(summary, "__dict__"))

    def test_55_no_direct_construction_and_no_subclassing(self):
        with self.assertRaises(TypeError):
            ImageOperationBatchSummary()
        with self.assertRaises(TypeError):
            ImageOperationBatchSummary(object(), 1, 1, 0, True, ())
        with self.assertRaises(TypeError):
            ImageOperationBatchSummary(None, 0, 0, 0, False, ())
        with self.assertRaises(TypeError):
            type("Sub", (ImageOperationBatchSummary,), {})

    def test_56_copy_and_deepcopy_return_the_same_object(self):
        for summary in self.all():
            self.assertIs(copy.copy(summary), summary)
            self.assertIs(copy.deepcopy(summary), summary)
            self.assertIs(copy.deepcopy([summary])[0], summary)
            self.assertIs(copy.deepcopy({"k": summary})["k"], summary)

    def test_57_pickle_refused(self):
        for summary in self.all():
            for proto in range(0, pickle.HIGHEST_PROTOCOL + 1):
                with self.subTest(proto=proto):
                    with self.assertRaises(TypeError):
                        pickle.dumps(summary, protocol=proto)

    def test_58_pickle_behaviour_matches_the_batch_result(self):
        batch = make_batch(good)
        with self.assertRaises(TypeError):
            pickle.dumps(batch)
        with self.assertRaises(TypeError):
            pickle.dumps(create_image_operation_batch_summary(batch))

    def test_59_members_are_exactly_the_required_ones(self):
        public = sorted(n for n in dir(ImageOperationBatchSummary) if not n.startswith("_"))
        self.assertEqual(public, ["codes", "failed", "success", "successful", "to_dict", "total"])
        self.assertEqual(sorted(s.ImageOperationBatchSummary.__slots__), ["_codes", "_failed", "_success", "_successful", "_total"])

    def test_60_repr(self):
        self.assertEqual(repr(self.ok), "ImageOperationBatchSummary(total=2, successful=2, failed=0, success=True, codes=[])")
        self.assertEqual(repr(self.mixed), "ImageOperationBatchSummary(total=2, successful=1, failed=1, success=False, codes=[])")
        self.assertEqual(repr(self.invalid), "ImageOperationBatchSummary(total=0, successful=0, failed=0, success=False, codes=['%s'])" % INVALID)


class TestBoundaries(unittest.TestCase):
    def test_70_no_filesystem_access(self):
        def refuse(*a, **k):
            raise AssertionError("filesystem access attempted")

        batches = [make_batch(), make_batch(good), make_batch(good, bad_dispatch, bad_missing)]
        with mock.patch.object(builtins, "open", refuse), mock.patch("os.listdir", refuse), mock.patch("os.stat", refuse), \
                mock.patch("os.scandir", refuse), mock.patch("os.walk", refuse), mock.patch("os.path.exists", refuse), \
                mock.patch("os.path.isfile", refuse), mock.patch("io.open", refuse):
            for batch in batches:
                create_image_operation_batch_summary(batch)
            self.assertEqual(create_image_operation_batch_summary(None).codes(), [INVALID])

    def test_71_module_imports_only_the_batch_result_and_does_no_io(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertTrue(all(isinstance(n, ast.ImportFrom) and n.level == 1 for n in imports))
        self.assertEqual([(n.module, sorted(a.name for a in n.names)) for n in imports],
                         [("image_operation_batch", ["ImageOperationBatchResult"])])
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"open", "os", "io", "subprocess", "socket", "random", "time", "pathlib", "threading", "asyncio", "concurrent",
                                  "multiprocessing", "sched", "process_image_operations", "process_image_operation", "ImageAssetRegistry",
                                  "ImageOperationRequest", "ImageOperationPipelineResult", "bytes", "bytearray", "memoryview", "Image", "PIL", "cv2"})
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertFalse(attrs & {"read", "write", "resize", "convert", "crop", "decode", "sleep", "failures", "request", "plan", "image_id",
                                  "operation", "target_format", "width", "height", "quality"})
        mutable = [n for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.value, (ast.List, ast.Dict, ast.Set))]
        self.assertEqual(mutable, [])

    def test_72_only_the_summary_level_code_is_defined(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        literals = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and "IMAGE_OPERATION" in n.value
                    and n.value not in (INVALID,)]
        for text in literals:      # only prose in the docstring may mention other names
            self.assertGreater(len(text), 60, text)

    def test_73_earlier_modules_are_unaware_of_the_summary(self):
        for name in ("image_asset.py", "image_asset_registry.py", "image_operation_request.py", "image_operation_validator.py",
                     "image_operation_plan.py", "image_operation_executor.py", "image_operation_output.py",
                     "image_operation_output_validator.py", "image_operation_metadata_executor.py", "image_operation_dispatcher.py",
                     "image_operation_pipeline.py", "image_operation_batch.py"):
            with open(os.path.join(PY_ROOT, "multimedia", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("image_operation_batch_summary", "create_image_operation_batch_summary", "ImageOperationBatchSummary"):
                self.assertNotIn(token, text, name)

    def test_74_not_wired_into_the_runtime(self):
        for folder in ("core", "planning", "agent", "game_creation"):
            for root, _dirs, files in os.walk(os.path.join(PY_ROOT, folder)):
                for f in files:
                    if f.endswith(".py"):
                        with open(os.path.join(root, f), encoding="utf-8") as fh:
                            text = fh.read()
                        self.assertNotIn("image_operation_batch_summary", text, os.path.join(root, f))
        with open(os.path.join(PY_ROOT, "multimedia", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_75_multimedia_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "multimedia")) if f != "__pycache__"),
                         ["__init__.py", "audio_asset.py", "audio_asset_registry.py", "audio_operation_batch.py", "audio_operation_batch_summary.py", "audio_operation_dispatcher.py", "audio_operation_executor.py", "audio_operation_metadata_executor.py", "audio_operation_output.py", "audio_operation_output_validator.py", "audio_operation_pipeline.py", "audio_operation_plan.py", "audio_operation_request.py", "audio_operation_validator.py", "image_asset.py", "image_asset_registry.py", "image_operation_batch.py",
                          "image_operation_batch_summary.py", "image_operation_dispatcher.py", "image_operation_executor.py",
                          "image_operation_metadata_executor.py", "image_operation_output.py", "image_operation_output_validator.py",
                          "image_operation_pipeline.py", "image_operation_plan.py", "image_operation_request.py",
                          "image_operation_validator.py"])

    def test_76_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("ImageOperationBatchSummary", "create_image_operation_batch_summary", "ImageOperationBatchResult", INVALID,
                       "total", "successful", "failed", "success", "codes()", "to_dict()", "exactly True", "does NOT", "Prompt 757",
                       "Prompt 759", "has **not** been started"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
