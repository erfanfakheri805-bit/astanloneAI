"""Prompt 743 - Section 7 game structure request (`game_creation.game_structure_request`)."""
import ast
import collections
import copy
import hashlib
import os
import pickle
import subprocess
import sys
import types
import unittest
from unittest import mock

from game_creation import game_project_structure as structure_module
from game_creation import game_structure_request as sr
from game_creation.game_structure_request import GameStructureRequest, GameStructureRequestResult, create_game_structure_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
PKG = os.path.join(PY_ROOT, "game_creation")
DOC = os.path.join(REPO_ROOT, "docs", "section7_game_structure_request_prompt743.md")
SOURCE = os.path.join(PKG, "game_structure_request.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"

FIELDS = ("scenes", "characters", "gameplay_systems", "assets")
P = "GAME_STRUCTURE_REQUEST_"
INVALID_INPUT, UNEXPECTED, MISSING = P + "INVALID_INPUT", P + "UNEXPECTED_FIELD", P + "MISSING_FIELD"
INVALID_COLLECTION, INVALID_ITEM, DUPLICATE = P + "INVALID_COLLECTION", P + "INVALID_ITEM", P + "DUPLICATE_ITEM"


class StrSubclass(str):
    pass


class DictSubclass(dict):
    pass


class ListSubclass(list):
    pass


class TupleSubclass(tuple):
    pass


Point = collections.namedtuple("Point", "a b")


def good(**over):
    d = {"scenes": ["menu", "level1"], "characters": ["hero", "villain"], "gameplay_systems": ["combat", "inventory"], "assets": ["hero.png", "theme.ogg"]}
    d.update(over)
    return d


def empty():
    return {f: [] for f in FIELDS}


def sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


class TestValid(unittest.TestCase):
    def test_01_valid_four_field_request(self):
        data = good()
        result = create_game_structure_request(data)
        self.assertIsInstance(result, GameStructureRequestResult)
        self.assertTrue(result.ok)
        self.assertIsInstance(result.request, GameStructureRequest)
        self.assertEqual(result.failures, [])
        self.assertEqual(result.codes(), [])
        self.assertEqual(result.request.to_dict(), data)
        self.assertEqual(result.to_dict(), {"ok": True, "request": data, "failures": []})

    def test_02_exactly_four_read_only_fields(self):
        r = create_game_structure_request(good()).request
        for f in FIELDS:
            self.assertEqual(getattr(r, f), tuple(good()[f]), f)
        self.assertEqual(sorted(n for n in dir(r) if not n.startswith("_")), sorted(FIELDS + ("to_dict",)))
        self.assertEqual(list(r.to_dict()), list(FIELDS))
        self.assertEqual(sr.FIELDS, FIELDS)

    def test_03_empty_collections_are_valid(self):
        r = create_game_structure_request(empty())
        self.assertTrue(r.ok)
        for f in FIELDS:
            self.assertEqual(getattr(r.request, f), ())
        self.assertEqual(r.request.to_dict(), empty())
        for f in FIELDS:
            only = empty()
            only[f] = ["x"]
            self.assertTrue(create_game_structure_request(only).ok, f)
        self.assertTrue(create_game_structure_request({f: () for f in FIELDS}).ok)

    def test_04_lists_and_tuples_are_both_accepted_and_mixable(self):
        data = {"scenes": ("a", "b"), "characters": ["c"], "gameplay_systems": (), "assets": []}
        r = create_game_structure_request(data)
        self.assertTrue(r.ok)
        self.assertEqual(r.request.to_dict(), {"scenes": ["a", "b"], "characters": ["c"], "gameplay_systems": [], "assets": []})
        self.assertEqual(create_game_structure_request({f: ["a"] for f in FIELDS}), create_game_structure_request({f: ("a",) for f in FIELDS}))

    def test_05_order_is_preserved(self):
        data = good(scenes=["z", "a", "m", "B", "A", "10", "9"], assets=("t3", "t1", "t2"))
        r = create_game_structure_request(data).request
        self.assertEqual(r.scenes, ("z", "a", "m", "B", "A", "10", "9"))
        self.assertEqual(r.assets, ("t3", "t1", "t2"))
        self.assertEqual(r.to_dict()["scenes"], ["z", "a", "m", "B", "A", "10", "9"])
        self.assertNotEqual(create_game_structure_request(good(scenes=["a", "b"])).request, create_game_structure_request(good(scenes=["b", "a"])).request)

    def test_06_collections_are_stored_as_tuples(self):
        r = create_game_structure_request(good(assets=("x",))).request
        for f in FIELDS:
            self.assertIs(type(getattr(r, f)), tuple, f)

    def test_07_no_normalization_trimming_casefolding_or_dedup_of_distinct_items(self):
        odd = [" a ", "a", "A", "\tTab", "Ünïcödé 🎮", "\u00a0x\u00a0", "a b", "a  b", "\u200b"]
        data = good(scenes=list(odd))
        r = create_game_structure_request(data).request
        self.assertEqual(r.scenes, tuple(odd))
        for given, kept in zip(data["scenes"], r.scenes):
            self.assertIs(given, kept)      # the very same string object, never rebuilt

    def test_08_same_item_in_different_collections_is_valid(self):
        self.assertTrue(create_game_structure_request({f: ["shared"] for f in FIELDS}).ok)

    def test_09_dict_key_order_does_not_matter(self):
        data = dict(reversed(list(good().items())))
        self.assertEqual(create_game_structure_request(data), create_game_structure_request(good()))
        self.assertEqual(list(create_game_structure_request(data).request.to_dict()), list(FIELDS))


class TestDuplicates(unittest.TestCase):
    def test_10_duplicate_in_each_field(self):
        for f in FIELDS:
            r = create_game_structure_request(good(**{f: ["a", "b", "a"]}))
            self.assertFalse(r.ok, f)
            self.assertIsNone(r.request)
            self.assertEqual(r.codes(), [DUPLICATE], f)
            self.assertEqual(r.failures[0]["field"], f)
            self.assertIn("item 2", r.failures[0]["message"])

    def test_11_every_later_occurrence_is_reported(self):
        r = create_game_structure_request(good(scenes=["a", "a", "b", "a", "b"]))
        self.assertEqual(r.codes(), [DUPLICATE] * 3)
        self.assertEqual([("item %d " % i) in x["message"] for x, i in zip(r.failures, (1, 3, 4))], [True] * 3)

    def test_12_duplicates_are_exact_only(self):
        for distinct in (["a", "A"], ["a", " a"], ["a", "a "], ["a b", "a  b"], ["é", "e\u0301"], ["a", "a\u200b"]):
            self.assertTrue(create_game_structure_request(good(scenes=distinct)).ok, distinct)

    def test_13_duplicates_in_tuples_too(self):
        self.assertEqual(create_game_structure_request(good(scenes=("a", "a"))).codes(), [DUPLICATE])

    def test_14_duplicate_detection_ignores_invalid_items(self):
        r = create_game_structure_request(good(scenes=["", "", "a", 1, 1, "a"]))
        self.assertEqual(r.codes(), [INVALID_ITEM] * 2 + [INVALID_ITEM] * 2 + [DUPLICATE])

    def test_15_duplicate_never_changes_input(self):
        data = good(scenes=["a", "a"])
        create_game_structure_request(data)
        self.assertEqual(data["scenes"], ["a", "a"])


class TestCollections(unittest.TestCase):
    def test_16_wrong_collection_types(self):
        wrong = (None, "abc", "", 1, 1.5, True, b"ab", {"a"}, frozenset({"a"}), {"a": 1}, object(), iter(["a"]), (x for x in ["a"]),
                 range(3), bytearray(b"a"), types.MappingProxyType({}), collections.deque(["a"]))
        for f in FIELDS:
            for bad in wrong:
                r = create_game_structure_request(good(**{f: bad}))
                self.assertFalse(r.ok, (f, bad))
                self.assertEqual(r.codes(), [INVALID_COLLECTION], (f, bad))
                self.assertEqual(r.failures[0]["field"], f)
                self.assertIn("list or a tuple", r.failures[0]["message"])

    def test_17_list_and_tuple_subclasses_are_rejected(self):
        for f in FIELDS:
            for bad in (ListSubclass(["a"]), TupleSubclass(("a",)), Point("a", "b"), ListSubclass(), TupleSubclass()):
                self.assertEqual(create_game_structure_request(good(**{f: bad})).codes(), [INVALID_COLLECTION], (f, type(bad).__name__))

    def test_18_subclass_hooks_are_never_run(self):
        class Evil(list):
            def __iter__(self):
                raise AssertionError("iterated")

            def __len__(self):
                raise AssertionError("len")
        self.assertEqual(create_game_structure_request(good(scenes=Evil(["a"]))).codes(), [INVALID_COLLECTION])

    def test_19_missing_fields(self):
        for f in FIELDS:
            data = good()
            del data[f]
            r = create_game_structure_request(data)
            self.assertFalse(r.ok, f)
            self.assertEqual(r.codes(), [MISSING])
            self.assertEqual(r.failures[0]["field"], f)
            self.assertIn(f, r.failures[0]["message"])
        r = create_game_structure_request({})
        self.assertEqual(r.codes(), [MISSING] * 4)
        self.assertEqual([x["field"] for x in r.failures], list(FIELDS))

    def test_20_a_none_value_is_not_a_missing_field(self):
        self.assertEqual(create_game_structure_request(good(scenes=None)).codes(), [INVALID_COLLECTION])

    def test_21_unexpected_fields(self):
        r = create_game_structure_request(good(extra=[]))
        self.assertEqual(r.codes(), [UNEXPECTED])
        self.assertEqual(r.failures[0]["field"], "extra")
        r = create_game_structure_request(good(Scenes=[], ASSETS=[], levels=[]))
        self.assertEqual(r.codes(), [UNEXPECTED] * 3)
        self.assertEqual([x["field"] for x in r.failures], ["ASSETS", "Scenes", "levels"])      # sorted by name (plain str ordering)
        self.assertEqual(create_game_structure_request(good(extra=None)).codes(), [UNEXPECTED])
        self.assertEqual(create_game_structure_request(dict(good(), project_id="p")).codes(), [UNEXPECTED])      # a request field, not a structure field

    def test_22_non_str_field_names(self):
        for key in (1, None, b"scenes", ("a",), 1.5):
            data = good()
            data[key] = []
            r = create_game_structure_request(data)
            self.assertEqual(r.codes(), [UNEXPECTED], repr(key))
            self.assertIsNone(r.failures[0]["field"])
        data = good()
        data[StrSubclass("scenes")] = ["dup"]      # equal and same hash as "scenes": replaces the value, key stays an exact str
        self.assertEqual(create_game_structure_request(data).codes(), [])


class TestItems(unittest.TestCase):
    def test_23_wrong_item_types(self):
        wrong = (None, 1, 1.5, True, b"x", ["x"], ("x",), {"x": 1}, {"x"}, object(), StrSubclass("x"), bytearray(b"x"))
        for f in FIELDS:
            for bad in wrong:
                for wrap in (list, tuple):
                    r = create_game_structure_request(good(**{f: wrap(["ok", bad])}))
                    self.assertFalse(r.ok, (f, bad))
                    self.assertEqual(r.codes(), [INVALID_ITEM], (f, bad))
                    self.assertEqual(r.failures[0]["field"], f)
                    self.assertIn("item 1", r.failures[0]["message"])
                    self.assertIn("must be a str", r.failures[0]["message"])

    def test_24_blank_strings(self):
        for f in FIELDS:
            for blank in ("", " ", "   ", "\t", "\n", "\r\n", " \t\n ", "\u00a0", "\u2003"):
                r = create_game_structure_request(good(**{f: ["ok", blank]}))
                self.assertEqual(r.codes(), [INVALID_ITEM], (f, blank))
                self.assertIn("empty or blank", r.failures[0]["message"])

    def test_25_non_blank_strings_with_whitespace_are_valid(self):
        for ok in (" x ", "a b", "\u200b", "\tx"):
            self.assertTrue(create_game_structure_request(good(scenes=[ok])).ok, repr(ok))

    def test_26_str_subclass_methods_are_never_run(self):
        class Evil(str):
            def strip(self, *a):
                raise AssertionError("subclass method run")

            def __eq__(self, other):
                raise AssertionError("subclass method run")
            __hash__ = str.__hash__
        self.assertEqual(create_game_structure_request(good(scenes=[Evil("x"), Evil("x")])).codes(), [INVALID_ITEM] * 2)

    def test_27_every_bad_item_is_reported_in_position_order(self):
        r = create_game_structure_request(good(scenes=["", 5, "a", " ", "a", None]))
        self.assertEqual(r.codes(), [INVALID_ITEM, INVALID_ITEM, INVALID_ITEM, DUPLICATE, INVALID_ITEM])
        self.assertEqual([m for m in (x["message"] for x in r.failures)].__len__(), 5)
        self.assertEqual([next(i for i in range(6) if ("item %d " % i) in x["message"]) for x in r.failures], [0, 1, 3, 4, 5])

    def test_28_item_failure_inside_a_non_collection_is_not_examined(self):
        r = create_game_structure_request(good(scenes="abc"))
        self.assertEqual(r.codes(), [INVALID_COLLECTION])


class TestInvalidInputAndOrdering(unittest.TestCase):
    def test_29_non_dict_input(self):
        for bad in (None, "x", 5, 1.5, True, [], (), set(), object(), good, [("scenes", [])], b"x", iter(good().items()),
                    types.MappingProxyType(good()), create_game_structure_request(good())):
            r = create_game_structure_request(bad)
            self.assertFalse(r.ok, repr(bad))
            self.assertIsNone(r.request)
            self.assertEqual(r.codes(), [INVALID_INPUT])
            self.assertIsNone(r.failures[0]["field"])

    def test_30_dict_subclasses_are_rejected(self):
        for bad in (DictSubclass(good()), collections.OrderedDict(good()), collections.defaultdict(list, good()), collections.Counter()):
            self.assertEqual(create_game_structure_request(bad).codes(), [INVALID_INPUT], type(bad).__name__)

    def test_31_bad_input_never_raises(self):
        class Boom(dict):
            def __iter__(self):
                raise AssertionError("iterated")
        weird = [None, 0, "", (), [], {}, set(), object(), Ellipsis, create_game_structure_request, float("nan"), Boom(),
                 {1: 2}, {None: None}, {"scenes": object()}, {"a": {"b": [1]}}, good(scenes=[float("nan")]), good(scenes=[[["x"]]])]
        for bad in weird:
            try:
                result = create_game_structure_request(bad)
            except Exception as exc:      # pragma: no cover
                self.fail("raised %r for %r" % (exc, bad))
            self.assertIsInstance(result, GameStructureRequestResult)
        with self.assertRaises(TypeError):      # wrong argument COUNT is a Python call error, not bad data
            create_game_structure_request()

    def test_32_deterministic_failure_ordering(self):
        data = {"assets": [1, "a", "a"], "zeta": 1, "scenes": "x", "Alpha": 2, "characters": [""], 7: "x"}
        r = create_game_structure_request(data)
        self.assertEqual(r.codes(), [UNEXPECTED] * 3 + [INVALID_COLLECTION, INVALID_ITEM, MISSING, INVALID_ITEM, DUPLICATE])
        self.assertEqual([x["field"] for x in r.failures], [None, "Alpha", "zeta", "scenes", "characters", "gameplay_systems", "assets", "assets"])
        self.assertEqual(r, create_game_structure_request(dict(data)))
        self.assertEqual(r.to_dict(), create_game_structure_request(dict(reversed(list(data.items())))).to_dict())

    def test_33_field_failures_follow_model_order(self):
        r = create_game_structure_request({"assets": 1, "gameplay_systems": 1, "characters": 1, "scenes": 1})
        self.assertEqual(r.codes(), [INVALID_COLLECTION] * 4)
        self.assertEqual([x["field"] for x in r.failures], list(FIELDS))

    def test_34_codes_are_stable_and_prefixed(self):
        self.assertEqual(sr.FAILURE_CODES, (INVALID_INPUT, UNEXPECTED, MISSING, INVALID_COLLECTION, INVALID_ITEM, DUPLICATE))
        self.assertEqual(len(set(sr.FAILURE_CODES)), 6)
        self.assertTrue(all(c.startswith("GAME_STRUCTURE_REQUEST_") for c in sr.FAILURE_CODES))

    def test_35_same_input_gives_same_result_every_time(self):
        data = good(extra=1, scenes=["a", "a", ""])
        self.assertEqual([create_game_structure_request(data).to_dict() for _ in range(3)], [create_game_structure_request(data).to_dict()] * 3)


class TestMutationProtection(unittest.TestCase):
    def test_36_supplied_input_is_not_mutated(self):
        data = good()
        for payload in (data, dict(data, extra=[]), {k: v for k, v in data.items() if k != "assets"}, dict(data, scenes=["a", "a", ""]),
                        dict(data, characters=("x", "y"))):
            snapshot = {k: (list(v) if type(v) is list else v) for k, v in payload.items()}
            keys = list(payload)
            create_game_structure_request(payload)
            self.assertEqual(list(payload), keys)
            for k, v in snapshot.items():
                self.assertEqual(payload[k], v)
                self.assertIs(type(payload[k]), type(v))

    def test_37_request_is_independent_of_the_supplied_collections(self):
        data = good()
        r = create_game_structure_request(data).request
        data["scenes"].append("added")
        data["characters"][0] = "changed"
        data["assets"].clear()
        data["extra"] = 1
        del data["gameplay_systems"]
        self.assertEqual(r.to_dict(), good())

    def test_38_supplied_strings_are_held_by_identity(self):
        data = good()
        r = create_game_structure_request(data).request
        for f in FIELDS:
            for given, kept in zip(data[f], getattr(r, f)):
                self.assertIs(given, kept)

    def test_39_request_collections_are_tuples_that_cannot_be_changed(self):
        r = create_game_structure_request(good()).request
        with self.assertRaises(AttributeError):
            r.scenes.append("x")
        with self.assertRaises(TypeError):
            r.scenes[0] = "x"
        with self.assertRaises(AttributeError):
            r.assets.extend(["x"])

    def test_40_fresh_to_dict(self):
        r = create_game_structure_request(good())
        d1, d2 = r.request.to_dict(), r.request.to_dict()
        self.assertEqual(d1, d2)
        self.assertIsNot(d1, d2)
        for f in FIELDS:
            self.assertIsNot(d1[f], d2[f])
            self.assertIs(type(d1[f]), list)
        snapshot = r.request.to_dict()
        d1["scenes"].append("mutated")
        d1["assets"].clear()
        d1["extra"] = 1
        del d1["characters"]
        self.assertEqual(r.request.to_dict(), snapshot)
        self.assertEqual(r.request.scenes, ("menu", "level1"))
        t1, t2 = r.to_dict(), r.to_dict()
        self.assertIsNot(t1, t2)
        self.assertIsNot(t1["request"], t2["request"])
        self.assertIsNot(t1["failures"], t2["failures"])
        t1["request"]["scenes"].append("mutated")
        self.assertEqual(r.to_dict()["request"]["scenes"], ["menu", "level1"])

    def test_41_fresh_failures_and_codes(self):
        bad = create_game_structure_request({"scenes": [""]})
        self.assertIsNot(bad.failures, bad.failures)
        self.assertIsNot(bad.failures[0], bad.failures[0])
        self.assertIsNot(bad.codes(), bad.codes())
        snapshot = bad.to_dict()
        bad.failures.append("junk")
        bad.failures[0]["code"] = "x"
        bad.codes().append("x")
        bad.to_dict()["failures"][0]["message"] = "x"
        self.assertEqual(bad.to_dict(), snapshot)
        self.assertIsNone(bad.to_dict()["request"])

    def test_42_to_dict_is_plain_data(self):
        def check(value):
            self.assertIn(type(value), (dict, list, str, bool, type(None)))
            if type(value) is dict:
                for k, v in value.items():
                    self.assertIs(type(k), str)
                    check(v)
            elif type(value) is list:
                for v in value:
                    check(v)
        check(create_game_structure_request(good()).to_dict())
        check(create_game_structure_request({"a": 1, 5: 2, "scenes": ["", "a", "a"]}).to_dict())
        check(create_game_structure_request(None).to_dict())


class TestImmutabilityEqualityAndRefusals(unittest.TestCase):
    def test_43_attributes_are_read_only(self):
        result = create_game_structure_request(good())
        for obj, names in ((result.request, FIELDS + tuple("_" + f for f in FIELDS) + ("extra", "to_dict")),
                           (result, ("ok", "request", "failures", "_request", "_failures", "extra", "codes"))):
            for name in names:
                with self.assertRaises(AttributeError, msg=(type(obj).__name__, name)):
                    setattr(obj, name, "x")
                with self.assertRaises(AttributeError, msg=(type(obj).__name__, name)):
                    delattr(obj, name)
            self.assertFalse(hasattr(obj, "__dict__"))
        self.assertEqual(result.request.to_dict(), good())

    def test_44_deterministic_equality_and_hash(self):
        a, b = create_game_structure_request(good()), create_game_structure_request(good(scenes=("menu", "level1")))
        self.assertIsNot(a.request, b.request)
        self.assertEqual(a.request, b.request)      # list vs tuple input, same contents
        self.assertEqual(hash(a.request), hash(b.request))
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a.request, b.request}), 1)
        for f in FIELDS:
            self.assertNotEqual(a.request, create_game_structure_request(good(**{f: ["other"]})).request, f)
        self.assertNotEqual(create_game_structure_request(good(scenes=["a", "b"])).request, create_game_structure_request(good(scenes=["b", "a"])).request)
        moved = create_game_structure_request({"scenes": ["x"], "characters": [], "gameplay_systems": [], "assets": []}).request
        other = create_game_structure_request({"scenes": [], "characters": ["x"], "gameplay_systems": [], "assets": []}).request
        self.assertNotEqual(moved, other)      # the same item in a different field is a different request
        self.assertNotEqual(a.request, a.request.to_dict())
        self.assertNotEqual(a, a.to_dict())
        self.assertNotEqual(a.request, "x")
        bad1, bad2 = create_game_structure_request(None), create_game_structure_request("x")
        self.assertEqual(bad1, bad2)
        self.assertEqual(hash(bad1), hash(bad2))
        self.assertNotEqual(bad1, a)
        self.assertNotEqual(create_game_structure_request({}), bad1)
        self.assertEqual(create_game_structure_request(empty()), create_game_structure_request({f: () for f in FIELDS}))

    def test_45_direct_construction_is_refused(self):
        values = [("a",)] * 4
        for token in (object(), None, True):
            with self.assertRaises(TypeError):
                GameStructureRequest(token, *values)
            with self.assertRaises(TypeError):
                GameStructureRequestResult(token, None, [])
        with self.assertRaises(TypeError):
            GameStructureRequest(*values)
        with self.assertRaises(TypeError):
            GameStructureRequest()
        with self.assertRaises(TypeError):
            GameStructureRequestResult()

    def test_46_subclassing_is_refused(self):
        for base in (GameStructureRequest, GameStructureRequestResult):
            with self.assertRaises(TypeError):
                type("Sub", (base,), {})
            with self.assertRaises(TypeError):
                exec("class Sub(base):\n    pass", {"base": base})

    def test_47_copy_and_deepcopy_return_the_same_object(self):
        result = create_game_structure_request(good())
        for obj in (result, result.request, create_game_structure_request(None)):
            self.assertIs(copy.copy(obj), obj)
            self.assertIs(copy.deepcopy(obj), obj)

    def test_48_pickle_is_refused(self):
        result = create_game_structure_request(good())
        for obj in (result, result.request, create_game_structure_request(None)):
            for protocol in range(0, pickle.HIGHEST_PROTOCOL + 1):
                with self.assertRaises(TypeError):
                    pickle.dumps(obj, protocol)
        with self.assertRaises(TypeError):
            result.request.__reduce_ex__(2)

    def test_49_repr_is_deterministic(self):
        r = create_game_structure_request(good())
        self.assertEqual(repr(r.request), "GameStructureRequest(scenes=2, characters=2, gameplay_systems=2, assets=2)")
        self.assertEqual(repr(r), "GameStructureRequestResult(ok=True, failures=0)")
        self.assertEqual(repr(create_game_structure_request(None)), "GameStructureRequestResult(ok=False, failures=1)")


class TestIsolation(unittest.TestCase):
    def tree(self):
        with open(SOURCE, encoding="utf-8") as fh:
            return ast.parse(fh.read())

    def test_50_module_imports_nothing(self):
        self.assertEqual([ast.unparse(n) for n in ast.walk(self.tree()) if isinstance(n, (ast.Import, ast.ImportFrom))], [])
        code = ("import sys; before=set(sys.modules); import game_creation.game_structure_request as m; "
                "new=sorted(n for n in set(sys.modules)-before if n.startswith('game_creation')); print(new)")
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=PY_ROOT)
        out = subprocess.run([sys.executable, "-c", code], cwd=PY_ROOT, env=env, capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(out, "['game_creation', 'game_creation.game_structure_request']")

    def test_51_module_does_not_reference_other_layers(self):
        tree = self.tree()
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for forbidden in ("GameProject", "create_game_project", "GameProjectStructure", "create_game_project_structure", "GameCreationRequest",
                          "create_game_creation_request", "GameDefinition", "create_game_definition", "GameSceneRegistry", "GameCharacterRegistry",
                          "GameAssetRegistry", "GameplaySystemRegistry", "GameSceneCompositionRegistry", "GameSceneBundleRegistry",
                          "GameProjectValidator", "validate_game_project", "validate_game_scene_composition", "lookup_game_scene",
                          "build_game_definition_summary", "get_game_definition_counts", "Core", "Planner", "AgentLoop", "process_input",
                          "copy", "pickle", "os", "sys", "open", "socket", "sqlite3", "random", "time", "datetime", "subprocess", "threading"):
            self.assertNotIn(forbidden, names, forbidden)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node is not tree.body[0].value:
                for token in ("game_project", "game_definition", "game_creation_request", "GameDefinition"):
                    self.assertNotIn(token, node.value)

    def test_52_no_project_structure_is_created(self):
        with mock.patch.object(structure_module, "create_game_project_structure", side_effect=AssertionError("structure created")), \
             mock.patch.object(structure_module, "GameProjectStructure", side_effect=AssertionError("structure built")):
            self.assertTrue(create_game_structure_request(good()).ok)
            self.assertFalse(create_game_structure_request({"scenes": [""]}).ok)
            self.assertFalse(create_game_structure_request(None).ok)
        self.assertFalse(hasattr(sr, "create_game_project_structure"))
        self.assertFalse(hasattr(sr, "GameProjectStructure"))

    def test_53_values_are_never_rewritten(self):
        tree = self.tree()
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for method in ("lstrip", "rstrip", "lower", "upper", "casefold", "normalize", "title", "capitalize", "encode", "decode", "replace", "join",
                       "split", "str", "int", "bool", "dict", "sorted_items", "deepcopy", "copy"):
            self.assertFalse([c for c in calls if c == method or c.endswith("." + method)], method)
        self.assertEqual(sorted(c for c in calls if c in ("set", "tuple", "list", "sorted")), ["list", "set", "sorted", "tuple"])
        strips = [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.Call) and ast.unparse(n.func).endswith(".strip")]
        self.assertEqual(strips, ["item.strip()"])      # the only use: a blank check whose result is compared, never stored
        compared = [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, ast.Compare) and "item.strip()" in ast.unparse(n)]
        self.assertEqual(compared, ["item.strip() == ''"])

    def test_54_no_io_and_no_module_level_mutable_state(self):
        tree = self.tree()
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "copy.copy", "copy.deepcopy"):
            self.assertNotIn(forbidden, calls)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef))
        for name, value in vars(sr).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set, bytearray), name)
        self.assertIs(type(sr.FIELDS), tuple)
        self.assertIs(type(sr.FAILURE_CODES), tuple)

    def test_55_exactly_one_public_function_and_two_classes(self):
        tree = self.tree()
        self.assertEqual([n.name for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")], ["create_game_structure_request"])
        self.assertEqual([n.name for n in tree.body if isinstance(n, ast.ClassDef)], ["GameStructureRequest", "GameStructureRequestResult"])

    def test_56_no_existing_module_knows_the_new_module(self):
        needles = ("game_structure_request", "create_game_structure_request", "GameStructureRequest")
        bridge = os.path.join(PKG, "game_structure_request_bridge.py")      # Prompt 744: a sanctioned consumer (exact-type import only)
        registries_bridge = os.path.join(PKG, "game_structure_registries_from_request.py")      # Prompt 745: a sanctioned consumer (exact-type import only)
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if d not in ("tests", "data")]
            for name in files:
                path = os.path.join(folder, name)
                if name.endswith(".py") and path not in (SOURCE, bridge, registries_bridge):
                    with open(path, encoding="utf-8") as fh:
                        text = fh.read()
                    for needle in needles:
                        self.assertNotIn(needle, text, path)

    def test_57_core_input_planner_and_agent_loop_do_not_know_the_game_layer(self):
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("game_creation", "game_structure_request", "create_game_structure_request"):
                self.assertNotIn(token, text, (rel, token))

    def test_58_package_listing_has_exactly_the_one_new_module(self):
        self.assertEqual(sorted(os.listdir(PKG)), [
            "__init__.py", "game_asset.py", "game_asset_registry.py", "game_character.py", "game_character_registry.py", "game_creation_request.py",
            "game_creation_request_bridge.py", "game_definition.py", "game_definition_counts.py", "game_definition_from_request.py",
            "game_definition_queries.py", "game_definition_query_helpers.py", "game_definition_summary.py", "game_project.py",
            "game_project_structure.py", "game_project_validator.py", "game_scene.py", "game_scene_bundle.py", "game_scene_bundle_registry.py",
            "game_scene_composition.py", "game_scene_composition_registry.py", "game_scene_composition_validator.py", "game_scene_registry.py",
            "game_structure_from_request.py", "game_structure_registries_from_request.py", "game_structure_request.py", "game_structure_request_bridge.py", "gameplay_system_registry.py"])

    def test_59_package_init_is_empty_of_exports(self):
        with open(os.path.join(PKG, "__init__.py"), encoding="utf-8") as fh:
            self.assertNotIn("game_structure_request", fh.read())


class TestScopeAndDocumentation(unittest.TestCase):
    def test_60_pristine_database_and_no_bytecode(self):
        self.assertEqual(sha(PROJECT_DB), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)

    def test_61_documentation_names_the_contract(self):
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("create_game_structure_request", "GameStructureRequestResult", "GameStructureRequest", "GAME_STRUCTURE_REQUEST_", "INVALID_INPUT",
                       "UNEXPECTED_FIELD", "MISSING_FIELD", "INVALID_COLLECTION", "INVALID_ITEM", "DUPLICATE_ITEM", "scenes", "characters",
                       "gameplay_systems", "assets", "exact", "does NOT", "imports nothing", "Prompt 744"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
