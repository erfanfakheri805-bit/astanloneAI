"""Prompt 759 - Section 8 audio asset contract (`multimedia.audio_asset`)."""
import ast
import copy
import hashlib
import json
import os
import pickle
import unittest

from multimedia import audio_asset as ima
from multimedia.audio_asset import AudioAsset, AudioAssetResult, create_audio_asset

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section8_audio_asset_prompt759.md")
MODULE = os.path.join(PY_ROOT, "multimedia", "audio_asset.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
TEXT_FIELDS = ("audio_id", "name", "description", "format")
NUMS = ("duration_ms", "sample_rate")


def valid(**over):
    data = {"audio_id": "theme_song", "name": "Theme Song", "description": "Main menu theme.", "format": "mp3",
            "duration_ms": 180000, "sample_rate": 44100}
    data.update(over)
    return data


def code_for(field):
    return ima._INVALID_CODES[ima.FIELDS.index(field)]


class TestValidCreation(unittest.TestCase):
    def test_1_valid_input_builds_an_asset_with_every_value_kept(self):
        r = create_audio_asset(valid())
        self.assertIs(type(r), AudioAssetResult)
        self.assertTrue(r.ok)
        self.assertEqual(r.failures, [])
        self.assertEqual(r.codes(), [])
        a = r.asset
        self.assertIs(type(a), AudioAsset)
        self.assertEqual((a.audio_id, a.name, a.description, a.format, a.duration_ms, a.sample_rate),
                         ("theme_song", "Theme Song", "Main menu theme.", "mp3", 180000, 44100))

    def test_2_exactly_six_fields_in_fixed_order(self):
        self.assertEqual(ima.FIELDS, ("audio_id", "name", "description", "format", "duration_ms", "sample_rate"))
        self.assertEqual(list(create_audio_asset(valid()).asset.to_dict()), list(ima.FIELDS))
        self.assertEqual(AudioAsset.__slots__, ("_audio_id", "_name", "_description", "_format", "_duration_ms", "_sample_rate"))

    def test_3_empty_description_is_valid_and_so_is_a_blank_one(self):
        self.assertEqual(create_audio_asset(valid(description="")).asset.description, "")
        self.assertEqual(create_audio_asset(valid(description="  \n")).asset.description, "  \n")

    def test_4_no_trim_no_normalization_values_are_stored_as_given(self):
        a = create_audio_asset(valid(audio_id=" ID-1 ", name="  Mixed Case\t", format=" MP3 ", description=" d ")).asset
        self.assertEqual((a.audio_id, a.name, a.format, a.description), (" ID-1 ", "  Mixed Case\t", " MP3 ", " d "))

    def test_5_any_format_text_and_minimal_dimensions_are_accepted(self):
        self.assertTrue(create_audio_asset(valid(format="not-a-real-format")).ok)
        a = create_audio_asset(valid(duration_ms=1, sample_rate=1)).asset
        self.assertEqual((a.duration_ms, a.sample_rate), (1, 1))
        self.assertEqual(create_audio_asset(valid(duration_ms=10 ** 12)).asset.duration_ms, 10 ** 12)

    def test_6_string_identity_is_preserved(self):
        values = {"audio_id": "".join(["img", "_", "1"]), "name": "".join(["Na", "me"]),
                  "description": "".join(["De", "sc"]), "format": "".join(["p", "ng"])}
        a = create_audio_asset(valid(**values)).asset
        for field in TEXT_FIELDS:
            self.assertIs(getattr(a, field), values[field], field)
            self.assertIs(a.to_dict()[field], values[field], field)

    def test_7_the_factory_never_changes_the_callers_dict(self):
        data = valid(name="  x ")
        snapshot = copy.deepcopy(data)
        keys = list(data)
        create_audio_asset(data)
        self.assertEqual(data, snapshot)
        self.assertEqual(list(data), keys)
        bad = {"audio_id": "", "zzz": 1, "duration_ms": True}
        snap_bad = dict(bad)
        create_audio_asset(bad)
        self.assertEqual(bad, snap_bad)

    def test_8_later_edits_to_the_input_do_not_reach_the_asset(self):
        data = valid()
        a = create_audio_asset(data).asset
        data["name"] = "changed"
        data["duration_ms"] = 5
        data["extra"] = 1
        self.assertEqual((a.name, a.duration_ms), ("Theme Song", 180000))
        self.assertEqual(a.to_dict(), valid())


class TestTextFieldValidation(unittest.TestCase):
    def test_9_blank_required_text_fields_are_rejected(self):
        for field in ("audio_id", "name", "format"):
            for bad in ("", " ", "   ", "\n", "\t", " \r\n\t "):
                with self.subTest(field=field, bad=bad):
                    r = create_audio_asset(valid(**{field: bad}))
                    self.assertFalse(r.ok)
                    self.assertIsNone(r.asset)
                    self.assertEqual(r.codes(), [code_for(field)])
                    self.assertEqual(r.failures[0]["field"], field)

    def test_10_every_text_field_rejects_wrong_types(self):
        class Sub(str):
            pass
        bads = [None, 0, 1, True, False, 1.5, b"x", bytearray(b"x"), ["a"], ("a",), {"a": 1}, {"a"}, object(), Sub("x")]
        for field in TEXT_FIELDS:
            for bad in bads:
                with self.subTest(field=field, bad=type(bad).__name__):
                    r = create_audio_asset(valid(**{field: bad}))
                    self.assertFalse(r.ok)
                    self.assertEqual(r.codes(), [code_for(field)])
                    self.assertEqual(r.failures[0]["field"], field)

    def test_11_a_str_subclass_method_is_never_called(self):
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
            create_audio_asset(valid(**{field: Evil("x")}))
        self.assertEqual(calls, [])


class TestDimensionValidation(unittest.TestCase):
    def test_12_non_positive_dimensions_are_rejected(self):
        for field in NUMS:
            for bad in (0, -1, -180000, -10 ** 9):
                with self.subTest(field=field, bad=bad):
                    r = create_audio_asset(valid(**{field: bad}))
                    self.assertFalse(r.ok)
                    self.assertIsNone(r.asset)
                    self.assertEqual(r.codes(), [code_for(field)])
                    self.assertEqual(r.failures[0]["field"], field)

    def test_13_bool_dimensions_are_rejected_even_though_bool_is_an_int(self):
        for field in NUMS:
            for bad in (True, False):
                with self.subTest(field=field, bad=bad):
                    r = create_audio_asset(valid(**{field: bad}))
                    self.assertEqual(r.codes(), [code_for(field)])
        self.assertEqual(create_audio_asset(valid(duration_ms=True, sample_rate=True)).codes(),
                         [ima.FAILURE_INVALID_DURATION_MS, ima.FAILURE_INVALID_SAMPLE_RATE])

    def test_14_every_non_int_dimension_type_is_rejected_without_coercion(self):
        class MyInt(int):
            pass
        bads = [None, 1.0, 1.5, 100.0, float("nan"), float("inf"), "100", "1", b"1", [1], (1,), {1}, {"a": 1}, object(), 1 + 0j,
                MyInt(5)]
        for field in NUMS:
            for bad in bads:
                with self.subTest(field=field, bad=type(bad).__name__ + repr(bad)[:10]):
                    r = create_audio_asset(valid(**{field: bad}))
                    self.assertFalse(r.ok)
                    self.assertEqual(r.codes(), [code_for(field)])

    def test_15_a_dimension_object_is_never_compared_or_converted(self):
        calls = []

        class Evil(int):
            def __le__(self, other):
                calls.append("le")
                return False

            def __index__(self):
                calls.append("index")
                return 5
        create_audio_asset(valid(duration_ms=Evil(5), sample_rate=Evil(5)))
        self.assertEqual(calls, [])

    def test_16_duration_ms_and_sample_rate_are_validated_independently(self):
        r = create_audio_asset(valid(duration_ms=0))
        self.assertEqual([f["field"] for f in r.failures], ["duration_ms"])
        r = create_audio_asset(valid(sample_rate="9"))
        self.assertEqual([f["field"] for f in r.failures], ["sample_rate"])

    def test_17_a_stored_dimension_is_the_same_int_value_and_exact_int(self):
        a = create_audio_asset(valid(duration_ms=640, sample_rate=480)).asset
        self.assertIs(type(a.duration_ms), int)
        self.assertIs(type(a.sample_rate), int)
        self.assertIs(type(a.to_dict()["duration_ms"]), int)


class TestInputShape(unittest.TestCase):
    def test_18_non_dict_input_is_rejected_including_dict_subclasses(self):
        from collections import OrderedDict

        class D(dict):
            pass
        for bad in (None, [], (), "x", 1, True, valid().items(), valid().keys(), D(valid()), OrderedDict(valid()), object()):
            with self.subTest(bad=type(bad).__name__):
                r = create_audio_asset(bad)
                self.assertEqual(r.codes(), [ima.FAILURE_INVALID_INPUT])
                self.assertIsNone(r.asset)
                self.assertFalse(r.ok)
                self.assertIsNone(r.failures[0]["field"])

    def test_19_missing_fields_are_rejected_and_nothing_is_defaulted(self):
        for field in ima.FIELDS:
            with self.subTest(field=field):
                data = valid()
                del data[field]
                r = create_audio_asset(data)
                self.assertFalse(r.ok)
                self.assertEqual(r.codes(), [ima.FAILURE_MISSING_FIELD])
                self.assertEqual(r.failures[0]["field"], field)
        self.assertEqual(create_audio_asset({}).codes(), [ima.FAILURE_MISSING_FIELD] * 6)

    def test_20_unexpected_fields_are_rejected_not_ignored_and_sorted(self):
        r = create_audio_asset(valid(zeta=1, objects=[], Alpha="x"))
        self.assertFalse(r.ok)
        self.assertEqual(r.codes(), [ima.FAILURE_UNEXPECTED_FIELD] * 3)
        self.assertEqual([f["field"] for f in r.failures], ["Alpha", "objects", "zeta"])

    def test_21_non_string_keys_are_rejected(self):
        data = valid()
        data[1] = "x"
        data[None] = "y"
        r = create_audio_asset(data)
        self.assertEqual(r.codes(), [ima.FAILURE_UNEXPECTED_FIELD])
        self.assertIsNone(r.failures[0]["field"])

    def test_22_str_subclass_keys_are_rejected(self):
        class K(str):
            pass
        data = valid()
        data[K("extra")] = 1
        self.assertEqual(create_audio_asset(data).codes(), [ima.FAILURE_UNEXPECTED_FIELD])

    def test_23_near_miss_field_names_are_unexpected_and_the_real_field_is_missing(self):
        data = valid()
        data["Name"] = data.pop("name")
        self.assertEqual(create_audio_asset(data).codes(), [ima.FAILURE_UNEXPECTED_FIELD, ima.FAILURE_MISSING_FIELD])
        data = valid()
        data["image_duration_ms"] = data.pop("duration_ms")
        self.assertEqual(create_audio_asset(data).codes(), [ima.FAILURE_UNEXPECTED_FIELD, ima.FAILURE_MISSING_FIELD])

    def test_24_other_prompts_field_names_are_unexpected(self):
        r = create_audio_asset(valid(asset_id="a", asset_type="audio"))
        self.assertEqual(r.codes(), [ima.FAILURE_UNEXPECTED_FIELD] * 2)


class TestFailureReporting(unittest.TestCase):
    def test_25_every_problem_is_reported_at_once_in_field_order(self):
        r = create_audio_asset(valid(audio_id="", name=3, description=None, format=" ", duration_ms=True, sample_rate=0))
        self.assertEqual(r.codes(), list(ima._INVALID_CODES))
        self.assertEqual([f["field"] for f in r.failures], list(ima.FIELDS))

    def test_26_input_then_unexpected_then_fields_ordering(self):
        bad = {"zzz": 1, "audio_id": "", "name": 5, "aaa": 2, "duration_ms": -1}
        self.assertEqual(create_audio_asset(bad).codes(),
                         [ima.FAILURE_UNEXPECTED_FIELD, ima.FAILURE_UNEXPECTED_FIELD, ima.FAILURE_INVALID_AUDIO_ID,
                          ima.FAILURE_INVALID_NAME, ima.FAILURE_MISSING_FIELD, ima.FAILURE_MISSING_FIELD,
                          ima.FAILURE_INVALID_DURATION_MS, ima.FAILURE_MISSING_FIELD])

    def test_27_the_factory_never_raises_for_bad_data(self):
        for bad in (None, 1, [], {}, {"x": object()}, valid(name=object()), {None: 1}, valid(audio_id=[1]), valid(duration_ms=object()),
                    valid(sample_rate=float("nan"))):
            with self.subTest(bad=repr(bad)[:30]):
                r = create_audio_asset(bad)
                self.assertFalse(r.ok)
                self.assertIsNone(r.asset)
                self.assertTrue(r.failures)
                for f in r.failures:
                    self.assertIn(f["code"], ima.FAILURE_CODES)
                    self.assertEqual(set(f), {"code", "field", "message"})
                    self.assertIs(type(f["message"]), str)

    def test_28_failures_are_deterministic_across_calls(self):
        bad = {"zzz": 1, "audio_id": "", "name": 5, "aaa": 2, "duration_ms": 0}
        self.assertEqual(create_audio_asset(bad).to_dict(), create_audio_asset(dict(bad)).to_dict())

    def test_29_failure_codes_are_unique_prefixed_and_stable(self):
        self.assertEqual(len(set(ima.FAILURE_CODES)), len(ima.FAILURE_CODES))
        for code in ima.FAILURE_CODES:
            self.assertTrue(code.startswith("AUDIO_ASSET_"), code)
        self.assertEqual(ima.FAILURE_CODES, (
            "AUDIO_ASSET_INVALID_INPUT", "AUDIO_ASSET_UNEXPECTED_FIELD", "AUDIO_ASSET_MISSING_FIELD",
            "AUDIO_ASSET_INVALID_AUDIO_ID", "AUDIO_ASSET_INVALID_NAME", "AUDIO_ASSET_INVALID_DESCRIPTION",
            "AUDIO_ASSET_INVALID_FORMAT", "AUDIO_ASSET_INVALID_DURATION_MS", "AUDIO_ASSET_INVALID_SAMPLE_RATE"))

    def test_30_result_shape_to_dict_and_fresh_failures(self):
        ok = create_audio_asset(valid()).to_dict()
        self.assertEqual(set(ok), {"ok", "asset", "failures"})
        self.assertEqual((ok["ok"], ok["asset"], ok["failures"]), (True, valid(), []))
        r = create_audio_asset(valid(name=""))
        bad = r.to_dict()
        self.assertEqual((bad["ok"], bad["asset"]), (False, None))
        bad["failures"][0]["code"] = "hacked"
        bad["failures"].append("x")
        self.assertEqual(r.codes(), [ima.FAILURE_INVALID_NAME])
        self.assertEqual(len(r.failures), 1)
        self.assertIsNot(r.to_dict()["failures"], r.to_dict()["failures"])
        self.assertIsNot(r.to_dict()["failures"][0], r.to_dict()["failures"][0])

    def test_31_result_ok_and_codes_are_consistent(self):
        self.assertFalse(AudioAssetResult().ok)
        self.assertEqual(AudioAssetResult().codes(), [])
        good = create_audio_asset(valid())
        self.assertTrue(good.ok)
        self.assertEqual(sorted(AudioAssetResult.__slots__), ["asset", "failures"])


class TestDeterminismAndImmutability(unittest.TestCase):
    def test_32_equal_data_gives_equal_objects_and_hashes(self):
        a, b = create_audio_asset(valid()).asset, create_audio_asset(valid()).asset
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertFalse(a != b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(a.to_dict(), b.to_dict())
        self.assertEqual(len({a, b}), 1)
        self.assertEqual({a: 1}[b], 1)

    def test_33_any_differing_field_breaks_equality(self):
        a = create_audio_asset(valid()).asset
        others = {"audio_id": "other", "name": "other", "description": "other", "format": "wav", "duration_ms": 1, "sample_rate": 1}
        for f, v in others.items():
            with self.subTest(field=f):
                b = create_audio_asset(valid(**{f: v})).asset
                self.assertNotEqual(a, b)
                self.assertEqual(len({a, b}), 2)

    def test_34_equality_is_exact_type_only(self):
        a = create_audio_asset(valid()).asset
        self.assertNotEqual(a, valid())
        self.assertNotEqual(a, a.to_dict())
        self.assertNotEqual(a, None)
        self.assertNotEqual(a, 1)
        self.assertNotEqual(a, tuple(valid().values()))
        self.assertEqual(a.__eq__(valid()), NotImplemented)

    def test_35_hash_is_stable_for_equal_content_built_from_distinct_strings(self):
        a = create_audio_asset(valid(name="".join(["Theme", " Song"]))).asset
        b = create_audio_asset(valid()).asset
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))

    def test_36_to_dict_is_fresh_and_round_trips(self):
        s = create_audio_asset(valid()).asset
        d = s.to_dict()
        self.assertEqual(d, valid())
        d["name"] = "hacked"
        d["duration_ms"] = 1
        d["extra"] = 1
        self.assertEqual(s.name, "Theme Song")
        self.assertEqual(s.duration_ms, 180000)
        self.assertIsNot(s.to_dict(), s.to_dict())
        self.assertEqual(s.to_dict(), valid())
        self.assertEqual(create_audio_asset(s.to_dict()).asset, s)
        self.assertEqual(json.loads(json.dumps(s.to_dict())), valid())

    def test_37_attributes_cannot_be_assigned_deleted_or_added(self):
        s = create_audio_asset(valid()).asset
        for field in ima.FIELDS:
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
        self.assertEqual(s.to_dict(), valid())

    def test_38_direct_construction_and_subclassing_are_refused(self):
        with self.assertRaises(TypeError):
            AudioAsset(object(), "a", "b", "", "mp3", 1, 1)
        with self.assertRaises(TypeError):
            AudioAsset(None, "a", "b", "", "mp3", 1, 1)
        with self.assertRaises(TypeError):
            AudioAsset("a", "b", "", "mp3", 1, 1)
        with self.assertRaises(TypeError):
            AudioAsset(**valid())
        with self.assertRaises(TypeError):
            class Sub(AudioAsset):
                pass

    def test_39_copy_and_deepcopy_return_the_same_object(self):
        s = create_audio_asset(valid()).asset
        self.assertIs(copy.copy(s), s)
        self.assertIs(copy.deepcopy(s), s)
        self.assertIs(copy.deepcopy({"k": [s]})["k"][0], s)

    def test_40_pickle_is_refused_for_every_protocol(self):
        s = create_audio_asset(valid()).asset
        for proto in range(0, pickle.HIGHEST_PROTOCOL + 1):
            with self.subTest(protocol=proto):
                with self.assertRaises(TypeError):
                    pickle.dumps(s, protocol=proto)
        with self.assertRaises(TypeError):
            s.__reduce__()
        with self.assertRaises(TypeError):
            s.__reduce_ex__(2)

    def test_41_repr_is_deterministic(self):
        s = create_audio_asset(valid()).asset
        self.assertEqual(repr(s), repr(create_audio_asset(valid()).asset))
        self.assertIn("theme_song", repr(s))


class TestBoundaries(unittest.TestCase):
    def test_42_module_has_no_imports_calls_or_module_state(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))], [])
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "getattr", "setattr", "globals", "vars"):
            self.assertNotIn(forbidden, calls)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef))
        for name, value in vars(ima).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_43_module_source_has_no_forbidden_dependency_words(self):
        with open(MODULE, encoding="utf-8") as fh:
            code = "\n".join(line for line in fh.read().splitlines() if not line.lstrip().startswith("#"))
        tree = ast.parse(code)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("os", "sys", "io", "pathlib", "subprocess", "socket", "urllib", "http", "requests", "PIL", "wave", "pydub", "soundfile", "pyaudio", "numpy",
                     "cv2", "sqlite3", "random", "time", "datetime", "anthropic", "openai", "game_creation", "core", "agent", "planning"):
            self.assertNotIn(word, names, word)

    def test_44_multimedia_package_holds_only_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "multimedia")) if f != "__pycache__"),
                         ["__init__.py", "audio_asset.py", "audio_asset_registry.py", "audio_operation_batch.py", "audio_operation_batch_summary.py", "audio_operation_dispatcher.py", "audio_operation_executor.py", "audio_operation_metadata_executor.py", "audio_operation_output.py", "audio_operation_output_validator.py", "audio_operation_pipeline.py", "audio_operation_plan.py", "audio_operation_request.py", "audio_operation_validator.py", "image_asset.py", "image_asset_registry.py", "image_operation_batch.py",
                          "image_operation_batch_summary.py", "image_operation_dispatcher.py", "image_operation_executor.py",
                          "image_operation_metadata_executor.py", "image_operation_output.py", "image_operation_output_validator.py",
                          "image_operation_pipeline.py", "image_operation_plan.py", "image_operation_request.py",
                          "image_operation_validator.py"])      # Prompt 759 adds exactly one module; no audio registry/request/executor
        with open(os.path.join(PY_ROOT, "multimedia", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_45_production_modules_do_not_reference_the_audio_asset(self):
        tokens = ("multimedia", "audio_asset", "AudioAsset", "create_audio_asset")
        skip = {"multimedia", "tests", "__pycache__", "data"}
        checked = 0
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if not (folder == PY_ROOT and d in skip) and d != "__pycache__"]
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                for token in tokens:
                    self.assertNotIn(token, text, path)
                checked += 1
        self.assertGreater(checked, 100)

    def test_46_section7_core_and_agent_modules_are_untouched_by_this_prompt(self):
        for rel in ("game_creation/game_asset.py", "game_creation/game_project.py", "game_creation/game_asset_registry.py",
                    "core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("multimedia", "AudioAsset", "audio_asset"):
                self.assertNotIn(token, text, (rel, token))

    def test_47_the_section7_game_asset_still_has_its_own_separate_shape(self):
        from game_creation.game_asset import GameAsset
        self.assertNotEqual(GameAsset.__slots__, AudioAsset.__slots__)
        self.assertEqual(sorted(ima.FIELDS), sorted(["audio_id", "name", "description", "format", "duration_ms", "sample_rate"]))

    def test_48_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("AudioAsset", "create_audio_asset", "audio_id", "duration_ms", "sample_rate", "AUDIO_ASSET_", "does NOT", "Prompt 760", "has **not** been started", "ImageAsset",
                       "unexpected"):
            self.assertIn(marker, text)


class TestPrompt759Contract(unittest.TestCase):
    def test_60_exact_field_set_and_error_code_set(self):
        self.assertEqual(ima.FIELDS, ("audio_id", "name", "description", "format", "duration_ms", "sample_rate"))
        self.assertEqual(AudioAsset.__slots__, ("_audio_id", "_name", "_description", "_format", "_duration_ms", "_sample_rate"))
        self.assertEqual(sorted(ima.FAILURE_CODES), sorted([
            "AUDIO_ASSET_INVALID_INPUT", "AUDIO_ASSET_MISSING_FIELD", "AUDIO_ASSET_UNEXPECTED_FIELD", "AUDIO_ASSET_INVALID_AUDIO_ID",
            "AUDIO_ASSET_INVALID_NAME", "AUDIO_ASSET_INVALID_DESCRIPTION", "AUDIO_ASSET_INVALID_FORMAT",
            "AUDIO_ASSET_INVALID_DURATION_MS", "AUDIO_ASSET_INVALID_SAMPLE_RATE"]))
        defined = {v for k, v in vars(ima).items() if isinstance(v, str) and v.startswith("AUDIO_ASSET_")}
        self.assertEqual(defined, set(ima.FAILURE_CODES))
        public = sorted(n for n in dir(AudioAsset) if not n.startswith("_"))
        self.assertEqual(public, ["audio_id", "description", "duration_ms", "format", "name", "sample_rate", "to_dict"])

    def test_61_each_invalid_field_gives_exactly_its_own_code(self):
        expected = {"audio_id": "AUDIO_ASSET_INVALID_AUDIO_ID", "name": "AUDIO_ASSET_INVALID_NAME",
                    "description": "AUDIO_ASSET_INVALID_DESCRIPTION", "format": "AUDIO_ASSET_INVALID_FORMAT",
                    "duration_ms": "AUDIO_ASSET_INVALID_DURATION_MS", "sample_rate": "AUDIO_ASSET_INVALID_SAMPLE_RATE"}
        for field, code in expected.items():
            r = create_audio_asset(valid(**{field: object()}))
            self.assertEqual(r.codes(), [code])
            self.assertEqual(r.failures[0]["field"], field)

    def test_62_invalid_input_missing_and_unexpected_codes(self):
        self.assertEqual(create_audio_asset([]).codes(), ["AUDIO_ASSET_INVALID_INPUT"])
        data = valid()
        del data["sample_rate"]
        self.assertEqual(create_audio_asset(data).codes(), ["AUDIO_ASSET_MISSING_FIELD"])
        self.assertEqual(create_audio_asset(valid(extra=1)).codes(), ["AUDIO_ASSET_UNEXPECTED_FIELD"])
        self.assertEqual(create_audio_asset(valid(width=1)).codes(), ["AUDIO_ASSET_UNEXPECTED_FIELD"])      # image fields are not audio fields

    def test_63_realistic_values_and_boundaries_are_accepted_unchecked(self):
        for duration, rate in ((1, 1), (500, 8000), (180000, 44100), (3600000, 48000), (10 ** 12, 10 ** 9), (7, 12345)):
            with self.subTest(duration=duration, rate=rate):
                a = create_audio_asset(valid(duration_ms=duration, sample_rate=rate)).asset
                self.assertEqual((a.duration_ms, a.sample_rate), (duration, rate))
        self.assertTrue(create_audio_asset(valid(format="not-a-real-format")).ok)

    def test_64_duration_and_sample_rate_report_independently_and_in_order(self):
        r = create_audio_asset(valid(duration_ms=True, sample_rate=False))
        self.assertEqual(r.codes(), ["AUDIO_ASSET_INVALID_DURATION_MS", "AUDIO_ASSET_INVALID_SAMPLE_RATE"])
        r = create_audio_asset(valid(duration_ms=0, sample_rate=44100))
        self.assertEqual([f["field"] for f in r.failures], ["duration_ms"])
        r = create_audio_asset(valid(duration_ms=1.0, sample_rate=-1))
        self.assertEqual([f["field"] for f in r.failures], ["duration_ms", "sample_rate"])

    def test_65_deterministic_repeated_construction(self):
        built = [create_audio_asset(valid()).asset for _ in range(5)]
        self.assertEqual(len({hash(a) for a in built}), 1)
        self.assertEqual(len({repr(a) for a in built}), 1)
        self.assertEqual(len({json.dumps(a.to_dict()) for a in built}), 1)
        self.assertEqual(len(set(built)), 1)
        bad = {"zzz": 1, "audio_id": "", "name": 5, "aaa": 2, "duration_ms": 0}
        self.assertEqual(len({json.dumps(create_audio_asset(dict(bad)).to_dict()) for _ in range(5)}), 1)

    def test_66_audio_asset_is_separate_from_the_image_asset(self):
        from multimedia.image_asset import ImageAsset, create_image_asset
        audio = create_audio_asset(valid()).asset
        image = create_image_asset({"image_id": "a", "name": "N", "description": "", "format": "png", "width": 1, "height": 1}).asset
        self.assertNotEqual(audio, image)
        self.assertNotEqual(image, audio)
        self.assertIsNot(type(audio), ImageAsset)
        self.assertEqual(create_audio_asset(image.to_dict()).codes()[0], "AUDIO_ASSET_UNEXPECTED_FIELD")
        self.assertFalse(create_image_asset(audio.to_dict()).ok)
        self.assertEqual(len({audio, image}), 2)

    def test_67_image_modules_are_unaware_of_audio(self):
        for name in sorted(os.listdir(os.path.join(PY_ROOT, "multimedia"))):
            if name.startswith("image_") and name.endswith(".py"):
                with open(os.path.join(PY_ROOT, "multimedia", name), encoding="utf-8") as fh:
                    text = fh.read()
                for token in ("audio_asset", "AudioAsset", "create_audio_asset", "AUDIO_ASSET"):
                    self.assertNotIn(token, text, name)

    def test_68_pickle_behaviour_matches_the_image_asset(self):
        from multimedia.image_asset import create_image_asset
        image = create_image_asset({"image_id": "a", "name": "N", "description": "", "format": "png", "width": 1, "height": 1}).asset
        audio = create_audio_asset(valid()).asset
        with self.assertRaises(TypeError):
            pickle.dumps(image)
        for proto in range(0, pickle.HIGHEST_PROTOCOL + 1):
            with self.assertRaises(TypeError):
                pickle.dumps(audio, protocol=proto)
        with self.assertRaises(TypeError):
            audio.__reduce_ex__(4)
        self.assertIs(copy.copy(audio), audio)
        self.assertIs(copy.deepcopy(audio), audio)

    def test_69_no_audio_registry_request_or_executor_exists(self):
        names = {n for n in dir(ima) if not n.startswith("_")}
        for word in ("registry", "Registry", "request", "Request", "execute", "Executor", "decode", "play", "Playback"):
            self.assertFalse([n for n in names if word in n], word)


if __name__ == "__main__":
    unittest.main()
