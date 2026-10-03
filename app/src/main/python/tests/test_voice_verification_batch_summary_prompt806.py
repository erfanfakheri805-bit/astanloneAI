"""Prompt 806 - Section 10 voice verification batch summary (`voice.voice_verification_batch_summary`)."""
import ast
import copy
import gc
import hashlib
import os
import pickle
import sys
import unittest
from unittest import mock

from voice import voice_verification_batch_summary as vs
from voice.voice_verification_batch import VoiceVerificationBatchResult, run_voice_verification_batch
from voice.voice_verification_batch_summary import VoiceVerificationBatchSummary, create_voice_verification_batch_summary
from voice.voice_verification_plan import create_voice_verification_plan
from voice.voice_verification_request import create_voice_verification_request
from voice.voice_verification_request_validator import validate_voice_verification_request
from voice.voice_verification_result import VoiceVerificationResult, create_voice_verification_result

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section10_voice_verification_batch_summary_prompt806.md")
MODULE = os.path.join(PY_ROOT, "voice", "voice_verification_batch_summary.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
INVALID = "VOICE_VERIFICATION_BATCH_SUMMARY_INVALID_RESULT"
MALFORMED = "VOICE_VERIFICATION_BATCH_SUMMARY_MALFORMED_RESULT"
BATCH_TARGET = "voice.voice_verification_batch.run_voice_verification_pipeline"
BATCH_SHA = "a156b6ac8cfac532b555b630d21f2e315c8d14936009fb7308923711fc4c4f4a"
ENROLL_SUMMARY_SHA = "59d676c57f385c044aaa5502f48914dae64fc231499109d7b66527ebadef5a80"


def make_plan(n=1):
    req = create_voice_verification_request({"request_id": "verify_%d" % n, "profile_id": "voice_%d" % n, "verification_mode": "standard"})
    assert req.ok
    res = create_voice_verification_plan(validate_voice_verification_request(req.request))
    assert res.ok
    return res.plan


def make_out(status="NOT_IMPLEMENTED", code="C1", n=1, metadata=None):
    r = create_voice_verification_result({"request_id": "r%d" % n, "profile_id": "p%d" % n, "status": status, "code": code, "metadata": metadata})
    assert r.ok, r.codes()
    return r.result


def make_batch(outs):
    """A real VoiceVerificationBatchResult whose outputs are exactly `outs` (pipeline mocked to return them in order)."""
    plans = tuple(make_plan(i) for i in range(len(outs)))
    with mock.patch(BATCH_TARGET, side_effect=list(outs)):
        res = run_voice_verification_batch(plans)
    assert type(res) is VoiceVerificationBatchResult
    return res


def forged(outputs, failures):
    """An exact-type batch result with arbitrary (possibly malformed) internals, built without going through the factory."""
    b = object.__new__(VoiceVerificationBatchResult)
    object.__setattr__(b, "_outputs", outputs)
    object.__setattr__(b, "_failures", failures)
    return b


class Spoof(object):
    @property
    def __class__(self):
        return VoiceVerificationBatchResult


class TestExactType(unittest.TestCase):
    def test_1_non_batch_results_rejected(self):
        out = make_out()
        class Look(object):
            ok, outputs, failures = True, (), ()
        for v in (None, {}, [], (), "x", 1, True, out, make_plan(), Look(), Spoof(), make_batch([out]).outputs):
            s = create_voice_verification_batch_summary(v)
            self.assertIs(type(s), VoiceVerificationBatchSummary)
            self.assertEqual(s.codes(), [INVALID])
            self.assertFalse(s.success)
            self.assertEqual((s.output_count, s.failure_count, s.total_count, s.status_counts, s.code_counts), (0, 0, 0, {}, {}))

    def test_2_input_is_not_read_when_wrong_type(self):
        class Boom(object):
            def __getattribute__(self, name):
                if name == "__class__":
                    return object.__getattribute__(self, name)
                raise AssertionError("read " + name)
        self.assertEqual(create_voice_verification_batch_summary(Boom()).codes(), [INVALID])

    def test_3_rejection_is_equal_but_fresh(self):
        a, b = create_voice_verification_batch_summary(None), create_voice_verification_batch_summary(5)
        self.assertEqual(a, b)
        self.assertIsNot(a, b)

    def test_4_exact_batch_result_accepted(self):
        s = create_voice_verification_batch_summary(make_batch([make_out()]))
        self.assertEqual(s.codes(), [])


class TestMalformed(unittest.TestCase):
    def check(self, batch):
        s = create_voice_verification_batch_summary(batch)
        self.assertEqual(s.codes(), [MALFORMED])
        self.assertFalse(s.success)
        self.assertEqual((s.output_count, s.failure_count, s.total_count, s.status_counts, s.code_counts), (0, 0, 0, {}, {}))

    def test_5_output_not_exact_result(self):
        class Look(object):
            status, code = "S", "C"
        for bad in (None, "x", 1, {}, Look(), make_plan()):
            self.check(forged((make_out(), bad), ()))

    def test_6_non_tuple_outputs(self):
        for bad in (None, [make_out()], "abc", 5, {make_out()}):
            self.check(forged(bad, ()))

    def test_7_outputs_and_failures_together(self):
        self.check(forged((make_out(),), (("C", "plans[0]", "m"),)))

    def test_8_unreadable_failures(self):
        self.check(forged((), 5))
        self.check(forged((), None))

    def test_9_non_str_status_or_code(self):
        o = make_out()
        class S(str):
            pass
        for status, code in ((5, "C"), ("S", None), (S("S"), "C"), ("S", S("C")), (None, None)):
            bad = object.__new__(VoiceVerificationResult)
            for k, v in (("_request_id", "r"), ("_profile_id", "p"), ("_status", status), ("_code", code), ("_items", None)):
                object.__setattr__(bad, k, v)
            self.check(forged((o, bad), ()))

    def test_10_first_problem_rejects_everything(self):
        self.check(forged((make_out(), make_out(status="OTHER"), None), ()))

    def test_11_never_raises_for_raising_output(self):
        bad = object.__new__(VoiceVerificationResult)   # slots unset -> status read raises AttributeError
        self.check(forged((bad,), ()))


class TestCounts(unittest.TestCase):
    def test_12_counts_for_valid_batch(self):
        outs = [make_out("A", "X", 1), make_out("B", "X", 2), make_out("A", "Y", 3), make_out("A", "X", 4)]
        s = create_voice_verification_batch_summary(make_batch(outs))
        self.assertEqual((s.output_count, s.failure_count, s.total_count, s.success), (4, 0, 4, True))
        self.assertEqual(s.status_counts, {"A": 3, "B": 1})
        self.assertEqual(s.code_counts, {"X": 3, "Y": 1})

    def test_13_empty_valid_batch(self):
        s = create_voice_verification_batch_summary(run_voice_verification_batch(()))
        self.assertEqual((s.output_count, s.failure_count, s.total_count, s.success), (0, 0, 0, True))
        self.assertEqual((s.status_counts, s.code_counts, s.codes()), ({}, {}, []))

    def test_14_rejected_batch_counts_failures(self):
        b = run_voice_verification_batch((None, make_plan(), 3))
        self.assertFalse(b.ok)
        s = create_voice_verification_batch_summary(b)
        self.assertEqual((s.output_count, s.failure_count, s.total_count, s.success), (0, 2, 2, False))
        self.assertEqual(s.codes(), [])
        self.assertEqual((s.status_counts, s.code_counts), ({}, {}))

    def test_15_non_collection_batch(self):
        s = create_voice_verification_batch_summary(run_voice_verification_batch([]))
        self.assertEqual((s.output_count, s.failure_count, s.total_count, s.success), (0, 1, 1, False))

    def test_16_total_equals_output_plus_failure(self):
        for b in (run_voice_verification_batch(()), run_voice_verification_batch((None,)), run_voice_verification_batch(None),
                  make_batch([make_out(), make_out(n=2)]), run_voice_verification_batch((make_plan(), make_plan(2)))):
            s = create_voice_verification_batch_summary(b)
            self.assertEqual(s.total_count, s.output_count + s.failure_count)
            self.assertEqual(sum(s.status_counts.values()), s.output_count)
            self.assertEqual(sum(s.code_counts.values()), s.output_count)

    def test_17_real_pipeline_batch(self):
        b = run_voice_verification_batch((make_plan(1), make_plan(2)))
        s = create_voice_verification_batch_summary(b)
        self.assertTrue(s.success)
        self.assertEqual(s.output_count, 2)
        self.assertEqual(sum(s.status_counts.values()), 2)

    def test_18_success_follows_batch_ok_only(self):
        s = create_voice_verification_batch_summary(make_batch([make_out("REJECTED", "BAD")]))
        self.assertTrue(s.success)
        self.assertEqual(s.status_counts, {"REJECTED": 1})

    def test_19_keys_compared_exactly(self):
        s = create_voice_verification_batch_summary(make_batch([make_out("a", "x"), make_out("A", "x", 2), make_out("a ", "x", 3)]))
        self.assertEqual(s.status_counts, {"A": 1, "a": 1, "a ": 1})


class TestDeterministicMappings(unittest.TestCase):
    def test_20_sorted_by_key_not_first_seen(self):
        outs = [make_out("Z", "z", 1), make_out("B", "b", 2), make_out("M", "m", 3), make_out("A", "a", 4)]
        s = create_voice_verification_batch_summary(make_batch(outs))
        self.assertEqual(list(s.status_counts), ["A", "B", "M", "Z"])
        self.assertEqual(list(s.code_counts), ["a", "b", "m", "z"])
        self.assertEqual(list(s.to_dict()["status_counts"]), ["A", "B", "M", "Z"])

    def test_21_same_multiset_gives_equal_summary(self):
        outs = [make_out("Z", "z", 1), make_out("B", "b", 2), make_out("Z", "b", 3)]
        a = create_voice_verification_batch_summary(make_batch(outs))
        b = create_voice_verification_batch_summary(make_batch(list(reversed(outs))))
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(list(a.code_counts.items()), list(b.code_counts.items()))

    def test_22_mappings_are_fresh_plain_dicts(self):
        s = create_voice_verification_batch_summary(make_batch([make_out("A", "x")]))
        m = s.status_counts
        self.assertIs(type(m), dict)
        m["A"] = 99
        m["new"] = 1
        s.code_counts.clear()
        self.assertEqual(s.status_counts, {"A": 1})
        self.assertEqual(s.code_counts, {"x": 1})
        self.assertIsNot(s.status_counts, s.status_counts)

    def test_23_to_dict_shape_and_freshness(self):
        s = create_voice_verification_batch_summary(make_batch([make_out("A", "x")]))
        d = s.to_dict()
        self.assertEqual(list(d), ["output_count", "failure_count", "total_count", "status_counts", "code_counts", "success", "codes"])
        d["status_counts"]["A"] = 5
        d["codes"].append("x")
        self.assertEqual(s.to_dict()["status_counts"], {"A": 1})
        self.assertEqual(s.codes(), [])


class TestImmutability(unittest.TestCase):
    def setUp(self):
        self.s = create_voice_verification_batch_summary(make_batch([make_out()]))

    def test_24_attributes_immutable(self):
        for name in ("output_count", "failure_count", "total_count", "status_counts", "code_counts", "success", "_output_count", "extra"):
            with self.assertRaises(AttributeError):
                setattr(self.s, name, 1)
            with self.assertRaises(AttributeError):
                delattr(self.s, name)

    def test_25_no_dict_no_direct_build_no_subclass(self):
        self.assertFalse(hasattr(self.s, "__dict__"))
        with self.assertRaises(TypeError):
            VoiceVerificationBatchSummary(0, 0, 0, (), (), True, ())
        with self.assertRaises(TypeError):
            VoiceVerificationBatchSummary(object(), 0, 0, 0, (), (), True, ())
        with self.assertRaises(TypeError):
            class S(VoiceVerificationBatchSummary):
                pass

    def test_26_copy_pickle_equality(self):
        self.assertIs(copy.copy(self.s), self.s)
        self.assertIs(copy.deepcopy(self.s), self.s)
        with self.assertRaises(TypeError):
            pickle.dumps(self.s)
        self.assertNotEqual(self.s, ())
        self.assertEqual(self.s, create_voice_verification_batch_summary(make_batch([make_out()])))
        self.assertNotEqual(self.s, create_voice_verification_batch_summary(make_batch([make_out("Q")])))

    def test_27_exactly_the_six_fields(self):
        public = sorted(n for n in dir(self.s) if not n.startswith("_") and not callable(getattr(self.s, n)))
        self.assertEqual(public, sorted(["output_count", "failure_count", "total_count", "status_counts", "code_counts", "success"]))


class TestNonRetentionAndMetadata(unittest.TestCase):
    def test_28_batch_and_outputs_not_retained(self):
        outs = [make_out("A", "x", 1), make_out("B", "y", 2)]
        batch = make_batch(outs)
        refs = [sys.getrefcount(batch)] + [sys.getrefcount(o) for o in outs]
        s = create_voice_verification_batch_summary(batch)
        after = [sys.getrefcount(batch)] + [sys.getrefcount(o) for o in outs]
        self.assertEqual(refs, after)
        for r in gc.get_referrers(batch):
            self.assertIsNot(r, s)
        held = [getattr(s, "_" + n) for n in ("output_count", "failure_count", "total_count", "status_counts", "code_counts", "success", "codes")]
        def ok(v):
            return type(v) in (int, bool, str) or (type(v) is tuple and all(ok(i) for i in v))
        self.assertTrue(all(ok(v) for v in held), held)

    def test_29_metadata_is_never_interpreted(self):
        class Trap(object):
            def __getattribute__(self, name):
                raise AssertionError("metadata touched")
            def __eq__(self, other):
                raise AssertionError("metadata compared")
            __hash__ = None
        outs = [make_out("A", "x", 1, metadata={"k": Trap()}), make_out("A", "x", 2, metadata={"verified": True, "status": "HACK", "code": "HACK"})]
        s = create_voice_verification_batch_summary(make_batch(outs))
        self.assertEqual(s.status_counts, {"A": 2})
        self.assertEqual(s.code_counts, {"x": 2})

    def test_30_metadata_property_never_read(self):
        outs = [make_out("A", "x")]
        batch = make_batch(outs)
        with mock.patch.object(VoiceVerificationResult, "metadata", new_callable=mock.PropertyMock) as m, \
                mock.patch.object(VoiceVerificationResult, "to_dict", side_effect=AssertionError("to_dict")):
            s = create_voice_verification_batch_summary(batch)
        m.assert_not_called()
        self.assertEqual(s.output_count, 1)

    def test_31_request_and_profile_ids_never_read(self):
        outs = [make_out("A", "x")]
        batch = make_batch(outs)
        with mock.patch.object(VoiceVerificationResult, "request_id", new_callable=mock.PropertyMock) as a, \
                mock.patch.object(VoiceVerificationResult, "profile_id", new_callable=mock.PropertyMock) as b:
            create_voice_verification_batch_summary(batch)
        a.assert_not_called()
        b.assert_not_called()

    def test_32_batch_and_outputs_unchanged(self):
        outs = [make_out("A", "x", 1), make_out("B", "y", 2)]
        batch = make_batch(outs)
        before = (batch.outputs, batch.failures, [o.to_dict() for o in outs])
        create_voice_verification_batch_summary(batch)
        self.assertEqual((batch.outputs, batch.failures, [o.to_dict() for o in outs]), before)
        for a, b in zip(batch.outputs, outs):
            self.assertIs(a, b)


class TestDeterminism(unittest.TestCase):
    def test_33_repeated_runs_equal(self):
        batch = make_batch([make_out("A", "x", 1), make_out("B", "y", 2)])
        runs = [create_voice_verification_batch_summary(batch) for _ in range(5)]
        for r in runs[1:]:
            self.assertEqual(r, runs[0])
            self.assertEqual(r.to_dict(), runs[0].to_dict())
        self.assertEqual(len({id(r) for r in runs}), 5)

    def test_34_rejected_deterministic(self):
        self.assertEqual(create_voice_verification_batch_summary(None), create_voice_verification_batch_summary(None))
        self.assertEqual(create_voice_verification_batch_summary(forged(5, ())), create_voice_verification_batch_summary(forged(None, ())))

    def test_35_no_io(self):
        batch = make_batch([make_out()])
        with mock.patch("builtins.open", side_effect=AssertionError("io")), mock.patch("os.listdir", side_effect=AssertionError("io")):
            self.assertEqual(create_voice_verification_batch_summary(batch).output_count, 1)

    def test_36_does_not_call_batch_or_pipeline(self):
        batch = make_batch([make_out()])
        with mock.patch("voice.voice_verification_batch.run_voice_verification_batch") as rb, mock.patch(BATCH_TARGET) as rp, \
                mock.patch("voice.voice_verification_pipeline.run_voice_verification_pipeline") as rp2, \
                mock.patch("voice.voice_verification_dispatcher.dispatch_voice_verification") as rd:
            create_voice_verification_batch_summary(batch)
        for m in (rb, rp, rp2, rd):
            m.assert_not_called()


class TestVerificationSpecific(unittest.TestCase):
    def test_44_enrollment_batch_result_is_invalid(self):
        from voice.voice_enrollment_batch import run_voice_enrollment_batch
        s = create_voice_verification_batch_summary(run_voice_enrollment_batch(()))
        self.assertEqual(s.codes(), [INVALID])

    def test_45_tuple_list_and_subclass_cases(self):
        batch = make_batch([make_out()])
        for v in ((batch,), [batch], (), []):
            self.assertEqual(create_voice_verification_batch_summary(v).codes(), [INVALID])
        with self.assertRaises(TypeError):
            class Sub(VoiceVerificationBatchResult):
                pass

    def test_46_enrollment_result_output_is_malformed(self):
        from voice.voice_enrollment_result import VoiceEnrollmentResult, create_voice_enrollment_result
        e = create_voice_enrollment_result({"request_id": "r", "profile_id": "p", "status": "S", "code": "C", "metadata": None}).result
        self.assertIs(type(e), VoiceEnrollmentResult)
        self.assertEqual(create_voice_verification_batch_summary(forged((make_out(), e), ())).codes(), [MALFORMED])

    def test_47_mixed_rejected_pipeline_outputs_with_real_batch(self):
        b = run_voice_verification_batch((make_plan(1), make_plan(2), make_plan(3)))
        s = create_voice_verification_batch_summary(b)
        self.assertEqual((s.output_count, s.failure_count, s.total_count, s.success), (3, 0, 3, True))
        self.assertEqual(sum(s.code_counts.values()), 3)
        self.assertEqual(list(s.status_counts), sorted(s.status_counts))

    def test_48_pipeline_error_batch_counts_the_failure(self):
        with mock.patch(BATCH_TARGET, side_effect=RuntimeError("x")):
            b = run_voice_verification_batch((make_plan(1), make_plan(2)))
        s = create_voice_verification_batch_summary(b)
        self.assertEqual((s.output_count, s.failure_count, s.total_count, s.success), (0, 1, 1, False))

    def test_49_previous_verification_modules_unchanged(self):
        pins = {"voice_verification_batch.py": "BATCH", "voice_verification_pipeline.py": "55bdb830f4add444c713466659c398cd1c0866a15c4ee3d062a37287075c3870",
                "voice_verification_result.py": "51c1161398590b55b75a4552709a286c68229335f56fd55a8b73c986db78242a",
                "voice_enrollment_batch_summary.py": "ENROLL_SUMMARY"}
        pins["voice_verification_batch.py"] = BATCH_SHA
        pins["voice_enrollment_batch_summary.py"] = ENROLL_SUMMARY_SHA
        for f, digest in pins.items():
            with open(os.path.join(PY_ROOT, "voice", f), "rb") as fh:
                self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), digest, f)


class TestPurityAndDoc(unittest.TestCase):
    def setUp(self):
        with open(MODULE, encoding="utf-8") as fh:
            self.src = fh.read()
        self.tree = ast.parse(self.src)

    def test_37_imports_are_only_batch_and_result(self):
        mods = sorted(n.module for n in ast.walk(self.tree) if isinstance(n, ast.ImportFrom))
        self.assertEqual(mods, ["voice_verification_batch", "voice_verification_result"])
        self.assertFalse([n for n in ast.walk(self.tree) if isinstance(n, ast.Import)])

    def test_38_no_lower_layer_calls(self):
        names = {n.id for n in ast.walk(self.tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(self.tree) if isinstance(n, ast.Attribute)}
        for bad in ("run_voice_verification_batch", "run_voice_verification_pipeline", "dispatch_voice_verification", "execute_voice_verification_plan",
                    "create_voice_verification_result", "metadata", "to_dict_of_output", "request_id", "profile_id",
                    "open", "os", "sys", "socket", "subprocess", "sqlite3", "random", "time", "datetime", "requests", "urllib", "print", "eval", "exec"):
            self.assertNotIn(bad, names, bad)

    def test_39_no_module_level_mutable_state(self):
        for node in self.tree.body:
            if isinstance(node, ast.Assign):
                self.assertNotIsInstance(node.value, (ast.List, ast.Dict, ast.Set))

    def test_40_codes_are_stable(self):
        self.assertEqual(vs.CODES, (INVALID, MALFORMED))
        for c in vs.CODES:
            self.assertTrue(c.startswith("VOICE_VERIFICATION_BATCH_SUMMARY_"))

    def test_41_not_wired_and_siblings_unchanged(self):
        for sub in ("core", "agent", "planning", "interface"):
            for root, _d, files in os.walk(os.path.join(PY_ROOT, sub)):
                for f in files:
                    if f.endswith(".py"):
                        with open(os.path.join(root, f), encoding="utf-8") as fh:
                            self.assertNotIn("voice_verification_batch_summary", fh.read())
        for f in os.listdir(os.path.join(PY_ROOT, "voice")):
            if f.endswith(".py") and f != "voice_verification_batch_summary.py":
                with open(os.path.join(PY_ROOT, "voice", f), encoding="utf-8") as fh:
                    self.assertNotIn("voice_verification_batch_summary", fh.read(), f)

    def test_42_doc_exists_and_names_the_api(self):
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("create_voice_verification_batch_summary", text)
        self.assertIn("Prompt 807 has NOT been started", text)

    def test_43_database_is_pristine(self):
        with open(PROJECT_DB, "rb") as f:
            self.assertEqual(hashlib.sha256(f.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
