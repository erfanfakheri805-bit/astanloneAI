"""Prompt 807 - Section 10 voice verification registry (`voice.voice_verification_registry`)."""
import ast
import copy
import hashlib
import os
import pickle
import unittest

from voice import voice_verification_registry as reg
from voice.voice_identity_profile import VoiceIdentityProfile, create_voice_identity_profile
from voice.voice_verification_registry import (VoiceVerificationLookupResult, VoiceVerificationRegistry, VoiceVerificationRegistryResult,
                                               create_voice_verification_registry)

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section10_voice_verification_registry_prompt807.md")
MODULE = os.path.join(PY_ROOT, "voice", "voice_verification_registry.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"


def prof(profile_id="voice_1", **over):
    data = {"profile_id": profile_id, "display_name": "Name " + profile_id, "enabled": True, "enrollment_status": "not_enrolled"}
    data.update(over)
    r = create_voice_identity_profile(data)
    assert r.ok, r.failures
    return r.profile


def three():
    return (prof("a"), prof("b"), prof("c"))


class TestValidRegistry(unittest.TestCase):
    def test_1_valid_ordered_profiles_build_a_registry(self):
        items = (prof("c"), prof("a"), prof("b"))
        r = create_voice_verification_registry(items)
        self.assertIs(type(r), VoiceVerificationRegistryResult)
        self.assertTrue(r.ok)
        self.assertEqual((r.failures, r.codes()), ([], []))
        self.assertIs(type(r.registry), VoiceVerificationRegistry)
        self.assertEqual(r.registry.profiles, items)
        self.assertEqual(r.registry.profile_ids, ("c", "a", "b"))
        self.assertEqual([p["profile_id"] for p in r.registry.to_dict()["profiles"]], ["c", "a", "b"])

    def test_2_the_registered_objects_are_the_very_same_profiles(self):
        items = three()
        for given, stored in zip(items, create_voice_verification_registry(items).registry.profiles):
            self.assertIs(given, stored)

    def test_3_empty_tuple_is_valid(self):
        r = create_voice_verification_registry(())
        self.assertTrue(r.ok)
        self.assertEqual((r.registry.profiles, r.registry.profile_ids), ((), ()))
        self.assertEqual(r.registry.to_dict(), {"profiles": []})
        self.assertEqual(r.registry.lookup("x").codes(), [reg.FAILURE_PROFILE_NOT_FOUND])

    def test_4_ids_differing_by_case_or_whitespace_are_distinct(self):
        r = create_voice_verification_registry((prof("a"), prof("A"), prof("a "), prof(" a")))
        self.assertTrue(r.ok, r.failures)
        self.assertEqual(r.registry.profile_ids, ("a", "A", "a ", " a"))

    def test_5_disabled_and_other_metadata_profiles_are_accepted_unchanged(self):
        items = (prof("a", enabled=False), prof("b", enrollment_status="enrolled"))
        self.assertEqual(create_voice_verification_registry(items).registry.profiles, items)


class TestInvalidCollections(unittest.TestCase):
    def test_6_only_an_exact_tuple_is_accepted(self):
        p = prof("a")
        gen = (x for x in (p,))
        for bad in ([p], [], {p}, frozenset([p]), {"a": p}, "abc", b"abc", None, 5, 1.5, True, p, gen, iter((p,)), range(2)):
            r = create_voice_verification_registry(bad)
            self.assertFalse(r.ok, repr(bad))
            self.assertIsNone(r.registry)
            self.assertEqual(r.codes(), [reg.FAILURE_INVALID_COLLECTION], repr(bad))
            self.assertEqual(r.failures[0]["field"], "profiles")
        self.assertEqual(next(gen), p)      # the generator was not consumed

    def test_7_tuple_subclasses_are_rejected(self):
        class T(tuple):
            pass

        class N(tuple):
            __slots__ = ()
        p = prof("a")
        for bad in (T((p,)), T(), N((p, prof("b")))):
            r = create_voice_verification_registry(bad)
            self.assertIsNone(r.registry)
            self.assertEqual(r.codes(), [reg.FAILURE_INVALID_COLLECTION], repr(bad))

    def test_8_a_tuple_subclass_is_never_iterated(self):
        calls = []

        class Evil(tuple):
            def __iter__(self):
                calls.append("iter")
                return super().__iter__()

            def __len__(self):
                calls.append("len")
                return 0
        self.assertEqual(create_voice_verification_registry(Evil((prof("a"),))).codes(), [reg.FAILURE_INVALID_COLLECTION])
        self.assertEqual(calls, [])


class TestInvalidItems(unittest.TestCase):
    def test_9_wrong_item_types_including_none_are_rejected_by_position(self):
        p = prof("a")
        r = create_voice_verification_registry((p, "b", None, 3, {"profile_id": "x"}))
        self.assertEqual(r.codes(), [reg.FAILURE_INVALID_PROFILE] * 4)
        self.assertEqual([f["message"] for f in r.failures], ["profiles[%d] must be a VoiceIdentityProfile." % i for i in (1, 2, 3, 4)])
        self.assertIsNone(r.registry)

    def test_10_spoofed_class_objects_are_rejected(self):
        class Spoof:
            __class__ = VoiceIdentityProfile
            profile_id, display_name, enabled, enrollment_status = "s", "S", True, "x"

            def to_dict(self):
                return {"profile_id": "s", "display_name": "S", "enabled": True, "enrollment_status": "x"}

        class DynamicSpoof:
            @property
            def __class__(self):
                return VoiceIdentityProfile
            profile_id = "d"
        for bad in (Spoof(), DynamicSpoof()):
            self.assertTrue(isinstance(bad, VoiceIdentityProfile))      # isinstance is fooled; the registry must not be
            r = create_voice_verification_registry((bad,))
            self.assertEqual(r.codes(), [reg.FAILURE_INVALID_PROFILE])
            self.assertIsNone(r.registry)
        self.assertEqual(create_voice_verification_registry((prof("a"), Spoof())).codes(), [reg.FAILURE_INVALID_PROFILE])

    def test_11_look_alikes_and_unbuilt_profiles_are_rejected(self):
        class Fake:
            profile_id, display_name, enabled, enrollment_status = "f", "F", True, "x"

            def to_dict(self):
                return {}
        for bad in (Fake(), object(), (prof("a"),), [prof("a")], prof("a").to_dict(), create_voice_identity_profile({"profile_id": "z"})):
            r = create_voice_verification_registry((bad,))
            self.assertEqual(r.codes(), [reg.FAILURE_INVALID_PROFILE], repr(bad))

    def test_12_a_profile_look_alike_from_the_enrollment_or_verification_chain_is_rejected(self):
        from voice.voice_verification_request import create_voice_verification_request
        made = create_voice_verification_request({"request_id": "r", "profile_id": "a", "verification_mode": "m"})
        obj = made.request if hasattr(made, "request") else made
        self.assertEqual(create_voice_verification_registry((obj,)).codes(), [reg.FAILURE_INVALID_PROFILE])

    def test_13_every_bad_item_is_reported_in_input_order(self):
        r = create_voice_verification_registry((1, prof("a"), 2, prof("b"), 3))
        self.assertEqual([f["message"][:11] for f in r.failures], ["profiles[0]", "profiles[2]", "profiles[4]"])
        self.assertIsNone(r.registry)


class TestDuplicates(unittest.TestCase):
    def test_14_duplicate_ids_are_rejected_deterministically(self):
        items = (prof("a"), prof("b"), prof("a", display_name="Other"))
        r1, r2 = create_voice_verification_registry(items), create_voice_verification_registry(items)
        self.assertFalse(r1.ok)
        self.assertIsNone(r1.registry)
        self.assertEqual(r1.codes(), [reg.FAILURE_DUPLICATE_PROFILE_ID])
        self.assertIn("profiles[2]", r1.failures[0]["message"])
        self.assertIn("'a'", r1.failures[0]["message"])
        self.assertEqual(r1.to_dict(), r2.to_dict())

    def test_15_the_same_object_twice_and_equal_objects_are_duplicates(self):
        p = prof("a")
        self.assertEqual(create_voice_verification_registry((p, p)).codes(), [reg.FAILURE_DUPLICATE_PROFILE_ID])
        self.assertEqual(create_voice_verification_registry((prof("a"), prof("a"))).codes(), [reg.FAILURE_DUPLICATE_PROFILE_ID])

    def test_16_each_extra_repeat_is_reported(self):
        a = prof("a")
        self.assertEqual(create_voice_verification_registry((a, a, a, prof("b"), prof("b"))).codes(), [reg.FAILURE_DUPLICATE_PROFILE_ID] * 3)

    def test_17_a_bad_item_is_not_also_counted_as_a_duplicate_and_mixed_problems_keep_order(self):
        r = create_voice_verification_registry((prof("a"), "a", prof("a"), None))
        self.assertEqual(r.codes(), [reg.FAILURE_INVALID_PROFILE, reg.FAILURE_DUPLICATE_PROFILE_ID, reg.FAILURE_INVALID_PROFILE])


class TestOrderingAndImmutability(unittest.TestCase):
    def test_18_a_different_order_is_a_different_registry(self):
        c, a, b = prof("c"), prof("a"), prof("b")
        r1 = create_voice_verification_registry((c, a, b)).registry
        r2 = create_voice_verification_registry((a, b, c)).registry
        self.assertEqual(r1.profile_ids, ("c", "a", "b"))
        self.assertNotEqual(r1, r2)

    def test_19_profiles_and_profile_ids_are_immutable_tuples(self):
        r = create_voice_verification_registry(three()).registry
        self.assertIs(type(r.profiles), tuple)
        self.assertIs(type(r.profile_ids), tuple)
        with self.assertRaises(TypeError):
            r.profiles[0] = prof("z")
        with self.assertRaises(TypeError):
            r.profile_ids[0] = "z"
        self.assertIsNot(r.profile_ids, r.profile_ids)      # fresh on every access
        self.assertEqual(r.profile_ids, r.profile_ids)

    def test_20_registry_attributes_cannot_be_assigned_deleted_or_added(self):
        r = create_voice_verification_registry(three()).registry
        for name in ("profiles", "profile_ids", "_profiles", "lookup", "to_dict", "extra"):
            with self.assertRaises(AttributeError):
                setattr(r, name, ())
            with self.assertRaises(AttributeError):
                delattr(r, name)
        self.assertFalse(hasattr(r, "__dict__"))
        self.assertEqual([n for n in dir(r) if not n.startswith("_")], ["lookup", "profile_ids", "profiles", "to_dict"])
        self.assertIs(type(r._profiles), tuple)

    def test_21_stored_profiles_stay_immutable(self):
        p = create_voice_verification_registry(three()).registry.profiles[0]
        with self.assertRaises(AttributeError):
            p.enabled = False


class TestNonRetention(unittest.TestCase):
    def test_22_the_callers_tuple_is_not_retained_or_aliased(self):
        items = three()
        before = tuple(items)
        r = create_voice_verification_registry(items).registry
        self.assertEqual(items, before)
        self.assertIsNot(r.profiles, items)
        self.assertIsNot(r._profiles, items)
        self.assertEqual(r.profiles, before)

    def test_23_the_failure_result_does_not_retain_the_input(self):
        bad = (prof("a"), prof("a"))
        r = create_voice_verification_registry(bad)
        self.assertIsNone(r.registry)
        for f in r.failures:
            for value in f.values():
                self.assertIsNot(value, bad)
        self.assertEqual(set(r.failures[0]), {"code", "field", "message"})

    def test_24_lookup_results_share_the_profile_but_never_the_registry_internals(self):
        r = create_voice_verification_registry(three()).registry
        found = r.lookup("a")
        self.assertIs(found.profile, r.profiles[0])
        found.failures.append("x")
        self.assertEqual(r.lookup("a").failures, [])
        self.assertEqual(r.to_dict(), create_voice_verification_registry(three()).registry.to_dict())


class TestLookup(unittest.TestCase):
    def setUp(self):
        self.items = three()
        self.registry = create_voice_verification_registry(self.items).registry

    def test_25_lookup_success_returns_the_registered_object(self):
        for item in self.items:
            r = self.registry.lookup(item.profile_id)
            self.assertIs(type(r), VoiceVerificationLookupResult)
            self.assertTrue(r.found)
            self.assertIs(r.profile, item)
            self.assertEqual((r.failures, r.codes()), ([], []))

    def test_26_a_missing_id_gives_a_deterministic_not_found_result(self):
        r = self.registry.lookup("zzz")
        self.assertFalse(r.found)
        self.assertIsNone(r.profile)
        self.assertEqual(r.codes(), [reg.FAILURE_PROFILE_NOT_FOUND])
        self.assertEqual(r.failures, self.registry.lookup("zzz").failures)
        self.assertEqual(set(r.failures[0]), {"code", "field", "message"})

    def test_27_exact_matching_only_no_trim_casefold_or_normalization(self):
        for text in ("A", "a ", " a", "\ta", "a\n", "", "ａ"):
            self.assertEqual(self.registry.lookup(text).codes(), [reg.FAILURE_PROFILE_NOT_FOUND], repr(text))
        accent = create_voice_verification_registry((prof("é"),)).registry
        self.assertEqual(accent.lookup("e\u0301").codes(), [reg.FAILURE_PROFILE_NOT_FOUND])
        self.assertTrue(accent.lookup("é").found)

    def test_28_non_str_ids_are_invalid_and_never_coerced(self):
        class S(str):
            pass
        for bad in (None, b"a", 1, 1.5, True, ("a",), ["a"], S("a"), object()):
            r = self.registry.lookup(bad)
            self.assertFalse(r.found, repr(bad))
            self.assertIsNone(r.profile)
            self.assertEqual(r.codes(), [reg.FAILURE_INVALID_PROFILE_ID], repr(bad))

    def test_29_a_str_subclass_method_is_never_called(self):
        calls = []

        class Evil(str):
            def __eq__(self, other):
                calls.append("eq")
                return True

            def __hash__(self):
                calls.append("hash")
                return 0

            def __ne__(self, other):
                calls.append("ne")
                return False
        self.assertEqual(self.registry.lookup(Evil("a")).codes(), [reg.FAILURE_INVALID_PROFILE_ID])
        self.assertEqual(calls, [])

    def test_30_lookup_does_not_search_other_fields(self):
        r = create_voice_verification_registry((prof("a", display_name="Zed", enrollment_status="enrolled"),)).registry
        for text in ("Zed", "enrolled", "True", "Name a"):
            self.assertEqual(r.lookup(text).codes(), [reg.FAILURE_PROFILE_NOT_FOUND])

    def test_31_lookup_never_changes_the_registry_and_result_shapes(self):
        before = self.registry.to_dict()
        found, missing, invalid = self.registry.lookup("a"), self.registry.lookup("q"), self.registry.lookup(None)
        self.assertEqual(self.registry.to_dict(), before)
        self.assertEqual(found.to_dict(), {"found": True, "profile": self.items[0].to_dict(), "failures": []})
        self.assertEqual(missing.to_dict()["profile"], None)
        self.assertEqual(missing.to_dict()["failures"][0]["code"], reg.FAILURE_PROFILE_NOT_FOUND)
        self.assertEqual(invalid.to_dict()["failures"][0]["code"], reg.FAILURE_INVALID_PROFILE_ID)
        missing.to_dict()["failures"][0]["code"] = "x"
        self.assertEqual(missing.to_dict()["failures"][0]["code"], reg.FAILURE_PROFILE_NOT_FOUND)
        self.assertEqual(VoiceVerificationLookupResult.__slots__, ("found", "profile", "failures"))


class TestFailureCodes(unittest.TestCase):
    def test_32_codes_are_unique_prefixed_and_stable(self):
        self.assertEqual(reg.FAILURE_CODES, (
            "VOICE_VERIFICATION_REGISTRY_INVALID_COLLECTION", "VOICE_VERIFICATION_REGISTRY_INVALID_PROFILE",
            "VOICE_VERIFICATION_REGISTRY_DUPLICATE_PROFILE_ID", "VOICE_VERIFICATION_REGISTRY_PROFILE_NOT_FOUND",
            "VOICE_VERIFICATION_REGISTRY_INVALID_PROFILE_ID"))
        self.assertEqual(len(set(reg.FAILURE_CODES)), 5)
        self.assertEqual(reg.FACTORY_FAILURE_CODES + reg.LOOKUP_FAILURE_CODES, reg.FAILURE_CODES)

    def test_33_the_factory_never_raises_and_is_deterministic(self):
        class Boom:
            def __getattr__(self, name):
                raise RuntimeError(name)
        weird = (None, 0, "x", [], {}, (), Boom(), (Boom(),), (None, prof("a"), prof("a")), (prof("a"), 1))
        for bad in weird:
            r1, r2 = create_voice_verification_registry(bad), create_voice_verification_registry(bad)
            self.assertEqual(r1.to_dict(), r2.to_dict())
            self.assertEqual(r1.codes(), r2.codes())

    def test_34_result_shapes(self):
        ok, bad = create_voice_verification_registry(three()), create_voice_verification_registry([])
        self.assertEqual(ok.to_dict()["ok"], True)
        self.assertEqual(ok.to_dict()["failures"], [])
        self.assertEqual(ok.to_dict()["registry"], {"profiles": [p.to_dict() for p in three()]})
        self.assertEqual(bad.to_dict()["registry"], None)
        self.assertFalse(bad.to_dict()["ok"])
        self.assertEqual(VoiceVerificationRegistryResult.__slots__, ("registry", "failures"))
        self.assertFalse(VoiceVerificationRegistryResult().ok)


class TestEqualityAndSerialization(unittest.TestCase):
    def test_35_equal_profiles_in_the_same_order_give_equal_registries_and_hashes(self):
        r1 = create_voice_verification_registry((prof("a"), prof("b"))).registry
        r2 = create_voice_verification_registry((prof("a"), prof("b"))).registry
        self.assertIsNot(r1, r2)
        self.assertEqual((r1, hash(r1)), (r2, hash(r2)))
        self.assertEqual(len({r1, r2}), 1)
        self.assertNotEqual(r1, create_voice_verification_registry((prof("a"), prof("b", enabled=False))).registry)
        self.assertNotEqual(r1, create_voice_verification_registry((prof("a"),)).registry)
        self.assertEqual(hash(create_voice_verification_registry(()).registry), hash(create_voice_verification_registry(()).registry))

    def test_36_equality_is_exact_type_only(self):
        from voice.voice_identity_profile_registry import create_voice_identity_profile_registry
        r = create_voice_verification_registry(three()).registry
        sibling = create_voice_identity_profile_registry(three()).registry
        for other in (three(), list(three()), r.to_dict(), None, "x", sibling):
            self.assertNotEqual(r, other)
            self.assertIs(r.__eq__(other), NotImplemented)

    def test_37_to_dict_is_fresh_and_exposes_no_internal_state(self):
        r = create_voice_verification_registry(three()).registry
        d1, d2 = r.to_dict(), r.to_dict()
        self.assertEqual(d1, d2)
        self.assertIsNot(d1, d2)
        self.assertIsNot(d1["profiles"], d2["profiles"])
        self.assertIsNot(d1["profiles"][0], d2["profiles"][0])
        d1["profiles"][0]["enabled"] = False
        d1["profiles"].append({})
        d1["extra"] = 1
        self.assertEqual(r.to_dict(), d2)
        self.assertEqual(list(r.to_dict()), ["profiles"])
        self.assertEqual(r.profiles[0].enabled, True)
        rebuilt = tuple(create_voice_identity_profile(d).profile for d in d2["profiles"])
        self.assertEqual(create_voice_verification_registry(rebuilt).registry, r)

    def test_38_repr_is_deterministic(self):
        self.assertEqual(repr(create_voice_verification_registry(three()).registry), "VoiceVerificationRegistry(profile_ids=('a', 'b', 'c'))")


class TestConstructionCopyPickle(unittest.TestCase):
    def test_39_direct_construction_and_subclassing_are_refused(self):
        for args in ((object(), three()), (None, three()), ()):
            with self.assertRaises(TypeError):
                VoiceVerificationRegistry(*args)
        with self.assertRaises(TypeError):
            class Sub(VoiceVerificationRegistry):
                pass

    def test_40_copy_and_deepcopy_return_the_same_object(self):
        r = create_voice_verification_registry(three()).registry
        self.assertIs(copy.copy(r), r)
        self.assertIs(copy.deepcopy(r), r)
        self.assertIs(copy.deepcopy({"k": [r]})["k"][0], r)

    def test_41_pickle_is_refused_for_every_protocol(self):
        r = create_voice_verification_registry(three()).registry
        for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
            with self.assertRaises(TypeError):
                pickle.dumps(r, protocol)
        with self.assertRaises(TypeError):
            r.__reduce__()


class TestBoundaries(unittest.TestCase):
    def test_42_module_imports_only_voice_identity_profile_and_has_no_forbidden_calls_or_state(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(len(imports), 1)
        self.assertIsInstance(imports[0], ast.ImportFrom)
        self.assertEqual((imports[0].module, imports[0].level, [a.name for a in imports[0].names]), ("voice_identity_profile", 1, ["VoiceIdentityProfile"]))
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "getattr", "setattr", "globals", "vars", "sorted", "isinstance"):
            self.assertNotIn(forbidden, calls)
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        self.assertNotIn("__class__", attrs)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.ImportFrom))
        for name, value in vars(reg).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_43_module_names_no_forbidden_dependency_or_biometric_storage(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("os", "sys", "io", "pathlib", "subprocess", "socket", "urllib", "http", "requests", "numpy", "wave", "sqlite3", "random", "time",
                     "datetime", "anthropic", "openai", "core", "agent", "planning", "web", "multimedia", "game_creation", "audio", "embedding",
                     "embeddings", "sample", "samples", "microphone", "android"):
            self.assertNotIn(word, names, word)

    def test_44_voice_package_holds_exactly_the_expected_files(self):
        self.assertEqual(sorted(f for f in os.listdir(os.path.join(PY_ROOT, "voice")) if f != "__pycache__"),
                         ["__init__.py", "voice_enrollment_batch.py", "voice_enrollment_batch_summary.py", "voice_enrollment_dispatcher.py", "voice_enrollment_executor.py", "voice_enrollment_pipeline.py", "voice_enrollment_plan.py", "voice_enrollment_request.py", "voice_enrollment_result.py", "voice_enrollment_result_validator.py", "voice_identity_profile.py", "voice_identity_profile_registry.py", "voice_verification_authorization.py", "voice_verification_batch.py", "voice_verification_batch_summary.py", "voice_verification_decision.py", "voice_verification_dispatcher.py", "voice_verification_execution.py", "voice_verification_execution_request.py", "voice_verification_executor.py", "voice_verification_handoff.py", "voice_verification_pipeline.py", "voice_verification_plan.py", "voice_verification_profile_resolver.py", "voice_verification_registry.py", "voice_verification_request.py", "voice_verification_request_validator.py", "voice_verification_result.py"])
        with open(os.path.join(PY_ROOT, "voice", "__init__.py"), "rb") as fh:
            self.assertEqual(fh.read(), b"")

    def test_45_profile_contract_is_reused_not_duplicated_or_changed(self):
        import voice.voice_identity_profile as vp
        self.assertIs(reg.VoiceIdentityProfile, VoiceIdentityProfile)
        self.assertEqual(vp.FIELDS, ("profile_id", "display_name", "enabled", "enrollment_status"))
        with open(os.path.join(PY_ROOT, "voice", "voice_identity_profile.py"), encoding="utf-8") as fh:
            text = fh.read()
        for token in ("registry", "Registry", "verification", "Verification"):
            self.assertNotIn(token, text)
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        classes = sorted(n.name for n in tree.body if isinstance(n, ast.ClassDef))
        self.assertEqual(classes, ["VoiceVerificationLookupResult", "VoiceVerificationRegistry", "VoiceVerificationRegistryResult"])

    def test_46_earlier_verification_modules_do_not_reference_the_registry(self):
        voice_dir = os.path.join(PY_ROOT, "voice")
        for name in sorted(os.listdir(voice_dir)):
            if name.endswith(".py") and name not in ("voice_verification_registry.py", "voice_verification_profile_resolver.py", "voice_verification_authorization.py"):
                with open(os.path.join(voice_dir, name), encoding="utf-8") as fh:
                    text = fh.read()
                self.assertNotIn("voice_verification_registry", text, name)
                self.assertNotIn("VoiceVerificationRegistry", text, name)

    def test_47_no_other_production_module_or_entry_point_references_the_voice_package(self):
        checked = 0
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if not (folder == PY_ROOT and d in ("voice", "tests", "data")) and d != "__pycache__"]
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        tree = ast.parse(fh.read())
                    for n in ast.walk(tree):
                        mods = [a.name for a in n.names] if isinstance(n, ast.Import) else ([n.module or ""] if isinstance(n, ast.ImportFrom) else [])
                        for m in mods:
                            self.assertNotEqual(m.split(".")[0], "voice", os.path.join(folder, name))
                    checked += 1
        self.assertGreater(checked, 100)
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py", "android_entry.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("VoiceVerificationRegistry", "voice_verification_registry", "from voice", "import voice"):
                self.assertNotIn(token, text, (rel, token))

    def test_48_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("VoiceVerificationRegistry", "create_voice_verification_registry", "VoiceIdentityProfile", "lookup", "VOICE_VERIFICATION_REGISTRY_",
                       "DUPLICATE_PROFILE_ID", "PROFILE_NOT_FOUND", "INVALID_PROFILE_ID", "INVALID_COLLECTION", "INVALID_PROFILE", "does NOT",
                       "raw audio", "embeddings", "biometric", "Prompt 808"):
            self.assertIn(marker, text, marker)


if __name__ == "__main__":
    unittest.main()
