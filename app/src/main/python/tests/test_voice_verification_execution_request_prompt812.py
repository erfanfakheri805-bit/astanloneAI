"""Prompt 812 - Section 10 voice verification execution request (`voice.voice_verification_execution_request`)."""
import ast
import copy
import gc
import hashlib
import os
import pickle
import unittest
from unittest import mock

from voice import voice_verification_authorization as au_mod
from voice import voice_verification_batch as batch_mod
from voice import voice_verification_dispatcher as dispatcher_mod
from voice import voice_verification_execution_request as er
from voice import voice_verification_executor as executor_mod
from voice import voice_verification_pipeline as pipeline_mod
from voice import voice_verification_plan as plan_mod
from voice.voice_identity_profile import create_voice_identity_profile
from voice.voice_verification_authorization import VoiceVerificationAuthorization, authorize_voice_verification
from voice.voice_verification_execution_request import VoiceVerificationExecutionRequest, create_voice_verification_execution_request
from voice.voice_verification_plan import VoiceVerificationPlan, create_voice_verification_plan
from voice.voice_verification_registry import create_voice_verification_registry
from voice.voice_verification_request import create_voice_verification_request
from voice.voice_verification_request_validator import validate_voice_verification_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section10_voice_verification_execution_request_prompt812.md")
MODULE = os.path.join(PY_ROOT, "voice", "voice_verification_execution_request.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
P = "VOICE_VERIFICATION_EXECUTION_REQUEST_"
INVALID_INPUT, NOT_AUTHORIZED, PROFILE_MISMATCH = P + "INVALID_INPUT", P + "NOT_AUTHORIZED", P + "PROFILE_MISMATCH"


class Str(str):
    pass


def make_request(profile_id="voice_1", request_id="r1", mode="STANDARD"):
    return create_voice_verification_request({"request_id": request_id, "profile_id": profile_id, "verification_mode": mode}).request


def make_registry(*ids):
    items = tuple(create_voice_identity_profile({"profile_id": i, "display_name": "N " + i, "enabled": True, "enrollment_status": "not_enrolled"}).profile
                  for i in (ids or ("voice_1", "voice_2")))
    return create_voice_verification_registry(items).registry


def make_plan(profile_id="voice_1", request_id="r1", mode="STANDARD"):
    result = create_voice_verification_plan(validate_voice_verification_request(make_request(profile_id, request_id, mode)))
    assert result.ok, result.failures
    return result.plan


def make_authorization(profile_id="voice_1", registered=("voice_1", "voice_2")):
    return authorize_voice_verification(make_request(profile_id), make_registry(*registered), make_plan(profile_id))


def raw_authorization(authorized, profile_id, codes=()):
    return VoiceVerificationAuthorization(au_mod._CREATE_TOKEN, authorized, profile_id, codes)


def raw_plan(profile_id="voice_1", request_id="r", mode="m"):
    return VoiceVerificationPlan(plan_mod._CREATE_TOKEN, request_id, profile_id, mode)


class NoExecution:
    """Replaces every execution entry point and the authorization boundary with a tripwire; `calls` must stay empty."""

    def __enter__(self):
        self.calls = []

        def trip(name):
            def f(*a, **k):
                self.calls.append(name)
                raise AssertionError(name + " must not be called")
            return f
        self._patches = [mock.patch.object(executor_mod, "execute_voice_verification_plan", trip("executor")),
                         mock.patch.object(dispatcher_mod, "dispatch_voice_verification", trip("dispatcher")),
                         mock.patch.object(pipeline_mod, "run_voice_verification_pipeline", trip("pipeline")),
                         mock.patch.object(batch_mod, "run_voice_verification_batch", trip("batch")),
                         mock.patch.object(au_mod, "authorize_voice_verification", trip("authorize"))]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


class TestExecutable(unittest.TestCase):
    def test_1_authorized_matching_authorization_and_plan(self):
        out = create_voice_verification_execution_request(make_authorization("voice_2"), make_plan("voice_2", "req-9", "FAST"))
        self.assertIs(type(out), VoiceVerificationExecutionRequest)
        self.assertIs(out.ok, True)
        self.assertEqual((out.request_id, out.profile_id, out.verification_mode, out.failure_codes), ("req-9", "voice_2", "FAST", ()))
        self.assertEqual(out.to_dict(), {"ok": True, "request_id": "req-9", "profile_id": "voice_2", "verification_mode": "FAST", "failure_codes": []})

    def test_2_request_id_is_preserved_exactly(self):
        for rid in ("r", "R-1", " r ", "id\n", "\u00e9", "0", "x" * 500):
            plan = make_plan("voice_1", rid)
            out = create_voice_verification_execution_request(make_authorization("voice_1"), plan)
            self.assertTrue(out.ok)
            self.assertIs(out.request_id, plan.request_id)
            self.assertEqual(out.request_id, rid)

    def test_3_profile_id_is_preserved_exactly(self):
        for pid in ("a", "A", " a ", "voice id\n", "\u00e9", "0", "x" * 500):
            auth = make_authorization(pid, registered=(pid,))
            out = create_voice_verification_execution_request(auth, make_plan(pid))
            self.assertTrue(out.ok)
            self.assertIs(out.profile_id, auth.profile_id)
            self.assertEqual(out.profile_id, pid)

    def test_4_verification_mode_is_preserved_exactly(self):
        for mode in ("STANDARD", "standard", " m ", "free text mode", "m\n", "\u00e9", "x" * 300):
            plan = make_plan("voice_1", "r1", mode)
            out = create_voice_verification_execution_request(make_authorization("voice_1"), plan)
            self.assertTrue(out.ok)
            self.assertIs(out.verification_mode, plan.verification_mode)
            self.assertEqual(out.verification_mode, mode)

    def test_5_nothing_is_normalized_or_reinterpreted(self):
        out = create_voice_verification_execution_request(raw_authorization(True, "Voice_1"), raw_plan("Voice_1", " Req ", "Mode X"))
        self.assertEqual((out.request_id, out.profile_id, out.verification_mode), (" Req ", "Voice_1", "Mode X"))
        self.assertEqual(list(out.to_dict()), ["ok", "request_id", "profile_id", "verification_mode", "failure_codes"])


class TestNotAuthorized(unittest.TestCase):
    def assertRejected(self, out, code):
        self.assertIs(type(out), VoiceVerificationExecutionRequest)
        self.assertEqual((out.ok, out.request_id, out.profile_id, out.verification_mode, out.failure_codes), (False, None, None, None, (code,)))
        self.assertEqual(out.to_dict(), {"ok": False, "request_id": None, "profile_id": None, "verification_mode": None, "failure_codes": [code]})

    def test_6_rejected_authorization_gives_a_rejected_result(self):
        for auth in (make_authorization("nobody"), authorize_voice_verification(None, None, None), raw_authorization(False, None, ("X",))):
            self.assertRejected(create_voice_verification_execution_request(auth, make_plan("voice_1")), NOT_AUTHORIZED)

    def test_7_not_authorized_never_yields_an_executable_request_even_with_a_matching_plan(self):
        out = create_voice_verification_execution_request(raw_authorization(False, "voice_1"), make_plan("voice_1"))
        self.assertRejected(out, NOT_AUTHORIZED)

    def test_8_plan_is_not_read_for_a_rejected_authorization(self):
        touched = []
        real = make_plan("voice_1")
        with mock.patch.object(VoiceVerificationPlan, "profile_id", property(lambda self: touched.append("profile_id") or "voice_1")), \
                mock.patch.object(VoiceVerificationPlan, "request_id", property(lambda self: touched.append("request_id") or "r")):
            out = create_voice_verification_execution_request(make_authorization("nobody"), real)
        self.assertRejected(out, NOT_AUTHORIZED)
        self.assertEqual(touched, [])

    def test_9_profile_mismatch_is_rejected(self):
        out = create_voice_verification_execution_request(make_authorization("voice_1"), make_plan("voice_2"))
        self.assertRejected(out, PROFILE_MISMATCH)
        for a, b in (("voice_1", "VOICE_1"), ("voice_1", "voice_1 "), ("a", "\u0061\u0301")):
            self.assertRejected(create_voice_verification_execution_request(raw_authorization(True, a), raw_plan(b)), PROFILE_MISMATCH)


class TestInvalidInputs(unittest.TestCase):
    def assertInvalid(self, out):
        self.assertIs(type(out), VoiceVerificationExecutionRequest)
        self.assertEqual((out.ok, out.request_id, out.profile_id, out.verification_mode, out.failure_codes), (False, None, None, None, (INVALID_INPUT,)))

    def test_10_invalid_authorization(self):
        plan = make_plan()
        for bad in (None, {}, "voice_1", 1, True, [], (), object(), make_authorization().to_dict(), plan, make_request(), make_registry()):
            self.assertInvalid(create_voice_verification_execution_request(bad, plan))

    def test_11_invalid_plan(self):
        auth = make_authorization()
        for bad in (None, {}, "voice_1", 1, True, [], (), object(), make_plan().to_dict(), auth, make_request(), make_registry()):
            self.assertInvalid(create_voice_verification_execution_request(auth, bad))
        self.assertInvalid(create_voice_verification_execution_request(None, None))
        self.assertInvalid(create_voice_verification_execution_request(make_plan(), make_authorization()))   # swapped

    def test_12_exact_objects_with_malformed_data_are_invalid(self):
        plan = make_plan("voice_1")
        for authorized in (None, 1, 0, "yes", "", object()):
            self.assertInvalid(create_voice_verification_execution_request(raw_authorization(authorized, "voice_1"), plan))
        for bad in (None, "", 5, Str("voice_1")):
            self.assertInvalid(create_voice_verification_execution_request(raw_authorization(True, bad), plan))
            self.assertInvalid(create_voice_verification_execution_request(raw_authorization(True, "voice_1"), raw_plan(profile_id=bad)))
            self.assertInvalid(create_voice_verification_execution_request(raw_authorization(True, "voice_1"), raw_plan("voice_1", request_id=bad)))
            self.assertInvalid(create_voice_verification_execution_request(raw_authorization(True, "voice_1"), raw_plan("voice_1", mode=bad)))

    def test_13_unreadable_public_properties_are_invalid_not_exceptions(self):
        def boom(self):
            raise RuntimeError("boom")
        for cls, name in ((VoiceVerificationAuthorization, "authorized"), (VoiceVerificationAuthorization, "profile_id"), (VoiceVerificationPlan, "profile_id"),
                          (VoiceVerificationPlan, "request_id"), (VoiceVerificationPlan, "verification_mode")):
            auth, plan = make_authorization("voice_1"), make_plan("voice_1")   # built before patching: building reads the same properties
            with mock.patch.object(cls, name, property(boom)):
                self.assertInvalid(create_voice_verification_execution_request(auth, plan))

    def test_14_type_check_comes_before_any_read(self):
        touched = []

        class Spoof:
            __class__ = VoiceVerificationAuthorization
            authorized = False

            def __getattribute__(self, name):
                touched.append(name)
                return object.__getattribute__(self, name)
        self.assertInvalid(create_voice_verification_execution_request(Spoof(), make_plan()))
        self.assertEqual([t for t in touched if t in ("authorized", "profile_id")], [])


class TestSpoofedAndLookAlikes(unittest.TestCase):
    def assertInvalid(self, out):
        self.assertEqual((out.ok, out.request_id, out.profile_id, out.verification_mode, out.failure_codes), (False, None, None, None, (INVALID_INPUT,)))

    def test_15_spoofed_class_authorization_and_plan_are_rejected(self):
        class SpoofAuthorization:
            __class__ = VoiceVerificationAuthorization
            authorized, profile_id, failure_codes = True, "voice_1", ()

        class SpoofPlan:
            __class__ = VoiceVerificationPlan
            request_id, profile_id, verification_mode = "r", "voice_1", "m"
        self.assertInvalid(create_voice_verification_execution_request(SpoofAuthorization(), make_plan("voice_1")))
        self.assertInvalid(create_voice_verification_execution_request(make_authorization("voice_1"), SpoofPlan()))
        self.assertInvalid(create_voice_verification_execution_request(SpoofAuthorization(), SpoofPlan()))

    def test_16_look_alikes_with_the_same_public_surface_are_rejected(self):
        real_a, real_p = make_authorization("voice_1"), make_plan("voice_1")

        class LookAuthorization:
            authorized, profile_id, failure_codes = real_a.authorized, real_a.profile_id, real_a.failure_codes

            def to_dict(self):
                return real_a.to_dict()

        class LookPlan:
            request_id, profile_id, verification_mode = "r1", "voice_1", "STANDARD"

            def to_dict(self):
                return real_p.to_dict()
        self.assertInvalid(create_voice_verification_execution_request(LookAuthorization(), real_p))
        self.assertInvalid(create_voice_verification_execution_request(real_a, LookPlan()))
        self.assertInvalid(create_voice_verification_execution_request(mock.Mock(), real_p))
        self.assertInvalid(create_voice_verification_execution_request(real_a, mock.MagicMock(spec=VoiceVerificationPlan)))
        self.assertInvalid(create_voice_verification_execution_request(mock.MagicMock(spec=VoiceVerificationAuthorization), real_p))

    def test_17_contract_classes_cannot_be_subclassed_into_look_alikes(self):
        for base in (VoiceVerificationAuthorization, VoiceVerificationPlan, VoiceVerificationExecutionRequest):
            with self.assertRaises(TypeError):
                type("Sub", (base,), {})


class TestNoExecution(unittest.TestCase):
    def test_18_no_executor_dispatcher_pipeline_batch_or_authorization_call_in_any_branch(self):
        auth_ok, auth_no = make_authorization("voice_1"), make_authorization("nobody")
        with NoExecution() as t:
            for a, p in ((auth_ok, make_plan("voice_1")), (auth_ok, make_plan("voice_2")), (auth_no, make_plan("voice_1")), (None, make_plan()), (auth_ok, None),
                         (raw_authorization(None, "x"), make_plan()), (raw_authorization(True, ""), make_plan()), (auth_ok, raw_plan(request_id=None))):
                create_voice_verification_execution_request(a, p)
        self.assertEqual(t.calls, [])

    def test_19_module_imports_only_authorization_and_plan_and_never_names_execution_apis(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        nodes = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertTrue(all(isinstance(n, ast.ImportFrom) for n in nodes))
        self.assertEqual(sorted((n.module, n.level, tuple(a.name for a in n.names)) for n in nodes),
                         [("voice_verification_authorization", 1, ("VoiceVerificationAuthorization",)), ("voice_verification_plan", 1, ("VoiceVerificationPlan",))])
        self.assertEqual(sorted(n.name for n in tree.body if isinstance(n, ast.ClassDef)), ["VoiceVerificationExecutionRequest"])
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("execute_voice_verification_plan", "dispatch_voice_verification", "run_voice_verification_pipeline", "run_voice_verification_batch",
                     "authorize_voice_verification", "create_voice_verification_plan", "resolve_voice_verification_profile", "decide_voice_verification",
                     "create_voice_verification_handoff", "lookup", "registry", "os", "sys", "io", "pathlib", "subprocess", "socket", "urllib", "http", "requests",
                     "numpy", "wave", "sqlite3", "random", "time", "datetime", "anthropic", "openai", "core", "agent", "planning", "audio", "embedding", "embeddings",
                     "microphone", "android", "__class__", "__dict__"):
            self.assertNotIn(word, names, word)
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "getattr", "setattr", "globals", "vars", "isinstance"):
            self.assertNotIn(forbidden, calls)

    def test_20_module_reads_only_public_properties_of_the_inputs(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        read = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in ("authorization", "plan"):
                read.setdefault(n.value.id, set()).add(n.attr)
        self.assertEqual(read, {"authorization": {"authorized", "profile_id"}, "plan": {"profile_id", "request_id", "verification_mode"}})


class TestDeterminism(unittest.TestCase):
    def test_21_repeated_calls_are_deterministic(self):
        auth, plan = make_authorization("voice_1"), make_plan("voice_1")
        for a, p in ((auth, plan), (auth, make_plan("voice_2")), (make_authorization("nobody"), plan), (None, None)):
            first = create_voice_verification_execution_request(a, p)
            for _ in range(3):
                again = create_voice_verification_execution_request(a, p)
                self.assertIsNot(again, first)
                self.assertEqual(again, first)
                self.assertEqual(hash(again), hash(first))
                self.assertEqual(again.to_dict(), first.to_dict())

    def test_22_failure_codes_are_stable_and_status_matches_codes(self):
        self.assertEqual(er.FAILURE_CODES, (INVALID_INPUT, NOT_AUTHORIZED, PROFILE_MISMATCH))
        self.assertEqual(len(set(er.FAILURE_CODES)), 3)
        self.assertEqual(INVALID_INPUT, "VOICE_VERIFICATION_EXECUTION_REQUEST_INVALID_INPUT")
        self.assertEqual(NOT_AUTHORIZED, "VOICE_VERIFICATION_EXECUTION_REQUEST_NOT_AUTHORIZED")
        self.assertEqual(PROFILE_MISMATCH, "VOICE_VERIFICATION_EXECUTION_REQUEST_PROFILE_MISMATCH")
        for a, p, expected in ((make_authorization("voice_1"), make_plan("voice_1"), ()), (make_authorization("nobody"), make_plan("voice_1"), (NOT_AUTHORIZED,)),
                               (make_authorization("voice_1"), make_plan("voice_2"), (PROFILE_MISMATCH,)), (None, None, (INVALID_INPUT,))):
            out = create_voice_verification_execution_request(a, p)
            self.assertEqual(out.failure_codes, expected)
            self.assertEqual(out.ok, expected == ())
            self.assertEqual(out.profile_id is not None, out.ok)

    def test_23_inputs_are_not_mutated(self):
        a, p = make_authorization("voice_1"), make_plan("voice_1")
        before = (a.to_dict(), p.to_dict(), a, p)
        create_voice_verification_execution_request(a, p)
        create_voice_verification_execution_request(a, make_plan("voice_2"))
        create_voice_verification_execution_request(make_authorization("nobody"), p)
        self.assertEqual((a.to_dict(), p.to_dict()), before[:2])
        self.assertEqual((a, p), before[2:])


class TestEqualityToDictImmutability(unittest.TestCase):
    def test_24_equality_and_hash_by_value(self):
        a = create_voice_verification_execution_request(make_authorization("voice_1"), make_plan("voice_1"))
        b = create_voice_verification_execution_request(make_authorization("voice_1"), make_plan("voice_1"))
        c = create_voice_verification_execution_request(make_authorization("voice_1"), make_plan("voice_1", "other"))
        d = create_voice_verification_execution_request(make_authorization("voice_1"), make_plan("voice_1", "r1", "OTHER"))
        m = create_voice_verification_execution_request(make_authorization("voice_1"), make_plan("voice_2"))
        n = create_voice_verification_execution_request(make_authorization("nobody"), make_plan("voice_1"))
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertNotEqual(a, c)
        self.assertNotEqual(a, d)
        self.assertNotEqual(m, n)
        self.assertEqual(len({a, b, c, d, m, n}), 5)
        self.assertNotEqual(a, a.to_dict())
        self.assertNotEqual(a, ("r1", "voice_1", "STANDARD", ()))
        self.assertEqual(repr(m), "VoiceVerificationExecutionRequest(ok=False, request_id=None, profile_id=None, verification_mode=None, failure_codes=('%s',))" % PROFILE_MISMATCH)

    def test_25_to_dict_is_fresh_every_call_and_mutation_safe(self):
        for out in (create_voice_verification_execution_request(make_authorization("voice_1"), make_plan("voice_1")),
                    create_voice_verification_execution_request(make_authorization("voice_1"), make_plan("voice_2"))):
            first = out.to_dict()
            snapshot = copy.deepcopy(first)
            first["failure_codes"].append("x")
            first["ok"] = "hacked"
            first["request_id"] = first["profile_id"] = first["verification_mode"] = "hacked"
            first["extra"] = 1
            self.assertEqual(out.to_dict(), snapshot)
            self.assertIsNot(out.to_dict(), out.to_dict())
            self.assertIsNot(out.to_dict()["failure_codes"], out.to_dict()["failure_codes"])

    def test_26_attributes_cannot_be_assigned_or_deleted(self):
        for out in (create_voice_verification_execution_request(make_authorization(), make_plan()), create_voice_verification_execution_request(None, None)):
            for name in ("ok", "request_id", "profile_id", "verification_mode", "failure_codes", "_request_id", "_profile_id", "_verification_mode", "_failure_codes", "extra"):
                with self.assertRaises(AttributeError, msg=name):
                    setattr(out, name, 1)
                with self.assertRaises(AttributeError, msg=name):
                    delattr(out, name)
            self.assertFalse(hasattr(out, "__dict__"))
            self.assertIs(type(out.failure_codes), tuple)

    def test_27_direct_construction_subclassing_copy_and_pickle_are_refused(self):
        for args in ((object(), "r", "p", "m", ()), (None, "r", "p", "m", ()), ()):
            with self.assertRaises(TypeError):
                VoiceVerificationExecutionRequest(*args)
        self.assertEqual(VoiceVerificationExecutionRequest.__slots__, ("_request_id", "_profile_id", "_verification_mode", "_failure_codes"))
        out = create_voice_verification_execution_request(make_authorization(), make_plan())
        self.assertIs(copy.copy(out), out)
        self.assertIs(copy.deepcopy(out), out)
        for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
            with self.assertRaises(TypeError):
                pickle.dumps(out, protocol)


class TestNonRetention(unittest.TestCase):
    def test_28_result_holds_only_minimal_plain_data(self):
        for a, p in ((make_authorization("voice_1"), make_plan("voice_1")), (make_authorization("nobody"), make_plan("voice_1")),
                     (make_authorization("voice_1"), make_plan("voice_2")), (None, None)):
            out = create_voice_verification_execution_request(a, p)
            for value in (out.request_id, out.profile_id, out.verification_mode):
                self.assertTrue(value is None or type(value) is str)
            self.assertTrue(all(type(c) is str for c in out.failure_codes))

    def test_29_source_authorization_and_plan_are_not_reachable_from_the_result(self):
        for a, p in ((make_authorization("voice_1"), make_plan("voice_1")), (make_authorization("nobody"), make_plan("voice_1")),
                     (make_authorization("voice_1"), make_plan("voice_2"))):
            out = create_voice_verification_execution_request(a, p)
            seen, stack = set(), [out]
            while stack:
                node = stack.pop()
                if id(node) in seen:
                    continue
                seen.add(id(node))
                if not isinstance(node, (type, type(None))):
                    stack.extend(gc.get_referents(node))
            for obj in (a, p):
                self.assertNotIn(id(obj), seen, type(obj).__name__)
                self.assertFalse(any(r is obj for r in gc.get_referents(out)))

    def test_30_no_object_names_leak_into_the_result_text(self):
        out = create_voice_verification_execution_request(make_authorization("voice_1"), make_plan("voice_1"))
        text = repr(out.to_dict()) + repr(out)
        for leaked in ("VoiceVerificationPlan", "VoiceVerificationAuthorization", "authorized", "display_name", "enrollment_status"):
            self.assertNotIn(leaked, text)


class TestBoundaries(unittest.TestCase):
    def test_31_earlier_voice_modules_do_not_reference_the_execution_request_and_nothing_outside_voice_does(self):
        voice_dir = os.path.join(PY_ROOT, "voice")
        for name in sorted(os.listdir(voice_dir)):
            if name.endswith(".py") and name not in ("voice_verification_execution_request.py", "voice_verification_execution.py"):
                with open(os.path.join(voice_dir, name), encoding="utf-8") as fh:
                    text = fh.read()
                self.assertNotIn("voice_verification_execution_request", text, name)
                self.assertNotIn("VoiceVerificationExecutionRequest", text, name)
                self.assertNotIn("create_voice_verification_execution_request", text, name)
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if not (folder == PY_ROOT and d in ("voice", "tests", "data")) and d != "__pycache__"]
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        text = fh.read()
                    self.assertNotIn("voice_verification_execution_request", text, name)
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py", "android_entry.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("create_voice_verification_execution_request", "voice_verification_execution_request", "from voice", "import voice"):
                self.assertNotIn(token, text, (rel, token))

    def test_32_existing_contracts_are_reused_and_no_state_is_added(self):
        self.assertIs(er.VoiceVerificationAuthorization, VoiceVerificationAuthorization)
        self.assertIs(er.VoiceVerificationPlan, VoiceVerificationPlan)
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.ImportFrom))
        for name, value in vars(er).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_33_voice_package_pristine_database_no_bytecode_and_documentation(self):
        listing = sorted(f for f in os.listdir(os.path.join(PY_ROOT, "voice")) if f != "__pycache__")
        self.assertIn("voice_verification_execution_request.py", listing)
        self.assertEqual(len(listing), 28)
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("create_voice_verification_execution_request", "VoiceVerificationExecutionRequest", "VoiceVerificationAuthorization", "VoiceVerificationPlan",
                       "VOICE_VERIFICATION_EXECUTION_REQUEST_", "INVALID_INPUT", "NOT_AUTHORIZED", "PROFILE_MISMATCH", "does NOT", "never calls the verification executor",
                       "biometrics", "embeddings", "retains neither", "Prompt 813"):
            self.assertIn(marker, text, marker)


if __name__ == "__main__":
    unittest.main()
