"""Prompt 763 - Section 8 audio operation plan (`multimedia.audio_operation_plan`)."""
import ast
import copy
import hashlib
import os
import pickle
import unittest

from multimedia import audio_operation_plan as aop
from multimedia.audio_asset import AudioAsset, create_audio_asset
from multimedia.audio_asset_registry import AudioAssetRegistry, create_audio_asset_registry
from multimedia.audio_operation_plan import AudioOperationPlan, AudioOperationPlanResult, create_audio_operation_plan
from multimedia.audio_operation_request import AudioOperationRequest, create_audio_operation_request
from multimedia.audio_operation_validator import AudioOperationValidationResult, validate_audio_operation_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section8_audio_operation_plan_prompt763.md")
MODULE = os.path.join(PY_ROOT, "multimedia", "audio_operation_plan.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
P = "AUDIO_OPERATION_PLAN_"
FIELDS = ("audio_id", "operation", "target_format", "duration_ms", "sample_rate", "quality")
DEFAULT = {"audio_id": "theme", "operation": "trim", "target_format": "mp3", "duration_ms": 1000, "sample_rate": 22050, "quality": 70}


def make_asset(audio_id="theme"):
    r = create_audio_asset({"audio_id": audio_id, "name": "N", "description": "", "format": "ogg", "duration_ms": 5000, "sample_rate": 44100})
    assert r.ok, r.failures
    return r.asset


def make_registry(*assets):
    r = create_audio_asset_registry(list(assets))
    assert r.ok, r.failures
    return r.registry


def make_request(**over):
    data = dict(DEFAULT)
    data.update(over)
    r = create_audio_operation_request(data)
    assert r.ok, r.failures
    return r.request


def validated(**over):
    """(validation_result, request, asset, registry) for a registered audio asset."""
    asset = make_asset(over.get("audio_id", "theme"))
    reg = make_registry(asset)
    req = make_request(**over)
    res = validate_audio_operation_request(req, reg)
    assert res.ok, res.codes()
    return res, req, asset, reg


class TestSuccess(unittest.TestCase):
    def test_1_valid_validation_result_produces_the_exact_expected_plan(self):
        vr, _req, _a, _r = validated()
        res = create_audio_operation_plan(vr)
        self.assertIs(type(res), AudioOperationPlanResult)
        self.assertTrue(res.ok)
        self.assertEqual(res.failures, ())
        self.assertEqual(res.codes(), [])
        self.assertIs(type(res.plan), AudioOperationPlan)
        self.assertEqual(res.plan.to_dict(), DEFAULT)
        self.assertEqual(res.to_dict(), {"ok": True, "plan": res.plan.to_dict(), "failures": []})

    def test_2_all_six_values_preserved_exactly(self):
        vr, req, _a, _r = validated(audio_id="aud-7", operation="Totally New  Op", target_format="", duration_ms=1, sample_rate=192000, quality=100)
        p = create_audio_operation_plan(vr).plan
        for name in FIELDS:
            self.assertEqual(getattr(p, name), getattr(req, name), name)
        self.assertEqual((p.audio_id, p.operation, p.target_format, p.duration_ms, p.sample_rate, p.quality),
                         ("aud-7", "Totally New  Op", "", 1, 192000, 100))

    def test_3_fields_are_exactly_the_six_in_fixed_order(self):
        self.assertEqual(aop.FIELDS, FIELDS)
        self.assertEqual(AudioOperationPlan.__slots__, tuple("_" + f for f in FIELDS))
        self.assertEqual(list(create_audio_operation_plan(validated()[0]).plan.to_dict()), list(FIELDS))

    def test_4_no_normalization_trimming_casefolding_or_coercion(self):
        for over in ({"operation": "  TRIM\t"}, {"target_format": "  MP3 "}, {"audio_id": " Theme "}, {"target_format": "   "}):
            with self.subTest(over=over):
                vr, req, _a, _r = validated(**over)
                p = create_audio_operation_plan(vr).plan
                self.assertEqual(p.to_dict(), req.to_dict())

    def test_5_exact_value_identity_preserved(self):
        audio_id = "".join(["the", "_", "me"])
        op = "".join(["tr", "im"])
        fmt = "".join(["m", "p3"])
        vr, req, _a, _r = validated(audio_id=audio_id, operation=op, target_format=fmt)
        p = create_audio_operation_plan(vr).plan
        self.assertIs(p.audio_id, audio_id)
        self.assertIs(p.operation, op)
        self.assertIs(p.target_format, fmt)
        self.assertIs(p.audio_id, req.audio_id)
        self.assertIs(p.to_dict()["operation"], op)
        for name in ("duration_ms", "sample_rate", "quality"):
            self.assertIs(getattr(p, name), getattr(req, name))
            self.assertIs(type(getattr(p, name)), int)

    def test_6_operation_and_format_stay_free_text(self):
        for op, fmt in (("fade", "flac"), ("convert", "not-a-format"), ("\u00e9", "\u00e9"), ("x" * 300, "")):
            with self.subTest(op=op[:8]):
                p = create_audio_operation_plan(validated(operation=op, target_format=fmt)[0]).plan
                self.assertEqual((p.operation, p.target_format), (op, fmt))

    def test_7_deterministic_repeated_creation(self):
        vr, _req, _a, _r = validated()
        r1, r2 = create_audio_operation_plan(vr), create_audio_operation_plan(vr)
        self.assertIsNot(r1, r2)
        self.assertIsNot(r1.plan, r2.plan)
        self.assertEqual(r1, r2)
        self.assertEqual(r1.plan, r2.plan)
        self.assertEqual(hash(r1), hash(r2))
        self.assertEqual(r1.to_dict(), r2.to_dict())
        self.assertEqual(create_audio_operation_plan(validated()[0]), r1)

    def test_8_values_are_not_compared_with_the_registered_asset(self):
        # request values deliberately differ from the asset (duration, sample rate, format); the plan copies the REQUEST.
        asset = create_audio_asset({"audio_id": "theme", "name": "N", "description": "", "format": "wav", "duration_ms": 10, "sample_rate": 8000}).asset
        vr = validate_audio_operation_request(make_request(duration_ms=999999, sample_rate=96000, target_format="flac"), make_registry(asset))
        p = create_audio_operation_plan(vr).plan
        self.assertEqual((p.duration_ms, p.sample_rate, p.target_format), (999999, 96000, "flac"))


class TestFailure(unittest.TestCase):
    def test_9_invalid_validation_result_type(self):
        vr = validated()[0]
        for bad in (None, {}, [], "ok", 5, True, object(), vr.to_dict(), vr.request, make_request(), make_registry(), make_asset()):
            with self.subTest(bad=type(bad).__name__):
                res = create_audio_operation_plan(bad)
                self.assertFalse(res.ok)
                self.assertIsNone(res.plan)
                self.assertEqual(res.codes(), [P + "INVALID_VALIDATION_RESULT"])
                self.assertEqual(res.failures[0]["field"], "validation_result")

    def test_10_look_alike_validation_result_is_rejected_and_never_read(self):
        class Fake:
            ok = True

            def __getattr__(self, name):
                raise AssertionError("must not read " + name)

        res = create_audio_operation_plan(Fake())
        self.assertEqual(res.codes(), [P + "INVALID_VALIDATION_RESULT"])
        with self.assertRaises(TypeError):
            type("Sub", (AudioOperationValidationResult,), {})

    def test_11_validation_result_with_ok_false(self):
        reg = make_registry(make_asset("theme"))
        failed_results = (
            validate_audio_operation_request(make_request(audio_id="ghost"), reg),
            validate_audio_operation_request(None, reg),
            validate_audio_operation_request(make_request(), None),
            validate_audio_operation_request(None, None),
        )
        for vr in failed_results:
            with self.subTest(codes=vr.codes()):
                self.assertFalse(vr.ok)
                res = create_audio_operation_plan(vr)
                self.assertFalse(res.ok)
                self.assertIsNone(res.plan)
                self.assertEqual(res.codes(), [P + "VALIDATION_FAILED"])
                self.assertEqual(res.failures[0]["field"], "validation_result")

    def test_12_no_plan_returned_on_failure(self):
        reg = make_registry()
        for vr in (validate_audio_operation_request(make_request(), reg), None):
            res = create_audio_operation_plan(vr)
            self.assertIsNone(res.plan)
            self.assertFalse(res.ok)
            self.assertIsNone(res.to_dict()["plan"])
            self.assertFalse(res.to_dict()["ok"])

    def test_13_failed_validation_with_found_request_still_gives_no_plan(self):
        # AUDIO_NOT_FOUND results still carry the (valid) request; a plan must not be built from it.
        vr = validate_audio_operation_request(make_request(audio_id="ghost"), make_registry())
        self.assertIsNotNone(vr.request)
        self.assertIsNone(create_audio_operation_plan(vr).plan)

    def test_14_failure_messages_and_codes_are_stable(self):
        self.assertEqual(aop.FAILURE_CODES, (P + "INVALID_VALIDATION_RESULT", P + "VALIDATION_FAILED"))
        a = create_audio_operation_plan(validate_audio_operation_request(make_request(audio_id="ghost"), make_registry()))
        b = create_audio_operation_plan(validate_audio_operation_request(make_request(audio_id="ghost"), make_registry()))
        self.assertEqual(a, b)
        self.assertEqual(a.failures, b.failures)
        self.assertEqual(set(a.failures[0]), {"code", "field", "message"})
        self.assertIn("AUDIO_OPERATION_VALIDATION_AUDIO_NOT_FOUND", a.failures[0]["message"])
        self.assertEqual(a.to_dict()["failures"], [dict(a.failures[0])])
        c = create_audio_operation_plan(None)
        self.assertEqual(c.failures[0]["message"], "validation_result must be exactly an AudioOperationValidationResult.")


class TestNoRetentionAndNoMutation(unittest.TestCase):
    def test_15_asset_registry_request_and_result_are_not_retained(self):
        vr, req, asset, reg = validated()
        res = create_audio_operation_plan(vr)
        forbidden = (asset, reg, req, vr)
        for obj in (res, res.plan):
            for slot in type(obj).__slots__:
                value = getattr(obj, slot)
                for f in forbidden:
                    self.assertIsNot(value, f, slot)
        for value in res.plan.to_dict().values():
            self.assertIs(type(value), str if isinstance(value, str) else int)
        self.assertEqual(sorted(type(res.plan).__slots__), sorted("_" + f for f in FIELDS))
        for name in ("asset", "registry", "request", "validation_result"):
            self.assertFalse(hasattr(res.plan, name), name)
            self.assertFalse(hasattr(res, name), name)
        self.assertNotIn("name", res.plan.to_dict())
        self.assertNotIn("description", res.plan.to_dict())
        self.assertFalse(hasattr(res.plan, "__dict__"))
        self.assertFalse(hasattr(res, "__dict__"))

    def test_16_source_validation_result_remains_unchanged(self):
        vr, req, _asset, reg = validated()
        before = (vr.to_dict(), hash(vr), vr.request, vr.registry, vr.codes(), vr.failures, vr.ok)
        create_audio_operation_plan(vr)
        create_audio_operation_plan(vr)
        after = (vr.to_dict(), hash(vr), vr.request, vr.registry, vr.codes(), vr.failures, vr.ok)
        self.assertEqual(before, after)
        self.assertIs(vr.request, req)
        self.assertIs(vr.registry, reg)

    def test_17_request_asset_and_registry_remain_unchanged(self):
        vr, req, asset, reg = validated()
        snap = (req.to_dict(), hash(req), asset.to_dict(), hash(asset), reg.to_dict(), hash(reg))
        create_audio_operation_plan(vr)
        self.assertEqual(snap, (req.to_dict(), hash(req), asset.to_dict(), hash(asset), reg.to_dict(), hash(reg)))
        self.assertIs(type(reg), AudioAssetRegistry)
        self.assertIs(type(asset), AudioAsset)
        self.assertIs(type(req), AudioOperationRequest)

    def test_18_failed_source_validation_result_remains_unchanged(self):
        vr = validate_audio_operation_request(make_request(audio_id="ghost"), make_registry())
        before = (vr.to_dict(), hash(vr))
        create_audio_operation_plan(vr)
        self.assertEqual(before, (vr.to_dict(), hash(vr)))


class TestPlanContract(unittest.TestCase):
    def setUp(self):
        self.res = create_audio_operation_plan(validated()[0])
        self.plan = self.res.plan
        self.bad = create_audio_operation_plan(None)

    def test_19_read_only_properties(self):
        for name in FIELDS:
            with self.subTest(name=name):
                with self.assertRaises(AttributeError):
                    setattr(self.plan, name, 1)
                with self.assertRaises(AttributeError):
                    delattr(self.plan, name)
                with self.assertRaises(AttributeError):
                    setattr(self.plan, "_" + name, 1)
        with self.assertRaises(AttributeError):
            self.plan.extra = 1

    def test_20_direct_construction_refused(self):
        for args in ((), (None, "a", "b", "c", 1, 1, 1), (object(), "a", "b", "c", 1, 1, 1)):
            with self.subTest(n=len(args)):
                with self.assertRaises(TypeError):
                    AudioOperationPlan(*args)
        for args in ((), (None, None, []), (object(), None, [])):
            with self.subTest(n=len(args)):
                with self.assertRaises(TypeError):
                    AudioOperationPlanResult(*args)

    def test_21_subclassing_refused(self):
        with self.assertRaises(TypeError):
            type("S1", (AudioOperationPlan,), {})
        with self.assertRaises(TypeError):
            type("S2", (AudioOperationPlanResult,), {})

    def test_22_result_is_immutable(self):
        for name in ("ok", "plan", "failures", "_plan", "_failures", "extra"):
            with self.subTest(name=name):
                with self.assertRaises(AttributeError):
                    setattr(self.res, name, 1)
                with self.assertRaises(AttributeError):
                    delattr(self.res, name)
        self.assertEqual(AudioOperationPlanResult.__slots__, ("_plan", "_failures"))

    def test_23_fresh_to_dict(self):
        d = self.plan.to_dict()
        d["audio_id"] = "mutated"
        d["duration_ms"] = -1
        d["extra"] = 1
        self.assertEqual(self.plan.to_dict(), DEFAULT)
        self.assertIsNot(self.plan.to_dict(), self.plan.to_dict())
        rd = self.res.to_dict()
        rd["plan"]["operation"] = "mutated"
        rd["failures"].append("x")
        rd["ok"] = False
        self.assertEqual(self.res.plan.operation, "trim")
        self.assertEqual(self.res.to_dict()["plan"]["operation"], "trim")
        self.assertEqual(self.res.to_dict()["failures"], [])
        self.assertTrue(self.res.to_dict()["ok"])
        self.assertIsNot(self.res.to_dict(), self.res.to_dict())

    def test_24_failure_to_dict_and_failures_are_fresh(self):
        d = self.bad.to_dict()
        self.assertEqual(list(d), ["ok", "plan", "failures"])
        self.assertEqual(d["failures"][0]["code"], P + "INVALID_VALIDATION_RESULT")
        d["failures"][0]["code"] = "mutated"
        f = self.bad.failures
        f[0]["code"] = "mutated"
        self.assertEqual(self.bad.to_dict()["failures"][0]["code"], P + "INVALID_VALIDATION_RESULT")
        self.assertEqual(self.bad.failures[0]["code"], P + "INVALID_VALIDATION_RESULT")
        self.assertIsInstance(self.bad.failures, tuple)

    def test_25_equality_and_hash(self):
        other = create_audio_operation_plan(validated()[0])
        self.assertEqual(self.plan, other.plan)
        self.assertEqual(hash(self.plan), hash(other.plan))
        self.assertEqual(self.res, other)
        self.assertEqual(hash(self.res), hash(other))
        self.assertEqual(len({self.plan, other.plan}), 1)
        self.assertEqual(len({self.res, other}), 1)
        for field, value in (("audio_id", "other"), ("operation", "fade"), ("target_format", ""), ("duration_ms", 1001), ("sample_rate", 22051), ("quality", 71)):
            with self.subTest(field=field):
                diff = create_audio_operation_plan(validated(**{field: value})[0])
                self.assertNotEqual(self.plan, diff.plan)
                self.assertNotEqual(self.res, diff)
        self.assertNotEqual(self.plan, self.plan.to_dict())
        self.assertNotEqual(self.plan, None)
        self.assertNotEqual(self.plan, make_request())
        self.assertNotEqual(self.res, self.bad)
        self.assertEqual(self.bad, create_audio_operation_plan(5))
        self.assertEqual(hash(self.bad), hash(create_audio_operation_plan(5)))
        self.assertNotEqual(self.bad, create_audio_operation_plan(validate_audio_operation_request(None, None)))

    def test_26_copy_and_deepcopy_return_same_object(self):
        for obj in (self.res, self.plan, self.bad):
            self.assertIs(copy.copy(obj), obj)
            self.assertIs(copy.deepcopy(obj), obj)
            self.assertIs(copy.deepcopy({"k": [obj]})["k"][0], obj)

    def test_27_pickle_refused(self):
        for obj in (self.res, self.plan, self.bad):
            for proto in range(pickle.HIGHEST_PROTOCOL + 1):
                with self.subTest(obj=type(obj).__name__, proto=proto):
                    with self.assertRaises(TypeError):
                        pickle.dumps(obj, protocol=proto)

    def test_28_repr_is_stable(self):
        self.assertEqual(repr(self.plan), "AudioOperationPlan(audio_id='theme', operation='trim', target_format='mp3', duration_ms=1000, sample_rate=22050, quality=70)")
        self.assertEqual(repr(self.res), "AudioOperationPlanResult(ok=True, codes=[])")
        self.assertEqual(repr(self.bad), "AudioOperationPlanResult(ok=False, codes=['%sINVALID_VALIDATION_RESULT'])" % P)

    def test_29_plan_has_no_execution_surface(self):
        public = {n for n in dir(self.plan) if not n.startswith("_")}
        self.assertEqual(public, set(FIELDS) | {"to_dict"})
        public = {n for n in dir(self.res) if not n.startswith("_")}
        self.assertEqual(public, {"ok", "plan", "failures", "codes", "to_dict"})

    def test_30_plan_is_not_the_image_plan(self):
        from multimedia.image_operation_plan import ImageOperationPlan
        self.assertIsNot(AudioOperationPlan, ImageOperationPlan)
        self.assertNotEqual(self.plan, ImageOperationPlan)


class TestBoundaries(unittest.TestCase):
    def test_31_module_is_pure(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imported = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                imported += [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                imported.append("." * n.level + (n.module or ""))
        self.assertEqual(imported, [".audio_operation_validator"])
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"open", "os", "subprocess", "socket", "random", "time", "AudioAsset", "AudioAssetRegistry", "AudioOperationRequest"})
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertFalse(attrs & {"asset", "assets", "lookup", "audio_ids", "registry"})

    def test_32_earlier_production_modules_are_unaware_of_the_plan(self):
        for name in ("audio_asset.py", "audio_asset_registry.py", "audio_operation_request.py", "audio_operation_validator.py"):
            with open(os.path.join(PY_ROOT, "multimedia", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("audio_operation_plan", "AudioOperationPlan", "create_audio_operation_plan"):
                self.assertNotIn(token, text, name)

    def test_33_multimedia_package_holds_exactly_the_expected_files(self):
        names = sorted(f for f in os.listdir(os.path.join(PY_ROOT, "multimedia")) if f != "__pycache__")
        self.assertEqual([n for n in names if n.startswith("audio_")],
                         ["audio_asset.py", "audio_asset_registry.py", "audio_operation_batch.py", "audio_operation_batch_summary.py", "audio_operation_dispatcher.py", "audio_operation_executor.py", "audio_operation_metadata_executor.py", "audio_operation_output.py", "audio_operation_output_validator.py", "audio_operation_pipeline.py", "audio_operation_plan.py", "audio_operation_request.py", "audio_operation_validator.py"])
        self.assertEqual(len([n for n in names if n.startswith("image_")]), 13)
        with open(os.path.join(PY_ROOT, "multimedia", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_34_end_to_end_with_prior_prompts_only_through_public_apis(self):
        reg = make_registry(make_asset("jingle"), make_asset("theme"))
        req = make_request(audio_id="jingle", operation="convert", target_format="ogg", duration_ms=2500, sample_rate=48000, quality=100)
        plan = create_audio_operation_plan(validate_audio_operation_request(req, reg)).plan
        self.assertEqual(plan.to_dict(), req.to_dict())
        self.assertIs(type(plan), AudioOperationPlan)

    def test_35_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("AudioOperationPlan", "AudioOperationPlanResult", "create_audio_operation_plan", "AUDIO_OPERATION_PLAN_",
                       "INVALID_VALIDATION_RESULT", "VALIDATION_FAILED", "does NOT", "Prompt 764", "execution description"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
