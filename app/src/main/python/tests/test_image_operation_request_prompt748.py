"""Prompt 748 - Section 8 image operation request foundation (`multimedia.image_operation_request`)."""
import ast
import copy
import hashlib
import json
import os
import pickle
import unittest

from multimedia import image_operation_request as iop
from multimedia.image_operation_request import ImageOperationRequest, ImageOperationRequestResult, create_image_operation_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section8_image_operation_request_prompt748.md")
MODULE = os.path.join(PY_ROOT, "multimedia", "image_operation_request.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
TEXT_FIELDS = ("image_id", "operation", "target_format")
DIMS = ("width", "height")


def valid(**over):
    data = {"image_id": "hero_banner", "operation": "resize", "target_format": "webp", "width": 800, "height": 600, "quality": 85}
    data.update(over)
    return data


def code_for(field):
    return iop._INVALID_CODES[iop.FIELDS.index(field)]


class TestValidCreation(unittest.TestCase):
    def test_1_valid_request_builds_with_every_value_kept(self):
        r = create_image_operation_request(valid())
        self.assertIs(type(r), ImageOperationRequestResult)
        self.assertTrue(r.ok)
        self.assertEqual(r.failures, [])
        self.assertEqual(r.codes(), [])
        q = r.request
        self.assertIs(type(q), ImageOperationRequest)
        self.assertEqual((q.image_id, q.operation, q.target_format, q.width, q.height, q.quality), ("hero_banner", "resize", "webp", 800, 600, 85))

    def test_2_exactly_six_fields_in_fixed_order(self):
        self.assertEqual(iop.FIELDS, ("image_id", "operation", "target_format", "width", "height", "quality"))
        self.assertEqual(list(create_image_operation_request(valid()).request.to_dict()), list(iop.FIELDS))
        self.assertEqual(ImageOperationRequest.__slots__, ("_image_id", "_operation", "_target_format", "_width", "_height", "_quality"))

    def test_3_empty_target_format_is_valid(self):
        q = create_image_operation_request(valid(target_format="")).request
        self.assertEqual(q.target_format, "")
        self.assertEqual(q.to_dict()["target_format"], "")

    def test_4_blank_target_format_is_kept_untouched(self):
        self.assertEqual(create_image_operation_request(valid(target_format="  \n")).request.target_format, "  \n")

    def test_5_operation_is_free_text(self):
        for op in ("resize", "convert", "RESIZE", "totally-new-operation", "a b c", "\u00e9", "x" * 500, "  padded  "):
            with self.subTest(op=op[:12]):
                self.assertEqual(create_image_operation_request(valid(operation=op)).request.operation, op)

    def test_6_exact_value_preservation_no_trim_casefold_or_reorder(self):
        q = create_image_operation_request(valid(image_id=" ID-1 ", operation="  ReSiZe\t", target_format=" PNG ")).request
        self.assertEqual((q.image_id, q.operation, q.target_format), (" ID-1 ", "  ReSiZe\t", " PNG "))
        self.assertEqual(list(q.to_dict()), list(iop.FIELDS))
        shuffled = {k: valid()[k] for k in reversed(iop.FIELDS)}
        self.assertEqual(list(create_image_operation_request(shuffled).request.to_dict()), list(iop.FIELDS))

    def test_7_string_identity_is_preserved(self):
        values = {"image_id": "".join(["img", "_", "1"]), "operation": "".join(["re", "size"]), "target_format": "".join(["p", "ng"])}
        q = create_image_operation_request(valid(**values)).request
        for field in TEXT_FIELDS:
            self.assertIs(getattr(q, field), values[field], field)
            self.assertIs(q.to_dict()[field], values[field], field)

    def test_8_boundary_numbers_are_accepted(self):
        for quality in (1, 2, 99, 100):
            self.assertEqual(create_image_operation_request(valid(quality=quality)).request.quality, quality)
        q = create_image_operation_request(valid(width=1, height=1)).request
        self.assertEqual((q.width, q.height), (1, 1))
        self.assertEqual(create_image_operation_request(valid(width=10 ** 12)).request.width, 10 ** 12)

    def test_9_stored_numbers_are_exact_ints(self):
        q = create_image_operation_request(valid()).request
        for v in (q.width, q.height, q.quality, q.to_dict()["width"], q.to_dict()["height"], q.to_dict()["quality"]):
            self.assertIs(type(v), int)

    def test_10_the_factory_never_changes_the_callers_dict(self):
        data = valid(operation="  x ")
        snapshot = copy.deepcopy(data)
        keys = list(data)
        create_image_operation_request(data)
        self.assertEqual(data, snapshot)
        self.assertEqual(list(data), keys)
        bad = {"image_id": "", "zzz": 1, "width": True}
        snap_bad = dict(bad)
        create_image_operation_request(bad)
        self.assertEqual(bad, snap_bad)

    def test_11_later_edits_to_the_input_do_not_reach_the_request(self):
        data = valid()
        q = create_image_operation_request(data).request
        data["operation"] = "changed"
        data["quality"] = 1
        data["extra"] = 1
        self.assertEqual((q.operation, q.quality), ("resize", 85))
        self.assertEqual(q.to_dict(), valid())


class TestTextFieldValidation(unittest.TestCase):
    def test_12_empty_or_blank_required_strings_are_rejected(self):
        for field in ("image_id", "operation"):
            for bad in ("", " ", "   ", "\n", "\t", " \r\n\t "):
                with self.subTest(field=field, bad=bad):
                    r = create_image_operation_request(valid(**{field: bad}))
                    self.assertFalse(r.ok)
                    self.assertIsNone(r.request)
                    self.assertEqual(r.codes(), [code_for(field)])
                    self.assertEqual(r.failures[0]["field"], field)

    def test_13_every_string_field_rejects_wrong_types(self):
        class Sub(str):
            pass
        bads = [None, 0, 1, True, False, 1.5, b"x", bytearray(b"x"), ["a"], ("a",), {"a": 1}, {"a"}, object(), Sub("x")]
        for field in TEXT_FIELDS:
            for bad in bads:
                with self.subTest(field=field, bad=type(bad).__name__):
                    r = create_image_operation_request(valid(**{field: bad}))
                    self.assertFalse(r.ok)
                    self.assertEqual(r.codes(), [code_for(field)])
                    self.assertEqual(r.failures[0]["field"], field)

    def test_14_a_str_subclass_method_is_never_called(self):
        calls = []

        class Evil(str):
            def strip(self, *a):
                calls.append("strip")
                return "x"

            def __eq__(self, other):
                calls.append("eq")
                return True
            __hash__ = str.__hash__
        for field in TEXT_FIELDS:
            create_image_operation_request(valid(**{field: Evil("x")}))
        self.assertEqual(calls, [])


class TestNumberValidation(unittest.TestCase):
    def test_15_non_positive_width_and_height_are_rejected(self):
        for field in DIMS:
            for bad in (0, -1, -1920, -10 ** 9):
                with self.subTest(field=field, bad=bad):
                    r = create_image_operation_request(valid(**{field: bad}))
                    self.assertFalse(r.ok)
                    self.assertIsNone(r.request)
                    self.assertEqual(r.codes(), [code_for(field)])
                    self.assertEqual(r.failures[0]["field"], field)

    def test_16_bool_is_rejected_for_width_height_and_quality(self):
        for field in DIMS + ("quality",):
            for bad in (True, False):
                with self.subTest(field=field, bad=bad):
                    r = create_image_operation_request(valid(**{field: bad}))
                    self.assertFalse(r.ok)
                    self.assertEqual(r.codes(), [code_for(field)])
        self.assertEqual(create_image_operation_request(valid(width=True, height=True, quality=True)).codes(),
                         [iop.FAILURE_INVALID_WIDTH, iop.FAILURE_INVALID_HEIGHT, iop.FAILURE_INVALID_QUALITY])

    def test_17_quality_below_range_is_rejected(self):
        for bad in (0, -1, -100, -10 ** 9):
            with self.subTest(bad=bad):
                self.assertEqual(create_image_operation_request(valid(quality=bad)).codes(), [iop.FAILURE_INVALID_QUALITY])

    def test_18_quality_above_range_is_rejected(self):
        for bad in (101, 102, 1000, 10 ** 9):
            with self.subTest(bad=bad):
                r = create_image_operation_request(valid(quality=bad))
                self.assertEqual(r.codes(), [iop.FAILURE_INVALID_QUALITY])
                self.assertEqual(r.failures[0]["field"], "quality")

    def test_19_every_non_int_number_type_is_rejected_without_coercion(self):
        class MyInt(int):
            pass
        bads = [None, 1.0, 50.0, 1.5, float("nan"), float("inf"), "50", "1", b"1", [1], (1,), {1}, {"a": 1}, object(), 1 + 0j, MyInt(5)]
        for field in DIMS + ("quality",):
            for bad in bads:
                with self.subTest(field=field, bad=type(bad).__name__ + repr(bad)[:10]):
                    r = create_image_operation_request(valid(**{field: bad}))
                    self.assertFalse(r.ok)
                    self.assertEqual(r.codes(), [code_for(field)])

    def test_20_a_number_object_is_never_compared_or_converted(self):
        calls = []

        class Evil(int):
            def __le__(self, other):
                calls.append("le")
                return False

            def __lt__(self, other):
                calls.append("lt")
                return False

            def __gt__(self, other):
                calls.append("gt")
                return False

            def __index__(self):
                calls.append("index")
                return 5
        create_image_operation_request(valid(width=Evil(5), height=Evil(5), quality=Evil(5)))
        self.assertEqual(calls, [])

    def test_21_numbers_are_validated_independently(self):
        for field, bad in (("width", 0), ("height", "9"), ("quality", 101)):
            r = create_image_operation_request(valid(**{field: bad}))
            self.assertEqual([f["field"] for f in r.failures], [field])


class TestInputShape(unittest.TestCase):
    def test_22_non_dict_input_is_rejected_including_dict_subclasses(self):
        from collections import OrderedDict

        class D(dict):
            pass
        for bad in (None, [], (), "x", 1, True, valid().items(), valid().keys(), D(valid()), OrderedDict(valid()), object()):
            with self.subTest(bad=type(bad).__name__):
                r = create_image_operation_request(bad)
                self.assertEqual(r.codes(), [iop.FAILURE_INVALID_INPUT])
                self.assertIsNone(r.request)
                self.assertFalse(r.ok)
                self.assertIsNone(r.failures[0]["field"])

    def test_23_missing_fields_are_rejected_and_nothing_is_defaulted(self):
        for field in iop.FIELDS:
            with self.subTest(field=field):
                data = valid()
                del data[field]
                r = create_image_operation_request(data)
                self.assertFalse(r.ok)
                self.assertEqual(r.codes(), [iop.FAILURE_MISSING_FIELD])
                self.assertEqual(r.failures[0]["field"], field)
        self.assertEqual(create_image_operation_request({}).codes(), [iop.FAILURE_MISSING_FIELD] * 6)

    def test_24_unexpected_fields_are_rejected_not_ignored_and_sorted(self):
        r = create_image_operation_request(valid(zeta=1, objects=[], Alpha="x"))
        self.assertFalse(r.ok)
        self.assertEqual(r.codes(), [iop.FAILURE_UNEXPECTED_FIELD] * 3)
        self.assertEqual([f["field"] for f in r.failures], ["Alpha", "objects", "zeta"])

    def test_25_non_string_keys_are_rejected(self):
        data = valid()
        data[1] = "x"
        data[None] = "y"
        r = create_image_operation_request(data)
        self.assertEqual(r.codes(), [iop.FAILURE_UNEXPECTED_FIELD])
        self.assertIsNone(r.failures[0]["field"])

    def test_26_str_subclass_keys_are_rejected(self):
        class K(str):
            pass
        data = valid()
        data[K("extra")] = 1
        self.assertEqual(create_image_operation_request(data).codes(), [iop.FAILURE_UNEXPECTED_FIELD])

    def test_27_near_miss_and_foreign_field_names_are_unexpected(self):
        data = valid()
        data["Operation"] = data.pop("operation")
        self.assertEqual(create_image_operation_request(data).codes(), [iop.FAILURE_UNEXPECTED_FIELD, iop.FAILURE_MISSING_FIELD])
        data = valid()
        data["format"] = data.pop("target_format")
        self.assertEqual(create_image_operation_request(data).codes(), [iop.FAILURE_UNEXPECTED_FIELD, iop.FAILURE_MISSING_FIELD])
        self.assertEqual(create_image_operation_request(valid(name="n", description="d")).codes(), [iop.FAILURE_UNEXPECTED_FIELD] * 2)


class TestFailureReporting(unittest.TestCase):
    def test_28_every_problem_is_reported_at_once_in_field_order(self):
        r = create_image_operation_request(valid(image_id="", operation=3, target_format=None, width=True, height=0, quality=101))
        self.assertEqual(r.codes(), list(iop._INVALID_CODES))
        self.assertEqual([f["field"] for f in r.failures], list(iop.FIELDS))

    def test_29_input_then_unexpected_then_fields_ordering(self):
        bad = {"zzz": 1, "image_id": "", "operation": 5, "aaa": 2, "quality": 0}
        self.assertEqual(create_image_operation_request(bad).codes(), [
            iop.FAILURE_UNEXPECTED_FIELD, iop.FAILURE_UNEXPECTED_FIELD, iop.FAILURE_INVALID_IMAGE_ID, iop.FAILURE_INVALID_OPERATION,
            iop.FAILURE_MISSING_FIELD, iop.FAILURE_MISSING_FIELD, iop.FAILURE_MISSING_FIELD, iop.FAILURE_INVALID_QUALITY])

    def test_30_the_factory_never_raises_for_bad_data(self):
        for bad in (None, 1, [], {}, {"x": object()}, valid(operation=object()), {None: 1}, valid(image_id=[1]), valid(width=object()),
                    valid(height=float("nan")), valid(quality=float("nan")), valid(quality=10 ** 40)):
            with self.subTest(bad=repr(bad)[:30]):
                r = create_image_operation_request(bad)
                self.assertFalse(r.ok)
                self.assertIsNone(r.request)
                self.assertTrue(r.failures)
                for f in r.failures:
                    self.assertIn(f["code"], iop.FAILURE_CODES)
                    self.assertEqual(set(f), {"code", "field", "message"})
                    self.assertIs(type(f["message"]), str)

    def test_31_failures_are_deterministic_across_calls(self):
        bad = {"zzz": 1, "image_id": "", "operation": 5, "aaa": 2, "width": 0}
        self.assertEqual(create_image_operation_request(bad).to_dict(), create_image_operation_request(dict(bad)).to_dict())

    def test_32_failure_codes_are_unique_prefixed_and_stable(self):
        self.assertEqual(len(set(iop.FAILURE_CODES)), len(iop.FAILURE_CODES))
        for code in iop.FAILURE_CODES:
            self.assertTrue(code.startswith("IMAGE_OPERATION_REQUEST_"), code)
        self.assertEqual(iop.FAILURE_CODES, (
            "IMAGE_OPERATION_REQUEST_INVALID_INPUT", "IMAGE_OPERATION_REQUEST_MISSING_FIELD", "IMAGE_OPERATION_REQUEST_UNEXPECTED_FIELD",
            "IMAGE_OPERATION_REQUEST_INVALID_IMAGE_ID", "IMAGE_OPERATION_REQUEST_INVALID_OPERATION",
            "IMAGE_OPERATION_REQUEST_INVALID_TARGET_FORMAT", "IMAGE_OPERATION_REQUEST_INVALID_WIDTH",
            "IMAGE_OPERATION_REQUEST_INVALID_HEIGHT", "IMAGE_OPERATION_REQUEST_INVALID_QUALITY"))

    def test_33_result_shape_to_dict_and_fresh_failures(self):
        ok = create_image_operation_request(valid()).to_dict()
        self.assertEqual(set(ok), {"ok", "request", "failures"})
        self.assertEqual((ok["ok"], ok["request"], ok["failures"]), (True, valid(), []))
        r = create_image_operation_request(valid(operation=""))
        bad = r.to_dict()
        self.assertEqual((bad["ok"], bad["request"]), (False, None))
        bad["failures"][0]["code"] = "hacked"
        bad["failures"].append("x")
        self.assertEqual(r.codes(), [iop.FAILURE_INVALID_OPERATION])
        self.assertEqual(len(r.failures), 1)
        self.assertIsNot(r.to_dict()["failures"], r.to_dict()["failures"])
        self.assertIsNot(r.to_dict()["failures"][0], r.to_dict()["failures"][0])

    def test_34_result_ok_codes_and_slots(self):
        self.assertFalse(ImageOperationRequestResult().ok)
        self.assertEqual(ImageOperationRequestResult().codes(), [])
        self.assertTrue(create_image_operation_request(valid()).ok)
        self.assertEqual(sorted(ImageOperationRequestResult.__slots__), ["failures", "request"])


class TestImmutabilityAndDeterminism(unittest.TestCase):
    def test_35_equal_data_gives_equal_objects_and_hashes(self):
        a, b = create_image_operation_request(valid()).request, create_image_operation_request(valid()).request
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertFalse(a != b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(a.to_dict(), b.to_dict())
        self.assertEqual(len({a, b}), 1)
        self.assertEqual({a: 1}[b], 1)

    def test_36_any_differing_field_breaks_equality(self):
        a = create_image_operation_request(valid()).request
        others = {"image_id": "other", "operation": "other", "target_format": "jpg", "width": 1, "height": 1, "quality": 1}
        for f, v in others.items():
            with self.subTest(field=f):
                b = create_image_operation_request(valid(**{f: v})).request
                self.assertNotEqual(a, b)
                self.assertEqual(len({a, b}), 2)

    def test_37_equality_is_exact_type_only(self):
        a = create_image_operation_request(valid()).request
        for other in (valid(), a.to_dict(), None, 1, tuple(valid().values())):
            self.assertNotEqual(a, other)
        self.assertEqual(a.__eq__(valid()), NotImplemented)

    def test_38_hash_is_stable_for_equal_content_built_from_distinct_strings(self):
        a = create_image_operation_request(valid(operation="".join(["re", "size"]))).request
        b = create_image_operation_request(valid()).request
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))

    def test_39_to_dict_is_fresh_and_round_trips(self):
        s = create_image_operation_request(valid()).request
        d = s.to_dict()
        self.assertEqual(d, valid())
        d["operation"] = "hacked"
        d["quality"] = 1
        d["extra"] = 1
        self.assertEqual(s.operation, "resize")
        self.assertEqual(s.quality, 85)
        self.assertIsNot(s.to_dict(), s.to_dict())
        self.assertEqual(s.to_dict(), valid())
        self.assertEqual(create_image_operation_request(s.to_dict()).request, s)
        self.assertEqual(json.loads(json.dumps(s.to_dict())), valid())

    def test_40_properties_are_read_only_and_nothing_can_be_added(self):
        s = create_image_operation_request(valid()).request
        for field in iop.FIELDS:
            for target in (field, "_" + field):
                with self.assertRaises(AttributeError, msg=target):
                    setattr(s, target, "x")
                with self.assertRaises(AttributeError, msg=target):
                    delattr(s, target)
        with self.assertRaises(AttributeError):
            s.extra = 1
        with self.assertRaises(AttributeError):
            object.__setattr__(s, "extra", 1)
        self.assertFalse(hasattr(s, "__dict__"))
        for field in iop.FIELDS:
            self.assertIsInstance(getattr(ImageOperationRequest, field), property)
            self.assertIsNone(getattr(ImageOperationRequest, field).fset)
        self.assertEqual(s.to_dict(), valid())

    def test_41_direct_construction_and_subclassing_are_refused(self):
        with self.assertRaises(TypeError):
            ImageOperationRequest(object(), "a", "b", "", 1, 1, 50)
        with self.assertRaises(TypeError):
            ImageOperationRequest(None, "a", "b", "", 1, 1, 50)
        with self.assertRaises(TypeError):
            ImageOperationRequest("a", "b", "", 1, 1, 50)
        with self.assertRaises(TypeError):
            ImageOperationRequest(**valid())
        with self.assertRaises(TypeError):
            class Sub(ImageOperationRequest):
                pass

    def test_42_copy_and_deepcopy_return_the_same_object(self):
        s = create_image_operation_request(valid()).request
        self.assertIs(copy.copy(s), s)
        self.assertIs(copy.deepcopy(s), s)
        self.assertIs(copy.deepcopy({"k": [s]})["k"][0], s)

    def test_43_pickle_is_refused_for_every_protocol(self):
        s = create_image_operation_request(valid()).request
        for proto in range(0, pickle.HIGHEST_PROTOCOL + 1):
            with self.subTest(protocol=proto):
                with self.assertRaises(TypeError):
                    pickle.dumps(s, protocol=proto)
        with self.assertRaises(TypeError):
            s.__reduce__()
        with self.assertRaises(TypeError):
            s.__reduce_ex__(2)

    def test_44_repr_is_deterministic(self):
        s = create_image_operation_request(valid()).request
        self.assertEqual(repr(s), repr(create_image_operation_request(valid()).request))
        self.assertIn("hero_banner", repr(s))


class TestBoundaries(unittest.TestCase):
    def test_45_module_has_no_imports_calls_or_module_state(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))], [])
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "getattr", "setattr", "globals", "vars"):
            self.assertNotIn(forbidden, calls)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef))
        for name, value in vars(iop).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_46_module_source_names_no_forbidden_dependency(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("os", "sys", "io", "pathlib", "subprocess", "socket", "urllib", "http", "requests", "PIL", "Image", "numpy", "cv2",
                     "sqlite3", "random", "time", "datetime", "anthropic", "openai", "game_creation", "ImageAsset", "ImageAssetRegistry",
                     "core", "agent", "planning"):
            self.assertNotIn(word, names, word)

    def test_47_multimedia_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "multimedia")) if f != "__pycache__"),
                         ["__init__.py", "audio_asset.py", "audio_asset_registry.py", "audio_operation_batch.py", "audio_operation_batch_summary.py", "audio_operation_dispatcher.py", "audio_operation_executor.py", "audio_operation_metadata_executor.py", "audio_operation_output.py", "audio_operation_output_validator.py", "audio_operation_pipeline.py", "audio_operation_plan.py", "audio_operation_request.py", "audio_operation_validator.py", "image_asset.py", "image_asset_registry.py", "image_operation_batch.py", "image_operation_batch_summary.py", "image_operation_dispatcher.py", "image_operation_executor.py", "image_operation_metadata_executor.py", "image_operation_output.py", "image_operation_output_validator.py", "image_operation_pipeline.py", "image_operation_plan.py", "image_operation_request.py", "image_operation_validator.py"])
        with open(os.path.join(PY_ROOT, "multimedia", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_48_earlier_section8_modules_are_unaware_of_the_request(self):
        for name in ("image_asset.py", "image_asset_registry.py"):
            with open(os.path.join(PY_ROOT, "multimedia", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("operation", "Operation", "image_operation_request"):
                self.assertNotIn(token, text, (name, token))

    def test_49_no_production_module_outside_multimedia_references_the_request_or_multimedia(self):
        tokens = ("multimedia", "image_operation_request", "ImageOperationRequest", "create_image_operation_request")
        skip = {"multimedia", "tests", "__pycache__", "data"}
        checked = 0
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if not (folder == PY_ROOT and d in skip) and d != "__pycache__"]
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        text = fh.read()
                    for token in tokens:
                        self.assertNotIn(token, text, os.path.join(folder, name))
                    checked += 1
        self.assertGreater(checked, 100)

    def test_50_section7_core_and_agent_modules_are_untouched_by_this_prompt(self):
        for rel in ("game_creation/game_asset.py", "game_creation/game_asset_registry.py", "core/core.py", "input_system/input_system.py",
                    "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("multimedia", "ImageOperationRequest", "image_operation_request"):
                self.assertNotIn(token, text, (rel, token))

    def test_51_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("ImageOperationRequest", "create_image_operation_request", "target_format", "quality", "IMAGE_OPERATION_REQUEST_",
                       "does NOT", "Prompt 749", "free text", "unexpected"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
