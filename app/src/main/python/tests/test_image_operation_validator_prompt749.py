"""Prompt 749 - Section 8 image operation request registry validation (`multimedia.image_operation_validator`)."""
import ast
import copy
import hashlib
import os
import pickle
import unittest
from unittest import mock

from multimedia import image_operation_validator as iov
from multimedia.image_asset import ImageAsset, create_image_asset
from multimedia.image_asset_registry import ImageAssetRegistry, create_image_asset_registry
from multimedia.image_operation_request import ImageOperationRequest, create_image_operation_request
from multimedia.image_operation_validator import ImageOperationValidationResult, validate_image_operation_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section8_image_operation_validator_prompt749.md")
MODULE = os.path.join(PY_ROOT, "multimedia", "image_operation_validator.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"

P = "IMAGE_OPERATION_VALIDATION_"


def asset(image_id, **over):
    data = {"image_id": image_id, "name": "Name " + image_id, "description": "d", "format": "png", "width": 1024, "height": 768}
    data.update(over)
    r = create_image_asset(data)
    assert r.ok, r.failures
    return r.asset


def registry(*ids):
    r = create_image_asset_registry([asset(i) for i in ids])
    assert r.ok, r.failures
    return r.registry


def request(image_id="hero", **over):
    data = {"image_id": image_id, "operation": "resize", "target_format": "webp", "width": 800, "height": 600, "quality": 85}
    data.update(over)
    r = create_image_operation_request(data)
    assert r.ok, r.failures
    return r.request


class TestValid(unittest.TestCase):
    def test_1_valid_request_with_registered_image(self):
        res = validate_image_operation_request(request("hero"), registry("hero", "logo"))
        self.assertIs(type(res), ImageOperationValidationResult)
        self.assertTrue(res.ok)
        self.assertEqual(res.failures, ())
        self.assertEqual(res.codes(), [])
        self.assertEqual(res.asset.image_id, "hero")

    def test_2_exact_asset_identity_preserved(self):
        a, b = asset("a"), asset("b")
        reg = create_image_asset_registry([a, b]).registry
        res = validate_image_operation_request(request("b"), reg)
        self.assertIs(res.asset, b)
        self.assertIs(res.asset, reg.assets[1])
        self.assertIsNot(res.asset, a)

    def test_3_request_identity_preserved(self):
        q = request("hero")
        res = validate_image_operation_request(q, registry("hero"))
        self.assertIs(res.request, q)

    def test_4_operation_and_format_not_restricted_beyond_748(self):
        reg = registry("hero")
        for op, fmt in (("resize", "webp"), ("totally-new-op", ""), ("  padded ", "XYZ"), ("\u00e9", "not-a-format")):
            with self.subTest(op=op):
                self.assertTrue(validate_image_operation_request(request("hero", operation=op, target_format=fmt), reg).ok)

    def test_5_dimensions_not_compared_with_asset(self):
        reg = create_image_asset_registry([asset("hero", width=10, height=10)]).registry
        res = validate_image_operation_request(request("hero", width=99999, height=99999, quality=1), reg)
        self.assertTrue(res.ok)

    def test_6_format_mismatch_is_not_checked(self):
        reg = create_image_asset_registry([asset("hero", format="jpeg")]).registry
        self.assertTrue(validate_image_operation_request(request("hero", target_format="png"), reg).ok)


class TestInvalidInputs(unittest.TestCase):
    def test_7_invalid_request(self):
        for bad in (None, {}, "hero", 5, object(), request("hero").to_dict()):
            with self.subTest(bad=type(bad).__name__):
                res = validate_image_operation_request(bad, registry("hero"))
                self.assertFalse(res.ok)
                self.assertEqual(res.codes(), [P + "INVALID_REQUEST"])
                self.assertIsNone(res.request)
                self.assertIsNone(res.asset)

    def test_8_invalid_registry(self):
        for bad in (None, [], (), {}, "reg", 5, object(), registry("hero").to_dict(), [asset("hero")]):
            with self.subTest(bad=type(bad).__name__):
                q = request("hero")
                res = validate_image_operation_request(q, bad)
                self.assertFalse(res.ok)
                self.assertEqual(res.codes(), [P + "INVALID_IMAGE_REGISTRY"])
                self.assertIs(res.request, q)
                self.assertIsNone(res.asset)

    def test_9_both_invalid_reported_in_order(self):
        res = validate_image_operation_request(None, None)
        self.assertEqual(res.codes(), [P + "INVALID_REQUEST", P + "INVALID_IMAGE_REGISTRY"])
        self.assertIsNone(res.request)
        self.assertEqual([f["field"] for f in res.failures], ["request", "image_registry"])

    def test_10_request_subclass_rejected(self):
        # ImageOperationRequest refuses subclassing, so a look-alike is the closest thing a caller can pass.
        with self.assertRaises(TypeError):
            type("Sub", (ImageOperationRequest,), {})

        class Fake:
            image_id = "hero"

        res = validate_image_operation_request(Fake(), registry("hero"))
        self.assertEqual(res.codes(), [P + "INVALID_REQUEST"])

    def test_11_registry_subclass_rejected(self):
        with self.assertRaises(TypeError):
            type("Sub", (ImageAssetRegistry,), {})

        class Fake:
            def lookup(self, image_id):
                raise AssertionError("must not be called")

        res = validate_image_operation_request(request("hero"), Fake())
        self.assertEqual(res.codes(), [P + "INVALID_IMAGE_REGISTRY"])

    def test_12_no_cross_validation_when_input_invalid(self):
        with mock.patch.object(ImageAssetRegistry, "lookup", autospec=True) as spy:
            validate_image_operation_request(None, registry("hero"))
            validate_image_operation_request(request("hero"), None)
            validate_image_operation_request(None, None)
        spy.assert_not_called()

    def test_13_failure_shape_and_codes_are_stable(self):
        self.assertEqual(iov.FAILURE_CODES, (P + "INVALID_REQUEST", P + "INVALID_IMAGE_REGISTRY", P + "IMAGE_NOT_FOUND"))
        for f in validate_image_operation_request(None, None).failures:
            self.assertEqual(set(f), {"code", "field", "message"})
            self.assertIs(type(f["message"]), str)


class TestNotFound(unittest.TestCase):
    def test_14_missing_image(self):
        q = request("ghost")
        res = validate_image_operation_request(q, registry("hero"))
        self.assertFalse(res.ok)
        self.assertEqual(res.codes(), [P + "IMAGE_NOT_FOUND"])
        self.assertIs(res.request, q)
        self.assertIsNone(res.asset)
        self.assertEqual(res.failures[0]["field"], "image_id")

    def test_15_exact_image_id_matching(self):
        reg = registry("Hero")
        for wrong in ("hero", "HERO", " Hero", "Hero ", "Hero\n", "He ro"):
            with self.subTest(wrong=wrong):
                self.assertEqual(validate_image_operation_request(request(wrong), reg).codes(), [P + "IMAGE_NOT_FOUND"])
        self.assertTrue(validate_image_operation_request(request("Hero"), reg).ok)

    def test_16_empty_registry(self):
        reg = create_image_asset_registry([]).registry
        res = validate_image_operation_request(request("hero"), reg)
        self.assertEqual(res.codes(), [P + "IMAGE_NOT_FOUND"])
        self.assertIsNone(res.asset)

    def test_17_not_found_message_is_deterministic(self):
        a = validate_image_operation_request(request("ghost"), registry("hero"))
        b = validate_image_operation_request(request("ghost"), registry("hero"))
        self.assertEqual(a.failures, b.failures)
        self.assertEqual(a, b)


class TestNoMutation(unittest.TestCase):
    def test_18_registry_state_unchanged(self):
        reg = registry("a", "b", "c")
        before_dict, before_ids, before_assets, before_hash = reg.to_dict(), reg.image_ids, reg.assets, hash(reg)
        for q in (request("a"), request("zzz")):
            validate_image_operation_request(q, reg)
        self.assertEqual(reg.to_dict(), before_dict)
        self.assertEqual(reg.image_ids, before_ids)
        self.assertEqual(reg.assets, before_assets)
        self.assertTrue(all(x is y for x, y in zip(reg.assets, before_assets)))
        self.assertEqual(hash(reg), before_hash)

    def test_19_request_state_unchanged(self):
        q = request("a")
        before, before_hash, ids = q.to_dict(), hash(q), q.image_id
        validate_image_operation_request(q, registry("a"))
        validate_image_operation_request(q, registry("b"))
        self.assertEqual(q.to_dict(), before)
        self.assertEqual(hash(q), before_hash)
        self.assertIs(q.image_id, ids)

    def test_20_asset_state_unchanged(self):
        a = asset("a")
        before = a.to_dict()
        validate_image_operation_request(request("a"), create_image_asset_registry([a]).registry)
        self.assertEqual(a.to_dict(), before)

    def test_21_same_inputs_are_idempotent(self):
        q, reg = request("a"), registry("a")
        r1, r2 = validate_image_operation_request(q, reg), validate_image_operation_request(q, reg)
        self.assertIsNot(r1, r2)
        self.assertEqual(r1, r2)
        self.assertEqual(hash(r1), hash(r2))


class TestPublicLookupDelegation(unittest.TestCase):
    def test_22_lookup_called_once_with_the_request_image_id_object(self):
        q, reg = request("a"), registry("a")
        with mock.patch.object(ImageAssetRegistry, "lookup", autospec=True, side_effect=ImageAssetRegistry.lookup) as spy:
            res = validate_image_operation_request(q, reg)
        self.assertTrue(res.ok)
        self.assertEqual(spy.call_count, 1)
        args = spy.call_args[0]
        self.assertIs(args[0], reg)
        self.assertIs(args[1], q.image_id)

    def test_23_result_follows_whatever_public_lookup_returns(self):
        from multimedia.image_asset_registry import ImageAssetLookupResult
        other = asset("other")
        q, reg = request("a"), registry("a")
        with mock.patch.object(ImageAssetRegistry, "lookup", autospec=True, return_value=ImageAssetLookupResult(True, other)):
            res = validate_image_operation_request(q, reg)
        self.assertTrue(res.ok)
        self.assertIs(res.asset, other)           # taken from lookup(), not re-derived from the registry's contents
        with mock.patch.object(ImageAssetRegistry, "lookup", autospec=True, return_value=ImageAssetLookupResult(False, None, [])):
            res = validate_image_operation_request(q, reg)
        self.assertEqual(res.codes(), [P + "IMAGE_NOT_FOUND"])
        self.assertIsNone(res.asset)

    def test_24_found_result_with_non_asset_is_not_trusted(self):
        from multimedia.image_asset_registry import ImageAssetLookupResult
        with mock.patch.object(ImageAssetRegistry, "lookup", autospec=True, return_value=ImageAssetLookupResult(True, object())):
            res = validate_image_operation_request(request("a"), registry("a"))
        self.assertEqual(res.codes(), [P + "IMAGE_NOT_FOUND"])
        self.assertIsNone(res.asset)

    def test_25_module_uses_only_public_registry_api(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertIn("lookup", attrs)
        for private in ("_assets", "_image_ids", "_key"):
            # `_key` is only used on the result's own state (self / other), never on registry/request objects
            if private != "_key":
                self.assertNotIn(private, attrs)
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and n.attr == "_key":
                self.assertIsInstance(n.value, ast.Name)
                self.assertIn(n.value.id, ("self", "other"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"open", "os", "subprocess", "socket", "random", "time"})


class TestResultContract(unittest.TestCase):
    def setUp(self):
        self.ok = validate_image_operation_request(request("a"), registry("a"))
        self.bad = validate_image_operation_request(request("zzz"), registry("a"))

    def test_26_direct_construction_refused(self):
        for args in ((), (None, None, None, []), (object(), None, None, [])):
            with self.subTest(args=len(args)):
                with self.assertRaises(TypeError):
                    ImageOperationValidationResult(*args)

    def test_27_subclassing_refused(self):
        with self.assertRaises(TypeError):
            type("Sub", (ImageOperationValidationResult,), {})

    def test_28_immutable(self):
        for name in ("ok", "request", "asset", "failures", "_request", "_asset", "_failures", "extra"):
            with self.subTest(name=name):
                with self.assertRaises(AttributeError):
                    setattr(self.ok, name, 1)
                with self.assertRaises(AttributeError):
                    delattr(self.ok, name)
        self.assertFalse(hasattr(self.ok, "__dict__"))
        self.assertEqual(ImageOperationValidationResult.__slots__, ("_request", "_asset", "_failures"))

    def test_29_to_dict_shape_and_freshness(self):
        d = self.ok.to_dict()
        self.assertEqual(list(d), ["ok", "request", "asset", "failures"])
        self.assertEqual(d["request"], request("a").to_dict())
        self.assertEqual(d["asset"], asset("a").to_dict())
        self.assertEqual(d["failures"], [])
        d["request"]["image_id"] = "mutated"
        d["asset"]["name"] = "mutated"
        d["failures"].append("x")
        d["ok"] = False
        d2 = self.ok.to_dict()
        self.assertIsNot(d, d2)
        self.assertEqual(d2["request"]["image_id"], "a")
        self.assertEqual(d2["asset"]["name"], "Name a")
        self.assertEqual(d2["failures"], [])
        self.assertTrue(d2["ok"])

    def test_30_failed_to_dict_is_fresh_and_json_shaped(self):
        d = self.bad.to_dict()
        self.assertFalse(d["ok"])
        self.assertIsNone(d["asset"])
        self.assertEqual(d["request"]["image_id"], "zzz")
        self.assertEqual([f["code"] for f in d["failures"]], [P + "IMAGE_NOT_FOUND"])
        d["failures"][0]["code"] = "mutated"
        self.assertEqual(self.bad.to_dict()["failures"][0]["code"], P + "IMAGE_NOT_FOUND")
        both = validate_image_operation_request(None, None).to_dict()
        self.assertIsNone(both["request"])
        self.assertEqual(len(both["failures"]), 2)

    def test_31_failures_property_returns_fresh_copies(self):
        f1 = self.bad.failures
        f1[0]["code"] = "mutated"
        self.assertEqual(self.bad.failures[0]["code"], P + "IMAGE_NOT_FOUND")
        self.assertIsInstance(f1, tuple)
        self.assertIsNot(self.bad.failures[0], self.bad.failures[0])

    def test_32_equality_and_hash(self):
        a1 = validate_image_operation_request(request("a"), registry("a"))
        a2 = validate_image_operation_request(request("a"), registry("a"))
        self.assertEqual(a1, a2)
        self.assertEqual(hash(a1), hash(a2))
        self.assertEqual(len({a1, a2}), 1)
        self.assertNotEqual(a1, self.bad)
        self.assertNotEqual(a1, validate_image_operation_request(request("a", width=1), registry("a")))
        self.assertNotEqual(a1, validate_image_operation_request(request("a"), create_image_asset_registry([asset("a", width=5)]).registry))
        self.assertNotEqual(a1, a1.to_dict())
        self.assertNotEqual(a1, None)
        self.assertEqual(validate_image_operation_request(None, None), validate_image_operation_request(5, "x"))
        self.assertEqual(hash(validate_image_operation_request(None, None)), hash(validate_image_operation_request(5, "x")))

    def test_33_hashable_for_every_outcome(self):
        outs = [self.ok, self.bad, validate_image_operation_request(None, registry("a")),
                validate_image_operation_request(request("a"), None), validate_image_operation_request(None, None)]
        self.assertEqual(len({hash(o) for o in outs}), len(outs))
        self.assertEqual(len(set(outs)), len(outs))

    def test_34_copy_and_deepcopy_return_same_object(self):
        for res in (self.ok, self.bad):
            self.assertIs(copy.copy(res), res)
            self.assertIs(copy.deepcopy(res), res)
            self.assertIs(copy.deepcopy([res])[0], res)

    def test_35_pickle_refused(self):
        for proto in range(pickle.HIGHEST_PROTOCOL + 1):
            with self.subTest(proto=proto):
                with self.assertRaises(TypeError):
                    pickle.dumps(self.ok, protocol=proto)
        with self.assertRaises(TypeError):
            pickle.dumps(self.bad)

    def test_36_repr_is_stable(self):
        self.assertEqual(repr(self.ok), "ImageOperationValidationResult(ok=True, codes=[])")
        self.assertEqual(repr(self.bad), "ImageOperationValidationResult(ok=False, codes=['%sIMAGE_NOT_FOUND'])" % P)

    def test_37_ok_is_derived_from_failures(self):
        self.assertIs(self.ok.ok, True)
        self.assertIs(self.bad.ok, False)
        self.assertIsNotNone(self.ok.asset)
        self.assertIsNone(self.bad.asset)


class TestDeterminism(unittest.TestCase):
    def test_38_never_raises_for_odd_inputs(self):
        class Evil:
            def __getattr__(self, name):
                raise AssertionError("attribute access on caller object: " + name)

            def __eq__(self, other):
                raise AssertionError("eq")

            __hash__ = None

        for req in (Evil(), None, [], 1.5):
            for reg in (Evil(), None, {}, 3):
                with self.subTest(req=type(req).__name__, reg=type(reg).__name__):
                    res = validate_image_operation_request(req, reg)
                    self.assertEqual(res.codes(), [P + "INVALID_REQUEST", P + "INVALID_IMAGE_REGISTRY"])

    def test_39_str_subclass_image_id_cannot_exist_on_request(self):
        class S(str):
            pass

        r = create_image_operation_request({"image_id": S("a"), "operation": "resize", "target_format": "", "width": 1, "height": 1, "quality": 1})
        self.assertFalse(r.ok)
        self.assertEqual(validate_image_operation_request(r.request, registry("a")).codes(), [P + "INVALID_REQUEST"])

    def test_40_prior_prompt_modules_still_unmodified_in_behavior(self):
        reg = registry("a")
        self.assertEqual(reg.lookup("a").asset, asset("a"))
        self.assertTrue(type(reg.lookup("a").asset) is ImageAsset)
        self.assertEqual(reg.lookup("nope").codes(), ["IMAGE_ASSET_REGISTRY_IMAGE_NOT_FOUND"])

    def test_41_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("ImageOperationValidationResult", "validate_image_operation_request", "IMAGE_OPERATION_VALIDATION_",
                       "INVALID_REQUEST", "INVALID_IMAGE_REGISTRY", "IMAGE_NOT_FOUND", "lookup()", "does NOT", "Prompt 750"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
