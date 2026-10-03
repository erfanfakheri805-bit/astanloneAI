"""Prompt 810 - Section 10 voice verification handoff (`voice.voice_verification_handoff`)."""
import ast
import copy
import gc
import hashlib
import os
import pickle
import unittest
from unittest import mock

from voice import voice_verification_batch as batch_mod
from voice import voice_verification_decision as dec_mod
from voice import voice_verification_dispatcher as dispatcher_mod
from voice import voice_verification_executor as executor_mod
from voice import voice_verification_handoff as ho
from voice import voice_verification_pipeline as pipeline_mod
from voice import voice_verification_plan as plan_mod
from voice.voice_identity_profile import create_voice_identity_profile
from voice.voice_verification_decision import VoiceVerificationDecision, decide_voice_verification
from voice.voice_verification_handoff import VoiceVerificationHandoff, create_voice_verification_handoff
from voice.voice_verification_plan import VoiceVerificationPlan, create_voice_verification_plan
from voice.voice_verification_profile_resolver import resolve_voice_verification_profile
from voice.voice_verification_registry import VoiceVerificationRegistry, create_voice_verification_registry
from voice.voice_verification_request import create_voice_verification_request
from voice.voice_verification_request_validator import validate_voice_verification_request

PY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(PY_ROOT))))
DOC = os.path.join(REPO_ROOT, "docs", "section10_voice_verification_handoff_prompt810.md")
MODULE = os.path.join(PY_ROOT, "voice", "voice_verification_handoff.py")
PROJECT_DB = os.path.join(PY_ROOT, "data", "memory.db")
PRISTINE_SHA256 = "0d79f26aeea9203da44b389da0e5363967ccab6cbc2efd30e6727b11836957bb"
P = "VOICE_VERIFICATION_HANDOFF_"
INVALID_INPUT, REJECTED_DECISION, PROFILE_MISMATCH = P + "INVALID_INPUT", P + "REJECTED_DECISION", P + "PROFILE_MISMATCH"


class Str(str):
    pass


def make_plan(profile_id="voice_1"):
    req = create_voice_verification_request({"request_id": "r1", "profile_id": profile_id, "verification_mode": "STANDARD"}).request
    result = create_voice_verification_plan(validate_voice_verification_request(req))
    assert result.ok, result.failures
    return result.plan


def make_decision(profile_id="voice_1", registered=("voice_1", "voice_2")):
    profiles = tuple(create_voice_identity_profile({"profile_id": i, "display_name": "N " + i, "enabled": True, "enrollment_status": "not_enrolled"}).profile
                     for i in registered)
    reg = create_voice_verification_registry(profiles).registry
    req = create_voice_verification_request({"request_id": "r1", "profile_id": profile_id, "verification_mode": "STANDARD"}).request
    return decide_voice_verification(resolve_voice_verification_profile(req, reg))


def raw_decision(approved, profile_id, codes=(), code="X"):
    """A decision with arbitrary internals (only possible inside tests, via the decision module's private token)."""
    return VoiceVerificationDecision(dec_mod._CREATE_TOKEN, approved, profile_id, codes, code)


def raw_plan(profile_id):
    return VoiceVerificationPlan(plan_mod._CREATE_TOKEN, "r", profile_id, "m")


class NoExecution:
    """Replaces every execution entry point and the registry lookup with a tripwire; `calls` must stay empty."""

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
                         mock.patch.object(VoiceVerificationRegistry, "lookup", trip("registry"))]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


class TestApproved(unittest.TestCase):
    def test_1_approved_decision_with_matching_plan_is_approved(self):
        out = create_voice_verification_handoff(make_decision("voice_2"), make_plan("voice_2"))
        self.assertIs(type(out), VoiceVerificationHandoff)
        self.assertIs(out.approved, True)
        self.assertEqual((out.profile_id, out.failure_codes), ("voice_2", ()))
        self.assertEqual(out.to_dict(), {"approved": True, "profile_id": "voice_2", "failure_codes": []})

    def test_2_profile_id_is_preserved_exactly(self):
        for pid in ("a", "A", " a ", "voice id\n", "\u00e9", "0", "x" * 500):
            d = make_decision(pid, registered=(pid,))
            out = create_voice_verification_handoff(d, make_plan(pid))
            self.assertTrue(out.approved)
            self.assertIs(out.profile_id, d.profile_id)
            self.assertEqual(out.profile_id, pid)

    def test_3_comparison_is_exact_without_normalization(self):
        for a, b in (("voice_1", "VOICE_1"), ("voice_1", "voice_1 "), ("voice_1", " voice_1"), ("a", "\u0061\u0301")):
            out = create_voice_verification_handoff(raw_decision(True, a), raw_plan(b))
            self.assertEqual(out.failure_codes, (PROFILE_MISMATCH,), (a, b))

    def test_4_plan_other_fields_do_not_matter(self):
        p1 = VoiceVerificationPlan(plan_mod._CREATE_TOKEN, "one", "voice_1", "A")
        p2 = VoiceVerificationPlan(plan_mod._CREATE_TOKEN, "two", "voice_1", "B")
        d = raw_decision(True, "voice_1")
        self.assertEqual(create_voice_verification_handoff(d, p1), create_voice_verification_handoff(d, p2))


class TestRejectedDecision(unittest.TestCase):
    def test_5_rejected_decision_gives_a_rejected_handoff(self):
        for d in (make_decision("nobody"), decide_voice_verification(None)):
            out = create_voice_verification_handoff(d, make_plan("voice_1"))
            self.assertIs(out.approved, False)
            self.assertIsNone(out.profile_id)
            self.assertEqual(out.failure_codes, (REJECTED_DECISION,))
            self.assertEqual(out.to_dict(), {"approved": False, "profile_id": None, "failure_codes": [REJECTED_DECISION]})

    def test_6_rejected_decision_never_yields_an_approved_handoff_even_with_matching_plan(self):
        d = raw_decision(False, "voice_1")
        out = create_voice_verification_handoff(d, make_plan("voice_1"))
        self.assertFalse(out.approved)
        self.assertIsNone(out.profile_id)
        self.assertEqual(out.failure_codes, (REJECTED_DECISION,))

    def test_7_plan_is_not_read_for_a_rejected_decision(self):
        touched = []
        real = make_plan("voice_1")
        with mock.patch.object(VoiceVerificationPlan, "profile_id", property(lambda self: touched.append("profile_id") or "voice_1")):
            out = create_voice_verification_handoff(make_decision("nobody"), real)
        self.assertEqual(out.failure_codes, (REJECTED_DECISION,))
        self.assertEqual(touched, [])


class TestProfileMismatch(unittest.TestCase):
    def test_8_profile_mismatch_is_rejected(self):
        out = create_voice_verification_handoff(make_decision("voice_1"), make_plan("voice_2"))
        self.assertIs(out.approved, False)
        self.assertIsNone(out.profile_id)
        self.assertEqual(out.failure_codes, (PROFILE_MISMATCH,))
        self.assertEqual(out.to_dict(), {"approved": False, "profile_id": None, "failure_codes": [PROFILE_MISMATCH]})


class TestInvalidInputs(unittest.TestCase):
    def assertInvalid(self, out):
        self.assertIs(type(out), VoiceVerificationHandoff)
        self.assertEqual((out.approved, out.profile_id, out.failure_codes), (False, None, (INVALID_INPUT,)))

    def test_9_wrong_types_are_invalid(self):
        d, p = make_decision(), make_plan()
        for bad in (None, {}, "voice_1", 1, True, [], (), object(), d.to_dict(), p.to_dict()):
            self.assertInvalid(create_voice_verification_handoff(bad, p))
            self.assertInvalid(create_voice_verification_handoff(d, bad))
        self.assertInvalid(create_voice_verification_handoff(None, None))
        self.assertInvalid(create_voice_verification_handoff(p, d))   # swapped

    def test_10_exact_objects_with_malformed_data_are_invalid(self):
        p = make_plan("voice_1")
        for approved in (None, 1, 0, "yes", "", object()):
            self.assertInvalid(create_voice_verification_handoff(raw_decision(approved, "voice_1"), p))
        for pid in (None, "", 5, Str("voice_1")):
            self.assertInvalid(create_voice_verification_handoff(raw_decision(True, pid), p))
            self.assertInvalid(create_voice_verification_handoff(raw_decision(True, "voice_1"), raw_plan(pid)))

    def test_11_unreadable_public_properties_are_invalid_not_exceptions(self):
        def boom(self):
            raise RuntimeError("boom")
        with mock.patch.object(VoiceVerificationDecision, "profile_id", property(boom)):
            self.assertInvalid(create_voice_verification_handoff(make_decision("voice_1"), make_plan("voice_1")))
        with mock.patch.object(VoiceVerificationPlan, "profile_id", property(boom)):
            self.assertInvalid(create_voice_verification_handoff(make_decision("voice_1"), make_plan("voice_1")))
        with mock.patch.object(VoiceVerificationDecision, "approved", property(boom)):
            self.assertInvalid(create_voice_verification_handoff(make_decision("voice_1"), make_plan("voice_1")))

    def test_12_invalid_input_wins_over_the_rest_by_type_before_any_read(self):
        touched = []

        class Spoof:
            __class__ = VoiceVerificationDecision
            approved = False

            def __getattribute__(self, name):
                touched.append(name)
                return object.__getattribute__(self, name)
        self.assertInvalid(create_voice_verification_handoff(Spoof(), make_plan()))
        self.assertEqual([t for t in touched if t in ("approved", "profile_id")], [])


class TestSpoofedAndLookAlikes(unittest.TestCase):
    def assertInvalid(self, out):
        self.assertEqual((out.approved, out.profile_id, out.failure_codes), (False, None, (INVALID_INPUT,)))

    def test_13_spoofed_class_decision_and_plan_are_rejected(self):
        class SpoofDecision:
            __class__ = VoiceVerificationDecision
            approved, profile_id, failure_codes, code = True, "voice_1", (), "VOICE_VERIFICATION_DECISION_APPROVED"

        class SpoofPlan:
            __class__ = VoiceVerificationPlan
            request_id, profile_id, verification_mode = "r", "voice_1", "m"
        self.assertInvalid(create_voice_verification_handoff(SpoofDecision(), make_plan("voice_1")))
        self.assertInvalid(create_voice_verification_handoff(make_decision("voice_1"), SpoofPlan()))
        self.assertInvalid(create_voice_verification_handoff(SpoofDecision(), SpoofPlan()))

    def test_14_look_alikes_with_the_same_public_surface_are_rejected(self):
        real_d, real_p = make_decision("voice_1"), make_plan("voice_1")

        class LookDecision:
            approved, profile_id, failure_codes, code = real_d.approved, real_d.profile_id, real_d.failure_codes, real_d.code

            def to_dict(self):
                return real_d.to_dict()

        class LookPlan:
            request_id, profile_id, verification_mode = "r", "voice_1", "m"

            def to_dict(self):
                return real_p.to_dict()
        self.assertInvalid(create_voice_verification_handoff(LookDecision(), real_p))
        self.assertInvalid(create_voice_verification_handoff(real_d, LookPlan()))
        self.assertInvalid(create_voice_verification_handoff(mock.Mock(), real_p))
        self.assertInvalid(create_voice_verification_handoff(real_d, mock.MagicMock(spec=VoiceVerificationPlan)))

    def test_15_decision_plan_and_handoff_cannot_be_subclassed(self):
        for base in (VoiceVerificationDecision, VoiceVerificationPlan, VoiceVerificationHandoff):
            with self.assertRaises(TypeError):
                type("Sub", (base,), {})

    def test_16_a_plan_request_look_alike_is_not_used(self):
        class Req:
            profile_id = "voice_1"

        class PlanWithRequest:
            request = Req()
        self.assertInvalid(create_voice_verification_handoff(make_decision("voice_1"), PlanWithRequest()))


class TestNoExecution(unittest.TestCase):
    def test_17_no_executor_dispatcher_pipeline_batch_or_registry_call_in_any_branch(self):
        d_ok, d_no, p = make_decision("voice_1"), make_decision("nobody"), make_plan("voice_1")
        with NoExecution() as t:
            cases = [(d_ok, p), (d_ok, make_plan("voice_2")), (d_no, p), (None, p), (d_ok, None), (raw_decision(True, ""), p), (raw_decision(None, "x"), p)]
            for d, pl in cases:
                create_voice_verification_handoff(d, pl)
        self.assertEqual(t.calls, [])

    def test_18_module_imports_only_decision_and_plan_and_never_names_execution_apis(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        nodes = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertTrue(all(isinstance(n, ast.ImportFrom) for n in nodes))
        self.assertEqual(sorted((n.module, n.level, tuple(a.name for a in n.names)) for n in nodes),
                         [("voice_verification_decision", 1, ("VoiceVerificationDecision",)), ("voice_verification_plan", 1, ("VoiceVerificationPlan",))])
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        for word in ("execute_voice_verification_plan", "dispatch_voice_verification", "run_voice_verification_pipeline", "run_voice_verification_batch",
                     "lookup", "registry", "resolve_voice_verification_profile", "decide_voice_verification", "create_voice_verification_plan",
                     "os", "sys", "io", "pathlib", "subprocess", "socket", "urllib", "http", "requests", "numpy", "wave", "sqlite3", "random", "time", "datetime",
                     "anthropic", "openai", "core", "agent", "planning", "audio", "embedding", "embeddings", "microphone", "android", "request", "__class__", "__dict__"):
            self.assertNotIn(word, names, word)
        calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for forbidden in ("open", "eval", "exec", "compile", "__import__", "print", "input", "getattr", "setattr", "globals", "vars", "isinstance"):
            self.assertNotIn(forbidden, calls)

    def test_19_module_reads_only_public_properties_of_the_inputs(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        read = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in ("decision", "plan"):
                read.setdefault(n.value.id, set()).add(n.attr)
        self.assertEqual(read, {"decision": {"approved", "profile_id"}, "plan": {"profile_id"}})


class TestDeterminism(unittest.TestCase):
    def test_20_codes_and_status_are_deterministic_and_stable(self):
        self.assertEqual(ho.FAILURE_CODES, (INVALID_INPUT, REJECTED_DECISION, PROFILE_MISMATCH))
        self.assertEqual(len(set(ho.FAILURE_CODES)), 3)
        for d, p in ((make_decision("voice_1"), make_plan("voice_1")), (make_decision("nobody"), make_plan("voice_1")),
                     (make_decision("voice_1"), make_plan("voice_2")), (None, None)):
            a, b = create_voice_verification_handoff(d, p), create_voice_verification_handoff(d, p)
            self.assertIsNot(a, b)
            self.assertEqual((a.approved, a.profile_id, a.failure_codes), (b.approved, b.profile_id, b.failure_codes))
            self.assertLessEqual(len(a.failure_codes), 1)
            self.assertTrue(all(c in ho.FAILURE_CODES for c in a.failure_codes))
            self.assertEqual(a.approved, a.failure_codes == ())

    def test_21_inputs_are_not_changed(self):
        d, p = make_decision("voice_1"), make_plan("voice_1")
        before = (d.to_dict(), p.to_dict(), d, p)
        create_voice_verification_handoff(d, p)
        create_voice_verification_handoff(d, make_plan("voice_2"))
        self.assertEqual((d.to_dict(), p.to_dict()), before[:2])
        self.assertEqual((d, p), before[2:])


class TestEqualityAndHash(unittest.TestCase):
    def test_22_equality_and_hash_by_value(self):
        a = create_voice_verification_handoff(make_decision("voice_1"), make_plan("voice_1"))
        b = create_voice_verification_handoff(make_decision("voice_1"), make_plan("voice_1"))
        c = create_voice_verification_handoff(make_decision("voice_2"), make_plan("voice_2"))
        m = create_voice_verification_handoff(make_decision("voice_1"), make_plan("voice_2"))
        r = create_voice_verification_handoff(make_decision("nobody"), make_plan("voice_1"))
        self.assertIsNot(a, b)
        self.assertEqual(a, b)
        self.assertEqual(hash(a), hash(b))
        self.assertNotEqual(a, c)
        self.assertNotEqual(m, r)
        self.assertEqual(len({a, b, c, m, r}), 4)
        self.assertNotEqual(a, a.to_dict())
        self.assertNotEqual(a, (True, "voice_1", ()))
        self.assertEqual(repr(m), "VoiceVerificationHandoff(approved=False, profile_id=None, failure_codes=('%s',))" % PROFILE_MISMATCH)


class TestToDict(unittest.TestCase):
    def test_23_to_dict_is_fresh_every_call_and_mutation_safe(self):
        for out in (create_voice_verification_handoff(make_decision("voice_1"), make_plan("voice_1")),
                    create_voice_verification_handoff(make_decision("voice_1"), make_plan("voice_2"))):
            first = out.to_dict()
            snapshot = copy.deepcopy(first)
            first["failure_codes"].append("x")
            first["approved"] = "hacked"
            first["profile_id"] = "hacked"
            first["extra"] = 1
            self.assertEqual(out.to_dict(), snapshot)
            self.assertIsNot(out.to_dict(), out.to_dict())
            self.assertIsNot(out.to_dict()["failure_codes"], out.to_dict()["failure_codes"])
            self.assertEqual(list(out.to_dict()), ["approved", "profile_id", "failure_codes"])


class TestImmutability(unittest.TestCase):
    def test_24_attributes_cannot_be_assigned_or_deleted(self):
        for out in (create_voice_verification_handoff(make_decision(), make_plan()), create_voice_verification_handoff(None, None)):
            for name in ("approved", "profile_id", "failure_codes", "_approved", "_profile_id", "_failure_codes", "extra"):
                with self.assertRaises(AttributeError, msg=name):
                    setattr(out, name, 1)
                with self.assertRaises(AttributeError, msg=name):
                    delattr(out, name)
            self.assertFalse(hasattr(out, "__dict__"))
            self.assertIs(type(out.failure_codes), tuple)

    def test_25_direct_construction_subclassing_copy_and_pickle_are_refused(self):
        for args in ((object(), True, "a", ()), (None, True, "a", ()), ()):
            with self.assertRaises(TypeError):
                VoiceVerificationHandoff(*args)
        self.assertEqual(VoiceVerificationHandoff.__slots__, ("_approved", "_profile_id", "_failure_codes"))
        out = create_voice_verification_handoff(make_decision(), make_plan())
        self.assertIs(copy.copy(out), out)
        self.assertIs(copy.deepcopy(out), out)
        for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
            with self.assertRaises(TypeError):
                pickle.dumps(out, protocol)


class TestNonRetention(unittest.TestCase):
    def test_26_handoff_holds_only_minimal_plain_data(self):
        for d, p in ((make_decision("voice_1"), make_plan("voice_1")), (make_decision("nobody"), make_plan("voice_1")),
                     (make_decision("voice_1"), make_plan("voice_2")), (None, None)):
            out = create_voice_verification_handoff(d, p)
            self.assertIs(type(out.approved), bool)
            self.assertTrue(out.profile_id is None or type(out.profile_id) is str)
            self.assertTrue(all(type(c) is str for c in out.failure_codes))

    def test_27_source_decision_and_plan_are_not_reachable_from_the_handoff(self):
        for d, p in ((make_decision("voice_1"), make_plan("voice_1")), (make_decision("nobody"), make_plan("voice_1")), (make_decision("voice_1"), make_plan("voice_2"))):
            out = create_voice_verification_handoff(d, p)
            seen, stack = set(), [out]
            while stack:
                node = stack.pop()
                if id(node) in seen:
                    continue
                seen.add(id(node))
                if not isinstance(node, (type, type(None))):
                    stack.extend(gc.get_referents(node))
            self.assertNotIn(id(d), seen)
            self.assertNotIn(id(p), seen)
            self.assertFalse([n for n in (d, p) if any(r is n for r in gc.get_referents(out))])

    def test_28_plan_request_id_and_mode_are_not_kept(self):
        out = create_voice_verification_handoff(make_decision("voice_1"), make_plan("voice_1"))
        text = repr(out.to_dict()) + repr(out)
        for leaked in ("r1", "STANDARD", "request_id", "verification_mode", "VoiceVerificationPlan", "VoiceVerificationDecision"):
            self.assertNotIn(leaked, text)


class TestBoundaries(unittest.TestCase):
    def test_29_earlier_voice_modules_do_not_reference_the_handoff_and_nothing_outside_voice_does(self):
        voice_dir = os.path.join(PY_ROOT, "voice")
        for name in sorted(os.listdir(voice_dir)):
            if name.endswith(".py") and name not in ("voice_verification_handoff.py", "voice_verification_authorization.py"):
                with open(os.path.join(voice_dir, name), encoding="utf-8") as fh:
                    text = fh.read()
                self.assertNotIn("voice_verification_handoff", text, name)
                self.assertNotIn("VoiceVerificationHandoff", text, name)
        for folder, dirs, files in os.walk(PY_ROOT):
            dirs[:] = [d for d in dirs if not (folder == PY_ROOT and d in ("voice", "tests", "data")) and d != "__pycache__"]
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(folder, name), encoding="utf-8") as fh:
                        text = fh.read()
                    self.assertNotIn("voice_verification_handoff", text, name)
        for rel in ("core/core.py", "input_system/input_system.py", "agent/agent_loop.py", "planning/planner.py", "android_entry.py"):
            with open(os.path.join(PY_ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            for token in ("create_voice_verification_handoff", "voice_verification_handoff", "from voice", "import voice"):
                self.assertNotIn(token, text, (rel, token))

    def test_30_module_defines_one_class_and_no_mutable_state(self):
        with open(MODULE, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        self.assertEqual(sorted(n.name for n in tree.body if isinstance(n, ast.ClassDef)), ["VoiceVerificationHandoff"])
        for node in tree.body:
            self.assertIsInstance(node, (ast.Expr, ast.Assign, ast.FunctionDef, ast.ClassDef, ast.ImportFrom))
        for name, value in vars(ho).items():
            if not name.startswith("__"):
                self.assertNotIsInstance(value, (list, dict, set), name)
        self.assertIs(ho.VoiceVerificationDecision, VoiceVerificationDecision)
        self.assertIs(ho.VoiceVerificationPlan, VoiceVerificationPlan)

    def test_31_voice_package_pristine_database_no_bytecode_and_documentation(self):
        listing = sorted(f for f in os.listdir(os.path.join(PY_ROOT, "voice")) if f != "__pycache__")
        self.assertIn("voice_verification_handoff.py", listing)
        self.assertEqual(len(listing), 28)
        with open(PROJECT_DB, "rb") as fh:
            self.assertEqual(hashlib.sha256(fh.read()).hexdigest(), PRISTINE_SHA256)
        for folder, _dirs, files in os.walk(REPO_ROOT):
            self.assertNotEqual(os.path.basename(folder), "__pycache__", folder)
            self.assertFalse([f for f in files if f.endswith(".pyc")], folder)
        with open(DOC, encoding="utf-8") as fh:
            text = fh.read()
        for marker in ("create_voice_verification_handoff", "VoiceVerificationHandoff", "VoiceVerificationDecision", "VoiceVerificationPlan", "plan.profile_id",
                       "VOICE_VERIFICATION_HANDOFF_", "INVALID_INPUT", "REJECTED_DECISION", "PROFILE_MISMATCH", "does NOT", "never calls the executor",
                       "biometrics", "embeddings", "retains neither", "Prompt 811"):
            self.assertIn(marker, text, marker)


if __name__ == "__main__":
    unittest.main()
