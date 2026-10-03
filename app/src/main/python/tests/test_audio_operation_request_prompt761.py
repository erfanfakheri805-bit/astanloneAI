"""Prompt 761 - Section 8 audio operation request (`multimedia.audio_operation_request`)."""
import ast
import copy
import hashlib
import os
import pickle
import unittest

from multimedia import audio_operation_request as aor
from multimedia.audio_operation_request import AudioOperationRequest, AudioOperationRequestResult, create_audio_operation_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section8_audio_operation_request_prompt761.md")
MODULE = os.path.join(PY_ROOT, "multimedia", "audio_operation_request.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
TEXT_FIELDS = ("audio_id", "operation", "target_format")
POSITIVE = ("duration_ms", "sample_rate")


def valid(**over):
    data = {"audio_id": "intro_theme", "operation": "trim", "target_format": "ogg", "duration_ms": 3500, "sample_rate": 44100, "quality": 80}
    data.update(over)
    return data


def code_for(field):
    return aor._INVALID_CODES[aor.FIELDS.index(field)]


class Sub(str):
    pass


class IntSub(int):
    pass


class DictSub(dict):
    pass


class TestValidConstruction(unittest.TestCase):
    def test_valid_request_builds_with_every_value_kept(self):
        r = create_audio_operation_request(valid())
        self.assertIs(type(r), AudioOperationRequestResult)
        self.assertTrue(r.ok)
        self.assertEqual((r.failures, r.codes()), ([], []))
        q = r.request
        self.assertIs(type(q), AudioOperationRequest)
        self.assertEqual((q.audio_id, q.operation, q.target_format, q.duration_ms, q.sample_rate, q.quality),
                         ("intro_theme", "trim", "ogg", 3500, 44100, 80))

    def test_exactly_six_fields_in_fixed_order(self):
        self.assertEqual(aor.FIELDS, ("audio_id", "operation", "target_format", "duration_ms", "sample_rate", "quality"))
        self.assertEqual(AudioOperationRequest.__slots__, ("_audio_id", "_operation", "_target_format", "_duration_ms", "_sample_rate", "_quality"))
        self.assertEqual(list(create_audio_operation_request(valid()).request.to_dict()), list(aor.FIELDS))

    def test_error_codes_are_exactly_the_specified_nine(self):
        self.assertEqual(set(aor.FAILURE_CODES), {
            "AUDIO_OPERATION_REQUEST_INVALID_INPUT", "AUDIO_OPERATION_REQUEST_MISSING_FIELD", "AUDIO_OPERATION_REQUEST_UNEXPECTED_FIELD",
            "AUDIO_OPERATION_REQUEST_INVALID_AUDIO_ID", "AUDIO_OPERATION_REQUEST_INVALID_OPERATION",
            "AUDIO_OPERATION_REQUEST_INVALID_TARGET_FORMAT", "AUDIO_OPERATION_REQUEST_INVALID_DURATION_MS",
            "AUDIO_OPERATION_REQUEST_INVALID_SAMPLE_RATE", "AUDIO_OPERATION_REQUEST_INVALID_QUALITY"})
        self.assertEqual(len(aor.FAILURE_CODES), 9)

    def test_boundary_numbers_accepted(self):
        for quality in (1, 2, 99, 100):
            self.assertEqual(create_audio_operation_request(valid(quality=quality)).request.quality, quality)
        q = create_audio_operation_request(valid(duration_ms=1, sample_rate=1)).request
        self.assertEqual((q.duration_ms, q.sample_rate), (1, 1))
        self.assertEqual(create_audio_operation_request(valid(duration_ms=10 ** 12)).request.duration_ms, 10 ** 12)

    def test_stored_numbers_are_exact_ints(self):
        q = create_audio_operation_request(valid()).request
        for v in (q.duration_ms, q.sample_rate, q.quality, *(q.to_dict()[k] for k in ("duration_ms", "sample_rate", "quality"))):
            self.assertIs(type(v), int)

    def test_operation_is_free_text(self):
        for op in ("trim", "convert", "TRIM", "brand-new-op", "a b c", "\u00e9", "x" * 500, "  padded  "):
            self.assertEqual(create_audio_operation_request(valid(operation=op)).request.operation, op)


class TestInputShape(unittest.TestCase):
    def test_non_dict_inputs_are_rejected(self):
        for bad in (None, [], (), "x", 1, True, 1.5, b"", set(), object(), DictSub(valid()), [("audio_id", "a")]):
            with self.subTest(bad=type(bad).__name__):
                r = create_audio_operation_request(bad)
                self.assertFalse(r.ok)
                self.assertIsNone(r.request)
                self.assertEqual(r.codes(), ["AUDIO_OPERATION_REQUEST_INVALID_INPUT"])
                self.assertIsNone(r.failures[0]["field"])

    def test_empty_dict_reports_every_field_missing_in_order(self):
        r = create_audio_operation_request({})
        self.assertEqual(r.codes(), ["AUDIO_OPERATION_REQUEST_MISSING_FIELD"] * 6)
        self.assertEqual([f["field"] for f in r.failures], list(aor.FIELDS))

    def test_each_missing_field_is_reported(self):
        for field in aor.FIELDS:
            data = valid()
            del data[field]
            with self.subTest(field=field):
                r = create_audio_operation_request(data)
                self.assertFalse(r.ok)
                self.assertEqual(r.codes(), ["AUDIO_OPERATION_REQUEST_MISSING_FIELD"])
                self.assertEqual(r.failures[0]["field"], field)

    def test_unexpected_fields_are_rejected_sorted(self):
        r = create_audio_operation_request(valid(zeta=1, alpha=2))
        self.assertEqual(r.codes(), ["AUDIO_OPERATION_REQUEST_UNEXPECTED_FIELD"] * 2)
        self.assertEqual([f["field"] for f in r.failures], ["alpha", "zeta"])

    def test_non_str_key_is_unexpected(self):
        for key in (1, None, (1,), b"audio_id"):
            with self.subTest(key=repr(key)):
                r = create_audio_operation_request(valid(**{}) | {key: 1})
                self.assertFalse(r.ok)
                self.assertEqual(r.codes(), ["AUDIO_OPERATION_REQUEST_UNEXPECTED_FIELD"])

    def test_near_miss_and_case_variant_keys_are_unexpected_and_missing(self):
        data = valid()
        data["Audio_ID"] = data.pop("audio_id")
        r = create_audio_operation_request(data)
        self.assertEqual(sorted(r.codes()), ["AUDIO_OPERATION_REQUEST_MISSING_FIELD", "AUDIO_OPERATION_REQUEST_UNEXPECTED_FIELD"])

    def test_old_image_field_names_are_rejected(self):
        r = create_audio_operation_request({"image_id": "a", "operation": "x", "target_format": "", "width": 1, "height": 1, "quality": 5})
        self.assertFalse(r.ok)

    def test_failure_order_is_input_unexpected_then_fields(self):
        r = create_audio_operation_request({"zzz": 1, "audio_id": "", "quality": 0})
        self.assertEqual(r.codes(), [
            "AUDIO_OPERATION_REQUEST_UNEXPECTED_FIELD", "AUDIO_OPERATION_REQUEST_INVALID_AUDIO_ID",
            "AUDIO_OPERATION_REQUEST_MISSING_FIELD", "AUDIO_OPERATION_REQUEST_MISSING_FIELD", "AUDIO_OPERATION_REQUEST_MISSING_FIELD",
            "AUDIO_OPERATION_REQUEST_MISSING_FIELD", "AUDIO_OPERATION_REQUEST_INVALID_QUALITY"])


class TestTextFields(unittest.TestCase):
    def test_empty_audio_id_and_operation_rejected(self):
        for field in ("audio_id", "operation"):
            r = create_audio_operation_request(valid(**{field: ""}))
            self.assertFalse(r.ok)
            self.assertEqual(r.codes(), [code_for(field)])
            self.assertEqual(r.failures[0]["field"], field)

    def test_empty_target_format_is_allowed(self):
        q = create_audio_operation_request(valid(target_format="")).request
        self.assertEqual(q.target_format, "")
        self.assertEqual(q.to_dict()["target_format"], "")

    def test_whitespace_only_values_are_not_empty_and_kept_untouched(self):
        for field in TEXT_FIELDS:
            for text in (" ", "  \n", "\t"):
                with self.subTest(field=field, text=text):
                    r = create_audio_operation_request(valid(**{field: text}))
                    self.assertTrue(r.ok)
                    self.assertEqual(getattr(r.request, field), text)

    def test_every_string_field_rejects_wrong_types(self):
        bads = [None, 0, 1, True, False, 1.5, b"x", bytearray(b"x"), ["a"], ("a",), {"a": 1}, {"a"}, object(), Sub("x"), Sub("")]
        for field in TEXT_FIELDS:
            for bad in bads:
                with self.subTest(field=field, bad=type(bad).__name__):
                    r = create_audio_operation_request(valid(**{field: bad}))
                    self.assertFalse(r.ok)
                    self.assertEqual(r.codes(), [code_for(field)])
                    self.assertEqual(r.failures[0]["field"], field)

    def test_str_subclass_methods_are_never_called(self):
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
            self.assertFalse(create_audio_operation_request(valid(**{field: Evil("x")})).ok)
        self.assertEqual(calls, [])


class TestNumberFields(unittest.TestCase):
    def test_positive_fields_reject_zero_negative(self):
        for field in POSITIVE:
            for bad in (0, -1, -10 ** 9):
                with self.subTest(field=field, bad=bad):
                    r = create_audio_operation_request(valid(**{field: bad}))
                    self.assertEqual(r.codes(), [code_for(field)])
                    self.assertEqual(r.failures[0]["field"], field)

    def test_every_number_field_rejects_bool_and_wrong_types(self):
        bads = [True, False, 1.0, 2.5, float("nan"), float("inf"), "5", "", None, b"5", [5], (5,), {5}, object(), IntSub(5), complex(1, 0)]
        for field in (*POSITIVE, "quality"):
            for bad in bads:
                with self.subTest(field=field, bad=repr(bad)):
                    r = create_audio_operation_request(valid(**{field: bad}))
                    self.assertFalse(r.ok)
                    self.assertEqual(r.codes(), [code_for(field)])

    def test_bool_is_rejected_even_when_value_would_be_in_range(self):
        for field in (*POSITIVE, "quality"):
            self.assertEqual(create_audio_operation_request(valid(**{field: True})).codes(), [code_for(field)])

    def test_quality_range_is_one_through_hundred(self):
        for bad in (0, -1, 101, 1000, 10 ** 9):
            with self.subTest(bad=bad):
                self.assertEqual(create_audio_operation_request(valid(quality=bad)).codes(), ["AUDIO_OPERATION_REQUEST_INVALID_QUALITY"])

    def test_each_invalid_field_gets_its_own_deterministic_code(self):
        expected = {"audio_id": "AUDIO_OPERATION_REQUEST_INVALID_AUDIO_ID", "operation": "AUDIO_OPERATION_REQUEST_INVALID_OPERATION",
                    "target_format": "AUDIO_OPERATION_REQUEST_INVALID_TARGET_FORMAT", "duration_ms": "AUDIO_OPERATION_REQUEST_INVALID_DURATION_MS",
                    "sample_rate": "AUDIO_OPERATION_REQUEST_INVALID_SAMPLE_RATE", "quality": "AUDIO_OPERATION_REQUEST_INVALID_QUALITY"}
        for field, code in expected.items():
            self.assertEqual(code_for(field), code)
            self.assertEqual(create_audio_operation_request(valid(**{field: None})).codes(), [code])

    def test_all_fields_invalid_reports_all_six_in_order(self):
        r = create_audio_operation_request({f: None for f in aor.FIELDS})
        self.assertEqual(r.codes(), [code_for(f) for f in aor.FIELDS])


class TestPreservation(unittest.TestCase):
    def test_exact_values_no_trim_casefold_or_reorder(self):
        q = create_audio_operation_request(valid(audio_id=" ID-1 ", operation="  TrIm\t", target_format=" OGG ")).request
        self.assertEqual((q.audio_id, q.operation, q.target_format), (" ID-1 ", "  TrIm\t", " OGG "))
        shuffled = {k: valid()[k] for k in reversed(aor.FIELDS)}
        self.assertEqual(list(create_audio_operation_request(shuffled).request.to_dict()), list(aor.FIELDS))

    def test_string_identity_is_preserved(self):
        values = {"audio_id": "".join(["aud", "_", "1"]), "operation": "".join(["tr", "im"]), "target_format": "".join(["o", "gg"])}
        q = create_audio_operation_request(valid(**values)).request
        for field in TEXT_FIELDS:
            self.assertIs(getattr(q, field), values[field])
            self.assertIs(q.to_dict()[field], values[field])

    def test_empty_target_format_identity(self):
        e = ""
        self.assertIs(create_audio_operation_request(valid(target_format=e)).request.target_format, e)

    def test_factory_never_mutates_the_callers_dict(self):
        data = valid(operation="  x ")
        snapshot, keys = copy.deepcopy(data), list(data)
        create_audio_operation_request(data)
        self.assertEqual((data, list(data)), (snapshot, keys))
        bad = {"audio_id": "", "zzz": 1, "duration_ms": True}
        snap_bad = dict(bad)
        create_audio_operation_request(bad)
        self.assertEqual(bad, snap_bad)

    def test_later_edits_to_input_do_not_reach_the_request(self):
        data = valid()
        q = create_audio_operation_request(data).request
        data["operation"], data["quality"], data["extra"] = "changed", 1, 1
        self.assertEqual((q.operation, q.quality), ("trim", 80))
        self.assertEqual(q.to_dict(), valid())


class TestImmutability(unittest.TestCase):
    def setUp(self):
        self.q = create_audio_operation_request(valid()).request

    def test_attribute_assignment_and_deletion_raise(self):
        for name in (*aor.FIELDS, "_audio_id", "extra"):
            with self.subTest(name=name):
                with self.assertRaises(AttributeError):
                    setattr(self.q, name, "x")
                with self.assertRaises(AttributeError):
                    delattr(self.q, name)
        self.assertEqual(self.q.to_dict(), valid())

    def test_no_instance_dict(self):
        self.assertFalse(hasattr(self.q, "__dict__"))
        with self.assertRaises(AttributeError):
            self.q.__dict__

    def test_direct_construction_refused(self):
        for args in ((), ("a", "b", "c", 1, 1, 1), (object(), "a", "b", "c", 1, 1, 1), (None, "a", "b", "c", 1, 1, 1)):
            with self.subTest(n=len(args)):
                with self.assertRaises(TypeError):
                    AudioOperationRequest(*args)

    def test_subclassing_refused(self):
        with self.assertRaises(TypeError):
            class Child(AudioOperationRequest):
                pass

    def test_result_class_is_not_the_request(self):
        r = create_audio_operation_request(valid())
        self.assertIsNot(type(r), AudioOperationRequest)
        self.assertIs(r.request, r.request)


class TestEqualityHashAndToDict(unittest.TestCase):
    def test_equal_data_equal_objects_and_hashes(self):
        a = create_audio_operation_request(valid()).request
        b = create_audio_operation_request(valid()).request
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        self.assertEqual({a: 1}[b], 1)

    def test_every_field_difference_breaks_equality(self):
        base = create_audio_operation_request(valid()).request
        changes = {"audio_id": "other", "operation": "fade", "target_format": "mp3", "duration_ms": 1, "sample_rate": 8000, "quality": 1}
        for field, value in changes.items():
            with self.subTest(field=field):
                other = create_audio_operation_request(valid(**{field: value})).request
                self.assertNotEqual(base, other)
                self.assertEqual(len({base, other}), 2)

    def test_no_equality_with_dicts_or_other_types(self):
        q = create_audio_operation_request(valid()).request
        for other in (valid(), None, 1, "x", object(), (q.to_dict(),)):
            self.assertNotEqual(q, other)
            self.assertFalse(q == other)

    def test_case_and_padding_make_different_requests(self):
        a = create_audio_operation_request(valid(audio_id="A")).request
        self.assertNotEqual(a, create_audio_operation_request(valid(audio_id="a")).request)
        self.assertNotEqual(a, create_audio_operation_request(valid(audio_id="A ")).request)

    def test_to_dict_is_fresh_plain_and_isolated(self):
        q = create_audio_operation_request(valid()).request
        d1, d2 = q.to_dict(), q.to_dict()
        self.assertIs(type(d1), dict)
        self.assertEqual(d1, valid())
        self.assertIsNot(d1, d2)
        d1["operation"] = "hacked"
        d1["extra"] = 1
        del d1["quality"]
        self.assertEqual(q.to_dict(), valid())
        self.assertEqual(q.operation, "trim")

    def test_result_to_dict_is_fresh(self):
        r = create_audio_operation_request(valid())
        a, b = r.to_dict(), r.to_dict()
        self.assertEqual(a, {"ok": True, "request": valid(), "failures": []})
        self.assertIsNot(a, b)
        self.assertIsNot(a["request"], b["request"])
        bad = create_audio_operation_request({})
        f1, f2 = bad.to_dict()["failures"], bad.to_dict()["failures"]
        self.assertEqual(f1, f2)
        self.assertIsNot(f1[0], f2[0])
        f1[0]["code"] = "X"
        self.assertNotEqual(bad.failures[0]["code"], "X")


class TestCopyPickleDeterminism(unittest.TestCase):
    def test_copy_and_deepcopy_return_same_object(self):
        q = create_audio_operation_request(valid()).request
        self.assertIs(copy.copy(q), q)
        self.assertIs(copy.deepcopy(q), q)
        self.assertIs(copy.deepcopy({"k": [q]})["k"][0], q)

    def test_pickle_is_refused_for_every_protocol(self):
        q = create_audio_operation_request(valid()).request
        for proto in range(0, pickle.HIGHEST_PROTOCOL + 1):
            with self.subTest(proto=proto):
                with self.assertRaises(TypeError):
                    pickle.dumps(q, protocol=proto)
        with self.assertRaises(TypeError):
            q.__reduce__()
        with self.assertRaises(TypeError):
            q.__reduce_ex__(2)

    def test_repeated_calls_are_deterministic(self):
        data = valid()
        results = [create_audio_operation_request(data) for _ in range(5)]
        self.assertEqual({r.request for r in results}, {results[0].request})
        self.assertEqual(len({repr(r.request) for r in results}), 1)
        bad = [create_audio_operation_request({"audio_id": "", "zzz": 1}) for _ in range(5)]
        self.assertEqual(len({tuple(r.codes()) for r in bad}), 1)
        self.assertEqual(len({str(r.to_dict()) for r in bad}), 1)

    def test_repr_is_deterministic(self):
        q = create_audio_operation_request(valid()).request
        self.assertEqual(repr(q), repr(create_audio_operation_request(valid()).request))
        self.assertIn("intro_theme", repr(q))

    def test_factory_never_raises_for_odd_input(self):
        odd = [None, {}, {1: 2}, {"audio_id": object()}, valid(quality=10 ** 400), valid(duration_ms=-10 ** 400), {None: None}]
        for data in odd:
            create_audio_operation_request(data)


class TestBoundaries(unittest.TestCase):
    def _tree(self):
        with open(MODULE, encoding="utf-8") as fh:
            return ast.parse(fh.read())

    def test_module_has_no_imports_calls_or_module_state(self):
        tree = self._tree()
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))], [])
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "getattr", "setattr", "globals", "vars"):
            self.assertNotIn(forbidden, calls)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef))
        for name, value in vars(aor).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_module_names_no_forbidden_dependency(self):
        tree = self._tree()
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("os", "sys", "io", "pathlib", "subprocess", "socket", "urllib", "http", "requests", "wave", "numpy", "scipy", "pydub",
                     "sqlite3", "random", "time", "datetime", "anthropic", "openai", "game_creation", "AudioAsset", "AudioAssetRegistry",
                     "ImageOperationRequest", "core", "agent", "planning"):
            self.assertNotIn(word, names, word)

    def test_audio_asset_modules_are_unaware_of_the_request(self):
        for name in ("audio_asset.py", "audio_asset_registry.py"):
            with open(os.path.join(PY_ROOT, "multimedia", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("audio_operation_request", "AudioOperationRequest"):
                self.assertNotIn(token, text, (name, token))

    def test_no_production_module_outside_multimedia_references_it(self):
        tokens = ("audio_operation_request", "AudioOperationRequest", "create_audio_operation_request")
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

    def test_multimedia_package_has_only_the_request_added(self):
        names = sorted(f for f in os.listdir(os.path.join(PY_ROOT, "multimedia")) if f != "__pycache__")
        self.assertIn("audio_operation_request.py", names)
        self.assertEqual([n for n in names if n.startswith("audio_")], ["audio_asset.py", "audio_asset_registry.py", "audio_operation_batch.py", "audio_operation_batch_summary.py", "audio_operation_dispatcher.py", "audio_operation_executor.py", "audio_operation_metadata_executor.py", "audio_operation_output.py", "audio_operation_output_validator.py", "audio_operation_pipeline.py", "audio_operation_plan.py", "audio_operation_request.py", "audio_operation_validator.py"])
        self.assertFalse([n for n in names if n.startswith("audio_") and n not in ("audio_asset.py", "audio_asset_registry.py", "audio_operation_batch.py", "audio_operation_batch_summary.py", "audio_operation_dispatcher.py", "audio_operation_executor.py", "audio_operation_metadata_executor.py", "audio_operation_output.py", "audio_operation_output_validator.py", "audio_operation_pipeline.py", "audio_operation_plan.py", "audio_operation_request.py", "audio_operation_validator.py")])
        with open(os.path.join(PY_ROOT, "multimedia", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("AudioOperationRequest", "create_audio_operation_request", "target_format", "quality", "duration_ms", "sample_rate",
                       "AUDIO_OPERATION_REQUEST_", "does NOT", "Prompt 762", "free text", "unexpected"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
