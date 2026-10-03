"""Prompt 808 - Section 10 voice verification profile resolver (`voice.voice_verification_profile_resolver`)."""
import ast
import copy
import hashlib
import os
import pickle
import unittest
from unittest import mock

from voice import voice_verification_profile_resolver as res
from voice import voice_verification_request as vr
from voice.voice_identity_profile import VoiceIdentityProfile, create_voice_identity_profile
from voice.voice_verification_profile_resolver import VoiceVerificationProfileResolutionResult, resolve_voice_verification_profile
from voice.voice_verification_registry import VoiceVerificationRegistry, create_voice_verification_registry
from voice.voice_verification_request import VoiceVerificationRequest, create_voice_verification_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section10_voice_verification_profile_resolver_prompt808.md")
MODULE = os.path.join(PY_ROOT, "voice", "voice_verification_profile_resolver.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
P = "VOICE_VERIFICATION_PROFILE_RESOLVER_"
INVALID_REQUEST, INVALID_REGISTRY, PROFILE_NOT_FOUND = P + "INVALID_REQUEST", P + "INVALID_REGISTRY", P + "PROFILE_NOT_FOUND"


class Str(str):
    pass


def prof(profile_id="voice_1", **over):
    data = {"profile_id": profile_id, "display_name": "Name " + profile_id, "enabled": True, "enrollment_status": "not_enrolled"}
    data.update(over)
    r = create_voice_identity_profile(data)
    assert r.ok, r.failures
    return r.profile


def req(profile_id="voice_1"):
    r = create_voice_verification_request({"request_id": "verify_1", "profile_id": profile_id, "verification_mode": "STANDARD"})
    assert r.ok, r.failures
    return r.request


def raw_request(request_id="r", profile_id="p", verification_mode="m"):
    """A VoiceVerificationRequest with arbitrary internals (only possible inside tests, via the contract module's private token)."""
    return VoiceVerificationRequest(vr._CREATE_TOKEN, request_id, profile_id, verification_mode)


def registry(*ids):
    items = tuple(prof(i) for i in (ids or ("voice_1", "voice_2", "voice_3")))
    r = create_voice_verification_registry(items)
    assert r.ok, r.failures
    return r.registry


class CountingLookup:
    """Patches VoiceVerificationRegistry.lookup at class level (the class is slotted/final, so instances cannot be patched) and counts calls."""

    def __enter__(self):
        self.calls = []
        original = VoiceVerificationRegistry.lookup
        calls = self.calls

        def counting(reg, profile_id):
            calls.append(profile_id)
            return original(reg, profile_id)

        self._patch = mock.patch.object(VoiceVerificationRegistry, "lookup", counting)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()


class TestValidResolution(unittest.TestCase):
    def test_1_valid_request_with_existing_profile_resolves(self):
        out = resolve_voice_verification_profile(req("voice_2"), registry())
        self.assertIs(type(out), VoiceVerificationProfileResolutionResult)
        self.assertTrue(out.ok)
        self.assertEqual((out.failures, out.codes()), ((), []))
        self.assertEqual(out.profile.profile_id, "voice_2")
        self.assertEqual(out.to_dict(), {"ok": True, "profile": out.profile.to_dict(), "failures": []})

    def test_2_the_returned_profile_is_the_registered_object(self):
        items = (prof("a"), prof("b"), prof("c"))
        reg = create_voice_verification_registry(items).registry
        for item in items:
            self.assertIs(resolve_voice_verification_profile(req(item.profile_id), reg).profile, item)

    def test_3_disabled_or_unenrolled_profiles_are_returned_unchanged(self):
        p = prof("x", enabled=False, enrollment_status="revoked")
        reg = create_voice_verification_registry((p,)).registry
        out = resolve_voice_verification_profile(req("x"), reg)
        self.assertTrue(out.ok)
        self.assertIs(out.profile, p)

    def test_4_lookup_is_called_exactly_once_with_the_request_profile_id(self):
        r = req("voice_3")
        with CountingLookup() as counter:
            resolve_voice_verification_profile(r, registry())
        self.assertEqual(len(counter.calls), 1)
        self.assertIs(counter.calls[0], r.profile_id)

    def test_5_resolution_is_deterministic(self):
        reg, r = registry(), req("voice_1")
        a, b = resolve_voice_verification_profile(r, reg), resolve_voice_verification_profile(r, reg)
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertIs(a.profile, b.profile)


class TestMissingProfile(unittest.TestCase):
    def test_6_unknown_profile_id_is_rejected(self):
        out = resolve_voice_verification_profile(req("nobody"), registry())
        self.assertFalse(out.ok)
        self.assertIsNone(out.profile)
        self.assertEqual(out.codes(), [PROFILE_NOT_FOUND])
        self.assertEqual(out.failures[0]["field"], "profile_id")
        self.assertEqual(out.to_dict(), {"ok": False, "profile": None, "failures": [dict(out.failures[0])]})

    def test_7_empty_registry_and_case_or_whitespace_variants_are_not_found(self):
        self.assertEqual(resolve_voice_verification_profile(req("voice_1"), create_voice_verification_registry(()).registry).codes(), [PROFILE_NOT_FOUND])
        for variant in ("VOICE_1", "voice_1 ", " voice_1", "Voice_1"):
            self.assertEqual(resolve_voice_verification_profile(req(variant), registry()).codes(), [PROFILE_NOT_FOUND], variant)

    def test_8_not_found_is_deterministic_and_attempts_one_lookup(self):
        r, reg = req("nobody"), registry()
        with CountingLookup() as counter:
            a = resolve_voice_verification_profile(r, reg)
            b = resolve_voice_verification_profile(r, reg)
        self.assertEqual(len(counter.calls), 2)
        self.assertEqual(a, b)
        self.assertEqual(a.failures, b.failures)
        self.assertEqual(a.failures[0]["message"], "No voice verification profile is registered with profile_id 'nobody'.")


class TestInvalidRequest(unittest.TestCase):
    def test_9_non_request_values_are_rejected_without_lookup(self):
        bad = (None, {}, {"request_id": "r", "profile_id": "voice_1", "verification_mode": "m"}, "voice_1", 1, True, object(), [], ())
        for value in bad:
            with CountingLookup() as counter:
                out = resolve_voice_verification_profile(value, registry())
            self.assertFalse(out.ok, value)
            self.assertIsNone(out.profile)
            self.assertEqual(out.codes(), [INVALID_REQUEST], value)
            self.assertEqual(out.failures[0]["field"], "request")
            self.assertEqual(counter.calls, [], value)

    def test_10_exact_request_with_malformed_internals_is_rejected_without_lookup(self):
        for malformed in (raw_request(profile_id=""), raw_request(profile_id=Str("voice_1")), raw_request(profile_id=None),
                          raw_request(request_id=""), raw_request(verification_mode=1)):
            with CountingLookup() as counter:
                out = resolve_voice_verification_profile(malformed, registry())
            self.assertEqual(out.codes(), [INVALID_REQUEST])
            self.assertIsNone(out.profile)
            self.assertEqual(counter.calls, [])

    def test_11_request_is_checked_before_registry_and_both_are_reported(self):
        out = resolve_voice_verification_profile(None, None)
        self.assertEqual(out.codes(), [INVALID_REQUEST, INVALID_REGISTRY])
        self.assertEqual([f["field"] for f in out.failures], ["request", "registry"])


class TestInvalidRegistry(unittest.TestCase):
    def test_12_non_registry_values_are_rejected_without_lookup(self):
        prof_tuple = (prof("voice_1"),)
        for value in (None, {}, [], prof_tuple, prof("voice_1"), "registry", 1, object()):
            with CountingLookup() as counter:
                out = resolve_voice_verification_profile(req("voice_1"), value)
            self.assertFalse(out.ok, value)
            self.assertIsNone(out.profile)
            self.assertEqual(out.codes(), [INVALID_REGISTRY], value)
            self.assertEqual(out.failures[0]["field"], "registry")
            self.assertEqual(counter.calls, [], value)

    def test_13_registry_result_objects_are_not_registries(self):
        wrapper = create_voice_verification_registry((prof("voice_1"),))
        self.assertEqual(resolve_voice_verification_profile(req("voice_1"), wrapper).codes(), [INVALID_REGISTRY])


class TestSpoofedAndLookAlikes(unittest.TestCase):
    def test_14_spoofed_class_request_is_rejected_without_touching_it(self):
        touched = []

        class SpoofRequest:
            __class__ = VoiceVerificationRequest
            request_id, profile_id, verification_mode = "r", "voice_1", "m"

            def __getattribute__(self, name):
                touched.append(name)
                return object.__getattribute__(self, name)

        with CountingLookup() as counter:
            out = resolve_voice_verification_profile(SpoofRequest(), registry())
        self.assertEqual(out.codes(), [INVALID_REQUEST])
        self.assertEqual(counter.calls, [])
        self.assertNotIn("profile_id", touched)

    def test_15_spoofed_class_registry_is_rejected_and_its_lookup_never_runs(self):
        calls = []

        class SpoofRegistry:
            __class__ = VoiceVerificationRegistry

            def lookup(self, profile_id):
                calls.append(profile_id)
                return None

        out = resolve_voice_verification_profile(req("voice_1"), SpoofRegistry())
        self.assertEqual(out.codes(), [INVALID_REGISTRY])
        self.assertEqual(calls, [])
        self.assertIsNone(out.profile)

    def test_16_look_alike_registry_with_lookup_is_rejected(self):
        calls = []
        real = registry()

        class LookAlike:
            profiles = real.profiles
            profile_ids = real.profile_ids

            def lookup(self, profile_id):
                calls.append(profile_id)
                return real.lookup(profile_id)

        out = resolve_voice_verification_profile(req("voice_1"), LookAlike())
        self.assertEqual(out.codes(), [INVALID_REGISTRY])
        self.assertEqual(calls, [])

    def test_17_look_alike_request_with_same_fields_is_rejected(self):
        class LookAlike:
            request_id, profile_id, verification_mode = "r", "voice_1", "m"

            def to_dict(self):
                return {"request_id": "r", "profile_id": "voice_1", "verification_mode": "m"}

        with CountingLookup() as counter:
            out = resolve_voice_verification_profile(LookAlike(), registry())
        self.assertEqual(out.codes(), [INVALID_REQUEST])
        self.assertEqual(counter.calls, [])

    def test_18_request_and_registry_cannot_be_subclassed_to_look_alike(self):
        with self.assertRaises(TypeError):
            class SubRequest(VoiceVerificationRequest):
                pass
        with self.assertRaises(TypeError):
            class SubRegistry(VoiceVerificationRegistry):
                pass

    def test_19_registry_with_a_spoofed_lookup_result_is_not_trusted(self):
        class FakeResult:
            found = True
            profile = prof("voice_1")

        with mock.patch.object(VoiceVerificationRegistry, "lookup", lambda self, pid: FakeResult()):
            out = resolve_voice_verification_profile(req("voice_1"), registry())
        self.assertFalse(out.ok)
        self.assertEqual(out.codes(), [PROFILE_NOT_FOUND])
        self.assertIsNone(out.profile)

    def test_20_found_result_with_a_non_profile_is_not_trusted(self):
        from voice.voice_verification_registry import VoiceVerificationLookupResult
        with mock.patch.object(VoiceVerificationRegistry, "lookup", lambda self, pid: VoiceVerificationLookupResult(True, {"profile_id": pid})):
            out = resolve_voice_verification_profile(req("voice_1"), registry())
        self.assertEqual(out.codes(), [PROFILE_NOT_FOUND])
        self.assertIsNone(out.profile)


class TestNoMutationOrRegistryInternals(unittest.TestCase):
    def test_21_inputs_are_not_changed(self):
        reg, r = registry(), req("voice_2")
        before = (reg.to_dict(), reg.profiles, r.to_dict())
        resolve_voice_verification_profile(r, reg)
        resolve_voice_verification_profile(req("zzz"), reg)
        self.assertEqual((reg.to_dict(), reg.profiles, r.to_dict()), before)

    def test_22_registry_internals_are_never_read(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for name in ("_profiles", "profiles", "profile_ids", "to_dict_registry", "__dict__", "__class__"):
            self.assertNotIn(name, attrs, name)
        self.assertIn("lookup", attrs)


class TestImmutability(unittest.TestCase):
    def test_23_result_attributes_cannot_be_assigned_or_deleted(self):
        for out in (resolve_voice_verification_profile(req("voice_1"), registry()), resolve_voice_verification_profile(None, None)):
            for name in ("ok", "profile", "failures", "_profile", "_failures", "extra"):
                with self.assertRaises(AttributeError, msg=name):
                    setattr(out, name, 1)
                with self.assertRaises(AttributeError, msg=name):
                    delattr(out, name)
            self.assertFalse(hasattr(out, "__dict__"))

    def test_24_failures_and_to_dict_are_fresh_copies(self):
        out = resolve_voice_verification_profile(req("nobody"), registry())
        out.failures[0]["code"] = "changed"
        d = out.to_dict()
        d["failures"][0]["code"] = "changed"
        d["ok"] = True
        self.assertEqual(out.codes(), [PROFILE_NOT_FOUND])
        self.assertFalse(out.ok)
        self.assertEqual(out.to_dict()["failures"][0]["code"], PROFILE_NOT_FOUND)
        self.assertIsNot(out.failures, out.failures)
        self.assertIsNot(out.to_dict(), out.to_dict())

    def test_25_success_to_dict_does_not_leak_the_profile(self):
        out = resolve_voice_verification_profile(req("voice_1"), registry())
        d = out.to_dict()
        d["profile"]["display_name"] = "changed"
        self.assertEqual(out.profile.display_name, "Name voice_1")
        self.assertEqual(out.to_dict()["profile"]["display_name"], "Name voice_1")

    def test_26_construction_subclassing_copy_and_pickle(self):
        with self.assertRaises(TypeError):
            VoiceVerificationProfileResolutionResult(object(), None, ())
        with self.assertRaises(TypeError):
            VoiceVerificationProfileResolutionResult(None, None, ())
        with self.assertRaises(TypeError):
            VoiceVerificationProfileResolutionResult()
        with self.assertRaises(TypeError):
            class Sub(VoiceVerificationProfileResolutionResult):
                pass
        out = resolve_voice_verification_profile(req("voice_1"), registry())
        self.assertIs(copy.copy(out), out)
        self.assertIs(copy.deepcopy(out), out)
        for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
            with self.assertRaises(TypeError):
                pickle.dumps(out, protocol)

    def test_27_equality_hash_and_repr(self):
        a = resolve_voice_verification_profile(req("voice_1"), registry())
        b = resolve_voice_verification_profile(req("voice_1"), registry())
        c = resolve_voice_verification_profile(req("nobody"), registry())
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertNotEqual(a, c)
        self.assertNotEqual(a, a.to_dict())
        self.assertEqual(len({a, b, c}), 2)
        self.assertEqual(repr(c), "VoiceVerificationProfileResolutionResult(ok=False, codes=['%s'])" % PROFILE_NOT_FOUND)


class TestNonRetention(unittest.TestCase):
    def _reachable(self, out):
        return [getattr(out, "_profile"), getattr(out, "_failures")]

    def test_28_result_holds_only_the_profile_and_plain_failure_data(self):
        self.assertEqual(VoiceVerificationProfileResolutionResult.__slots__, ("_profile", "_failures"))
        reg, r = registry(), req("voice_1")
        for request, regi in ((r, reg), (req("nobody"), reg), (None, None), (r, None), (None, reg)):
            out = resolve_voice_verification_profile(request, regi)
            profile, failures = self._reachable(out)
            self.assertTrue(profile is None or type(profile) is VoiceIdentityProfile)
            self.assertIs(type(failures), tuple)
            for failure in failures:
                self.assertEqual([type(x) for x in failure], [str, str, str])
            for value in (profile, failures):
                self.assertIsNot(value, reg)
                self.assertIsNot(value, r)

    def test_29_request_and_registry_are_not_reachable_from_the_result(self):
        import gc
        reg = create_voice_verification_registry((prof("voice_1"), prof("voice_2"))).registry
        r = req("voice_1")
        for request, regi in ((r, reg), (req("nobody"), reg), (r, None), (None, reg), (None, None)):
            out = resolve_voice_verification_profile(request, regi)
            seen, stack = set(), [out]
            while stack:
                node = stack.pop()
                if id(node) in seen:
                    continue
                seen.add(id(node))
                self.assertIsNot(node, reg)
                self.assertIsNot(node, r)
                if type(request) is VoiceVerificationRequest:
                    self.assertIsNot(node, request)
                if not isinstance(node, (type, type(None))) and type(node) is not type(res):
                    stack.extend(gc.get_referents(node))
            self.assertNotIn(id(reg), seen)
            self.assertNotIn(id(r), seen)

    def test_30_failure_messages_never_hold_the_request_or_registry(self):
        out = resolve_voice_verification_profile(req("nobody"), registry())
        text = repr(out.to_dict())
        self.assertNotIn("VoiceVerificationRequest", text)
        self.assertNotIn("VoiceVerificationRegistry", text)
        self.assertNotIn("verify_1", text)
        self.assertNotIn("STANDARD", text)


class TestBoundaries(unittest.TestCase):
    def test_31_failure_codes_are_stable(self):
        self.assertEqual(res.FAILURE_CODES, (INVALID_REQUEST, INVALID_REGISTRY, PROFILE_NOT_FOUND))
        self.assertEqual(len(set(res.FAILURE_CODES)), 3)
        for code in res.FAILURE_CODES:
            self.assertTrue(code.startswith(P))

    def test_32_module_imports_only_existing_voice_contracts_and_defines_no_new_model(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imports = sorted((n.module, n.level, tuple(a.name for a in n.names)) for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)))
        self.assertTrue(all(isinstance(n, ast.ImportFrom) for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))))
        self.assertEqual(imports, [("voice_identity_profile", 1, ("VoiceIdentityProfile",)),
                                   ("voice_verification_registry", 1, ("VoiceVerificationLookupResult", "VoiceVerificationRegistry")),
                                   ("voice_verification_request", 1, ("VoiceVerificationRequest",)),
                                   ("voice_verification_request_validator", 1, ("validate_voice_verification_request",))])
        self.assertEqual(sorted(n.name for n in tree.body if isinstance(n, ast.ClassDef)), ["VoiceVerificationProfileResolutionResult"])

    def test_33_module_has_no_forbidden_calls_dependencies_or_state(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "getattr", "setattr", "globals", "vars", "isinstance"):
            self.assertNotIn(forbidden, calls)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("os", "sys", "io", "pathlib", "subprocess", "socket", "urllib", "http", "requests", "numpy", "wave", "sqlite3", "random", "time",
                     "datetime", "anthropic", "openai", "core", "agent", "planning", "web", "multimedia", "game_creation", "audio", "embedding",
                     "embeddings", "sample", "samples", "microphone", "android", "__class__"):
            self.assertNotIn(word, names, word)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.ImportFrom))
        for name, value in vars(res).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_34_existing_contracts_are_reused_not_duplicated(self):
        self.assertIs(res.VoiceVerificationRequest, VoiceVerificationRequest)
        self.assertIs(res.VoiceVerificationRegistry, VoiceVerificationRegistry)
        self.assertIs(res.VoiceIdentityProfile, VoiceIdentityProfile)
        self.assertEqual(vr.FIELDS, ("request_id", "profile_id", "verification_mode"))
        for earlier in ("voice_verification_request.py", "voice_verification_registry.py", "voice_identity_profile.py", "voice_verification_plan.py",
                        "voice_verification_result.py", "voice_verification_executor.py", "voice_verification_dispatcher.py",
                        "voice_verification_pipeline.py", "voice_verification_batch.py", "voice_verification_batch_summary.py"):
            with open(os.path.join(PY_ROOT, "voice", earlier), encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn("voice_verification_profile_resolver", text, earlier)
            self.assertNotIn("resolve_voice_verification_profile", text, earlier)

    def test_35_nothing_outside_the_voice_package_references_the_resolver(self):
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if not (folder == PY_ROOT and d in ("voice", "tests", "data")) and d != "__pycache__"]
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        text = fh.read()
                    self.assertNotIn("voice_verification_profile_resolver", text, os.path.join(folder, name))
                    self.assertNotIn("from voice", text, os.path.join(folder, name))
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py", "android_entry.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("resolve_voice_verification_profile", "voice_verification_profile_resolver", "from voice", "import voice"):
                self.assertNotIn(token, text, (rel, token))

    def test_36_voice_package_holds_exactly_the_expected_files(self):
        listing = sorted(f for f in os.listdir(os.path.join(PY_ROOT, "voice")) if f != "__pycache__")
        self.assertIn("voice_verification_profile_resolver.py", listing)
        self.assertEqual(len(listing), 28)
        with open(os.path.join(PY_ROOT, "voice", "__init__.py"), "rb") as fh:
            self.assertEqual(fh.read(), b"")

    def test_37_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("resolve_voice_verification_profile", "VoiceVerificationProfileResolutionResult", "VoiceVerificationRequest", "VoiceVerificationRegistry",
                       "lookup()", "VOICE_VERIFICATION_PROFILE_RESOLVER_", "INVALID_REQUEST", "INVALID_REGISTRY", "PROFILE_NOT_FOUND", "does NOT",
                       "biometrics", "embeddings", "retains neither", "Prompt 809"):
            self.assertIn(marker, text, marker)


if __name__ == "__main__":
    unittest.main()
