"""Prompt 790 - Section 10 voice enrollment result contract (`voice.voice_enrollment_result`)."""
import ast
import copy
import hashlib
import json
import os
import pickle
import unittest

from voice import voice_enrollment_result as vr
from voice.voice_enrollment_result import VoiceEnrollmentResult, VoiceEnrollmentResultResult, create_voice_enrollment_result

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section10_voice_enrollment_result_prompt790.md")
MODULE = os.path.join(PY_ROOT, "voice", "voice_enrollment_result.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
FIELDS = ("request_id", "profile_id", "status", "code", "metadata")
STRING_FIELDS = FIELDS[:4]


def valid(**over):
    data = {"request_id": "enroll_1", "profile_id": "voice_1", "status": "COMPLETED", "code": "OK", "metadata": {"step": 1}}
    data.update(over)
    return data


def code_for(field):
    return vr._INVALID_CODES[vr.FIELDS.index(field)]


class TestValidCreation(unittest.TestCase):
    def test_1_valid_input_builds_a_result_with_every_value_kept(self):
        r = create_voice_enrollment_result(valid())
        self.assertIs(type(r), VoiceEnrollmentResultResult)
        self.assertTrue(r.ok)
        self.assertEqual((r.failures, r.codes()), ([], []))
        q = r.result
        self.assertIs(type(q), VoiceEnrollmentResult)
        self.assertEqual((q.request_id, q.profile_id, q.status, q.code, q.metadata), ("enroll_1", "voice_1", "COMPLETED", "OK", {"step": 1}))

    def test_2_exactly_five_fields_in_fixed_order(self):
        self.assertEqual(vr.FIELDS, FIELDS)
        self.assertEqual(list(create_voice_enrollment_result(valid()).result.to_dict()), list(FIELDS))
        self.assertEqual(VoiceEnrollmentResult.__slots__, ("_request_id", "_profile_id", "_status", "_code", "_items"))

    def test_3_metadata_none_is_accepted_and_stays_none(self):
        q = create_voice_enrollment_result(valid(metadata=None)).result
        self.assertIsNone(q.metadata)
        self.assertIsNone(q.to_dict()["metadata"])

    def test_4_empty_metadata_dict_is_accepted_and_stays_an_empty_dict(self):
        q = create_voice_enrollment_result(valid(metadata={})).result
        self.assertEqual(q.metadata, {})
        self.assertEqual(q.to_dict()["metadata"], {})
        self.assertNotEqual(q, create_voice_enrollment_result(valid(metadata=None)).result)

    def test_5_no_trim_no_normalization_and_non_empty_means_not_the_empty_string(self):
        q = create_voice_enrollment_result(valid(request_id=" R ", profile_id=" ID  1 ", status=" ok ", code=" ")).result
        self.assertEqual((q.request_id, q.profile_id, q.status, q.code), (" R ", " ID  1 ", " ok ", " "))
        for field in STRING_FIELDS:
            for ok in (" ", "\t", "x", "\u0627\u06a9\u0648"):
                self.assertTrue(create_voice_enrollment_result(valid(**{field: ok})).ok, (field, ok))

    def test_6_status_and_code_are_free_text_and_ids_are_not_looked_up(self):
        for text in ("COMPLETED", "weird status", "FAILED"):
            self.assertEqual(create_voice_enrollment_result(valid(status=text, code=text)).result.status, text)
        self.assertTrue(create_voice_enrollment_result(valid(request_id="nope", profile_id="no_such_profile")).ok)

    def test_7_string_identity_is_preserved(self):
        parts = ["".join(["a", "b"]), "".join(["c", "d"]), "".join(["e", "f"]), "".join(["g", "h"])]
        q = create_voice_enrollment_result(valid(request_id=parts[0], profile_id=parts[1], status=parts[2], code=parts[3])).result
        self.assertTrue(all(a is b for a, b in zip((q.request_id, q.profile_id, q.status, q.code), parts)))

    def test_8_dict_key_order_does_not_matter(self):
        data = {"metadata": None, "code": "OK", "status": "COMPLETED", "profile_id": "voice_1", "request_id": "enroll_1"}
        self.assertEqual(create_voice_enrollment_result(data).result, create_voice_enrollment_result(valid(metadata=None)).result)

    def test_9_metadata_keeps_key_order_and_value_objects(self):
        value = object()
        meta = {"z": 1, "a": value, 5: "int key"}
        q = create_voice_enrollment_result(valid(metadata=meta)).result
        self.assertEqual(list(q.metadata), ["z", "a", 5])
        self.assertIs(q.metadata["a"], value)


class TestFieldValidation(unittest.TestCase):
    def test_10_empty_strings_are_rejected(self):
        for field in STRING_FIELDS:
            r = create_voice_enrollment_result(valid(**{field: ""}))
            self.assertFalse(r.ok)
            self.assertIsNone(r.result)
            self.assertEqual(r.codes(), [code_for(field)])
            self.assertEqual(r.failures[0]["field"], field)

    def test_11_a_bool_is_rejected_for_every_string_field(self):
        for field in STRING_FIELDS:
            for bad in (True, False):
                self.assertEqual(create_voice_enrollment_result(valid(**{field: bad})).codes(), [code_for(field)], (field, bad))

    def test_12_string_fields_reject_every_other_wrong_type(self):
        for field in STRING_FIELDS:
            for bad in (None, 0, 1, 1.5, b"x", bytearray(b"x"), ["x"], ("x",), {"x": 1}, {"x"}, object(), str, 3 + 4j):
                self.assertEqual(create_voice_enrollment_result(valid(**{field: bad})).codes(), [code_for(field)], (field, bad))

    def test_13_a_str_subclass_is_rejected_and_its_methods_never_run(self):
        calls = []

        class Sneaky(str):
            def __len__(self):
                calls.append("len")
                return 1

            def __eq__(self, other):
                calls.append("eq")
                return True

            __hash__ = str.__hash__

            def __ne__(self, other):
                calls.append("ne")
                return False

        for field in STRING_FIELDS:
            self.assertEqual(create_voice_enrollment_result(valid(**{field: Sneaky("x")})).codes(), [code_for(field)])
        self.assertEqual(calls, [])

    def test_14_metadata_rejects_everything_but_none_and_an_exact_dict(self):
        class D(dict):
            pass

        class M:
            def keys(self):
                raise RuntimeError("must not run")

            def items(self):
                raise RuntimeError("must not run")
        for bad in (D(), D(a=1), M(), [], [("a", 1)], (), (("a", 1),), "x", "", 0, 1, 1.5, True, False, b"x", {"a"}, frozenset(), object(), dict, {}.items()):
            r = create_voice_enrollment_result(valid(metadata=bad))
            self.assertFalse(r.ok, bad)
            self.assertEqual(r.codes(), [vr.FAILURE_INVALID_METADATA], bad)
            self.assertEqual(r.failures[0]["field"], "metadata")

    def test_15_fields_are_validated_independently(self):
        self.assertEqual(create_voice_enrollment_result(valid(status=7)).codes(), [vr.FAILURE_INVALID_STATUS])
        self.assertEqual(create_voice_enrollment_result(valid(request_id="", metadata=[])).codes(),
                         [vr.FAILURE_INVALID_REQUEST_ID, vr.FAILURE_INVALID_METADATA])


class TestInputShape(unittest.TestCase):
    def test_16_non_dict_input_is_rejected_including_dict_subclasses(self):
        class D(dict):
            pass
        for bad in (None, [], (), "x", 5, True, valid().items(), D(valid()), [valid()], object()):
            r = create_voice_enrollment_result(bad)
            self.assertFalse(r.ok)
            self.assertIsNone(r.result)
            self.assertEqual(r.codes(), [vr.FAILURE_INVALID_INPUT])
            self.assertIsNone(r.failures[0]["field"])

    def test_17_missing_fields_are_rejected_and_nothing_is_defaulted(self):
        for field in FIELDS:
            data = valid()
            del data[field]
            r = create_voice_enrollment_result(data)
            self.assertEqual(r.codes(), [vr.FAILURE_MISSING_FIELD])
            self.assertEqual(r.failures[0]["field"], field)
        self.assertEqual(create_voice_enrollment_result({}).codes(), [vr.FAILURE_MISSING_FIELD] * 5)

    def test_18_unexpected_fields_are_rejected_not_ignored_and_sorted(self):
        r = create_voice_enrollment_result(valid(zeta=1, alpha=2))
        self.assertEqual(r.codes(), [vr.FAILURE_UNEXPECTED_FIELD] * 2)
        self.assertEqual([f["field"] for f in r.failures], ["alpha", "zeta"])

    def test_19_audio_biometric_and_credential_style_extras_are_rejected(self):
        for extra in ("audio", "recording", "embedding", "voiceprint", "biometric_sample", "samples", "service_data", "token", "api_key",
                      "password", "credentials", "ok", "result", "enabled"):
            self.assertEqual(create_voice_enrollment_result(valid(**{extra: "x"})).codes(), [vr.FAILURE_UNEXPECTED_FIELD], extra)

    def test_20_non_string_and_str_subclass_keys_are_rejected(self):
        class K(str):
            pass
        for key in (1, None):
            data = valid()
            data[key] = "x"
            self.assertEqual(create_voice_enrollment_result(data).codes(), [vr.FAILURE_UNEXPECTED_FIELD])
        data = valid()
        del data["request_id"]
        data[K("request_id")] = "a"
        r = create_voice_enrollment_result(data)
        self.assertFalse(r.ok)
        self.assertIn(vr.FAILURE_UNEXPECTED_FIELD, r.codes())

    def test_21_near_miss_field_names_are_unexpected_and_the_real_field_is_missing(self):
        data = valid()
        del data["status"]
        data["Status"] = "COMPLETED"
        self.assertEqual(create_voice_enrollment_result(data).codes(), [vr.FAILURE_UNEXPECTED_FIELD, vr.FAILURE_MISSING_FIELD])

    def test_22_a_request_or_profile_object_is_not_accepted_as_data(self):
        from voice.voice_enrollment_request import create_voice_enrollment_request
        req = create_voice_enrollment_request({"request_id": "r", "profile_id": "p", "enrollment_mode": "m"}).request
        self.assertEqual(create_voice_enrollment_result(req).codes(), [vr.FAILURE_INVALID_INPUT])
        self.assertEqual(create_voice_enrollment_result(req.to_dict()).codes(),
                         [vr.FAILURE_UNEXPECTED_FIELD, vr.FAILURE_MISSING_FIELD, vr.FAILURE_MISSING_FIELD, vr.FAILURE_MISSING_FIELD])


class TestFailureReporting(unittest.TestCase):
    def test_23_every_problem_is_reported_at_once_in_field_order(self):
        r = create_voice_enrollment_result({"request_id": 1, "profile_id": "", "status": None, "code": b"x", "metadata": []})
        self.assertEqual(r.codes(), list(vr._INVALID_CODES))
        self.assertEqual([f["field"] for f in r.failures], list(FIELDS))

    def test_24_input_then_unexpected_then_fields_ordering(self):
        r = create_voice_enrollment_result({"zz": 1, "aa": 2, "profile_id": 3})
        self.assertEqual(r.codes(), [vr.FAILURE_UNEXPECTED_FIELD, vr.FAILURE_UNEXPECTED_FIELD, vr.FAILURE_MISSING_FIELD, vr.FAILURE_INVALID_PROFILE_ID,
                                     vr.FAILURE_MISSING_FIELD, vr.FAILURE_MISSING_FIELD, vr.FAILURE_MISSING_FIELD])
        self.assertEqual([f["field"] for f in r.failures], ["aa", "zz", "request_id", "profile_id", "status", "code", "metadata"])

    def test_25_the_factory_never_raises_for_bad_data(self):
        class Boom:
            def __getattr__(self, name):
                raise RuntimeError(name)

            def __len__(self):
                raise RuntimeError("len")
        for bad in (None, 0, "x", [], (), Boom(), {"request_id": Boom(), "profile_id": Boom(), "status": Boom(), "code": Boom(), "metadata": Boom()},
                    {Boom(): 1}, {None: None}):
            self.assertFalse(create_voice_enrollment_result(bad).ok)

    def test_26_failures_are_deterministic_across_calls(self):
        bad = {"request_id": 1, "x": 2}
        self.assertEqual(create_voice_enrollment_result(bad).to_dict(), create_voice_enrollment_result(bad).to_dict())

    def test_27_failure_codes_are_unique_prefixed_and_stable(self):
        self.assertEqual(vr.FAILURE_CODES, (
            "VOICE_ENROLLMENT_RESULT_INVALID_INPUT", "VOICE_ENROLLMENT_RESULT_UNEXPECTED_FIELD", "VOICE_ENROLLMENT_RESULT_MISSING_FIELD",
            "VOICE_ENROLLMENT_RESULT_INVALID_REQUEST_ID", "VOICE_ENROLLMENT_RESULT_INVALID_PROFILE_ID", "VOICE_ENROLLMENT_RESULT_INVALID_STATUS",
            "VOICE_ENROLLMENT_RESULT_INVALID_CODE", "VOICE_ENROLLMENT_RESULT_INVALID_METADATA"))
        self.assertEqual(len(set(vr.FAILURE_CODES)), 8)

    def test_28_carrier_shape_to_dict_and_fresh_failures(self):
        ok = create_voice_enrollment_result(valid())
        self.assertEqual(ok.to_dict(), {"ok": True, "result": valid(), "failures": []})
        bad = create_voice_enrollment_result({})
        d = bad.to_dict()
        self.assertEqual((d["ok"], d["result"]), (False, None))
        self.assertEqual(set(d["failures"][0]), {"code", "field", "message"})
        d["failures"][0]["code"] = "x"
        self.assertEqual(bad.failures[0]["code"], vr.FAILURE_MISSING_FIELD)
        self.assertEqual(VoiceEnrollmentResultResult.__slots__, ("result", "failures"))
        self.assertFalse(VoiceEnrollmentResultResult().ok)
        self.assertFalse(VoiceEnrollmentResultResult(result=ok.result, failures=[{"code": "x"}]).ok)


class TestImmutabilityAndIsolation(unittest.TestCase):
    def test_29_attributes_cannot_be_assigned_deleted_or_added(self):
        q = create_voice_enrollment_result(valid()).result
        for name in FIELDS + ("_request_id", "_profile_id", "_status", "_code", "_items", "extra"):
            with self.assertRaises(AttributeError):
                setattr(q, name, "x")
            with self.assertRaises(AttributeError):
                delattr(q, name)
        self.assertFalse(hasattr(q, "__dict__"))
        self.assertEqual([n for n in dir(q) if not n.startswith("_")], ["code", "metadata", "profile_id", "request_id", "status", "to_dict"])
        self.assertEqual(q.to_dict(), valid())

    def test_30_direct_construction_and_subclassing_are_refused(self):
        for args in ((), (object(), "a", "b", "c", "d", None), (None, "a", "b", "c", "d", None), ("a", "b", "c", "d", None)):
            with self.assertRaises(TypeError):
                VoiceEnrollmentResult(*args)
        with self.assertRaises(TypeError):
            class Sub(VoiceEnrollmentResult):
                pass

    def test_31_to_dict_is_fresh_has_exactly_five_fields_and_round_trips(self):
        q = create_voice_enrollment_result(valid()).result
        d1, d2 = q.to_dict(), q.to_dict()
        self.assertEqual(d1, valid())
        self.assertIsNot(d1, d2)
        self.assertIsNot(d1["metadata"], d2["metadata"])
        d1["request_id"] = "changed"
        d1["extra"] = 1
        self.assertEqual(q.to_dict(), valid())
        self.assertEqual(create_voice_enrollment_result(q.to_dict()).result, q)
        self.assertEqual(json.loads(json.dumps(q.to_dict())), valid())

    def test_32_mutating_a_returned_metadata_dict_never_affects_the_result(self):
        q = create_voice_enrollment_result(valid()).result
        for fresh in (q.metadata, q.to_dict()["metadata"]):
            fresh["step"] = 99
            fresh["new"] = True
            fresh.clear()
        self.assertEqual(q.metadata, {"step": 1})
        self.assertIsNot(q.metadata, q.metadata)
        self.assertEqual(q.to_dict(), valid())

    def test_33_the_input_dict_and_metadata_are_not_retained(self):
        meta = {"step": 1}
        data = valid(metadata=meta)
        q = create_voice_enrollment_result(data).result
        data["request_id"] = "changed"
        data["metadata"] = None
        meta["step"] = 2
        meta["added"] = 1
        self.assertEqual(q.to_dict(), valid())
        meta.clear()
        self.assertEqual(q.metadata, {"step": 1})
        self.assertIsNot(q.metadata, meta)

    def test_34_the_factory_never_changes_the_callers_data_or_metadata(self):
        meta = {"b": 1, "a": 2}
        data = valid(metadata=meta)
        snapshot, meta_snapshot = dict(data), dict(meta)
        create_voice_enrollment_result(data)
        create_voice_enrollment_result(dict(data, extra=1))
        self.assertEqual((data, list(data), meta, list(meta)), (snapshot, list(snapshot), meta_snapshot, list(meta_snapshot)))
        self.assertIs(data["metadata"], meta)

    def test_35_two_results_from_one_metadata_dict_do_not_share_state(self):
        meta = {"k": "v"}
        a = create_voice_enrollment_result(valid(metadata=meta)).result
        b = create_voice_enrollment_result(valid(metadata=meta)).result
        a.metadata["k"] = "changed"
        self.assertEqual((a.metadata, b.metadata, a, b), ({"k": "v"}, {"k": "v"}, a, a))
        self.assertIsNot(a.metadata, b.metadata)

    def test_36_equal_data_gives_equal_objects_and_hashes_including_metadata(self):
        a, b = create_voice_enrollment_result(valid()).result, create_voice_enrollment_result(valid()).result
        self.assertIsNot(a, b)
        self.assertEqual((a, hash(a)), (b, hash(b)))
        self.assertEqual(len({a, b}), 1)
        self.assertNotEqual(a, create_voice_enrollment_result(valid(metadata={"step": 2})).result)
        self.assertNotEqual(a, create_voice_enrollment_result(valid(metadata=None)).result)

    def test_37_any_differing_field_breaks_equality(self):
        base = create_voice_enrollment_result(valid()).result
        for field in STRING_FIELDS:
            self.assertNotEqual(base, create_voice_enrollment_result(valid(**{field: "different"})).result, field)

    def test_38_unhashable_metadata_values_do_not_break_hashing(self):
        q = create_voice_enrollment_result(valid(metadata={"nested": [1, 2], "d": {"x": 1}})).result
        self.assertIsInstance(hash(q), int)
        self.assertEqual(q, create_voice_enrollment_result(valid(metadata={"nested": [1, 2], "d": {"x": 1}})).result)

    def test_39_equality_is_exact_type_only(self):
        q = create_voice_enrollment_result(valid()).result
        for other in (valid(), q.to_dict(), tuple(valid().values()), None, "x"):
            self.assertNotEqual(q, other)
            self.assertIs(q.__eq__(other), NotImplemented)

    def test_40_copy_and_deepcopy_return_the_same_object(self):
        q = create_voice_enrollment_result(valid()).result
        self.assertIs(copy.copy(q), q)
        self.assertIs(copy.deepcopy(q), q)
        self.assertIs(copy.deepcopy([q])[0], q)

    def test_41_pickle_is_refused_for_every_protocol(self):
        q = create_voice_enrollment_result(valid()).result
        for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
            with self.assertRaises(TypeError):
                pickle.dumps(q, protocol)

    def test_42_repr_is_stable_and_leaves_metadata_out(self):
        self.assertEqual(repr(create_voice_enrollment_result(valid(metadata={"secret": "x"})).result),
                         "VoiceEnrollmentResult(request_id='enroll_1', profile_id='voice_1', status='COMPLETED', code='OK')")

    def test_43_the_carrier_does_not_affect_the_immutable_result(self):
        r = create_voice_enrollment_result(valid())
        q = r.result
        r.result = None
        r.failures.append({"code": "x"})
        self.assertEqual(q.to_dict(), valid())


class TestScopeAndHygiene(unittest.TestCase):
    def test_44_module_imports_nothing_and_does_no_io_or_networking(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))], [])
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "getattr", "setattr", "globals", "vars", "deepcopy"):
            self.assertNotIn(forbidden, calls)

    def test_45_module_has_no_mutable_module_level_state(self):
        for name, value in vars(vr).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_46_the_result_stores_no_audio_embedding_biometric_recording_service_data_or_credentials(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        idents = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for token in ("audio", "embedding", "embeddings", "biometric", "sample", "samples", "recording", "voiceprint", "credentials", "api_key", "token_value",
                      "socket", "urllib", "requests", "sqlite3", "os", "sys", "subprocess", "random", "time", "datetime", "anthropic", "openai"):
            self.assertNotIn(token, idents, token)
        self.assertEqual(vr.VoiceEnrollmentResult.__slots__, ("_request_id", "_profile_id", "_status", "_code", "_items"))

    def test_47_voice_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "voice")) if f != "__pycache__"),
                         ["__init__.py", "voice_enrollment_batch.py", "voice_enrollment_batch_summary.py", "voice_enrollment_dispatcher.py", "voice_enrollment_executor.py", "voice_enrollment_pipeline.py", "voice_enrollment_plan.py", "voice_enrollment_request.py", "voice_enrollment_result.py", "voice_enrollment_result_validator.py",
                          "voice_identity_profile.py", "voice_identity_profile_registry.py", "voice_verification_authorization.py", "voice_verification_batch.py", "voice_verification_batch_summary.py", "voice_verification_decision.py", "voice_verification_dispatcher.py", "voice_verification_execution.py", "voice_verification_execution_request.py", "voice_verification_executor.py", "voice_verification_handoff.py", "voice_verification_pipeline.py", "voice_verification_plan.py", "voice_verification_profile_resolver.py", "voice_verification_registry.py", "voice_verification_request.py", "voice_verification_request_validator.py", "voice_verification_result.py"])
        with open(os.path.join(PY_ROOT, "voice", "__init__.py"), "rb") as fh:
            self.assertEqual(fh.read(), b"")

    def test_48_earlier_voice_contracts_are_unaware_of_the_result_and_unchanged_in_contract(self):
        for name in ("voice_identity_profile.py", "voice_identity_profile_registry.py", "voice_enrollment_request.py"):
            with open(os.path.join(PY_ROOT, "voice", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("voice_enrollment_result", "VoiceEnrollmentResult"):
                self.assertNotIn(token, text, (name, token))
        import voice.voice_enrollment_request as vq
        import voice.voice_identity_profile as vp
        self.assertEqual(vp.FIELDS, ("profile_id", "display_name", "enabled", "enrollment_status"))
        self.assertEqual(vq.FIELDS, ("request_id", "profile_id", "enrollment_mode"))
        self.assertEqual(vq.FAILURE_CODES[0], "VOICE_ENROLLMENT_REQUEST_INVALID_INPUT")

    def test_49_no_existing_module_outside_voice_imports_or_names_the_result(self):
        checked = 0
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if not (folder == PY_ROOT and d in ("voice", "tests", "data")) and d != "__pycache__"]
            for name in files:
                if not name.endswith(".py"):
                    continue
                with open(os.path.join(folder, name), encoding="utf-8") as fh:
                    text = fh.read()
                for token in ("VoiceEnrollmentResult", "voice_enrollment_result"):
                    self.assertNotIn(token, text, (os.path.join(folder, name), token))
                checked += 1
        self.assertGreater(checked, 100)

    def test_50_doc_exists_and_mentions_the_contract_and_limits(self):
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for needle in ("Prompt 790", "VoiceEnrollmentResult", "create_voice_enrollment_result", "VOICE_ENROLLMENT_RESULT_", "metadata", "does NOT",
                       "audio", "embeddings", "biometric", "recordings", "credentials", "Prompt 791"):
            self.assertIn(needle, text, needle)

    def test_51_pristine_database_and_no_bytecode(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)


if __name__ == "__main__":
    unittest.main()
