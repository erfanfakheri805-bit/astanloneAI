"""Prompt 770 - Section 8 audio operation batch pipeline (`multimedia.audio_operation_batch`)."""
import ast
import builtins
import copy
import hashlib
import os
import pickle
import unittest
from unittest import mock

from multimedia import audio_operation_batch as b
from multimedia.audio_asset import create_audio_asset
from multimedia.audio_asset_registry import create_audio_asset_registry
from multimedia.audio_operation_batch import AudioOperationBatchResult, process_audio_operations
from multimedia.audio_operation_pipeline import AudioOperationPipelineResult, process_audio_operation
from multimedia.audio_operation_request import AudioOperationRequest, create_audio_operation_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section8_audio_operation_batch_prompt770.md")
MODULE = os.path.join(PY_ROOT, "multimedia", "audio_operation_batch.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
P = "AUDIO_OPERATION_BATCH_"
PP = "AUDIO_OPERATION_PIPELINE_"

BASE = {"audio_id": "theme", "operation": "metadata", "target_format": "mp3", "duration_ms": 1000, "sample_rate": 22050, "quality": 70}


def make_registry(*audio_ids):
    assets = []
    for audio_id in (audio_ids or ("theme", "jingle")):
        created = create_audio_asset({"audio_id": audio_id, "name": "N", "description": "", "format": "ogg", "duration_ms": 5000, "sample_rate": 44100})
        assert created.ok, created.failures
        assets.append(created.asset)
    registry = create_audio_asset_registry(assets)
    assert registry.ok, registry.failures
    return registry.registry


def make_request(**over):
    data = dict(BASE)
    data.update(over)
    created = create_audio_operation_request(data)
    assert created.ok, created.failures
    return created.request


class TestValidBatches(unittest.TestCase):
    def test_01_empty_list(self):
        res = process_audio_operations([], make_registry())
        self.assertIs(type(res), AudioOperationBatchResult)
        self.assertIs(res.ok, True)
        self.assertEqual(res.results, ())
        self.assertEqual(res.failures, ())
        self.assertEqual(res.codes(), [])
        self.assertEqual(res.to_dict(), {"ok": True, "results": [], "failures": []})

    def test_02_empty_tuple(self):
        res = process_audio_operations((), make_registry())
        self.assertIs(res.ok, True)
        self.assertEqual((res.results, res.failures), ((), ()))

    def test_03_one_successful_request(self):
        req, reg = make_request(), make_registry()
        res = process_audio_operations([req], reg)
        self.assertIs(res.ok, True)
        self.assertEqual(len(res.results), 1)
        self.assertIs(type(res.results[0]), AudioOperationPipelineResult)
        self.assertIs(res.results[0].ok, True)
        self.assertIs(res.results[0].request, req)
        self.assertEqual(res.failures, ())

    def test_04_multiple_successful_requests(self):
        reqs = [make_request(), make_request(audio_id="jingle", target_format="wav", duration_ms=64, sample_rate=32), make_request(duration_ms=1, sample_rate=1)]
        res = process_audio_operations(reqs, make_registry())
        self.assertIs(res.ok, True)
        self.assertEqual(len(res.results), 3)
        self.assertTrue(all(r.ok for r in res.results))
        self.assertEqual(res.codes(), [])

    def test_05_tuple_input_gives_the_same_result_as_list_input(self):
        reqs = [make_request(), make_request(audio_id="jingle")]
        reg = make_registry()
        self.assertEqual(process_audio_operations(reqs, reg), process_audio_operations(tuple(reqs), reg))

    def test_06_order_preservation(self):
        ids = ["jingle", "theme", "jingle", "theme", "jingle"]
        reqs = [make_request(audio_id=i, duration_ms=10 + n) for n, i in enumerate(ids)]
        res = process_audio_operations(reqs, make_registry())
        self.assertEqual([r.request.audio_id for r in res.results], ids)
        self.assertEqual([r.plan.duration_ms for r in res.results], [10, 11, 12, 13, 14])
        for req, r in zip(reqs, res.results):
            self.assertIs(r.request, req)

    def test_07_pipeline_called_once_per_request_in_order_with_the_exact_arguments(self):
        reqs = [make_request(), make_request(operation="trim"), make_request(audio_id="ghost")]
        reg = make_registry()
        with mock.patch.object(b, "process_audio_operation", wraps=process_audio_operation) as spy:
            res = process_audio_operations(reqs, reg)
        self.assertEqual(spy.call_count, 3)
        for call, req in zip(spy.call_args_list, reqs):
            self.assertEqual(len(call.args), 2)
            self.assertIs(call.args[0], req)
            self.assertIs(call.args[1], reg)
        self.assertEqual(len(res.results), 3)

    def test_08_exact_result_object_identity(self):
        reqs = [make_request(), make_request(operation="trim")]
        reg = make_registry()
        sentinels = [process_audio_operation(r, reg) for r in reqs]
        with mock.patch.object(b, "process_audio_operation", side_effect=sentinels):
            res = process_audio_operations(reqs, reg)
        self.assertEqual(len(res.results), 2)
        self.assertIs(res.results[0], sentinels[0])
        self.assertIs(res.results[1], sentinels[1])
        self.assertIs(type(res.results), tuple)

    def test_09_results_equal_the_individual_pipeline_results(self):
        reqs = [make_request(), make_request(operation="mix"), make_request(audio_id="ghost")]
        reg = make_registry()
        res = process_audio_operations(reqs, reg)
        self.assertEqual(res.results, tuple(process_audio_operation(r, reg) for r in reqs))

    def test_10_same_request_object_repeated_is_processed_each_time(self):
        req, reg = make_request(), make_registry()
        with mock.patch.object(b, "process_audio_operation", wraps=process_audio_operation) as spy:
            res = process_audio_operations([req, req, req], reg)
        self.assertEqual(spy.call_count, 3)
        self.assertEqual(len(res.results), 3)
        self.assertTrue(res.ok)


class TestMixedAndFailedOperations(unittest.TestCase):
    def test_20_mixed_success_and_failure(self):
        reqs = [make_request(), make_request(operation="trim"), make_request(audio_id="jingle"), make_request(audio_id="ghost")]
        res = process_audio_operations(reqs, make_registry())
        self.assertIs(res.ok, False)
        self.assertEqual(len(res.results), 4)
        self.assertEqual([r.ok for r in res.results], [True, False, True, False])
        self.assertEqual(res.codes(), [P + "OPERATION_FAILED", P + "OPERATION_FAILED"])
        self.assertEqual([f["field"] for f in res.failures], ["results[1]", "results[3]"])
        self.assertIn(PP + "DISPATCH_FAILED", res.failures[0]["message"])
        self.assertIn(PP + "VALIDATION_FAILED", res.failures[1]["message"])

    def test_21_processing_continues_after_a_failed_operation(self):
        reqs = [make_request(operation="trim"), make_request(), make_request(audio_id="ghost"), make_request(audio_id="jingle")]
        reg = make_registry()
        with mock.patch.object(b, "process_audio_operation", wraps=process_audio_operation) as spy:
            res = process_audio_operations(reqs, reg)
        self.assertEqual(spy.call_count, 4)
        self.assertEqual([r.ok for r in res.results], [False, True, False, True])

    def test_22_every_result_is_preserved_including_failed_ones_in_full_detail(self):
        reqs = [make_request(operation="trim"), make_request(audio_id="ghost")]
        res = process_audio_operations(reqs, make_registry())
        first, second = res.results
        self.assertIs(first.request, reqs[0])
        self.assertEqual(first.plan.operation, "trim")
        self.assertEqual(first.dispatch_result.codes(), ["AUDIO_OPERATION_DISPATCHER_UNSUPPORTED_OPERATION"])
        self.assertIsNone(first.output_validation)
        self.assertIs(second.request, reqs[1])
        self.assertIsNone(second.plan)
        self.assertEqual(second.codes(), [PP + "VALIDATION_FAILED"])

    def test_23_all_operations_failing(self):
        reqs = [make_request(operation="trim"), make_request(operation="mix"), make_request(audio_id="ghost")]
        res = process_audio_operations(reqs, make_registry())
        self.assertIs(res.ok, False)
        self.assertEqual(len(res.results), 3)
        self.assertEqual(res.codes(), [P + "OPERATION_FAILED"] * 3)
        self.assertEqual([f["field"] for f in res.failures], ["results[0]", "results[1]", "results[2]"])

    def test_24_one_failure_per_failing_entry_even_with_several_pipeline_codes(self):
        reg = make_registry()
        req = make_request()
        two_codes = process_audio_operation(None, None)
        self.assertEqual(len(two_codes.codes()), 2)
        with mock.patch.object(b, "process_audio_operation", side_effect=[two_codes]):
            res = process_audio_operations([req], reg)
        self.assertEqual(res.codes(), [P + "OPERATION_FAILED"])
        self.assertIs(res.results[0], two_codes)
        for code in two_codes.codes():
            self.assertIn(code, res.failures[0]["message"])

    def test_25_ok_requires_every_result_ok(self):
        reg = make_registry()
        self.assertTrue(process_audio_operations([make_request()] * 3, reg).ok)
        self.assertFalse(process_audio_operations([make_request()] * 3 + [make_request(operation="x")], reg).ok)
        self.assertFalse(process_audio_operations([make_request(operation="x")] + [make_request()] * 3, reg).ok)

    def test_26_operation_failure_does_not_reinterpret_pipeline_codes(self):
        res = process_audio_operations([make_request(operation="trim")], make_registry())
        self.assertEqual(res.results[0].codes(), [PP + "DISPATCH_FAILED"])
        self.assertEqual(res.codes(), [P + "OPERATION_FAILED"])
        self.assertEqual(list(res.failures[0]), ["code", "field", "message", "context"])
        self.assertIsNone(res.failures[0]["context"])


class TestInvalidInputs(unittest.TestCase):
    def assert_nothing_ran(self, res, spy):
        spy.assert_not_called()
        self.assertIs(res.ok, False)
        self.assertEqual(res.results, ())

    def test_30_invalid_collection_types(self):
        reqs = [make_request()]
        bad = (None, 0, "", "abc", b"", {}, {0: make_request()}, set(), frozenset(), object(), make_request(), iter(reqs), (r for r in reqs),
               range(3), bytearray(), float("nan"), True)
        for value in bad:
            with self.subTest(value=type(value).__name__):
                with mock.patch.object(b, "process_audio_operation") as spy:
                    res = process_audio_operations(value, make_registry())
                self.assert_nothing_ran(res, spy)
                self.assertEqual(res.codes(), [P + "INVALID_COLLECTION"])
                self.assertEqual(res.failures[0]["field"], "requests")

    def test_31_list_and_tuple_subclasses_are_rejected(self):
        class L(list):
            pass

        class T(tuple):
            pass

        for value in (L([make_request()]), T([make_request()]), L()):
            with self.subTest(value=type(value).__name__):
                with mock.patch.object(b, "process_audio_operation") as spy:
                    res = process_audio_operations(value, make_registry())
                self.assert_nothing_ran(res, spy)
                self.assertEqual(res.codes(), [P + "INVALID_COLLECTION"])

    def test_32_invalid_request_item_reports_the_index_in_the_field(self):
        reqs = [make_request(), "theme", make_request()]
        with mock.patch.object(b, "process_audio_operation") as spy:
            res = process_audio_operations(reqs, make_registry())
        self.assert_nothing_ran(res, spy)
        self.assertEqual(res.codes(), [P + "INVALID_REQUEST"])
        self.assertEqual(res.failures[0]["field"], "requests[1]")
        self.assertIn("requests[1]", res.failures[0]["message"])

    def test_33_every_invalid_item_is_reported_in_input_order_and_nothing_is_called(self):
        reqs = [None, make_request(), dict(BASE), 5, make_request(), AudioOperationRequest]
        with mock.patch.object(b, "process_audio_operation") as spy:
            res = process_audio_operations(reqs, make_registry())
        self.assert_nothing_ran(res, spy)
        self.assertEqual(res.codes(), [P + "INVALID_REQUEST"] * 4)
        self.assertEqual([f["field"] for f in res.failures], ["requests[0]", "requests[2]", "requests[3]", "requests[5]"])

    def test_34_invalid_item_in_a_tuple(self):
        with mock.patch.object(b, "process_audio_operation") as spy:
            res = process_audio_operations((make_request(), None), make_registry())
        self.assert_nothing_ran(res, spy)
        self.assertEqual([f["field"] for f in res.failures], ["requests[1]"])

    def test_35_look_alike_and_subclass_items_are_rejected(self):
        class Fake:
            audio_id = "theme"
            operation = "metadata"
            target_format = "mp3"
            duration_ms = 1
            sample_rate = 1
            quality = 1

            def to_dict(self):
                return dict(BASE)

        with mock.patch.object(b, "process_audio_operation") as spy:
            res = process_audio_operations([Fake()], make_registry())
        self.assert_nothing_ran(res, spy)
        self.assertEqual(res.codes(), [P + "INVALID_REQUEST"])

    def test_36_invalid_registry(self):
        reqs = [make_request(), make_request()]
        for value in (None, {}, [], "registry", 0, object(), make_registry().to_dict()):
            with self.subTest(value=type(value).__name__):
                with mock.patch.object(b, "process_audio_operation") as spy:
                    res = process_audio_operations(reqs, value)
                self.assert_nothing_ran(res, spy)
                self.assertEqual(res.codes(), [P + "INVALID_REGISTRY"])
                self.assertEqual(res.failures[0]["field"], "audio_registry")

    def test_37_invalid_registry_with_empty_collection_is_still_invalid(self):
        res = process_audio_operations([], None)
        self.assertEqual((res.ok, res.results, res.codes()), (False, (), [P + "INVALID_REGISTRY"]))

    def test_38_collection_and_registry_both_invalid_are_reported_together_collection_first(self):
        res = process_audio_operations(None, None)
        self.assertEqual((res.ok, res.results), (False, ()))
        self.assertEqual(res.codes(), [P + "INVALID_COLLECTION", P + "INVALID_REGISTRY"])
        self.assertEqual([f["field"] for f in res.failures], ["requests", "audio_registry"])

    def test_39_invalid_registry_and_invalid_items_are_reported_together(self):
        with mock.patch.object(b, "process_audio_operation") as spy:
            res = process_audio_operations([make_request(), None], "nope")
        self.assert_nothing_ran(res, spy)
        self.assertEqual(res.codes(), [P + "INVALID_REGISTRY", P + "INVALID_REQUEST"])
        self.assertEqual([f["field"] for f in res.failures], ["audio_registry", "requests[1]"])

    def test_40_invalid_input_never_calls_the_pipeline_even_for_the_valid_items(self):
        with mock.patch.object(b, "process_audio_operation") as spy:
            process_audio_operations([make_request(), make_request(), None], make_registry())
            process_audio_operations([make_request()], None)
            process_audio_operations(None, make_registry())
        spy.assert_not_called()

    def test_41_never_raises_for_odd_inputs(self):
        odd = (None, 0, "", b"", [], {}, object(), float("nan"), AudioOperationBatchResult, [None], [object()], ((),), [[]])
        for a in odd:
            for r in odd:
                with self.subTest(a=type(a).__name__, r=type(r).__name__):
                    res = process_audio_operations(a, r)
                    self.assertIs(res.ok, False)
                    self.assertEqual(res.results, ())
                    self.assertTrue(set(res.codes()) <= {P + "INVALID_COLLECTION", P + "INVALID_REGISTRY", P + "INVALID_REQUEST"})


class TestInvalidItemContext(unittest.TestCase):
    def test_45_invalid_item_is_the_exact_failure_context(self):
        bad = [object(), "theme", dict(BASE), None, 5]
        reqs = [bad[0], make_request(), bad[1], bad[2], bad[3], make_request(), bad[4]]
        res = process_audio_operations(reqs, make_registry())
        self.assertEqual(res.codes(), [P + "INVALID_REQUEST"] * 5)
        self.assertEqual([f["field"] for f in res.failures], ["requests[0]", "requests[2]", "requests[3]", "requests[4]", "requests[6]"])
        for failure, item in zip(res.failures, bad):
            self.assertIs(failure["context"], item)

    def test_46_context_identity_is_preserved_on_every_call_and_not_copied(self):
        item = {"mutable": []}
        res = process_audio_operations([item], make_registry())
        self.assertIs(res.failures[0]["context"], item)
        self.assertIs(res.failures[0]["context"], res.failures[0]["context"])
        self.assertIsNot(res.failures[0], res.failures[0])
        item["mutable"].append(1)
        self.assertEqual(res.failures[0]["context"], {"mutable": [1]})

    def test_47_context_follows_original_index_when_valid_items_surround_it(self):
        bad = ()
        res = process_audio_operations([make_request(), bad, make_request()], make_registry())
        self.assertEqual([(f["field"], f["context"]) for f in res.failures], [("requests[1]", ())])
        self.assertIs(res.failures[0]["context"], bad)

    def test_48_other_failures_have_no_context(self):
        for reqs, reg in ((None, None), ([], None), ([make_request(operation="trim")], make_registry())):
            for f in process_audio_operations(reqs, reg).failures:
                self.assertIsNone(f["context"])

    def test_49_unhashable_and_hostile_contexts_are_never_hashed_or_compared_by_value(self):
        class Hostile:
            __hash__ = None

            def __eq__(self, other):
                raise AssertionError("context __eq__ called")

        item = Hostile()
        a = process_audio_operations([item], make_registry())
        c = process_audio_operations([item], make_registry())
        self.assertEqual(a, c)
        self.assertEqual(hash(a), hash(c))
        other = process_audio_operations([Hostile()], make_registry())
        self.assertNotEqual(a, other)
        self.assertEqual(hash(a), hash(other))
        self.assertEqual(a.to_dict()["failures"], [{"code": P + "INVALID_REQUEST", "field": "requests[0]", "message": a.failures[0]["message"]}])
        self.assertIn("Hostile", a.failures[0]["message"])


class TestFailureCodes(unittest.TestCase):
    def test_50_only_the_four_codes_exist(self):
        self.assertEqual(b.FAILURE_CODES, (P + "INVALID_COLLECTION", P + "INVALID_REQUEST", P + "INVALID_REGISTRY", P + "OPERATION_FAILED"))
        self.assertEqual(len(set(b.FAILURE_CODES)), 4)

    def test_51_every_produced_code_is_one_of_the_four(self):
        reg = make_registry()
        seen = set()
        for reqs, rg in ((None, None), ([None], reg), ([], None), ([make_request(operation="x")], reg), ([make_request()], reg)):
            seen.update(process_audio_operations(reqs, rg).codes())
        self.assertEqual(seen, set(b.FAILURE_CODES))

    def test_52_failures_are_fresh_four_key_dicts(self):
        res = process_audio_operations(None, None)
        for f in res.failures:
            self.assertEqual(list(f), ["code", "field", "message", "context"])
            self.assertTrue(all(type(f[k]) is str for k in ("code", "field", "message")))
            self.assertIsNone(f["context"])
        res.failures[0]["code"] = "tampered"
        self.assertEqual(res.codes()[0], P + "INVALID_COLLECTION")
        self.assertIsNot(res.failures[0], res.failures[0])
        self.assertIs(type(res.failures), tuple)


class TestNoMutationAndDeterminism(unittest.TestCase):
    def test_60_no_mutation_of_the_collection_requests_or_registry(self):
        reqs = [make_request(), make_request(operation="trim"), make_request(audio_id="ghost")]
        reg = make_registry()
        snapshot = (list(reqs), [r.to_dict() for r in reqs], [hash(r) for r in reqs], reg.to_dict(), hash(reg))
        for _ in range(3):
            process_audio_operations(reqs, reg)
            process_audio_operations(tuple(reqs), reg)
        self.assertEqual(len(reqs), 3)
        for before, after in zip(snapshot[0], reqs):
            self.assertIs(before, after)
        self.assertEqual(snapshot[1:], ([r.to_dict() for r in reqs], [hash(r) for r in reqs], reg.to_dict(), hash(reg)))

    def test_61_input_collection_is_not_retained(self):
        reqs = [make_request()]
        res = process_audio_operations(reqs, make_registry())
        reqs.append(make_request(audio_id="jingle"))
        reqs.clear()
        self.assertEqual(len(res.results), 1)
        self.assertIs(type(res.results), tuple)

    def test_62_invalid_input_does_not_mutate_the_collection(self):
        reqs = [make_request(), None]
        process_audio_operations(reqs, make_registry())
        self.assertEqual(len(reqs), 2)
        self.assertIsNone(reqs[1])

    def test_63_deterministic_repeated_calls(self):
        reqs = [make_request(), make_request(operation="trim"), make_request(audio_id="ghost")]
        reg = make_registry()
        results = [process_audio_operations(reqs, reg) for _ in range(5)]
        self.assertTrue(all(r == results[0] for r in results))
        self.assertEqual(len({hash(r) for r in results}), 1)
        self.assertEqual(len({repr(r.to_dict()) for r in results}), 1)
        bad = process_audio_operations(None, None)
        self.assertEqual([process_audio_operations(None, None) for _ in range(5)], [bad] * 5)

    def test_64_equal_inputs_built_separately_give_equal_results(self):
        a = process_audio_operations([make_request(), make_request(operation="x")], make_registry())
        c = process_audio_operations([make_request(), make_request(operation="x")], make_registry())
        self.assertIsNot(a, c)
        self.assertEqual(a, c)
        self.assertEqual(hash(a), hash(c))

    def test_65_fresh_to_dict(self):
        res = process_audio_operations([make_request(), make_request(operation="trim")], make_registry())
        d1, d2 = res.to_dict(), res.to_dict()
        self.assertEqual(list(d1), ["ok", "results", "failures"])
        self.assertEqual(d1, d2)
        self.assertIsNot(d1, d2)
        self.assertIsNot(d1["results"], d2["results"])
        self.assertIsNot(d1["results"][0], d2["results"][0])
        self.assertIsNot(d1["failures"], d2["failures"])
        self.assertEqual(d1["results"], [r.to_dict() for r in res.results])
        d1["results"][0]["plan"]["duration_ms"] = -1
        d1["results"].append("x")
        d1["failures"].append("x")
        d1["ok"] = True
        self.assertEqual(res.to_dict(), d2)
        self.assertEqual(res.results[0].plan.duration_ms, 1000)
        self.assertFalse(res.ok)

    def test_66_to_dict_of_invalid_input(self):
        d = process_audio_operations([None], None).to_dict()
        self.assertEqual((d["ok"], d["results"]), (False, []))
        self.assertEqual([f["code"] for f in d["failures"]], [P + "INVALID_REGISTRY", P + "INVALID_REQUEST"])


class TestResultModel(unittest.TestCase):
    def setUp(self):
        self.ok = process_audio_operations([make_request()], make_registry())
        self.bad = process_audio_operations([make_request(operation="trim")], make_registry())
        self.invalid = process_audio_operations(None, make_registry())

    def test_70_equality_and_hash(self):
        self.assertEqual(self.ok, process_audio_operations([make_request()], make_registry()))
        self.assertNotEqual(self.ok, self.bad)
        self.assertNotEqual(self.bad, self.invalid)
        self.assertNotEqual(self.ok, self.ok.to_dict())
        self.assertNotEqual(self.ok, None)
        self.assertEqual(len({self.ok, process_audio_operations([make_request()], make_registry()), self.bad, self.invalid}), 3)
        self.assertNotEqual(process_audio_operations([], make_registry()), self.ok)
        self.assertNotEqual(process_audio_operations([make_request(), make_request()], make_registry()), self.ok)

    def test_71_order_matters_for_equality(self):
        reg = make_registry()
        a, c = make_request(duration_ms=1), make_request(duration_ms=2)
        self.assertNotEqual(process_audio_operations([a, c], reg), process_audio_operations([c, a], reg))

    def test_72_immutable(self):
        for name in ("ok", "results", "failures", "extra"):
            with self.subTest(name=name):
                with self.assertRaises(AttributeError):
                    setattr(self.ok, name, 1)
                with self.assertRaises(AttributeError):
                    delattr(self.ok, name)
        self.assertFalse(hasattr(self.ok, "__dict__"))
        with self.assertRaises(TypeError):
            self.ok.results[0] = None

    def test_73_no_direct_construction_and_no_subclassing(self):
        with self.assertRaises(TypeError):
            AudioOperationBatchResult()
        with self.assertRaises(TypeError):
            AudioOperationBatchResult(object(), (), ())
        with self.assertRaises(TypeError):
            AudioOperationBatchResult(None, (), ())
        with self.assertRaises(TypeError):
            type("Sub", (AudioOperationBatchResult,), {})

    def test_74_copy_and_deepcopy_return_the_same_object(self):
        for res in (self.ok, self.bad, self.invalid):
            self.assertIs(copy.copy(res), res)
            self.assertIs(copy.deepcopy(res), res)
            self.assertIs(copy.deepcopy([res])[0], res)

    def test_75_pickle_refused(self):
        for res in (self.ok, self.bad, self.invalid):
            for proto in range(0, pickle.HIGHEST_PROTOCOL + 1):
                with self.subTest(proto=proto):
                    with self.assertRaises(TypeError):
                        pickle.dumps(res, protocol=proto)

    def test_76_repr(self):
        self.assertEqual(repr(self.ok), "AudioOperationBatchResult(ok=True, results=1, codes=[])")
        self.assertEqual(repr(self.bad), "AudioOperationBatchResult(ok=False, results=1, codes=['%sOPERATION_FAILED'])" % P)
        self.assertEqual(repr(self.invalid), "AudioOperationBatchResult(ok=False, results=0, codes=['%sINVALID_COLLECTION'])" % P)


class TestBoundaries(unittest.TestCase):
    def test_80_no_filesystem_access(self):
        def refuse(*a, **k):
            raise AssertionError("filesystem access attempted")

        reg = make_registry()
        reqs = [make_request(), make_request(operation="trim"), make_request(audio_id="ghost")]
        with mock.patch.object(builtins, "open", refuse), mock.patch("os.listdir", refuse), mock.patch("os.stat", refuse), \
                mock.patch("os.scandir", refuse), mock.patch("os.walk", refuse), mock.patch("os.path.exists", refuse), \
                mock.patch("os.path.isfile", refuse), mock.patch("io.open", refuse):
            self.assertTrue(process_audio_operations([], reg).ok)
            self.assertTrue(process_audio_operations([make_request()], reg).ok)
            self.assertEqual(process_audio_operations(reqs, reg).codes(), [P + "OPERATION_FAILED"] * 2)
            self.assertEqual(process_audio_operations(None, None).codes(), [P + "INVALID_COLLECTION", P + "INVALID_REGISTRY"])
            self.assertEqual(process_audio_operations([None], reg).codes(), [P + "INVALID_REQUEST"])

    def test_81_module_uses_only_the_pipeline_and_the_two_type_checks_and_does_no_io(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertTrue(all(isinstance(n, ast.ImportFrom) and n.level == 1 for n in imports))
        self.assertEqual([(n.module, sorted(a.name for a in n.names)) for n in imports], [
            ("audio_asset_registry", ["AudioAssetRegistry"]),
            ("audio_operation_pipeline", ["process_audio_operation"]),
            ("audio_operation_request", ["AudioOperationRequest"])])
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"open", "os", "io", "subprocess", "socket", "random", "time", "pathlib", "threading", "asyncio", "concurrent",
                                  "multiprocessing", "sched", "AudioAsset", "create_audio_operation_plan", "dispatch_audio_operation",
                                  "validate_audio_operation_request", "validate_audio_operation_output", "execute_audio_operation",
                                  "execute_audio_operation_metadata", "bytes", "bytearray", "memoryview", "Audio", "wave", "pydub", "numpy"})
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertFalse(attrs & {"read", "write", "trim", "convert", "mix", "decode", "lower", "upper", "casefold", "strip", "sleep",
                                  "audio_id", "operation", "target_format", "duration_ms", "sample_rate", "quality"})
        mutable = [n for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.value, (ast.List, ast.Dict, ast.Set))]
        self.assertEqual(mutable, [])

    def test_82_earlier_modules_are_unaware_of_the_batch(self):
        for name in ("audio_asset.py", "audio_asset_registry.py", "audio_operation_request.py", "audio_operation_validator.py",
                     "audio_operation_plan.py", "audio_operation_executor.py", "audio_operation_output.py",
                     "audio_operation_output_validator.py", "audio_operation_metadata_executor.py", "audio_operation_dispatcher.py",
                     "audio_operation_pipeline.py"):
            with open(os.path.join(PY_ROOT, "multimedia", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("audio_operation_batch", "process_audio_operations", "AudioOperationBatchResult"):
                self.assertNotIn(token, text, name)

    def test_83_not_wired_into_the_runtime(self):
        for folder in ("core", "planning", "agent", "game_creation"):
            for root, _dirs, files in os.walk(os.path.join(PY_ROOT, folder)):
                for f in files:
                    if f.endswith(".py"):
                        with open(os.path.join(root, f), encoding="utf-8") as fh:
                            text = fh.read()
                        self.assertNotIn("audio_operation_batch", text, os.path.join(root, f))
        with open(os.path.join(PY_ROOT, "multimedia", "__init__.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "")

    def test_84_multimedia_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "multimedia")) if f != "__pycache__"),
                         ["__init__.py", "audio_asset.py", "audio_asset_registry.py", "audio_operation_batch.py", "audio_operation_batch_summary.py", "audio_operation_dispatcher.py",
                          "audio_operation_executor.py", "audio_operation_metadata_executor.py", "audio_operation_output.py",
                          "audio_operation_output_validator.py", "audio_operation_pipeline.py", "audio_operation_plan.py",
                          "audio_operation_request.py", "audio_operation_validator.py",
                          "image_asset.py", "image_asset_registry.py", "image_operation_batch.py", "image_operation_batch_summary.py",
                          "image_operation_dispatcher.py", "image_operation_executor.py", "image_operation_metadata_executor.py",
                          "image_operation_output.py", "image_operation_output_validator.py", "image_operation_pipeline.py",
                          "image_operation_plan.py", "image_operation_request.py", "image_operation_validator.py"])

    def test_85_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("AudioOperationBatchResult", "process_audio_operations", "process_audio_operation", P, "INVALID_COLLECTION",
                       "INVALID_REQUEST", "INVALID_REGISTRY", "OPERATION_FAILED", "requests[", "results[", "does NOT", "Prompt 769",
                       "Prompt 771", "has **not** been started"):
            self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
