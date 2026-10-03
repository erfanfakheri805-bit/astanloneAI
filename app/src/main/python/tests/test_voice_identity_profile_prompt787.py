"""Prompt 787 - Section 10 voice identity profile contract (`voice.voice_identity_profile`)."""
import ast
import copy
import hashlib
import json
import os
import pickle
import unittest

from voice import voice_identity_profile as vp
from voice.voice_identity_profile import (VoiceIdentityProfile, VoiceIdentityProfileResult, create_voice_identity_profile)

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section10_voice_identity_profile_prompt787.md")
MODULE = os.path.join(PY_ROOT, "voice", "voice_identity_profile.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
FIELDS = ("profile_id", "display_name", "enabled", "enrollment_status")
STR_FIELDS = ("profile_id", "display_name", "enrollment_status")


def valid(**over):
    data = {"profile_id": "voice_1", "display_name": "Main User", "enabled": True, "enrollment_status": "not_enrolled"}
    data.update(over)
    return data


def code_for(field):
    return vp._INVALID_CODES[vp.FIELDS.index(field)]


class TestValidCreation(unittest.TestCase):
    def test_1_valid_input_builds_a_profile_with_every_value_kept(self):
        r = create_voice_identity_profile(valid())
        self.assertIs(type(r), VoiceIdentityProfileResult)
        self.assertTrue(r.ok)
        self.assertEqual((r.failures, r.codes()), ([], []))
        p = r.profile
        self.assertIs(type(p), VoiceIdentityProfile)
        self.assertEqual((p.profile_id, p.display_name, p.enabled, p.enrollment_status), ("voice_1", "Main User", True, "not_enrolled"))

    def test_2_exactly_four_fields_in_fixed_order(self):
        self.assertEqual(vp.FIELDS, FIELDS)
        self.assertEqual(list(create_voice_identity_profile(valid()).profile.to_dict()), list(FIELDS))
        self.assertEqual(VoiceIdentityProfile.__slots__, ("_profile_id", "_display_name", "_enabled", "_enrollment_status"))

    def test_3_enabled_accepts_both_true_and_false(self):
        self.assertIs(create_voice_identity_profile(valid(enabled=True)).profile.enabled, True)
        self.assertIs(create_voice_identity_profile(valid(enabled=False)).profile.enabled, False)

    def test_4_no_trim_no_normalization_values_are_stored_as_given(self):
        p = create_voice_identity_profile(valid(profile_id=" ID-1 ", display_name=" Ada  L ", enrollment_status=" Enrolled ")).profile
        self.assertEqual((p.profile_id, p.display_name, p.enrollment_status), (" ID-1 ", " Ada  L ", " Enrolled "))

    def test_5_non_empty_means_only_not_the_empty_string(self):
        for field in STR_FIELDS:
            for ok in (" ", "\t", "  \n", "x"):
                self.assertTrue(create_voice_identity_profile(valid(**{field: ok})).ok, (field, ok))

    def test_6_enrollment_status_is_free_text(self):
        for text in ("pending", "ENROLLED", "anything at all", "\u0627\u06a9\u0648"):
            self.assertEqual(create_voice_identity_profile(valid(enrollment_status=text)).profile.enrollment_status, text)

    def test_7_string_identity_is_preserved(self):
        pid, name, status = "".join(["voice", "_9"]), "".join(["Na", "me"]), "".join(["sta", "tus"])
        p = create_voice_identity_profile(valid(profile_id=pid, display_name=name, enrollment_status=status)).profile
        self.assertIs(p.profile_id, pid)
        self.assertIs(p.display_name, name)
        self.assertIs(p.enrollment_status, status)

    def test_8_the_factory_never_changes_the_callers_dict(self):
        data = valid()
        snapshot = dict(data)
        create_voice_identity_profile(data)
        create_voice_identity_profile(dict(data, extra=1))
        self.assertEqual(data, snapshot)
        self.assertEqual(list(data), list(snapshot))

    def test_9_later_edits_to_the_input_do_not_reach_the_profile(self):
        data = valid()
        p = create_voice_identity_profile(data).profile
        data["profile_id"] = "changed"
        data["enabled"] = False
        self.assertEqual((p.profile_id, p.enabled), ("voice_1", True))


class TestFieldValidation(unittest.TestCase):
    def test_10_empty_required_strings_are_rejected(self):
        for field in STR_FIELDS:
            r = create_voice_identity_profile(valid(**{field: ""}))
            self.assertFalse(r.ok)
            self.assertIsNone(r.profile)
            self.assertEqual(r.codes(), [code_for(field)])
            self.assertEqual(r.failures[0]["field"], field)

    def test_11_a_bool_is_rejected_for_every_str_field(self):
        for field in STR_FIELDS:
            for bad in (True, False):
                r = create_voice_identity_profile(valid(**{field: bad}))
                self.assertFalse(r.ok, (field, bad))
                self.assertEqual(r.codes(), [code_for(field)])

    def test_12_str_fields_reject_every_other_wrong_type(self):
        for field in STR_FIELDS:
            for bad in (None, 0, 1, 1.5, b"x", bytearray(b"x"), ["x"], ("x",), {"x": 1}, {"x"}, object(), str, 3 + 4j):
                r = create_voice_identity_profile(valid(**{field: bad}))
                self.assertEqual(r.codes(), [code_for(field)], (field, bad))

    def test_13_enabled_must_be_exactly_bool(self):
        for bad in ("true", "True", "false", "", "yes", 0, 1, 2, -1, 1.0, 0.0, None, [], [True], (True,), {}, object(), b"1"):
            r = create_voice_identity_profile(valid(enabled=bad))
            self.assertFalse(r.ok, bad)
            self.assertEqual(r.codes(), [vp.FAILURE_INVALID_ENABLED], bad)
            self.assertEqual(r.failures[0]["field"], "enabled")

    def test_14_a_str_subclass_is_rejected_and_its_methods_never_run(self):
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

        for field in STR_FIELDS:
            r = create_voice_identity_profile(valid(**{field: Sneaky("x")}))
            self.assertEqual(r.codes(), [code_for(field)])
        self.assertEqual(calls, [])

    def test_15_a_bool_subclass_is_impossible_and_int_lookalikes_are_rejected(self):
        with self.assertRaises(TypeError):
            type("B", (bool,), {})
        import enum

        class Flag(enum.IntEnum):
            ON = 1
        self.assertEqual(create_voice_identity_profile(valid(enabled=Flag.ON)).codes(), [vp.FAILURE_INVALID_ENABLED])

    def test_16_fields_are_validated_independently(self):
        r = create_voice_identity_profile(valid(display_name=7))
        self.assertEqual(r.codes(), [vp.FAILURE_INVALID_DISPLAY_NAME])
        r = create_voice_identity_profile(valid(profile_id="", enabled="x"))
        self.assertEqual(r.codes(), [vp.FAILURE_INVALID_PROFILE_ID, vp.FAILURE_INVALID_ENABLED])


class TestInputShape(unittest.TestCase):
    def test_17_non_dict_input_is_rejected_including_dict_subclasses(self):
        class D(dict):
            pass

        from collections import OrderedDict
        for bad in (None, [], (), "x", 1, True, valid().items(), [("profile_id", "a")], D(valid()), OrderedDict(valid())):
            r = create_voice_identity_profile(bad)
            self.assertFalse(r.ok)
            self.assertEqual(r.codes(), [vp.FAILURE_INVALID_INPUT])
            self.assertEqual(r.failures[0]["field"], None)

    def test_18_missing_fields_are_rejected_and_nothing_is_defaulted(self):
        for field in FIELDS:
            data = valid()
            del data[field]
            r = create_voice_identity_profile(data)
            self.assertEqual(r.codes(), [vp.FAILURE_MISSING_FIELD])
            self.assertEqual(r.failures[0]["field"], field)
        self.assertEqual(create_voice_identity_profile({}).codes(), [vp.FAILURE_MISSING_FIELD] * 4)

    def test_19_unexpected_fields_are_rejected_not_ignored_and_sorted(self):
        r = create_voice_identity_profile(valid(zeta=1, alpha=2))
        self.assertEqual(r.codes(), [vp.FAILURE_UNEXPECTED_FIELD] * 2)
        self.assertEqual([f["field"] for f in r.failures], ["alpha", "zeta"])
        self.assertIsNone(r.profile)

    def test_20_biometric_style_extras_are_rejected(self):
        for name in ("audio", "raw_audio", "embedding", "voiceprint", "biometric_sample", "sample_rate", "service", "api_key", "metadata"):
            r = create_voice_identity_profile(valid(**{name: "x"}))
            self.assertEqual(r.codes(), [vp.FAILURE_UNEXPECTED_FIELD], name)

    def test_21_non_string_and_str_subclass_keys_are_rejected(self):
        class K(str):
            pass

        for key in (1, None, b"profile_id", ("profile_id",), K("extra")):
            data = valid()
            data[key] = "x"
            r = create_voice_identity_profile(data)
            self.assertFalse(r.ok, key)
            self.assertIn(vp.FAILURE_UNEXPECTED_FIELD, r.codes())
        data = valid()
        del data["profile_id"]
        data[K("profile_id")] = "x"
        r = create_voice_identity_profile(data)          # the subclass key still finds the real field, but is itself an unexpected key
        self.assertFalse(r.ok)
        self.assertEqual(r.codes(), [vp.FAILURE_UNEXPECTED_FIELD])

    def test_22_near_miss_field_names_are_unexpected_and_the_real_field_is_missing(self):
        for near in ("Profile_Id", "profileId", "profile_id ", "displayname", "Enabled", "enrollment"):
            data = valid()
            real = next(f for f in FIELDS if near.lower().replace("_", "").startswith(f.lower().replace("_", "")[:5]))
            del data[real]
            data[near] = "x"
            r = create_voice_identity_profile(data)
            self.assertFalse(r.ok, near)
            self.assertIn(vp.FAILURE_UNEXPECTED_FIELD, r.codes())
            self.assertIn(vp.FAILURE_MISSING_FIELD, r.codes())


class TestFailureReporting(unittest.TestCase):
    def test_23_every_problem_is_reported_at_once_in_field_order(self):
        r = create_voice_identity_profile({"profile_id": 1, "display_name": "", "enabled": "no", "enrollment_status": None})
        self.assertEqual(r.codes(), [vp.FAILURE_INVALID_PROFILE_ID, vp.FAILURE_INVALID_DISPLAY_NAME, vp.FAILURE_INVALID_ENABLED,
                                     vp.FAILURE_INVALID_ENROLLMENT_STATUS])

    def test_24_input_then_unexpected_then_fields_ordering(self):
        r = create_voice_identity_profile({"b_extra": 1, "a_extra": 2, "display_name": 5, "profile_id": "p"})
        self.assertEqual(r.codes(), [vp.FAILURE_UNEXPECTED_FIELD, vp.FAILURE_UNEXPECTED_FIELD, vp.FAILURE_INVALID_DISPLAY_NAME,
                                     vp.FAILURE_MISSING_FIELD, vp.FAILURE_MISSING_FIELD])
        self.assertEqual([f["field"] for f in r.failures], ["a_extra", "b_extra", "display_name", "enabled", "enrollment_status"])

    def test_25_the_factory_never_raises_for_bad_data(self):
        class Boom(dict):
            def __iter__(self):
                raise RuntimeError("boom")

        weird = (None, 0, "", b"", [], {}, {"": ""}, {1: 1}, {None: None}, Boom(), object(), float("nan"), {"enabled": float("nan")})
        for bad in weird:
            r = create_voice_identity_profile(bad)
            self.assertIs(type(r), VoiceIdentityProfileResult)
            self.assertFalse(r.ok)

    def test_26_failures_are_deterministic_across_calls(self):
        data = {"profile_id": 1, "x": 2, "enabled": 3}
        self.assertEqual(create_voice_identity_profile(data).to_dict(), create_voice_identity_profile(dict(data)).to_dict())

    def test_27_failure_codes_are_unique_prefixed_and_stable(self):
        self.assertEqual(len(set(vp.FAILURE_CODES)), len(vp.FAILURE_CODES))
        self.assertEqual(len(vp.FAILURE_CODES), 7)
        for c in vp.FAILURE_CODES:
            self.assertTrue(c.startswith("VOICE_IDENTITY_PROFILE_"), c)
        self.assertEqual(vp.FAILURE_CODES, (
            "VOICE_IDENTITY_PROFILE_INVALID_INPUT", "VOICE_IDENTITY_PROFILE_UNEXPECTED_FIELD", "VOICE_IDENTITY_PROFILE_MISSING_FIELD",
            "VOICE_IDENTITY_PROFILE_INVALID_PROFILE_ID", "VOICE_IDENTITY_PROFILE_INVALID_DISPLAY_NAME",
            "VOICE_IDENTITY_PROFILE_INVALID_ENABLED", "VOICE_IDENTITY_PROFILE_INVALID_ENROLLMENT_STATUS"))

    def test_28_result_shape_to_dict_and_fresh_failures(self):
        ok = create_voice_identity_profile(valid())
        self.assertEqual(ok.to_dict(), {"ok": True, "profile": valid(), "failures": []})
        bad = create_voice_identity_profile(valid(enabled="x"))
        d = bad.to_dict()
        self.assertEqual(list(d), ["ok", "profile", "failures"])
        self.assertEqual((d["ok"], d["profile"]), (False, None))
        self.assertEqual(list(d["failures"][0]), ["code", "field", "message"])
        d["failures"][0]["code"] = "changed"
        self.assertEqual(bad.failures[0]["code"], vp.FAILURE_INVALID_ENABLED)

    def test_29_result_ok_and_codes_are_consistent(self):
        self.assertFalse(VoiceIdentityProfileResult().ok)
        self.assertEqual(VoiceIdentityProfileResult().codes(), [])
        p = create_voice_identity_profile(valid()).profile
        self.assertTrue(VoiceIdentityProfileResult(profile=p).ok)
        self.assertFalse(VoiceIdentityProfileResult(profile=p, failures=[{"code": "X", "field": None, "message": "m"}]).ok)


class TestImmutability(unittest.TestCase):
    def test_30_equal_data_gives_equal_objects_and_hashes(self):
        a = create_voice_identity_profile(valid()).profile
        b = create_voice_identity_profile(valid()).profile
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b}), 1)
        self.assertEqual({a: 1}[b], 1)
        self.assertEqual(hash(a), hash(a))

    def test_31_any_differing_field_breaks_equality(self):
        base = create_voice_identity_profile(valid()).profile
        for over in ({"profile_id": "other"}, {"display_name": "Other"}, {"enabled": False}, {"enrollment_status": "enrolled"}):
            other = create_voice_identity_profile(valid(**over)).profile
            self.assertNotEqual(base, other, over)
            self.assertEqual(len({base, other}), 2)

    def test_32_equality_is_exact_type_only(self):
        p = create_voice_identity_profile(valid()).profile
        self.assertNotEqual(p, valid())
        self.assertNotEqual(p, tuple(valid().values()))
        self.assertNotEqual(p, None)
        self.assertFalse(p == p.to_dict())
        self.assertTrue(p == p)

    def test_33_enabled_true_and_false_hash_and_compare_distinctly(self):
        t = create_voice_identity_profile(valid(enabled=True)).profile
        f = create_voice_identity_profile(valid(enabled=False)).profile
        self.assertNotEqual(t, f)
        self.assertEqual(len({t, f}), 2)

    def test_34_to_dict_returns_exactly_the_four_fields_fresh_and_round_trips(self):
        p = create_voice_identity_profile(valid()).profile
        d = p.to_dict()
        self.assertIs(type(d), dict)
        self.assertEqual(d, valid())
        self.assertEqual(list(d), list(FIELDS))
        self.assertIsNot(p.to_dict(), d)
        d["profile_id"] = "mutated"
        d["extra"] = 1
        self.assertEqual(p.to_dict(), valid())
        self.assertEqual(create_voice_identity_profile(p.to_dict()).profile, p)
        self.assertEqual(json.loads(json.dumps(p.to_dict())), valid())
        self.assertIs(p.to_dict()["enabled"], True)

    def test_35_attributes_cannot_be_assigned_deleted_or_added(self):
        p = create_voice_identity_profile(valid()).profile
        for name in FIELDS + ("_profile_id", "_display_name", "_enabled", "_enrollment_status", "extra", "__class__", "__dict__"):
            with self.assertRaises(AttributeError, msg=name):
                setattr(p, name, "x")
            with self.assertRaises(AttributeError, msg=name):
                delattr(p, name)
        with self.assertRaises(AttributeError):
            p.enabled = False
        with self.assertRaises(AttributeError):
            del p.profile_id
        self.assertFalse(hasattr(p, "__dict__"))
        self.assertEqual(p.to_dict(), valid())

    def test_36_direct_construction_and_subclassing_are_refused(self):
        with self.assertRaises(TypeError):
            VoiceIdentityProfile("voice_1", "Main User", True, "not_enrolled")
        with self.assertRaises(TypeError):
            VoiceIdentityProfile(object(), "voice_1", "Main User", True, "not_enrolled")
        with self.assertRaises(TypeError):
            VoiceIdentityProfile(None, "voice_1", "Main User", True, "not_enrolled")
        with self.assertRaises(TypeError):
            VoiceIdentityProfile()
        with self.assertRaises(TypeError):
            class Sub(VoiceIdentityProfile):
                pass

    def test_37_copy_and_deepcopy_return_the_same_object(self):
        p = create_voice_identity_profile(valid()).profile
        self.assertIs(copy.copy(p), p)
        self.assertIs(copy.deepcopy(p), p)
        self.assertIs(copy.deepcopy({"k": [p]})["k"][0], p)
        self.assertEqual(copy.copy(p).to_dict(), p.to_dict())
        self.assertEqual(hash(copy.deepcopy(p)), hash(p))

    def test_38_pickle_is_refused_for_every_protocol(self):
        p = create_voice_identity_profile(valid()).profile
        for proto in range(pickle.HIGHEST_PROTOCOL + 1):
            with self.assertRaises(TypeError):
                pickle.dumps(p, proto)

    def test_39_repr_is_stable_and_shows_exactly_the_four_fields(self):
        p = create_voice_identity_profile(valid()).profile
        self.assertEqual(repr(p), "VoiceIdentityProfile(profile_id='voice_1', display_name='Main User', enabled=True, enrollment_status='not_enrolled')")
        self.assertEqual(repr(p), repr(create_voice_identity_profile(valid()).profile))

    def test_40_the_result_carrier_does_not_affect_the_immutable_profile(self):
        r = create_voice_identity_profile(valid())
        p = r.profile
        r.profile = None
        r.failures.append({"code": "X", "field": None, "message": "m"})
        self.assertEqual(p.to_dict(), valid())


class TestScopeAndHygiene(unittest.TestCase):
    def test_41_module_imports_nothing_and_does_no_io_or_networking(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        self.assertEqual([n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))], [])
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & {"open", "eval", "exec", "compile", "__import__", "input", "print", "globals", "locals", "setattr", "delattr"})

    def test_42_module_has_no_mutable_module_level_state(self):
        for name, value in vars(vp).items():
            if name.startswith("__"):
                continue
            self.assertNotIsInstance(value, (list, dict, set, bytearray), name)

    def test_43_the_profile_stores_no_audio_embedding_biometric_or_service_data(self):
        self.assertEqual(VoiceIdentityProfile.__slots__, ("_profile_id", "_display_name", "_enabled", "_enrollment_status"))
        public = sorted(n for n in dir(VoiceIdentityProfile) if not n.startswith("_"))
        self.assertEqual(public, ["display_name", "enabled", "enrollment_status", "profile_id", "to_dict"])
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        idents = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for token in ("socket", "urllib", "http", "requests", "subprocess", "sqlite3", "os", "sys", "random", "time", "datetime", "wave", "numpy"):
            self.assertNotIn(token, idents, token)

    def test_44_voice_package_contains_only_the_expected_files(self):
        entries = sorted(e for e in os.listdir(os.path.join(PY_ROOT, "voice")) if e != "__pycache__")
        self.assertEqual(entries, ["__init__.py", "voice_enrollment_batch.py", "voice_enrollment_batch_summary.py", "voice_enrollment_dispatcher.py", "voice_enrollment_executor.py", "voice_enrollment_pipeline.py", "voice_enrollment_plan.py", "voice_enrollment_request.py", "voice_enrollment_result.py", "voice_enrollment_result_validator.py", "voice_identity_profile.py", "voice_identity_profile_registry.py", "voice_verification_authorization.py", "voice_verification_batch.py", "voice_verification_batch_summary.py", "voice_verification_decision.py", "voice_verification_dispatcher.py", "voice_verification_execution.py", "voice_verification_execution_request.py", "voice_verification_executor.py", "voice_verification_handoff.py", "voice_verification_pipeline.py", "voice_verification_plan.py", "voice_verification_profile_resolver.py", "voice_verification_registry.py", "voice_verification_request.py", "voice_verification_request_validator.py", "voice_verification_result.py"])      # Prompts 788 (registry), 789 (enrollment request), 790 (enrollment result) 791 (result validator) and 792 (enrollment plan) and 793 (executor) add modules
        with open(os.path.join(PY_ROOT, "voice", "__init__.py"), "rb") as fh:
            self.assertEqual(fh.read(), b"")

    def test_45_no_existing_module_imports_the_voice_package(self):
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if d not in ("voice", "tests", "__pycache__")]
            for name in files:
                if not name.endswith(".py"):
                    continue
                with open(os.path.join(folder, name), encoding="utf-8") as fh:
                    tree = ast.parse(fh.read())
                for n in ast.walk(tree):
                    mods = []
                    if isinstance(n, ast.Import):
                        mods = [a.name for a in n.names]
                    elif isinstance(n, ast.ImportFrom):
                        mods = [n.module or ""]
                    for m in mods:
                        self.assertNotEqual(m.split(".")[0], "voice", os.path.join(folder, name))

    def test_46_doc_exists_and_mentions_the_contract_and_limits(self):
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for needle in ("Prompt 787", "VoiceIdentityProfile", "create_voice_identity_profile", "VOICE_IDENTITY_PROFILE_", "Prompt 788", "NOT",
                       "raw audio", "embeddings", "biometric"):
            self.assertIn(needle, text, needle)

    def test_47_pristine_database_is_untouched(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)


if __name__ == "__main__":
    unittest.main()
