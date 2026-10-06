"""
Tests for Prompt 937 - Final Runtime Integration Boundary Validation.

`final_runtime_integration_boundary_validation(evidence)` is a pure, descriptive
classification of the existing runtime integration. It keeps four things apart per
area: the architecture exists, it is connected to RuntimeCore, it is activated in the
real runtime path, and it is capable of real execution. RuntimeCore stores the latest
result per turn as an observation field only.

Run directly:
    python -m unittest tests.test_final_runtime_integration_boundary_validation_prompt937 -v
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
from runtime_integration.runtime_core import RuntimeCore
from tests.test_pre_inference_readiness_guard import GuardCase, MESSAGE, MODEL_TEXT
from tests.test_local_inference_response_generation import TextRuntime

AREAS = ("controlled_reasoning_integration", "local_model_runtime", "memory_runtime",
         "AEL_learning_runtime", "capability_runtime", "upgrade_runtime",
         "android_runtime_bridge")
TOP_KEYS = ["available", "status", "structurally_integrated", "runtime_connected",
            "execution_capable", "descriptive_only", "actionable", "executed",
            "structurally_integrated_areas", "activated_areas", "execution_capable_areas",
            "areas"]
AREA_KEYS = ["status", "reason", "exists", "connected_to_runtime_core",
             "activated_in_runtime_path", "execution_capable", "descriptive_only"]
validate = ri.final_runtime_integration_boundary_validation
PYTHON_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE_PATH = os.path.join(PYTHON_ROOT, "runtime_integration", "bridge.py")


def ev(exists=True, connected=True, activated=False, capable=False):
    return {"exists": exists, "connected_to_runtime_core": connected,
            "activated_in_runtime_path": activated, "execution_capable": capable}


def structural():
    """Every area exists and is connected; nothing activated or executable."""
    return {name: ev() for name in AREAS}


def safe_state():
    area = {"status": "not_integrated", "reason": "missing_evidence", "exists": False,
            "connected_to_runtime_core": False, "activated_in_runtime_path": False,
            "execution_capable": False, "descriptive_only": True}
    return {"available": False, "status": "not_integrated", "structurally_integrated": False,
            "runtime_connected": False, "execution_capable": False, "descriptive_only": True,
            "actionable": False, "executed": False, "structurally_integrated_areas": [],
            "activated_areas": [], "execution_capable_areas": [],
            "areas": {name: dict(area) for name in AREAS}}


class TestFullyValidStructuralInputs(unittest.TestCase):
    def test_all_areas_structurally_integrated_but_not_activated_or_executable(self):
        result = validate(structural())
        self.assertEqual(list(result), TOP_KEYS)
        self.assertIs(result["available"], True)
        self.assertEqual(result["status"], "structurally_integrated")
        self.assertIs(result["structurally_integrated"], True)
        self.assertIs(result["runtime_connected"], True)
        self.assertIs(result["execution_capable"], False)
        self.assertIs(result["descriptive_only"], True)
        self.assertEqual(result["structurally_integrated_areas"], list(AREAS))
        self.assertEqual(result["activated_areas"], [])
        self.assertEqual(result["execution_capable_areas"], [])
        self.assertEqual(list(result["areas"]), list(AREAS))
        for name in AREAS:
            area = result["areas"][name]
            self.assertEqual(list(area), AREA_KEYS)
            self.assertEqual(area["status"], "structurally_integrated")
            self.assertEqual(area["reason"], "connected_not_activated")
            self.assertEqual((area["exists"], area["connected_to_runtime_core"]), (True, True))
            self.assertEqual((area["activated_in_runtime_path"], area["execution_capable"]),
                             (False, False))
            self.assertIs(area["descriptive_only"], True)
        json.dumps(result)

    def test_existing_and_connected_never_implies_activated_or_executable(self):
        for name in AREAS:
            area = validate(structural())["areas"][name]
            self.assertFalse(area["activated_in_runtime_path"], name)
            self.assertFalse(area["execution_capable"], name)

    def test_activated_and_executable_only_when_the_evidence_says_so(self):
        evidence = structural()
        evidence["local_model_runtime"] = ev(activated=True, capable=True)
        evidence["memory_runtime"] = ev(activated=True, capable=True)
        evidence["capability_runtime"] = ev(activated=True)
        result = validate(evidence)
        self.assertEqual(result["activated_areas"],
                         ["local_model_runtime", "memory_runtime", "capability_runtime"])
        self.assertEqual(result["execution_capable_areas"],
                         ["local_model_runtime", "memory_runtime"])
        area = result["areas"]["local_model_runtime"]
        self.assertEqual(area["reason"], "execution_capable_in_runtime_path")
        self.assertIs(area["descriptive_only"], False)
        self.assertEqual(result["areas"]["capability_runtime"]["reason"],
                         "activated_not_execution_capable")
        self.assertIs(result["areas"]["capability_runtime"]["descriptive_only"], True)
        # areas with no executor keep the overall verdict from claiming execution
        self.assertIs(result["execution_capable"], False)

    def test_overall_execution_capable_needs_every_area(self):
        evidence = {name: ev(activated=True, capable=True) for name in AREAS}
        result = validate(evidence)
        # the three non-executable areas turn this into contradictory evidence
        self.assertIs(result["execution_capable"], False)
        for name in ("controlled_reasoning_integration", "capability_runtime", "upgrade_runtime"):
            self.assertEqual(result["areas"][name]["reason"], "contradictory_evidence")

    def test_actionable_and_executed_always_false(self):
        for evidence in (structural(), None, {}, {n: ev(True, False) for n in AREAS}):
            result = validate(evidence)
            self.assertIs(result["actionable"], False)
            self.assertIs(result["executed"], False)
            self.assertIs(result["descriptive_only"], True)

    def test_extra_keys_are_ignored(self):
        evidence = structural()
        evidence["unrelated"] = ev(False, False)
        evidence["memory_runtime"]["note"] = "ignored"
        self.assertEqual(validate(evidence), validate(structural()))


class TestPartiallyIntegratedInputs(unittest.TestCase):
    def test_exists_but_not_connected_is_partial(self):
        evidence = structural()
        evidence["upgrade_runtime"] = ev(exists=True, connected=False)
        result = validate(evidence)
        area = result["areas"]["upgrade_runtime"]
        self.assertEqual(area["status"], "partially_integrated")
        self.assertEqual(area["reason"], "exists_not_connected_to_runtime_core")
        self.assertEqual(result["status"], "partially_integrated")
        self.assertIs(result["structurally_integrated"], False)
        self.assertIs(result["runtime_connected"], False)
        self.assertNotIn("upgrade_runtime", result["structurally_integrated_areas"])

    def test_one_missing_architecture_among_integrated_areas_is_partial(self):
        evidence = structural()
        evidence["android_runtime_bridge"] = ev(exists=False, connected=False)
        result = validate(evidence)
        self.assertEqual(result["areas"]["android_runtime_bridge"]["status"], "not_integrated")
        self.assertEqual(result["areas"]["android_runtime_bridge"]["reason"], "not_present")
        self.assertEqual(result["status"], "partially_integrated")
        self.assertIs(result["available"], True)

    def test_every_area_absent_is_not_integrated_but_still_available(self):
        result = validate({name: ev(False, False) for name in AREAS})
        self.assertIs(result["available"], True)
        self.assertEqual(result["status"], "not_integrated")
        self.assertEqual(result["structurally_integrated_areas"], [])

    def test_every_area_not_connected_is_partial_overall(self):
        result = validate({name: ev(True, False) for name in AREAS})
        self.assertEqual(result["status"], "partially_integrated")
        self.assertIs(result["runtime_connected"], False)


class TestMissingInputs(unittest.TestCase):
    def test_unusable_inputs_return_the_exact_safe_state(self):
        for bad in (None, "x", 1, 1.5, True, [], (), set(), object(), {}, [ev()], ("a",)):
            self.assertEqual(validate(bad), safe_state(), repr(bad))
        self.assertEqual(validate(), safe_state())

    def test_missing_area_is_reported_missing_while_others_are_evaluated(self):
        evidence = structural()
        del evidence["memory_runtime"]
        result = validate(evidence)
        self.assertEqual(result["areas"]["memory_runtime"]["reason"], "missing_evidence")
        self.assertEqual(result["areas"]["memory_runtime"]["status"], "not_integrated")
        self.assertEqual(result["areas"]["local_model_runtime"]["status"],
                         "structurally_integrated")
        self.assertEqual(result["status"], "partially_integrated")
        self.assertIs(result["structurally_integrated"], False)

    def test_malformed_area_evidence_is_never_trusted(self):
        for bad in (None, "x", 1, [], True, {}, {"exists": True},
                    {"exists": 1, "connected_to_runtime_core": True,
                     "activated_in_runtime_path": False, "execution_capable": False},
                    {"exists": "True", "connected_to_runtime_core": True,
                     "activated_in_runtime_path": False, "execution_capable": False},
                    {"exists": True, "connected_to_runtime_core": None,
                     "activated_in_runtime_path": False, "execution_capable": False}):
            evidence = structural()
            evidence["capability_runtime"] = bad
            area = validate(evidence)["areas"]["capability_runtime"]
            self.assertEqual(area["status"], "not_integrated", repr(bad))
            self.assertIn(area["reason"], ("missing_evidence", "malformed_evidence"))
            self.assertEqual((area["exists"], area["connected_to_runtime_core"],
                              area["activated_in_runtime_path"], area["execution_capable"]),
                             (False, False, False, False))

    def test_all_areas_malformed_is_the_safe_state(self):
        self.assertEqual(validate({name: "bad" for name in AREAS}), safe_state())

    def test_evidence_that_raises_when_read_is_the_safe_state(self):
        class Boom(dict):
            def get(self, *args, **kwargs):
                raise RuntimeError("boom")

        self.assertEqual(validate(Boom(structural())), safe_state())


class TestContradictoryInputs(unittest.TestCase):
    def assert_contradictory(self, name, evidence_for_area):
        evidence = structural()
        evidence[name] = evidence_for_area
        result = validate(evidence)
        area = result["areas"][name]
        self.assertEqual((area["status"], area["reason"]),
                         ("not_integrated", "contradictory_evidence"), (name, evidence_for_area))
        self.assertEqual((area["exists"], area["connected_to_runtime_core"],
                          area["activated_in_runtime_path"], area["execution_capable"]),
                         (False, False, False, False))
        self.assertIs(area["descriptive_only"], True)
        self.assertNotIn(name, result["activated_areas"])
        self.assertNotIn(name, result["execution_capable_areas"])
        self.assertIs(result["structurally_integrated"], False)

    def test_connected_without_existing(self):
        self.assert_contradictory("memory_runtime", ev(exists=False, connected=True))

    def test_activated_without_connected(self):
        self.assert_contradictory("memory_runtime", ev(connected=False, activated=True))

    def test_activated_without_existing(self):
        self.assert_contradictory("memory_runtime",
                                  ev(exists=False, connected=False, activated=True))

    def test_execution_capable_without_activated(self):
        self.assert_contradictory("local_model_runtime", ev(activated=False, capable=True))

    def test_execution_capable_without_connected(self):
        self.assert_contradictory("local_model_runtime",
                                  ev(connected=False, activated=True, capable=True))

    def test_areas_without_an_executor_can_never_be_execution_capable(self):
        for name in ("controlled_reasoning_integration", "capability_runtime", "upgrade_runtime"):
            self.assert_contradictory(name, ev(activated=True, capable=True))

    def test_contradiction_does_not_poison_the_other_areas(self):
        evidence = structural()
        evidence["upgrade_runtime"] = ev(exists=False, connected=True)
        result = validate(evidence)
        for name in AREAS:
            if name != "upgrade_runtime":
                self.assertEqual(result["areas"][name]["status"], "structurally_integrated")
        self.assertIs(result["available"], True)
        self.assertEqual(result["status"], "partially_integrated")


class TestMutationSafety(unittest.TestCase):
    def test_input_is_never_mutated(self):
        for evidence in (structural(),
                         {**structural(), "memory_runtime": ev(False, True),
                          "local_model_runtime": "bad"},
                         {name: ev(activated=True, capable=True) for name in AREAS}):
            before = copy.deepcopy(evidence)
            validate(evidence)
            self.assertEqual(evidence, before)

    def test_result_is_fresh_and_independent_of_the_input_and_earlier_results(self):
        evidence = structural()
        first = validate(evidence)
        first["areas"]["memory_runtime"]["exists"] = False
        first["activated_areas"].append("x")
        first["status"] = "changed"
        second = validate(evidence)
        self.assertIsNot(first, second)
        self.assertEqual(second, validate(structural()))
        self.assertIsNot(second["areas"]["memory_runtime"], first["areas"]["memory_runtime"])
        # mutating the input afterwards does not change an earlier result
        evidence["memory_runtime"]["exists"] = False
        self.assertEqual(second, validate(structural()))

    def test_safe_state_is_fresh_every_call(self):
        first = validate(None)
        first["areas"]["memory_runtime"]["exists"] = True
        first["activated_areas"].append("x")
        self.assertEqual(validate(None), safe_state())

    def test_deterministic(self):
        evidence = {**structural(), "local_model_runtime": ev(activated=True, capable=True)}
        self.assertEqual(validate(evidence), validate(copy.deepcopy(evidence)))
        self.assertEqual(json.dumps(validate(evidence)), json.dumps(validate(evidence)))


class TestNoExecutionSideEffects(unittest.TestCase):
    def test_helper_source_has_no_io_execution_or_network(self):
        with open(BRIDGE_PATH, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        names = {"final_runtime_integration_boundary_validation", "_boundary_classify_area",
                 "_boundary_result", "_boundary_safe_state", "_boundary_area_result"}
        found = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        self.assertEqual({n.name for n in found}, names)
        forbidden = {"open", "exec", "eval", "compile", "__import__", "input", "print",
                     "setattr", "delattr", "getattr", "system", "popen", "run", "connect",
                     "urlopen", "write", "remove", "unlink", "rename"}
        for node in found:
            for sub in ast.walk(node):
                if isinstance(sub, (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)):
                    self.fail("%s must not import or use globals" % node.name)
                if isinstance(sub, ast.Call):
                    callee = sub.func
                    label = callee.id if isinstance(callee, ast.Name) else (
                        callee.attr if isinstance(callee, ast.Attribute) else None)
                    self.assertNotIn(label, forbidden, "%s calls %s" % (node.name, label))

    def test_nothing_runs_when_the_input_holds_callables(self):
        trap = mock.Mock(side_effect=AssertionError("must never be called"))
        evidence = structural()
        evidence["memory_runtime"]["trap"] = trap
        evidence["upgrade_runtime"] = {**ev(), "run": trap}
        validate(evidence)
        trap.assert_not_called()


class RuntimeCoreCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def new_core(self, cls=RuntimeCore, name="core"):
        base = os.path.join(self._tmp.name, name)
        os.makedirs(base, exist_ok=True)
        return cls(memory_db_path=os.path.join(base, "m.sqlite3"),
                   skill_definitions_dir=os.path.join(base, "skills"))


class TestRuntimeCoreObservationField(RuntimeCoreCase):
    def test_none_before_the_first_message_and_stored_after_a_turn(self):
        core = self.new_core()
        self.assertIsNone(core.get_last_final_runtime_integration_boundary_validation())
        core.process_input("hello")
        result = core.get_last_final_runtime_integration_boundary_validation()
        self.assertEqual(list(result), TOP_KEYS)
        self.assertEqual(list(result["areas"]), list(AREAS))
        json.dumps(result)

    def test_real_runtime_reports_structural_integration_without_false_execution(self):
        core = self.new_core()
        core.process_input("hello")
        result = core.get_last_final_runtime_integration_boundary_validation()
        self.assertIs(result["available"], True)
        self.assertEqual(result["status"], "structurally_integrated")
        self.assertIs(result["runtime_connected"], True)
        self.assertIs(result["execution_capable"], False)
        # default Core: deterministic backend, no model, nothing executable observed
        local = result["areas"]["local_model_runtime"]
        self.assertEqual((local["activated_in_runtime_path"], local["execution_capable"]),
                         (False, False))
        for name in ("controlled_reasoning_integration", "capability_runtime", "upgrade_runtime"):
            self.assertIs(result["areas"][name]["execution_capable"], False, name)
        self.assertIs(result["areas"]["upgrade_runtime"]["activated_in_runtime_path"], False)
        self.assertIs(result["areas"]["android_runtime_bridge"]["exists"], True)
        self.assertIs(result["areas"]["android_runtime_bridge"]["connected_to_runtime_core"], True)
        # the Android server is not started by a test
        self.assertIs(result["areas"]["android_runtime_bridge"]["activated_in_runtime_path"], False)

    def test_memory_area_follows_what_the_bridge_observed(self):
        core = self.new_core()
        core.process_input("hello")
        first = core.get_last_final_runtime_integration_boundary_validation()
        self.assertIs(first["areas"]["memory_runtime"]["activated_in_runtime_path"], False)
        core.process_input("hello again")
        second = core.get_last_final_runtime_integration_boundary_validation()
        self.assertIs(second["areas"]["memory_runtime"]["activated_in_runtime_path"], True)
        self.assertIs(second["areas"]["memory_runtime"]["execution_capable"], True)

    def test_ael_area_is_execution_capable_only_when_learning_really_ran(self):
        core = self.new_core()
        core.process_input("hello")
        idle = core.get_last_final_runtime_integration_boundary_validation()
        self.assertIs(idle["areas"]["AEL_learning_runtime"]["activated_in_runtime_path"], False)
        core.process_input("TEACH sun IS a star at the center of the solar system")
        ael = core.get_last_final_runtime_integration_boundary_validation()["areas"][
            "AEL_learning_runtime"]
        self.assertEqual((ael["activated_in_runtime_path"], ael["execution_capable"]),
                         (True, True))

    def test_upgrade_statement_does_not_make_the_upgrade_area_active_or_executable(self):
        core = self.new_core()
        core.process_input("UPGRADE demo IS a harmless demo upgrade description")
        area = core.get_last_final_runtime_integration_boundary_validation()["areas"][
            "upgrade_runtime"]
        self.assertEqual(area["status"], "structurally_integrated")
        self.assertEqual((area["activated_in_runtime_path"], area["execution_capable"]),
                         (False, False))

    def test_getter_returns_independent_copies(self):
        core = self.new_core()
        core.process_input("hello")
        first = core.get_last_final_runtime_integration_boundary_validation()
        expected = copy.deepcopy(first)
        first["areas"]["memory_runtime"]["exists"] = "tampered"
        first["activated_areas"].append("x")
        second = core.get_last_final_runtime_integration_boundary_validation()
        self.assertEqual(second, expected)
        self.assertIsNot(second, first)
        self.assertIsNot(second["areas"], core.get_last_final_runtime_integration_boundary_validation()["areas"])

    def test_cleared_at_the_start_of_every_turn_and_when_core_raises(self):
        core = self.new_core()
        core.process_input("hello")
        self.assertIsNotNone(core.get_last_final_runtime_integration_boundary_validation())
        with mock.patch.object(Core, "process_input", side_effect=RuntimeError("core failed")):
            with self.assertRaises(RuntimeError):
                core.process_input("hello")
        self.assertIsNone(core.get_last_final_runtime_integration_boundary_validation())

    def test_unusable_observation_leaves_the_field_none(self):
        core = self.new_core()
        for bad in (lambda e: 1 / 0, lambda e: ["not", "a", "dict"]):
            with mock.patch.object(ri, "final_runtime_integration_boundary_validation", bad):
                core.process_input("hello")
            self.assertIsNone(core.get_last_final_runtime_integration_boundary_validation())


class TestObservationOnlyBoundary(RuntimeCoreCase):
    def test_replies_are_identical_to_plain_core_and_to_a_failing_validation(self):
        inputs = ("hello", "من عرفان هستم", "What is Python?", "",
                  "TEACH sun IS a star", "ASK sun", "create a plan to learn python")
        plain, runtime, broken = (self.new_core(Core, "plain"), self.new_core(RuntimeCore, "rt"),
                                  self.new_core(RuntimeCore, "broken"))
        for text in inputs:
            expected = plain.process_input(text)
            self.assertEqual(runtime.process_input(text), expected, text)
            with mock.patch.object(ri, "final_runtime_integration_boundary_validation",
                                   side_effect=RuntimeError("boom")):
                self.assertEqual(broken.process_input(text), expected, text)
            self.assertIsNone(broken.get_last_final_runtime_integration_boundary_validation())

    def test_the_validation_is_never_read_by_process_input_or_other_results(self):
        core = self.new_core()
        with mock.patch.object(ri, "final_runtime_integration_boundary_validation",
                               side_effect=lambda e: {"available": True, "actionable": True,
                                                      "executed": True}):
            core.process_input("hello")
        # a result claiming action/execution is refused outright
        self.assertIsNone(core.get_last_final_runtime_integration_boundary_validation())
        baseline = self.new_core(name="baseline")
        baseline.process_input("hello")
        core.process_input("hello")
        keys = ("status", "route", "execution", "learning", "capability", "local_model")
        for key in keys:
            self.assertEqual(core.last_runtime_result[key], baseline.last_runtime_result[key], key)
        self.assertEqual(core.get_last_final_runtime_integration_checkpoint(),
                         baseline.get_last_final_runtime_integration_checkpoint())

    def test_collecting_evidence_executes_nothing(self):
        core = self.new_core()
        core.process_input("hello")
        boom = AssertionError("evidence collection must not run this")
        with mock.patch.object(core.ael, "run", side_effect=boom) as ael_run, \
                mock.patch.object(core.upgrades, "propose_upgrade", side_effect=boom) as up, \
                mock.patch.object(core.upgrades, "rollback", side_effect=boom) as rb, \
                mock.patch.object(core.learning, "teach", side_effect=boom) as teach, \
                mock.patch.object(core.learning, "relate", side_effect=boom) as relate, \
                mock.patch.object(core.capabilities, "set_enabled", side_effect=boom) as enable, \
                mock.patch.object(core.language_intelligence, "generate_response",
                                  side_effect=boom, create=True) as gen:
            core._runtime_boundary_evidence()
            core._store_final_runtime_integration_boundary_validation()
            core.get_last_final_runtime_integration_boundary_validation()
        for spy in (ael_run, up, rb, teach, relate, enable, gen):
            spy.assert_not_called()

    def test_storing_the_validation_changes_no_persistent_state(self):
        core = self.new_core()
        core.process_input("TEACH sun IS a star")
        before = (len(core.upgrades.history(100)), core.capabilities.all(),
                  len(core.context.get_recent_turns()))
        for _ in range(3):
            core._store_final_runtime_integration_boundary_validation()
        after = (len(core.upgrades.history(100)), core.capabilities.all(),
                 len(core.context.get_recent_turns()))
        self.assertEqual(before, after)


class TestLocalModelAreaWithDouble(GuardCase):
    """TEST DOUBLE ONLY (not a model): proves the area becomes activated and
    execution-capable only when a backend is really ready, and that producing the
    validation never runs it."""

    def make_core(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return RuntimeCore(memory_db_path=os.path.join(tmp.name, "m.sqlite3"),
                           skill_definitions_dir=os.path.join(tmp.name, "skills"))

    def test_ready_backend_is_activated_and_capable_and_never_invoked_by_the_validation(self):
        core = self.make_core()
        runtime = TextRuntime(self.config())
        core.use_local_language_model(runtime=runtime)
        core.process_input("hello")  # answered by a skill, not by the model
        area = core.get_last_final_runtime_integration_boundary_validation()["areas"][
            "local_model_runtime"]
        self.assertEqual((area["status"], area["activated_in_runtime_path"],
                          area["execution_capable"]), ("structurally_integrated", True, True))
        self.assertEqual((runtime.load_calls, runtime.generate_calls, runtime.inferences),
                         (0, 0, 0))
        core._store_final_runtime_integration_boundary_validation()
        self.assertEqual((runtime.load_calls, runtime.generate_calls, runtime.inferences),
                         (0, 0, 0))

    def test_unconfigured_backend_is_connected_but_not_activated(self):
        core = self.make_core()
        core.use_local_language_model()
        core.process_input(MESSAGE)
        area = core.get_last_final_runtime_integration_boundary_validation()["areas"][
            "local_model_runtime"]
        self.assertEqual((area["status"], area["activated_in_runtime_path"],
                          area["execution_capable"]), ("structurally_integrated", False, False))

    def test_reply_is_unchanged_by_the_validation(self):
        core = self.make_core()
        core.use_local_language_model(runtime=TextRuntime(self.config()))
        self.assertEqual(core.process_input(MESSAGE), MODEL_TEXT)


if __name__ == "__main__":
    unittest.main()
