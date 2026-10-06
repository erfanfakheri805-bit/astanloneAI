"""
Tests for Prompt 938 - Final Runtime and Claude-Exit Gap Assessment.

`build_final_runtime_assessment(boundary_validation, runtime_readiness,
controlled_reasoning_snapshot=None)` is a pure, descriptive assessment. It keeps
architecture, runtime integration, runtime usability, APK readiness and Claude
independence apart and never claims more than the evidence supports. RuntimeCore
stores the latest result per turn as an observation only.

Run directly:
    python -m unittest tests.test_final_runtime_assessment_prompt938 -v
"""

import ast
import copy
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.core import Core
from runtime_integration import bridge as ri
from runtime_integration import final_runtime_assessment as fra
from runtime_integration.runtime_core import RuntimeCore

assess = fra.build_final_runtime_assessment
AREAS = ri.BOUNDARY_AREAS
KEYS = ["version", "available", "status", "runtime_state", "apk_state", "claude_exit_state",
        "blocking_areas", "deferred_areas", "structurally_integrated", "runtime_usable",
        "apk_ready", "claude_independent", "actionable", "executed", "descriptive_only"]
MODULE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "runtime_integration", "final_runtime_assessment.py")


def ev(exists=True, connected=True, activated=False, capable=False):
    return {"exists": exists, "connected_to_runtime_core": connected,
            "activated_in_runtime_path": activated, "execution_capable": capable}


def structural_evidence():
    return {name: ev() for name in AREAS}


def boundary(**overrides):
    evidence = structural_evidence()
    evidence.update(overrides)
    return ri.final_runtime_integration_boundary_validation(evidence)


def snapshot():
    snap = {"available": True, "status": "controlled_ready", "actionable": False,
            "executed": False, "descriptive_only": True}
    for name in ("handoff", "consumption", "decision_candidate", "validation", "eligibility",
                 "checkpoint"):
        snap[name] = {"payload": {"n": [1]}}
    return snap


def ready():
    return ri.controlled_reasoning_runtime_ready(snapshot())


def usable_evidence():
    """The most the evidence can honestly say today: memory/AEL/local model live
    and executable, Android server running, reasoning active."""
    return {
        "controlled_reasoning_integration": ev(activated=True),
        "local_model_runtime": ev(activated=True, capable=True),
        "memory_runtime": ev(activated=True, capable=True),
        "AEL_learning_runtime": ev(activated=True, capable=True),
        "capability_runtime": ev(activated=True),
        "upgrade_runtime": ev(),
        "android_runtime_bridge": ev(activated=True, capable=True),
    }


class TestShapeAndFlags(unittest.TestCase):
    def test_exact_top_level_keys_and_constant_flags(self):
        for result in (assess(boundary(), ready(), snapshot()), assess(None, None),
                       assess("x", 1, 2), assess(boundary(), {})):
            self.assertEqual(list(result), KEYS)
            self.assertIs(result["actionable"], False)
            self.assertIs(result["executed"], False)
            self.assertIs(result["descriptive_only"], True)
            self.assertEqual(result["version"], 1)
            json.dumps(result)

    def test_fully_structurally_integrated_but_runtime_incomplete(self):
        result = assess(boundary(), ready(), snapshot())
        self.assertIs(result["available"], True)
        self.assertEqual(result["status"], "assessed")
        self.assertEqual(result["runtime_state"], "integrated")
        self.assertIs(result["structurally_integrated"], True)
        self.assertIs(result["runtime_usable"], False)
        self.assertIs(result["apk_ready"], False)
        self.assertIs(result["claude_independent"], False)

    def test_four_concepts_are_never_collapsed(self):
        result = assess(boundary(**usable_evidence()), ready(), snapshot())
        self.assertIs(result["structurally_integrated"], True)
        self.assertIs(result["runtime_usable"], False)   # capability has no executor
        self.assertIs(result["apk_ready"], False)
        self.assertIs(result["claude_independent"], False)


class TestRuntimeUsability(unittest.TestCase):
    def test_runtime_partially_usable(self):
        result = assess(boundary(**usable_evidence()), ready())
        parts = result["apk_state"]["requirements"]
        self.assertTrue(parts["memory_runtime"] and parts["AEL_learning_runtime"]
                        and parts["local_ai_runtime"] and parts["reasoning_runtime"])
        self.assertFalse(parts["capability_runtime"])
        self.assertIs(result["runtime_usable"], False)
        self.assertIs(parts["usable_runtime_path"], False)

    def test_missing_local_model(self):
        result = assess(boundary(), ready())
        self.assertIn("local_model_runtime", result["blocking_areas"])
        self.assertFalse(result["apk_state"]["requirements"]["local_ai_runtime"])
        ok = assess(boundary(local_model_runtime=ev(activated=True, capable=True)), ready())
        self.assertNotIn("local_model_runtime", ok["blocking_areas"])

    def test_missing_capability_executor(self):
        result = assess(boundary(), ready())
        self.assertIn("capability_runtime", result["blocking_areas"])
        # a claim that the capability registry executes is contradictory, never trusted
        claimed = assess(boundary(capability_runtime=ev(activated=True, capable=True)), ready())
        self.assertIs(claimed["runtime_usable"], False)
        self.assertIs(claimed["structurally_integrated"], False)
        self.assertIn("capability_runtime", claimed["blocking_areas"])

    def test_missing_upgrade_runtime(self):
        result = assess(boundary(), ready())
        self.assertIn("upgrade_runtime", result["blocking_areas"])
        self.assertIn("upgrade_runtime", result["claude_exit_state"]["missing"])
        absent = assess(boundary(upgrade_runtime=ev(False, False)), ready())
        self.assertIn("upgrade_runtime", absent["blocking_areas"])
        self.assertEqual(absent["runtime_state"], "partially_integrated")

    def test_missing_android_device_validation(self):
        result = assess(boundary(**usable_evidence()), ready())
        self.assertIn("android_device_validation", result["blocking_areas"])
        self.assertIn("android_device_validation", result["apk_state"]["missing"])
        self.assertIs(result["apk_state"]["requirements"]["android_device_validation"], False)
        self.assertEqual(result["apk_state"]["status"], "not_ready")
        self.assertIs(result["apk_ready"], False)

    def test_apk_requirements_cover_every_required_distinction(self):
        reqs = assess(boundary(), ready())["apk_state"]["requirements"]
        for name in ("android_integration", "usable_runtime_path", "memory_runtime",
                     "AEL_learning_runtime", "local_ai_runtime", "capability_runtime",
                     "reasoning_runtime", "android_device_validation",
                     "production_release_evidence"):
            self.assertIn(name, reqs)

    def test_architecture_alone_never_makes_apk_ready(self):
        result = assess(boundary(), ready(), snapshot())
        self.assertIs(result["apk_ready"], False)
        self.assertEqual(result["apk_state"]["status"], "not_ready")
        self.assertTrue(result["apk_state"]["missing"])

    def test_reasoning_not_ready_downgrades_runtime_state(self):
        not_ready = ri.controlled_reasoning_runtime_ready(None)
        result = assess(boundary(), not_ready)
        self.assertEqual(result["runtime_state"], "partially_integrated")
        self.assertIs(result["structurally_integrated"], False)

    def test_not_integrated_when_nothing_exists(self):
        result = assess(boundary(**{n: ev(False, False) for n in AREAS}), ready())
        self.assertEqual(result["runtime_state"], "not_integrated")
        self.assertEqual(result["blocking_areas"][:7], list(AREAS))


class TestClaudeExit(unittest.TestCase):
    def test_claude_independence_false_when_growth_path_not_executable(self):
        for b in (boundary(), boundary(**usable_evidence())):
            result = assess(b, ready(), snapshot())
            self.assertIs(result["claude_independent"], False)
            self.assertEqual(result["claude_exit_state"]["status"], "not_independent")
            self.assertIn("runtime_growth_path", result["blocking_areas"])
            self.assertIn("runtime_growth_path", result["claude_exit_state"]["missing"])
            self.assertIs(result["claude_exit_state"]["requirements"]["runtime_growth_path"],
                          False)

    def test_autonomy_structures_or_any_input_cannot_make_claude_independent(self):
        rich = boundary(**usable_evidence())
        for extra in (None, snapshot(), {"autonomy": True}):
            self.assertIs(assess(rich, ready(), extra)["claude_independent"], False)
        for variant in (dict(rich, claude_independent=True), dict(rich, autonomy_ready=True)):
            result = assess(variant, ready())
            self.assertIs(result["claude_independent"], False)
            self.assertEqual(result["runtime_state"], "not_verified")

    def test_strictness_ordering(self):
        for b in (boundary(), boundary(**usable_evidence()), None):
            result = assess(b, ready())
            if result["claude_independent"]:
                self.assertTrue(result["apk_ready"])
            if result["apk_ready"]:
                self.assertTrue(result["runtime_usable"])
            if result["runtime_usable"]:
                self.assertTrue(result["structurally_integrated"])


class TestDeferredAreas(unittest.TestCase):
    def test_deferred_features_listed_and_never_blockers(self):
        result = assess(boundary(), ready())
        self.assertEqual(result["deferred_areas"], list(fra.DEFERRED_AREAS))
        for name in ("advanced_multimodal_generation", "image_video_generation",
                     "advanced_voice_transformation", "broad_device_automation",
                     "advanced_web_research", "full_jarvis_level_autonomy"):
            self.assertIn(name, result["deferred_areas"])
        for variant in (assess(boundary(), ready()), assess(None, None),
                        assess(boundary(**usable_evidence()), ready())):
            self.assertFalse(set(variant["blocking_areas"]) & set(variant["deferred_areas"]))

    def test_blocking_areas_are_only_concrete_current_blockers(self):
        result = assess(boundary(**usable_evidence()), ready())
        self.assertEqual(result["blocking_areas"],
                         ["capability_runtime", "upgrade_runtime", "android_device_validation",
                          "runtime_growth_path"])


class TestMalformedAndMissingInput(unittest.TestCase):
    def assert_not_verified(self, result):
        self.assertIs(result["available"], False)
        self.assertEqual(result["status"], "not_verified")
        self.assertEqual(result["runtime_state"], "not_verified")
        for key in ("structurally_integrated", "runtime_usable", "apk_ready",
                    "claude_independent"):
            self.assertIs(result[key], False, key)
        self.assertEqual(result["apk_state"]["status"], "not_ready")
        self.assertEqual(result["claude_exit_state"]["status"], "not_independent")
        self.assertEqual(result["blocking_areas"], ["android_device_validation",
                                                    "runtime_growth_path"])

    def test_missing_input(self):
        self.assert_not_verified(assess(None, None))
        self.assert_not_verified(assess(boundary(), None))
        self.assert_not_verified(assess(None, ready()))
        self.assert_not_verified(assess(boundary(), ready(), "snapshot"))

    def test_malformed_input(self):
        good_b, good_r = boundary(), ready()
        for bad in ("x", 1, 1.5, True, [], (), {}, object(), [good_b]):
            self.assert_not_verified(assess(bad, good_r))
            self.assert_not_verified(assess(good_b, bad))
        for bad in ("x", 1, [], {"available": True}, object()):
            self.assert_not_verified(assess(good_b, good_r, bad))

    def test_safe_state_boundary_is_not_verified(self):
        self.assert_not_verified(assess(ri.final_runtime_integration_boundary_validation(None),
                                        ready()))

    def test_tampered_boundary_is_never_trusted(self):
        b = boundary()
        for mutate in (lambda d: d.update(status="not_integrated"),
                       lambda d: d.update(runtime_connected=False),
                       lambda d: d["areas"]["memory_runtime"].update(execution_capable=True),
                       lambda d: d["areas"]["local_model_runtime"].update(status="bogus"),
                       lambda d: d["areas"].pop("memory_runtime"),
                       lambda d: d.update(executed=True),
                       lambda d: d.update(activated_areas=list(AREAS))):
            tampered = copy.deepcopy(b)
            mutate(tampered)
            self.assert_not_verified(assess(tampered, ready()))

    def test_readiness_with_unsafe_flags_is_malformed(self):
        for key, value in (("actionable", True), ("executed", True), ("descriptive_only", False),
                           ("status", "other"), ("ready", "yes"), ("available", None)):
            r = ready()
            r[key] = value
            self.assert_not_verified(assess(boundary(), r))

    def test_readiness_inconsistent_with_snapshot(self):
        other = snapshot()
        other.update(available=False, status="not_ready")
        self.assert_not_verified(assess(boundary(), ready(), other))

    def test_input_that_raises_when_read(self):
        class Boom(dict):
            def get(self, *a, **k):
                raise RuntimeError("boom")

            def __getitem__(self, k):
                raise RuntimeError("boom")

        self.assert_not_verified(assess(Boom(boundary()), ready()))
        self.assert_not_verified(assess(boundary(), Boom(ready())))


class TestPurity(unittest.TestCase):
    def test_deterministic_repeated_calls(self):
        args = (boundary(**usable_evidence()), ready(), snapshot())
        first = assess(*args)
        for _ in range(3):
            self.assertEqual(assess(*args), first)
        self.assertEqual(json.dumps(assess(*args)), json.dumps(first))
        self.assertEqual(assess(*copy.deepcopy(args)), first)

    def test_no_input_mutation(self):
        for args in ((boundary(), ready(), snapshot()), (boundary(**usable_evidence()), ready(), None),
                     (None, "x", []), ({"a": 1}, {"b": 2}, {"c": 3})):
            before = copy.deepcopy(args)
            assess(*args)
            self.assertEqual(args, before)

    def test_returned_values_are_independent_copies(self):
        args = (boundary(), ready(), snapshot())
        first = assess(*args)
        first["blocking_areas"].append("x")
        first["deferred_areas"].clear()
        first["apk_state"]["requirements"]["memory_runtime"] = "tampered"
        first["apk_state"]["missing"].clear()
        first["claude_exit_state"]["requirements"]["runtime_usable"] = "tampered"
        first["runtime_state"] = "changed"
        second = assess(*args)
        self.assertEqual(second, assess(*args))
        self.assertEqual(second["deferred_areas"], list(fra.DEFERRED_AREAS))
        self.assertNotIn("x", second["blocking_areas"])
        self.assertIsNot(second["blocking_areas"], assess(*args)["blocking_areas"])
        self.assertIsNot(second["apk_state"], assess(*args)["apk_state"])
        self.assertIsNot(second["apk_state"]["missing"], assess(*args)["apk_state"]["missing"])
        # the constant deferred tuple is never exposed
        self.assertIsInstance(fra.DEFERRED_AREAS, tuple)

    def test_module_source_has_no_io_execution_network_or_extra_imports(self):
        with open(MODULE_PATH, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(imported, {"os", "sys", "runtime_integration"})
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"open", "exec", "eval", "compile", "__import__",
                                                "input", "print", "setattr", "delattr"})


class RuntimeCoreCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def new_core(self, cls=RuntimeCore, name="core"):
        base = os.path.join(self._tmp.name, name)
        os.makedirs(base, exist_ok=True)
        return cls(memory_db_path=os.path.join(base, "m.sqlite3"),
                   skill_definitions_dir=os.path.join(base, "skills"))


class TestRuntimeCoreObservation(RuntimeCoreCase):
    def test_none_before_first_turn_then_stored(self):
        core = self.new_core()
        self.assertIsNone(core.get_last_final_runtime_assessment())
        self.assertIsNone(core._last_final_runtime_assessment)
        core.process_input("من عرفان هستم")
        result = core.get_last_final_runtime_assessment()
        self.assertEqual(list(result), KEYS)
        self.assertEqual(result["runtime_state"], "integrated")
        self.assertIs(result["structurally_integrated"], True)
        for key in ("runtime_usable", "apk_ready", "claude_independent", "actionable",
                    "executed"):
            self.assertIs(result[key], False, key)
        self.assertIs(result["descriptive_only"], True)
        json.dumps(result)

    def test_exposed_under_final_runtime_assessment_key(self):
        core = self.new_core()
        self.assertEqual(core.get_last_runtime_observation(), {"final_runtime_assessment": None})
        core.process_input("من عرفان هستم")
        observation = core.get_last_runtime_observation()
        self.assertEqual(list(observation), ["final_runtime_assessment"])
        self.assertEqual(observation["final_runtime_assessment"],
                         core.get_last_final_runtime_assessment())
        # last_runtime_result keeps its pinned key set
        self.assertNotIn("final_runtime_assessment", core.last_runtime_result)

    def test_previous_assessment_is_cleared_at_the_start_of_every_turn(self):
        core = self.new_core()
        core.process_input("من عرفان هستم")
        self.assertIsNotNone(core.get_last_final_runtime_assessment())
        seen = []
        real = Core.process_input

        def spy(self_, text):
            seen.append(self_._last_final_runtime_assessment)
            return real(self_, text)

        with mock.patch.object(Core, "process_input", spy):
            core.process_input("hello")
        self.assertEqual(seen, [None])
        with mock.patch.object(Core, "process_input", side_effect=RuntimeError("core failed")):
            with self.assertRaises(RuntimeError):
                core.process_input("hello")
        self.assertIsNone(core.get_last_final_runtime_assessment())

    def test_accessor_returns_independent_copies(self):
        core = self.new_core()
        core.process_input("من عرفان هستم")
        first = core.get_last_final_runtime_assessment()
        expected = copy.deepcopy(first)
        first["blocking_areas"].append("x")
        first["apk_state"]["requirements"]["memory_runtime"] = "tampered"
        first["claude_independent"] = True
        second = core.get_last_final_runtime_assessment()
        self.assertEqual(second, expected)
        self.assertIsNot(second, first)
        self.assertIsNot(second["apk_state"], core.get_last_final_runtime_assessment()["apk_state"])
        core.get_last_runtime_observation()["final_runtime_assessment"]["apk_ready"] = True
        self.assertEqual(core.get_last_final_runtime_assessment(), expected)

    def test_failure_leaves_the_field_none_without_touching_the_reply(self):
        core = self.new_core()
        plain = self.new_core(Core, "plain")
        with mock.patch("runtime_integration.runtime_core.build_final_runtime_assessment",
                        side_effect=RuntimeError("boom")):
            reply = core.process_input("hello")
        self.assertEqual(reply, plain.process_input("hello"))
        self.assertIsNone(core.get_last_final_runtime_assessment())
        with mock.patch("runtime_integration.runtime_core.build_final_runtime_assessment",
                        return_value={"actionable": True, "executed": True}):
            core.process_input("hello")
        self.assertIsNone(core.get_last_final_runtime_assessment())

    def test_non_conversation_turn_without_reasoning_is_not_verified(self):
        core = self.new_core()
        core.process_input("TEACH sun IS a star")
        result = core.get_last_final_runtime_assessment()
        self.assertEqual(result["runtime_state"], "not_verified")
        self.assertIs(result["available"], False)


class TestObservationOnly(RuntimeCoreCase):
    def test_normal_reply_behavior_unchanged(self):
        inputs = ("hello", "من عرفان هستم", "What is Python?", "", "TEACH sun IS a star",
                  "ASK sun", "create a plan to learn python", "UPGRADE demo IS a demo")
        plain, runtime = self.new_core(Core, "plain"), self.new_core(RuntimeCore, "rt")
        for text in inputs:
            self.assertEqual(runtime.process_input(text), plain.process_input(text), text)

    def test_assessment_never_feeds_back_into_results(self):
        a, b = self.new_core(name="a"), self.new_core(name="b")
        with mock.patch("runtime_integration.runtime_core.build_final_runtime_assessment",
                        side_effect=RuntimeError("boom")):
            a.process_input("من عرفان هستم")
        b.process_input("من عرفان هستم")
        self.assertEqual(a.last_runtime_result, b.last_runtime_result)
        for getter in ("get_last_final_runtime_integration_checkpoint",
                       "get_last_final_runtime_integration_boundary_validation",
                       "get_last_controlled_reasoning_runtime_ready",
                       "get_last_controlled_reasoning_snapshot"):
            self.assertEqual(getattr(a, getter)(), getattr(b, getter)(), getter)

    def test_producing_the_assessment_executes_nothing(self):
        core = self.new_core()
        core.process_input("من عرفان هستم")
        boom = AssertionError("assessment must not run this")
        before = (len(core.upgrades.history(100)), core.capabilities.all(),
                  len(core.context.get_recent_turns()))
        with mock.patch.object(core.ael, "run", side_effect=boom) as ael_run, \
                mock.patch.object(core.upgrades, "propose_upgrade", side_effect=boom) as up, \
                mock.patch.object(core.learning, "teach", side_effect=boom) as teach, \
                mock.patch.object(core.learning, "relate", side_effect=boom) as relate, \
                mock.patch.object(core.capabilities, "set_enabled", side_effect=boom) as enable:
            for _ in range(3):
                core._store_final_runtime_assessment()
            core.get_last_runtime_observation()
        for spy in (ael_run, up, teach, relate, enable):
            spy.assert_not_called()
        after = (len(core.upgrades.history(100)), core.capabilities.all(),
                 len(core.context.get_recent_turns()))
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
