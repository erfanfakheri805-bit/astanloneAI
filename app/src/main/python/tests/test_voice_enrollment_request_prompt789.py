"""Prompt 789 - Section 10 voice enrollment request contract (`voice.voice_enrollment_request`)."""
import ast
import copy
import hashlib
import json
import os
import pickle
import unittest

from voice import voice_enrollment_request as vr
from voice.voice_enrollment_request import VoiceEnrollmentRequest, VoiceEnrollmentRequestResult, create_voice_enrollment_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section10_voice_enrollment_request_prompt789.md")
MODULE = os.path.join(PY_ROOT, "voice", "voice_enrollment_request.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
FIELDS = ("request_id", "profile_id", "enrollment_mode")


def valid(**over):
    data = {"request_id": "enroll_1", "profile_id": "voice_1", "enrollment_mode": "guided"}
    data.update(over)
    return data


def code_for(field):
    return vr._INVALID_CODES[vr.FIELDS.index(field)]


class TestValidCreation(unittest.TestCase):
    def test_1_valid_input_builds_a_request_with_every_value_kept(self):
        r = create_voice_enrollment_request(valid())
        self.assertIs(type(r), VoiceEnrollmentRequestResult)
        self.assertTrue(r.ok)
        self.assertEqual((r.failures, r.codes()), ([], []))
        q = r.request
        self.assertIs(type(q), VoiceEnrollmentRequest)
        self.assertEqual((q.request_id, q.profile_id, q.enrollment_mode), ("enroll_1", "voice_1", "guided"))

    def test_2_exactly_three_fields_in_fixed_order(self):
        self.assertEqual(vr.FIELDS, FIELDS)
        self.assertEqual(list(create_voice_enrollment_request(valid()).request.to_dict()), list(FIELDS))
        self.assertEqual(VoiceEnrollmentRequest.__slots__, ("_request_id", "_profile_id", "_enrollment_mode"))

    def test_3_no_trim_no_normalization_values_are_stored_as_given(self):
        q = create_voice_enrollment_request(valid(request_id=" R-1 ", profile_id=" ID  1 ", enrollment_mode=" GUIDED ")).request
        self.assertEqual((q.request_id, q.profile_id, q.enrollment_mode), (" R-1 ", " ID  1 ", " GUIDED "))

    def test_4_non_empty_means_only_not_the_empty_string(self):
        for field in FIELDS:
            for ok in (" ", "\t", "  \n", "x"):
                self.assertTrue(create_voice_enrollment_request(valid(**{field: ok})).ok, (field, ok))

    def test_5_enrollment_mode_is_free_text_and_profile_id_is_not_looked_up(self):
        for text in ("guided", "PASSIVE", "anything at all", "\u0627\u06a9\u0648"):
            self.assertEqual(create_voice_enrollment_request(valid(enrollment_mode=text)).request.enrollment_mode, text)
        self.assertTrue(create_voice_enrollment_request(valid(profile_id="no_such_profile_anywhere")).ok)

    def test_6_string_identity_is_preserved(self):
        rid, pid, mode = "".join(["enr", "_9"]), "".join(["vo", "ice"]), "".join(["mo", "de"])
        q = create_voice_enrollment_request(valid(request_id=rid, profile_id=pid, enrollment_mode=mode)).request
        self.assertIs(q.request_id, rid)
        self.assertIs(q.profile_id, pid)
        self.assertIs(q.enrollment_mode, mode)

    def test_7_the_factory_never_changes_the_callers_dict(self):
        data = valid()
        snapshot = dict(data)
        create_voice_enrollment_request(data)
        create_voice_enrollment_request(dict(data, extra=1))
        self.assertEqual(data, snapshot)
        self.assertEqual(list(data), list(snapshot))

    def test_8_later_edits_to_the_input_do_not_reach_the_request(self):
        data = valid()
        q = create_voice_enrollment_request(data).request
        data["request_id"] = "changed"
        self.assertEqual(q.request_id, "enroll_1")

    def test_9_dict_key_order_does_not_matter(self):
        data = {"enrollment_mode": "guided", "profile_id": "voice_1", "request_id": "enroll_1"}
        self.assertEqual(create_voice_enrollment_request(data).request, create_voice_enrollment_request(valid()).request)


class TestFieldValidation(unittest.TestCase):
    def test_10_empty_strings_are_rejected(self):
        for field in FIELDS:
            r = create_voice_enrollment_request(valid(**{field: ""}))
            self.assertFalse(r.ok)
            self.assertIsNone(r.request)
            self.assertEqual(r.codes(), [code_for(field)])
            self.assertEqual(r.failures[0]["field"], field)

    def test_11_a_bool_is_rejected_for_every_string_field(self):
        for field in FIELDS:
            for bad in (True, False):
                r = create_voice_enrollment_request(valid(**{field: bad}))
                self.assertFalse(r.ok, (field, bad))
                self.assertEqual(r.codes(), [code_for(field)])

    def test_12_string_fields_reject_every_other_wrong_type(self):
        for field in FIELDS:
            for bad in (None, 0, 1, 1.5, b"x", bytearray(b"x"), ["x"], ("x",), {"x": 1}, {"x"}, object(), str, 3 + 4j):
                r = create_voice_enrollment_request(valid(**{field: bad}))
                self.assertEqual(r.codes(), [code_for(field)], (field, bad))

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

        for field in FIELDS:
            r = create_voice_enrollment_request(valid(**{field: Sneaky("x")}))
            self.assertEqual(r.codes(), [code_for(field)])
        self.assertEqual(calls, [])

    def test_14_fields_are_validated_independently(self):
        self.assertEqual(create_voice_enrollment_request(valid(profile_id=7)).codes(), [vr.FAILURE_INVALID_PROFILE_ID])
        self.assertEqual(create_voice_enrollment_request(valid(request_id="", enrollment_mode=True)).codes(),
                         [vr.FAILURE_INVALID_REQUEST_ID, vr.FAILURE_INVALID_ENROLLMENT_MODE])


class TestInputShape(unittest.TestCase):
    def test_15_non_dict_input_is_rejected_including_dict_subclasses(self):
        class D(dict):
            pass
        for bad in (None, [], (), "x", 5, True, valid().items(), D(valid()), [valid()], object()):
            r = create_voice_enrollment_request(bad)
            self.assertFalse(r.ok)
            self.assertIsNone(r.request)
            self.assertEqual(r.codes(), [vr.FAILURE_INVALID_INPUT])
            self.assertIsNone(r.failures[0]["field"])

    def test_16_missing_fields_are_rejected_and_nothing_is_defaulted(self):
        for field in FIELDS:
            data = valid()
            del data[field]
            r = create_voice_enrollment_request(data)
            self.assertEqual(r.codes(), [vr.FAILURE_MISSING_FIELD])
            self.assertEqual(r.failures[0]["field"], field)
        self.assertEqual(create_voice_enrollment_request({}).codes(), [vr.FAILURE_MISSING_FIELD] * 3)

    def test_17_unexpected_fields_are_rejected_not_ignored_and_sorted(self):
        r = create_voice_enrollment_request(valid(zeta=1, alpha=2))
        self.assertEqual(r.codes(), [vr.FAILURE_UNEXPECTED_FIELD] * 2)
        self.assertEqual([f["field"] for f in r.failures], ["alpha", "zeta"])

    def test_18_audio_and_biometric_style_extras_are_rejected(self):
        for extra in ("audio", "recording", "embedding", "voiceprint", "biometric_sample", "samples", "service_data", "language", "enabled"):
            r = create_voice_enrollment_request(valid(**{extra: "x"}))
            self.assertEqual(r.codes(), [vr.FAILURE_UNEXPECTED_FIELD], extra)

    def test_19_non_string_and_str_subclass_keys_are_rejected(self):
        class K(str):
            pass
        data = valid()
        data[1] = "x"
        self.assertEqual(create_voice_enrollment_request(data).codes(), [vr.FAILURE_UNEXPECTED_FIELD])
        data = valid()
        data[None] = "x"
        self.assertEqual(create_voice_enrollment_request(data).codes(), [vr.FAILURE_UNEXPECTED_FIELD])
        data = {K("request_id"): "a", "profile_id": "b", "enrollment_mode": "c"}
        r = create_voice_enrollment_request(data)
        self.assertFalse(r.ok)
        self.assertIn(vr.FAILURE_UNEXPECTED_FIELD, r.codes())

    def test_20_near_miss_field_names_are_unexpected_and_the_real_field_is_missing(self):
        data = valid()
        del data["profile_id"]
        data["Profile_Id"] = "voice_1"
        r = create_voice_enrollment_request(data)
        self.assertEqual(r.codes(), [vr.FAILURE_UNEXPECTED_FIELD, vr.FAILURE_MISSING_FIELD])
        data = valid()
        del data["request_id"]
        data["request_id "] = "enroll_1"
        self.assertEqual(create_voice_enrollment_request(data).codes(), [vr.FAILURE_UNEXPECTED_FIELD, vr.FAILURE_MISSING_FIELD])


class TestFailureReporting(unittest.TestCase):
    def test_21_every_problem_is_reported_at_once_in_field_order(self):
        r = create_voice_enrollment_request({"request_id": 1, "profile_id": "", "enrollment_mode": None})
        self.assertEqual(r.codes(), list(vr._INVALID_CODES))
        self.assertEqual([f["field"] for f in r.failures], list(FIELDS))

    def test_22_input_then_unexpected_then_fields_ordering(self):
        r = create_voice_enrollment_request({"zz": 1, "aa": 2, "profile_id": 3})
        self.assertEqual(r.codes(), [vr.FAILURE_UNEXPECTED_FIELD, vr.FAILURE_UNEXPECTED_FIELD, vr.FAILURE_MISSING_FIELD,
                                     vr.FAILURE_INVALID_PROFILE_ID, vr.FAILURE_MISSING_FIELD])
        self.assertEqual([f["field"] for f in r.failures], ["aa", "zz", "request_id", "profile_id", "enrollment_mode"])

    def test_23_the_factory_never_raises_for_bad_data(self):
        class Boom:
            def __getattr__(self, name):
                raise RuntimeError(name)

            def __len__(self):
                raise RuntimeError("len")
        for bad in (None, 0, "x", [], (), Boom(), {"request_id": Boom(), "profile_id": Boom(), "enrollment_mode": Boom()}, {Boom(): 1}, {None: None}):
            r = create_voice_enrollment_request(bad)
            self.assertFalse(r.ok)

    def test_24_failures_are_deterministic_across_calls(self):
        bad = {"request_id": 1, "x": 2}
        self.assertEqual(create_voice_enrollment_request(bad).to_dict(), create_voice_enrollment_request(bad).to_dict())

    def test_25_failure_codes_are_unique_prefixed_and_stable(self):
        self.assertEqual(vr.FAILURE_CODES, (
            "VOICE_ENROLLMENT_REQUEST_INVALID_INPUT", "VOICE_ENROLLMENT_REQUEST_UNEXPECTED_FIELD", "VOICE_ENROLLMENT_REQUEST_MISSING_FIELD",
            "VOICE_ENROLLMENT_REQUEST_INVALID_REQUEST_ID", "VOICE_ENROLLMENT_REQUEST_INVALID_PROFILE_ID",
            "VOICE_ENROLLMENT_REQUEST_INVALID_ENROLLMENT_MODE"))
        self.assertEqual(len(set(vr.FAILURE_CODES)), 6)
        for code in vr.FAILURE_CODES:
            self.assertTrue(code.startswith("VOICE_ENROLLMENT_REQUEST_"))

    def test_26_result_shape_to_dict_and_fresh_failures(self):
        ok = create_voice_enrollment_request(valid())
        self.assertEqual(ok.to_dict(), {"ok": True, "request": valid(), "failures": []})
        bad = create_voice_enrollment_request({})
        d = bad.to_dict()
        self.assertEqual((d["ok"], d["request"]), (False, None))
        self.assertEqual(set(d["failures"][0]), {"code", "field", "message"})
        d["failures"][0]["code"] = "x"
        self.assertEqual(bad.failures[0]["code"], vr.FAILURE_MISSING_FIELD)
        self.assertEqual(VoiceEnrollmentRequestResult.__slots__, ("request", "failures"))
        self.assertFalse(VoiceEnrollmentRequestResult().ok)
        self.assertFalse(VoiceEnrollmentRequestResult(request=ok.request, failures=[{"code": "x"}]).ok)


class TestImmutability(unittest.TestCase):
    def test_27_equal_data_gives_equal_objects_and_hashes(self):
        a, b = create_voice_enrollment_request(valid()).request, create_voice_enrollment_request(valid()).request
        self.assertIsNot(a, b)
        self.assertEqual((a, hash(a)), (b, hash(b)))
        self.assertEqual(len({a, b}), 1)
        self.assertEqual({a: 1}[b], 1)

    def test_28_any_differing_field_breaks_equality(self):
        base = create_voice_enrollment_request(valid()).request
        for field in FIELDS:
            other = create_voice_enrollment_request(valid(**{field: "different"})).request
            self.assertNotEqual(base, other, field)

    def test_29_equality_is_exact_type_only(self):
        q = create_voice_enrollment_request(valid()).request
        for other in (valid(), q.to_dict(), tuple(valid().values()), None, "x"):
            self.assertNotEqual(q, other)
            self.assertIs(q.__eq__(other), NotImplemented)

    def test_30_to_dict_returns_exactly_the_three_fields_fresh_and_round_trips(self):
        q = create_voice_enrollment_request(valid()).request
        d1, d2 = q.to_dict(), q.to_dict()
        self.assertEqual(d1, valid())
        self.assertIsNot(d1, d2)
        d1["request_id"] = "changed"
        d1["extra"] = 1
        self.assertEqual(q.to_dict(), valid())
        self.assertEqual(create_voice_enrollment_request(q.to_dict()).request, q)
        self.assertEqual(json.loads(json.dumps(q.to_dict())), valid())

    def test_31_attributes_cannot_be_assigned_deleted_or_added(self):
        q = create_voice_enrollment_request(valid()).request
        for name in FIELDS + ("_request_id", "_profile_id", "_enrollment_mode", "extra"):
            with self.assertRaises(AttributeError):
                setattr(q, name, "x")
            with self.assertRaises(AttributeError):
                delattr(q, name)
        self.assertFalse(hasattr(q, "__dict__"))
        self.assertEqual([n for n in dir(q) if not n.startswith("_")], ["enrollment_mode", "profile_id", "request_id", "to_dict"])

    def test_32_direct_construction_and_subclassing_are_refused(self):
        for args in ((), (object(), "a", "b", "c"), (None, "a", "b", "c"), ("a", "b", "c")):
            with self.assertRaises(TypeError):
                VoiceEnrollmentRequest(*args)
        with self.assertRaises(TypeError):
            class Sub(VoiceEnrollmentRequest):
                pass

    def test_33_copy_and_deepcopy_return_the_same_object(self):
        q = create_voice_enrollment_request(valid()).request
        self.assertIs(copy.copy(q), q)
        self.assertIs(copy.deepcopy(q), q)
        self.assertIs(copy.deepcopy([q])[0], q)

    def test_34_pickle_is_refused_for_every_protocol(self):
        q = create_voice_enrollment_request(valid()).request
        for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
            with self.assertRaises(TypeError):
                pickle.dumps(q, protocol)

    def test_35_repr_is_stable_and_shows_exactly_the_three_fields(self):
        self.assertEqual(repr(create_voice_enrollment_request(valid()).request),
                         "VoiceEnrollmentRequest(request_id='enroll_1', profile_id='voice_1', enrollment_mode='guided')")

    def test_36_the_result_carrier_does_not_affect_the_immutable_request(self):
        r = create_voice_enrollment_request(valid())
        q = r.request
        r.request = None
        r.failures.append({"code": "x"})
        self.assertEqual(q.to_dict(), valid())


class TestScopeAndHygiene(unittest.TestCase):
    def test_37_module_imports_nothing_and_does_no_io_or_networking(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))], [])
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "getattr", "setattr", "globals", "vars"):
            self.assertNotIn(forbidden, calls)

    def test_38_module_has_no_mutable_module_level_state(self):
        for name, value in vars(vr).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_39_the_request_stores_no_audio_embedding_biometric_recording_or_service_data(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        idents = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for token in ("audio", "embedding", "embeddings", "biometric", "sample", "samples", "recording", "voiceprint", "socket", "urllib", "requests",
                      "sqlite3", "os", "sys", "subprocess", "random", "time", "datetime", "anthropic", "openai"):
            self.assertNotIn(token, idents, token)

    def test_40_voice_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "voice")) if f != "__pycache__"),
                         ["__init__.py", "voice_enrollment_batch.py", "voice_enrollment_batch_summary.py", "voice_enrollment_dispatcher.py", "voice_enrollment_executor.py", "voice_enrollment_pipeline.py", "voice_enrollment_plan.py", "voice_enrollment_request.py", "voice_enrollment_result.py", "voice_enrollment_result_validator.py", "voice_identity_profile.py", "voice_identity_profile_registry.py", "voice_verification_authorization.py", "voice_verification_batch.py", "voice_verification_batch_summary.py", "voice_verification_decision.py", "voice_verification_dispatcher.py", "voice_verification_execution.py", "voice_verification_execution_request.py", "voice_verification_executor.py", "voice_verification_handoff.py", "voice_verification_pipeline.py", "voice_verification_plan.py", "voice_verification_profile_resolver.py", "voice_verification_registry.py", "voice_verification_request.py", "voice_verification_request_validator.py", "voice_verification_result.py"])
        with open(os.path.join(PY_ROOT, "voice", "__init__.py"), "rb") as fh:
            self.assertEqual(fh.read(), b"")

    def test_41_profile_and_registry_modules_are_unaware_of_the_request_and_unchanged_in_contract(self):
        for name in ("voice_identity_profile.py", "voice_identity_profile_registry.py"):
            with open(os.path.join(PY_ROOT, "voice", name), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("enrollment_request", "EnrollmentRequest", "voice_enrollment"):
                self.assertNotIn(token, text, (name, token))
        import voice.voice_identity_profile as vp
        import voice.voice_identity_profile_registry as vg
        self.assertEqual(vp.FIELDS, ("profile_id", "display_name", "enabled", "enrollment_status"))
        self.assertEqual(vg.FAILURE_CODES[0], "VOICE_IDENTITY_PROFILE_REGISTRY_INVALID_COLLECTION")

    def test_42_no_existing_module_imports_or_names_the_request(self):
        checked = 0
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if not (folder == PY_ROOT and d in ("voice", "tests", "data")) and d != "__pycache__"]
            for name in files:
                if not name.endswith(".py"):
                    continue
                with open(os.path.join(folder, name), encoding="utf-8") as fh:
                    text = fh.read()
                for token in ("VoiceEnrollmentRequest", "voice_enrollment_request", "from voice", "import voice"):
                    self.assertNotIn(token, text, (os.path.join(folder, name), token))
                checked += 1
        self.assertGreater(checked, 100)

    def test_43_doc_exists_and_mentions_the_contract_and_limits(self):
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for needle in ("Prompt 789", "VoiceEnrollmentRequest", "create_voice_enrollment_request", "VOICE_ENROLLMENT_REQUEST_", "enrollment_mode",
                       "does NOT", "audio", "embeddings", "biometric", "recordings", "Prompt 790"):
            self.assertIn(needle, text, needle)

    def test_44_pristine_database_and_no_bytecode(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)


if __name__ == "__main__":
    unittest.main()
