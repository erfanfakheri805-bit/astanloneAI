"""Prompt 809 - Section 10 voice verification decision gate (`voice.voice_verification_decision`)."""
import ast
import copy
import gc
import hashlib
import os
import pickle
import unittest

from voice import voice_verification_decision as dec
from voice import voice_verification_profile_resolver as pr
from voice.voice_identity_profile import VoiceIdentityProfile, create_voice_identity_profile
from voice.voice_verification_decision import VoiceVerificationDecision, decide_voice_verification
from voice.voice_verification_profile_resolver import VoiceVerificationProfileResolutionResult, resolve_voice_verification_profile
from voice.voice_verification_registry import create_voice_verification_registry
from voice.voice_verification_request import create_voice_verification_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section10_voice_verification_decision_prompt809.md")
MODULE = os.path.join(PY_ROOT, "voice", "voice_verification_decision.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
P = "VOICE_VERIFICATION_DECISION_"
APPROVED, REJECTED, INVALID_RESULT = P + "APPROVED", P + "REJECTED", P + "INVALID_RESULT"
RP = "VOICE_VERIFICATION_PROFILE_RESOLVER_"


class Str(str):
    pass


def prof(profile_id="voice_1"):
    r = create_voice_identity_profile({"profile_id": profile_id, "display_name": "N " + profile_id, "enabled": True, "enrollment_status": "not_enrolled"})
    assert r.ok, r.failures
    return r.profile


def resolution(profile_id="voice_1", ids=("voice_1", "voice_2")):
    reg = create_voice_verification_registry(tuple(prof(i) for i in ids)).registry
    req = create_voice_verification_request({"request_id": "r1", "profile_id": profile_id, "verification_mode": "STANDARD"}).request
    return resolve_voice_verification_profile(req, reg)


def raw_result(profile, failures):
    """A resolution result with arbitrary internals (only possible inside tests, via the resolver module's private token)."""
    return VoiceVerificationProfileResolutionResult(pr._CREATE_TOKEN, profile, failures)


class TestApproved(unittest.TestCase):
    def test_1_successful_resolution_is_approved(self):
        out = decide_voice_verification(resolution("voice_2"))
        self.assertIs(type(out), VoiceVerificationDecision)
        self.assertIs(out.approved, True)
        self.assertEqual((out.profile_id, out.failure_codes, out.code), ("voice_2", (), APPROVED))
        self.assertEqual(out.to_dict(), {"approved": True, "profile_id": "voice_2", "failure_codes": [], "code": APPROVED})

    def test_2_profile_id_is_preserved_exactly(self):
        for pid in ("a", "A", " a ", "voice id\n", "\u00e9", "0", "x" * 500):
            res = resolution(pid, ids=(pid,))
            out = decide_voice_verification(res)
            self.assertTrue(out.approved)
            self.assertIs(out.profile_id, res.profile.profile_id)
            self.assertEqual(out.profile_id, pid)

    def test_3_disabled_profile_is_still_a_resolved_profile(self):
        p = create_voice_identity_profile({"profile_id": "x", "display_name": "X", "enabled": False, "enrollment_status": "revoked"}).profile
        reg = create_voice_verification_registry((p,)).registry
        req = create_voice_verification_request({"request_id": "r", "profile_id": "x", "verification_mode": "m"}).request
        self.assertTrue(decide_voice_verification(resolve_voice_verification_profile(req, reg)).approved)


class TestRejected(unittest.TestCase):
    def test_4_missing_profile_is_rejected_with_the_resolution_codes(self):
        out = decide_voice_verification(resolution("nobody"))
        self.assertIs(out.approved, False)
        self.assertIsNone(out.profile_id)
        self.assertEqual(out.failure_codes, (RP + "PROFILE_NOT_FOUND",))
        self.assertEqual(out.code, REJECTED)
        self.assertEqual(out.to_dict(), {"approved": False, "profile_id": None, "failure_codes": [RP + "PROFILE_NOT_FOUND"], "code": REJECTED})

    def test_5_invalid_request_and_registry_resolutions_keep_every_code_in_order(self):
        out = decide_voice_verification(resolve_voice_verification_profile(None, None))
        self.assertEqual((out.approved, out.profile_id, out.code), (False, None, REJECTED))
        self.assertEqual(out.failure_codes, (RP + "INVALID_REQUEST", RP + "INVALID_REGISTRY"))
        out = decide_voice_verification(resolve_voice_verification_profile(None, create_voice_verification_registry(()).registry))
        self.assertEqual(out.failure_codes, (RP + "INVALID_REQUEST",))

    def test_6_a_rejected_decision_is_not_the_invalid_result_code(self):
        self.assertNotEqual(decide_voice_verification(resolution("nobody")).code, INVALID_RESULT)
        self.assertNotIn(INVALID_RESULT, decide_voice_verification(resolution("nobody")).failure_codes)


class TestInvalidInput(unittest.TestCase):
    def assertInvalid(self, out):
        self.assertIs(type(out), VoiceVerificationDecision)
        self.assertEqual((out.approved, out.profile_id, out.failure_codes, out.code), (False, None, (INVALID_RESULT,), INVALID_RESULT))

    def test_7_non_result_values_are_invalid(self):
        good = resolution()
        for value in (None, {}, {"ok": True}, good.to_dict(), "ok", 1, True, [], (), object(), good.profile, prof("voice_1")):
            self.assertInvalid(decide_voice_verification(value))

    def test_8_exact_results_with_contradictory_data_are_invalid(self):
        p = prof("voice_1")
        bad = (raw_result(None, ()),                                   # "ok" without a profile
               raw_result(p, (("c", "f", "m"),)),                      # profile together with a failure
               raw_result({"profile_id": "x"}, ()),                    # not a VoiceIdentityProfile
               raw_result(object(), ()))
        for value in bad:
            self.assertInvalid(decide_voice_verification(value))

    def test_9_failed_results_need_exact_str_codes(self):
        self.assertInvalid(decide_voice_verification(raw_result(None, ((1, "f", "m"),))))
        self.assertInvalid(decide_voice_verification(raw_result(None, ((Str("c"), "f", "m"),))))
        self.assertInvalid(decide_voice_verification(raw_result(None, ((None, "f", "m"),))))
        ok_codes = decide_voice_verification(raw_result(None, (("CODE_A", "f", "m"), ("CODE_B", "g", "n"))))
        self.assertEqual((ok_codes.approved, ok_codes.failure_codes, ok_codes.code), (False, ("CODE_A", "CODE_B"), REJECTED))

    def test_10_profile_with_a_malformed_profile_id_is_invalid(self):
        for pid in ("", None, 5, Str("x")):
            p = VoiceIdentityProfile.__new__(VoiceIdentityProfile)
            object.__setattr__(p, "_profile_id", pid)
            self.assertInvalid(decide_voice_verification(raw_result(p, ())))

    def test_11_unreadable_result_is_invalid_not_an_exception(self):
        # subclassing is refused, so an exact-type result whose public read raises is simulated by patching the property
        def boom(self):
            raise RuntimeError("boom")
        res = resolution()
        original = VoiceVerificationProfileResolutionResult.profile
        VoiceVerificationProfileResolutionResult.profile = property(boom)
        try:
            self.assertInvalid(decide_voice_verification(res))
        finally:
            VoiceVerificationProfileResolutionResult.profile = original


class TestSpoofedAndLookAlikes(unittest.TestCase):
    def assertInvalid(self, out):
        self.assertEqual((out.approved, out.profile_id, out.failure_codes, out.code), (False, None, (INVALID_RESULT,), INVALID_RESULT))

    def test_12_spoofed_class_is_rejected_without_reading_it(self):
        touched = []

        class Spoof:
            __class__ = VoiceVerificationProfileResolutionResult
            ok = True
            profile = prof("voice_1")

            def __getattribute__(self, name):
                touched.append(name)
                return object.__getattribute__(self, name)

            def codes(self):
                return []

        self.assertInvalid(decide_voice_verification(Spoof()))
        self.assertNotIn("ok", touched)
        self.assertNotIn("profile", touched)

    def test_13_look_alike_with_same_public_surface_is_rejected(self):
        real = resolution("voice_1")

        class LookAlike:
            ok = real.ok
            profile = real.profile
            failures = real.failures

            def codes(self):
                return real.codes()

            def to_dict(self):
                return real.to_dict()

        self.assertInvalid(decide_voice_verification(LookAlike()))

    def test_14_result_cannot_be_subclassed_into_a_look_alike(self):
        with self.assertRaises(TypeError):
            class Sub(VoiceVerificationProfileResolutionResult):
                pass

    def test_15_mock_like_objects_are_rejected(self):
        from unittest import mock
        self.assertInvalid(decide_voice_verification(mock.Mock()))
        self.assertInvalid(decide_voice_verification(mock.MagicMock(spec=VoiceVerificationProfileResolutionResult)))


class TestDeterminism(unittest.TestCase):
    def test_16_decisions_and_codes_are_deterministic(self):
        for make in (lambda: resolution("voice_1"), lambda: resolution("nobody"), lambda: None):
            a, b = decide_voice_verification(make()), decide_voice_verification(make())
            self.assertIsNot(a, b)
            self.assertEqual(a, b)
            self.assertEqual(hash(a), hash(b))
            self.assertEqual(a.to_dict(), b.to_dict())
        same = resolution("nobody")
        self.assertEqual(decide_voice_verification(same), decide_voice_verification(same))

    def test_17_codes_are_stable(self):
        self.assertEqual(dec.DECISION_CODES, (APPROVED, REJECTED, INVALID_RESULT))
        self.assertEqual(dec.FAILURE_INVALID_RESULT, "VOICE_VERIFICATION_DECISION_INVALID_RESULT")
        self.assertEqual(len(set(dec.DECISION_CODES)), 3)

    def test_18_inputs_are_not_changed(self):
        res = resolution("voice_1")
        before = (res.to_dict(), res.profile, res.codes())
        decide_voice_verification(res)
        self.assertEqual((res.to_dict(), res.profile, res.codes()), before)
        self.assertIs(res.profile, before[1])


class TestImmutability(unittest.TestCase):
    def test_19_attributes_cannot_be_assigned_or_deleted(self):
        for out in (decide_voice_verification(resolution()), decide_voice_verification(resolution("nobody")), decide_voice_verification(None)):
            for name in ("approved", "profile_id", "failure_codes", "code", "_approved", "_profile_id", "_failure_codes", "_code", "extra"):
                with self.assertRaises(AttributeError, msg=name):
                    setattr(out, name, 1)
                with self.assertRaises(AttributeError, msg=name):
                    delattr(out, name)
            self.assertFalse(hasattr(out, "__dict__"))

    def test_20_failure_codes_is_a_tuple_and_to_dict_is_fresh(self):
        out = decide_voice_verification(resolution("nobody"))
        self.assertIs(type(out.failure_codes), tuple)
        d = out.to_dict()
        d["failure_codes"].append("x")
        d["approved"] = True
        d["profile_id"] = "hacked"
        self.assertEqual(out.to_dict(), {"approved": False, "profile_id": None, "failure_codes": [RP + "PROFILE_NOT_FOUND"], "code": REJECTED})
        self.assertIsNot(out.to_dict(), out.to_dict())

    def test_21_construction_subclassing_copy_pickle(self):
        for args in ((object(), True, "a", (), APPROVED), (None, True, "a", (), APPROVED), ()):
            with self.assertRaises(TypeError):
                VoiceVerificationDecision(*args)
        with self.assertRaises(TypeError):
            class Sub(VoiceVerificationDecision):
                pass
        out = decide_voice_verification(resolution())
        self.assertIs(copy.copy(out), out)
        self.assertIs(copy.deepcopy(out), out)
        for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
            with self.assertRaises(TypeError):
                pickle.dumps(out, protocol)

    def test_22_equality_hash_and_repr(self):
        a, b, c = (decide_voice_verification(resolution("voice_1")), decide_voice_verification(resolution("voice_1")), decide_voice_verification(resolution("voice_2")))
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertNotEqual(a, a.to_dict())
        self.assertEqual(len({a, b, c}), 2)
        self.assertEqual(repr(a), "VoiceVerificationDecision(approved=True, profile_id='voice_1', code='%s')" % APPROVED)


class TestNonRetention(unittest.TestCase):
    def test_23_decision_holds_only_minimal_plain_data(self):
        self.assertEqual(VoiceVerificationDecision.__slots__, ("_approved", "_profile_id", "_failure_codes", "_code"))
        for res in (resolution("voice_1"), resolution("nobody"), None):
            out = decide_voice_verification(res)
            self.assertIs(type(out.approved), bool)
            self.assertTrue(out.profile_id is None or type(out.profile_id) is str)
            self.assertTrue(all(type(c) is str for c in out.failure_codes))
            self.assertIs(type(out.code), str)

    def test_24_source_resolution_and_profile_are_not_reachable_from_the_decision(self):
        for res in (resolution("voice_1"), resolution("nobody")):
            profile = res.profile
            out = decide_voice_verification(res)
            seen, stack = set(), [out]
            while stack:
                node = stack.pop()
                if id(node) in seen:
                    continue
                seen.add(id(node))
                if not isinstance(node, (type, type(None))):
                    stack.extend(gc.get_referents(node))
            self.assertNotIn(id(res), seen)
            if profile is not None:
                self.assertNotIn(id(profile), seen)
            self.assertFalse([n for n in (res, profile) if n is not None and any(r is n for r in gc.get_referents(out))])

    def test_25_decision_does_not_keep_the_source_alive(self):
        import weakref

        class Marker:
            pass
        res = resolution("voice_1")
        ref = None
        try:
            ref = weakref.ref(res)
        except TypeError:
            pass   # slotted result: reachability is covered by test 24
        out = decide_voice_verification(res)
        del res
        gc.collect()
        if ref is not None:
            self.assertIsNone(ref())
        self.assertEqual(out.profile_id, "voice_1")


class TestBoundaries(unittest.TestCase):
    def test_26_module_imports_only_existing_voice_contracts_and_defines_one_class(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        nodes = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertTrue(all(isinstance(n, ast.ImportFrom) for n in nodes))
        self.assertEqual(sorted((n.module, n.level, tuple(a.name for a in n.names)) for n in nodes),
                         [("voice_identity_profile", 1, ("VoiceIdentityProfile",)),
                          ("voice_verification_profile_resolver", 1, ("VoiceVerificationProfileResolutionResult",))])
        self.assertEqual(sorted(n.name for n in tree.body if isinstance(n, ast.ClassDef)), ["VoiceVerificationDecision"])
        self.assertIs(dec.VoiceVerificationProfileResolutionResult, VoiceVerificationProfileResolutionResult)

    def test_27_module_reads_only_public_result_api_and_has_no_forbidden_calls_or_state(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        read_from_result = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "resolution_result"}
        self.assertEqual(read_from_result, {"ok", "profile", "codes"})
        for private in ("_profile", "_failures", "__dict__", "__class__", "failures"):
            self.assertNotIn(private, attrs, private)
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "getattr", "setattr", "globals", "vars", "isinstance"):
            self.assertNotIn(forbidden, calls)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | attrs
        for word in ("os", "sys", "io", "pathlib", "subprocess", "socket", "urllib", "http", "requests", "numpy", "wave", "sqlite3", "random", "time",
                     "datetime", "anthropic", "openai", "core", "agent", "planning", "web", "multimedia", "game_creation", "audio", "embedding",
                     "embeddings", "microphone", "android", "registry", "lookup"):
            self.assertNotIn(word, names, word)
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.ImportFrom))
        for name, value in vars(dec).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_28_earlier_voice_modules_do_not_reference_the_decision_and_nothing_outside_voice_does(self):
        voice_dir = os.path.join(PY_ROOT, "voice")
        for name in sorted(os.listdir(voice_dir)):
            if name.endswith(".py") and name not in ("voice_verification_decision.py", "voice_verification_handoff.py", "voice_verification_authorization.py"):
                with open(os.path.join(voice_dir, name), encoding="utf-8") as fh:
                    text = fh.read()
                self.assertNotIn("voice_verification_decision", text, name)
                self.assertNotIn("VoiceVerificationDecision", text, name)
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if not (folder == PY_ROOT and d in ("voice", "tests", "data")) and d != "__pycache__"]
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        text = fh.read()
                    self.assertNotIn("voice_verification_decision", text, name)
                    self.assertNotIn("from voice", text, name)
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py", "android_entry.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("decide_voice_verification", "voice_verification_decision", "from voice", "import voice"):
                self.assertNotIn(token, text, (rel, token))

    def test_29_voice_package_holds_the_expected_files(self):
        listing = sorted(f for f in os.listdir(os.path.join(PY_ROOT, "voice")) if f != "__pycache__")
        self.assertIn("voice_verification_decision.py", listing)
        self.assertEqual(len(listing), 28)

    def test_30_pristine_database_no_bytecode_and_documentation(self):
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("decide_voice_verification", "VoiceVerificationDecision", "VoiceVerificationProfileResolutionResult", "VOICE_VERIFICATION_DECISION_",
                       "INVALID_RESULT", "APPROVED", "REJECTED", "does NOT", "biometrics", "embeddings", "retains neither", "Prompt 810"):
            self.assertIn(marker, text, marker)


if __name__ == "__main__":
    unittest.main()
