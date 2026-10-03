"""Prompt 813 - Section 10 voice verification execution boundary (`voice.voice_verification_execution`)."""
import ast
import builtins
import copy
import gc
import hashlib
import io
import os
import pickle
import socket
import unittest
from unittest import mock

from voice import voice_verification_execution as ex
from voice import voice_verification_execution_request as er
from voice.voice_identity_profile import create_voice_identity_profile
from voice.voice_verification_authorization import authorize_voice_verification
from voice.voice_verification_execution import VoiceVerificationExecutionResult, execute_voice_verification
from voice.voice_verification_execution_request import VoiceVerificationExecutionRequest, create_voice_verification_execution_request
from voice.voice_verification_plan import create_voice_verification_plan
from voice.voice_verification_registry import create_voice_verification_registry
from voice.voice_verification_request import create_voice_verification_request
from voice.voice_verification_request_validator import validate_voice_verification_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section10_voice_verification_execution_prompt813.md")
MODULE = os.path.join(PY_ROOT, "voice", "voice_verification_execution.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
P = "VOICE_VERIFICATION_EXECUTION_"
INVALID, NOT_AUTH, NOT_IMPL = P + "INVALID_REQUEST", P + "NOT_AUTHORIZED", P + "NOT_IMPLEMENTED"


class Str(str):
    pass


def make_request(profile_id="voice_1", request_id="r1", mode="STANDARD"):
    return create_voice_verification_request({"request_id": request_id, "profile_id": profile_id, "verification_mode": mode}).request


def make_execution_request(profile_id="voice_1", request_id="r1", mode="STANDARD", registered=None):
    registry = create_voice_verification_registry(tuple(
        create_voice_identity_profile({"profile_id": i, "display_name": "N " + i, "enabled": True, "enrollment_status": "not_enrolled"}).profile
        for i in (registered or (profile_id,)))).registry
    plan = create_voice_verification_plan(validate_voice_verification_request(make_request(profile_id, request_id, mode))).plan
    auth = authorize_voice_verification(make_request(profile_id, request_id, mode), registry, plan)
    return create_voice_verification_execution_request(auth, plan)


def raw(request_id, profile_id, mode, codes=()):
    return VoiceVerificationExecutionRequest(er._CREATE_TOKEN, request_id, profile_id, mode, codes)


def rejected_request(code="VOICE_VERIFICATION_EXECUTION_REQUEST_NOT_AUTHORIZED"):
    return raw(None, None, None, (code,))


class TestInvalidRequest(unittest.TestCase):
    def assertInvalid(self, out):
        self.assertIs(type(out), VoiceVerificationExecutionResult)
        self.assertEqual((out.ok, out.request_id, out.profile_id, out.verification_mode, out.status, out.failure_codes),
                         (False, None, None, None, "rejected", (INVALID,)))

    def test_1_invalid_inputs(self):
        good = make_execution_request()
        for bad in (None, {}, [], (), "r1", 1, True, object(), good.to_dict(), make_request(), type("X", (), {})()):
            self.assertInvalid(execute_voice_verification(bad))

    def test_1b_malformed_exact_requests_are_invalid(self):
        for ok_codes in ((), ):
            for rid, pid, mode in ((None, "p", "m"), ("r", None, "m"), ("r", "p", None), ("", "p", "m"), ("r", "", "m"), ("r", "p", ""),
                                   (Str("r"), "p", "m"), ("r", Str("p"), "m"), ("r", "p", Str("m")), (1, "p", "m")):
                self.assertInvalid(execute_voice_verification(raw(rid, pid, mode, ok_codes)))

    def test_1c_ok_that_is_not_a_bool_and_unreadable_properties_are_invalid(self):
        req = make_execution_request()
        with mock.patch.object(VoiceVerificationExecutionRequest, "ok", property(lambda self: 1)):
            self.assertInvalid(execute_voice_verification(req))
        with mock.patch.object(VoiceVerificationExecutionRequest, "ok", property(lambda self: None)):
            self.assertInvalid(execute_voice_verification(req))

        def boom(self):
            raise RuntimeError("boom")
        for name in ("ok", "request_id", "profile_id", "verification_mode", "failure_codes"):
            req = make_execution_request()
            with mock.patch.object(VoiceVerificationExecutionRequest, name, property(boom)):
                self.assertInvalid(execute_voice_verification(req))
        with mock.patch.object(VoiceVerificationExecutionRequest, "failure_codes", property(lambda self: ["x"])):
            self.assertInvalid(execute_voice_verification(req))
        with mock.patch.object(VoiceVerificationExecutionRequest, "failure_codes", property(lambda self: ("x",))):
            self.assertInvalid(execute_voice_verification(req))

    def test_19_lookalike_and_spoofed_requests_are_rejected_without_being_read(self):
        touched = []

        class Spoof:
            @property
            def __class__(self):
                return VoiceVerificationExecutionRequest

            def __getattribute__(self, name):
                if name != "__class__":
                    touched.append(name)
                return True

        class Duck:
            ok, request_id, profile_id, verification_mode, failure_codes = True, "r", "p", "m", ()

        for bad in (Spoof(), Duck(), mock.Mock(spec=VoiceVerificationExecutionRequest), mock.MagicMock()):
            self.assertInvalid(execute_voice_verification(bad))
        self.assertEqual(touched, [])
        with self.assertRaises(TypeError):
            type("Sub", (VoiceVerificationExecutionRequest,), {})


class TestNotAuthorized(unittest.TestCase):
    def test_2_rejected_request_is_not_authorized_and_exposes_nothing(self):
        for req in (rejected_request(), rejected_request("VOICE_VERIFICATION_EXECUTION_REQUEST_INVALID_INPUT"),
                    create_voice_verification_execution_request(None, None), make_execution_request("voice_1", registered=("voice_2",))):
            self.assertFalse(req.ok)
            out = execute_voice_verification(req)
            self.assertIs(type(out), VoiceVerificationExecutionResult)
            self.assertEqual((out.ok, out.request_id, out.profile_id, out.verification_mode, out.status, out.failure_codes),
                             (False, None, None, None, "rejected", (NOT_AUTH,)))

    def test_2b_data_of_an_unsuccessful_request_is_not_exposed(self):
        out = execute_voice_verification(raw("secret-r", "secret-p", "secret-m", ("X",)))
        self.assertEqual((out.request_id, out.profile_id, out.verification_mode, out.status, out.failure_codes), (None, None, None, "rejected", (NOT_AUTH,)))
        self.assertNotIn("secret", repr(out) + repr(out.to_dict()))


class TestNotImplemented(unittest.TestCase):
    def test_3_valid_request_returns_not_implemented_never_success(self):
        out = execute_voice_verification(make_execution_request("voice_2", "req-9", "FAST"))
        self.assertIs(type(out), VoiceVerificationExecutionResult)
        self.assertIs(out.ok, False)
        self.assertEqual(out.status, "not_implemented")
        self.assertEqual(out.failure_codes, (NOT_IMPL,))
        self.assertEqual(out.to_dict(), {"ok": False, "request_id": "req-9", "profile_id": "voice_2", "verification_mode": "FAST",
                                         "status": "not_implemented", "failure_codes": [NOT_IMPL]})
        self.assertEqual(list(out.to_dict()), ["ok", "request_id", "profile_id", "verification_mode", "status", "failure_codes"])

    def test_4_request_id_preserved_exactly(self):
        for rid in ("r", "R-1", " r ", "id\n", "\u00e9", "0", "x" * 500):
            req = make_execution_request(request_id=rid)
            out = execute_voice_verification(req)
            self.assertIs(out.request_id, req.request_id)
            self.assertEqual(out.request_id, rid)

    def test_5_profile_id_preserved_exactly(self):
        for pid in ("a", "A", " a ", "voice id\n", "\u00e9", "0", "x" * 500):
            req = make_execution_request(profile_id=pid)
            out = execute_voice_verification(req)
            self.assertIs(out.profile_id, req.profile_id)
            self.assertEqual(out.profile_id, pid)

    def test_6_verification_mode_preserved_exactly(self):
        for mode in ("STANDARD", "standard", " m ", "free text mode", "m\n", "\u00e9", "x" * 300):
            req = make_execution_request(mode=mode)
            out = execute_voice_verification(req)
            self.assertIs(out.verification_mode, req.verification_mode)
            self.assertEqual(out.verification_mode, mode)

    def test_7_nothing_is_normalized(self):
        out = execute_voice_verification(raw(" Req ", "Voice_1", "Mode X"))
        self.assertEqual((out.request_id, out.profile_id, out.verification_mode), (" Req ", "Voice_1", "Mode X"))


class TestCodesAndStatuses(unittest.TestCase):
    def test_8_codes_and_statuses(self):
        self.assertEqual(ex.FAILURE_CODES, (INVALID, NOT_AUTH, NOT_IMPL))
        self.assertEqual(ex.STATUSES, ("rejected", "not_implemented"))
        cases = ((None, INVALID, "rejected"), (rejected_request(), NOT_AUTH, "rejected"), (make_execution_request(), NOT_IMPL, "not_implemented"))
        for source, code, status in cases:
            out = execute_voice_verification(source)
            self.assertEqual(out.failure_codes, (code,))
            self.assertIs(type(out.failure_codes), tuple)
            self.assertIs(type(out.status), str)
            self.assertEqual(out.status, status)
            self.assertIn(out.status, ex.STATUSES)
            self.assertIs(out.ok, False)
            self.assertIs(type(out.ok), bool)

    def test_9_no_result_is_ever_successful(self):
        sources = [None, {}, rejected_request(), make_execution_request(), raw("r", "p", "m"), raw("", "p", "m")]
        self.assertTrue(all(execute_voice_verification(s).ok is False for s in sources))


class TestNoSideEffects(unittest.TestCase):
    def test_10_no_filesystem_access(self):
        req = make_execution_request()
        trip = mock.Mock(side_effect=AssertionError("filesystem must not be touched"))
        with mock.patch.object(builtins, "open", trip), mock.patch.object(io, "open", trip), mock.patch.object(os, "open", trip), \
                mock.patch.object(os, "listdir", trip), mock.patch.object(os, "scandir", trip), mock.patch.object(os, "stat", trip):
            for source in (req, None, rejected_request(), raw("r", "p", "m")):
                execute_voice_verification(source)
        trip.assert_not_called()

    def test_11_no_microphone_audio_or_network_access(self):
        req = make_execution_request()
        trip = mock.Mock(side_effect=AssertionError("must not be touched"))
        with mock.patch.object(socket, "socket", trip), mock.patch.object(socket, "create_connection", trip), mock.patch.object(socket, "getaddrinfo", trip):
            execute_voice_verification(req)
        trip.assert_not_called()
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(("." * node.level) + (node.module or ""))
        self.assertEqual(imported, {".voice_verification_execution_request"})
        with open(MODULE, encoding="utf-8") as fh:
            code = "\n".join(line for line in fh.read().split('"""', 2)[2].splitlines())
        for token in ("open(", "wave", "pyaudio", "sounddevice", "socket", "urllib", "requests", "numpy", "torch", "android", "random", "time.", "os.", "sys."):
            self.assertNotIn(token, code, token)

    def test_12_request_is_not_mutated(self):
        for source in (make_execution_request(), rejected_request(), raw(" r ", "p", "m")):
            before = (source.ok, source.request_id, source.profile_id, source.verification_mode, source.failure_codes, source.to_dict(), hash(source), repr(source))
            execute_voice_verification(source)
            after = (source.ok, source.request_id, source.profile_id, source.verification_mode, source.failure_codes, source.to_dict(), hash(source), repr(source))
            self.assertEqual(before, after)

    def test_13_source_request_is_not_retained(self):
        for source in (make_execution_request(), rejected_request(), raw("r", "p", "m")):
            out = execute_voice_verification(source)
            seen, stack = set(), [out]
            while stack:
                node = stack.pop()
                if id(node) in seen:
                    continue
                seen.add(id(node))
                if not isinstance(node, (type, type(None))):
                    stack.extend(gc.get_referents(node))
            self.assertNotIn(id(source), seen)
            self.assertFalse(any(r is source for r in gc.get_referents(out)))
        text = repr(execute_voice_verification(make_execution_request())) + repr(execute_voice_verification(make_execution_request()).to_dict())
        for leaked in ("VoiceVerificationExecutionRequest", "VoiceVerificationPlan", "VoiceVerificationAuthorization", "display_name", "enrollment_status"):
            self.assertNotIn(leaked, text)

    def test_14_result_holds_only_minimal_plain_data(self):
        self.assertEqual(VoiceVerificationExecutionResult.__slots__, ("_ok", "_request_id", "_profile_id", "_verification_mode", "_status", "_failure_codes"))
        for source in (make_execution_request(), rejected_request(), None):
            out = execute_voice_verification(source)
            for value in (out.request_id, out.profile_id, out.verification_mode):
                self.assertTrue(value is None or type(value) is str)
            self.assertTrue(all(type(c) is str for c in out.failure_codes))

    def test_15_repeated_calls_are_deterministic(self):
        for source in (make_execution_request("voice_1", "r1", "STANDARD"), rejected_request(), None):
            first = execute_voice_verification(source)
            for _ in range(20):
                again = execute_voice_verification(source)
                self.assertEqual(again, first)
                self.assertEqual(hash(again), hash(first))
                self.assertEqual(repr(again), repr(first))
        self.assertEqual(execute_voice_verification(make_execution_request()), execute_voice_verification(make_execution_request()))


class TestResultObject(unittest.TestCase):
    def test_16_immutability(self):
        for out in (execute_voice_verification(make_execution_request()), execute_voice_verification(None)):
            for name in ("ok", "request_id", "profile_id", "verification_mode", "status", "failure_codes", "_ok", "_status", "_failure_codes", "extra"):
                with self.assertRaises(AttributeError, msg=name):
                    setattr(out, name, 1)
                with self.assertRaises(AttributeError, msg=name):
                    delattr(out, name)
            self.assertFalse(hasattr(out, "__dict__"))
            self.assertIs(type(out.failure_codes), tuple)

    def test_17_equality_and_hash(self):
        a = execute_voice_verification(make_execution_request())
        b = execute_voice_verification(make_execution_request())
        c = execute_voice_verification(make_execution_request(request_id="other"))
        d = execute_voice_verification(make_execution_request(mode="OTHER"))
        e = execute_voice_verification(None)
        f = execute_voice_verification(rejected_request())
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertEqual(len({a, b, c, d, e, f}), 5)
        self.assertNotEqual(e, f)
        self.assertNotEqual(a, a.to_dict())
        self.assertNotEqual(a, make_execution_request())
        self.assertNotEqual(a, ("r1", "voice_1", "STANDARD"))
        self.assertEqual(repr(e), "VoiceVerificationExecutionResult(ok=False, request_id=None, profile_id=None, verification_mode=None, "
                                  "status='rejected', failure_codes=('%s',))" % INVALID)

    def test_18_copy_and_deepcopy_return_same_object(self):
        out = execute_voice_verification(make_execution_request())
        self.assertIs(copy.copy(out), out)
        self.assertIs(copy.deepcopy(out), out)
        self.assertIs(copy.deepcopy({"k": [out]})["k"][0], out)

    def test_20_to_dict_is_fresh_and_mutation_safe(self):
        for out in (execute_voice_verification(make_execution_request()), execute_voice_verification(None)):
            first = out.to_dict()
            snapshot = copy.deepcopy(first)
            first["failure_codes"].append("x")
            first["ok"] = "hacked"
            first["status"] = first["request_id"] = first["profile_id"] = first["verification_mode"] = "hacked"
            first["extra"] = 1
            self.assertEqual(out.to_dict(), snapshot)
            self.assertIsNot(out.to_dict(), out.to_dict())
            self.assertIsNot(out.to_dict()["failure_codes"], out.to_dict()["failure_codes"])

    def test_21_direct_construction_subclassing_and_pickle_are_refused(self):
        for args in ((object(), False, "r", "p", "m", "rejected", ()), (None, False, "r", "p", "m", "rejected", ()), (ex._CREATE_TOKEN,), ()):
            if args and args[0] is ex._CREATE_TOKEN:
                with self.assertRaises(TypeError):
                    VoiceVerificationExecutionResult(*args)
                continue
            with self.assertRaises(TypeError):
                VoiceVerificationExecutionResult(*args)
        with self.assertRaises(TypeError):
            type("Sub", (VoiceVerificationExecutionResult,), {})
        out = execute_voice_verification(make_execution_request())
        for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
            with self.assertRaises(TypeError):
                pickle.dumps(out, protocol)


class TestBoundaries(unittest.TestCase):
    def test_22_no_other_module_references_the_execution_boundary(self):
        voice_dir = os.path.join(PY_ROOT, "voice")
        for name in sorted(os.listdir(voice_dir)):
            if name.endswith(".py") and name != "voice_verification_execution.py":
                with open(os.path.join(voice_dir, name), encoding="utf-8") as fh:
                    text = fh.read()
                for token in ("voice_verification_execution import", "VoiceVerificationExecutionResult", "execute_voice_verification("):
                    self.assertNotIn(token, text, (name, token))
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if not (folder == PY_ROOT and d in ("voice", "tests", "data")) and d != "__pycache__"]
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        self.assertNotIn("voice_verification_execution", fh.read(), name)
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py", "android_entry.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("execute_voice_verification", "voice_verification_execution", "from voice", "import voice"):
                self.assertNotIn(token, text, (rel, token))

    def test_23_existing_contract_reused_and_no_state_added(self):
        self.assertIs(ex.VoiceVerificationExecutionRequest, VoiceVerificationExecutionRequest)
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.ImportFrom))
        for name, value in vars(ex).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_24_voice_package_pristine_database_no_bytecode_and_documentation(self):
        listing = sorted(f for f in os.listdir(os.path.join(PY_ROOT, "voice")) if f != "__pycache__")
        self.assertIn("voice_verification_execution.py", listing)
        self.assertEqual(len(listing), 28)
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("execute_voice_verification", "VoiceVerificationExecutionResult", "VoiceVerificationExecutionRequest", "VOICE_VERIFICATION_EXECUTION_",
                       "INVALID_REQUEST", "NOT_AUTHORIZED", "NOT_IMPLEMENTED", "not_implemented", "does NOT", "biometrics", "embeddings", "Prompt 814"):
            self.assertIn(marker, text, marker)


if __name__ == "__main__":
    unittest.main()
