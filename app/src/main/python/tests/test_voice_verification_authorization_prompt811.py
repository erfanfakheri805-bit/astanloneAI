"""Prompt 811 - Section 10 voice verification authorization boundary (`voice.voice_verification_authorization`)."""
import ast
import copy
import gc
import hashlib
import os
import pickle
import unittest
from unittest import mock

from voice import voice_verification_authorization as au
from voice import voice_verification_batch as batch_mod
from voice import voice_verification_decision as dec_mod
from voice import voice_verification_dispatcher as dispatcher_mod
from voice import voice_verification_executor as executor_mod
from voice import voice_verification_handoff as ho_mod
from voice import voice_verification_pipeline as pipeline_mod
from voice import voice_verification_plan as plan_mod
from voice import voice_verification_profile_resolver as pr_mod
from voice import voice_verification_request as vr_mod
from voice.voice_identity_profile import create_voice_identity_profile
from voice.voice_verification_authorization import VoiceVerificationAuthorization, authorize_voice_verification
from voice.voice_verification_plan import VoiceVerificationPlan, create_voice_verification_plan
from voice.voice_verification_registry import VoiceVerificationRegistry, create_voice_verification_registry
from voice.voice_verification_request import VoiceVerificationRequest, create_voice_verification_request
from voice.voice_verification_request_validator import validate_voice_verification_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section10_voice_verification_authorization_prompt811.md")
MODULE = os.path.join(PY_ROOT, "voice", "voice_verification_authorization.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
P = "VOICE_VERIFICATION_AUTHORIZATION_"
INVALID_INPUT, REJECTED = P + "INVALID_INPUT", P + "REJECTED"
R = "VOICE_VERIFICATION_PROFILE_RESOLVER_"
NOT_FOUND, INVALID_REQUEST, INVALID_REGISTRY = R + "PROFILE_NOT_FOUND", R + "INVALID_REQUEST", R + "INVALID_REGISTRY"
H = "VOICE_VERIFICATION_HANDOFF_"
H_REJECTED_DECISION, H_MISMATCH, H_INVALID = H + "REJECTED_DECISION", H + "PROFILE_MISMATCH", H + "INVALID_INPUT"


class Str(str):
    pass


def req(profile_id="voice_1"):
    return create_voice_verification_request({"request_id": "r1", "profile_id": profile_id, "verification_mode": "STANDARD"}).request


def reg(*ids):
    items = tuple(create_voice_identity_profile({"profile_id": i, "display_name": "N " + i, "enabled": True, "enrollment_status": "not_enrolled"}).profile
                  for i in (ids or ("voice_1", "voice_2")))
    return create_voice_verification_registry(items).registry


def plan(profile_id="voice_1"):
    result = create_voice_verification_plan(validate_voice_verification_request(req(profile_id)))
    assert result.ok, result.failures
    return result.plan


def raw_request(profile_id="voice_1", request_id="r", mode="m"):
    return VoiceVerificationRequest(vr_mod._CREATE_TOKEN, request_id, profile_id, mode)


def raw_plan(profile_id):
    return VoiceVerificationPlan(plan_mod._CREATE_TOKEN, "r", profile_id, "m")


class Recorder:
    """Wraps the three composed stages (as imported by the authorization module) and every execution entry point; records calls and results."""

    def __enter__(self):
        self.stages, self.results, self.forbidden = [], {}, []

        def wrap(name, real):
            def f(*a, **k):
                self.stages.append(name)
                out = real(*a, **k)
                self.results[name] = out
                return out
            return f

        def trip(name):
            def f(*a, **k):
                self.forbidden.append(name)
                raise AssertionError(name + " must not be called")
            return f
        self._patches = [mock.patch.object(au, "resolve_voice_verification_profile", wrap("resolve", au.resolve_voice_verification_profile)),
                         mock.patch.object(au, "decide_voice_verification", wrap("decide", au.decide_voice_verification)),
                         mock.patch.object(au, "create_voice_verification_handoff", wrap("handoff", au.create_voice_verification_handoff)),
                         mock.patch.object(executor_mod, "execute_voice_verification_plan", trip("executor")),
                         mock.patch.object(dispatcher_mod, "dispatch_voice_verification", trip("dispatcher")),
                         mock.patch.object(pipeline_mod, "run_voice_verification_pipeline", trip("pipeline")),
                         mock.patch.object(batch_mod, "run_voice_verification_batch", trip("batch"))]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


class TestAuthorized(unittest.TestCase):
    def test_1_matching_request_registry_plan_is_authorized(self):
        out = authorize_voice_verification(req("voice_2"), reg(), plan("voice_2"))
        self.assertIs(type(out), VoiceVerificationAuthorization)
        self.assertIs(out.authorized, True)
        self.assertEqual((out.profile_id, out.failure_codes), ("voice_2", ()))
        self.assertEqual(out.to_dict(), {"authorized": True, "profile_id": "voice_2", "failure_codes": []})

    def test_2_profile_id_is_preserved_exactly(self):
        for pid in ("a", "A", " a ", "voice id\n", "\u00e9", "0", "x" * 500):
            r = reg(pid)
            out = authorize_voice_verification(req(pid), r, plan(pid))
            self.assertTrue(out.authorized)
            self.assertIs(out.profile_id, r.lookup(pid).profile.profile_id)
            self.assertEqual(out.profile_id, pid)

    def test_3_stages_run_once_each_in_the_fixed_order(self):
        with Recorder() as rec:
            authorize_voice_verification(req("voice_1"), reg(), plan("voice_1"))
        self.assertEqual(rec.stages, ["resolve", "decide", "handoff"])
        self.assertEqual(rec.forbidden, [])

    def test_4_disabled_profiles_are_not_interpreted(self):
        p = create_voice_identity_profile({"profile_id": "x", "display_name": "X", "enabled": False, "enrollment_status": "revoked"}).profile
        r = create_voice_verification_registry((p,)).registry
        self.assertTrue(authorize_voice_verification(req("x"), r, plan("x")).authorized)


class TestRejectedStages(unittest.TestCase):
    def assertRejected(self, out, codes):
        self.assertIs(type(out), VoiceVerificationAuthorization)
        self.assertEqual((out.authorized, out.profile_id, out.failure_codes), (False, None, codes))
        self.assertEqual(out.to_dict(), {"authorized": False, "profile_id": None, "failure_codes": list(codes)})

    def test_5_missing_profile_is_rejected_with_every_underlying_code_in_order(self):
        self.assertRejected(authorize_voice_verification(req("nobody"), reg(), plan("nobody")), (REJECTED, NOT_FOUND, H_REJECTED_DECISION))

    def test_6_empty_registry_is_a_rejected_resolution(self):
        empty = create_voice_verification_registry(()).registry
        self.assertRejected(authorize_voice_verification(req("voice_1"), empty, plan("voice_1")), (REJECTED, NOT_FOUND, H_REJECTED_DECISION))

    def test_7_plan_profile_mismatch_is_rejected_with_the_handoff_code(self):
        self.assertRejected(authorize_voice_verification(req("voice_1"), reg(), plan("voice_2")), (REJECTED, H_MISMATCH))

    def test_8_exact_request_that_fails_validation_is_rejected_with_resolver_codes(self):
        for bad in (raw_request(profile_id=""), raw_request(profile_id=Str("voice_1")), raw_request(request_id=""), raw_request(mode=1)):
            self.assertRejected(authorize_voice_verification(bad, reg(), plan("voice_1")), (REJECTED, INVALID_REQUEST, H_REJECTED_DECISION))

    def test_9_exact_plan_with_malformed_profile_id_is_rejected_with_the_handoff_code(self):
        for pid in ("", None, 5, Str("voice_1")):
            self.assertRejected(authorize_voice_verification(req("voice_1"), reg(), raw_plan(pid)), (REJECTED, H_INVALID))

    def test_10_underlying_codes_come_from_the_stages_unchanged_and_in_stage_order(self):
        with Recorder() as rec:
            out = authorize_voice_verification(req("nobody"), reg(), plan("voice_1"))
        decision, handoff = rec.results["decide"], rec.results["handoff"]
        self.assertEqual(out.failure_codes, (REJECTED,) + decision.failure_codes + handoff.failure_codes)
        self.assertEqual(decision.failure_codes, (NOT_FOUND,))
        self.assertEqual(handoff.failure_codes, (H_REJECTED_DECISION,))

    def test_11_stage_codes_are_forwarded_verbatim_not_rewritten(self):
        fake_decision = dec_mod.VoiceVerificationDecision(dec_mod._CREATE_TOKEN, False, None, ("A", "B", "A"), "X")
        fake_handoff = ho_mod.VoiceVerificationHandoff(ho_mod._CREATE_TOKEN, False, None, ("C",))
        with mock.patch.object(au, "decide_voice_verification", lambda r: fake_decision), \
                mock.patch.object(au, "create_voice_verification_handoff", lambda d, p: fake_handoff):
            out = authorize_voice_verification(req(), reg(), plan())
        self.assertEqual(out.failure_codes, (REJECTED, "A", "B", "A", "C"))
        self.assertEqual((out.authorized, out.profile_id), (False, None))

    def test_12_an_inconsistent_approved_handoff_is_not_authorized(self):
        for pid in (None, "", 5):
            fake = ho_mod.VoiceVerificationHandoff(ho_mod._CREATE_TOKEN, True, pid, ())
            with mock.patch.object(au, "create_voice_verification_handoff", lambda d, p: fake):
                out = authorize_voice_verification(req(), reg(), plan())
            self.assertEqual((out.authorized, out.profile_id, out.failure_codes), (False, None, (REJECTED,)))
        for approved in (1, "yes", None):
            fake = ho_mod.VoiceVerificationHandoff(ho_mod._CREATE_TOKEN, approved, "voice_1", ())
            with mock.patch.object(au, "create_voice_verification_handoff", lambda d, p: fake):
                self.assertFalse(authorize_voice_verification(req(), reg(), plan()).authorized)


class TestInvalidInputs(unittest.TestCase):
    def assertInvalid(self, out):
        self.assertIs(type(out), VoiceVerificationAuthorization)
        self.assertEqual((out.authorized, out.profile_id, out.failure_codes), (False, None, (INVALID_INPUT,)))

    def test_13_invalid_request_type(self):
        for bad in (None, {}, "voice_1", 1, True, [], object(), req().to_dict(), plan("voice_1"), reg()):
            with Recorder() as rec:
                self.assertInvalid(authorize_voice_verification(bad, reg(), plan()))
            self.assertEqual((rec.stages, rec.forbidden), ([], []))

    def test_14_invalid_registry_type(self):
        for bad in (None, {}, [], (), "registry", 1, object(), req(), plan(), reg().profiles, create_voice_verification_registry(())):
            with Recorder() as rec:
                self.assertInvalid(authorize_voice_verification(req(), bad, plan()))
            self.assertEqual((rec.stages, rec.forbidden), ([], []))

    def test_15_invalid_plan_type(self):
        for bad in (None, {}, [], "plan", 1, object(), plan().to_dict(), req(), reg()):
            with Recorder() as rec:
                self.assertInvalid(authorize_voice_verification(req(), reg(), bad))
            self.assertEqual((rec.stages, rec.forbidden), ([], []))

    def test_16_all_invalid_gives_one_code_and_swapped_arguments_are_invalid(self):
        self.assertInvalid(authorize_voice_verification(None, None, None))
        self.assertInvalid(authorize_voice_verification(plan(), reg(), req()))
        self.assertInvalid(authorize_voice_verification(reg(), req(), plan()))


class TestSpoofedAndLookAlikes(unittest.TestCase):
    def assertInvalidNoStage(self, *args):
        with Recorder() as rec:
            out = authorize_voice_verification(*args)
        self.assertEqual((out.authorized, out.profile_id, out.failure_codes), (False, None, (INVALID_INPUT,)))
        self.assertEqual((rec.stages, rec.forbidden), ([], []))

    def test_17_spoofed_class_objects_are_rejected_without_reading_them(self):
        touched, lookups = [], []

        class SpoofRequest:
            __class__ = VoiceVerificationRequest
            request_id, profile_id, verification_mode = "r", "voice_1", "m"

            def __getattribute__(self, name):
                touched.append(name)
                return object.__getattribute__(self, name)

        class SpoofRegistry:
            __class__ = VoiceVerificationRegistry

            def lookup(self, profile_id):
                lookups.append(profile_id)

        class SpoofPlan:
            __class__ = VoiceVerificationPlan
            request_id, profile_id, verification_mode = "r", "voice_1", "m"
        self.assertInvalidNoStage(SpoofRequest(), reg(), plan())
        self.assertInvalidNoStage(req(), SpoofRegistry(), plan())
        self.assertInvalidNoStage(req(), reg(), SpoofPlan())
        self.assertInvalidNoStage(SpoofRequest(), SpoofRegistry(), SpoofPlan())
        self.assertEqual((touched, lookups), ([], []))

    def test_18_look_alikes_with_the_same_public_surface_are_rejected(self):
        real_reg = reg()
        calls = []

        class LookRequest:
            request_id, profile_id, verification_mode = "r", "voice_1", "m"

            def to_dict(self):
                return {"request_id": "r", "profile_id": "voice_1", "verification_mode": "m"}

        class LookRegistry:
            profiles = real_reg.profiles
            profile_ids = real_reg.profile_ids

            def lookup(self, profile_id):
                calls.append(profile_id)
                return real_reg.lookup(profile_id)

        class LookPlan:
            request_id, profile_id, verification_mode = "r", "voice_1", "m"

            def to_dict(self):
                return {"request_id": "r", "profile_id": "voice_1", "verification_mode": "m"}
        self.assertInvalidNoStage(LookRequest(), real_reg, plan())
        self.assertInvalidNoStage(req(), LookRegistry(), plan())
        self.assertInvalidNoStage(req(), real_reg, LookPlan())
        self.assertInvalidNoStage(mock.Mock(), real_reg, plan())
        self.assertInvalidNoStage(req(), mock.MagicMock(spec=VoiceVerificationRegistry), plan())
        self.assertInvalidNoStage(req(), real_reg, mock.MagicMock(spec=VoiceVerificationPlan))
        self.assertEqual(calls, [])

    def test_19_composed_contract_classes_cannot_be_subclassed(self):
        for base in (VoiceVerificationRequest, VoiceVerificationRegistry, VoiceVerificationPlan, VoiceVerificationAuthorization):
            with self.assertRaises(TypeError):
                type("Sub", (base,), {})


class TestNoExecution(unittest.TestCase):
    def test_20_no_executor_dispatcher_pipeline_or_batch_call_in_any_branch(self):
        cases = [(req("voice_1"), reg(), plan("voice_1")), (req("nobody"), reg(), plan("voice_1")), (req("voice_1"), reg(), plan("voice_2")),
                 (raw_request(profile_id=""), reg(), plan()), (req(), reg(), raw_plan(None)), (None, reg(), plan()), (req(), None, plan()), (req(), reg(), None)]
        with Recorder() as rec:
            for case in cases:
                authorize_voice_verification(*case)
        self.assertEqual(rec.forbidden, [])
        self.assertEqual(rec.stages, ["resolve", "decide", "handoff"] * 5)

    def test_21_module_imports_only_the_composed_contracts_and_stage_functions(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        nodes = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertTrue(all(isinstance(n, ast.ImportFrom) for n in nodes))
        self.assertEqual(sorted((n.module, n.level, tuple(a.name for a in n.names)) for n in nodes),
                         [("voice_verification_decision", 1, ("decide_voice_verification",)),
                          ("voice_verification_handoff", 1, ("create_voice_verification_handoff",)),
                          ("voice_verification_plan", 1, ("VoiceVerificationPlan",)),
                          ("voice_verification_profile_resolver", 1, ("resolve_voice_verification_profile",)),
                          ("voice_verification_registry", 1, ("VoiceVerificationRegistry",)),
                          ("voice_verification_request", 1, ("VoiceVerificationRequest",))])
        self.assertEqual(sorted(n.name for n in tree.body if isinstance(n, ast.ClassDef)), ["VoiceVerificationAuthorization"])
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("execute_voice_verification_plan", "dispatch_voice_verification", "run_voice_verification_pipeline", "run_voice_verification_batch",
                     "lookup", "create_voice_verification_plan", "validate_voice_verification_request", "os", "sys", "io", "pathlib", "subprocess", "socket",
                     "urllib", "http", "requests", "numpy", "wave", "sqlite3", "random", "time", "datetime", "anthropic", "openai", "core", "agent", "planning",
                     "audio", "embedding", "embeddings", "microphone", "android", "__class__", "__dict__"):
            self.assertNotIn(word, names, word)
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "getattr", "setattr", "globals", "vars", "isinstance"):
            self.assertNotIn(forbidden, calls)

    def test_22_module_reads_only_public_properties_of_the_stage_results(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        read = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in ("decision", "handoff", "resolution", "request", "registry", "plan"):
                read.setdefault(n.value.id, set()).add(n.attr)
        self.assertEqual(read, {"decision": {"failure_codes"}, "handoff": {"profile_id", "approved", "failure_codes"}})


class TestDeterminismAndNoMutation(unittest.TestCase):
    def test_23_repeated_calls_give_equal_results(self):
        r, rg, p = req("voice_1"), reg(), plan("voice_1")
        for args in ((r, rg, p), (req("nobody"), rg, p), (r, rg, plan("voice_2")), (None, None, None)):
            first = authorize_voice_verification(*args)
            for _ in range(3):
                again = authorize_voice_verification(*args)
                self.assertIsNot(again, first)
                self.assertEqual(again, first)
                self.assertEqual(hash(again), hash(first))
                self.assertEqual(again.to_dict(), first.to_dict())

    def test_24_supplied_objects_are_not_mutated(self):
        r, rg, p = req("voice_1"), reg(), plan("voice_1")
        before = (r.to_dict(), rg.to_dict(), rg.profiles, p.to_dict(), r, rg, p)
        authorize_voice_verification(r, rg, p)
        authorize_voice_verification(req("nobody"), rg, plan("voice_2"))
        authorize_voice_verification(r, rg, plan("voice_2"))
        self.assertEqual((r.to_dict(), rg.to_dict(), rg.profiles, p.to_dict(), r, rg, p), before)

    def test_25_codes_are_stable_and_authorized_matches_empty_codes(self):
        self.assertEqual(au.FAILURE_CODES, (INVALID_INPUT, REJECTED))
        self.assertEqual(INVALID_INPUT, "VOICE_VERIFICATION_AUTHORIZATION_INVALID_INPUT")
        self.assertEqual(REJECTED, "VOICE_VERIFICATION_AUTHORIZATION_REJECTED")
        for case in ((req(), reg(), plan()), (req("nobody"), reg(), plan()), (req(), reg(), plan("voice_2")), (None, None, None)):
            out = authorize_voice_verification(*case)
            self.assertEqual(out.authorized, out.failure_codes == ())
            self.assertEqual(out.authorized, out.profile_id is not None)
            if not out.authorized:
                self.assertIn(out.failure_codes[0], au.FAILURE_CODES)


class TestEqualityToDictImmutability(unittest.TestCase):
    def test_26_equality_and_hash_by_value(self):
        a = authorize_voice_verification(req("voice_1"), reg(), plan("voice_1"))
        b = authorize_voice_verification(req("voice_1"), reg(), plan("voice_1"))
        c = authorize_voice_verification(req("voice_2"), reg(), plan("voice_2"))
        d = authorize_voice_verification(req("voice_1"), reg(), plan("voice_2"))
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertNotEqual(a, c)
        self.assertEqual(len({a, b, c, d}), 3)
        self.assertNotEqual(a, a.to_dict())
        self.assertNotEqual(a, (True, "voice_1", ()))
        self.assertEqual(repr(d), "VoiceVerificationAuthorization(authorized=False, profile_id=None, failure_codes=('%s', '%s'))" % (REJECTED, H_MISMATCH))

    def test_27_to_dict_is_fresh_every_call(self):
        for out in (authorize_voice_verification(req(), reg(), plan()), authorize_voice_verification(req("nobody"), reg(), plan())):
            first = out.to_dict()
            snapshot = copy.deepcopy(first)
            first["failure_codes"].append("x")
            first["authorized"] = "hacked"
            first["profile_id"] = "hacked"
            first["extra"] = 1
            self.assertEqual(out.to_dict(), snapshot)
            self.assertIsNot(out.to_dict(), out.to_dict())
            self.assertIsNot(out.to_dict()["failure_codes"], out.to_dict()["failure_codes"])
            self.assertEqual(list(out.to_dict()), ["authorized", "profile_id", "failure_codes"])

    def test_28_attributes_cannot_be_assigned_or_deleted(self):
        for out in (authorize_voice_verification(req(), reg(), plan()), authorize_voice_verification(None, None, None)):
            for name in ("authorized", "profile_id", "failure_codes", "_authorized", "_profile_id", "_failure_codes", "extra"):
                with self.assertRaises(AttributeError, msg=name):
                    setattr(out, name, 1)
                with self.assertRaises(AttributeError, msg=name):
                    delattr(out, name)
            self.assertFalse(hasattr(out, "__dict__"))
            self.assertIs(type(out.failure_codes), tuple)

    def test_29_direct_construction_subclassing_copy_and_pickle_are_refused(self):
        for args in ((object(), True, "a", ()), (None, True, "a", ()), ()):
            with self.assertRaises(TypeError):
                VoiceVerificationAuthorization(*args)
        self.assertEqual(VoiceVerificationAuthorization.__slots__, ("_authorized", "_profile_id", "_failure_codes"))
        out = authorize_voice_verification(req(), reg(), plan())
        self.assertIs(copy.copy(out), out)
        self.assertIs(copy.deepcopy(out), out)
        for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
            with self.assertRaises(TypeError):
                pickle.dumps(out, protocol)


class TestNonRetention(unittest.TestCase):
    def test_30_authorization_holds_only_minimal_plain_data(self):
        for case in ((req(), reg(), plan()), (req("nobody"), reg(), plan()), (req(), reg(), plan("voice_2")), (None, None, None)):
            out = authorize_voice_verification(*case)
            self.assertIs(type(out.authorized), bool)
            self.assertTrue(out.profile_id is None or type(out.profile_id) is str)
            self.assertTrue(all(type(c) is str for c in out.failure_codes))

    def test_31_no_source_or_intermediate_object_is_reachable_from_the_result(self):
        for rq, rg, pl in ((req("voice_1"), reg(), plan("voice_1")), (req("nobody"), reg(), plan("voice_1")), (req("voice_1"), reg(), plan("voice_2"))):
            with Recorder() as rec:
                out = authorize_voice_verification(rq, rg, pl)
            tracked = [rq, rg, pl] + list(rec.results.values())
            self.assertEqual(len(tracked), 6)
            seen, stack = set(), [out]
            while stack:
                node = stack.pop()
                if id(node) in seen:
                    continue
                seen.add(id(node))
                if not isinstance(node, (type, type(None))):
                    stack.extend(gc.get_referents(node))
            for obj in tracked:
                self.assertNotIn(id(obj), seen, type(obj).__name__)
                self.assertFalse(any(r is obj for r in gc.get_referents(out)))

    def test_32_request_and_plan_details_and_stage_objects_are_not_kept(self):
        text = repr(authorize_voice_verification(req("voice_1"), reg(), plan("voice_1")).to_dict()) + repr(authorize_voice_verification(req("voice_1"), reg(), plan("voice_1")))
        for leaked in ("r1", "STANDARD", "request_id", "verification_mode", "display_name", "enrollment_status", "VoiceVerificationPlan", "VoiceVerificationDecision"):
            self.assertNotIn(leaked, text)


class TestBoundaries(unittest.TestCase):
    def test_33_earlier_voice_modules_do_not_reference_the_authorization_and_nothing_outside_voice_does(self):
        voice_dir = os.path.join(PY_ROOT, "voice")
        for name in sorted(os.listdir(voice_dir)):
            if name.endswith(".py") and name not in ("voice_verification_authorization.py", "voice_verification_execution.py", "voice_verification_execution_request.py"):
                with open(os.path.join(voice_dir, name), encoding="utf-8") as fh:
                    text = fh.read()
                self.assertNotIn("voice_verification_authorization", text, name)
                self.assertNotIn("VoiceVerificationAuthorization", text, name)
                self.assertNotIn("authorize_voice_verification", text, name)
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if not (folder == PY_ROOT and d in ("voice", "tests", "data")) and d != "__pycache__"]
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        text = fh.read()
                    self.assertNotIn("voice_verification_authorization", text, name)
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py", "android_entry.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("authorize_voice_verification", "voice_verification_authorization", "from voice", "import voice"):
                self.assertNotIn(token, text, (rel, token))

    def test_34_existing_contracts_are_reused_and_no_state_is_added(self):
        self.assertIs(au.resolve_voice_verification_profile, pr_mod.resolve_voice_verification_profile)
        self.assertIs(au.decide_voice_verification, dec_mod.decide_voice_verification)
        self.assertIs(au.create_voice_verification_handoff, ho_mod.create_voice_verification_handoff)
        self.assertIs(au.VoiceVerificationRequest, VoiceVerificationRequest)
        self.assertIs(au.VoiceVerificationRegistry, VoiceVerificationRegistry)
        self.assertIs(au.VoiceVerificationPlan, VoiceVerificationPlan)
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.ImportFrom))
        for name, value in vars(au).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)

    def test_35_voice_package_pristine_database_no_bytecode_and_documentation(self):
        listing = sorted(f for f in os.listdir(os.path.join(PY_ROOT, "voice")) if f != "__pycache__")
        self.assertIn("voice_verification_authorization.py", listing)
        self.assertEqual(len(listing), 28)
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("authorize_voice_verification", "VoiceVerificationAuthorization", "resolve_voice_verification_profile", "decide_voice_verification",
                       "create_voice_verification_handoff", "VOICE_VERIFICATION_AUTHORIZATION_", "INVALID_INPUT", "REJECTED", "in that order", "does NOT",
                       "never calls the verification executor", "biometrics", "embeddings", "retains none", "Prompt 812"):
            self.assertIn(marker, text, marker)


if __name__ == "__main__":
    unittest.main()
